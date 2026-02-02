from datetime import datetime
from config import BaseConfig, TradingConfig, RiskConfig
from data.data_enginner import data_access
from strategies.strategy_researcher import strategy_engine
from risk.risk_manager import risk_manager

class TradingSystem:
    def __init__(self):
        BaseConfig.validate()
        self.data = data_access
        self.strategy = strategy_engine
        self.risk = risk_manager
        self.config = TradingConfig()
        self.initialized = False

        print("TRADING SYSTEM INITIALIZED")
        print(f"Environment: {BaseConfig.ENVIRONMENT}")
        print(f"Debug Mode: {BaseConfig.DEBUG}")
        print(f"Watchlist: {len(self.config.DEFAULT_WATCHLIST)} stocks\n")