"""
Tests for RiskManager
======================
Run from project root: pytest test/test_risk_manager.py -v

Covers:
- approve_trade: BUY + SELL paths
- _check_position_size
- _check_cash_reserve
- _check_max_positions
- _check_sector_exposure
- _check_position_exists
- _check_daily_loss
- _check_drawdown
- get_risk_summary
- HOLD always approved
- Edge cases

KNOWN BUG (tested with xfail):
  Sector key mismatch: RiskConfig uses keys like 'technology', but
  PortfolioCalculator returns 'Information Technology'. After lowercasing,
  'information technology' != 'technology', so the sector limit always
  falls back to 'other' (40%).

FIXES APPLIED vs previous versions:
  v1 → v2: mock positions had no Decimal attrs → TypeError in summary math
  v2 → v3: injecting mock positions caused fcntl file lock freeze.
            Fix: patch num_positions property directly instead of touching
            tracker.positions list, so zero file I/O happens in that test.
"""

import pytest
import sys
import os
from decimal import Decimal
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def fresh_rm(tmp_path):
    """
    RiskManager wired to a fresh PositionTracker (no real files touched).
    The tracker is isolated in a temp directory.
    """
    from risk.portfolio.portfolio_tracker import PositionTracker
    from risk.risk_manager import RiskManager

    tracker = PositionTracker(initial_capital=20_000)
    tracker.positions_file = str(tmp_path / "pos.csv")
    tracker.history_file   = str(tmp_path / "hist.csv")
    tracker.cash_file      = str(tmp_path / "cash.json")
    tracker.trades_file    = str(tmp_path / "trades.csv")
    tracker.lock_dir       = str(tmp_path / ".locks")
    os.makedirs(tracker.lock_dir, exist_ok=True)

    rm = RiskManager()
    rm._tracker = tracker

    from risk.portfolio.portfolio_calculator import PortfolioCalculator
    rm._calculator = PortfolioCalculator(tracker=tracker)

    return rm


def _buy_trade(ticker="AAPL", quantity=5, price=200.0, confidence=0.75):
    return {
        "ticker":        ticker,
        "action":        "BUY",
        "quantity":      quantity,
        "current_price": price,
        "confidence":    confidence,
        "reasoning":     "Test trade",
    }


def _sell_trade(ticker="AAPL", quantity=5, price=210.0):
    return {
        "ticker":        ticker,
        "action":        "SELL",
        "quantity":      quantity,
        "current_price": price,
        "confidence":    0.75,
        "reasoning":     "Test sell",
    }


# ─────────────────────────────────────────────────────────────
# BUY: NORMAL (SHOULD PASS)
# ─────────────────────────────────────────────────────────────

class TestBuyApproved:

    def test_small_trade_is_approved(self, fresh_rm):
        """A $1,000 trade (5% of $20k) should pass all checks."""
        result = fresh_rm.approve_trade(_buy_trade("AAPL", 5, 200.0))
        assert result["approved"] is True, result["reason"]

    def test_approved_result_has_expected_keys(self, fresh_rm):
        """Result dict always contains: approved, trade, checks, reason."""
        result = fresh_rm.approve_trade(_buy_trade())
        for key in ("approved", "trade", "checks", "reason"):
            assert key in result

    def test_approved_trade_reason_is_all_checks_passed(self, fresh_rm):
        """Approved trade reason string is 'All checks passed'."""
        result = fresh_rm.approve_trade(_buy_trade("AAPL", 5, 200.0))
        if result["approved"]:
            assert result["reason"] == "All checks passed"


# ─────────────────────────────────────────────────────────────
# BUY: POSITION SIZE CHECK
# ─────────────────────────────────────────────────────────────

class TestCheckPositionSize:

    def test_oversized_trade_is_rejected(self, fresh_rm):
        """10 × $400 = $4,000 = 20% of $20k. MAX = 15% → REJECTED."""
        result = fresh_rm.approve_trade(_buy_trade("MSFT", 10, 400.0))
        assert result["approved"] is False
        assert result["checks"].get("position_size") is False

    def test_exactly_at_limit_is_approved(self, fresh_rm):
        """15 × $200 = $3,000 = exactly 15% of $20k → PASS."""
        result = fresh_rm.approve_trade(_buy_trade("AAPL", 15, 200.0))
        assert result["checks"].get("position_size") is True

    def test_just_above_limit_is_rejected(self, fresh_rm):
        """16 × $200 = $3,200 = 16% of $20k → above 15% limit → REJECTED."""
        result = fresh_rm.approve_trade(_buy_trade("AAPL", 16, 200.0))
        assert result["checks"].get("position_size") is False


