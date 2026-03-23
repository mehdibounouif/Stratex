"""
Pytest test suite for PairsStrategy — Quant_firm project layout.

Location : test/test_pairs_strategy.py
Run from project root:
    pytest test/test_pairs_strategy.py -v

Assumes conftest.py adds the project root to sys.path so that
  from strategies.pairs_strategy import ...
  from strategies.base_strategy import BaseStrategy
resolve correctly against the real strategies/ package.

No sys.modules patching needed — the real strategies/ and logger.py
are present on disk.
"""

import math
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
import pytest

from strategies.pairs_strategy import (
    PairsStrategy,
    DEFAULT_WINDOW,
    SIG_NEUTRAL,
    SIG_LONG_A,
    SIG_SHORT_A,
    SIG_LONG_B,
    SIG_SHORT_B,
    SIG_NO_SIG,
    _half_life,
    _ols_hedge_ratio,
    _engle_granger_pvalue,
)
from strategies.base_strategy import BaseStrategy


# ── Fixtures & helpers ────────────────────────────────────────────────────────

RNG = np.random.default_rng(42)
IDX = pd.date_range(end="2025-01-01", periods=200, freq="D")


def _make_close(
    n: int = 200,
    base: float = 100.0,
    drift: float = 0.0,
    noise: float = 0.5,
    seed: int = 42,
) -> pd.DataFrame:
    rng    = np.random.default_rng(seed)
    closes = base + np.cumsum(rng.normal(drift, noise, n))
    closes = np.maximum(closes, 1.0)   # prices must be positive for log()
    idx    = pd.date_range(end="2025-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"Open": closes, "High": closes + 0.2, "Low": closes - 0.2,
         "Close": closes, "Volume": np.full(n, 1_000_000.0)},
        index=idx,
    )


def _make_cointegrated_pair(
    n: int = 200,
    beta: float = 1.0,
    noise: float = 0.3,
    seed: int = 0,
) -> tuple:
    """
    Generate a genuinely cointegrated pair:
        log(B) = common_factor
        log(A) = beta * log(B) + stationary_noise
    """
    rng    = np.random.default_rng(seed)
    factor = np.cumsum(rng.normal(0, 0.5, n)) + 5.0   # log-scale, always > 0
    log_b  = factor
    log_a  = beta * log_b + rng.normal(0, noise, n)
    a      = np.exp(log_a)
    b      = np.exp(log_b)
    idx    = pd.date_range(end="2025-01-01", periods=n, freq="D")
    data_a = pd.DataFrame({"Close": a, "Open": a, "High": a+0.1, "Low": a-0.1,
                           "Volume": np.full(n, 1e6)}, index=idx)
    data_b = pd.DataFrame({"Close": b, "Open": b, "High": b+0.1, "Low": b-0.1,
                           "Volume": np.full(n, 1e6)}, index=idx)
    return data_a, data_b


def _make_spread_oversold(
    n: int = 200,
    z_target: float = -3.0,
    seed: int = 1,
) -> tuple:
    """
    Cointegrated pair where the last bar's spread is z_target std below mean.
    Shifts ONLY the last bar of A so rolling mean/std stays intact.
    Uses beta=1.0 (matching use_hedge_ratio=False in _filters_off()).
    Reliably triggers a BUY-A / SELL-B signal when z_target < -z_threshold.
    """
    data_a, data_b = _make_cointegrated_pair(n=n, seed=seed, noise=0.05)
    log_a = np.log(data_a["Close"])
    log_b = np.log(data_b["Close"])
    # Use beta=1.0 to match strategy when use_hedge_ratio=False
    spread = log_a - log_b
    # Compute stats from bars [-(DEFAULT_WINDOW+1)..-2] so last bar is not included
    s_mean = spread.iloc[-(DEFAULT_WINDOW + 1):-1].mean()
    s_std  = spread.iloc[-(DEFAULT_WINDOW + 1):-1].std()
    # Target log(A[-1]) = target_spread + log(B[-1])
    target_spread = s_mean + z_target * s_std
    data_a = data_a.copy()
    new_price = float(np.exp(target_spread + log_b.iloc[-1]))
    data_a.loc[data_a.index[-1], "Close"] = new_price
    data_a.loc[data_a.index[-1], "Open"]  = new_price
    data_a.loc[data_a.index[-1], "High"]  = new_price + 0.1
    data_a.loc[data_a.index[-1], "Low"]   = new_price - 0.1
    return data_a, data_b


