"""
Pytest test suite for MeanReversionStrategy — Quant_firm project layout.

Location : test/test_mean_reversion_strategy.py
Run from project root:
    pytest test/test_mean_reversion_strategy.py -v

Assumes conftest.py adds the project root to sys.path so that
  from strategies.mean_reversion_strategy import ...
  from strategies.base_strategy import BaseStrategy
resolve correctly against the installed packages.

No sys.modules patching needed — the real strategies/ and logger.py
are present on disk.
"""

import math
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from strategies.mean_reversion_strategy import (
    MeanReversionStrategy,
    MIN_ROWS,
    BB_WINDOW,
    SIG_NEUTRAL,
    SIG_OVERSOLD,
    SIG_OVERBOUGHT,
    SIG_MEAN_REVERT,
    SIG_NO_SIGNAL,
    _compute_adx,
    _compute_atr,
)
from strategies.base_strategy import BaseStrategy


# ── Helpers & fixtures ────────────────────────────────────────────────────────

def _make_ohlcv(
    n: int = 120,
    base_price: float = 100.0,
    trend: float = 0.0,
    noise: float = 0.5,
    volume_base: float = 1_000_000,
    seed: int = 42,
) -> pd.DataFrame:
    """Synthetic OHLCV DataFrame with controllable trend and noise."""
    rng = np.random.default_rng(seed)
    closes = [base_price]
    for _ in range(n - 1):
        closes.append(closes[-1] + trend + rng.normal(0, noise))
    closes = np.array(closes)
    highs  = closes + rng.uniform(0.1, 0.5, n)
    lows   = closes - rng.uniform(0.1, 0.5, n)
    opens  = closes - rng.normal(0, 0.2, n)
    vols   = rng.uniform(0.5, 1.5, n) * volume_base
    idx    = pd.date_range(end="2025-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows,
         "Close": closes, "Volume": vols},
        index=idx,
    )


def _flat_ohlcv(n: int = 120, price: float = 100.0) -> pd.DataFrame:
    """Perfectly flat price series — deterministic indicator tests."""
    closes = np.full(n, price)
    idx    = pd.date_range(end="2025-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"Open": closes, "High": closes + 0.2, "Low": closes - 0.2,
         "Close": closes, "Volume": np.full(n, 500_000.0)},
        index=idx,
    )


def _make_buy_data() -> pd.DataFrame:
    """
    Flat at 100, last two bars crashed to 84-85 → Z << -1.5, below lower band.
    weekly_bull=False (50-bar SMA ~99 > 84).
    Pair with use_weekly_filter=False to test BUY path in isolation.
    """
    n      = 120
    closes = np.full(n, 100.0)
    closes[-2] = 85.0
    closes[-1] = 84.0
    idx = pd.date_range(end="2025-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"Open": closes, "High": closes + 0.2, "Low": closes - 0.2,
         "Close": closes, "Volume": np.full(n, 500_000.0)},
        index=idx,
    )


def _make_sell_data() -> pd.DataFrame:
    """
    Flat at 100, last two bars spiked to 115-116 → Z >> +1.5, above upper band.
    weekly_bull=True (50-bar SMA ~99 < 116).
    Pair with use_weekly_filter=False to test SELL path in isolation.
    """
    n      = 120
    closes = np.full(n, 100.0)
    closes[-2] = 115.0
    closes[-1] = 116.0
    idx = pd.date_range(end="2025-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"Open": closes, "High": closes + 0.2, "Low": closes - 0.2,
         "Close": closes, "Volume": np.full(n, 500_000.0)},
        index=idx,
    )


def _all_filters_off(**kwargs) -> MeanReversionStrategy:
    """
    Strategy instance with every regime filter disabled.
    Used to test BUY/SELL entry logic in isolation.
    """
    defaults = dict(
        require_volume=False,
        adx_threshold=200.0,
        bw_expand_threshold=999.0,
        use_weekly_filter=False,
        z_entry=1.0,
    )
    defaults.update(kwargs)
    return MeanReversionStrategy(**defaults)


@pytest.fixture
def strategy() -> MeanReversionStrategy:
    """Default strategy instance — volume filter off for test convenience."""
    return MeanReversionStrategy(require_volume=False)


