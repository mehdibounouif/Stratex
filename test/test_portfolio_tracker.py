"""
Comprehensive pytest suite for PositionTracker

Tests cover:
- Position addition and removal
- Price updates
- Portfolio calculations
- File persistence and recovery
- Error handling and edge cases
- Reconciliation and data integrity
"""

import pytest
import pandas as pd
import json
import os
import shutil
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
import tempfile

# Import the class to test
# Assuming the module is named portfolio_tracker.py
# Adjust the import based on your actual module structure
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Mock the logger to avoid dependency issues
sys.modules['logger'] = MagicMock()
sys.modules['config.base_config'] = MagicMock()
sys.modules['config.trading_config'] = MagicMock()

# Now import after mocking
from risk.portfolio.portfolio_tracker import PositionTracker


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files"""
    temp_directory = tempfile.mkdtemp()
    yield temp_directory
    # Cleanup
    if os.path.exists(temp_directory):
        shutil.rmtree(temp_directory)


@pytest.fixture
def tracker(temp_dir, monkeypatch):
    """Create a fresh PositionTracker instance for each test"""
    # Override file paths to use temp directory
    positions_file = os.path.join(temp_dir, 'current_positions.csv')
    history_file = os.path.join(temp_dir, 'portfolio_history.csv')
    cash_file = os.path.join(temp_dir, 'cash_balance.json')
    trades_file = os.path.join(temp_dir, 'trade_history.csv')
    
    tracker = PositionTracker(initial_capital=10000)
    tracker.positions_file = positions_file
    tracker.history_file = history_file
    tracker.cash_file = cash_file
    tracker.trades_file = trades_file
    
    return tracker


class TestPositionTrackerInitialization:
    """Test initialization and setup"""
    
    def test_initial_state(self, tracker):
        """Test that tracker initializes with correct default values"""
        assert tracker.cash == Decimal('10000')
        assert tracker.initial_capital == Decimal('10000')
        assert len(tracker.positions) == 0
        assert tracker.total_realized_pnl == Decimal('0')
    
    def test_custom_initial_capital(self, temp_dir):
        """Test initialization with custom capital"""
        tracker = PositionTracker(initial_capital=50000)
        assert tracker.initial_capital == Decimal('50000')
        assert tracker.cash == Decimal('50000')


class TestAddPosition:
    """Test adding positions (buying stocks)"""
    
    def test_add_new_position(self, tracker):
        """Test adding a new position successfully"""
        result = tracker.add_position('AAPL', 10, 150.0)
        
        assert result is True
        assert len(tracker.positions) == 1
        assert tracker.positions[0].ticker == 'AAPL'
        assert tracker.positions[0].quantity == Decimal('10')
        assert tracker.positions[0].entry_price == Decimal('150.0')
        assert tracker.cash == Decimal('10000') - Decimal('1500')
    
    def test_add_to_existing_position(self, tracker):
        """Test adding to an existing position (average price calculation)"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.add_position('AAPL', 5, 160.0)
        
        position = tracker.positions[0]
        expected_avg = (Decimal('150') * 10 + Decimal('160') * 5) / 15
        
        assert len(tracker.positions) == 1
        assert position.quantity == Decimal('15')
        assert position.entry_price == expected_avg
        assert tracker.cash == Decimal('10000') - Decimal('2300')
    
    def test_add_position_insufficient_funds(self, tracker):
        """Test that buying with insufficient funds raises error"""
        with pytest.raises(ValueError, match="Insufficient funds"):
            tracker.add_position('AAPL', 100, 150.0)
    
    def test_add_position_invalid_quantity(self, tracker):
        """Test that negative/zero quantity raises error"""
        with pytest.raises(ValueError, match="must be positive"):
            tracker.add_position('AAPL', 0, 150.0)
        
        with pytest.raises(ValueError, match="must be positive"):
            tracker.add_position('AAPL', -5, 150.0)
    
    def test_add_position_invalid_price(self, tracker):
        """Test that negative/zero price raises error"""
        with pytest.raises(ValueError, match="must be positive"):
            tracker.add_position('AAPL', 10, 0)
        
        with pytest.raises(ValueError, match="must be positive"):
            tracker.add_position('AAPL', 10, -150.0)
    
    def test_ticker_normalization(self, tracker):
        """Test that tickers are normalized to uppercase"""
        tracker.add_position('aapl', 10, 150.0)
        tracker.add_position('  MSFT  ', 5, 200.0)
        
        assert tracker.positions[0].ticker == 'AAPL'
        assert tracker.positions[1].ticker == 'MSFT'
    
    def test_ticker_validation(self, tracker):
        """Test that invalid tickers raise errors"""
        with pytest.raises(ValueError, match="must be a string"):
            tracker.add_position(123, 10, 150.0)
    
    def test_rollback_on_failure(self, tracker, monkeypatch):
        """Test that state rolls back if save fails"""
        original_cash = tracker.cash
        
        # Mock _save_cash to raise an exception
        def mock_save_cash():
            raise IOError("Disk full")
        
        monkeypatch.setattr(tracker, '_save_cash', mock_save_cash)
        
        with pytest.raises(IOError):
            tracker.add_position('AAPL', 10, 150.0)
        
        # Verify rollback
        assert tracker.cash == original_cash
        assert len(tracker.positions) == 0


