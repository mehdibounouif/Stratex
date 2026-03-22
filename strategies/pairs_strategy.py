"""
Production-grade Statistical Arbitrage Pairs Trading Strategy.
Fully compatible with Quant_firm BaseStrategy.

Improvements over baseline
--------------------------
1.  Input validation on generate_pair_signal() — handles None, non-DataFrame,
    missing Close column, NaN values. Crashes replaced with _no_signal returns.

2.  NaN z-score guard — constant-price or zero-STD series produces NaN z;
    detected explicitly and returned as NO_SIGNAL with a clear reason.

3.  Cointegration filter (Engle-Granger) — pair is skipped if the spread
    does not reject the unit-root null at the configured p-value threshold.
    Prevents trading pairs that are not actually mean-reverting.

4.  Dynamic hedge ratio (OLS beta) — rolling regression of log(A) on log(B)
    over the same window gives a proper hedge ratio instead of hardcoded 1:1.
    The spread is then: log(A) - beta * log(B) - alpha.

5.  Half-life check (Ornstein-Uhlenbeck) — spread must have a half-life
    within [min_half_life, max_half_life] bars to be tradeable.

6.  Stop-loss and take-profit on every directional signal — derived from
    spread ATR so risk is sized to spread volatility.

7.  Diagnostics dict on every signal — z_score, hedge_ratio, half_life,
    spread_mean, spread_std, cointegrated flag for monitoring.

8.  Improved confidence model — two-zone ramp (entry → strong → cap at 0.88)
    mirroring MeanReversionStrategy for consistency across strategies.

9.  generate_signal() awareness — single-ticker call now clearly documents
    the two-leg requirement; returns informative NO_SIGNAL (not confusing HOLD).

10. Type annotations cleaned up — Optional[tuple] replaces invalid
    'tuple or None' annotation.

BaseStrategy compatibility
--------------------------
- Does NOT override _validate() or _no_signal(). Uses base versions.
- action is always BUY | SELL | HOLD.
- Extra keys (stop_loss, take_profit, diagnostics) pass through _validate()
  untouched.
- source field added by base _validate() automatically.
"""

from datetime import datetime
from typing import Optional
import numpy as np
import pandas as pd

from strategies.base_strategy import BaseStrategy
from logger import get_logger

log = get_logger("strategies.pairs")


# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_PAIRS       = [("MSFT", "GOOGL"), ("AAPL", "MSFT"), ("AMD", "NVDA")]
DEFAULT_WINDOW      = 60       # rolling window for spread stats
DEFAULT_Z_THRESHOLD = 2.0      # |z| must exceed this to enter
Z_STRONG_THRESHOLD  = 2.8      # |z| above this → stronger confidence boost
CONFIDENCE_BASE     = 0.55     # confidence at z_threshold
COINT_PVALUE        = 0.05     # Engle-Granger p-value threshold
MIN_HALF_LIFE       = 5        # spread must revert faster than this (bars)
MAX_HALF_LIFE       = 40       # spread must revert within this (bars)
STOP_SPREAD_MULT    = 1.5      # stop = entry_spread ± 1.5 × spread_std
TP_SPREAD_MULT      = 0.0      # take-profit = mean reversion to zero (z=0)

