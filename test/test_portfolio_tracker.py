"""
Tests for PortfolioTracker
==========================
Run from project root: pytest tests/test_portfolio_tracker.py -v

Covers:
- add_position (buy)
- remove_position (sell)
- update_prices
- reconcile
- get_portfolio_summary
- edge cases and error handling

NOTE: Tests use a temp directory so they never touch real portfolio files.
"""

import pytest
import tempfile
import os
import sys
from decimal import Decimal

# ── make sure project root is on PYTHONPATH ──────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk.portfolio.portfolio_tracker import PositionTracker


# ─────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_tracker(tmp_path):
    """
    Fresh PositionTracker that writes ALL files inside a temp directory.
    Automatically cleaned up after each test.
    """
    tracker = PositionTracker(initial_capital=20_000)

    # Redirect all file paths into temp dir so tests are isolated
    tracker.positions_file = str(tmp_path / "current_positions.csv")
    tracker.history_file   = str(tmp_path / "portfolio_history.csv")
    tracker.cash_file      = str(tmp_path / "cash_balance.json")
    tracker.trades_file    = str(tmp_path / "trade_history.csv")
    tracker.lock_dir       = str(tmp_path / ".locks")
    os.makedirs(tracker.lock_dir, exist_ok=True)

    return tracker


# ─────────────────────────────────────────────────────────────
# ADD POSITION (BUY)
# ─────────────────────────────────────────────────────────────