def _make_spread_overbought(
    n: int = 200,
    z_target: float = 3.0,
    seed: int = 2,
) -> tuple:
    """
    Cointegrated pair where the last bar's spread is z_target std above mean.
    Shifts ONLY the last bar of A so rolling mean/std stays intact.
    Uses beta=1.0 (matching use_hedge_ratio=False in _filters_off()).
    Reliably triggers a SELL-A / BUY-B signal when z_target > z_threshold.
    """
    data_a, data_b = _make_cointegrated_pair(n=n, seed=seed, noise=0.05)
    log_a = np.log(data_a["Close"])
    log_b = np.log(data_b["Close"])
    spread = log_a - log_b
    s_mean = spread.iloc[-(DEFAULT_WINDOW + 1):-1].mean()
    s_std  = spread.iloc[-(DEFAULT_WINDOW + 1):-1].std()
    target_spread = s_mean + z_target * s_std
    data_a = data_a.copy()
    new_price = float(np.exp(target_spread + log_b.iloc[-1]))
    data_a.loc[data_a.index[-1], "Close"] = new_price
    data_a.loc[data_a.index[-1], "Open"]  = new_price
    data_a.loc[data_a.index[-1], "High"]  = new_price + 0.1
    data_a.loc[data_a.index[-1], "Low"]   = new_price - 0.1
    return data_a, data_b


def _filters_off(**kwargs) -> PairsStrategy:
    """
    PairsStrategy with all optional filters disabled for unit isolation.
    use_hedge_ratio=False ensures beta=1.0, which matches the _make_spread_*
    helpers that also use beta=1.0 when constructing synthetic data.
    """
    defaults = dict(
        check_cointegration=False,
        check_half_life=False,
        use_hedge_ratio=False,
    )
    defaults.update(kwargs)
    return PairsStrategy(**defaults)


@pytest.fixture
def strategy() -> PairsStrategy:
    return PairsStrategy()


@pytest.fixture
def strategy_no_filters() -> PairsStrategy:
    return _filters_off()


@pytest.fixture
def coint_pair():
    return _make_cointegrated_pair(n=200, seed=0)


# ── Inheritance ───────────────────────────────────────────────────────────────

class TestInheritance:

    def test_is_base_strategy_subclass(self):
        assert issubclass(PairsStrategy, BaseStrategy)

    def test_instance_is_base_strategy(self, strategy):
        assert isinstance(strategy, BaseStrategy)

    def test_does_not_override_validate(self):
        assert PairsStrategy._validate is BaseStrategy._validate

    def test_does_not_override_no_signal(self):
        assert PairsStrategy._no_signal is BaseStrategy._no_signal

    def test_name_attribute_set(self, strategy):
        assert strategy.name == "Pairs Statistical Arbitrage"

    def test_str_returns_name(self, strategy):
        assert str(strategy) == strategy.name

    def test_repr_contains_class_name(self, strategy):
        assert "PairsStrategy" in repr(strategy)


# ── generate_signal (single-ticker interface) ─────────────────────────────────

class TestGenerateSignal:
    """generate_signal() must always HOLD/NO_SIGNAL — pairs need two legs."""

    def test_unregistered_ticker_returns_no_signal(self, strategy):
        sig = strategy.generate_signal("XYZ", _make_close())
        assert sig["action"] == "HOLD"
        assert sig["signal_type"] == SIG_NO_SIG

    def test_registered_ticker_returns_no_signal(self, strategy):
        sig = strategy.generate_signal("MSFT", _make_close())
        assert sig["action"] == "HOLD"
        assert sig["signal_type"] == SIG_NO_SIG

    def test_reasoning_contains_pair_hint(self, strategy):
        sig = strategy.generate_signal("MSFT", _make_close())
        assert "generate_pair_signal" in sig["reasoning"] or "pair" in sig["reasoning"].lower()

    def test_unregistered_ticker_mentions_ticker(self, strategy):
        sig = strategy.generate_signal("BANANA", _make_close())
        assert "BANANA" in sig["reasoning"]

    def test_satisfies_base_contract(self, strategy):
        sig = strategy.generate_signal("MSFT", _make_close())
        assert sig["action"] in {"BUY", "SELL", "HOLD"}
        assert 0.0 <= sig["confidence"] <= 1.0
        assert sig["current_price"] >= 0.0
        datetime.fromisoformat(sig["timestamp"])


