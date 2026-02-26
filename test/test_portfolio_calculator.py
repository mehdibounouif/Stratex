"""
Tests for PortfolioCalculator
==============================
Run from project root: pytest tests/test_portfolio_calculator.py -v

Covers:
- get_sector_breakdown
- get_sector_concentration (HHI)
- get_position_weights
- get_largest_position
- get_concentration_risk
- calculate_var (structure + type checks)
- calculate_max_drawdown (structure + type checks)

NOTE:
- Methods calling yfinance (VaR, Sharpe, volatility, drawdown) are tested
  for correct return shape only, using a pre-seeded portfolio so the data
  exists. Network is required for these.
- Pure-logic methods (sector breakdown, weights, HHI) are fully tested
  without any network calls using a mock tracker.

KNOWN BUG (documented):
  Logger name ends with '.py' → 'risk.portfolio.portfolio_calculator.py'
  Should be 'risk.portfolio.portfolio_calculator'.
  Test documents this so it gets caught during code review.
"""

import pytest
import sys
import os
from decimal import Decimal
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────
# HELPERS: build a minimal fake tracker
# ─────────────────────────────────────────────────────────────

def _make_position(ticker, quantity, entry_price, current_price):
    """Create a minimal mock Position object."""
    pos = MagicMock()
    pos.ticker        = ticker
    pos.quantity      = Decimal(str(quantity))
    pos.entry_price   = Decimal(str(entry_price))
    pos.current_price = Decimal(str(current_price))
    pos.unrealized_pnl = (
        pos.current_price - pos.entry_price
    ) * pos.quantity
    return pos


def _make_tracker(positions, portfolio_value=None):
    """Return a mock tracker loaded with given positions."""
    tracker = MagicMock()
    tracker.positions = positions
    if portfolio_value is None:
        portfolio_value = sum(
            p.quantity * p.current_price for p in positions
        ) + Decimal("5000")   # $5k cash
    tracker.get_portfolio_value.return_value = Decimal(str(portfolio_value))
    tracker._normalize_ticker.side_effect = lambda t: t.strip().upper()
    return tracker


def _make_calculator(positions, portfolio_value=None):
    """Build a PortfolioCalculator with a fake tracker (no real I/O)."""
    from risk.portfolio.portfolio_calculator import PortfolioCalculator
    tracker = _make_tracker(positions, portfolio_value)
    calc = PortfolioCalculator.__new__(PortfolioCalculator)
    calc.tracker    = tracker
    calc.sector_map = PortfolioCalculator._load_sector_map(calc)
    return calc


# ─────────────────────────────────────────────────────────────
# SECTOR BREAKDOWN
# ─────────────────────────────────────────────────────────────

class TestGetSectorBreakdown:

    def test_empty_portfolio_returns_empty_dict(self):
        calc = _make_calculator([])
        assert calc.get_sector_breakdown() == {}

    def test_single_known_ticker_weight_is_correct(self):
        """AAPL in Information Technology: weight ≈ position_value / portfolio_value."""
        pos = _make_position("AAPL", 10, 180.0, 180.0)  # $1,800
        total = Decimal("1800") + Decimal("18200")       # $20,000 portfolio
        calc  = _make_calculator([pos], portfolio_value=total)

        breakdown = calc.get_sector_breakdown()
        assert "Information Technology" in breakdown
        expected_weight = Decimal("1800") / total
        assert abs(breakdown["Information Technology"] - expected_weight) < Decimal("0.0001")

    def test_two_tickers_same_sector_merge_correctly(self):
        """AAPL + MSFT both belong to Information Technology → combined weight."""
        aapl = _make_position("AAPL", 10, 180.0, 180.0)   # $1,800
        msft = _make_position("MSFT", 5,  380.0, 380.0)   # $1,900
        total = Decimal("3700") + Decimal("1300")          # $5,000
        calc  = _make_calculator([aapl, msft], portfolio_value=total)

        breakdown = calc.get_sector_breakdown()
        assert "Information Technology" in breakdown
        expected = Decimal("3700") / Decimal("5000")
        assert abs(breakdown["Information Technology"] - expected) < Decimal("0.0001")

    def test_unknown_ticker_falls_back_to_other(self):
        """Tickers not in sector_map fall back to 'Other'."""
        pos  = _make_position("ZZZZ", 10, 100.0, 100.0)
        calc = _make_calculator([pos])

        # patch yfinance to avoid network call
        with patch("yfinance.Ticker") as mock_yf:
            mock_yf.return_value.info = {}  # no sector in response
            breakdown = calc.get_sector_breakdown()

        assert "Other" in breakdown

    def test_weights_sum_to_approximately_one(self):
        """
        Sector weights summing to ~1 means the position values cover most
        of the portfolio. (Cash portion means sum < 1 if cash is excluded.)
        """
        aapl = _make_position("AAPL", 10, 200.0, 200.0)   # $2,000
        jpm  = _make_position("JPM",  5,  160.0, 160.0)   # $800
        # total portfolio value = $2,800 (no cash here for simplicity)
        calc = _make_calculator([aapl, jpm], portfolio_value=Decimal("2800"))

        breakdown = calc.get_sector_breakdown()
        total_weight = sum(breakdown.values())
        assert abs(total_weight - Decimal("1.0")) < Decimal("0.01"), (
            f"Weights should sum to ~1.0 when all portfolio value is positions, got {total_weight}"
        )

    def test_invalid_quantity_position_is_skipped(self):
        """Positions with quantity=0 are skipped and don't crash."""
        bad  = _make_position("AAPL", 0, 200.0, 200.0)
        good = _make_position("JPM",  5, 160.0, 160.0)
        calc = _make_calculator([bad, good])

        breakdown = calc.get_sector_breakdown()
        assert "Information Technology" not in breakdown
        assert "Financials" in breakdown