class TestRemovePosition:
    """Test removing positions (selling stocks)"""
    
    def test_sell_partial_position(self, tracker):
        """Test selling part of a position"""
        tracker.add_position('AAPL', 10, 150.0)
        result = tracker.remove_position('AAPL', quantity=5, exit_price=160.0)
        
        assert result is not None
        assert result['quantity_sold'] == Decimal('5')
        assert result['selling_price'] == Decimal('160.0')
        assert result['realized_pnl'] == Decimal('50.0')  # (160-150) * 5
        
        assert len(tracker.positions) == 1
        assert tracker.positions[0].quantity == Decimal('5')
        assert tracker.cash == Decimal('10000') - Decimal('1500') + Decimal('800')
    
    def test_sell_entire_position(self, tracker):
        """Test selling entire position"""
        tracker.add_position('AAPL', 10, 150.0)
        result = tracker.remove_position('AAPL', quantity=10, exit_price=160.0)
        
        assert result is not None
        assert len(tracker.positions) == 0
        assert tracker.total_realized_pnl == Decimal('100.0')
    
    def test_sell_without_quantity_sells_all(self, tracker):
        """Test that omitting quantity sells entire position"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.remove_position('AAPL', exit_price=160.0)
        
        assert len(tracker.positions) == 0
    
    def test_sell_nonexistent_position(self, tracker):
        """Test selling a position that doesn't exist"""
        result = tracker.remove_position('AAPL', quantity=5, exit_price=160.0)
        assert result is None
    
    def test_sell_more_than_owned(self, tracker):
        """Test selling more shares than owned"""
        tracker.add_position('AAPL', 10, 150.0)
        result = tracker.remove_position('AAPL', quantity=15, exit_price=160.0)
        
        assert result is None
        assert len(tracker.positions) == 1  # Position unchanged
    
    def test_sell_with_loss(self, tracker):
        """Test selling at a loss"""
        tracker.add_position('AAPL', 10, 150.0)
        result = tracker.remove_position('AAPL', quantity=5, exit_price=140.0)
        
        assert result['realized_pnl'] == Decimal('-50.0')  # (140-150) * 5
        assert tracker.total_realized_pnl == Decimal('-50.0')
    
    def test_sell_invalid_quantity(self, tracker):
        """Test selling with invalid quantity"""
        tracker.add_position('AAPL', 10, 150.0)
        
        with pytest.raises(ValueError, match="must be positive"):
            tracker.remove_position('AAPL', quantity=0, exit_price=160.0)
        
        with pytest.raises(ValueError, match="must be positive"):
            tracker.remove_position('AAPL', quantity=-5, exit_price=160.0)
    
    def test_sell_invalid_price(self, tracker):
        """Test selling with invalid price"""
        tracker.add_position('AAPL', 10, 150.0)
        
        with pytest.raises(ValueError, match="must be positive"):
            tracker.remove_position('AAPL', quantity=5, exit_price=0)
        
        with pytest.raises(ValueError, match="must be positive"):
            tracker.remove_position('AAPL', quantity=5, exit_price=-160.0)
    
    def test_sell_uses_current_price_if_not_specified(self, tracker):
        """Test that sell uses current_price when exit_price not provided"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.update_prices({'AAPL': 160.0})
        
        result = tracker.remove_position('AAPL', quantity=5)
        
        assert result['selling_price'] == Decimal('160.0')


class TestUpdatePrices:
    """Test price updates and P&L calculations"""
    
    def test_update_single_position_price(self, tracker):
        """Test updating price for a single position"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.update_prices({'AAPL': 160.0})
        
        position = tracker.positions[0]
        assert position.current_price == Decimal('160.0')
        assert position.unrealized_pnl == Decimal('100.0')  # (160-150) * 10
    
    def test_update_multiple_positions(self, tracker):
        """Test updating prices for multiple positions"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.add_position('MSFT', 5, 200.0)
        
        tracker.update_prices({
            'AAPL': 160.0,
            'MSFT': 210.0
        })
        
        assert tracker.positions[0].unrealized_pnl == Decimal('100.0')
        assert tracker.positions[1].unrealized_pnl == Decimal('50.0')
    
    def test_update_price_with_missing_ticker(self, tracker):
        """Test that missing price data is handled gracefully"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.add_position('MSFT', 5, 200.0)
        
        # Only update AAPL, not MSFT
        tracker.update_prices({'AAPL': 160.0})
        
        assert tracker.positions[0].current_price == Decimal('160.0')
        # MSFT price should remain unchanged
        assert tracker.positions[1].current_price == Decimal('200.0')
    
    def test_update_price_negative_unrealized_pnl(self, tracker):
        """Test that unrealized loss is calculated correctly"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.update_prices({'AAPL': 140.0})
        
        assert tracker.positions[0].unrealized_pnl == Decimal('-100.0')


class TestPortfolioQueries:
    """Test portfolio query methods"""
    
    def test_get_position(self, tracker):
        """Test retrieving a specific position"""
        tracker.add_position('AAPL', 10, 150.0)
        
        position = tracker.get_position('AAPL')
        assert position is not None
        assert position['ticker'] == 'AAPL'
        assert position['quantity'] == 10.0
    
    def test_get_nonexistent_position(self, tracker):
        """Test retrieving a position that doesn't exist"""
        position = tracker.get_position('AAPL')
        assert position is None
    
    def test_get_all_positions(self, tracker):
        """Test retrieving all positions"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.add_position('MSFT', 5, 200.0)
        
        positions = tracker.get_all_positions()
        assert len(positions) == 2
        assert positions[0]['ticker'] == 'AAPL'
        assert positions[1]['ticker'] == 'MSFT'
    
    def test_get_portfolio_value(self, tracker):
        """Test portfolio value calculation"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.add_position('MSFT', 5, 200.0)
        
        # Portfolio value = cash + positions value
        # cash = 10000 - 1500 - 1000 = 7500
        # positions value at current price = 1500 + 1000 = 2500
        # total = 10000
        
        portfolio_value = tracker.get_portfolio_value()
        assert portfolio_value == Decimal('10000')
        
        # Update prices
        tracker.update_prices({'AAPL': 160.0, 'MSFT': 210.0})
        portfolio_value = tracker.get_portfolio_value()
        
        # positions value = 160*10 + 210*5 = 1600 + 1050 = 2650
        # total = 7500 + 2650 = 10150
        assert portfolio_value == Decimal('10150')
    
    def test_get_total_unrealized_pnl(self, tracker):
        """Test total unrealized P&L calculation"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.add_position('MSFT', 5, 200.0)
        tracker.update_prices({'AAPL': 160.0, 'MSFT': 190.0})
        
        total_pnl = tracker.get_total_unrealized_pnl()
        # AAPL: (160-150)*10 = 100
        # MSFT: (190-200)*5 = -50
        # Total: 50
        assert total_pnl == Decimal('50.0')
    
    def test_get_portfolio_summary(self, tracker):
        """Test portfolio summary generation"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.update_prices({'AAPL': 160.0})
        
        summary = tracker.get_portfolio_summary()
        
        assert 'positions_value' in summary
        assert 'cash' in summary
        assert 'portfolio_value' in summary
        assert 'total_positions' in summary
        assert 'total_unrealized_pnl' in summary
        assert 'total_realized_pnl' in summary
        assert 'return_pct' in summary
        
        assert summary['total_positions'] == 1
        assert summary['total_unrealized_pnl'] == Decimal('100.0')
    
    def test_portfolio_return_percentage(self, tracker):
        """Test return percentage calculation"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.update_prices({'AAPL': 165.0})  # +15 per share = +150 total
        
        summary = tracker.get_portfolio_summary()
        # Portfolio value = 8500 (cash) + 1650 (positions) = 10150
        # Return = (10150 - 10000) / 10000 = 1.5%
        assert abs(summary['return_pct'] - Decimal('1.5')) < Decimal('0.01')


class TestPersistence:
    """Test saving and loading from files"""
    
    def test_save_and_load_positions(self, tracker):
        """Test that positions are saved and can be reloaded"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.add_position('MSFT', 5, 200.0)
        
        # Create new tracker with same file paths
        new_tracker = PositionTracker(initial_capital=10000)
        new_tracker.positions_file = tracker.positions_file
        new_tracker.history_file = tracker.history_file
        new_tracker.cash_file = tracker.cash_file
        new_tracker.trades_file = tracker.trades_file
        new_tracker._load_positions()
        
        assert len(new_tracker.positions) == 2
        assert new_tracker.positions[0].ticker == 'AAPL'
        assert new_tracker.positions[1].ticker == 'MSFT'
    
    def test_save_and_load_cash(self, tracker):
        """Test that cash balance is saved and reloaded"""
        tracker.add_position('AAPL', 10, 150.0)
        original_cash = tracker.cash
        
        # Load in new tracker
        new_tracker = PositionTracker(initial_capital=10000)
        new_tracker.positions_file = tracker.positions_file
        new_tracker.history_file = tracker.history_file
        new_tracker.cash_file = tracker.cash_file
        new_tracker._load_positions()
        
        assert new_tracker.cash == original_cash
    
    def test_save_empty_positions(self, tracker):
        """Test saving when no positions exist"""
        tracker._save_positions()
        
        assert os.path.exists(tracker.positions_file)
        df = pd.read_csv(tracker.positions_file)
        assert len(df) == 0
    
    def test_load_nonexistent_files(self, tracker):
        """Test loading when files don't exist"""
        # Should not raise error, just use defaults
        new_tracker = PositionTracker(initial_capital=10000)
        assert new_tracker.cash == Decimal('10000')
        assert len(new_tracker.positions) == 0
    
    def test_trade_history_recording(self, tracker):
        """Test that trades are recorded in history file"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.remove_position('AAPL', quantity=5, exit_price=160.0)
        
        assert os.path.exists(tracker.trades_file)
        df = pd.read_csv(tracker.trades_file)
        
        assert len(df) == 2  # One BUY, one SELL
        assert df.iloc[0]['action'] == 'BUY'
        assert df.iloc[1]['action'] == 'SELL'
        assert df.iloc[1]['realized_pnl'] == 50.0
    
    def test_portfolio_history_recording(self, tracker):
        """Test that portfolio history is recorded"""
        tracker.add_position('AAPL', 10, 150.0)
        
        assert os.path.exists(tracker.history_file)
        df = pd.read_csv(tracker.history_file)
        
        assert len(df) >= 1
        assert 'timestamp' in df.columns
        assert 'total_value' in df.columns


class TestReconciliation:
    """Test portfolio reconciliation and data integrity"""
    
    def test_reconcile_after_buy(self, tracker):
        """Test that reconciliation passes after buying"""
        tracker.add_position('AAPL', 10, 150.0)
        assert tracker.reconcile() is True
    
    def test_reconcile_after_sell(self, tracker):
        """Test that reconciliation passes after selling"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.remove_position('AAPL', quantity=5, exit_price=160.0)
        assert tracker.reconcile() is True
    
    def test_reconcile_after_price_update(self, tracker):
        """Test that reconciliation still works after price updates"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.update_prices({'AAPL': 200.0})
        assert tracker.reconcile() is True
    
    def test_reconcile_detects_corruption(self, tracker):
        """Test that reconciliation detects corrupted data"""
        tracker.add_position('AAPL', 10, 150.0)
        
        # Artificially corrupt the cash balance
        tracker.cash += Decimal('1000')
        
        assert tracker.reconcile() is False
    
    def test_reconcile_with_multiple_trades(self, tracker):
        """Test reconciliation with complex trading history"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.add_position('MSFT', 5, 200.0)
        tracker.remove_position('AAPL', quantity=5, exit_price=160.0)
        tracker.add_position('GOOGL', 3, 100.0)
        tracker.remove_position('MSFT', exit_price=210.0)
        
        assert tracker.reconcile() is True


