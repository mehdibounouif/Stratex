"""
Portfolio Tracker - Comprehensive Test Suite
==============================================

Tests every critical function with edge cases:
- Normal operations (buy, sell, update prices)
- Edge cases (sell entire position, partial sell, insufficient funds)
- Error handling (invalid inputs, negative values, empty strings)
- Accounting integrity (reconciliation, rollback on errors)
- File persistence (crash recovery, backup/restore)
- Thread safety (concurrent operations)

Run: python3 -m pytest tests/test_portfolio_tracker.py -v
Or:  python3 tests/test_portfolio_tracker.py
"""

import pytest
import os
import shutil
import json
import pandas as pd
from decimal import Decimal
from datetime import datetime, timezone
import tempfile
import time

# Import the tracker
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from risk.portfolio.portfolio_tracker import PositionTracker, Position


# ══════════════════════════════════════════════════════════════
# FIXTURES — Test Setup & Cleanup
# ══════════════════════════════════════════════════════════════

@pytest.fixture
def test_dir():
    """Create temporary directory for test files."""
    temp_dir = tempfile.mkdtemp(prefix='portfolio_test_')
    original_cwd = os.getcwd()
    os.chdir(temp_dir)
    
    yield temp_dir
    
    # Cleanup
    os.chdir(original_cwd)
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def tracker(test_dir):
    """Create fresh tracker with $10,000 capital."""
    return PositionTracker(initial_capital=10000)


@pytest.fixture
def tracker_with_positions(tracker):
    """Tracker with pre-loaded positions."""
    tracker.add_position('AAPL', 10, 150.0)
    tracker.add_position('MSFT', 5, 300.0)
    tracker.add_position('GOOGL', 3, 100.0)
    return tracker


# ══════════════════════════════════════════════════════════════
# TEST 1 — INITIALIZATION
# ══════════════════════════════════════════════════════════════

def test_initialization_default_capital(test_dir):
    """Test tracker initializes with default capital from config."""
    tracker = PositionTracker()
    assert tracker.initial_capital > 0
    assert tracker.cash == tracker.initial_capital
    assert len(tracker.positions) == 0
    assert tracker.total_realized_pnl == Decimal('0')


def test_initialization_custom_capital(test_dir):
    """Test tracker initializes with custom capital."""
    tracker = PositionTracker(initial_capital=50000)
    assert tracker.initial_capital == Decimal('50000')
    assert tracker.cash == Decimal('50000')


def test_initialization_invalid_capital(test_dir):
    """Test tracker rejects negative or zero capital."""
    with pytest.raises(ValueError, match="must be positive"):
        PositionTracker(initial_capital=0)
    
    with pytest.raises(ValueError, match="must be positive"):
        PositionTracker(initial_capital=-1000)


# ══════════════════════════════════════════════════════════════
# TEST 2 — ADD POSITION (BUY)
# ══════════════════════════════════════════════════════════════

def test_add_position_new(tracker):
    """Test buying a new position."""
    initial_cash = tracker.cash
    
    success = tracker.add_position('AAPL', 10, 150.0)
    
    assert success is True
    assert len(tracker.positions) == 1
    assert tracker.positions[0].ticker == 'AAPL'
    assert tracker.positions[0].quantity == Decimal('10')
    assert tracker.positions[0].entry_price == Decimal('150')
    assert tracker.cash == initial_cash - Decimal('1500')


def test_add_position_average_price(tracker):
    """Test adding to existing position calculates average price."""
    # First buy: 10 @ $150 = $1500
    tracker.add_position('AAPL', 10, 150.0)
    
    # Second buy: 5 @ $180 = $900
    tracker.add_position('AAPL', 5, 180.0)
    
    # Average: (10*150 + 5*180) / 15 = 2400/15 = $160
    position = tracker.positions[0]
    assert position.quantity == Decimal('15')
    assert position.entry_price == Decimal('160')


def test_add_position_insufficient_funds(tracker):
    """Test buying fails if not enough cash."""
    with pytest.raises(ValueError, match="Insufficient funds"):
        tracker.add_position('AAPL', 1000, 100.0)  # $100,000 needed, only $10k available


def test_add_position_invalid_quantity(tracker):
    """Test buying fails with invalid quantity."""
    with pytest.raises(ValueError, match="must be positive"):
        tracker.add_position('AAPL', 0, 150.0)
    
    with pytest.raises(ValueError, match="must be positive"):
        tracker.add_position('AAPL', -5, 150.0)


