"""
Production-grade Bollinger Bands + Z-Score Mean Reversion Strategy.
Fully compatible with Quant_firm BaseStrategy.

Compatibility notes vs BaseStrategy._validate()
------------------------------------------------
- action: only 'BUY' | 'SELL' | 'HOLD' are accepted; 'EXIT' is NOT in the
  base allowed set and would be silently normalised to 'HOLD'.
  Solution: EXIT intent is encoded as action='HOLD' + signal_type='BB_MEAN_REVERT'
  + reasoning prefixed with '[EXIT]'. Downstream consumers that want to act on
  exits should check signal_type == 'BB_MEAN_REVERT'.

- confidence: base accepts 0.0-1.0 (values > 1.0 are divided by 100).
  This strategy always stays in [0.55, 0.88] so no normalisation fires.

- current_price: base clamps to >= 0.0 and rounds to 4dp. Compatible.

- extra fields (stop_loss, take_profit, diagnostics): base leaves unknown
  fields untouched. Compatible.

- source field: base appends source = strategy if absent. Compatible.
"""

from datetime import datetime , timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional

import numpy as np
import pandas as pd

from logger import get_logger
from strategies.base_strategy import BaseStrategy

log = get_logger("strategies.mean_reversion")


# ── Constants ────────────────────────────────────────────────────────────────

#Minimum number of days of data needed before generating any signal 
MIN_ROWS            = 60
# n days used to cal moving average and standard deviation for Bollinger Bands
BB_WINDOW           = 20
# How many standard deviations to draw the upper and lower bands
BB_NUM_STD          = 2.0
# Minimum Z-Score needed to trigger a BUY or SELL signal (price must be 1.5 standard deviations from average)
Z_ENTRY_THRESHOLD   = 1.5
# Z-Score at which confidence starts getting an extra boost (very strong signal)
Z_STRONG_THRESHOLD  = 2.2
#If ADX is above 25, market is trending and mean reversion trades are blocked
ADX_TREND_THRESHOLD = 25.0
# Number of days used to calculate ADX
ADX_PERIOD          = 14
# If Bollinger Bands expand by 3% or more in one day, block trades (breakout starting)
BAND_WIDTH_EXPAND   = 0.03
#Number of days (approximately 10 weeks) to calculate the long-term moving average trend
WEEKLY_WINDOW       = 50
# Stop loss is placed 1.5 times the ATR away from entry price
STOP_LOSS_ATR_MULT  = 1.5
#Take profit is placed 3.0 times the ATR away from entry price (2:1 reward-to-risk ratio)
TP_ATR_MULT         = 3.0
#Number of days used to calculate Average True Range (volatility)
ATR_PERIOD          = 14
#Volume is considered "quiet" if it's below the 40th percentile of recent volume (bottom 40% of days)
VOLUME_CONFIRM_PCTL = 40
# Minimum confidence score
CONFIDENCE_BASE     = 0.55
# No trading signal, price is between bands (do nothing)
SIG_NEUTRAL     = "BB_NEUTRAL"
# - BUY signal triggered (price below lower band, very negative Z-Score)
SIG_OVERSOLD    = "BB_OVERSOLD"
# SELL signal triggered (price above upper band, very positive Z-Score)
SIG_OVERBOUGHT  = "BB_OVERBOUGHT"
# EXIT signal (Z-Score crossed zero, price returned to average)
SIG_MEAN_REVERT = "BB_MEAN_REVERT"   # EXIT intent — action is always HOLD
# "NO_SIGNAL"
SIG_NO_SIGNAL   = "NO_SIGNAL"

# Decimal precision used for all intermediate financial calculations.
_DECIMAL_PLACES = Decimal("0.0000000001")


# ── Module-level helpers ─────────────────────────────────────────────────────

