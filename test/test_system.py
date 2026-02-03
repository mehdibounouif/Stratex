import pytest
from system.system_architect import trading_system

def test_system_initialization():
    """Test that system initializes without errors"""
    assert trading_system is not None
    assert trading_system.data is not None
    assert trading_system.strategy is not None
    assert trading_system.risk is not None

def test_single_stock_analysis():
    """Test analyzing a single stock"""
    result = trading_system.analyze_single_stock('AAPL')
    assert result is not None
    assert 'ticker' in result
    assert 'action' in result
    assert result['action'] in ['BUY', 'SELL', 'HOLD']

def test_data_access():
    """Test data retrieval"""
    data = trading_system.data.get_price_history('AAPL', days=30)
    assert data is not None
    assert not data.empty
    assert 'Close' in data.columns

#if __name__ == "__main__":
#    pytest.main([__file__, '-v'])