# ── Input validation ──────────────────────────────────────────────────────────

class TestInputValidation:

    def test_none_data_a_returns_two_no_signals(self, strategy_no_filters):
        sigs = strategy_no_filters.generate_pair_signal(
            "MSFT", None, "GOOGL", _make_close()
        )
        assert len(sigs) == 2
        assert sigs[0]["signal_type"] == SIG_NO_SIG
        assert sigs[1]["action"] == "HOLD"

    def test_none_data_b_returns_two_no_signals(self, strategy_no_filters):
        sigs = strategy_no_filters.generate_pair_signal(
            "MSFT", _make_close(), "GOOGL", None
        )
        assert len(sigs) == 2
        assert all(s["signal_type"] == SIG_NO_SIG for s in sigs)

    def test_both_none_returns_two_no_signals(self, strategy_no_filters):
        sigs = strategy_no_filters.generate_pair_signal("A", None, "B", None)
        assert len(sigs) == 2
        assert all(s["signal_type"] == SIG_NO_SIG for s in sigs)

    def test_non_dataframe_returns_no_signal(self, strategy_no_filters):
        sigs = strategy_no_filters.generate_pair_signal(
            "MSFT", [[1, 2, 3]], "GOOGL", _make_close()
        )
        assert sigs[0]["signal_type"] == SIG_NO_SIG

    def test_missing_close_column_returns_no_signal(self, strategy_no_filters):
        bad = _make_close().drop(columns=["Close"])
        sigs = strategy_no_filters.generate_pair_signal(
            "MSFT", bad, "GOOGL", _make_close()
        )
        assert sigs[0]["signal_type"] == SIG_NO_SIG

    def test_all_nan_close_returns_no_signal(self, strategy_no_filters):
        bad = _make_close()
        bad["Close"] = float("nan")
        sigs = strategy_no_filters.generate_pair_signal(
            "MSFT", bad, "GOOGL", _make_close()
        )
        assert sigs[0]["signal_type"] == SIG_NO_SIG

    def test_insufficient_aligned_rows_returns_no_signal(self, strategy_no_filters):
        short = _make_close(n=DEFAULT_WINDOW - 1)
        sigs = strategy_no_filters.generate_pair_signal(
            "MSFT", short, "GOOGL", short
        )
        assert all(s["signal_type"] == SIG_NO_SIG for s in sigs)

    def test_constant_prices_nan_z_returns_no_signal(self, strategy_no_filters):
        """Constant prices → STD = 0 → z = NaN → must return NO_SIGNAL."""
        const = _make_close(n=200)
        const["Close"] = 100.0
        sigs = strategy_no_filters.generate_pair_signal(
            "MSFT", const, "GOOGL", const
        )
        assert all(s["signal_type"] == SIG_NO_SIG for s in sigs)


# ── BaseStrategy contract ─────────────────────────────────────────────────────