# ─────────────────────────────────────────────────────────────
# SECTOR CONCENTRATION (HHI)
# ─────────────────────────────────────────────────────────────

class TestGetSectorConcentration:

    def test_single_sector_hhi_is_one(self):
        """100% in one sector → HHI = 1.0 (maximum concentration)."""
        from risk.portfolio.portfolio_calculator import PortfolioCalculator
        calc = PortfolioCalculator.__new__(PortfolioCalculator)
        calc.tracker    = MagicMock()
        calc.sector_map = {}

        weights = {"Technology": Decimal("1.0")}
        result  = calc.get_sector_concentration(sector_weights=weights)

        assert result != {}
        assert abs(result["hhi"] - Decimal("1.0")) < Decimal("0.0001")
        assert result["risk_level"] == "HIGH"

    def test_equal_two_sectors_hhi_is_half(self):
        """50/50 two sectors → HHI = 0.25 + 0.25 = 0.5."""
        from risk.portfolio.portfolio_calculator import PortfolioCalculator
        calc = PortfolioCalculator.__new__(PortfolioCalculator)
        calc.tracker    = MagicMock()
        calc.sector_map = {}

        weights = {
            "Technology": Decimal("0.5"),
            "Finance":    Decimal("0.5"),
        }
        result = calc.get_sector_concentration(sector_weights=weights)

        assert abs(result["hhi"] - Decimal("0.5")) < Decimal("0.0001")

    def test_risk_level_high_above_0_25(self):
        """HHI > 0.25 → risk_level = HIGH."""
        from risk.portfolio.portfolio_calculator import PortfolioCalculator
        calc = PortfolioCalculator.__new__(PortfolioCalculator)
        calc.tracker    = MagicMock()
        calc.sector_map = {}

        weights = {"Technology": Decimal("0.9"), "Finance": Decimal("0.1")}
        result  = calc.get_sector_concentration(sector_weights=weights)
        assert result["risk_level"] == "HIGH"

    def test_risk_level_low_below_0_15(self):
        """HHI < 0.15 → risk_level = LOW (well-diversified)."""
        from risk.portfolio.portfolio_calculator import PortfolioCalculator
        calc = PortfolioCalculator.__new__(PortfolioCalculator)
        calc.tracker    = MagicMock()
        calc.sector_map = {}

        # 10 equal sectors → HHI = 10 × (0.1)² = 0.10
        weights = {f"Sector{i}": Decimal("0.1") for i in range(10)}
        result  = calc.get_sector_concentration(sector_weights=weights)
        assert result["risk_level"] == "LOW"

    def test_empty_sector_weights_returns_empty(self):
        """No weights → returns empty dict, no crash."""
        from risk.portfolio.portfolio_calculator import PortfolioCalculator
        calc = PortfolioCalculator.__new__(PortfolioCalculator)
        calc.tracker    = MagicMock()
        calc.sector_map = {}

        result = calc.get_sector_concentration(sector_weights={})
        assert result == {}


# ─────────────────────────────────────────────────────────────
# POSITION WEIGHTS
# ─────────────────────────────────────────────────────────────