def _to_dec(val) -> Optional[Decimal]:
    """
    Safely convert a single value to Decimal.

    Why str(val) and not Decimal(val) directly?
      Decimal(0.1) inherits the float representation error → 0.1000000000000000055...
      Decimal("0.1") is exact → 0.1

    Returns None for NaN / None / unconvertible values so callers can
    skip those rows without crashing.
    """
    if val is None:
        return None
    try:
        if isinstance(val, float) and np.isnan(val):
            return None
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _compute_adx(high: pd.Series,low: pd.Series,close: pd.Series,period: int = 14,) -> pd.Series:
    """
    Compute the Average Directional Index (ADX) using Wilder EWM smoothing.

    ADX measures trend STRENGTH (not direction) on a scale of 0–100.
      ADX < 25  → market ranging   → mean reversion is SAFE   ✅
      ADX >= 25 → market trending  → mean reversion is RISKY  ❌

    How it is built:
      BLOCK 1 — True Range (TR): real daily move including overnight gaps
      BLOCK 2 — +DM / -DM: which direction dominated today
      BLOCK 3 — Wilder-smooth everything → +DI, -DI, DX → final ADX

    Parameters
    ----------
    high   : daily high prices
    low    : daily low prices
    close  : daily close prices
    period : Wilder smoothing window (default 14)

    Price → Movement → Direction → Strength → Smoothed Strength
    TR → +DM / -DM → smoothing → +DI / -DI  % → DX → ADX

    Returns
    -------
    pd.Series of ADX values aligned to close.index.
    Returns an all-NaN Series on unrecoverable error.
    """

    for name, s in [("high", high), ("low", low), ("close", close)]:
        if not isinstance(s, pd.Series):
            log.error(
                "_compute_adx | invalid type | param=%s | expected=pd.Series | got=%s",
                name, type(s).__name__,
            )
            return pd.Series(dtype=float)

    if not (len(high) == len(low) == len(close)):
        log.error(
            "_compute_adx | length mismatch | high=%d | low=%d | close=%d",
            len(high), len(low), len(close),
        )
        return pd.Series(dtype=float)

    if not isinstance(period, int) or period < 1:
        log.error(
            "_compute_adx | invalid period | period=%s | must be positive int", period
        )
        return pd.Series(dtype=float)

    min_rows = period * 2
    if len(close) < min_rows:
        log.warning(
            "_compute_adx | insufficient rows | rows=%d | minimum=%d | "
            "ADX will be mostly NaN",
            len(close), min_rows,
        )

    for name, s in [("high", high), ("low", low), ("close", close)]:
        nan_count = int(s.isna().sum())
        if nan_count:
            log.warning(
                "_compute_adx | NaN detected | column=%s | count=%d | "
                "ADX reliability may be reduced",
                name, nan_count,
            )

    log.debug(
        "_compute_adx | starting | rows=%d | period=%d", len(close), period
    )

    try:

        # decimal for calculation
        high_d  = high.apply(_to_dec)
        low_d   = low.apply(_to_dec)
        close_d = close.apply(_to_dec)

        log.debug("_compute_adx | Decimal conversion done")
        """
         — True Range ──
             shift(1) slides close DOWN one row so yesterday's close sits
            next to today's row — no need to look at a different index.
        """
        prev_close_d = close_d.shift(1)
        tr_values: list = []
        """
         tr : Measures the TRUE daily movement including overnight gaps.
         How much did price move in THIS one period? or
         What is the biggest distance price actually traveled
        """
        for idx in range(len(close)):
            h  = high_d.iloc[idx]
            l  = low_d.iloc[idx]
            pc = prev_close_d.iloc[idx]

            if h is None or l is None:
                log.warning(
                    "_compute_adx | TR | row=%d | None in high/low | NaN appended", idx
                )
                tr_values.append(np.nan)
                continue

            #   opt1 = high - low           → today's full candle
            opt1 = h - l

            if pc is None:
                # First row — no yesterday exists, only opt1 available
                log.debug(
                    "_compute_adx | TR | row=%d | no prev_close | tr=%s", idx, opt1
                )
                tr_values.append(float(opt1))
                continue

            #   opt2 = |high - prev_close|  → catches gap UP overnight
            opt2 = abs(h - pc)
            #   opt3 = |low  - prev_close|  → catches gap DOWN overnight
            opt3 = abs(l - pc)
            """
             TR = max of three options:
             We take max or the biggest value cuz it's what actually affected the market .
            """
            tr   = max(opt1, opt2, opt3)

            log.debug(
                "_compute_adx | TR | row=%d | opt1=%s | opt2=%s | opt3=%s | TR=%s",
                idx, opt1, opt2, opt3, tr,
            )
            tr_values.append(float(tr))

        tr = pd.Series(tr_values, index=close.index, dtype=float)

        log.debug(
            "_compute_adx | TR done | sample(last3)=%s", tr.tail(3).to_dict()
        )

        plus_dm_vals:  list = []
        minus_dm_vals: list = []
        _zero = Decimal("0")

        # Determines which direction pushed harder today - up or down.
        for idx in range(len(close)):

            if idx == 0:
                # No yesterday on first row
                plus_dm_vals.append(0.0)
                minus_dm_vals.append(0.0)
                continue

            h_now  = high_d.iloc[idx]
            h_prev = high_d.iloc[idx - 1]
            l_now  = low_d.iloc[idx]
            l_prev = low_d.iloc[idx - 1]

            if any(v is None for v in (h_now, h_prev, l_now, l_prev)):
                log.warning(
                    "_compute_adx | DM | row=%d | None value → (0, 0)", idx
                )
                plus_dm_vals.append(0.0)
                minus_dm_vals.append(0.0)
                continue
            """
              Directional Movement (+DM / -DM)
            
             up_move   = today_high - yesterday_high  (did ceiling rise?)
             down_move = yesterday_low - today_low    (did floor drop?)
            
            """

            up_move   = h_now  - h_prev
            down_move = l_prev - l_now
            """
             Rules (only ONE wins per row):
               up_move > down_move AND up_move > 0  → +DM = up_move, -DM = 0
               down_move > up_move AND down_move > 0 → -DM = down_move, +DM = 0
               otherwise                              → both = 0
            """
            if up_move > down_move and up_move > _zero:
                plus_dm_vals.append(float(up_move))
                minus_dm_vals.append(0.0)
            elif down_move > up_move and down_move > _zero:
                plus_dm_vals.append(0.0)
                minus_dm_vals.append(float(down_move))
            else:
                plus_dm_vals.append(0.0)
                minus_dm_vals.append(0.0)

            log.debug(
                "_compute_adx | DM | row=%d | up=%s | dn=%s | +DM=%s | -DM=%s",
                idx, up_move, down_move,
                plus_dm_vals[-1], minus_dm_vals[-1],
            )

        plus_dm  = pd.Series(plus_dm_vals,  index=close.index, dtype=float)
        minus_dm = pd.Series(minus_dm_vals, index=close.index, dtype=float)

        log.debug(
            "_compute_adx | DM done | +DM(last3)=%s | -DM(last3)=%s",
            plus_dm.tail(3).to_dict(), minus_dm.tail(3).to_dict(),
        )
        """
         — Wilder EWM smoothing ─ Exponentially Weighted Moving
         alpha = 1 / period  (e.g. 1/14 ≈ 0.071)
        
         Each smoothed value:
           smoothed = alpha × today_raw + (1 - alpha) × yesterday_smoothed
        
        Reduces noise:
            We smooth TR and ±DM to filter out random spikes so ADX
            reflects consistent directional movement, not noisy one-day jumps
            smooth, stable series that reflects persistent movement, not short-term noise
        """
        alpha  = 1 / period
        wilder = dict(alpha=alpha, adjust=False)

        log.debug("_compute_adx | Wilder alpha=%.6f | period=%d", alpha, period)

        """
        tr.ewm(**wilder) → creates an ExponentialMovingWindow object in memory.
        .mean() → loops internally over tr, calculates smoothed values recursively.
        The result is a new pandas Series → assigned to smooth_tr.
        """
        smooth_tr       = tr.ewm(**wilder).mean()
        smooth_plus_dm  = plus_dm.ewm(**wilder).mean()
        smooth_minus_dm = minus_dm.ewm(**wilder).mean()

        log.debug(
            "_compute_adx | smooth_tr(last3)=%s", smooth_tr.tail(3).to_dict()
        )
        """
         — +DI and -DI ──
        
         Convert smoothed DM into percentage of total smoothed range.
        
           +DI = 100 × smooth_plus_dm  / smooth_tr
           -DI = 100 × smooth_minus_dm / smooth_tr

          --> We divide by smooth_tr to normalize directional movement, 
           so +DI and -DI show how strong up/down moves are relative to
            total volatility or true range not just their raw size
        """

        smooth_tr_safe = smooth_tr.replace(0, np.nan)

        plus_di  = 100 * smooth_plus_dm  / smooth_tr_safe
        minus_di = 100 * smooth_minus_dm / smooth_tr_safe

        log.debug(
            "_compute_adx | +DI(last3)=%s | -DI(last3)=%s",
            plus_di.tail(3).to_dict(), minus_di.tail(3).to_dict(),
        )
        """
          — DX ─
         Measures the GAP between up and down movement.
         How different are +DI and -DI and what direction is dominant?
         DX condenses +DI and -DI into a single number showing trend strength:

        • High DX → one direction clearly dominates → tells you "trend is strong"
        • Low DX  → moves are balanced → tells you "market is ranging / choppy"

        • Mean-reversion strategies → safer when DX low

            DX turns two noisy directional measures into one clear signal of trend strength
        
           DX = 100 × |+DI - -DI| / |+DI + -DI|
        """
        di_diff = (plus_di - minus_di).abs()
        di_sum  = (plus_di + minus_di).abs().replace(0, np.nan)
        # combine +DI and -DI into ONE number that tells you "how different are they?" 
        dx      = 100 * di_diff / di_sum

        log.debug("_compute_adx | DX(last3)=%s", dx.tail(3).to_dict())
        """
        — Final ADX ──
        We take the DX series (directional dominance) and smooth it using EWM.

        Why?
        • One day of high DX is just a spike → might be noise
        • Only several consecutive days of high DX indicate a true trend
        
         14+ consecutive days of high DX → confirmed trend.
        """
        adx = dx.ewm(**wilder).mean()


        valid_count = int(adx.notna().sum())
        nan_count   = int(adx.isna().sum())
        latest_adx  = float(adx.dropna().iloc[-1]) if valid_count > 0 else float("nan")

        log.info(
            "_compute_adx | done | rows=%d | valid=%d | nan=%d | latest_adx=%.4f",
            len(adx), valid_count, nan_count, latest_adx,
        )

        return adx

    except Exception as exc:
        log.exception(
            "_compute_adx | unexpected error | error=%s | returning NaN Series", exc
        )
        return pd.Series(np.nan, index=close.index, dtype=float)