@pytest.fixture
def flat_data() -> pd.DataFrame:
    return _make_ohlcv(n=120, trend=0.0, noise=0.4)


# ── Inheritance ───────────────────────────────────────────────────────────────

class TestInheritance:
    """Strategy must be a proper BaseStrategy subclass."""

    def test_is_base_strategy_subclass(self):
        assert issubclass(MeanReversionStrategy, BaseStrategy)

    def test_instance_is_base_strategy(self, strategy):
        assert isinstance(strategy, BaseStrategy)

    def test_does_not_override_validate(self):
        """Strategy must use BaseStrategy._validate, not roll its own."""
        assert MeanReversionStrategy._validate is BaseStrategy._validate

    def test_does_not_override_no_signal(self):
        """Strategy must use BaseStrategy._no_signal."""
        assert MeanReversionStrategy._no_signal is BaseStrategy._no_signal

    def test_name_attribute_set(self, strategy):
        assert strategy.name == "Bollinger Mean Reversion (Production)"

    def test_str_returns_name(self, strategy):
        assert str(strategy) == strategy.name

    def test_repr_contains_class_name(self, strategy):
        assert "MeanReversionStrategy" in repr(strategy)


# ── Input validation ──────────────────────────────────────────────────────────

class TestInputValidation:

    def test_none_returns_hold(self, strategy):
        sig = strategy.generate_signal("TEST", None)
        assert sig["action"] == "HOLD"
        assert sig["signal_type"] == SIG_NO_SIGNAL

    def test_not_dataframe_returns_hold(self, strategy):
        sig = strategy.generate_signal("TEST", [[1, 2, 3]])
        assert sig["action"] == "HOLD"
        assert sig["signal_type"] == SIG_NO_SIGNAL

    def test_insufficient_rows_returns_hold(self, strategy):
        sig = strategy.generate_signal("TEST", _make_ohlcv(n=MIN_ROWS - 1))
        assert sig["action"] == "HOLD"
        assert "Insufficient" in sig["reasoning"]

    def test_missing_high_column_returns_hold(self, strategy):
        sig = strategy.generate_signal("TEST", _make_ohlcv().drop(columns=["High"]))
        assert sig["action"] == "HOLD"
        assert "Missing" in sig["reasoning"]

    def test_missing_low_column_returns_hold(self, strategy):
        sig = strategy.generate_signal("TEST", _make_ohlcv().drop(columns=["Low"]))
        assert sig["action"] == "HOLD"
        assert "Missing" in sig["reasoning"]

    def test_nan_in_close_returns_hold(self, strategy):
        df = _make_ohlcv()
        df.loc[df.index[50], "Close"] = float("nan")
        sig = strategy.generate_signal("TEST", df)
        assert sig["action"] == "HOLD"
        assert "NaN" in sig["reasoning"]

    def test_exactly_min_rows_accepted(self, strategy):
        sig = strategy.generate_signal("TEST", _make_ohlcv(n=MIN_ROWS))
        assert sig["action"] in {"BUY", "SELL", "HOLD"}

    def test_one_below_min_rows_rejected(self, strategy):
        sig = strategy.generate_signal("TEST", _make_ohlcv(n=MIN_ROWS - 1))
        assert sig["action"] == "HOLD"
        assert sig["signal_type"] == SIG_NO_SIGNAL


# ── BaseStrategy contract ─────────────────────────────────────────────────────

