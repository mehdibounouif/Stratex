"""
Objective
 - Create a system to track current portfolio positions in real-time

Position Tracker - Manages current portfolio positions

Tracks:
- What stocks we own
- Quantity and entry prices
- Current P&L (unrealized)
- Position history
"""


"""
Deliverables:
   - risk/portfolio/current_positions.csv
   - risk/portfolio/portfolio_history.csv
   - risk/portfolio/cash_balance.json
"""


import pandas as pd
import json
from config.base_config import BaseConfig
from config.trading_config import TradingConfig
from datetime import datetime , timezone
#from config import BaseConfig, TradingConfig
import os

class PositionTracker:
    def __init__(self, initial_capital=None):
        if initial_capital is None:
            initial_capital = TradingConfig.INITIAL_CAPITAL
        
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions = []  # List of current positions
        
        # File paths
        self.positions_file = 'risk/portfolio/current_positions.csv'
        self.history_file = 'risk/portfolio/portfolio_history.csv'
        self.cash_file = 'risk/portfolio/cash_balance.json'
        
        
        # Load existing positions if available
        self._load_positions()

    def add_position(self, ticker, quantity, entry_price, entry_date=None):
#    """
#    function that handle bying shares,check if there's alreasy the position with the
#     specified ticker if no creates it and update the cash buy sybstracting the total cost
#     of the trade ,aveage pricing , save the cash to disk to keep track of the last time
#     it was updated record portfolio history
#     Returns bool
#        True if the position was successfully added, False otherwise.
#    """
        
        ticker = self._normalize_ticker(ticker)
        if entry_date is None:
              entry_date = datetime.now(timezone.utc).isoformat()
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        if entry_price <= 0:
            raise ValueError("Entry price must be positive")
        position_total_cost = entry_price * quantity
        if position_total_cost > self.cash:
            print(f"Not enough cash to buy {quantity} shares of {ticker}. Needed: {position_total_cost}, available: {self.cash}")
            return False
        existing_position = self._find_position(ticker)
        if existing_position:
            old_quantity = existing_position['quantity']
            old_entry_price = existing_position['entry_price']
            new_quantity = old_quantity + quantity
            average_price = (old_entry_price * old_quantity + entry_price * quantity) / new_quantity
            existing_position['quantity'] = new_quantity
            existing_position['entry_price'] = average_price
            existing_position['current_price'] = entry_price 
        #This means now your shares (old + new) cost average_price per each share on average.
        else:
            self.positions.append({
            'ticker': ticker,
            'quantity': quantity,
            'entry_price' : entry_price,
            'current_price' : entry_price,
            'unrealized_pnl': 0.0,
            'entry_date' : entry_date
        })
        self.cash -= position_total_cost
        if self.cash < 0:
            raise RuntimeError("Cash balance went negative — system invariant broken")
        self._save_cash()
        print(f"Bought {quantity} shares of {ticker} at ${entry_price} each. Cash remaining: ${self.cash:.2f}")
        self._record_history()
        return True
    
    def _normalize_ticker(self, ticker):
        if not isinstance(ticker, str):
            raise ValueError("Ticker must be a string")
        return ticker.strip().upper()
    
    def remove_position(self, ticker, quantity=None, exit_price=None):
#    """
#    Reduce or fully close a position after a SELL trade.
#    decides how much to sell if no specified quantity sell everything 
#    calculate the total selling price and get the realized profit increase the cash by the 
#    the tota selling price updates or removes the whole position save cash to disk and records
#    the portfolio state
#    Returns dict or None
#        Dictionary containing trade details (P&L, prices, quantity),
#        or None if the sell operation fails.
#    """
        ticker = self._normalize_ticker(ticker)
        position = self._find_position(ticker)
        if not position:
            print(f"No postion fount for {ticker}")
            return None
        if quantity is not None and quantity <= 0:
            raise ValueError("Quantity to sell must be positive")
        if quantity is None:
            quantity_to_sell = position['quantity']
        else:
            if quantity > position['quantity']:
               print(f"cannot sell {quantity} shares of {ticker}.Only {position['quantity']} is available!")
               return None
            quantity_to_sell = quantity
        selling_price = exit_price if exit_price is not None else position['current_price']
        cash_in_flow = selling_price * quantity_to_sell
        self.cash += cash_in_flow
        self._save_cash()
        realized_pnl = (selling_price - position['entry_price']) * quantity_to_sell
        if quantity_to_sell == position['quantity']:
            self.positions.remove(position)
        else:
           position['quantity'] -= quantity_to_sell
        sell_infos = {
                'ticker' : ticker,
                'quantity_sold' : quantity_to_sell,
                'selling_price' : selling_price,
                'realized_pnl' : realized_pnl
            }
        print(f"Sold {quantity_to_sell} shares of {ticker} at ${selling_price:.3f} each. Cash now: ${self.cash:.2f}")
        if realized_pnl > 0:
            print("HALAWA ;)") 
        self._record_history()
        return sell_infos

    def update_prices(self, price_dict):
