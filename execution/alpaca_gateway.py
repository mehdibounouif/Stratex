"""
Alpaca paper trading broker gateway and order management.
Handles connectivity, order submission, and position syncing.
"""
import os
import json
from datetime import datetime
from decimal import Decimal
from dotenv import load_dotenv
import alpaca_trade_api as tradeapi
from logger import get_logger

load_dotenv()
log = get_logger('execution.alpaca_gateway')

class AlpacaGateway:
    def __init__(self):
        self.api_key = os.getenv('ALPACA_API_KEY')
        self.secret_key = os.getenv('ALPACA_SECRET_KEY')
        self.base_url = os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')
        
        # Robustness fix: some users put /v2 in the URL, but the SDK adds it again if api_version='v2'
        if self.base_url.endswith('/v2'):
            self.base_url = self.base_url[:-3]
        
        if not self.api_key or not self.secret_key:
            log.error("Alpaca API keys missing from environment.")
            self.api = None
            return

        try:
            self.api = tradeapi.REST(self.api_key, self.secret_key, self.base_url, api_version='v2')
            account = self.api.get_account()
            log.info(f"Connected to Alpaca. Account Status: {account.status}, Buying Power: ${account.buying_power}")
        except Exception as e:
            log.error(f"Failed to connect to Alpaca: {e}")
            self.api = None

    def is_market_open(self) -> bool:
        if not self.api: return False
        try:
            clock = self.api.get_clock()
            return clock.is_open
        except Exception as e:
            log.error(f"Error checking market clock: {e}")
            return False

    def get_account(self) -> dict:
        if not self.api: return {}
        try:
            acc = self.api.get_account()
            return {
                'cash': Decimal(acc.cash),
                'buying_power': Decimal(acc.buying_power),
                'portfolio_value': Decimal(acc.portfolio_value),
                'status': acc.status
            }
        except Exception as e:
            log.error(f"Error fetching account: {e}")
            return {}

    def submit_order(self, ticker, action, quantity, order_type='market') -> dict:
        if not self.api: 
            raise RuntimeError("Alpaca API not initialized")
        if action not in ['BUY', 'SELL']:
            raise ValueError(f"Invalid action: {action}")
        if not self.is_market_open():
            log.warning("Attempted to submit order while market is closed.")
            raise RuntimeError("Market is closed.")

        try:
            order = self.api.submit_order(
                symbol=ticker,
                qty=quantity,
                side=action.lower(),
                type=order_type,
                time_in_force='day'
            )
            log.info(f"Order submitted: {action} {quantity} {ticker} (ID: {order.id})")
            return {
                'order_id': order.id,
                'status': order.status,
                'ticker': ticker,
                'quantity': quantity,
                'action': action,
                'submitted_at': order.submitted_at.isoformat()
            }
        except Exception as e:
            log.error(f"Error submitting order for {ticker}: {e}")
            raise

    def get_order_status(self, order_id) -> str:
        if not self.api:                          # ADD: null-guard (matches all other methods)
            log.warning("get_order_status called but Alpaca API is not initialised.")
            return "unknown"
        try:
            order = self.api.get_order(order_id)
            return order.status
        except Exception as e:
            log.error(f"Error getting order status {order_id}: {e}")
            return "unknown"
    
    
    def cancel_order(self, order_id) -> bool:
        if not self.api:                          # ADD: null-guard
            log.warning("cancel_order called but Alpaca API is not initialised.")
            return False
        try:
            self.api.cancel_order(order_id)
            log.info(f"Order {order_id} cancelled successfully.")
            return True
        except Exception as e:
            log.error(f"Error cancelling order {order_id}: {e}")
            return False
    
    
    def cancel_all_orders(self) -> int:
        if not self.api:                          # ADD: null-guard (was already missing this too)
            log.warning("cancel_all_orders called but Alpaca API is not initialised.")
            return 0
        try:
            orders = self.api.list_orders(status='open')
            count = len(orders)          # capture count BEFORE cancelling (fixes race condition R7)
            self.api.cancel_all_orders()
            log.info(f"Cancelled {count} open orders.")
            return count
        except Exception as e:
            log.error(f"Error cancelling all orders: {e}")
            return 0

    def get_positions(self) -> list:
        if not self.api: return []
        try:
            positions = self.api.list_positions()
            return [{
                'ticker': p.symbol,
                'quantity': int(p.qty),
                'market_value': Decimal(p.market_value),
                'unrealized_pnl': Decimal(p.unrealized_intraday_pl)
            } for p in positions]
        except Exception as e:
            log.error(f"Error fetching positions: {e}")
            return []

class OrderManager:
    def __init__(self, gateway: AlpacaGateway, tracker=None):
        self.gateway = gateway
        if tracker is None:
            from risk.portfolio.portfolio_tracker import position_tracker
            self.tracker = position_tracker
        else:
            self.tracker = tracker
        self.log_file = 'execution/order_log.jsonl'
        os.makedirs('execution', exist_ok=True)

    def submit_from_signal(self, signal: dict, quantity: int) -> dict:
        try:
            order_result = self.gateway.submit_order(
                ticker=signal['ticker'],
                action=signal['action'],
                quantity=quantity
            )
            
            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'ticker': signal['ticker'],
                'action': signal['action'],
                'quantity': quantity,
                'order_id': order_result['order_id'],
                'status': order_result['status'],
                'confidence': signal['confidence'],
                'strategy': signal['strategy']
            }
            
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')
            
            return order_result
        except Exception as e:
            log.error(f"OrderManager failed to submit order: {e}")
            return {'status': 'failed', 'error': str(e)}

    def sync_positions(self):
        live_positions = self.gateway.get_positions()
        # Update tracker prices
        price_dict = {}
        for p in live_positions:
            if p['quantity'] != 0:
                price_dict[p['ticker']] = float(p['market_value'] / p['quantity'])
        
        self.tracker.update_prices(price_dict)
        
        local_positions = self.tracker.get_all_positions()
        live_tickers = {p['ticker'] for p in live_positions}
        local_tickers = {p['ticker'] for p in local_positions}
        
        discrepancies = []
        for ticker in live_tickers | local_tickers:
            live_qty = next((p['quantity'] for p in live_positions if p['ticker'] == ticker), 0)
            local_qty = next((p['quantity'] for p in local_positions if p['ticker'] == ticker), 0)
            if live_qty != local_qty:
                discrepancies.append(f"{ticker}: Live={live_qty}, Local={local_qty}")
        
        if discrepancies:
            log.warning(f"Position discrepancies found: {', '.join(discrepancies)}")
        else:
            log.info("Positions synced successfully with Alpaca.")

    def get_order_history(self, n=50) -> list:
        if not os.path.exists(self.log_file):
            return []
        with open(self.log_file, 'r') as f:
            lines = f.readlines()
            return [json.loads(line) for line in lines[-n:]]

alpaca_gateway = AlpacaGateway()
order_manager = OrderManager(alpaca_gateway)