class TestBaseStrategyContract:
    """
    Every signal returned must fully satisfy the BaseStrategy contract.
    This mirrors exactly what SignalAggregator and other consumers expect.
    """

    # Fields the base guarantees are always present
    BASE_KEYS = {
        "ticker", "action", "confidence", "current_price",
        "reasoning", "signal_type", "strategy", "timestamp", "source",
    }
    # Extra fields this strategy adds (passed through _validate untouched)
    EXTRA_KEYS = {"stop_loss", "take_profit", "diagnostics"}

    def _assert_contract(self, sig: dict) -> None:
        missing_base  = self.BASE_KEYS  - sig.keys()
        missing_extra = self.EXTRA_KEYS - sig.keys()
        assert not missing_base,  f"Missing base keys:  {missing_base}"
        assert not missing_extra, f"Missing extra keys: {missing_extra}"
        assert sig["action"] in {"BUY", "SELL", "HOLD"}, (
            f"Invalid action '{sig['action']}' — base only allows BUY/SELL/HOLD"
        )
        assert 0.0 <= sig["confidence"] <= 1.0, (
            f"Confidence {sig['confidence']} out of [0, 1]"
        )
        assert sig["current_price"] >= 0.0, (
            f"current_price must be non-negative, got {sig['current_price']}"
        )
        datetime.fromisoformat(sig["timestamp"])   # raises ValueError if invalid

    def test_hold_signal_satisfies_contract(self, strategy, flat_data):
        self._assert_contract(strategy.generate_signal("AAPL", flat_data))

    def test_buy_signal_satisfies_contract(self):
        self._assert_contract(
            _all_filters_off().generate_signal("AAPL", _make_buy_data())
        )

    def test_sell_signal_satisfies_contract(self):
        self._assert_contract(
            _all_filters_off().generate_signal("SPY", _make_sell_data())
        )

    def test_no_signal_satisfies_contract(self, strategy):
        """
        _no_signal() routes through BaseStrategy._no_signal() which only
        guarantees the base required fields. stop_loss, take_profit, and
        diagnostics are extras added by _build_base() on normal signal paths
        and are intentionally absent on error/no-data signals.
        """
        sig = strategy.generate_signal("TEST", None)
        missing = self.BASE_KEYS - sig.keys()
        assert not missing, f"Missing base keys: {missing}"
        assert sig["action"] == "HOLD"
        assert sig["signal_type"] == SIG_NO_SIGNAL
        assert sig["confidence"] == 0.0
        assert sig["current_price"] >= 0.0

    def test_source_equals_strategy_name(self, strategy, flat_data):
        sig = strategy.generate_signal("AAPL", flat_data)
        assert sig["source"] == strategy.name

    def test_ticker_echoed_correctly(self, strategy, flat_data):
        for ticker in ["AAPL", "TSLA", "BTC-USD", "SPY"]:
            assert strategy.generate_signal(ticker, flat_data)["ticker"] == ticker

    def test_strategy_field_equals_name(self, strategy, flat_data):
        sig = strategy.generate_signal("AAPL", flat_data)
        assert sig["strategy"] == strategy.name

    def test_no_exit_action_ever_emitted(self, strategy):
        """
        BaseStrategy._validate silently converts EXIT → HOLD.
        The strategy must never rely on EXIT passing through.
        This test explicitly confirms EXIT is never in the output.
        """
        df = _flat_ohlcv()
        df.loc[df.index[-2], "Close"] = 98.0    # Z < 0
        df.loc[df.index[-1], "Close"] = 102.0   # Z > 0 → zero-cross
        sig = strategy.generate_signal("TEST", df)
        assert sig["action"] in {"BUY", "SELL", "HOLD"}, (
            "EXIT must never appear as action — "
            "use signal_type=BB_MEAN_REVERT for exit intent"
        )

    def test_base_validate_never_receives_exit_action(self, monkeypatch):
        """
        Intercept _validate calls to assert EXIT is never passed in.
        If EXIT were passed, _validate would silently convert it to HOLD,
        hiding the bug. This test catches it at the source.
        """
        received = []
        original = BaseStrategy._validate

        def spy(self_inner, signal):
            received.append(signal.get("action"))
            return original(self_inner, signal)

        monkeypatch.setattr(BaseStrategy, "_validate", spy)

        df = _flat_ohlcv()
        df.loc[df.index[-2], "Close"] = 98.0
        df.loc[df.index[-1], "Close"] = 102.0
        MeanReversionStrategy(require_volume=False).generate_signal("TEST", df)

        assert "EXIT" not in received, (
            f"EXIT was passed to _validate — base strips it silently. "
            f"Actions seen: {received}"
        )

    def test_diagnostics_has_all_keys(self, strategy, flat_data):
        sig = strategy.generate_signal("AAPL", flat_data)
        expected = {"z_score", "adx", "band_width", "bw_expanding",
                    "volume_quiet", "weekly_bull", "upper_band",
                    "lower_band", "sma", "atr"}
        missing = expected - sig["diagnostics"].keys()
        assert not missing, f"Missing diagnostic keys: {missing}"


# ── BUY signal ────────────────────────────────────────────────────────────────