# ─────────────────────────────────────────────────────────────
# BUY: CASH RESERVE CHECK
# ─────────────────────────────────────────────────────────────

class TestCheckCashReserve:

    def test_trade_leaving_less_than_10pct_cash_is_rejected(self, fresh_rm):
        """92 × $200 = $18,400 → leaves $1,600 (8%) → below 10% minimum → REJECT."""
        result = fresh_rm.approve_trade(_buy_trade("AAPL", 92, 200.0))
        assert result["approved"] is False
        assert result["checks"].get("cash_reserve") is False

    def test_trade_leaving_exactly_10pct_is_approved(self, fresh_rm):
        """90 × $200 = $18,000 → leaves $2,000 = exactly 10% of $20k → PASS."""
        result = fresh_rm.approve_trade(_buy_trade("AAPL", 90, 200.0))
        assert result["checks"].get("cash_reserve") is True

    def test_trade_exceeding_available_cash_is_rejected(self, fresh_rm):
        """125 × $200 = $25,000 > $20,000 available → REJECTED."""
        result = fresh_rm.approve_trade(_buy_trade("AAPL", 125, 200.0))
        assert result["approved"] is False
        assert result["checks"].get("cash_reserve") is False


# ─────────────────────────────────────────────────────────────
# BUY: MAX POSITIONS CHECK
# ─────────────────────────────────────────────────────────────

class TestCheckMaxPositions:

    def test_trade_when_at_max_positions_is_rejected(self, fresh_rm):
        """
        MAX_TOTAL_POSITIONS = 15.
        Already at 15 positions → 16th trade is REJECTED.

        FIX vs previous version:
        v2 injected mock positions directly into tracker.positions.
        This caused the test to FREEZE because somewhere in approve_trade()
        the code calls fcntl.flock() on a lock file, and with a half-mocked
        tracker the lock was never released → infinite hang.

        Solution: patch num_positions at the RiskManager property level.
        RiskManager.num_positions is already a @property that reads
        len(self.tracker.positions). We patch it to return 15 directly,
        so zero file I/O happens and no locks are touched.
        """
        with patch.object(
            type(fresh_rm), "num_positions",
            new_callable=PropertyMock, return_value=15
        ):
            result = fresh_rm.approve_trade(_buy_trade("AAPL", 5, 200.0))

        assert result["approved"] is False
        assert result["checks"].get("max_positions") is False

    def test_trade_below_max_positions_passes_check(self, fresh_rm):
        """0 positions → max_positions check passes."""
        result = fresh_rm.approve_trade(_buy_trade("AAPL", 5, 200.0))
        assert result["checks"].get("max_positions") is True


# ─────────────────────────────────────────────────────────────
# SELL: POSITION EXISTS CHECK
# ─────────────────────────────────────────────────────────────

class TestCheckPositionExists:

    def test_sell_stock_not_owned_is_rejected(self, fresh_rm):
        """Selling a ticker with no position returns approved=False."""
        result = fresh_rm.approve_trade(_sell_trade("NVDA"))
        assert result["approved"] is False
        assert result["checks"].get("position_exists") is False
        assert "NVDA" in result["reason"]

    def test_sell_stock_owned_is_approved(self, fresh_rm):
        """Selling a ticker we own passes the position_exists check."""
        fresh_rm._tracker.add_position("AAPL", 5, 200.0)
        result = fresh_rm.approve_trade(_sell_trade("AAPL", quantity=5, price=210.0))
        assert result["checks"].get("position_exists") is True

    def test_sell_check_is_case_insensitive(self, fresh_rm):
        """
        Selling 'aapl' when we own 'AAPL' should pass — tickers must be
        normalized before comparison.

        ── THIS TEST EXPOSES A REAL BUG IN risk_manager.py ──────────────────
        _check_position_exists() does not normalize the ticker:

            owned = [p.ticker for p in self.tracker.positions]
            if ticker not in owned:   # 'aapl' not in ['AAPL'] → always fails

        ONE-LINE FIX in risk_manager.py:
            def _check_position_exists(self, ticker):
                ticker = ticker.strip().upper()   ← ADD THIS LINE
                owned  = [p.ticker for p in self.tracker.positions]
                ...

        This test will FAIL until that fix is applied.
        ─────────────────────────────────────────────────────────────────────
        """
        fresh_rm._tracker.add_position("AAPL", 5, 200.0)
        result = fresh_rm.approve_trade(_sell_trade("aapl"))
        assert result["checks"].get("position_exists") is True, (
            "BUG: _check_position_exists() does not normalize ticker to uppercase.\n"
            "Fix: add `ticker = ticker.strip().upper()` at the top of the method\n"
            "in risk/risk_manager.py."
        )