class TestAddPosition:

    def test_buy_creates_new_position(self, tmp_tracker):
        """Buying a stock creates exactly one position with correct values."""
        tmp_tracker.add_position("AAPL", 5, 200.0)

        assert len(tmp_tracker.positions) == 1
        pos = tmp_tracker.positions[0]
        assert pos.ticker == "AAPL"
        assert pos.quantity == Decimal("5")
        assert pos.entry_price == Decimal("200.00")

    def test_buy_deducts_cash_correctly(self, tmp_tracker):
        """Cash is reduced by exactly quantity × price."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        # 5 × $200 = $1,000 spent
        expected_cash = Decimal("20000") - Decimal("1000")
        assert tmp_tracker.cash == expected_cash

    def test_buy_multiple_stocks(self, tmp_tracker):
        """Buying two different tickers creates two separate positions."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        tmp_tracker.add_position("MSFT", 2, 380.0)
        assert len(tmp_tracker.positions) == 2

    def test_buy_existing_position_averages_price(self, tmp_tracker):
        """Buying more shares of an owned ticker averages the entry price."""
        tmp_tracker.add_position("AAPL", 4, 200.0)  # avg = $200
        tmp_tracker.add_position("AAPL", 4, 240.0)  # avg = $220

        pos = tmp_tracker.positions[0]
        assert pos.ticker == "AAPL"
        assert pos.quantity == Decimal("8")
        assert pos.entry_price == Decimal("220.00"), (
            f"Expected average $220.00, got {pos.entry_price}"
        )

    def test_buy_raises_on_insufficient_cash(self, tmp_tracker):
        """Buying more than available cash raises ValueError."""
        with pytest.raises(ValueError, match="Insufficient funds"):
            tmp_tracker.add_position("AAPL", 1000, 200.0)  # $200,000 >> $20,000

    def test_buy_raises_on_negative_quantity(self, tmp_tracker):
        """Negative quantity raises ValueError."""
        with pytest.raises(ValueError):
            tmp_tracker.add_position("AAPL", -5, 200.0)

    def test_buy_raises_on_zero_price(self, tmp_tracker):
        """Zero price raises ValueError."""
        with pytest.raises(ValueError):
            tmp_tracker.add_position("AAPL", 5, 0)

    def test_buy_normalizes_ticker_lowercase(self, tmp_tracker):
        """Ticker is always stored uppercase regardless of input case."""
        tmp_tracker.add_position("aapl", 5, 200.0)
        assert tmp_tracker.positions[0].ticker == "AAPL"

    def test_buy_reconcile_passes_after_trade(self, tmp_tracker):
        """Accounting equation holds after a BUY."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        assert tmp_tracker.reconcile() is True

    def test_buy_rollback_on_failure(self, tmp_tracker):
        """If an error occurs mid-buy, cash and positions are rolled back."""
        original_cash = tmp_tracker.cash

        # Force failure by passing an invalid ticker type after initial checks
        # We can test rollback by patching _save_cash to raise
        original_save = tmp_tracker._save_cash
        def bad_save():
            raise RuntimeError("Simulated disk failure")
        tmp_tracker._save_cash = bad_save

        with pytest.raises(RuntimeError):
            tmp_tracker.add_position("AAPL", 5, 200.0)

        # Should be rolled back
        assert tmp_tracker.cash == original_cash
        assert len(tmp_tracker.positions) == 0

        tmp_tracker._save_cash = original_save  # restore


# ─────────────────────────────────────────────────────────────
# REMOVE POSITION (SELL)
# ─────────────────────────────────────────────────────────────

class TestRemovePosition:

    def test_sell_entire_position_removes_it(self, tmp_tracker):
        """Selling all shares removes the position from the list."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        tmp_tracker.remove_position("AAPL", quantity=5, exit_price=210.0)

        assert len(tmp_tracker.positions) == 0

    def test_sell_returns_correct_realized_pnl(self, tmp_tracker):
        """Realized P&L = (exit - entry) × quantity."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        result = tmp_tracker.remove_position("AAPL", quantity=5, exit_price=210.0)

        assert result is not None
        expected_pnl = (210.0 - 200.0) * 5  # $50
        assert abs(result["realized_pnl"] - expected_pnl) < 0.01

    def test_sell_updates_cash(self, tmp_tracker):
        """Cash increases by selling_price × quantity on sell."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        cash_before_sell = float(tmp_tracker.cash)
        tmp_tracker.remove_position("AAPL", quantity=5, exit_price=210.0)

        # Cash should increase by 5 × $210 = $1,050
        assert float(tmp_tracker.cash) == pytest.approx(cash_before_sell + 1050.0, abs=0.01)

    def test_partial_sell_keeps_remaining_shares(self, tmp_tracker):
        """Selling part of a position leaves the remainder intact."""
        tmp_tracker.add_position("AAPL", 10, 200.0)
        tmp_tracker.remove_position("AAPL", quantity=3, exit_price=210.0)

        pos = tmp_tracker.positions[0]
        assert pos.quantity == Decimal("7")

    def test_sell_not_owned_returns_none(self, tmp_tracker):
        """Selling a ticker you don't own returns None (not an exception)."""
        result = tmp_tracker.remove_position("NVDA", quantity=5, exit_price=500.0)
        assert result is None

    def test_sell_more_than_owned_raises(self, tmp_tracker):
        """Trying to sell more shares than owned raises ValueError."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        with pytest.raises(ValueError, match="Cannot sell"):
            tmp_tracker.remove_position("AAPL", quantity=10, exit_price=210.0)

    def test_sell_without_exit_price_uses_current_price(self, tmp_tracker):
        """If no exit_price given, it uses current_price from the position."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        tmp_tracker.update_prices({"AAPL": 215.0})
        result = tmp_tracker.remove_position("AAPL", quantity=5)

        assert result is not None
        assert abs(result["selling_price"] - 215.0) < 0.01

    def test_sell_reconcile_passes_after_trade(self, tmp_tracker):
        """Accounting equation holds after a SELL."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        tmp_tracker.remove_position("AAPL", quantity=5, exit_price=210.0)
        assert tmp_tracker.reconcile() is True

    def test_sell_loss_captured_correctly(self, tmp_tracker):
        """Selling at a loss records a negative realized P&L."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        result = tmp_tracker.remove_position("AAPL", quantity=5, exit_price=190.0)

        assert result["realized_pnl"] < 0

    def test_sell_entire_position_no_quantity_arg(self, tmp_tracker):
        """Calling remove_position with quantity=None sells everything."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        result = tmp_tracker.remove_position("AAPL", exit_price=220.0)

        assert len(tmp_tracker.positions) == 0
        assert result is not None


# ─────────────────────────────────────────────────────────────
# UPDATE PRICES
# ─────────────────────────────────────────────────────────────

class TestUpdatePrices:

    def test_update_prices_changes_current_price(self, tmp_tracker):
        """update_prices sets the current_price on matching positions."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        tmp_tracker.update_prices({"AAPL": 215.0})

        pos = tmp_tracker.positions[0]
        assert pos.current_price == Decimal("215.0")

    def test_update_prices_recalculates_unrealized_pnl(self, tmp_tracker):
        """Unrealized P&L = (current - entry) × quantity after price update."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        tmp_tracker.update_prices({"AAPL": 210.0})

        pos = tmp_tracker.positions[0]
        expected_pnl = (210.0 - 200.0) * 5  # $50
        assert float(pos.unrealized_pnl) == pytest.approx(expected_pnl, abs=0.01)

    def test_update_prices_ignores_missing_tickers(self, tmp_tracker):
        """Positions with no price update keep their existing current_price."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        tmp_tracker.add_position("MSFT", 2, 380.0)
        original_msft_price = tmp_tracker.positions[1].current_price

        tmp_tracker.update_prices({"AAPL": 215.0})  # MSFT not included

        assert tmp_tracker.positions[1].current_price == original_msft_price

    def test_update_prices_empty_dict_does_nothing(self, tmp_tracker):
        """Passing an empty dict leaves all positions unchanged."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        tmp_tracker.update_prices({})  # Should not raise, should do nothing

    def test_update_prices_zero_price_skipped(self, tmp_tracker):
        """Zero/negative prices are rejected; original price is kept."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        tmp_tracker.update_prices({"AAPL": 0})  # Invalid price

        assert tmp_tracker.positions[0].current_price == Decimal("200.0")