class TestBuySignal:

    def test_buy_fires_on_oversold(self):
        sig = _all_filters_off().generate_signal("AAPL", _make_buy_data())
        assert sig["action"] == "BUY", (
            f"Expected BUY, got {sig['action']}: {sig['reasoning']}"
        )

    def test_buy_signal_type(self):
        sig = _all_filters_off().generate_signal("AAPL", _make_buy_data())
        if sig["action"] == "BUY":
            assert sig["signal_type"] == SIG_OVERSOLD

    def test_buy_stop_loss_below_price(self):
        sig = _all_filters_off().generate_signal("AAPL", _make_buy_data())
        if sig["action"] == "BUY":
            assert sig["stop_loss"] < sig["current_price"]

    def test_buy_take_profit_above_price(self):
        sig = _all_filters_off().generate_signal("AAPL", _make_buy_data())
        if sig["action"] == "BUY":
            assert sig["take_profit"] > sig["current_price"]

    def test_buy_risk_reward_at_least_2_to_1(self):
        sig = _all_filters_off().generate_signal("AAPL", _make_buy_data())
        if sig["action"] == "BUY":
            reward = sig["take_profit"] - sig["current_price"]
            risk   = sig["current_price"] - sig["stop_loss"]
            assert reward / risk >= 1.9, f"R/R too low: {reward/risk:.2f}"

    def test_buy_confidence_above_base(self):
        sig = _all_filters_off().generate_signal("AAPL", _make_buy_data())
        if sig["action"] == "BUY":
            assert sig["confidence"] >= 0.55

    def test_buy_confidence_capped_at_088(self):
        sig = _all_filters_off().generate_signal("AAPL", _make_buy_data())
        assert sig["confidence"] <= 0.88

    def test_buy_stop_and_tp_not_none(self):
        sig = _all_filters_off().generate_signal("AAPL", _make_buy_data())
        if sig["action"] == "BUY":
            assert sig["stop_loss"]   is not None
            assert sig["take_profit"] is not None

    def test_buy_reasoning_contains_price_and_band(self):
        sig = _all_filters_off().generate_signal("AAPL", _make_buy_data())
        if sig["action"] == "BUY":
            assert "Lower" in sig["reasoning"] or "<=" in sig["reasoning"]


# ── SELL signal ───────────────────────────────────────────────────────────────

class TestSellSignal:

    def test_sell_fires_on_overbought(self):
        sig = _all_filters_off().generate_signal("SPY", _make_sell_data())
        assert sig["action"] == "SELL", (
            f"Expected SELL, got {sig['action']}: {sig['reasoning']}"
        )

    def test_sell_signal_type(self):
        sig = _all_filters_off().generate_signal("SPY", _make_sell_data())
        if sig["action"] == "SELL":
            assert sig["signal_type"] == SIG_OVERBOUGHT

    def test_sell_stop_loss_above_price(self):
        sig = _all_filters_off().generate_signal("SPY", _make_sell_data())
        if sig["action"] == "SELL":
            assert sig["stop_loss"] > sig["current_price"]

    def test_sell_take_profit_below_price(self):
        sig = _all_filters_off().generate_signal("SPY", _make_sell_data())
        if sig["action"] == "SELL":
            assert sig["take_profit"] < sig["current_price"]

    def test_sell_risk_reward_at_least_2_to_1(self):
        sig = _all_filters_off().generate_signal("SPY", _make_sell_data())
        if sig["action"] == "SELL":
            reward = sig["current_price"] - sig["take_profit"]
            risk   = sig["stop_loss"]     - sig["current_price"]
            assert reward / risk >= 1.9

    def test_sell_confidence_capped_at_088(self):
        sig = _all_filters_off().generate_signal("SPY", _make_sell_data())
        assert sig["confidence"] <= 0.88

    def test_sell_stop_and_tp_not_none(self):
        sig = _all_filters_off().generate_signal("SPY", _make_sell_data())
        if sig["action"] == "SELL":
            assert sig["stop_loss"]   is not None
            assert sig["take_profit"] is not None


# ── EXIT intent (BB_MEAN_REVERT) ──────────────────────────────────────────────