# ─────────────────────────────────────────────────────────────
# HOLD: ALWAYS APPROVED
# ─────────────────────────────────────────────────────────────

class TestHoldAlwaysApproved:

    def test_hold_action_is_always_approved(self, fresh_rm):
        """HOLD trades bypass all checks and are always approved."""
        result = fresh_rm.approve_trade({
            "ticker":        "AAPL",
            "action":        "HOLD",
            "quantity":      0,
            "current_price": 200.0,
            "confidence":    0.5,
            "reasoning":     "Waiting",
        })
        assert result["approved"] is True


# ─────────────────────────────────────────────────────────────
# DAILY LOSS CIRCUIT BREAKER
# ─────────────────────────────────────────────────────────────

class TestDailyLossCircuitBreaker:

    def test_daily_loss_check_skipped_when_no_history(self, fresh_rm):
        """If no portfolio_history.csv exists the check is skipped (passes)."""
        ok, msg = fresh_rm._check_daily_loss()
        assert ok is True
        assert "skipped" in msg.lower() or "no history" in msg.lower()

    def test_daily_loss_triggers_when_loss_exceeds_3pct(self, fresh_rm, tmp_path):
        """
        Portfolio dropped −5% today (exceeds 3% limit) → circuit breaker fires.
        Opening value $20,000 written to history CSV, current value mocked to $19,000.
        """
        import pandas as pd
        from datetime import datetime, timezone

        history_file = str(tmp_path / "portfolio_history.csv")
        fresh_rm._tracker.history_file = history_file

        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        df = pd.DataFrame([{
            "timestamp":            today,
            "cash":                 19000,
            "positions_value":      0,
            "total_value":          20000,
            "cash_pct":             100.0,
            "num_positions":        0,
            "total_unrealized_pnl": 0,
            "total_realized_pnl":   0,
            "return_pct":           0,
        }])
        df.to_csv(history_file, index=False)

        with patch.object(
            type(fresh_rm), "portfolio_value",
            new_callable=PropertyMock, return_value=19_000
        ):
            ok, msg = fresh_rm._check_daily_loss()

        assert ok is False, "Circuit breaker should fire at −5% daily loss"
        assert "CIRCUIT BREAKER" in msg

    def test_daily_loss_allows_trade_within_limit(self, fresh_rm, tmp_path):
        """Portfolio dropped −1% today (within the 3% limit) → check passes."""
        import pandas as pd
        from datetime import datetime, timezone

        history_file = str(tmp_path / "portfolio_history.csv")
        fresh_rm._tracker.history_file = history_file

        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        df = pd.DataFrame([{
            "timestamp":            today,
            "cash":                 19800,
            "positions_value":      0,
            "total_value":          20000,
            "cash_pct":             100.0,
            "num_positions":        0,
            "total_unrealized_pnl": 0,
            "total_realized_pnl":   0,
            "return_pct":           0,
        }])
        df.to_csv(history_file, index=False)

        with patch.object(
            type(fresh_rm), "portfolio_value",
            new_callable=PropertyMock, return_value=19_800
        ):
            ok, msg = fresh_rm._check_daily_loss()

        assert ok is True, f"−1% loss should be within limit, got: {msg}"


# ─────────────────────────────────────────────────────────────
# DRAWDOWN CIRCUIT BREAKER
# ─────────────────────────────────────────────────────────────

