import pandas as pd
import numpy as np
from config import TradingConfig
from logger import get_logger, setup_logging
from strategies.rsi_strategy import RSIStrategy
from strategies.momentum_strategy import MomentumStrategy

setup_logging()
logging = get_logger("strategies.strategy_researcher")

momentum_strategy = MomentumStrategy()
rsi_strategy = RSIStrategy()

class StrategyResearcher:
    """
    Central registry and dispatcher for all trading strategies.

    All strategies must implement a generate_signal(ticker, price_data) method
    that returns a signal dict with at minimum:
        {ticker, action, confidence, current_price, reasoning, strategy, timestamp}

    To add a new strategy:
        1. Create your strategy class in strategies/
        2. Instantiate it at module level (like momentum_strategy above)
        3. Add it to self.strategies dict in __init__
        4. It will automatically be available via analyze()
    """

    def __init__(self):
        # ── Strategy Registry ─────────────────────────────────
        self.strategies = {
            'rsi_mean_reversion': rsi_strategy,
            'momentum':           momentum_strategy,
            # Add future strategies here:
            # 'mean_reversion':   mean_reversion_strategy,
            # 'macd':             macd_strategy,
            # 'earnings':         earnings_strategy,
        }

        # Default strategy (from TradingConfig)
        self.default_strategy = TradingConfig.DEFAULT_STRATEGY

        logging.info(f"✅ Strategy Researcher initialized")
        logging.info(f"   Available strategies: {list(self.strategies.keys())}")
        logging.info(f"   Default: {self.default_strategy}")

    def analyze(self, ticker, price_data, strategy_name=None):
        """
        Analyze a stock using specified strategy.

        Parameters
        ----------
        ticker        : str   Stock symbol
        price_data    : DataFrame   OHLCV data from DataEngineer
        strategy_name : str, optional   Key in self.strategies dict

        Returns
        -------
        dict  Signal with at minimum {ticker, action, confidence, reasoning}
        """
        if strategy_name is None:
            strategy_name = self.default_strategy

        strategy = self.strategies.get(strategy_name)

        if strategy is None:
            logging.warning(f"Strategy '{strategy_name}' not found. Available: {list(self.strategies.keys())}")
            return {
                'ticker':      ticker,
                'action':      'HOLD',
                'confidence':  0.0,
                'reasoning':   f"Strategy '{strategy_name}' not registered",
                'signal_type': 'NO_STRATEGY',
            }

        return strategy.generate_signal(ticker, price_data)

    def analyze_multiple(self, tickers, price_data_dict, strategy_name=None):
        """Analyze multiple stocks with the same strategy."""
        signals = []
        for ticker in tickers:
            data = price_data_dict.get(ticker)
            signal = self.analyze(ticker, data, strategy_name)
            signals.append(signal)
        return signals

    def list_strategies(self):
        """Return list of registered strategy names."""
        return list(self.strategies.keys())


# Global instance
strategy_engine = StrategyResearcher()

if __name__ == "__main__":
    from data.data_engineer import data_access
    logging.info("Testing Strategy Researcher...")
    data = data_access.get_price_history('AMD', days=90)
    signal = strategy_engine.analyze('AMD', data, 'rsi_mean_reversion')
    rsi_strategy.save_signal(signal)
    logging.info(f"Signal: {signal}")