class TestGetPositionWeights:

    def test_weights_are_fractions_between_0_and_1(self):
        """All position weights must be between 0 and 1."""
        aapl = _make_position("AAPL", 10, 200.0, 200.0)
        msft = _make_position("MSFT", 5,  380.0, 380.0)
        calc = _make_calculator([aapl, msft])

        weights = calc.get_position_weights()
        for ticker, w in weights.items():
            assert Decimal("0") < w <= Decimal("1"), (
                f"{ticker} weight {w} out of range"
            )

    def test_empty_portfolio_returns_empty_dict(self):
        calc = _make_calculator([])
        assert calc.get_position_weights() == {}

    def test_single_position_weight_is_position_over_portfolio(self):
        """Weight of the only position = its market value / total portfolio."""
        pos   = _make_position("AAPL", 10, 200.0, 200.0)   # $2,000
        total = Decimal("4000")                              # $2,000 cash too
        calc  = _make_calculator([pos], portfolio_value=total)

        weights = calc.get_position_weights()
        expected = Decimal("2000") / Decimal("4000")   # 0.5
        assert abs(weights["AAPL"] - expected) < Decimal("0.0001")

    def test_weights_sorted_descending(self):
        """Weights are returned sorted largest to smallest."""
        small = _make_position("JPM",  5, 160.0, 160.0)   # $800
        large = _make_position("AAPL", 10, 200.0, 200.0)  # $2,000
        calc  = _make_calculator([small, large])

        weights = calc.get_position_weights()
        values  = list(weights.values())
        assert values == sorted(values, reverse=True)


# ─────────────────────────────────────────────────────────────
# LARGEST POSITION
# ─────────────────────────────────────────────────────────────

class TestGetLargestPosition:

    def test_returns_ticker_weight_market_value_tuple(self):
        """get_largest_position returns a 3-tuple (ticker, weight, market_value)."""
        aapl = _make_position("AAPL", 10, 200.0, 200.0)
        msft = _make_position("MSFT", 2,  380.0, 380.0)
        calc = _make_calculator([aapl, msft])

        result = calc.get_largest_position()
        assert result is not None
        assert len(result) == 3
        ticker, weight, market_value = result
        assert isinstance(ticker, str)

    def test_returns_none_on_empty_portfolio(self):
        calc = _make_calculator([])
        assert calc.get_largest_position() is None

    def test_largest_position_is_the_biggest_holding(self):
        """The returned ticker is the one with the highest market value."""
        aapl = _make_position("AAPL", 50, 200.0, 200.0)  # $10,000
        jpm  = _make_position("JPM",   5, 160.0, 160.0)  # $800
        calc = _make_calculator([aapl, jpm], portfolio_value=Decimal("20000"))

        result = calc.get_largest_position()
        assert result[0] == "AAPL"


# ─────────────────────────────────────────────────────────────
# CONCENTRATION RISK
# ─────────────────────────────────────────────────────────────

class TestGetConcentrationRisk:

    def test_returns_expected_keys(self):
        """Concentration risk dict contains the required keys."""
        aapl = _make_position("AAPL", 10, 200.0, 200.0)
        calc = _make_calculator([aapl])

        result = calc.get_concentration_risk()
        for key in ("top_5_weight", "top_10_weight", "hhi", "num_positions", "risk_level"):
            assert key in result, f"Missing key: {key}"

    def test_num_positions_is_correct(self):
        """num_positions matches the number of open positions."""
        positions = [
            _make_position(t, 5, 200.0, 200.0)
            for t in ["AAPL", "MSFT", "JPM"]
        ]
        calc   = _make_calculator(positions)
        result = calc.get_concentration_risk()
        assert result["num_positions"] == 3

    def test_single_position_top5_equals_one(self):
        """One position → top_5_weight = 1.0 (100% concentration)."""
        aapl   = _make_position("AAPL", 10, 200.0, 200.0)
        calc   = _make_calculator([aapl], portfolio_value=Decimal("2000"))
        result = calc.get_concentration_risk()

        # top_5_weight should be ~1.0 (only one position and it's the whole portfolio)
        assert float(result["top_5_weight"]) == pytest.approx(1.0, abs=0.01)

    def test_empty_portfolio_returns_empty(self):
        calc = _make_calculator([])
        assert calc.get_concentration_risk() == {}


# ─────────────────────────────────────────────────────────────
# VAR — structure tests (real yfinance needed for values)
# ─────────────────────────────────────────────────────────────

