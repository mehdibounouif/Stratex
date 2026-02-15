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
from datetime import datetime, timezone
import os
from logger import setup_logging, get_logger
from decimal import Decimal
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
@dataclass
class Position:
    ticker: str
    quantity: Decimal
    entry_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    entry_date: str
    
    def to_dict(self):
        """Convert to dict for CSV."""
        return {
            'ticker': self.ticker,
            'quantity': float(self.quantity),
            'entry_price': float(self.entry_price),
            'current_price': float(self.current_price),
            'unrealized_pnl': float(self.unrealized_pnl),
            'entry_date': self.entry_date
        }
    @classmethod
    def from_dict(cls, data: Dict) -> 'Position':
        """Create from dict loaded from CSV."""
        return cls(
            ticker=data['ticker'],
            quantity=Decimal(str(data['quantity'])),
            entry_price=Decimal(str(data['entry_price'])),
            current_price=Decimal(str(data['current_price'])),
            unrealized_pnl=Decimal(str(data['unrealized_pnl'])),
            entry_date=data['entry_date']
        )
    def copy(self):
        """Create a deep copy of the position for rollback."""
        return Position(
            ticker=self.ticker,
            quantity=self.quantity,
            entry_price=self.entry_price,
            current_price=self.current_price,
            unrealized_pnl=self.unrealized_pnl,
            entry_date=self.entry_date
        )

setup_logging()
log = get_logger('risk.portfolio.portfolio_tracker') 