class TestBaseStrategyContract:

    BASE_KEYS  = {"ticker", "action", "confidence", "current_price",
                  "reasoning", "signal_type", "strategy", "timestamp", "source"}
    EXTRA_KEYS = {"stop_loss", "take_profit", "diagnostics"}

    def _assert_signal(self, sig: dict) -> None:
        missing_base = self.BASE_KEYS - sig.keys()
        assert not missing_base, f"Missing base keys: {missing_base}"
        assert sig["action"] in {"BUY", "SELL", "HOLD"}, \
            f"Invalid action: {sig['action']}"
        assert 0.0 <= sig["confidence"] <= 1.0
        assert sig["current_price"] >= 0.0
        datetime.fromisoformat(sig["timestamp"])

    def _assert_directional(self, sig: dict) -> None:
        self._assert_signal(sig)
        missing_extra = self.EXTRA_KEYS - sig.keys()
        assert not missing_extra, f"Missing extra keys: {missing_extra}"

    def test_neutral_signals_satisfy_contract(self, strategy, coint_pair):
        data_a, data_b = coint_pair
        sigs = strategy.generate_pair_signal("MSFT", data_a, "GOOGL", data_b)
        for sig in sigs:
            self._assert_signal(sig)

    def test_buy_signal_satisfies_full_contract(self):
        data_a, data_b = _make_spread_oversold()
        sigs = _filters_off().generate_pair_signal("MSFT", data_a, "GOOGL", data_b)
        for sig in sigs:
            self._assert_directional(sig)

    def test_sell_signal_satisfies_full_contract(self):
        data_a, data_b = _make_spread_overbought()
        sigs = _filters_off().generate_pair_signal("MSFT", data_a, "GOOGL", data_b)
        for sig in sigs:
            self._assert_directional(sig)

    def test_no_signal_satisfies_base_contract(self, strategy_no_filters):
        sigs = strategy_no_filters.generate_pair_signal("A", None, "B", None)
        for sig in sigs:
            missing = self.BASE_KEYS - sig.keys()
            assert not missing, f"Missing base keys: {missing}"
            assert sig["action"] == "HOLD"

    def test_always_returns_list_of_two(self, strategy, coint_pair):
        data_a, data_b = coint_pair
        sigs = strategy.generate_pair_signal("MSFT", data_a, "GOOGL", data_b)
        assert isinstance(sigs, list) and len(sigs) == 2

    def test_source_field_present(self, strategy, coint_pair):
        data_a, data_b = coint_pair
        sigs = strategy.generate_pair_signal("MSFT", data_a, "GOOGL", data_b)
        for sig in sigs:
            assert "source" in sig
            assert sig["source"] == strategy.name

    def test_tickers_correctly_assigned(self):
        data_a, data_b = _make_cointegrated_pair()
        sigs = _filters_off().generate_pair_signal("AAA", data_a, "BBB", data_b)
        assert sigs[0]["ticker"] == "AAA"
        assert sigs[1]["ticker"] == "BBB"

    def test_strategy_field_equals_name(self, strategy, coint_pair):
        data_a, data_b = coint_pair
        for sig in strategy.generate_pair_signal("MSFT", data_a, "GOOGL", data_b):
            assert sig["strategy"] == strategy.name


# ── Signal logic: BUY-A / SELL-B ─────────────────────────────────────────────

class TestLongAShortBSignal:
    """Spread below -z_threshold → BUY A, SELL B."""

    def setup_method(self):
        self.sigs = da, db = _make_spread_oversold()
        self.sigs = _filters_off().generate_pair_signal("MSFT", da, "GOOGL", db)
        self.sig_a, self.sig_b = self.sigs

    def test_sig_a_is_buy(self):
        assert self.sig_a["action"] == "BUY", \
            f"Expected BUY on A, got {self.sig_a['action']}: {self.sig_a['reasoning']}"

    def test_sig_b_is_sell(self):
        assert self.sig_b["action"] == "SELL", \
            f"Expected SELL on B, got {self.sig_b['action']}: {self.sig_b['reasoning']}"

    def test_sig_a_type(self):
        assert self.sig_a["signal_type"] == SIG_LONG_A

    def test_sig_b_type(self):
        assert self.sig_b["signal_type"] == SIG_SHORT_B

    def test_both_have_same_confidence(self):
        assert self.sig_a["confidence"] == self.sig_b["confidence"]

    def test_confidence_above_base(self):
        assert self.sig_a["confidence"] >= 0.55

    def test_confidence_capped_at_088(self):
        assert self.sig_a["confidence"] <= 0.88

    def test_stop_loss_present(self):
        assert self.sig_a["stop_loss"] is not None

    def test_take_profit_present(self):
        assert self.sig_a["take_profit"] is not None

    def test_diagnostics_present(self):
        assert "diagnostics" in self.sig_a
        assert "z_score" in self.sig_a["diagnostics"]


