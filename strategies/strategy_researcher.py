"""
Strategy registry and researcher engine.
"""
from strategies.rsi_strategy import rsi_strategy
from strategies.momentum_strategy import momentum_strategy
#from strategies.mean_reversion_strategy import mean_reversion_strategy
# from strategies.pairs_strategy import pairs_strategy
#from strategies.ml_signal_strategy import ml_signal_strategy
from config.trading_config import TradingConfig
from logger import get_logger

log = get_logger('strategies.strategy_researcher')

class StrategyResearcher:
    def __init__(self):
        self.strategies = {
            'rsi_mean_reversion':  rsi_strategy,
            'momentum':            momentum_strategy,
#            'mean_reversion':      mean_reversion_strategy,
            #'pairs':               pairs_strategy,
            #'ml_signal':           ml_signal_strategy,
        }
        self.default_strategy = TradingConfig.DEFAULT_STRATEGY

    def analyze(self, ticker, price_data, strategy_name=None) -> dict:
        strat_key = strategy_name or self.default_strategy
        strategy = self.strategies.get(strat_key)
        if not strategy:
            log.error(f"Strategy {strat_key} not found in registry.")
            return {}
        return strategy.generate_signal(ticker, price_data)

    def analyze_multiple(self, ticker, price_data) -> list:
        return [s.generate_signal(ticker, price_data) for s in self.strategies.values()]

    def list_strategies(self) -> list:
        return list(self.strategies.keys())

strategy_engine = StrategyResearcher()

if __name__ == "__main__":
    from data.data_engineer import data_access
    log.info("Testing Strategy Researcher...")
    data = data_access.get_price_history('AMD', days=90)
    signal = strategy_engine.analyze('AMD', data, 'rsi_mean_reversion')
    rsi_strategy.save_signal(signal)
    log.info(f"Signal: {signal}")
