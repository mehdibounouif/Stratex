import pandas as pd
import numpy as np
from config import TradingConfig

class StrategyResearcher:
    def __init__(self):
        self.config = TradingConfig()
        print("Using test strategy")
    
    def calculate_rsi(self, prices, period=14):
        """Calculate RSI indicator"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return (rsi)
    