#    """
#    Update current market prices and unrealized P&L for all positions
#    save updated positions to cvs file
#    This method performs mark-to-market valuation.
#    It does NOT affect cash or realized P&L.
#    """
        for position in self.positions:
            ticker = position['ticker']
            if ticker in price_dict:
                current_price = price_dict[ticker]
                position['current_price'] = current_price
                position['unrealized_pnl'] = (current_price - position['entry_price']) * position['quantity']
            else:
                print(f"no shares from {ticker}")
        try:
            os.makedirs(os.path.dirname(self.positions_file), exist_ok=True)
            pd.DataFrame(self.positions).to_csv(self.positions_file, index=False)
            self._record_history()
        except Exception as e:
            print("Error while saving current positions to CSV while udating prices")
            print(e)
    def get_position(self, ticker):
#    """
#    Retrieve a single position by ticker.
#    Returns
#    dict or None
#        The position dictionary if found, otherwise None.
#    """
        ticker = self._normalize_ticker(ticker)
        position = self._find_position(ticker)
        if position:
                return position
        return None
    def get_all_positions(self):
#    """
#    Retrieve all currently open positions.
#    Returns
#    list
#        A copy of the list containing all position dictionaries.
#    """
        return [ position.copy() for position in self.positions]
    def get_portfolio_value(self):
#    """
#    Calculate the total portfolio value.
#    Returns
#    -------
#    float
#        Total portfolio value defined as:
#        cash + sum(quantity * current_price for all positions)
#    """
            positions_value = sum(position['quantity'] * position['current_price'] for position in self.positions)
            portfolio_value =  positions_value + self.cash
            return portfolio_value
    def get_total_unrealized_pnl(self):
#    """
#    Calculate total unrealized profit or loss across all positions.
#    Returns
#    -------
#    float
#        Sum of unrealized P&L for all open positions.
#    """
        return sum(pos['unrealized_pnl'] for pos in self.positions)
    def get_portfolio_summary(self):
#    """
#    Generate a high-level summary of the portfolio state.
#    Returns
#    -------
#    dict
#        Dictionary containing:
#        - total_value: Total portfolio value
#        - cash: Available cash
#        - cash_pct: Cash as a percentage of total value
#        - positions_value: Market value of all positions
#        - num_positions: Number of open positions
#        - total_unrealized_pnl: Total unrealized profit/loss
#        - total_return_pct: Return relative to initial capital
#    """
      positions_value = sum(pos['quantity'] * pos['current_price'] for pos in self.positions)
      total_unrealized_pnl = self.get_total_unrealized_pnl()
      total_value = self.get_portfolio_value()
      cash = self.cash
      cash_purcentage = (cash / total_value * 100) if total_value != 0 else 0
      cap = self.initial_capital
      return_percentage = ((total_value - cap) / cap) * 100 if cap != 0 else 0
      summury = {
          'positions_value' : positions_value,
          'cash' : cash,
          'cash_prct' : cash_purcentage,
          'portfolio_value' : total_value,
          'total_position' : len(self.positions),
          'total_unrealized_pnl' : total_unrealized_pnl,
          'return_percentage' : return_percentage
      }
      return summury
    def _find_position(self, ticker):
#    """
#    Find an existing position by ticker symbol.
#    dict or None
#        The matching position dictionary, or None if not found.
        for position in self.positions:
            if position['ticker'] == ticker:
                return position
        return None

    def _load_positions(self):