def _compute_atr(high: pd.Series,low: pd.Series,close: pd.Series,period: int = 14,) -> pd.Series:
    """
    Compute the Average True Range (ATR) using Wilder EWM smoothing.

    ATR answers: "How many dollars does this stock move per day on average?"
    It is used to size stop-loss and take-profit distances dynamically.

      stop_loss   = price - (ATR × stop_atr_mult)
      take_profit = price + (ATR × tp_atr_mult)

    ATR is simpler than ADX — same True Range logic, same Wilder smoothing,
    but NO directional movement (+DM/-DM), NO +DI/-DI, NO DX.
    Just: TR → smooth(TR) → ATR.

    Parameters
    ----------
    high   : daily high prices
    low    : daily low prices
    close  : daily close prices
    period : Wilder smoothing window (default 14)

    Returns
    -------
    pd.Series of ATR values aligned to close.index.
    Returns an all-NaN Series on unrecoverable error.
    """

    for name, s in [("high", high), ("low", low), ("close", close)]:
        if not isinstance(s, pd.Series):
            log.error(
                "_compute_atr | invalid type | param=%s | expected=pd.Series | got=%s",
                name, type(s).__name__,
            )
            return pd.Series(dtype=float)

    if not (len(high) == len(low) == len(close)):
        log.error(
            "_compute_atr | length mismatch | high=%d | low=%d | close=%d",
            len(high), len(low), len(close),
        )
        return pd.Series(dtype=float)

    if not isinstance(period, int) or period < 1:
        log.error(
            "_compute_atr | invalid period | period=%s | must be positive int", period
        )
        return pd.Series(dtype=float)

    min_rows = period * 2
    if len(close) < min_rows:
        log.warning(
            "_compute_atr | insufficient rows | rows=%d | minimum=%d | "
            "ATR will be mostly NaN",
            len(close), min_rows,
        )

    for name, s in [("high", high), ("low", low), ("close", close)]:
        nan_count = int(s.isna().sum())
        if nan_count:
            log.warning(
                "_compute_atr | NaN detected | column=%s | count=%d | "
                "ATR reliability may be reduced",
                name, nan_count,
            )

    log.debug(
        "_compute_atr | starting | rows=%d | period=%d", len(close), period
    )

    try:

        high_d  = high.apply(_to_dec)
        low_d   = low.apply(_to_dec)
        close_d = close.apply(_to_dec)

        log.debug("_compute_atr | Decimal conversion done")

        prev_close_d = close_d.shift(1)
        tr_values: list = []

        for idx in range(len(close)):
            h  = high_d.iloc[idx]
            l  = low_d.iloc[idx]
            pc = prev_close_d.iloc[idx]

            if h is None or l is None:
                log.warning(
                    "_compute_atr | TR | row=%d | None in high/low | NaN appended", idx
                )
                tr_values.append(np.nan)
                continue

            opt1 = h - l

            if pc is None:
                log.debug(
                    "_compute_atr | TR | row=%d | no prev_close | tr=%s", idx, opt1
                )
                tr_values.append(float(opt1))
                continue

            opt2 = abs(h - pc)
            opt3 = abs(l - pc)
            tr   = max(opt1, opt2, opt3)

            log.debug(
                "_compute_atr | TR | row=%d | opt1=%s | opt2=%s | opt3=%s | TR=%s",
                idx, opt1, opt2, opt3, tr,
            )
            tr_values.append(float(tr))

        tr = pd.Series(tr_values, index=close.index, dtype=float)

        log.debug(
            "_compute_atr | TR done | sample(last3)=%s", tr.tail(3).to_dict()
        )

        """
        --> ATR = smoothed average of TR values.
         This is the ONLY step that differs from ADX.
         No directions needed — ATR only cares about SIZE of moves.
        """

        alpha  = 1 / period
        wilder = dict(alpha=alpha, adjust=False)

        log.debug("_compute_atr | Wilder alpha=%.6f | period=%d", alpha, period)

        atr = tr.ewm(**wilder).mean()

        valid_count = int(atr.notna().sum())
        nan_count   = int(atr.isna().sum())
        latest_atr  = float(atr.dropna().iloc[-1]) if valid_count > 0 else float("nan")

        log.info(
            "_compute_atr | done | rows=%d | valid=%d | nan=%d | latest_atr=%.4f",
            len(atr), valid_count, nan_count, latest_atr,
        )

        return atr

    except Exception as exc:
        log.exception(
            "_compute_atr | unexpected error | error=%s | returning NaN Series", exc
        )
        return pd.Series(np.nan, index=close.index, dtype=float)


# ── Strategy class ────────────────────────────────────────────────────────────

