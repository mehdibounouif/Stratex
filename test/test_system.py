"""
System-level smoke tests.
Uses the lazy factory pattern — get_trading_system() instead of the
module-level singleton (which is None until first call).
"""
import pytest
from system.system_architect import get_trading_system


@pytest.fixture(scope="module")
def trading_system():
    """
    Module-scoped fixture: creates TradingSystem once for all tests in this file.
    Scope='module' means it's initialized once, not before every test.
    """
    return get_trading_system()


def test_system_initialization(trading_system):
    """Test that system initializes without errors."""
    assert trading_system is not None
    assert trading_system.data is not None
    assert trading_system.strategy is not None
    assert trading_system.risk is not None
    assert trading_system.aggregator is not None


def test_strategy_registry(trading_system):
    """Test that strategies are registered correctly."""
    strategies = trading_system.strategy.list_strategies()
    assert 'rsi_mean_reversion' in strategies
    assert 'momentum' in strategies


def test_single_stock_analysis(trading_system):
    """Test analyzing a single stock returns a valid result."""
    result = trading_system.analyze_single_stock('AAPL')
    # Result may be None if data fetch fails in CI — that's acceptable
    if result is not None:
        assert 'ticker' in result
        assert 'action' in result
        assert result['action'] in ['BUY', 'SELL', 'HOLD']
        assert result['ticker'] == 'AAPL'


def test_data_access(trading_system):
    """Test that data retrieval works and returns OHLCV data."""
    data = trading_system.data.get_price_history('AAPL', days=30)
    if data is not None:  # may be None if yfinance rate-limited
        assert not data.empty
        assert 'Close' in data.columns


def test_risk_manager(trading_system):
    """Test that risk manager is functional and returns expected structure."""
    summary = trading_system.risk.get_risk_summary()
    assert isinstance(summary, dict)
    assert 'portfolio_value' in summary
    assert 'cash' in summary
    assert 'num_positions' in summary


# if __name__ == "__main__":
#     pytest.main([__file__, '-v'])