class TestBackup:
    """Test backup functionality"""
    
    def test_backup_creates_directory(self, tracker, temp_dir):
        """Test that backup creates a timestamped directory"""
        tracker.add_position('AAPL', 10, 150.0)
        
        backup_dir = os.path.join(temp_dir, 'backups')
        backup_path = tracker.backup(backup_dir=backup_dir)
        
        assert backup_path is not None
        assert os.path.exists(backup_path)
    
    def test_backup_copies_all_files(self, tracker, temp_dir):
        """Test that backup copies all portfolio files"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.remove_position('AAPL', quantity=5, exit_price=160.0)
        
        backup_dir = os.path.join(temp_dir, 'backups')
        backup_path = tracker.backup(backup_dir=backup_dir)
        
        assert os.path.exists(os.path.join(backup_path, 'current_positions.csv'))
        assert os.path.exists(os.path.join(backup_path, 'cash_balance.json'))
        assert os.path.exists(os.path.join(backup_path, 'portfolio_history.csv'))
        assert os.path.exists(os.path.join(backup_path, 'trade_history.csv'))


class TestEdgeCases:
    """Test edge cases and boundary conditions"""
    
    def test_zero_cash_remaining(self, tracker):
        """Test trading with exact cash amount"""
        tracker.add_position('AAPL', 66, 150.0)  # Costs 9900
        tracker.add_position('MSFT', 1, 100.0)   # Costs 100
        
        # Should have 0 cash left
        assert tracker.cash == Decimal('0')
        
        # Should not be able to buy more
        with pytest.raises(ValueError, match="Insufficient funds"):
            tracker.add_position('GOOGL', 1, 1.0)
    
    def test_fractional_shares(self, tracker):
        """Test handling of fractional shares"""
        tracker.add_position('AAPL', 10.5, 150.0)
        
        position = tracker.positions[0]
        assert position.quantity == Decimal('10.5')
        assert tracker.cash == Decimal('10000') - Decimal('1575')
    
    def test_high_precision_prices(self, tracker):
        """Test handling of high-precision prices"""
        tracker.add_position('AAPL', 10, 150.123456)
        
        position = tracker.positions[0]
        assert position.entry_price == Decimal('150.123456')
    
    def test_very_small_position(self, tracker):
        """Test handling of very small positions"""
        tracker.add_position('AAPL', 0.001, 1.0)
        
        assert len(tracker.positions) == 1
        assert tracker.cash == Decimal('10000') - Decimal('0.001')
    
    def test_display_positions_empty(self, tracker, capsys):
        """Test displaying positions when portfolio is empty"""
        tracker.display_positions()
        
        captured = capsys.readouterr()
        assert "No open positions" in captured.out
    
    def test_display_positions_with_data(self, tracker, capsys):
        """Test displaying positions with actual data"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.update_prices({'AAPL': 160.0})
        tracker.display_positions()
        
        captured = capsys.readouterr()
        assert "AAPL" in captured.out
        assert "CURRENT POSITIONS" in captured.out
        assert "PORTFOLIO SUMMARY" in captured.out
    
    def test_concurrent_position_updates(self, tracker):
        """Test multiple updates to same position"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.add_position('AAPL', 5, 160.0)
        tracker.add_position('AAPL', 3, 170.0)
        
        position = tracker.positions[0]
        # Should have 18 shares with weighted average price
        assert position.quantity == Decimal('18')
        
        expected_avg = (
            Decimal('150') * 10 + 
            Decimal('160') * 5 + 
            Decimal('170') * 3
        ) / 18
        assert abs(position.entry_price - expected_avg) < Decimal('0.01')


class TestPositionClass:
    """Test the Position dataclass"""
    
    def test_position_to_dict(self):
        """Test Position serialization"""
        position = Position(
            ticker='AAPL',
            quantity=Decimal('10'),
            entry_price=Decimal('150.0'),
            current_price=Decimal('160.0'),
            unrealized_pnl=Decimal('100.0'),
            entry_date='2024-01-01T00:00:00Z'
        )
        
        pos_dict = position.to_dict()
        
        assert pos_dict['ticker'] == 'AAPL'
        assert pos_dict['quantity'] == 10.0
        assert pos_dict['entry_price'] == 150.0
    
    def test_position_from_dict(self):
        """Test Position deserialization"""
        data = {
            'ticker': 'AAPL',
            'quantity': 10.0,
            'entry_price': 150.0,
            'current_price': 160.0,
            'unrealized_pnl': 100.0,
            'entry_date': '2024-01-01T00:00:00Z'
        }
        
        position = Position.from_dict(data)
        
        assert position.ticker == 'AAPL'
        assert position.quantity == Decimal('10.0')
        assert position.entry_price == Decimal('150.0')
    
    def test_position_copy(self):
        """Test Position deep copy"""
        original = Position(
            ticker='AAPL',
            quantity=Decimal('10'),
            entry_price=Decimal('150.0'),
            current_price=Decimal('160.0'),
            unrealized_pnl=Decimal('100.0'),
            entry_date='2024-01-01T00:00:00Z'
        )
        
        copied = original.copy()
        
        assert copied.ticker == original.ticker
        assert copied.quantity == original.quantity
        assert copied is not original  # Different objects


class TestDataValidation:
    """Test data validation and error handling"""
    
    def test_validate_positions_on_load(self, tracker, temp_dir):
        """Test that invalid loaded data is caught"""
        # Create a corrupted positions file
        corrupted_data = pd.DataFrame([{
            'ticker': 'AAPL',
            'quantity': -10,  # Invalid: negative quantity
            'entry_price': 150.0,
            'current_price': 160.0,
            'unrealized_pnl': 100.0,
            'entry_date': '2024-01-01T00:00:00Z'
        }])
        
        corrupted_data.to_csv(tracker.positions_file, index=False)
        
        with pytest.raises(ValueError, match="Invalid quantity"):
            new_tracker = PositionTracker(initial_capital=10000)
            new_tracker.positions_file = tracker.positions_file
            new_tracker.cash_file = tracker.cash_file
            new_tracker._load_positions()
    
    def test_validate_negative_cash(self, tracker, monkeypatch):
        """Test that negative cash is detected"""
        tracker.add_position('AAPL', 10, 150.0)
        
        # Force cash to go negative (simulating a bug)
        original_cash = tracker.cash
        tracker.cash = Decimal('-100')
        
        with pytest.raises(RuntimeError, match="Cash balance went negative"):
            # This should trigger the validation in add_position
            pass
        
        # Restore for cleanup
        tracker.cash = original_cash


# Integration tests
class TestIntegrationScenarios:
    """Test realistic trading scenarios"""
    
    def test_full_trading_day_scenario(self, tracker):
        """Test a complete trading day with multiple operations"""
        # Morning: Buy some stocks
        tracker.add_position('AAPL', 10, 150.0)
        tracker.add_position('MSFT', 5, 200.0)
        tracker.add_position('GOOGL', 3, 100.0)
        
        # Midday: Price updates
        tracker.update_prices({
            'AAPL': 155.0,
            'MSFT': 195.0,
            'GOOGL': 105.0
        })
        
        # Afternoon: Take some profits
        tracker.remove_position('AAPL', quantity=5, exit_price=155.0)
        
        # End of day: More price updates
        tracker.update_prices({
            'AAPL': 158.0,
            'MSFT': 198.0,
            'GOOGL': 103.0
        })
        
        # Verify final state
        summary = tracker.get_portfolio_summary()
        assert tracker.reconcile() is True
        assert summary['total_positions'] == 3
        assert summary['total_realized_pnl'] > 0
    
    def test_round_trip_trade(self, tracker):
        """Test buying and selling the same stock"""
        initial_cash = tracker.cash
        
        tracker.add_position('AAPL', 10, 150.0)
        tracker.remove_position('AAPL', exit_price=150.0)
        
        # Should be back to original cash (no profit/loss)
        assert tracker.cash == initial_cash
        assert tracker.total_realized_pnl == Decimal('0')
    
    def test_pyramid_strategy(self, tracker):
        """Test pyramiding into a winning position"""
        tracker.add_position('AAPL', 10, 150.0)
        tracker.update_prices({'AAPL': 160.0})
        
        # Add more after price increases
        tracker.add_position('AAPL', 5, 160.0)
        tracker.update_prices({'AAPL': 170.0})
        
        # Add even more
        tracker.add_position('AAPL', 3, 170.0)
        
        position = tracker.positions[0]
        assert position.quantity == Decimal('18')
        assert tracker.reconcile() is True
    
    def test_portfolio_rebalancing(self, tracker):
        """Test selling losers and adding to winners"""
        # Initial positions
        tracker.add_position('AAPL', 10, 150.0)
        tracker.add_position('MSFT', 10, 200.0)
        
        # AAPL goes up, MSFT goes down
        tracker.update_prices({'AAPL': 180.0, 'MSFT': 180.0})
        
        # Sell the loser, add to winner
        tracker.remove_position('MSFT', exit_price=180.0)
        tracker.add_position('AAPL', 10, 180.0)
        
        assert tracker.reconcile() is True
        assert len(tracker.positions) == 1
        assert tracker.positions[0].ticker == 'AAPL'


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])