# ─────────────────────────────────────────────────────────────
# RECONCILE
# ─────────────────────────────────────────────────────────────

class TestReconcile:

    def test_reconcile_passes_fresh_portfolio(self, tmp_tracker):
        """A fresh portfolio with no trades always reconciles."""
        assert tmp_tracker.reconcile() is True

    def test_reconcile_passes_after_buy_and_sell(self, tmp_tracker):
        """Reconcile passes through a full buy → sell cycle."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        tmp_tracker.add_position("MSFT", 2, 380.0)
        tmp_tracker.remove_position("AAPL", quantity=3, exit_price=215.0)
        assert tmp_tracker.reconcile() is True

    def test_reconcile_fails_on_tampered_cash(self, tmp_tracker):
        """Manually corrupting cash makes reconcile return False."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        tmp_tracker.cash += Decimal("500")  # inject money out of thin air

        assert tmp_tracker.reconcile() is False


# ─────────────────────────────────────────────────────────────
# PORTFOLIO SUMMARY & VALUATION
# ─────────────────────────────────────────────────────────────

class TestPortfolioSummary:

    def test_portfolio_value_equals_cash_plus_positions(self, tmp_tracker):
        """Portfolio value = cash + sum(quantity × current_price)."""
        tmp_tracker.add_position("AAPL", 5, 200.0)   # $1,000 invested
        tmp_tracker.update_prices({"AAPL": 210.0})   # now worth $1,050

        value = float(tmp_tracker.get_portfolio_value())
        cash  = float(tmp_tracker.cash)
        pos_value = 5 * 210.0

        assert value == pytest.approx(cash + pos_value, abs=0.01)

    def test_summary_return_pct_is_correct(self, tmp_tracker):
        """Return % is based on initial capital, not current cash."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        tmp_tracker.update_prices({"AAPL": 220.0})  # +$100 unrealized gain

        summary = tmp_tracker.get_portfolio_summary()
        # Portfolio is now $20,100, started at $20,000 → +0.5%
        assert float(summary["return_pct"]) == pytest.approx(0.5, abs=0.05)

    def test_summary_no_positions_all_cash(self, tmp_tracker):
        """With no positions, total value equals initial capital."""
        summary = tmp_tracker.get_portfolio_summary()
        assert float(summary["portfolio_value"]) == pytest.approx(20_000.0, abs=0.01)
        assert float(summary["total_positions"]) == 0

    def test_get_position_returns_correct_data(self, tmp_tracker):
        """get_position returns a dict matching the added position."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        pos = tmp_tracker.get_position("AAPL")

        assert pos is not None
        assert pos["ticker"] == "AAPL"
        assert pos["quantity"] == 5.0
        assert pos["entry_price"] == 200.0

    def test_get_position_unknown_ticker_returns_none(self, tmp_tracker):
        """get_position returns None for tickers not in the portfolio."""
        assert tmp_tracker.get_position("ZZZZ") is None

    def test_total_unrealized_pnl_sums_all_positions(self, tmp_tracker):
        """Total unrealized P&L is the sum across all open positions."""
        tmp_tracker.add_position("AAPL", 5, 200.0)
        tmp_tracker.add_position("MSFT", 2, 380.0)
        tmp_tracker.update_prices({"AAPL": 210.0, "MSFT": 390.0})

        # AAPL: +$50,  MSFT: +$20 → total = +$70
        total_pnl = float(tmp_tracker.get_total_unrealized_pnl())
        assert total_pnl == pytest.approx(70.0, abs=0.01)


# ─────────────────────────────────────────────────────────────
# INPUT VALIDATION
# ─────────────────────────────────────────────────────────────

class TestInputValidation:

    def test_non_string_ticker_raises_type_error(self, tmp_tracker):
        """Passing a non-string ticker raises TypeError."""
        with pytest.raises(TypeError):
            tmp_tracker.add_position(123, 5, 200.0)

    def test_empty_ticker_raises_value_error(self, tmp_tracker):
        """Empty string ticker raises ValueError."""
        with pytest.raises(ValueError):
            tmp_tracker.add_position("", 5, 200.0)

    def test_invalid_initial_capital_raises(self):
        """PositionTracker raises ValueError for zero/negative capital."""
        with pytest.raises(ValueError):
            PositionTracker(initial_capital=0)

        with pytest.raises(ValueError):
            PositionTracker(initial_capital=-5000)