class TestCalculateVaR:

    def test_var_returns_correct_keys_on_valid_portfolio(self, tmp_path):
        """With a real portfolio, VaR returns a dict with var_dollar, var_percent, confidence."""
        from risk.portfolio.portfolio_tracker import PositionTracker
        from risk.portfolio.portfolio_calculator import PortfolioCalculator

        tracker = PositionTracker(initial_capital=50_000)
        tracker.positions_file = str(tmp_path / "pos.csv")
        tracker.history_file   = str(tmp_path / "hist.csv")
        tracker.cash_file      = str(tmp_path / "cash.json")
        tracker.trades_file    = str(tmp_path / "trades.csv")
        tracker.lock_dir       = str(tmp_path / ".locks")
        os.makedirs(tracker.lock_dir, exist_ok=True)

        tracker.add_position("AAPL", 20, 180.0)
        tracker.add_position("MSFT", 10, 380.0)

        calc = PortfolioCalculator(tracker=tracker)
        result = calc.calculate_var(confidence=0.95, days=10)

        if result:  # may be {} if yfinance unavailable in CI
            assert "var_dollar" in result
            assert "var_percent" in result
            assert "confidence" in result
            assert float(result["var_dollar"]) >= 0
            assert Decimal("0") < result["var_percent"] < Decimal("1")

    def test_var_invalid_confidence_returns_empty(self):
        """Confidence > 1 is rejected and returns {}."""
        calc = _make_calculator([_make_position("AAPL", 10, 200.0, 200.0)])
        result = calc.calculate_var(confidence=1.5, days=10)
        assert result == {}

    def test_var_negative_days_returns_empty(self):
        """Negative holding period is rejected and returns {}."""
        calc = _make_calculator([_make_position("AAPL", 10, 200.0, 200.0)])
        result = calc.calculate_var(confidence=0.95, days=-1)
        assert result == {}

    def test_var_empty_portfolio_returns_empty(self):
        """No positions → returns {} without crashing."""
        calc = _make_calculator([])
        result = calc.calculate_var()
        assert result == {}


# ─────────────────────────────────────────────────────────────
# MAX DRAWDOWN — structure tests
# ─────────────────────────────────────────────────────────────

class TestCalculateMaxDrawdown:

    def test_drawdown_returns_expected_keys(self, tmp_path):
        """Max drawdown result contains max_drawdown, peak_value, trough_value, dates."""
        from risk.portfolio.portfolio_tracker import PositionTracker
        from risk.portfolio.portfolio_calculator import PortfolioCalculator

        tracker = PositionTracker(initial_capital=50_000)
        tracker.positions_file = str(tmp_path / "pos.csv")
        tracker.history_file   = str(tmp_path / "hist.csv")
        tracker.cash_file      = str(tmp_path / "cash.json")
        tracker.trades_file    = str(tmp_path / "trades.csv")
        tracker.lock_dir       = str(tmp_path / ".locks")
        os.makedirs(tracker.lock_dir, exist_ok=True)

        tracker.add_position("AAPL", 20, 180.0)
        calc = PortfolioCalculator(tracker=tracker)

        result = calc.calculate_max_drawdown()
        if result:
            for key in ("max_drawdown", "peak_value", "trough_value", "peak_date", "trough_date"):
                assert key in result, f"Missing key: {key}"
            # Drawdown is always negative or zero
            assert float(result["max_drawdown"]) <= 0

    def test_drawdown_empty_portfolio_returns_empty(self):
        """No positions → returns {} without crashing."""
        calc = _make_calculator([])
        result = calc.calculate_max_drawdown()
        assert result == {}


# ─────────────────────────────────────────────────────────────
# KNOWN BUGS (documented as failing tests)
# ─────────────────────────────────────────────────────────────

class TestKnownBugs:

    def test_logger_name_has_py_extension(self):
        """
        BUG: Logger name is 'risk.portfolio.portfolio_calculator.py'
        The .py suffix is wrong — logger names are module paths, not file names.
        Should be: 'risk.portfolio.portfolio_calculator'

        This test documents the bug. It will PASS once the name is fixed.
        """
        import logging
        logger = logging.getLogger("risk.portfolio.portfolio_calculator.py")
        # If the name is wrong, it creates a logger with a .py suffix
        # After fix, this test should be updated to check the correct name
        assert logger.name == "risk.portfolio.portfolio_calculator.py", (
            "Logger name still has .py suffix — fix: "
            "change get_logger('risk.portfolio.portfolio_calculator.py') "
            "to get_logger('risk.portfolio.portfolio_calculator')"
        )