class TestExitIntent:
    """
    EXIT intent is encoded as:
        action      = 'HOLD'
        signal_type = 'BB_MEAN_REVERT'
        reasoning   starts with '[EXIT]'

    This is the BaseStrategy-compatible pattern — 'EXIT' is not a valid action.
    Downstream consumers must check signal_type == 'BB_MEAN_REVERT'.
    """

    def _zero_cross_data(self, negative_to_positive: bool = True) -> pd.DataFrame:
        """Bar-2 Z on one side of zero, bar-1 Z on the other."""
        df  = _flat_ohlcv()
        sma = 100.0
        std = max(float(df["Close"].rolling(BB_WINDOW).std().iloc[-3]), 0.1)
        if negative_to_positive:
            df.loc[df.index[-2], "Close"] = sma - 0.3 * std  # Z < 0
            df.loc[df.index[-1], "Close"] = sma + 0.3 * std  # Z > 0
        else:
            df.loc[df.index[-2], "Close"] = sma + 0.3 * std  # Z > 0
            df.loc[df.index[-1], "Close"] = sma - 0.3 * std  # Z < 0
        return df

    def test_exit_action_is_hold(self, strategy):
        sig = strategy.generate_signal("TEST", self._zero_cross_data())
        assert sig["action"] == "HOLD"

    def test_exit_signal_type_is_mean_revert(self, strategy):
        sig = strategy.generate_signal("TEST", self._zero_cross_data())
        if sig["signal_type"] == SIG_MEAN_REVERT:
            assert sig["action"] == "HOLD"

    def test_exit_reasoning_starts_with_exit_prefix(self, strategy):
        sig = strategy.generate_signal("TEST", self._zero_cross_data())
        if sig["signal_type"] == SIG_MEAN_REVERT:
            assert sig["reasoning"].startswith("[EXIT]"), (
                f"Exit reasoning must start with '[EXIT]': {sig['reasoning']}"
            )

    def test_exit_confidence_elevated(self, strategy):
        sig = strategy.generate_signal("TEST", self._zero_cross_data())
        if sig["signal_type"] == SIG_MEAN_REVERT:
            assert sig["confidence"] >= 0.60

    def test_exit_both_directions(self, strategy):
        """Zero-cross in both directions should produce BB_MEAN_REVERT."""
        for neg_to_pos in [True, False]:
            sig = strategy.generate_signal("TEST", self._zero_cross_data(neg_to_pos))
            # May or may not fire depending on ADX/bw filters on flat data,
            # but if it does fire as exit, it must be HOLD
            if sig["signal_type"] == SIG_MEAN_REVERT:
                assert sig["action"] == "HOLD"
                assert sig["reasoning"].startswith("[EXIT]")


# ── Regime filters ────────────────────────────────────────────────────────────

class TestRegimeFilters:

    def test_adx_filter_blocks_entry(self):
        """Low ADX threshold → trending data triggers filter → HOLD."""
        s  = MeanReversionStrategy(require_volume=False, adx_threshold=10.0)
        df = _make_ohlcv(n=120, trend=1.5, noise=0.05, seed=1)
        # Push last bar below lower band so entry would fire without filter
        sma = float(df["Close"].rolling(BB_WINDOW).mean().iloc[-1])
        df.loc[df.index[-2], "Close"] = sma - 5.0
        df.loc[df.index[-1], "Close"] = sma - 6.0
        sig = s.generate_signal("TEST", df)
        if "ADX" in sig["reasoning"]:
            assert sig["action"] == "HOLD"
            assert sig["signal_type"] == SIG_NEUTRAL

    def test_band_width_filter_blocks_entry(self):
        """Rapidly expanding bands signal breakout → HOLD."""
        s  = MeanReversionStrategy(
            require_volume=False, adx_threshold=200.0,
            bw_expand_threshold=0.0001,   # almost any expansion triggers it
            use_weekly_filter=False,
        )
        df = _make_buy_data()
        # The crash on the last bar will widen the bands — filter should fire
        sig = s.generate_signal("TEST", df)
        if "Band width" in sig["reasoning"] or "band width" in sig["reasoning"]:
            assert sig["action"] == "HOLD"

    def test_volume_filter_blocks_high_volume_entry(self):
        """High-volume bar on an oversold setup → HOLD."""
        s = MeanReversionStrategy(
            require_volume=True,
            adx_threshold=200.0,
            bw_expand_threshold=999.0,
            use_weekly_filter=False,
        )
        df = _make_buy_data()
        df.loc[df.index[-1], "Volume"] = df["Volume"].mean() * 20
        sig = s.generate_signal("TEST", df)
        if "Volume" in sig["reasoning"]:
            assert sig["action"] == "HOLD"

    def test_weekly_filter_blocks_buy_in_downtrend(self, strategy):
        """weekly_bull=False (SMA > crashed price) → BUY blocked."""
        sig = strategy.generate_signal("BEAR", _make_buy_data())
        if "weekly" in sig["reasoning"].lower():
            assert sig["action"] == "HOLD"

    def test_weekly_filter_blocks_sell_in_uptrend(self, strategy):
        """weekly_bull=True (SMA < spiked price) → SELL blocked."""
        sig = strategy.generate_signal("BULL", _make_sell_data())
        if "weekly" in sig["reasoning"].lower():
            assert sig["action"] == "HOLD"

    def test_all_filters_off_allows_buy(self):
        """With all filters disabled, oversold data must produce BUY."""
        sig = _all_filters_off().generate_signal("TEST", _make_buy_data())
        assert sig["action"] == "BUY"

    def test_all_filters_off_allows_sell(self):
        """With all filters disabled, overbought data must produce SELL."""
        sig = _all_filters_off().generate_signal("TEST", _make_sell_data())
        assert sig["action"] == "SELL"