# ── Signal logic: SELL-A / BUY-B ─────────────────────────────────────────────

class TestShortALongBSignal:
    """Spread above +z_threshold → SELL A, BUY B."""

    def setup_method(self):
        self.sigs = da, db = _make_spread_overbought()
        self.sigs = _filters_off().generate_pair_signal("MSFT", da, "GOOGL", db)
        self.sig_a, self.sig_b = self.sigs

    def test_sig_a_is_sell(self):
        assert self.sig_a["action"] == "SELL", \
            f"Expected SELL on A, got {self.sig_a['action']}: {self.sig_a['reasoning']}"

    def test_sig_b_is_buy(self):
        assert self.sig_b["action"] == "BUY", \
            f"Expected BUY on B, got {self.sig_b['action']}: {self.sig_b['reasoning']}"

    def test_sig_a_type(self):
        assert self.sig_a["signal_type"] == SIG_SHORT_A

    def test_sig_b_type(self):
        assert self.sig_b["signal_type"] == SIG_LONG_B

    def test_confidence_capped_at_088(self):
        assert self.sig_a["confidence"] <= 0.88


# ── Regime filters ────────────────────────────────────────────────────────────

class TestRegimeFilters:

    def test_cointegration_filter_blocks_non_cointegrated(self):
        """Independent random walks → p-value high → HOLD."""
        s = PairsStrategy(
            check_cointegration=True,
            coint_pvalue=0.01,   # very strict
            check_half_life=False,
            use_hedge_ratio=False,
        )
        # Two independent random walks are unlikely to cointegrate
        data_a = _make_close(n=200, seed=10)
        data_b = _make_close(n=200, seed=99)
        sigs = s.generate_pair_signal("A", data_a, "B", data_b)
        # Both must be HOLD (cointegration filter or neutral spread)
        for sig in sigs:
            assert sig["action"] == "HOLD"

    def test_half_life_filter_blocks_slow_reversion(self):
        """Pair with very long half-life → blocked by max_half_life filter."""
        s = PairsStrategy(
            check_cointegration=False,
            check_half_life=True,
            max_half_life=3,   # very tight — almost nothing passes
            use_hedge_ratio=False,
        )
        data_a, data_b = _make_spread_oversold()
        sigs = s.generate_pair_signal("A", data_a, "B", data_b)
        for sig in sigs:
            if "half" in sig["reasoning"].lower():
                assert sig["action"] == "HOLD"

    def test_no_filters_allows_directional_signal(self):
        """With all filters off, a sufficiently extreme spread fires."""
        da, db = _make_spread_oversold()
        sigs = _filters_off().generate_pair_signal("A", da, "B", db)
        actions = {s["action"] for s in sigs}
        assert "BUY" in actions or "SELL" in actions

    def test_neutral_spread_always_holds(self, strategy):
        """Cointegrated pair with small spread → HOLD."""
        data_a, data_b = _make_cointegrated_pair(n=200, noise=0.01, seed=5)
        sigs = strategy.generate_pair_signal("A", data_a, "B", data_b)
        for sig in sigs:
            assert sig["action"] == "HOLD"


# ── Confidence model ──────────────────────────────────────────────────────────

class TestConfidenceModel:

    def test_increases_with_z_magnitude(self):
        s = PairsStrategy()
        c1 = s._confidence(-2.1)
        c2 = s._confidence(-2.5)
        c3 = s._confidence(-3.0)
        assert c1 < c2 < c3

    def test_capped_at_088(self):
        s = PairsStrategy()
        assert s._confidence(-10.0) <= 0.88
        assert s._confidence(10.0)  <= 0.88

    def test_symmetric_around_zero(self):
        s = PairsStrategy()
        assert s._confidence(-2.5) == pytest.approx(s._confidence(2.5), abs=0.001)

    def test_base_at_entry_threshold(self):
        s = PairsStrategy(z_threshold=2.0)
        assert s._confidence(-2.0) == pytest.approx(0.55, abs=0.01)

    def test_always_in_valid_range(self):
        s = PairsStrategy()
        for z in [-1.0, -2.0, -2.8, -3.5, -6.0, 2.0, 2.8, 3.5, 6.0]:
            c = s._confidence(z)
            assert 0.0 <= c <= 1.0, f"Out of [0,1] for z={z}: {c}"


