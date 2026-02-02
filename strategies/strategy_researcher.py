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
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return (rsi)
    
    def rsi_strategy(self, ticker, price_data):
        if price_data is None or price_data.empty:
            return (None)
        
        close = price_data['Close']
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        rsi = self.calculate_rsi(close)
        current_rsi = float(rsi.iloc[-1])
        current_price = float(close.iloc[-1])

        if not 0 <= current_rsi <= 100:
            raise ValueError(f"Invalid RSI value: {current_rsi}")
        if current_rsi < 30:
            signal = 'BUY'
            confidence = 0.65
            reasoning = f"RSI at {current_rsi:.1f} indicates oversold condition"
        elif current_rsi > 70:
            signal = 'SELL'
            confidence = 0.65
            reasoning = f"RSI at {current_rsi:.1f} indicates overbought condition"
        else:
            signal = 'HOLD'
            confidence = 0.40
            reasoning = f"RSI at {current_rsi:.1f} in neutral zone"
        
        return {
            'ticker': ticker,
            'action': signal,
            'confidence': confidence,
            'current_price': current_price,
            'rsi': current_rsi,
            'reasoning': reasoning,
            'source': 'RSI Strategy'
        }
    
    def analyze(self, ticker, price_data):
        return self.rsi_strategy(ticker, price_data)

strategy_engine = StrategyResearcher()

if __name__ == "__main__":
    from data.data_enginner import data_access
    print("Testing Stratgy...")
    data = data_access.get_price_history('AAPL', days=90)
    signal = strategy_engine.analyze('AAPL', data)
    print(f"\n Signal: {signal}")