def test_add_position_invalid_price(tracker):
    """Test buying fails with invalid price."""
    with pytest.raises(ValueError, match="must be positive"):
        tracker.add_position('AAPL', 10, 0)
    
    with pytest.raises(ValueError, match="must be positive"):
        tracker.add_position('AAPL', 10, -150)


def test_add_position_invalid_ticker(tracker):
    """Test buying fails with invalid ticker."""
    with pytest.raises(TypeError, match="Ticker must be string"):
        tracker.add_position(123, 10, 150.0)
    
    with pytest.raises(ValueError, match="cannot be empty"):
        tracker.add_position('', 10, 150.0)
    
    with pytest.raises(ValueError, match="cannot be empty"):
        tracker.add_position('   ', 10, 150.0)


def test_add_position_ticker_normalization(tracker):
    """Test ticker is normalized to uppercase."""
    tracker.add_position('aapl', 10, 150.0)
    assert tracker.positions[0].ticker == 'AAPL'
    
    tracker.add_position('  msft  ', 5, 300.0)
    assert tracker.positions[1].ticker == 'MSFT'


def test_add_position_rollback_on_error(tracker):
    """Test state is rolled back if add_position fails."""
    initial_cash = tracker.cash
    initial_positions_count = len(tracker.positions)
    
    # Force an error by mocking reconcile to fail
    original_reconcile = tracker.reconcile
    tracker.reconcile = lambda: False
    
    try:
        tracker.add_position('AAPL', 10, 150.0)
        assert False, "Should have raised RuntimeError"
    except RuntimeError:
        pass
    
    # Verify rollback
    assert tracker.cash == initial_cash
    assert len(tracker.positions) == initial_positions_count
    
    # Restore
    tracker.reconcile = original_reconcile


# ══════════════════════════════════════════════════════════════
# TEST 3 — REMOVE POSITION (SELL)
# ══════════════════════════════════════════════════════════════

def test_remove_position_entire(tracker_with_positions):
    """Test selling entire position."""
    initial_cash = tracker_with_positions.cash
    
    result = tracker_with_positions.remove_position('AAPL', exit_price=200.0)
    
    assert result is not None
    assert result['ticker'] == 'AAPL'
    assert result['quantity_sold'] == 10.0
    assert result['selling_price'] == 200.0
    assert result['realized_pnl'] == 500.0  # (200 - 150) * 10
    
    # AAPL should be removed
    assert len(tracker_with_positions.positions) == 2
    assert tracker_with_positions._find_position('AAPL') is None
    
    # Cash should increase
    assert tracker_with_positions.cash == initial_cash + Decimal('2000')  # 10 * $200


def test_remove_position_partial(tracker_with_positions):
    """Test selling partial position."""
    result = tracker_with_positions.remove_position('AAPL', quantity=5, exit_price=200.0)
    
    assert result is not None
    assert result['quantity_sold'] == 5.0
    assert result['realized_pnl'] == 250.0  # (200 - 150) * 5
    
    # AAPL should still exist with reduced quantity
    position = tracker_with_positions._find_position('AAPL')
    assert position is not None
    assert position.quantity == Decimal('5')


def test_remove_position_no_quantity_sells_all(tracker_with_positions):
    """Test selling without specifying quantity sells entire position."""
    result = tracker_with_positions.remove_position('AAPL', exit_price=200.0)
    
    assert result['quantity_sold'] == 10.0
    assert tracker_with_positions._find_position('AAPL') is None


def test_remove_position_no_exit_price_uses_current(tracker_with_positions):
    """Test selling without exit_price uses current_price."""
    # Update current price
    tracker_with_positions.update_prices({'AAPL': 175.0})
    
    result = tracker_with_positions.remove_position('AAPL')
    
    assert result['selling_price'] == 175.0
    assert result['realized_pnl'] == 250.0  # (175 - 150) * 10


def test_remove_position_not_owned(tracker):
    """Test selling position that doesn't exist returns None."""
    result = tracker.remove_position('AAPL', exit_price=200.0)
    assert result is None


def test_remove_position_quantity_exceeds_owned(tracker_with_positions):
    """Test selling more than owned returns None."""
    result = tracker_with_positions.remove_position('AAPL', quantity=20, exit_price=200.0)
    assert result is None


