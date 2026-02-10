from config import RiskConfig
from logger import get_logger, setup_logging

setup_logging()
logging = get_logger("risk.risk_manager")

class RiskManager:
    def __init__(self):
        self.config = RiskConfig()
        self.current_portfolio_value = 10000
        self.current_cach = 1000
        self.num_positions = 20
        logging.info("Using test risk manager (Message for B3aybach)")

    def check_position_size(self, size):
        """Check if position size is limited"""
        if size > self.config.MAX_POSITION_SIZE:
            return False, f"Position size {size:.1%} exceeds max {self.config.MAX_POSITION_SIZE} "
        return True, "Position size Ok"

    def check_cash_reserve(self, trade_value):
        cash_after_trade = self.current_cach - trade_value
        cash_pct = cash_after_trade / self.current_portfolio_value
        if cash_pct < self.config.MIN_CASH_RESERVE:
            return False, f"insuffcient cash reserve would have {cash_pct:.1%}"
        return True, "cash reserve Ok"

    def approve_trade(self, trade):
        logging.info(f"\nReviewing trade: {trade['ticker']}")
        checks = {}
        if trade['action'] == 'BUY':
            trade_value = trade.get('quantity', 0) * trade.get('currect_price', 0)
            position_size = trade_value / self.current_portfolio_value

            """check position size"""
            passed, msg = self.check_position_size(trade_value)
            checks['position_size'] = passed
            logging.info(f"{msg}")

            """check cash reserve"""
            passed, msg = self.check_cash_reserve(trade_value)
            checks['cash_reserve'] = passed
            logging.info(f"{msg}")

            """check max position"""
            if self.num_positions >= self.config.MAX_TOTAL_POSITIONS:
                checks['max_position'] = False
                logging.warning(f"{self.num_positions} is too much, Max positions is: {self.config.MAX_TOTAL_POSITIONS}")
            else:
                checks['max_position'] = True
                logging.info(f"{self.num_positions} is good, Max positions is: {self.config.MAX_TOTAL_POSITIONS}")

        else: # sell or hold b3aybach logic
            checks = {'position_size': True, 'cash_reserve': True, 'max_positions': True}
            logging.info("SELL/HOLD order - checks passed")
        aproved = all(checks.values())
        if aproved:
            logging.info("trade APPROVED")
        else:
            logging.info("Trade REJECTED")

        return {
            'trade': trade,
            'checks': checks,
            'approved': aproved
        }
    
risk_manager = RiskManager()

if __name__ == "__main__":
    logging.info("Testing risk manager...")
    test_trade = {
        'ticker': 'AAPL',
        'action': 'BUY',
        'quantity': 7,
        'current_price': 25.00
    }

    result = risk_manager.approve_trade(test_trade)
    logging.info(f"Result: {result}")