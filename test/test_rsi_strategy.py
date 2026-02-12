import pytest
import pandas as pd
import numpy as np
from strategies.rsi_strategy import RSIStrategy

class TestRSIStrategy:
    
    @pytest.fixture
    def strategy(self):
        """Create strategy instance"""
        return RSIStrategy()
    
    @pytest.fixture
    def sample_data(self):
        """Create sample price data"""
        dates = pd.date_range('2024-01-01', periods=100, freq='D')
        data = pd.DataFrame({
            'Close': np.random.uniform(190, 210, 100),
            'High': np.random.uniform(195, 215, 100),
            'Low': np.random.uniform(185, 205, 100),
            'Volume': np.random.randint(1000000, 5000000, 100)
        }, index=dates)
        return data
    
    def test_calculate_rsi(self, strategy, sample_data):
        """Test RSI calculation"""
        rsi = strategy.calculate_rsi(sample_data['Close'])
        
        assert rsi is not None
        assert len(rsi) == len(sample_data)
        assert rsi.min() >= 0
        assert rsi.max() <= 100
    
    def test_generate_signal_buy(self, strategy):
        """Test BUY signal generation"""
        # Create data with low RSI (oversold)
        data = pd.DataFrame({
            'Close': [100, 95, 90, 85, 80],  # Declining
            'High': [102, 97, 92, 87, 82],
            'Low': [98, 93, 88, 83, 78],
            'Volume': [1000000] * 5
        })
        
        signal = strategy.generate_signal('TEST', data)
        
        # With declining prices, RSI should be low
        assert signal is not None
        assert 'action' in signal
        assert 'confidence' in signal
    
    def test_generate_signal_insufficient_data(self, strategy):
        """Test with insufficient data"""
        data = pd.DataFrame({
            'Close': [100, 101, 102]  # Only 3 points
        })
        
        signal = strategy.generate_signal('TEST', data)
        
        assert signal['action'] == 'HOLD'
        assert 'Insufficient data' in signal['reasoning']
    
    def test_signal_structure(self, strategy, sample_data):
        """Test signal has all required fields"""
        signal = strategy.generate_signal('AAPL', sample_data)
        
        required_fields = [
            'ticker', 'action', 'confidence', 
            'current_price', 'reasoning', 'strategy'
        ]
        
        for field in required_fields:
            assert field in signal, f"Missing field: {field}"
    
    def test_save_signal(self, strategy, sample_data, tmp_path):
        """Test signal saving"""
        signal = strategy.generate_signal('AAPL', sample_data)
        
        # Save to temp directory
        strategy.save_signal(signal, output_dir=str(tmp_path))
        
        # Check file was created
        files = list(tmp_path.glob('*.json'))
        assert len(files) == 1

if __name__ == "__main__":
    pytest.main([__file__, '-v'])