class MeanReversionStrategy(BaseStrategy):
    """
    Production Bollinger Band + Z-Score mean reversion strategy.

    Signal lifecycle
    ----------------
    BUY   signal_type=BB_OVERSOLD    price <= lower band, Z <= -z_entry, all filters pass
    SELL  signal_type=BB_OVERBOUGHT  price >= upper band, Z >= +z_entry, all filters pass
    HOLD  signal_type=BB_MEAN_REVERT EXIT intent: Z crossed zero → reversion complete
    HOLD  signal_type=BB_NEUTRAL     no entry condition met
    HOLD  signal_type=NO_SIGNAL      bad or insufficient input data

    BaseStrategy compatibility
    --------------------------
    action is always BUY | SELL | HOLD (EXIT intent encoded in signal_type).
    Extra keys (stop_loss, take_profit, diagnostics) pass through untouched.
    """

    name = "Bollinger Mean Reversion (Production)"

    def __init__(
        self,
        window: int = BB_WINDOW,
        num_std: float = BB_NUM_STD,
        z_entry: float = Z_ENTRY_THRESHOLD,
        z_strong: float = Z_STRONG_THRESHOLD,
        adx_threshold: float = ADX_TREND_THRESHOLD,
        stop_atr_mult: float = STOP_LOSS_ATR_MULT,
        tp_atr_mult: float = TP_ATR_MULT,
        require_volume: bool = True,
        bw_expand_threshold: float = BAND_WIDTH_EXPAND,
        use_weekly_filter: bool = True,
    ) -> None:
        """
        Store all tunable hyperparameters as instance attributes.

        Every parameter has a module-level constant as its default so the
        singleton at the bottom of the file uses the standard values, while
        tests can override individual parameters cleanly.

        Parameters
        ----------
        window              : Bollinger Band rolling window (bars)
        num_std             : Standard deviations for band width
        z_entry             : |Z| threshold to allow entry
        z_strong            : |Z| threshold for confidence boost
        adx_threshold       : ADX above this → trending → block entry
        stop_atr_mult       : ATR multiplier for stop-loss distance
        tp_atr_mult         : ATR multiplier for take-profit distance
        require_volume      : Whether to enforce quiet-volume filter
        bw_expand_threshold : Band-width expansion rate that blocks entry
        use_weekly_filter   : Whether to enforce weekly trend alignment
        """

        if not isinstance(window, int) or window < 2:
            log.error(
                "__init__ | invalid window=%s | must be int >= 2 | "
                "falling back to default=%d",
                window, BB_WINDOW,
            )
            window = BB_WINDOW

        try:
            num_std = float(num_std)
            if num_std <= 0:
                raise ValueError("non-positive")
        except (TypeError, ValueError):
            log.error(
                "__init__ | invalid num_std=%s | must be float > 0 | "
                "falling back to default=%.1f",
                num_std, BB_NUM_STD,
            )
            num_std = BB_NUM_STD

        try:
            z_entry  = float(z_entry)
            z_strong = float(z_strong)
            if z_entry <= 0 or z_strong <= 0:
                raise ValueError("non-positive")
            if z_entry >= z_strong:
                raise ValueError("z_entry must be < z_strong")
        except (TypeError, ValueError) as exc:
            log.error(
                "__init__ | invalid z thresholds | z_entry=%s | z_strong=%s | "
                "error=%s | falling back to defaults",
                z_entry, z_strong, exc,
            )
            z_entry  = Z_ENTRY_THRESHOLD
            z_strong = Z_STRONG_THRESHOLD

        # ── Guard — adx_threshold ─────────────────────────────────────────
        try:
            adx_threshold = float(adx_threshold)
            if adx_threshold <= 0:
                raise ValueError("non-positive")
        except (TypeError, ValueError):
            log.error(
                "__init__ | invalid adx_threshold=%s | falling back to %.1f",
                adx_threshold, ADX_TREND_THRESHOLD,
            )
            adx_threshold = ADX_TREND_THRESHOLD

        # ── Guard — ATR multipliers ───────────────────────────────────────
        try:
            stop_atr_mult = float(stop_atr_mult)
            tp_atr_mult   = float(tp_atr_mult)
            if stop_atr_mult <= 0 or tp_atr_mult <= 0:
                raise ValueError("non-positive")
        except (TypeError, ValueError):
            log.error(
                "__init__ | invalid ATR multipliers | stop=%s | tp=%s | "
                "falling back to defaults",
                stop_atr_mult, tp_atr_mult,
            )
            stop_atr_mult = STOP_LOSS_ATR_MULT
            tp_atr_mult   = TP_ATR_MULT

        # ── Guard — bw_expand_threshold ────
        try:
            bw_expand_threshold = float(bw_expand_threshold)
            if bw_expand_threshold <= 0:
                raise ValueError("non-positive")
        except (TypeError, ValueError):
            log.error(
                "__init__ | invalid bw_expand_threshold=%s | falling back to %.4f",
                bw_expand_threshold, BAND_WIDTH_EXPAND,
            )
            bw_expand_threshold = BAND_WIDTH_EXPAND

        # ── Guard — booleans ─────────────────────────────────────────────
        if not isinstance(require_volume, bool):
            log.warning(
                "__init__ | require_volume is not bool | got=%s | coercing to bool",
                type(require_volume).__name__,
            )
            require_volume = bool(require_volume)

        if not isinstance(use_weekly_filter, bool):
            log.warning(
                "__init__ | use_weekly_filter is not bool | got=%s | coercing to bool",
                type(use_weekly_filter).__name__,
            )
            use_weekly_filter = bool(use_weekly_filter)

        # ── Storage ──────────────────────────────────────────────────────
        self.window              = window
        self.num_std             = num_std
        self.z_entry             = z_entry
        self.z_strong            = z_strong
        self.adx_threshold       = adx_threshold
        self.stop_atr_mult       = stop_atr_mult
        self.tp_atr_mult         = tp_atr_mult
        self.require_volume      = require_volume
        self.bw_expand_threshold = bw_expand_threshold
        self.use_weekly_filter   = use_weekly_filter

        log.info(
            "__init__ | MeanReversionStrategy ready | "
            "window=%d | num_std=%.1f | z_entry=%.2f | z_strong=%.2f | "
            "adx_threshold=%.1f | stop_mult=%.2f | tp_mult=%.2f | "
            "require_volume=%s | bw_expand=%.4f | weekly_filter=%s",
            self.window, self.num_std, self.z_entry, self.z_strong,
            self.adx_threshold, self.stop_atr_mult, self.tp_atr_mult,
            self.require_volume, self.bw_expand_threshold, self.use_weekly_filter,
        )

    # ── Public API ────────────────────────────────────────────────────────────
    def _validate_input(self, ticker: str, price_data: Optional[pd.DataFrame]) -> Optional[dict]:
        """
        Validate ticker and price_data before any processing.

        Returns a _no_signal() dict for any invalid condition,
        or None when the input is fully valid.

        Checks (in order)
        -----------------
        1. price_data is None
        2. price_data is not a DataFrame
        3. Required columns (Close, High, Low) missing
        4. Fewer than MIN_ROWS rows
        5. NaN values in Closing prices
        """
        # wash data frame khawya
        if price_data is None:
            log.warning("_validate_input | price_data is None | ticker=%s", ticker)
            return self._no_signal(ticker=ticker, reason="price_data is None")

        # wash dataframe dataframe hhhhh
        if not isinstance(price_data, pd.DataFrame):
            log.error(
                "_validate_input | not a DataFrame | ticker=%s | got=%s",
                ticker, type(price_data).__name__,
            )
            return self._no_signal(
                ticker=ticker,
                reason=f"price_data is not a DataFrame (got {type(price_data).__name__})",
            )

        required = {"Close", "High", "Low"}
        missing  = required - set(price_data.columns)
        if missing:
            log.error(
                "_validate_input | missing columns | ticker=%s | missing=%s",
                ticker, sorted(missing),
            )
            return self._no_signal(
                ticker=ticker,
                reason=f"Missing required columns: {sorted(missing)}",  # FIXED: Capital M
            )

        # ela l a9al 60 price or row
        if len(price_data) < MIN_ROWS:
            log.warning(
                "_validate_input | insufficient rows | ticker=%s | rows=%d | min=%d",
                ticker, len(price_data), MIN_ROWS,
            )
            return self._no_signal(
                ticker=ticker,
                reason=f"Insufficient rows ({len(price_data)} < {MIN_ROWS})",  # FIXED: Capital I
            )

        # NaN in Close ila kant nan mablansh atkhrbe9 lhsab
        nan_count = int(price_data["Close"].isna().sum())
        if nan_count:
            log.error(
                "_validate_input | NaN in Close | ticker=%s | count=%d",
                ticker, nan_count,
            )
            return self._no_signal(
                ticker=ticker,
                reason=f"NaN values in Close column ({nan_count})",
            )

        log.debug("_validate_input | OK | ticker=%s | rows=%d", ticker, len(price_data))
        # return none ida dazo ga3 checks
        return None  

    def _is_zero_cross(self, z_now: float, z_prev: float) -> bool:
        """
        Detect whether Z-Score crossed zero between prev bar and current bar.

        A zero-cross means the price has returned to its mean — the trade
        that was opened on the band touch is now complete (EXIT intent).

        Returns True for:
          negative → positive cross  (z_prev < 0 < z_now)
          positive → negative cross  (z_prev > 0 > z_now)
        Returns False for all other cases including NaN inputs.
        """

        if z_now is None or z_prev is None:
            log.debug("_is_zero_cross | None input | returning False")
            return False

        try:
            if np.isnan(z_now) or np.isnan(z_prev):
                log.debug("_is_zero_cross | NaN input | returning False")
                return False
        except (TypeError, ValueError):
            log.warning(
                "_is_zero_cross | non-numeric input | z_now=%s z_prev=%s | "
                "returning False",
                z_now, z_prev,
            )
            return False
        # z of today 
        z_now_d  = _to_dec(z_now)
        # z of yesterday 
        z_prev_d = _to_dec(z_prev)

        if z_now_d is None or z_prev_d is None:
            return False

        _zero = Decimal("0")

        # negative → positive  
        if z_prev_d < _zero and z_now_d > _zero:
            log.debug(
                "_is_zero_cross | neg→pos cross | z_prev=%.4f | z_now=%.4f",
                float(z_prev_d), float(z_now_d),
            )
            return True

        # positive → negative cross
        if z_prev_d > _zero and z_now_d < _zero:
            log.debug(
                "_is_zero_cross | pos→neg cross | z_prev=%.4f | z_now=%.4f",
                float(z_prev_d), float(z_now_d),
            )
            return True

        return False
    
    def generate_signal(self, ticker: str, price_data: Optional[pd.DataFrame]) -> dict:
        """
        Analyse price data and return a BaseStrategy-compatible signal dict.

        Flow
        ----
        1. Validate input
        2. Compute all indicators
        3. Build base skeleton signal
        4. EXIT check (highest priority — Z-Score zero-cross)
        5. Regime filters (ADX, band-width, volume, weekly trend)
        6. Entry logic (BUY oversold / SELL overbought)
        7. Neutral fallback

        EXIT encoding (BaseStrategy does not accept 'EXIT'):
          action      = 'HOLD'
          signal_type = 'BB_MEAN_REVERT'
          reasoning   starts with '[EXIT]'

        Returns
        -------
        dict with keys: ticker, action, confidence, current_price,
        stop_loss, take_profit, reasoning, signal_type, strategy,
        timestamp, diagnostics
        """
        # validate input and exits if any check fails
        invalid = self._validate_input(ticker, price_data)
        if invalid is not None:
            return invalid

        try:
            # compute indicators and get the last two rows
            df     = self._compute_indicators(price_data)
            latest = df.iloc[-1]
            # we need it for z zero cross check
            prev   = df.iloc[-2]

            # Pull latest close as Decimal then float for calculations
            price_dec = _to_dec(latest["Close"])
            if price_dec is None:
                log.error(
                    "generate_signal | latest Close is None | ticker=%s", ticker
                )
                return self._no_signal(ticker=ticker, reason="latest Close is None")
            price = float(price_dec)


            def _safe_float(row, col: str) -> float:
                v = _to_dec(row.get(col))
                return float(v) if v is not None else float("nan")

            # Calculate volume_quiet and bw_expanding flags
            volume_quiet = self._volume_is_quiet(df)
            
            # bw_expanding: True if BandWidth_Change >= bw_expand_threshold
            bw_change = _safe_float(latest, "BandWidth_Change")
            bw_expanding = not np.isnan(bw_change) and bw_change >= self.bw_expand_threshold

            diagnostics = {
                "z_score":      _safe_float(latest, "Z_Score"),
                "adx":          _safe_float(latest, "ADX"),
                "band_width":   _safe_float(latest, "BandWidth"),
                "bw_expanding": bw_expanding,
                "volume_quiet": volume_quiet,
                "weekly_bull":  bool(latest.get("WeeklyBull", True)),
                "upper_band":   _safe_float(latest, "Upper"),
                "lower_band":   _safe_float(latest, "Lower"),
                "sma":          _safe_float(latest, "SMA"),
                "atr":          _safe_float(latest, "ATR"),
            }

            signal = self._build_base(ticker, price, diagnostics)

            z_now  = diagnostics["z_score"]
            z_prev = _safe_float(prev, "Z_Score")
            adx    = diagnostics["adx"]
            atr    = diagnostics["atr"]

            upper            = diagnostics["upper_band"]
            lower            = diagnostics["lower_band"]
            bandwidth_change = _safe_float(latest, "BandWidth_Change")
            weekly_bull      = diagnostics["weekly_bull"]

            # ── 4. EXIT LOGIC — highest priority ─────────────────────────
            #
            # If Z-Score crossed zero, the price has returned to its mean.
            # The trade is done. Signal EXIT regardless of everything else.

            if self._is_zero_cross(z_now, z_prev):
                signal.update({
                    "action":      "HOLD",
                    "signal_type": SIG_MEAN_REVERT,
                    "confidence":  self._confidence(z_now),
                    "reasoning":   (
                        f"[EXIT] Z-Score crossed zero "
                        f"(prev={z_prev:.4f} → now={z_now:.4f}) "
                        f"→ mean reversion complete"
                    ),
                })
                log.info(
                    "generate_signal | EXIT | ticker=%s | z_prev=%.4f | z_now=%.4f",
                    ticker, z_prev, z_now,
                )
                return self._validate(signal)

            # ── 5. Regime filters ─────────────────────────────────────────

            # 5a — ADX: block if market is trending
            if not np.isnan(adx) and adx >= self.adx_threshold:
                signal["reasoning"] = (
                    f"ADX={adx:.2f} >= threshold={self.adx_threshold:.1f} "
                    f"→ trending market, mean reversion blocked"
                )
                log.debug(
                    "generate_signal | blocked ADX | ticker=%s | adx=%.2f", ticker, adx
                )
                return self._validate(signal)

            # 5b — BandWidth: block if bands are explosively expanding
            if not np.isnan(bandwidth_change) and bandwidth_change >= self.bw_expand_threshold:
                signal["reasoning"] = (
                    f"BandWidth expanding ({bandwidth_change:.4f} >= "
                    f"{self.bw_expand_threshold:.4f}) → breakout risk, blocked"
                )
                log.debug(
                    "generate_signal | blocked bandwidth | ticker=%s | bw_change=%.4f",
                    ticker, bandwidth_change,
                )
                return self._validate(signal)

            # 5c — Volume: block if volume is elevated (conviction move)
            if self.require_volume and not volume_quiet:
                signal["reasoning"] = (
                    f"Volume elevated (above {VOLUME_CONFIRM_PCTL}th percentile) "
                    f"→ conviction move, mean reversion blocked"
                )
                log.debug(
                    "generate_signal | blocked volume | ticker=%s", ticker
                )
                return self._validate(signal)

            # ── 6. Entry logic ────────────────────────────────────────────

            # Use Decimal for stop/tp arithmetic to avoid float rounding
            price_d     = Decimal(str(price))
            atr_d       = _to_dec(atr)
            stop_mult_d = Decimal(str(self.stop_atr_mult))
            tp_mult_d   = Decimal(str(self.tp_atr_mult))

            def _stop_buy() -> Optional[float]:
                # stop below entry for a BUY
                if atr_d is None:
                    return None
                result = price_d - (stop_mult_d * atr_d)
                return float(result.quantize(_DECIMAL_PLACES, rounding=ROUND_HALF_UP))

            def _tp_buy() -> Optional[float]:
                # take-profit above entry for a BUY
                if atr_d is None:
                    return None
                result = price_d + (tp_mult_d * atr_d)
                return float(result.quantize(_DECIMAL_PLACES, rounding=ROUND_HALF_UP))

            def _stop_sell() -> Optional[float]:
                # stop above entry for a SELL
                if atr_d is None:
                    return None
                result = price_d + (stop_mult_d * atr_d)
                return float(result.quantize(_DECIMAL_PLACES, rounding=ROUND_HALF_UP))

            def _tp_sell() -> Optional[float]:
                # take-profit below entry for a SELL
                if atr_d is None:
                    return None
                result = price_d - (tp_mult_d * atr_d)
                return float(result.quantize(_DECIMAL_PLACES, rounding=ROUND_HALF_UP))

            # 6a — BUY: price at or below lower band, Z sufficiently negative
            if price <= lower and z_now <= -self.z_entry:

                # Weekly filter: only BUY when macro trend is up
                if self.use_weekly_filter and not weekly_bull:
                    signal["reasoning"] = (
                        f"Oversold (Z={z_now:.2f}) but weekly trend is bearish "
                        f"→ against macro direction, blocked"
                    )
                    log.debug(
                        "generate_signal | BUY blocked weekly | ticker=%s", ticker
                    )
                    return self._validate(signal)

                signal.update({
                    "action":      "BUY",
                    "signal_type": SIG_OVERSOLD,
                    "confidence":  self._confidence(z_now),
                    "stop_loss":   _stop_buy(),
                    "take_profit": _tp_buy(),
                    "reasoning":   (
                        f"Oversold: price={price:.4f} <= lower={lower:.4f} "
                        f"& Z={z_now:.4f} <= -{self.z_entry}"
                    ),
                })
                log.info(
                    "generate_signal | BUY | ticker=%s | z=%.4f | price=%.4f | "
                    "stop=%.4f | tp=%.4f",
                    ticker, z_now, price,
                    signal["stop_loss"]   or float("nan"),
                    signal["take_profit"] or float("nan"),
                )
                return self._validate(signal)

            # 6b — SELL: price at or above upper band, Z sufficiently positive
            if price >= upper and z_now >= self.z_entry:

                # Weekly filter: only SELL when macro trend is down
                if self.use_weekly_filter and weekly_bull:
                    signal["reasoning"] = (
                        f"Overbought (Z={z_now:.2f}) but weekly trend is bullish "
                        f"→ against macro direction, blocked"
                    )
                    log.debug(
                        "generate_signal | SELL blocked weekly | ticker=%s", ticker
                    )
                    return self._validate(signal)

                signal.update({
                    "action":      "SELL",
                    "signal_type": SIG_OVERBOUGHT,
                    "confidence":  self._confidence(z_now),
                    "stop_loss":   _stop_sell(),
                    "take_profit": _tp_sell(),
                    "reasoning":   (
                        f"Overbought: price={price:.4f} >= upper={upper:.4f} "
                        f"& Z={z_now:.4f} >= +{self.z_entry}"
                    ),
                })
                log.info(
                    "generate_signal | SELL | ticker=%s | z=%.4f | price=%.4f | "
                    "stop=%.4f | tp=%.4f",
                    ticker, z_now, price,
                    signal["stop_loss"]   or float("nan"),
                    signal["take_profit"] or float("nan"),
                )
                return self._validate(signal)

            # ── 7. No signal ──────────────────────────────────────────────
            signal["signal_type"] = SIG_NEUTRAL
            signal["reasoning"]   = (
                f"No entry condition met | Z={z_now:.4f} | "
                f"price={price:.4f} | lower={lower:.4f} | upper={upper:.4f}"
            )
            log.debug("generate_signal | HOLD/NEUTRAL | ticker=%s", ticker)
            return self._validate(signal)

        except Exception as exc:
            log.exception(
                "generate_signal | unexpected error | ticker=%s | error=%s",
                ticker, exc,
            )
            return self._no_signal(ticker=ticker, reason=f"unexpected error: {exc}")

    # ── Private helpers ───────────────────────────────────────────────────────


    def _compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute all technical indicators and append as new columns.

        Works on a copy of df so the caller's DataFrame is never mutated.

        Columns added
        -------------
        SMA, STD, Upper, Lower   — Bollinger Bands
        Z_Score                  — (Close - SMA) / STD
        BandWidth                — (Upper - Lower) / SMA
        BandWidth_Change         — pct_change of BandWidth (expansion rate)
        ADX                      — via _compute_adx()
        ATR                      — via _compute_atr()
        WeeklySMA                — 50-bar rolling mean
        WeeklyBull               — bool, Close > WeeklySMA
        """
        #awalan nakhdo copy mn data frame
        df = df.copy()

        # Cast to float for type safety — pandas rolling/ewm require numeric dtype & pandas need float
        df["Close"] = df["Close"].astype(float)
        df["High"]  = df["High"].astype(float)
        df["Low"]   = df["Low"].astype(float)

        # ── Bollinger Bands ───────────────────────────────────────────────
        # SMA = simple moving average of Close over self.window bars
        # STD = rolling standard deviation of Close over self.window bars
        # Upper / Lower = SMA ± num_std × STD
        # .roling kadroppi lina some days bash twsel l3adad li tbda ameno lhsab d lmoving average
        df["SMA"] = df["Close"].rolling(self.window).mean()
        # volatilty 
        df["STD"] = df["Close"].rolling(self.window).std()
        # upper band
        df["Upper"] = df["SMA"] + (self.num_std * df["STD"])
        # lower band
        df["Lower"] = df["SMA"] - (self.num_std * df["STD"])

        # Z-Score
        # Z = (Close - SMA) / STD
        # Guard: if STD == 0 (flat market) → Z = 0.0 to avoid division-by-zero
        # We use Decimal row-by-row for precision, then store as float column.

        z_values: list = []
        for idx in range(len(df)):
            close_d = _to_dec(df["Close"].iloc[idx])
            sma_d   = _to_dec(df["SMA"].iloc[idx])
            std_d   = _to_dec(df["STD"].iloc[idx])

            if close_d is None or sma_d is None or std_d is None:
                z_values.append(float("nan"))
                continue

            if std_d == Decimal("0"):
                z_values.append(0.0)
                continue

            z = (close_d - sma_d) / std_d
            #rounds to n decimal places ida kant for 5 round up
            z_values.append(float(z.quantize(_DECIMAL_PLACES, rounding=ROUND_HALF_UP)))

        df["Z_Score"] = z_values

        # ── BandWidth 
        # BandWidth = (Upper - Lower) / SMA

        bw_values: list = []
        for idx in range(len(df)):
            upper_d = _to_dec(df["Upper"].iloc[idx])
            lower_d = _to_dec(df["Lower"].iloc[idx])
            sma_d   = _to_dec(df["SMA"].iloc[idx])

            if upper_d is None or lower_d is None or sma_d is None:
                bw_values.append(float("nan"))
                continue

            if sma_d == Decimal("0"):
                bw_values.append(float("nan"))
                continue

            bw = (upper_d - lower_d) / sma_d
            bw_values.append(float(bw.quantize(_DECIMAL_PLACES, rounding=ROUND_HALF_UP)))

        df["BandWidth"]        = bw_values
        df["BandWidth_Change"] = df["BandWidth"].pct_change()

        # ── ADX ─
        df["ADX"] = _compute_adx(
            high=df["High"], low=df["Low"], close=df["Close"], period=ADX_PERIOD
        )

        # ── ATR 
        df["ATR"] = _compute_atr(
            high=df["High"], low=df["Low"], close=df["Close"], period=ATR_PERIOD
        )

        # ── Weekly trend filter ──
        df["WeeklySMA"]  = df["Close"].rolling(WEEKLY_WINDOW).mean()
        df["WeeklyBull"] = df["Close"] > df["WeeklySMA"]

        # ── Snapshot log ──────────────────────────────────────────────────
        latest = df.iloc[-1]
        log.debug(
            "_compute_indicators | latest snapshot | "
            "Close=%.4f | SMA=%.4f | Z=%.4f | ADX=%.2f | ATR=%.4f | BW=%.4f",
            float(latest.get("Close",    float("nan"))),
            float(latest.get("SMA",      float("nan"))),
            float(latest.get("Z_Score",  float("nan"))),
            float(latest.get("ADX",      float("nan"))),
            float(latest.get("ATR",      float("nan"))),
            float(latest.get("BandWidth",float("nan"))),
        )

        return df

    def _volume_is_quiet(self, df: pd.DataFrame) -> bool:
        """
        Return True if the latest bar's volume is at or below the
        VOLUME_CONFIRM_PCTL (40th) percentile of recent volume history.

        Quiet volume → low-conviction move → likely exhaustion → allow entry.
        Loud  volume → high-conviction move → likely breakout  → block entry.

        Defaults to True (allow) when volume data is unavailable or
        insufficient so the strategy degrades gracefully.
        purpose : is today's volume low enough to trade
        """

        # wash volume kayn
        if "Volume" not in df.columns:
            log.warning(
                "_volume_is_quiet | no Volume column | defaulting to True (allow)"
            )
            return True

        volume       = df["Volume"]
        volume_clean = volume.dropna()

        if len(volume_clean) < 10:
            log.warning(
                "_volume_is_quiet | insufficient volume rows | "
                "valid=%d | defaulting to True (allow)",
                len(volume_clean),
            )
            return True

        # latest volume , v of today
        latest_vol = volume.iloc[-1]
        if pd.isna(latest_vol):
            log.warning(
                "_volume_is_quiet | latest volume is NaN | defaulting to True (allow)"
            )
            return True

        try:
            latest_vol_d  = _to_dec(latest_vol)
            # volumes are sorted low to high
            # we check if the volume of today is among the 40% quiet area or in the loud one
            threshold_d   = _to_dec(np.percentile(volume_clean, VOLUME_CONFIRM_PCTL))

            if latest_vol_d is None or threshold_d is None:
                log.warning(
                    "_volume_is_quiet | Decimal conversion failed | "
                    "defaulting to True (allow)"
                )
                return True

            is_quiet = latest_vol_d <= threshold_d

            log.debug(
                "_volume_is_quiet | latest=%.2f | pctl%d=%.2f | quiet=%s",
                float(latest_vol_d), VOLUME_CONFIRM_PCTL, float(threshold_d), is_quiet,
            )

            return bool(is_quiet)

        except Exception as exc:
            log.exception(
                "_volume_is_quiet | error computing percentile | error=%s | "
                "defaulting to True (allow)",
                exc,
            )
            return True


    def _confidence(self, z: float) -> float:
        """
        Map Z-Score magnitude to a confidence score in [0.55, 0.88].

        Mapping
        -------
        |z| <= z_entry              → CONFIDENCE_BASE (0.55)  flat floor
        z_entry < |z| <= z_strong  → linear ramp 0.55 → 0.80
        |z| > z_strong             → 0.80 + small boost, capped at 0.88

        All arithmetic done in Decimal then rounded to 4dp.
        """

        if z is None:
            log.error("_confidence | z is None | returning base=%.4f", CONFIDENCE_BASE)
            return round(CONFIDENCE_BASE, 4)

        # ── Guard: NaN ────────────────────────────────────────────────────
        try:
            if np.isnan(float(z)):
                log.error("_confidence | z is NaN | returning base=%.4f", CONFIDENCE_BASE)
                return round(CONFIDENCE_BASE, 4)
        except (TypeError, ValueError):
            log.error(
                "_confidence | z not numeric | type=%s | returning base=%.4f",
                type(z).__name__, CONFIDENCE_BASE,
            )
            return round(CONFIDENCE_BASE, 4)

        z_d        = _to_dec(abs(float(z)))
        z_entry_d  = _to_dec(self.z_entry)
        z_strong_d = _to_dec(self.z_strong)
        base_d     = _to_dec(CONFIDENCE_BASE)
        cap_d      = Decimal("0.88")
        mid_d      = Decimal("0.80")

        if any(v is None for v in (z_d, z_entry_d, z_strong_d, base_d)):
            log.error("_confidence | Decimal conversion failed | returning base")
            return round(CONFIDENCE_BASE, 4)

        # Case 1 — below entry threshold: flat floor
        if z_d <= z_entry_d:
            confidence_d = base_d
            log.debug(
                "_confidence | flat floor | |z|=%.4f | conf=%.4f",
                float(z_d), float(confidence_d),
            )

        #  between entry and strong: linear ramp 0.55 → 0.80
        elif z_d <= z_strong_d:
            # distance between tresholds
            span = z_strong_d - z_entry_d
            if span <= Decimal("0"):
                log.error(
                    "_confidence | zero span | z_entry=%.4f z_strong=%.4f | "
                    "returning base",
                    self.z_entry, self.z_strong,
                )
                return round(CONFIDENCE_BASE, 4)

            ratio        = (z_d - z_entry_d) / span
            confidence_d = base_d + ratio * (mid_d - base_d)

            log.debug(
                "_confidence | linear ramp | |z|=%.4f | ratio=%.4f | conf=%.4f",
                float(z_d), float(ratio), float(confidence_d),
            )

        # Case 3 — beyond strong threshold: add boost up to 0.08
        else:
            boost_ratio  = min((z_d - z_strong_d) / z_strong_d, Decimal("1"))
            boost        = boost_ratio * Decimal("0.08")
            confidence_d = mid_d + boost

            log.debug(
                "_confidence | strong boost | |z|=%.4f | boost=%.4f | conf=%.4f",
                float(z_d), float(boost), float(confidence_d),
            )

        # ── Clamp to [CONFIDENCE_BASE, 0.88] then round to 4dp ───────────
        confidence_d = max(base_d, min(cap_d, confidence_d))
        confidence_d = confidence_d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

        log.debug(
            "_confidence | final | z=%.4f | confidence=%.4f", float(z_d), float(confidence_d)
        )

        return float(confidence_d)

    def _build_base(self, ticker: str, price: float, diagnostics: dict) -> dict:
        """
        Construct a skeleton signal dict that every code path starts from.

        Every generate_signal code path calls this first, then mutates
        only the fields it needs before calling self._validate().

        Default state
        -------------
        action      = 'HOLD'
        confidence  = 0.30  (safe non-committal placeholder)
        stop_loss   = None
        take_profit = None
        signal_type = BB_NEUTRAL
        reasoning   = ''
        """

        # ── Guard: ticker ─────────────────────────────────────────────────
        if not isinstance(ticker, str) or not ticker.strip():
            log.error(
                "_build_base | invalid ticker | got=%s | using UNKNOWN", ticker
            )
            ticker = "UNKNOWN"
        else:
            ticker = ticker.strip().upper()

        price_d = _to_dec(price)
        if price_d is None or price_d < Decimal("0"):
            log.error(
                "_build_base | invalid price | ticker=%s | price=%s | using 0.0",
                ticker, price,
            )
            price_d = Decimal("0")

        price_rounded = float(
            price_d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        )

        if not isinstance(diagnostics, dict):
            log.warning(
                "_build_base | diagnostics not a dict | type=%s | resetting to {}",
                type(diagnostics).__name__,
            )
            diagnostics = {}

        signal = {
            "ticker":        ticker,
            "action":        "HOLD",
            "confidence":    0.30,
            "current_price": price_rounded,
            "stop_loss":     None,
            "take_profit":   None,
            "reasoning":     "",
            "signal_type":   SIG_NEUTRAL,
            "strategy":      self.name,
            "timestamp":     datetime.now(timezone.utc).isoformat(),
            "diagnostics":   diagnostics,
        }

        log.debug(
            "_build_base | built | ticker=%s | price=%.4f", ticker, price_rounded
        )

        return signal


# ── Module-level singleton ────────────────────────────────────────────────────

mean_reversion_strategy = MeanReversionStrategy()