# Signal type constants
SIG_NEUTRAL  = "PAIRS_NEUTRAL"
SIG_LONG_A   = "PAIRS_LONG_A"    # BUY A / SELL B
SIG_SHORT_A  = "PAIRS_SHORT_A"   # SELL A / BUY B
SIG_LONG_B   = "PAIRS_LONG_B"
SIG_SHORT_B  = "PAIRS_SHORT_B"
SIG_NO_SIG   = "NO_SIGNAL"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _engle_granger_pvalue(spread: pd.Series) -> float:
    """
    Approximate Engle-Granger cointegration test via ADF on the spread.

    Parameters:
    - spread (pd.Series): Time series of spread values between two assets

    Responsibility:
    - Attempt to import statsmodels and use adfuller() for an accurate result
    - Fall back to a manual ADF with one lag when statsmodels is unavailable:
        * Fit OLS: delta_s = alpha + beta * s_{t-1} + eps
        * Compute tau statistic from the OLS coefficient
        * Map tau to an approximate p-value using MacKinnon critical values:
            tau < -3.5  → p ≈ 0.01
            tau < -2.9  → p ≈ 0.05
            tau < -2.6  → p ≈ 0.10
            tau < -1.95 → p ≈ 0.25
            otherwise   → p = 0.99
    - Return 1.0 if fewer than 20 aligned observations are available

    Returns:
    - float: Estimated p-value; values < COINT_PVALUE indicate cointegration
    """
    pass


def _half_life(spread: pd.Series) -> float:
    """
    Estimate the half-life of mean reversion using an Ornstein-Uhlenbeck fit.

    Parameters:
    - spread (pd.Series): Time series of spread values between two assets

    Responsibility:
    - Fit OLS: delta_s = alpha + beta * s_{t-1} + eps
    - Derive half-life = -ln(2) / beta
    - Return float('inf') if fewer than 10 observations are available,
      if the OLS solve fails, or if beta >= 0 (not mean-reverting)

    Returns:
    - float: Half-life in bars; float('inf') signals non-mean-reverting spread
    """
    pass


def _ols_hedge_ratio(log_a: pd.Series, log_b: pd.Series) -> tuple[float, float]:
    """
    Estimate the OLS hedge ratio by regressing log_a on log_b.

    Parameters:
    - log_a (pd.Series): Log prices of asset A over the lookback window
    - log_b (pd.Series): Log prices of asset B over the lookback window

    Responsibility:
    - Fit OLS: log_a = alpha + beta * log_b + eps
    - Return (1.0, 0.0) as safe defaults if the OLS solve fails
    - The resulting spread is defined as: log_a - beta * log_b - alpha

    Returns:
    - tuple[float, float]: (beta, alpha) hedge ratio and intercept
    """
    pass