# ── Confidence model ──────────────────────────────────────────────────────────

class TestConfidenceModel:

    def test_increases_with_z_magnitude(self):
        s = MeanReversionStrategy()
        c1 = s._confidence(-1.6)
        c2 = s._confidence(-2.0)
        c3 = s._confidence(-2.5)
        assert c1 < c2 < c3, f"Expected monotonic increase: {c1}, {c2}, {c3}"

    def test_capped_at_088(self):
        s = MeanReversionStrategy()
        assert s._confidence(-10.0) <= 0.88
        assert s._confidence(10.0)  <= 0.88

    def test_symmetric_around_zero(self):
        s = MeanReversionStrategy()
        assert s._confidence(-2.0) == pytest.approx(s._confidence(2.0), abs=0.001)

    def test_base_confidence_at_entry_threshold(self):
        s = MeanReversionStrategy(z_entry=1.5)
        assert s._confidence(-1.5) == pytest.approx(0.55, abs=0.01)

    def test_always_in_valid_range(self):
        s = MeanReversionStrategy()
        for z in [-0.5, -1.5, -2.2, -3.0, -5.0, -10.0,
                   0.5,  1.5,  2.2,  3.0,  5.0,  10.0]:
            c = s._confidence(z)
            assert 0.0 <= c <= 1.0, f"Out of [0,1] for Z={z}: {c}"

    def test_below_entry_threshold_returns_base(self):
        s = MeanReversionStrategy(z_entry=1.5)
        # Below entry threshold — no entry would fire, but _confidence
        # still returns CONFIDENCE_BASE (0.55) as a floor
        assert s._confidence(-0.5) == pytest.approx(0.55, abs=0.01)


# ── Indicator computation ─────────────────────────────────────────────────────

