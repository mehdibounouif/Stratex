from datetime import datetime
from config import BaseConfig, TradingConfig, RiskConfig
from data.data_enginner import data_access
from strategies.strategy_researcher import strategy_engine
from risk.risk_manager import risk_manager
from logger import setup_logging, get_logger

setup_logging()
logging = get_logger('system.system_architect')

class TradingSystem:
    def __init__(self):
        BaseConfig.validate()
        self.data = data_access
        self.strategy = strategy_engine
        self.risk = risk_manager
        self.config = TradingConfig()
        self.initialized = False

        logging.info("TRADING SYSTEM INITIALIZED")
        logging.info(f"Environment: {BaseConfig.ENVIRONMENT}")
        logging.info(f"Debug Mode: {BaseConfig.DEBUG}")
        logging.info(f"Watchlist: {len(self.config.DEFAULT_WATCHLIST)} stocks\n")

    def analyze_single_stock(self, ticker, data=None):
        if data is None:
            data = datetime.now().strftime("%Y-%m-%d")

        logging.info(f"\nANALYZING: {ticker} on {data}")

        logging.info(f"Fetching data...")
        price_data = self.data.get_price_history(ticker, days=90)
        if price_data is None or price_data.empty:
            logging.error(f"No data available for {ticker}")
            return None
        
        logging.info("Running strategy analysis...")
        signal = self.strategy.analyze(ticker, price_data)
        if signal is None:
            logging.error(f"Strategy analysis faild for {ticker}")
          
        logging.info(f"Signal : {signal['action']}")
        logging.info(f"Confidence : {signal['confidence']:.0%}")
        logging.info(f"Reasoning : {signal['reasoning']}")

        if signal['action'] in ['BUY', 'SELL']:
            logging.info("\nRisk management review...")
            
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
               logging.info("SELL signal (skiping)")
               return {
                   'ticker': ticker,
                   'action': 'HOLD',
                   'status': 'PENDING',
                   'reason': 'Position tracking not implemented'
               }
        else: # for HOLD
            logging.info("No action (HOLD signal)")
            return {
                'ticker': ticker,
                'action': 'HOLD',
                'status': 'NO_ACTION',
                'signal': signal
            }
    def scan_watchlist(self):
        logging.info(f"SCANNING WATCHLIST ({len(self.config.DEFAULT_WATCHLIST)}) Stocks.")
        results = []
        
        for ticker in self.config.DEFAULT_WATCHLIST:
            try:
                decision = self.analyze_single_stock(ticker)
                if decision:
                    results.append(decision)
            except Exception as e:
                logging.info(f"Error analysing {ticker}: {e}")
                continue
        buy_signals = [r for r in results if r['action'] == 'BUY' and r['status'] == 'APPROVED']
        hold_signals = [r for r in results if r['action'] == 'HOLD']

        logging.info("\nSCAN SUMMARY:")
        logging.info(f"Total analyzed: {len(results)}")
        logging.info(f"BUY signals (approved): {len(buy_signals)}")
        logging.info(f"HOLD signals: {len(hold_signals)}")

        if buy_signals:
            logging.info("APPROVED BUY OPPORTUNITIES:")
            for signal in buy_signals:
                logging.info(f" - {signal['ticker']}: {signal['quantity']} shares ${signal['price']:.2f}\n")
        return results
    
    def run_daily_analysis(self):
        logging.info(f"#{'DAILY TRADING ANALYSIS':^68}#")
        logging.info(f"#{'Date: ' + datetime.now().strftime('%Y-%m-%d %H:%M:%S'):^68}#")

        results = self.scan_watchlist()
        return results

trading_system = TradingSystem()

if __name__ == "__main__":
    logging.info("Testing Trading System...\n")
    
    # Test 1: Analyze single stock
    logging.info("TEST 1: Single Stock Analysis\n")
    result = trading_system.analyze_single_stock('AAPL')
    logging.info(f"\nResult: {result}\n")
    
    # Test 2: Scan first 3 stocks from watchlist (to save time)
    logging.info("TEST 2: Watchlist Scan (first 3 stocks)\n")
    trading_system.config.DEFAULT_WATCHLIST = ['AAPL', 'MSFT', 'NVDA']  # Just 3 for testing
    results = trading_system.scan_watchlist()
    