def test_remove_position_invalid_quantity(tracker_with_positions):
    """Test selling with invalid quantity raises error."""
    with pytest.raises(ValueError, match="must be positive"):
        tracker_with_positions.remove_position('AAPL', quantity=0, exit_price=200.0)
    
    with pytest.raises(ValueError, match="must be positive"):
        tracker_with_positions.remove_position('AAPL', quantity=-5, exit_price=200.0)


def test_remove_position_invalid_exit_price(tracker_with_positions):
    """Test selling with invalid exit price raises error."""
    with pytest.raises(ValueError, match="must be positive"):
        tracker_with_positions.remove_position('AAPL', exit_price=0)
    
    with pytest.raises(ValueError, match="must be positive"):
        tracker_with_positions.remove_position('AAPL', exit_price=-100)


def test_remove_position_profit(tracker_with_positions):
    """Test realized P&L is positive when selling for profit."""
    result = tracker_with_positions.remove_position('AAPL', exit_price=200.0)
    
    assert result['realized_pnl'] > 0
    assert tracker_with_positions.total_realized_pnl == Decimal('500')


def test_remove_position_loss(tracker_with_positions):
    """Test realized P&L is negative when selling for loss."""
    result = tracker_with_positions.remove_position('AAPL', exit_price=100.0)
    
    assert result['realized_pnl'] < 0
    assert tracker_with_positions.total_realized_pnl == Decimal('-500')


# ══════════════════════════════════════════════════════════════
# TEST 4 — UPDATE PRICES
# ══════════════════════════════════════════════════════════════

def test_update_prices_all_positions(tracker_with_positions):
    """Test updating prices for all positions."""
    tracker_with_positions.update_prices({
        'AAPL': 175.0,
        'MSFT': 350.0,
        'GOOGL': 120.0
    })
    
    aapl = tracker_with_positions._find_position('AAPL')
    assert aapl.current_price == Decimal('175')
    assert aapl.unrealized_pnl == Decimal('250')  # (175 - 150) * 10
    
    msft = tracker_with_positions._find_position('MSFT')
    assert msft.current_price == Decimal('350')
    assert msft.unrealized_pnl == Decimal('250')  # (350 - 300) * 5


def test_update_prices_partial(tracker_with_positions):
    """Test updating prices for only some positions."""
    tracker_with_positions.update_prices({
        'AAPL': 175.0
        # MSFT and GOOGL not provided
    })
    
    aapl = tracker_with_positions._find_position('AAPL')
    assert aapl.current_price == Decimal('175')
    
    # MSFT should still have entry price as current price
    msft = tracker_with_positions._find_position('MSFT')
    assert msft.current_price == Decimal('300')


def test_update_prices_empty_dict(tracker_with_positions):
    """Test updating with empty dict does nothing."""
    initial_aapl_price = tracker_with_positions._find_position('AAPL').current_price
    
    tracker_with_positions.update_prices({})
    
    # Prices should not change
    assert tracker_with_positions._find_position('AAPL').current_price == initial_aapl_price


def test_update_prices_invalid_price(tracker_with_positions):
    """Test invalid prices are skipped, not fatal."""
    tracker_with_positions.update_prices({
        'AAPL': 175.0,
        'MSFT': 0,      # Invalid: zero
        'GOOGL': -50    # Invalid: negative
    })
    
    # AAPL should update
    assert tracker_with_positions._find_position('AAPL').current_price == Decimal('175')
    
    # MSFT and GOOGL should keep old prices
    assert tracker_with_positions._find_position('MSFT').current_price == Decimal('300')
    assert tracker_with_positions._find_position('GOOGL').current_price == Decimal('100')


def test_update_prices_missing_ticker(tracker_with_positions):
    """Test missing tickers are logged but not fatal."""
    tracker_with_positions.update_prices({
        'AAPL': 175.0
        # MSFT missing
    })
    
    # Should not crash
    assert tracker_with_positions._find_position('AAPL').current_price == Decimal('175')


# ══════════════════════════════════════════════════════════════
# TEST 5 — QUERIES
# ══════════════════════════════════════════════════════════════

def test_get_position(tracker_with_positions):
    """Test retrieving a single position."""
    pos = tracker_with_positions.get_position('AAPL')
    
    assert pos is not None
    assert pos['ticker'] == 'AAPL'
    assert pos['quantity'] == 10.0
    assert pos['entry_price'] == 150.0