class PairsStrategy(BaseStrategy):
    """
    Production statistical arbitrage pairs trading strategy.

    Primary API:
    - generate_pair_signal(ticker_a, data_a, ticker_b, data_b) -> list[dict]
        Returns two signal dicts (one per leg) always in order [sig_a, sig_b].
        Use this for all live and backtest signal generation.

    - generate_signal(ticker, price_data) -> dict
        Satisfies the abstract BaseStrategy interface. Always returns HOLD /
        NO_SIGNAL because pairs logic requires both legs simultaneously.

    Signal types:
    - PAIRS_LONG_A  / PAIRS_SHORT_B → spread below -z_threshold (A cheap vs B)
    - PAIRS_SHORT_A / PAIRS_LONG_B  → spread above +z_threshold (A dear vs B)
    - PAIRS_NEUTRAL                 → |z| within threshold
    - NO_SIGNAL                     → bad input or failed filter

    BaseStrategy compatibility:
    - Does NOT override _validate() or _no_signal()
    - action is always BUY | SELL | HOLD
    - Extra fields (stop_loss, take_profit, diagnostics) pass through untouched
    """

    name = "Pairs Statistical Arbitrage"

    def __init__(
        self,
        pairs: Optional[list] = None,
        window: int = 60,
        z_threshold: float = 2.0,
        z_strong: float = 2.5,
        check_cointegration: bool = True,
        coint_pvalue: float = 0.05,
        check_half_life: bool = True,
        min_half_life: int = 5,
        max_half_life: int = 60,
        use_hedge_ratio: bool = True,
        stop_spread_mult: float = 2.0,
    ) -> None:
        """
        Initialise strategy parameters.

        Parameters:
        - pairs (list | None): List of (ticker_a, ticker_b) tuples to trade;
            defaults to DEFAULT_PAIRS if None
        - window (int): Rolling window for spread statistics (default: 60)
        - z_threshold (float): Z-Score magnitude to trigger entry (default: 2.0)
        - z_strong (float): Z-Score threshold for strong signal boost (default: 2.5)
        - check_cointegration (bool): Enforce cointegration filter (default: True)
        - coint_pvalue (float): Max p-value to accept as cointegrated (default: 0.05)
        - check_half_life (bool): Enforce half-life filter (default: True)
        - min_half_life (int): Minimum acceptable half-life in bars (default: 5)
        - max_half_life (int): Maximum acceptable half-life in bars (default: 60)
        - use_hedge_ratio (bool): Use OLS hedge ratio for spread (default: True)
        - stop_spread_mult (float): Spread-STD multiplier for stop distance (default: 2.0)

        Responsibility:
        - Store all tunable hyperparameters as instance attributes
        """
        pass

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_signal(self, ticker: str,
                        price_data: Optional[pd.DataFrame]) -> dict:
        """
        Single-ticker interface required by BaseStrategy.

        Parameters:
        - ticker (str): Stock symbol
        - price_data (pd.DataFrame | None): OHLCV data (unused)

        Responsibility:
        - Look up whether ticker belongs to a registered pair via find_pair()
        - Always return a NO_SIGNAL HOLD explaining that generate_pair_signal()
          must be used instead
        - Include the paired ticker name in the reasoning when found

        Returns:
        - dict: HOLD signal with signal_type=NO_SIGNAL and guidance message
        """
        pass

    def generate_pair_signal(
        self,
        ticker_a: str,
        data_a: Optional[pd.DataFrame],
        ticker_b: str,
        data_b: Optional[pd.DataFrame],
    ) -> list:
        """
        Generate simultaneous entry/exit signals for both legs of a pair.

        Parameters:
        - ticker_a (str): Symbol for asset A
        - data_a (pd.DataFrame | None): OHLCV data for asset A; must have 'Close'
        - ticker_b (str): Symbol for asset B
        - data_b (pd.DataFrame | None): OHLCV data for asset B; must have 'Close'

        Responsibility:
        - Validate both inputs via _validate_pair_input(); return early on error
        - Align on shared index, drop NaN rows, enforce minimum window length
        - Compute log prices; optionally fit OLS hedge ratio via _ols_hedge_ratio()
        - Build spread = log_a - beta * log_b - alpha
        - Compute rolling mean, std, and Z-Score over self.window
        - Guard against non-finite Z-Score (zero std edge case)
        - Apply cointegration filter via _engle_granger_pvalue() if enabled
        - Apply half-life filter via _half_life() if enabled
        - Return NEUTRAL HOLD signals when |z| <= z_threshold
        - Generate directional signals when |z| > z_threshold:
            z < -threshold → BUY A (PAIRS_LONG_A) + SELL B (PAIRS_SHORT_B)
            z > +threshold → SELL A (PAIRS_SHORT_A) + BUY B (PAIRS_LONG_B)
        - Call self._validate() on every returned signal dict

        Returns:
        - list[dict]: Always exactly [sig_a, sig_b], both BaseStrategy-compatible,
            with keys: ticker, action, confidence, current_price, stop_loss,
            take_profit, reasoning, signal_type, strategy, timestamp, diagnostics
        """
        pass

    def find_pair(self, ticker: str) -> Optional[tuple]:
        """
        Look up the registered pair that contains the given ticker.

        Parameters:
        - ticker (str): Stock symbol to search for

        Responsibility:
        - Iterate self.pairs and return the first tuple containing ticker
        - Return None if ticker is not found in any registered pair

        Returns:
        - tuple | None: Matching (ticker_a, ticker_b) pair, or None
        """
        pass

    # ── Private helpers ───────────────────────────────────────────────────────

    def _validate_pair_input(
        self,
        ticker_a: str, data_a: Optional[pd.DataFrame],
        ticker_b: str, data_b: Optional[pd.DataFrame],
    ) -> Optional[list]:
        """
        Validate price data for both legs before any computation.

        Parameters:
        - ticker_a (str): Symbol for asset A
        - data_a (pd.DataFrame | None): Price data for asset A
        - ticker_b (str): Symbol for asset B
        - data_b (pd.DataFrame | None): Price data for asset B

        Responsibility:
        - For each leg independently check:
            * data is not None
            * data is a pd.DataFrame
            * 'Close' column is present
            * Close column is not entirely NaN
        - If either leg fails, return [no_sig_a, no_sig_b] with cross-referenced
          error messages (e.g. "counterpart error: ..." for the passing leg)
        - Return None when both legs are valid

        Returns:
        - list[dict] | None: Two-element error list, or None if both legs are valid
        """
        pass

    def _confidence(self, z: float) -> float:
        """
        Map Z-Score magnitude to a signal confidence in [0.55, 0.88].

        Parameters:
        - z (float): Current Z-Score (sign ignored; absolute value used)

        Responsibility:
        - Return CONFIDENCE_BASE (0.55) when |z| <= z_threshold
        - Linearly ramp confidence from 0.55 to 0.80 as |z| moves from
          z_threshold to z_strong
        - Add a small boost (up to 0.08) for |z| beyond z_strong
        - Clamp result to a maximum of 0.88

        Returns:
        - float: Confidence score rounded to 4 decimal places
        """
        pass

    def _build_hold(
        self,
        ticker: str,
        price: float,
        reasoning: str,
        signal_type: str,
        z_score: float,
        hedge_ratio: float,
        half_life: float,
        cointegrated: bool,
        diagnostics: Optional[dict] = None,
    ) -> dict:
        """
        Construct and validate a HOLD signal for one leg.

        Parameters:
        - ticker (str): Stock symbol
        - price (float): Latest close price
        - reasoning (str): Human-readable explanation for the HOLD
        - signal_type (str): One of PAIRS_NEUTRAL or NO_SIGNAL
        - z_score (float): Current spread Z-Score
        - hedge_ratio (float): OLS beta used to construct the spread
        - half_life (float): Estimated mean-reversion half-life in bars
        - cointegrated (bool): Whether the spread passed the cointegration test
        - diagnostics (dict | None): Pre-built diagnostics dict; if None, a
            minimal dict is built from the scalar parameters above

        Responsibility:
        - Assemble a full BaseStrategy-compatible signal dict with action='HOLD'
        - Call self._validate() before returning

        Returns:
        - dict: Validated HOLD signal
        """
        pass

    def _build_directional(
        self,
        ticker: str,
        price: float,
        action: str,
        signal_type: str,
        confidence: float,
        reasoning: str,
        spread_now: float,
        spread_mean: float,
        stop_dist: float,
        diagnostics: dict,
    ) -> dict:
        """
        Construct a BUY or SELL signal with spread-based stop and take-profit.

        Parameters:
        - ticker (str): Stock symbol
        - price (float): Latest close price
        - action (str): 'BUY' or 'SELL'
        - signal_type (str): PAIRS_LONG_A, PAIRS_SHORT_A, PAIRS_LONG_B, or PAIRS_SHORT_B
        - confidence (float): Signal confidence from _confidence()
        - reasoning (str): Human-readable signal description
        - spread_now (float): Current spread value
        - spread_mean (float): Rolling mean of the spread (take-profit target)
        - stop_dist (float): Stop distance = stop_spread_mult * spread_std
        - diagnostics (dict): Shared diagnostics snapshot from generate_pair_signal()

        Responsibility:
        - Compute spread-level stop_loss and take_profit (not price levels):
            BUY  → stop = spread_now - stop_dist, tp = spread_mean
            SELL → stop = spread_now + stop_dist, tp = spread_mean
        - Assemble and return the signal dict (caller applies self._validate())

        Returns:
        - dict: Unvalidated directional signal dict (validated by caller)
        """
        pass


# Module-level singleton
pairs_strategy = PairsStrategy()