class TestDrawdownCircuitBreaker:

    def test_drawdown_circuit_breaker_fires_at_17pct(self, fresh_rm):
        """17% drawdown exceeds the 15% halt limit → circuit breaker fires."""
        mock_drawdown = {
            "max_drawdown": Decimal("-0.17"),
            "peak_value":   Decimal("20000"),
            "trough_value": Decimal("16600"),
            "peak_date":    "2025-01-01",
            "trough_date":  "2025-02-01",
        }
        with patch.object(fresh_rm.calculator, "calculate_max_drawdown", return_value=mock_drawdown):
            ok, msg = fresh_rm._check_drawdown()

        assert ok is False, "Drawdown circuit breaker should fire at 17% (limit is 15%)"

    def test_drawdown_within_limit_is_allowed(self, fresh_rm):
        """10% drawdown is below the 15% halt limit → check passes."""
        mock_drawdown = {
            "max_drawdown": Decimal("-0.10"),
            "peak_value":   Decimal("20000"),
            "trough_value": Decimal("18000"),
            "peak_date":    "2025-01-01",
            "trough_date":  "2025-02-01",
        }
        with patch.object(fresh_rm.calculator, "calculate_max_drawdown", return_value=mock_drawdown):
            ok, msg = fresh_rm._check_drawdown()

        assert ok is True, f"10% drawdown should be within limit, got: {msg}"

    def test_drawdown_check_passes_when_no_drawdown(self, fresh_rm):
        """0% drawdown → check always passes."""
        mock_drawdown = {
            "max_drawdown": Decimal("0"),
            "peak_value":   Decimal("20000"),
            "trough_value": Decimal("20000"),
            "peak_date":    "2025-01-01",
            "trough_date":  "2025-01-01",
        }
        with patch.object(fresh_rm.calculator, "calculate_max_drawdown", return_value=mock_drawdown):
            ok, msg = fresh_rm._check_drawdown()

        assert ok is True

    def test_drawdown_check_skipped_on_exception(self, fresh_rm):
        """If drawdown calculation throws, the check is skipped (passes)."""
        with patch.object(
            fresh_rm.calculator, "calculate_max_drawdown",
            side_effect=RuntimeError("API down")
        ):
            ok, msg = fresh_rm._check_drawdown()

        assert ok is True
        assert "skipped" in msg.lower()


# ─────────────────────────────────────────────────────────────
# KNOWN BUG: Sector key mismatch
# ─────────────────────────────────────────────────────────────

class TestSectorExposureMismatch:

    @pytest.mark.xfail(
        reason=(
            "BUG: RiskConfig.MAX_SECTOR_EXPOSURE uses keys like 'technology', "
            "but PortfolioCalculator._get_sector() returns 'Information Technology'. "
            "After lowercasing: 'information technology' != 'technology'. "
            "The lookup always falls back to 'other' (40%), "
            "so sector limits for tech/finance/healthcare are never enforced. "
            "FIX: Update config/risk_config.py to use GICS names:\n"
            "  'information technology': 0.50,\n"
            "  'financials': 0.30,\n"
            "  'health care': 0.30, ..."
        ),
        strict=True,
    )
    def test_technology_sector_limit_enforced(self, fresh_rm):
        """
        Sector already at 60% IT (over 50% limit) + new trade → should REJECT.
        Will go green once risk_config.py keys are updated to GICS names.
        """
        with patch.object(
            fresh_rm.calculator,
            "get_sector_breakdown",
            return_value={"information technology": Decimal("0.60")},
        ):
            with patch.object(
                fresh_rm.calculator,
                "_get_sector",
                return_value="Information Technology",
            ):
                ok, msg = fresh_rm._check_sector_exposure("AAPL", trade_value=100)

        assert ok is False, (
            "Technology sector at 60% should violate the 50% limit. "
            "Sector key mismatch bug means the limit was never found."
        )


# ─────────────────────────────────────────────────────────────
# GET RISK SUMMARY
# ─────────────────────────────────────────────────────────────

class TestGetRiskSummary:

    def test_risk_summary_has_required_keys(self, fresh_rm):
        """get_risk_summary returns a dict with all expected keys."""
        summary = fresh_rm.get_risk_summary()
        expected_keys = [
            "portfolio_value", "cash", "cash_pct",
            "num_positions", "total_return_pct",
            "unrealized_pnl", "realized_pnl",
        ]
        for key in expected_keys:
            assert key in summary, f"Missing key: {key}"

    def test_risk_summary_portfolio_value_is_positive(self, fresh_rm):
        """Portfolio value in summary is always positive."""
        summary = fresh_rm.get_risk_summary()
        assert summary["portfolio_value"] > 0

    def test_risk_summary_fresh_portfolio_has_zero_positions(self, fresh_rm):
        """A fresh portfolio has 0 open positions."""
        summary = fresh_rm.get_risk_summary()
        assert summary["num_positions"] == 0

    def test_risk_summary_cash_pct_is_fraction(self, fresh_rm):
        """cash_pct is a decimal fraction (0–1), not a percentage (0–100)."""
        summary = fresh_rm.get_risk_summary()
        assert 0 <= summary["cash_pct"] <= 1, (
            f"cash_pct should be between 0 and 1, got {summary['cash_pct']}"
        )