class PositionTracker:
    def __init__(self, initial_capital=None):
        log.info("Initializing PositionTracker")
        if initial_capital is None:
            initial_capital = TradingConfig.INITIAL_CAPITAL
        self.initial_capital = Decimal(str(initial_capital))
        log.info(f"Initial capital is set to: ${self.initial_capital}") 
        self.cash = Decimal(str(initial_capital))
        self.positions: List[Position] = [] 
        self.total_realized_pnl = Decimal('0')

        # Files paths
        self.positions_file = 'risk/portfolio/current_positions.csv'
        self.history_file = 'risk/portfolio/portfolio_history.csv'
        self.cash_file = 'risk/portfolio/cash_balance.json'
        self.trades_file = 'risk/portfolio/trade_history.csv'  # ✓ Fixed extension

        # Load existing positions if available
        self._load_positions()
        log.info(f"PositionTracker initialized with {len(self.positions)} positions and ${self.cash} cash")

    def add_position(self, ticker, quantity, entry_price, entry_date=None):
        """
        Function that handles buying shares, checks if there's already a position with the
        specified ticker. If not, creates it and updates the cash by subtracting the total cost
        of the trade, average pricing, save the cash to disk to keep track of the last time
        it was updated, record portfolio history.
        
        Returns:
            bool: True if the position was successfully added, False otherwise.
        """
        log.info(f"Attempting to add position: {ticker}, qty={quantity}, price=${entry_price}")
        quantity = Decimal(str(quantity))
        entry_price = Decimal(str(entry_price))
        ticker = self._normalize_ticker(ticker)
        
        if entry_date is None:
            entry_date = datetime.now(timezone.utc).isoformat()
        
        if quantity <= 0:
            log.error(f"Invalid quantity: {quantity} (must be positive)")
            raise ValueError("Quantity must be positive")
        
        if entry_price <= 0:
            log.error(f"Invalid entry price: {entry_price} (must be positive)")
            raise ValueError("Entry price must be positive")
        
        position_total_cost = entry_price * quantity
        
        if position_total_cost > self.cash:
            error_msg = f"Insufficient funds: need ${position_total_cost} to buy shares, have only ${self.cash}"
            log.error(error_msg)
            raise ValueError(error_msg)
        
        # Save cash and position for backup if the trade fails
        original_cash = self.cash
        original_positions = [p.copy() for p in self.positions]
        
        try:
            existing_position = self._find_position(ticker)
            
            if existing_position:
                log.info(f"Adding to existing {ticker} position")
                old_quantity = Decimal(str(existing_position.quantity))
                old_entry_price = Decimal(str(existing_position.entry_price))
                new_quantity = old_quantity + quantity
                average_price = (old_entry_price * old_quantity + entry_price * quantity) / new_quantity
                existing_position.quantity = new_quantity
                existing_position.entry_price = average_price
                existing_position.current_price = entry_price
                log.info(f"Updated {ticker}: qty={new_quantity}, avg_price=${average_price:.2f}")
            else:
                new_position = Position(
                      ticker=ticker,
                      quantity=quantity,
                      entry_price=entry_price,
                      current_price= entry_price,
                      unrealized_pnl=Decimal('0'),
                      entry_date=entry_date  
                )
                self.positions.append(new_position)
            self.cash -= position_total_cost
            
            if self.cash < 0:
                raise RuntimeError("Cash balance went negative — system invariant broken")
            
            log.info(f"Cash deducted: ${position_total_cost:.2f}, remaining: ${self.cash:.2f}")
            
            self._save_cash()
            self._save_positions()
            self._record_trade('BUY', ticker, float(quantity), float(entry_price))  # ✓ Fixed method name
            self._record_history()
            
            log.info(f"✅ Successfully bought {quantity} shares of {ticker} at ${entry_price}")
            return True
            
        except Exception as e:
            log.error(f"Transaction failed, rolling back: {e}")
            self.cash = original_cash
            self.positions = original_positions
            raise

    def _record_trade(self, action, ticker, quantity, price, pnl=None):
        """
        Purpose: Record every individual trade for audit trail
    
        Args:
            action: 'BUY' or 'SELL'
            ticker: Stock symbol
            quantity: Number of shares
            price: Trade price
            pnl: Realized profit/loss (only for SELL)
            
        This creates a permanent record of EVERY trade you make.
        """
        try:
            os.makedirs(os.path.dirname(self.trades_file), exist_ok=True)
            
            trade = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'action': action,
                'ticker': ticker,
                'quantity': quantity,
                'price': price,
                'total_value': quantity * price,
                'realized_pnl': pnl if action == 'SELL' else None
            }
            
            df = pd.DataFrame([trade])
            file_exists = os.path.exists(self.trades_file)
            write_header = not file_exists or (os.path.getsize(self.trades_file) == 0)
            
            df.to_csv(self.trades_file, mode='a', header=write_header, index=False)
            log.info(f"📝 Recorded {action} trade: {quantity} of {ticker} at ${price:.2f}")
            
        except Exception as e:
            log.error(f"❌ Error recording trade: {e}")

    def _normalize_ticker(self, ticker):
        """
        Normalize ticker symbol to uppercase and strip whitespace.
        """
        if not isinstance(ticker, str):
            log.error(f"Ticker must be a string, got {type(ticker)}")
            raise ValueError("Ticker must be a string")
        
        normalized = ticker.strip().upper()
        log.debug(f"Normalized ticker: '{ticker}' -> '{normalized}'")
        return normalized
    
    def remove_position(self, ticker, quantity=None, exit_price=None):
        """
        Reduce or fully close a position after a SELL trade.
        Decides how much to sell. If no specified quantity, sell everything.
        Calculate the total selling price and get the realized profit, increase the cash by the
        total selling price, updates or removes the whole position, save cash to disk and records
        the portfolio state.
        
        Returns:
            dict or None: Dictionary containing trade details (P&L, prices, quantity),
                         or None if the sell operation fails.
        """
        log.info(f"Attempting to sell {ticker}: qty={quantity}, price=${exit_price}")
        ticker = self._normalize_ticker(ticker)
        position = self._find_position(ticker)
        
        if not position:
            log.error(f"No position found for {ticker}")
            return None
        
        if quantity is not None:
            quantity = Decimal(str(quantity))
            if quantity <= 0:
                log.error(f"Invalid sell quantity: {quantity}")
                raise ValueError("Quantity to sell must be positive")
        
        if quantity is None:
            quantity_to_sell = position.quantity
            log.info(f"Selling entire {ticker} position: {quantity_to_sell} shares")
        else:
            quantity_to_sell = Decimal(str(quantity))
            if quantity_to_sell > position.quantity:
                error_msg = f"Cannot sell {quantity_to_sell} shares of {ticker}. Only {position.quantity} available"
                log.error(error_msg)
                return None
        
        original_cash = self.cash
        original_positions = [p.copy() for p in self.positions]
        original_realized_pnl = self.total_realized_pnl
        
        try:
            if exit_price is not None:
                selling_price = Decimal(str(exit_price))
                if selling_price <= 0:
                    log.error(f"Invalid exit price for {ticker}: {selling_price}")
                    raise ValueError("Exit price must be positive")
            else:
                selling_price = position.current_price
            cash_inflow = selling_price * quantity_to_sell
            self.cash += cash_inflow
            realized_pnl = (selling_price - position.entry_price) * quantity_to_sell
            self.total_realized_pnl += realized_pnl
            
            log.info(f"Realized P&L for {ticker}: ${realized_pnl:.2f}")
            
            if quantity_to_sell == position.quantity:
                log.info(f"Closing entire {ticker} position")
                self.positions.remove(position)
            else:
                log.info(f"Reducing {ticker} position by {quantity_to_sell} shares")
                position.quantity -= quantity_to_sell
                position.unrealized_pnl = (
                (position.current_price - position.entry_price)
                * position.quantity
                )
            
            self._save_cash()
            self._save_positions()
            self._record_trade('SELL', ticker, float(quantity_to_sell), float(selling_price), float(realized_pnl))
            self._record_history()
            
            sell_info = {
                'ticker': ticker,
                'quantity_sold': float(quantity_to_sell),
                'selling_price': float(selling_price),
                'realized_pnl': float(realized_pnl)
            }
            
            log.info(f"✅ Successfully sold {quantity_to_sell} shares of {ticker} at ${selling_price:.2f}")
            if realized_pnl > 0:
                log.info(f"🎉 Profit: ${realized_pnl:.2f}")
            elif realized_pnl < 0:
                log.warning(f"📉 Loss: ${realized_pnl:.2f}")
            
            return sell_info
            
        except Exception as e:
            log.error(f"Sell transaction failed, rolling back: {e}")
            self.cash = original_cash
            self.positions = original_positions
            self.total_realized_pnl = original_realized_pnl
            raise

    def update_prices(self, price_dict):
        """
        Update current market prices and unrealized P&L for all positions.
        Save updated positions to CSV file.
        This method performs mark-to-market valuation.
        It does NOT affect cash or realized P&L.
        """
        log.info(f"Updating prices for {len(price_dict)} tickers")
        updated_count = 0
        for position in self.positions:
            ticker = position.ticker
            if ticker in price_dict:
                current_price = Decimal(str(price_dict[ticker]))
                position.current_price = current_price
                position.unrealized_pnl = (current_price - position.entry_price) * position.quantity
                log.debug(f"Updated {ticker}: price=${current_price:.2f}, unrealized_pnl=${position.unrealized_pnl:.2f}")
                updated_count += 1
            else:
                log.warning(f"No price data for {ticker}")
        log.info(f"Updated {updated_count}/{len(self.positions)} positions")
        try:
            self._save_positions()
            self._record_history()
        except Exception as e:
            log.error(f"Error saving positions after price update: {e}")
            raise

    def get_position(self, ticker):
        """
        Retrieve a single position by ticker.
        
        Returns:
            dict or None: The position dictionary if found, otherwise None.
        """
        ticker = self._normalize_ticker(ticker)
        position = self._find_position(ticker)
        
        if position:
            log.debug(f"Retrieved position for {ticker}")
            return position.to_dict()
        
        log.debug(f"No position found for {ticker}")
        return None
    
    def get_all_positions(self):
        """
        Retrieve all currently open positions.
        
        Returns:
            list: A copy of the list containing all position dictionaries.
        """
        log.debug(f"Retrieved {len(self.positions)} positions")
        return [position.to_dict() for position in self.positions]
    
    def get_portfolio_value(self):
        """
        Calculate the total portfolio value.
        
        Returns:
            float: Total portfolio value defined as:
                  cash + sum(quantity * current_price for all positions)
        """
        positions_value = sum((pos.quantity * pos.current_price) 
            for pos in self.positions
        )
        portfolio_value = positions_value + self.cash
        log.debug(f"Portfolio value: ${portfolio_value:.2f} (positions: ${positions_value:.2f}, cash: ${self.cash:.2f})")
        return portfolio_value
    
    def get_total_unrealized_pnl(self):
        """
        Calculate total unrealized profit or loss across all positions.
        
        Returns:
            float: Sum of unrealized P&L for all open positions.
        """
        total = sum(pos.unrealized_pnl
            for pos in self.positions
        )
        log.debug(f"Total unrealized P&L: ${total:.2f}")
        return total
    
    def get_portfolio_summary(self):
        """
        Generate a high-level summary of the portfolio state.
        
        Returns:
            dict: Dictionary containing portfolio metrics
        """
        positions_value = sum(
            pos.quantity * pos.current_price
            for pos in self.positions
        )
        total_unrealized_pnl = self.get_total_unrealized_pnl()
        total_value = self.get_portfolio_value()
        cash = self.cash
        
        cash_pct = (cash / total_value * 100) if total_value != 0 else Decimal('0')
        return_pct = ((Decimal(str(total_value)) - self.initial_capital) / self.initial_capital) * 100 if self.initial_capital != 0 else Decimal('0')
        
        summary = {
            'positions_value': float(positions_value),
            'cash': float(cash),
            'cash_pct': float(cash_pct),
            'portfolio_value': float(total_value),
            'total_positions': len(self.positions),
            'total_unrealized_pnl': float(total_unrealized_pnl),
            'total_realized_pnl': float(self.total_realized_pnl),
            'return_pct': float(return_pct)
        }
        
        log.debug(f"Portfolio summary: value=${summary['portfolio_value']:.2f}, return={summary['return_pct']:.2f}%")
        return summary

    def _find_position(self, ticker):
        """
        Find an existing position by ticker symbol.
        
        Returns:
            dict or None: The matching position dictionary, or None if not found.
        """
        for position in self.positions:
            if position.ticker == ticker:
                return position
        return None

    def _validate_positions(self):
        """
        Called after loading positions from CSV.
        Validates that loaded data has valid values.
        Field existence is guaranteed by dataclass.
        """
        log.info("Validating loaded positions")
    
        for i, pos in enumerate(self.positions):
            if pos.quantity <= 0:
                error_msg = f"Invalid quantity for {pos.ticker}: {pos.quantity}"
                log.error(error_msg)
                raise ValueError(error_msg)
        
            if pos.entry_price <= 0:
                error_msg = f"Invalid entry price for {pos.ticker}: {pos.entry_price}"
                log.error(error_msg)
                raise ValueError(error_msg)
        
            if pos.current_price <= 0:
                error_msg = f"Invalid current price for {pos.ticker}: {pos.current_price}"
                log.error(error_msg)
                raise ValueError(error_msg)
    
        log.info("✅ All positions validated successfully")

    def _load_positions(self):
        """
        Load positions and cash balance from disk if files exist.
        
        Behavior:
        - Restores positions from CSV
        - Restores cash balance from JSON
        - Allows portfolio recovery after restart or crash
        """
        log.info("Loading positions from disk")
        
        if os.path.exists(self.positions_file):
            try:
                df = pd.read_csv(self.positions_file)
                if df.empty:
                    log.warning("⚠️ Positions file exists but is empty!")
                else:
                    self.positions = [ 
                        Position.from_dict(row)
                        for row in df.to_dict(orient='records')
                    ]
                    self._validate_positions()
                    log.info(f"✅ Loaded {len(self.positions)} positions from {self.positions_file}")
            except Exception as e:
                log.error(f"❌ CRITICAL: Error loading positions file: {e}")
                log.error("Starting with empty positions - VERIFY THIS IS CORRECT!")
        else:
            log.info("No existing positions file found, starting fresh")
        
        if os.path.exists(self.cash_file):
            try:
                with open(self.cash_file, "r") as f:
                    data = json.load(f)
                    self.cash = Decimal(str(data.get("cash", self.cash)))
                    self.total_realized_pnl = Decimal(str(data.get("total_realized_pnl", 0)))
                    log.info(f"✅ Loaded cash balance: ${self.cash:.2f}, realized P&L: ${self.total_realized_pnl:.2f}")
            except Exception as e:
                log.error(f"❌ Error loading cash file: {e}")
        else:
            log.info("No existing cash file found, using initial capital")

    def _save_cash(self):
        """
        Purpose: Save cash balance to disk.
        Why? So if the program crashes, we don't lose track of our cash!
        """
        try:
            directory = os.path.dirname(self.cash_file)
            os.makedirs(directory, exist_ok=True)
            
            data = {
                "cash": float(self.cash),
                "total_realized_pnl": float(self.total_realized_pnl),
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            
            with open(self.cash_file, "w") as f:
                json.dump(data, f, indent=4)
            
            log.debug(f"Saved cash balance: ${self.cash:.2f}")
        except Exception as e:
            log.error(f"❌ Error saving cash: {e}")
            raise

    def _record_history(self):
        """
        Record a snapshot of the current portfolio state.
        """
        try:
            directory = os.path.dirname(self.history_file)
            os.makedirs(directory, exist_ok=True)
            timestamp = datetime.now(timezone.utc).isoformat()
            summary = self.get_portfolio_summary()

            history_row = {
                "timestamp": timestamp,
                "cash": summary["cash"],
                "positions_value": summary["positions_value"],
                "total_value": summary["portfolio_value"],
                "cash_pct": summary["cash_pct"],
                "num_positions": summary["total_positions"],
                "total_unrealized_pnl": summary["total_unrealized_pnl"],
                "total_realized_pnl": summary["total_realized_pnl"],
                "return_pct": summary["return_pct"],
            }
            
            df = pd.DataFrame([history_row])
            file_exists = os.path.exists(self.history_file)
            write_header = not file_exists or (os.path.getsize(self.history_file) == 0)
            
            df.to_csv(
                self.history_file,
                mode="a",
                header=write_header,
                index=False
            )
            log.debug(f"Recorded portfolio history snapshot")
        except Exception as e:
            log.error(f"❌ Error recording portfolio history: {e}")

    def _save_positions(self):
        """
        Purpose: Save all positions to CSV.
        Why? So if the program crashes, we don't lose track of what we own!
        This is called after EVERY buy/sell operation.
        """
        try:
            os.makedirs(os.path.dirname(self.positions_file), exist_ok=True)
            
            if self.positions:
                position_data = [pos.to_dict() for pos in self.positions]
                pd.DataFrame(position_data).to_csv(self.positions_file, index=False)
                log.debug(f"Saved {len(self.positions)} positions to {self.positions_file}")
            else:
                empty_df = pd.DataFrame(columns=[
                    'ticker', 'quantity', 'entry_price', 
                    'current_price', 'unrealized_pnl', 'entry_date'
                ])
                empty_df.to_csv(self.positions_file, index=False)
                log.debug("Saved empty positions file (no open positions)")
        except Exception as e:
            log.error(f"❌ Error saving positions: {e}")
            raise
    
    def display_positions(self):
        """
        Print formatted, human-readable view of current positions.
        """
        if not self.positions:
            print("\n" + "="*60)
            print("No open positions.")
            print("="*60)
            log.info("Displayed empty positions")
            return

        positions_data = [pos.to_dict() for pos in self.positions]
        df = pd.DataFrame(positions_data)
        df['unrealized_pnl'] = df['unrealized_pnl'].round(2)
        df['entry_price'] = df['entry_price'].round(2)
        df['current_price'] = df['current_price'].round(2)
        
        print("\n" + "="*60)
        print("CURRENT POSITIONS")
        print("="*60)
        print(df[['ticker', 'quantity', 'entry_price', 'current_price', 'unrealized_pnl']].to_string(index=False))

        summary = self.get_portfolio_summary()
        print("\n" + "="*60)
        print("PORTFOLIO SUMMARY")
        print("="*60)
        print(f"Total Value:          ${summary['portfolio_value']:,.2f}")
        print(f"Cash:                 ${summary['cash']:,.2f} ({summary['cash_pct']:.1f}%)")
        print(f"Positions Value:      ${summary['positions_value']:,.2f}")
        print(f"Total Unrealized P&L: ${summary['total_unrealized_pnl']:,.2f}")
        print(f"Total Realized P&L:   ${summary['total_realized_pnl']:,.2f}")
        print(f"Total Return:         {summary['return_pct']:.2f}%")
        print(f"Number of Positions:  {summary['total_positions']}")
        print("="*60 + "\n")
        
        log.info("Displayed positions summary")

    def backup(self, backup_dir='risk/portfolio/backups'):
        """
        Create timestamped backup of all portfolio files.
        Use this before major changes or at end of each trading day.
        """
        import shutil
    
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(backup_dir, timestamp)
    
        try:
            os.makedirs(backup_path, exist_ok=True)
        
        # Backup all files
            if os.path.exists(self.positions_file):
                shutil.copy2(self.positions_file, os.path.join(backup_path, 'current_positions.csv'))
            if os.path.exists(self.cash_file):
                shutil.copy2(self.cash_file, os.path.join(backup_path, 'cash_balance.json'))
            if os.path.exists(self.history_file):
                shutil.copy2(self.history_file, os.path.join(backup_path, 'portfolio_history.csv'))
            if os.path.exists(self.trades_file):
                shutil.copy2(self.trades_file, os.path.join(backup_path, 'trade_history.csv'))
        
            log.info(f"✅ Backup created: {backup_path}")
            return backup_path
        except Exception as e:
            log.error(f"❌ Backup failed: {e}")
        return None

position_tracker = PositionTracker()

if __name__ == "__main__":
    log.info("="*60)
    log.info("Starting PositionTracker demo")
    log.info("="*60)
    
    tracker = PositionTracker()
    
    # Initial state
    print("\n📊 Initial State:")
    print(f"Positions: {tracker.get_all_positions()}")
    print(f"Cash: ${tracker.cash}")

    # Buy shares
    print("\n💰 Buying shares...")
    tracker.add_position('AAPL', 5, 200.0)
    tracker.add_position('MSFT', 2, 380.0)

    # Display after buying
    tracker.display_positions()

    # Update market prices
    print("\n📈 Updating market prices...")
    tracker.update_prices({
        'AAPL': 210.5,
        'MSFT': 390.2
    })

    # Display after price update
    tracker.display_positions()

    # Sell some shares
    print("\n💸 Selling shares...")
    tracker.remove_position('AAPL', 3, 215.0)
    
    # Final state
    tracker.display_positions()
    
    log.info("Demo completed")
