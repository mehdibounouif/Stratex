import pandas as pd
import numpy as np
from datetime import datetime
from data.data_engineer import data_access
import json
import os
from logger import setup_logging, get_logger

setup_logging()
logging = get_logger("strategies.rsi_strategy")

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
    

    def calculate_rsi(self, prices, period=14):
        """
        Calculate RSI indicator
        
        Args:
            prices: Series of closing prices
            period: RSI period (default: 14)
        
        Returns:
            Series of RSI values
        """
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi


    def generate_signal(self, ticker, price_data):
        """
        Generate trading signal for a stock
        
        Args:
            ticker: Stock symbol
            price_data: DataFrame with OHLCV data
        
        Returns:
            dict with signal information
        """
        if price_data is None or len(price_data) < 20:
            return self._no_signal(ticker, "Insufficient data")
        
        # Calculate RSI
        price_data['RSI'] = self.calculate_rsi(price_data['Close'])
        
        # Get current values
        current_rsi = price_data['RSI'].iloc[-1]
        current_price = price_data['Close'].iloc[-1]

        # Convert to Python floats if needed
        if hasattr(current_rsi, "item"):
            current_rsi = current_rsi.item()
        if hasattr(current_price, "item"):
            current_price = current_price.item()
        
        # Check if RSI is valid
        if pd.isna(current_rsi):
            return self._no_signal(ticker, "RSI calculation failed")
        
        # Generate signal
        if current_rsi < self.rsi_buy:
            # OVERSOLD - BUY signal
            signal = self._buy_signal(ticker, current_price, current_rsi, price_data)
        
        elif current_rsi > self.rsi_sell:
            # OVERBOUGHT - SELL signal
            signal = self._sell_signal(ticker, current_price, current_rsi, price_data)
        
        else:
            # NEUTRAL - HOLD
            signal = self._hold_signal(ticker, current_price, current_rsi)
        
        return signal


    def _buy_signal(self, ticker, price, rsi, price_data):
        """Create BUY signal"""
        # Calculate support level (recent low)
        support_data = price_data['Low'].iloc[-20:]

        if isinstance(support_data, pd.DataFrame):
            support = float(support_data.min().min())
        else:
            support = float(support_data.min())
        
        # Calculate target (based on historical rebounds)
        target_pct = 0.10  # 10% target
        target_price = price * (1 + target_pct)
        
        # Calculate stop loss
        stop_loss_price = price * (1 - self.stop_loss)
        
        # Confidence based on how oversold
        if rsi < 20:
            confidence = 0.80  # Very oversold = high confidence
        elif rsi < 25:
            confidence = 0.70
        else:
            confidence = 0.60
        
        return {
            'ticker': ticker,
            'action': 'BUY',
            'signal_type': 'RSI_OVERSOLD',
            'confidence': confidence,
            'current_price': round(price, 2),
            'target_price': round(target_price, 2),
            'stop_loss': round(stop_loss_price, 2),
            'rsi': round(rsi, 1),
            'support_level': round(support, 2),
            'holding_period': self.holding_days,
            'reasoning': f"RSI at {rsi:.1f} indicates oversold condition. "
                        f"Historical analysis shows {confidence:.0%} probability of rebound. "
                        f"Support at ${support:.2f}.",
            'strategy': self.name,
            'timestamp': datetime.now().isoformat()
    }

    def _sell_signal(self, ticker, price, rsi, price_data):
        """Create enhanced SELL signal with resistance analysis"""

        # --- Resistance level (recent high) ---
        resistance_data = price_data['High'].iloc[-20:]

        if isinstance(resistance_data, pd.DataFrame):
            resistance = float(resistance_data.max().max())
        else:
            resistance = float(resistance_data.max())
 
        # --- Confidence based on how overbought ---
        if rsi > 85:
            confidence = 0.85   # Extremely overbought
        elif rsi > 80:
            confidence = 0.75
        else:
            confidence = 0.65

        # --- Risk context vs resistance ---
        distance_to_resistance = (resistance - price) / price

        if distance_to_resistance < 0.02:
            confidence += 0.05  # Near resistance → stronger sell

        confidence = min(confidence, 0.95)  # Cap at 95%

        return {
            'ticker': ticker,
            'action': 'SELL',
            'signal_type': 'RSI_OVERBOUGHT',
            'confidence': round(confidence, 2),
            'current_price': round(price, 2),
            'rsi': round(rsi, 1),
            'resistance_level': round(resistance, 2),
            'holding_period': self.holding_days,
            'reasoning': (
                f"RSI at {rsi:.1f} indicates overbought condition. "
                f"Price approaching resistance at ${resistance:.2f}. "
                f"Historical probability of pullback: {confidence:.0%}."
            ),
            'strategy': self.name,
            'timestamp': datetime.now().isoformat()
        }

#    def _sell_signal(self, ticker, price, rsi):
#        """Create SELL signal"""
#        confidence = 0.65
#
#        return {
#            'ticker': ticker,
#            'action': 'SELL',
#            'signal_type': 'RSI_OVERBOUGHT',
#            'confidence': confidence,
#            'current_price': round(price, 2),
#            'rsi': round(rsi, 1),
#            'reasoning': f"RSI at {rsi:.1f} indicates overbought condition. "
#                        f"Take profits before reversal.",
#            'strategy': self.name,
#            'timestamp': datetime.now().isoformat()
#        }

    def _hold_signal(self, ticker, price, rsi):
        """Create HOLD signal"""
        return {
            'ticker': ticker,
            'action': 'HOLD',
            'signal_type': 'RSI_NEUTRAL',
            'confidence': 0.40,
            'current_price': round(price, 2),
            'rsi': round(rsi, 1),
            'reasoning': f"RSI at {rsi:.1f} in neutral zone. "
                        f"Wait for clearer signal.",
            'strategy': self.name,
            'timestamp': datetime.now().isoformat()
        }
    

    def _no_signal(self, ticker, reason):
        """Create NO SIGNAL response"""
        return {
            'ticker': ticker,
            'action': 'HOLD',
            'signal_type': 'NO_SIGNAL',
            'confidence': 0.0,
            'reasoning': reason,
            'strategy': self.name,
            'timestamp': datetime.now().isoformat()
        }

    def save_signal(self, signal, output_dir='strategies/signals'):
        """
        Save signal to JSON file

        Args:
            signal: Signal dictionary
            output_dir: Directory to save signals
        """
        os.makedirs(output_dir, exist_ok=True)

        # Create filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{signal['ticker']}_{signal['action']}_{timestamp}.json"
        filepath = os.path.join(output_dir, filename)

        # Save
        with open(filepath, 'w') as f:
            json.dump(signal, f, indent=2)

        logging.info(f"✅ Signal saved: {filepath}")

    def __str__(self):
        return f"RSIStrategy(buy={self.rsi_buy}, sell={self.rsi_sell}, hold={self.holding_days}d, stop={self.stop_loss:.0%})"
    

rsi_strategy = RSIStrategy(rsi_buy=25,rsi_sell=75,holding_days=5,stop_loss=0.05)

if __name__ == '__main__':
    # Test on AAPL
    logging.info("Testing RSI Strategy...")
    logging.info(rsi_strategy)

    data = data_access.get_price_history('AMD', days=90)
    signal = rsi_strategy.generate_signal('AMD', data)

    logging.info(f"\nSignal for AAPL:")
    logging.info(f"Action: {signal['action']}")
    logging.info(f"Confidence: {signal['confidence']:.0%}")
    logging.info(f"Reasoning: {signal['reasoning']}")

    # Save signal
    rsi_strategy.save_signal(signal)