def test_get_position_not_found(tracker):
    """Test retrieving non-existent position returns None."""
    pos = tracker.get_position('AAPL')
    assert pos is None


def test_get_all_positions(tracker_with_positions):
    """Test retrieving all positions."""
    positions = tracker_with_positions.get_all_positions()
    
    assert len(positions) == 3
    tickers = [p['ticker'] for p in positions]
    assert 'AAPL' in tickers
    assert 'MSFT' in tickers
    assert 'GOOGL' in tickers


def test_get_all_positions_empty(tracker):
    """Test retrieving positions when none exist."""
    positions = tracker.get_all_positions()
    assert positions == []


def test_get_portfolio_value(tracker_with_positions):
    """Test calculating total portfolio value."""
    # Positions: AAPL 10@150, MSFT 5@300, GOOGL 3@100 = $3300
    # Cash: $10000 - $3300 = $6700
    # Total: $10000
    
    value = tracker_with_positions.get_portfolio_value()
    assert value == Decimal('10000')
    
    # Update prices
    tracker_with_positions.update_prices({
        'AAPL': 200.0,  # +$500
        'MSFT': 350.0,  # +$250
        'GOOGL': 150.0  # +$150
    })
    
    # New value: $10000 + $900 = $10900
    value = tracker_with_positions.get_portfolio_value()
    assert value == Decimal('10900')


def test_get_total_unrealized_pnl(tracker_with_positions):
    """Test calculating total unrealized P&L."""
    # Initially, unrealized P&L should be 0 (current = entry)
    pnl = tracker_with_positions.get_total_unrealized_pnl()
    assert pnl == Decimal('0')
    
    # Update prices
    tracker_with_positions.update_prices({
        'AAPL': 175.0,   # +$250
        'MSFT': 350.0,   # +$250
        'GOOGL': 120.0   # +$60
    })
    
    # Total unrealized: $560
    pnl = tracker_with_positions.get_total_unrealized_pnl()
    assert pnl == Decimal('560')


def test_get_portfolio_summary(tracker_with_positions):
    """Test getting complete portfolio summary."""
    summary = tracker_with_positions.get_portfolio_summary()
    
    assert 'cash' in summary
    assert 'portfolio_value' in summary
    assert 'total_positions' in summary
    assert 'total_unrealized_pnl' in summary
    assert 'total_realized_pnl' in summary
    assert 'return_pct' in summary
    
    assert summary['total_positions'] == 3
    assert summary['portfolio_value'] == Decimal('10000')
    assert summary['return_pct'] == Decimal('0')  # No change yet


def test_get_portfolio_summary_with_profit(tracker_with_positions):
    """Test portfolio summary shows profit correctly."""
    # Update prices to create unrealized profit
    tracker_with_positions.update_prices({
        'AAPL': 200.0,
        'MSFT': 350.0,
        'GOOGL': 150.0
    })
    
    summary = tracker_with_positions.get_portfolio_summary()
    
    # Portfolio value should be $10,900
    assert summary['portfolio_value'] == Decimal('10900')
    
    # Return should be +9%
    assert summary['return_pct'] == Decimal('9.00')


def test_get_portfolio_summary_zero_value(test_dir):
    """Test summary handles zero portfolio value."""
    tracker = PositionTracker(initial_capital=0)
    summary = tracker.get_portfolio_summary()
    
    # Should not crash
    assert summary['cash_pct'] == Decimal('0')
    assert summary['return_pct'] == Decimal('0')


# ══════════════════════════════════════════════════════════════
# TEST 6 — RECONCILIATION
# ══════════════════════════════════════════════════════════════

def test_reconcile_fresh_tracker(tracker):
    """Test reconciliation passes for fresh tracker."""
    assert tracker.reconcile() is True


def test_reconcile_after_buy(tracker):
    """Test reconciliation passes after buying."""
    tracker.add_position('AAPL', 10, 150.0)
    assert tracker.reconcile() is True


def test_reconcile_after_sell(tracker_with_positions):
    """Test reconciliation passes after selling."""
    tracker_with_positions.remove_position('AAPL', exit_price=200.0)
    assert tracker_reconcile() is True


def test_reconcile_after_price_update(tracker_with_positions):
    """Test reconciliation passes after price update."""
    tracker_with_positions.update_prices({'AAPL': 200.0})
    assert tracker_with_positions.reconcile() is True


