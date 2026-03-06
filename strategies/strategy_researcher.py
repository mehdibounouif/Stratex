import pandas as pd
import numpy as np
from config import TradingConfig
from logger import get_logger, setup_logging
from strategies.rsi_strategy import rsi_strategy
from strategies.momentum_strategy import momentum_strategy

setup_logging()
logging = get_logger("strategies.strategy_researcher")

class StrategyResearcher:
    """
    Manages all trading strategies
    """
    
    def __init__(self):
        # Register all strategies
        self.strategies = {
            'rsi_mean_reversion': rsi_strategy,
            'momentum': momentum_strategy,
            # 'earnings': earnings_strategy,
        }
             
        # Default strategy
        self.default_strategy = TradingConfig.DEFAULT_STRATEGY
        
        logging.info(f"✅ Strategy Researcher initialized")
        logging.info(f"   Available strategies: {list(self.strategies.keys())}")
        logging.info(f"   Default: {self.default_strategy}")
    
    def analyze(self, ticker, price_data, strategy_name=None):
        """
        Analyze a stock using specified strategy
        
        Args:
            ticker: Stock symbol
            price_data: Price DataFrame
            strategy_name: Which strategy to use (None = default)
        
        Returns:
            Signal dictionary
        """
        # Use default if not specified
        if strategy_name is None:
            strategy_name = self.default_strategy
        
        # Get strategy
        strategy = self.strategies.get(strategy_name)
        
        if strategy is None:
            return {
                'ticker': ticker,
                'action': 'HOLD',
                'error': f"Strategy '{strategy_name}' not found"
            }
        
        # Generate signal
        signal = strategy.generate_signal(ticker, price_data)
        
        return signal
    
    def analyze_multiple(self, tickers, price_data_dict, strategy_name=None):
        """Analyze multiple stocks"""
        signals = []
        
        for ticker in tickers:
            data = price_data_dict.get(ticker)
            signal = self.analyze(ticker, data, strategy_name)
            signals.append(signal)
        
        return signals

# Global instance
strategy_engine = StrategyResearcher()

if __name__ == "__main__":
    from data.data_enginner import data_access
    logging.info("Testing Stratgy...")
    data = data_access.get_price_history('AMD', days=90)
    signal = strategy_engine.analyze('AMD', data, 'rsi_mean_reversion')
    rsi_strategy.save_signal(signal)
    logging.info(f"Signal: {signal}")