#    """
#    Load positions and cash balance from disk if files exist.
#    Behavior
#    --------
#    - Restores positions from CSV
#    - Restores cash balance from JSON
#    - Allows portfolio recovery after restart or crash
#    Notes
#    -----
#    Internal initialization helper.
#    """
        if os.path.exists(self.positions_file):
            try:
                df = pd.read_csv(self.positions_file)
                self.positions = df.to_dict(orient="records")
            except Exception as e:
                print("Error loading positions file:")
                print(e)
        if os.path.exists(self.cash_file):
            try:
                with open(self.cash_file, "r") as f:
                    data = json.load(f)
                    self.cash = data.get("cash", self.cash)
            except Exception as e:
                print("Error loading cash file:")
                print(e)
    def _save_cash(self):
        """
        Persist the current cash balance to disk.

        Behavior
        --------
        - Saves cash amount and last update timestamp to JSON

        Notes
        -----
        Internal persistence method.
        """

        try:
            directory = os.path.dirname(self.cash_file)
            # Create the directory if it does not exist
            # exist_ok=True prevents an error if the folder already exists
            os.makedirs(directory, exist_ok=True)
            data = {
                "cash": float(self.cash),
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            # "with" ensures the file is closed automatically
            with open(self.cash_file, "w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print("Error while saving cash:")
            print(e)
    def _record_history(self):
        """
        Record a snapshot of the current portfolio state.

        Behavior
        --------
        - Appends portfolio metrics to portfolio_history.csv
        - Used to build equity curves and performance analytics

        Notes
        -----
        Stores portfolio STATE, not individual trades.
        """
        try:
            directory = os.path.dirname(self.history_file)
            os.makedirs(directory, exist_ok=True)
            time_date = datetime.now(timezone.utc).isoformat()
            summary = self.get_portfolio_summary()

            history_row = {
                "timestamp": time_date,
                "cash": summary["cash"],
                "positions_value": summary["positions_value"],
                "total_value": summary["portfolio_value"],
                "cash_pct": summary["cash_prct"],
                "num_positions": summary["total_position"],
                "total_unrealized_pnl": summary["total_unrealized_pnl"],
                "return_pct": summary["return_percentage"],
            }
            df = pd.DataFrame([history_row])
            file_exist = os.path.exists(self.history_file)
            df.to_csv(
                self.history_file,
                mode= "a",
                header= not file_exist,
                index= False
            )
        except Exception as e:
            print("Error while recording portfolio history:")
            print(e)

    def _save_positions(self):
        pass
    def display_positions(self):
        """
        Print a formatted, human-readable view of current positions.
        Behavior
        --------
        - Displays all positions in a table
        - Shows entry price, current price, and unrealized P&L
        - Prints portfolio summary below the table
        """
        if not self.positions:
            print("No open positions.")
            return

        df = pd.DataFrame(self.positions)
        df['unrealized_pnl'] = df['unrealized_pnl'].round(2)
        df['entry_price'] = df['entry_price'].round(2)
        df['current_price'] = df['current_price'].round(2)
        print("\nCurrent Positions:")
        print(df[['ticker', 'quantity', 'entry_price', 'current_price', 'unrealized_pnl']].to_string(index=False))

        summary = self.get_portfolio_summary()
        print("\nPortfolio Summary:")
        print(f"Total Value: ${summary['portfolio_value']:.2f}")
        print(f"Cash: ${summary['cash']:.2f} ({summary['cash_prct']:.2f}%)")
        print(f"Positions Value: ${summary['positions_value']:.2f}")
        print(f"Total Unrealized P&L: ${summary['total_unrealized_pnl']:.2f}")
        print(f"Return %: {summary['return_percentage']:.2f}%")
        print(f"Total Positions: {summary['total_position']}\n")
 
position_tracker =  PositionTracker()

if __name__ == "__main__":
    tracker = PositionTracker()
    
    # Initial state
    print("Initial positions:", tracker.get_all_positions())
    print("Cash:", tracker.cash)

    # Buy shares
    tracker.add_position('AAPL', 5, 200.0)
    tracker.add_position('MSFT', 2, 380.0)

    # Display after buying
    tracker.display_positions()

    # Update market prices
    tracker.update_prices({
        'AAPL': 210.5,
        'MSFT': 390.2
    })

    # Display after price update
    tracker.display_positions()

    # Sell some shares
    tracker.remove_position('AAPL', 3, 215.0)
    
    # Final state
    tracker.display_positions()