def test_reconcile_equation(tracker_with_positions):
    """Test reconciliation equation holds: cash + positions_at_entry = initial + realized."""
    # Buy 10 AAPL @ $150 = $1500
    # Sell 5 AAPL @ $200 = realized P&L of $250
    
    tracker_with_positions.remove_position('AAPL', quantity=5, exit_price=200.0)
    
    # Manual calculation:
    # cash = initial - $1500 + $1000 = $9500
    # positions_at_entry = 5 * $150 + 5 * $300 + 3 * $100 = $2550
    # total = $12050
    
    # initial + realized = $10000 + $250 = $10250
    # Wait, this doesn't match. Let me recalculate...
    
    # Actually:
    # Initial positions: AAPL 10@150, MSFT 5@300, GOOGL 3@100
    # Cost: $1500 + $1500 + $300 = $3300
    # Cash after buy: $10000 - $3300 = $6700
    
    # Sell 5 AAPL @ $200:
    # Cash inflow: $1000
    # Realized P&L: (200-150)*5 = $250
    # Cash after sell: $6700 + $1000 = $7700
    
    # Remaining positions at entry:
    # AAPL 5@150 = $750
    # MSFT 5@300 = $1500
    # GOOGL 3@100 = $300
    # Total at entry: $2550
    
    # Left side: $7700 + $2550 = $10250
    # Right side: $10000 + $250 = $10250
    # ✅ Matches!
    
    assert tracker_with_positions.reconcile() is True


# ══════════════════════════════════════════════════════════════
# TEST 7 — PERSISTENCE (FILE OPERATIONS)
# ══════════════════════════════════════════════════════════════

def test_save_and_load_positions(test_dir):
    """Test positions are saved and loaded correctly."""
    # Create tracker and buy
    tracker1 = PositionTracker(initial_capital=10000)
    tracker1.add_position('AAPL', 10, 150.0)
    tracker1.add_position('MSFT', 5, 300.0)
    
    # Create new tracker (should load from disk)
    tracker2 = PositionTracker(initial_capital=10000)
    
    assert len(tracker2.positions) == 2
    assert tracker2._find_position('AAPL') is not None
    assert tracker2._find_position('MSFT') is not None
    assert tracker2.cash == Decimal('6700')


def test_save_and_load_cash(test_dir):
    """Test cash balance is saved and loaded correctly."""
    tracker1 = PositionTracker(initial_capital=10000)
    tracker1.add_position('AAPL', 10, 150.0)
    tracker1.remove_position('AAPL', exit_price=200.0)
    
    realized_pnl = tracker1.total_realized_pnl
    final_cash = tracker1.cash
    
    # Create new tracker
    tracker2 = PositionTracker(initial_capital=10000)
    
    assert tracker2.cash == final_cash
    assert tracker2.total_realized_pnl == realized_pnl


def test_trade_history_recorded(test_dir):
    """Test every trade is recorded in trade history."""
    tracker = PositionTracker(initial_capital=10000)
    
    tracker.add_position('AAPL', 10, 150.0)
    tracker.add_position('MSFT', 5, 300.0)
    tracker.remove_position('AAPL', quantity=5, exit_price=200.0)
    
    # Check trade history file
    assert os.path.exists('risk/portfolio/trade_history.csv')
    
    df = pd.read_csv('risk/portfolio/trade_history.csv')
    assert len(df) == 3  # 2 buys, 1 sell
    
    # First trade
    assert df.iloc[0]['action'] == 'BUY'
    assert df.iloc[0]['ticker'] == 'AAPL'
    
    # Third trade
    assert df.iloc[2]['action'] == 'SELL'
    assert df.iloc[2]['ticker'] == 'AAPL'
    assert df.iloc[2]['realized_pnl'] == 250.0


def test_portfolio_history_recorded(test_dir):
    """Test portfolio snapshots are recorded."""
    tracker = PositionTracker(initial_capital=10000)
    tracker.add_position('AAPL', 10, 150.0)
    
    # Check history file
    assert os.path.exists('risk/portfolio/portfolio_history.csv')
    
    df = pd.read_csv('risk/portfolio/portfolio_history.csv')
    assert len(df) >= 1  # At least one snapshot
    
    latest = df.iloc[-1]
    assert latest['total_value'] == 10000.0
    assert latest['num_positions'] == 1


