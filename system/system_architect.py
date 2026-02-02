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

    def analyze_signal_stock(self, ticker, data=None):
        if data is None:
            data = datetime.now().strftime("%Y-%m-%d")

        print(f"\nANALYZING: {ticker} on {data}")

        print(f"Fetching data...")
        price_data = self.data.get_price_history(ticker, days=90)
        if price_data is None or price_data.empty:
            print(f"No data available for {ticker}")
            return None
        
        print("Running strategy analysis...")
        signal = self.strategy.analyze(ticker, price_data)
        if signal is None:
            print(f"Strategy analysis faild for {ticker}")
          
        print(f"Signal : {signal['action']}")
        print(f"Confidence : {signal['confidence']:.0%}")
        print(f"Reasoning : {signal['reasoning']}")

        if signal['action'] in ['BUY', 'SELL']:
            print("\nRisk management review...")
            
            if signal['action'] == 'BUY':
              position_size = 0.05
              quantity = int((self.risk.current_portfolio_value * position_size) / signal['current_price'])
              trade_proposal = {
                   'ticker': ticker,
                   'action': signal['action'],
                   'quantity': quantity,
                   'current_price': signal['current_price'],
                   'confidence': signal['confidence'],
                   'reasoning': signal['reasoning']
              }
              approval = self.risk.approve_trade(trade_proposal)

              if approval['approved']:
                  return {
                      'ticker': ticker,
                      'action': signal['action'],
                      'quantity': quantity,
                      'price': signal['current_price'],
                      'status': 'APPROVED',
                      'signal': signal,
                      'approval': approval
                  }
              else:
                  return {
                      'ticker': ticker,
                      'action': 'HOLD',
                      'status': 'REJECTED',
                      'reason': 'Risk check failed',
                      'signal': signal,
                      'approval': approval
                  }
            else: # for sell
               # test doesn't track positions, skip sell for now
               print("SELL signal (skiping)")
               return {
                   'ticker': ticker,
                   'action': 'HOLD',
                   'status': 'PENDING',
                   'reason': 'Position tracking not implemented'
               }
        else: # for HOLD
            print("\nNo action (HOLD signal)")
            return {
                'ticker': ticker,
                'action': 'HOLD',
                'status': 'NO_ACTION',
                'signal': signal
            }

system = TradingSystem()

#if __name__ == "__main__":
    