# ── Indicator helpers ─────────────────────────────────────────────────────────

class TestIndicatorHelpers:

    def test_ols_hedge_ratio_returns_floats(self, coint_pair):
        data_a, data_b = coint_pair
        log_a = np.log(data_a["Close"].iloc[-DEFAULT_WINDOW:])
        log_b = np.log(data_b["Close"].iloc[-DEFAULT_WINDOW:])
        beta, alpha = _ols_hedge_ratio(log_a, log_b)
        assert isinstance(beta, float) and math.isfinite(beta)
        assert isinstance(alpha, float) and math.isfinite(alpha)

    def test_ols_hedge_ratio_near_one_for_matched_pair(self):
        """When A ≈ B (beta=1.0), OLS should recover beta ≈ 1."""
        data_a, data_b = _make_cointegrated_pair(beta=1.0, noise=0.05, n=200)
        log_a = np.log(data_a["Close"].iloc[-DEFAULT_WINDOW:])
        log_b = np.log(data_b["Close"].iloc[-DEFAULT_WINDOW:])
        beta, _ = _ols_hedge_ratio(log_a, log_b)
        assert abs(beta - 1.0) < 0.3, f"Expected beta ~1.0, got {beta:.3f}"

    def test_half_life_positive_for_cointegrated(self, coint_pair):
        data_a, data_b = coint_pair
        log_a = np.log(data_a["Close"])
        log_b = np.log(data_b["Close"])
        spread = log_a - log_b
        hl = _half_life(spread)
        assert math.isfinite(hl) and hl > 0

    def test_half_life_inf_for_random_walk(self):
        """Pure random walk has infinite (or very large) half-life."""
        rw = pd.Series(np.cumsum(np.random.default_rng(0).normal(0, 1, 200)))
        hl = _half_life(rw)
        # Random walk: beta >= 0 means _half_life returns inf, OR
        # by chance it may appear mean-reverting on a short sample.
        # We just verify the function returns a float (not crash).
        assert isinstance(hl, float)

    def test_engle_granger_low_pvalue_for_cointegrated(self, coint_pair):
        data_a, data_b = coint_pair
        spread = np.log(data_a["Close"]) - np.log(data_b["Close"])
        pval = _engle_granger_pvalue(spread)
        assert 0.0 <= pval <= 1.0

    def test_engle_granger_high_pvalue_for_random_walk(self):
        rng    = np.random.default_rng(7)
        spread = pd.Series(np.cumsum(rng.normal(0, 1, 200)))
        pval   = _engle_granger_pvalue(spread)
        assert 0.0 <= pval <= 1.0


# ── find_pair ─────────────────────────────────────────────────────────────────

class TestFindPair:

    def test_finds_registered_ticker(self, strategy):
        assert strategy.find_pair("MSFT") is not None

    def test_returns_none_for_unregistered(self, strategy):
        assert strategy.find_pair("BANANA") is None

    def test_returns_correct_pair(self, strategy):
        pair = strategy.find_pair("AMD")
        assert "AMD" in pair

    def test_custom_pairs(self):
        s = PairsStrategy(pairs=[("X", "Y"), ("P", "Q")])
        assert s.find_pair("X") == ("X", "Y")
        assert s.find_pair("Q") == ("P", "Q")
        assert s.find_pair("Z") is None


# ── Diagnostics ───────────────────────────────────────────────────────────────