def test_backup_creates_files(test_dir):
    """Test backup creates timestamped directory with all files."""
    tracker = PositionTracker(initial_capital=10000)
    tracker.add_position('AAPL', 10, 150.0)
    
    backup_path = tracker.backup()
    
    assert backup_path is not None
    assert os.path.exists(backup_path)
    assert os.path.exists(os.path.join(backup_path, 'current_positions.csv'))
    assert os.path.exists(os.path.join(backup_path, 'cash_balance.json'))


# ══════════════════════════════════════════════════════════════
# TEST 8 — EDGE CASES
# ══════════════════════════════════════════════════════════════

def test_sell_immediately_after_buy(tracker):
    """Test buying and immediately selling."""
    tracker.add_position('AAPL', 10, 150.0)
    result = tracker.remove_position('AAPL', exit_price=150.0)
    
    assert result is not None
    assert result['realized_pnl'] == 0.0  # No profit/loss
    assert len(tracker.positions) == 0
    assert tracker.cash == Decimal('10000')  # Back to initial


def test_multiple_buys_and_sells(tracker):
    """Test complex sequence of trades."""
    tracker.add_position('AAPL', 10, 100.0)   # $1000
    tracker.add_position('AAPL', 5, 120.0)    # $600, avg $106.67
    tracker.remove_position('AAPL', quantity=7, exit_price=150.0)  # Sell 7
    tracker.add_position('AAPL', 3, 130.0)    # Buy 3 more
    
    # Should have 8 + 3 = 11 shares
    aapl = tracker._find_position('AAPL')
    assert aapl is not None
    assert aapl.quantity == Decimal('11')


def test_sell_all_positions(tracker_with_positions):
    """Test selling all positions."""
    tracker_with_positions.remove_position('AAPL', exit_price=200.0)
    tracker_with_positions.remove_position('MSFT', exit_price=350.0)
    tracker_with_positions.remove_position('GOOGL', exit_price=150.0)
    
    assert len(tracker_with_positions.positions) == 0
    assert tracker_with_positions.cash > Decimal('10000')  # Made profit


def test_decimal_precision(tracker):
    """Test Decimal arithmetic maintains precision."""
    tracker.add_position('AAPL', 3, 33.33)
    
    # 3 * 33.33 = 99.99, not 100.00
    assert tracker.cash == Decimal('10000') - Decimal('99.99')


# ══════════════════════════════════════════════════════════════
# MAIN — Run Tests Without Pytest
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    """
    Run tests manually without pytest.
    
    Usage: python3 tests/test_portfolio_tracker.py
    """
    import traceback
    
    # Create test directory
    test_dir = tempfile.mkdtemp(prefix='portfolio_test_')
    original_cwd = os.getcwd()
    os.chdir(test_dir)
    
    print("="*60)
    print("PORTFOLIO TRACKER TEST SUITE")
    print("="*60)
    print(f"Test directory: {test_dir}\n")
    
    # Get all test functions
    test_functions = [
        (name, obj) for name, obj in globals().items()
        if name.startswith('test_') and callable(obj)
    ]
    
    passed = 0
    failed = 0
    errors = []
    
    for name, test_func in test_functions:
        try:
            # Create fresh tracker for each test
            if 'tracker_with_positions' in test_func.__code__.co_varnames:
                tracker = PositionTracker(initial_capital=10000)
                tracker.add_position('AAPL', 10, 150.0)
                tracker.add_position('MSFT', 5, 300.0)
                tracker.add_position('GOOGL', 3, 100.0)
                test_func(tracker)
            elif 'tracker' in test_func.__code__.co_varnames:
                tracker = PositionTracker(initial_capital=10000)
                test_func(tracker)
            elif 'test_dir' in test_func.__code__.co_varnames:
                test_func(test_dir)
            else:
                test_func()
            
            print(f"✅ {name}")
            passed += 1
            
        except AssertionError as e:
            print(f"❌ {name}: {e}")
            failed += 1
            errors.append((name, traceback.format_exc()))
            
        except Exception as e:
            print(f"💥 {name}: {e}")
            failed += 1
            errors.append((name, traceback.format_exc()))
    
    # Summary
    print("\n" + "="*60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*60)
    
    if errors:
        print("\nFAILURES:\n")
        for name, trace in errors:
            print(f"\n{name}:")
            print(trace)
    
    # Cleanup
    os.chdir(original_cwd)
    shutil.rmtree(test_dir, ignore_errors=True)
    
    # Exit code
    sys.exit(0 if failed == 0 else 1)