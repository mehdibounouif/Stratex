import pandas as pd
import numpy as np
from datetime import datetime
import json
import os


class RSIStrategy:
    """
    RSI Mean Reversion Trading Strategy
    
    Buy when RSI < 25 (oversold)
    Sell when RSI > 75 (overbought) OR 5 days passed OR -5% stop loss
    """
    
    def __init__(self, rsi_buy=25, rsi_sell=75, holding_days=5, stop_loss=0.05):
        """
        Initialize strategy with parameters
        
        Args:
            rsi_buy: RSI threshold to trigger buy (default: 25)
            rsi_sell: RSI threshold to trigger sell (default: 75)
            holding_days: Maximum holding period (default: 5)
            stop_loss: Stop loss percentage (default: 0.05 = 5%)
        """
        self.rsi_buy = rsi_buy
        self.rsi_sell = rsi_sell
        self.holding_days = holding_days
        self.stop_loss = stop_loss
        self.name = "RSI Mean Reversion"