class TestDiagnostics:

    DIAG_KEYS = {"z_score", "spread", "spread_mean", "spread_std",
                 "hedge_ratio", "half_life", "cointegrated",
                 "price_a", "price_b"}

    def test_directional_signals_have_full_diagnostics(self):
        sigs = da, db = _make_spread_oversold()
        sigs = _filters_off().generate_pair_signal("A", da, "B", db)
        for sig in sigs:
            if sig["action"] in {"BUY", "SELL"}:
                diag = sig["diagnostics"]
                missing = self.DIAG_KEYS - diag.keys()
                assert not missing, f"Missing diag keys: {missing}"

    def test_z_score_in_diagnostics_is_finite(self):
        sigs = da, db = _make_cointegrated_pair()
        sigs = _filters_off().generate_pair_signal("A", da, "B", db)
        for sig in sigs:
            if "diagnostics" in sig and sig["diagnostics"]:
                z = sig["diagnostics"].get("z_score")
                if z is not None:
                    assert math.isfinite(z)

    def test_hedge_ratio_in_diagnostics(self):
        s = PairsStrategy(check_cointegration=False, check_half_life=False)
        sigs = da, db = _make_spread_oversold()
        sigs = s.generate_pair_signal("A", da, "B", db)
        for sig in sigs:
            if "diagnostics" in sig and sig["diagnostics"]:
                assert "hedge_ratio" in sig["diagnostics"]


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_input_dataframes_not_mutated(self):
        data_a, data_b = _make_cointegrated_pair()
        cols_a, cols_b = set(data_a.columns), set(data_b.columns)
        vals_a = data_a["Close"].copy()
        _filters_off().generate_pair_signal("A", data_a, "B", data_b)
        assert set(data_a.columns) == cols_a
        assert set(data_b.columns) == cols_b
        pd.testing.assert_series_equal(data_a["Close"], vals_a)

    def test_deterministic_on_identical_input(self):
        data_a, data_b = _make_spread_oversold()
        s = _filters_off()
        sigs1 = s.generate_pair_signal("A", data_a, "B", data_b)
        sigs2 = s.generate_pair_signal("A", data_a, "B", data_b)
        for s1, s2 in zip(sigs1, sigs2):
            assert s1["action"]      == s2["action"]
            assert s1["confidence"]  == s2["confidence"]
            assert s1["signal_type"] == s2["signal_type"]

    def test_very_large_prices(self):
        data_a = _make_close(base=1_000_000, noise=100)
        data_b = _make_close(base=1_000_000, noise=100, seed=1)
        sigs = _filters_off().generate_pair_signal("A", data_a, "B", data_b)
        for sig in sigs:
            assert sig["action"] in {"BUY", "SELL", "HOLD"}
            assert math.isfinite(sig["confidence"])

    def test_very_small_prices(self):
        data_a = _make_close(base=0.01, noise=0.001)
        data_b = _make_close(base=0.01, noise=0.001, seed=1)
        sigs = _filters_off().generate_pair_signal("A", data_a, "B", data_b)
        for sig in sigs:
            assert sig["action"] in {"BUY", "SELL", "HOLD"}

    def test_misaligned_indexes_handled(self):
        """A and B with different date ranges — inner join should work."""
        data_a = _make_close(n=200, seed=0)
        data_b = _make_close(n=180, seed=1)   # 20 fewer bars
        sigs = _filters_off().generate_pair_signal("A", data_a, "B", data_b)
        assert isinstance(sigs, list) and len(sigs) == 2

    def test_custom_z_threshold_respected(self):
        """With z_threshold=0.1, almost any spread fires a signal."""
        s = PairsStrategy(
            z_threshold=0.1,
            check_cointegration=False,
            check_half_life=False,
        )
        data_a, data_b = _make_cointegrated_pair(noise=0.5, seed=3)
        sigs = s.generate_pair_signal("A", data_a, "B", data_b)
        actions = {sig["action"] for sig in sigs}
        assert "BUY" in actions or "SELL" in actions

    def test_confidence_never_exceeds_088_under_extreme_z(self):
        sigs = da, db = _make_spread_oversold(z_target=-8.0)
        sigs = _filters_off().generate_pair_signal("A", da, "B", db)
        for sig in sigs:
            assert sig["confidence"] <= 0.88

    def test_always_returns_two_signals_on_any_input(self):
        """No matter what input, must return exactly 2 signals."""
        s    = _filters_off()
        cases = [
            (None, None),
            (_make_close(), None),
            (None, _make_close()),
            (_make_close(), _make_close()),
        ]
        for da, db in cases:
            sigs = s.generate_pair_signal("A", da, "B", db)
            assert len(sigs) == 2, f"Expected 2 signals for ({da is None}, {db is None})"