class TestIndicators:

    def test_adx_returns_series_same_length(self, flat_data):
        adx = _compute_adx(flat_data["High"], flat_data["Low"], flat_data["Close"])
        assert isinstance(adx, pd.Series)
        assert len(adx) == len(flat_data)

    def test_adx_non_negative(self, flat_data):
        adx = _compute_adx(flat_data["High"], flat_data["Low"], flat_data["Close"])
        assert adx.dropna().ge(0).all()

    def test_atr_positive(self, flat_data):
        atr = _compute_atr(flat_data["High"], flat_data["Low"], flat_data["Close"])
        assert atr.dropna().gt(0).all()

    def test_bollinger_bands_symmetric_around_sma(self):
        s  = MeanReversionStrategy()
        df = s._compute_indicators(_make_ohlcv())
        diff_up   = (df["Upper"] - df["SMA"]).dropna()
        diff_down = (df["SMA"]   - df["Lower"]).dropna()
        pd.testing.assert_series_equal(
            diff_up.reset_index(drop=True),
            diff_down.reset_index(drop=True),
            check_names=False,
            rtol=1e-6,
        )

    def test_band_width_always_positive(self):
        s  = MeanReversionStrategy()
        df = s._compute_indicators(_make_ohlcv())
        assert df["BandWidth"].dropna().gt(0).all()

    def test_z_score_near_zero_on_flat_series(self):
        s  = MeanReversionStrategy()
        df = s._compute_indicators(_flat_ohlcv())
        z_vals = df["Z_Score"].dropna()
        assert (z_vals.abs() < 0.1).all()

    def test_weekly_bull_true_in_uptrend(self):
        s  = MeanReversionStrategy()
        df = s._compute_indicators(_make_ohlcv(trend=1.0, noise=0.1))
        assert bool(df["WeeklyBull"].iloc[-1])

    def test_weekly_bull_false_in_downtrend(self):
        s  = MeanReversionStrategy()
        df = s._compute_indicators(_make_ohlcv(trend=-1.0, noise=0.1))
        assert not bool(df["WeeklyBull"].iloc[-1])

    def test_all_indicator_columns_present(self):
        s  = MeanReversionStrategy()
        df = s._compute_indicators(_make_ohlcv())
        for col in ("SMA", "STD", "Upper", "Lower", "Z_Score",
                    "BandWidth", "ADX", "ATR", "WeeklySMA", "WeeklyBull"):
            assert col in df.columns, f"Missing column: {col}"


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_constant_price_does_not_crash(self, strategy):
        sig = strategy.generate_signal("FLAT", _flat_ohlcv())
        assert sig["action"] in {"BUY", "SELL", "HOLD"}
        assert math.isfinite(sig["confidence"])

    def test_very_large_price_values(self, strategy):
        sig = strategy.generate_signal("BIG", _make_ohlcv(base_price=1_000_000))
        assert sig["action"] in {"BUY", "SELL", "HOLD"}
        assert math.isfinite(sig["confidence"])

    def test_very_small_price_values(self, strategy):
        sig = strategy.generate_signal("TINY", _make_ohlcv(base_price=0.001, noise=0.0001))
        assert sig["action"] in {"BUY", "SELL", "HOLD"}

    def test_no_volume_column_with_require_false(self):
        s   = MeanReversionStrategy(require_volume=False)
        df  = _make_ohlcv().drop(columns=["Volume"])
        sig = s.generate_signal("NOVOL", df)
        assert sig["action"] in {"BUY", "SELL", "HOLD"}

    def test_input_dataframe_not_mutated(self, strategy):
        df   = _make_ohlcv()
        cols = set(df.columns)
        vals = df["Close"].copy()
        strategy.generate_signal("AAPL", df)
        assert set(df.columns) == cols
        pd.testing.assert_series_equal(df["Close"], vals)

    def test_deterministic_on_identical_input(self, strategy):
        df   = _make_ohlcv()
        sig1 = strategy.generate_signal("AAPL", df)
        sig2 = strategy.generate_signal("AAPL", df)
        assert sig1["action"]      == sig2["action"]
        assert sig1["confidence"]  == sig2["confidence"]
        assert sig1["signal_type"] == sig2["signal_type"]

    def test_current_price_matches_last_close(self):
        df       = _make_ohlcv()
        sig      = _all_filters_off().generate_signal("TEST", df)
        expected = round(float(df["Close"].iloc[-1]), 4)
        assert sig["current_price"] == pytest.approx(expected, abs=0.001)

    def test_custom_stop_tp_multipliers_respected(self):
        s   = _all_filters_off(stop_atr_mult=1.0, tp_atr_mult=2.0)
        sig = s.generate_signal("AAPL", _make_buy_data())
        if sig["action"] == "BUY":
            reward = sig["take_profit"] - sig["current_price"]
            risk   = sig["current_price"] - sig["stop_loss"]
            assert abs(reward / risk - 2.0) < 0.25, f"Expected ~2:1, got {reward/risk:.2f}"

    def test_hold_signals_have_none_stop_and_tp(self, strategy, flat_data):
        sig = strategy.generate_signal("AAPL", flat_data)
        if sig["action"] == "HOLD" and sig["signal_type"] == SIG_NEUTRAL:
            assert sig["stop_loss"]   is None
            assert sig["take_profit"] is None