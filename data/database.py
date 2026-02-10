
"""
Objective:
- Create a SQLite database to store all trading data (stock prices, fundamentals, news).
"""

"""

Before emplementation verify:

- Database file created at `data/trading_data.db`
- All 3 tables exist
- Can insert sample data without errors
- Can query data successfully
- Handles duplicate inserts gracefully
"""

import sqlite3
from datetime import datetime, timedelta
from config import BaseConfig
import pandas as pd
from logger import get_logger, setup_logging

setup_logging()
logging = get_logger('data.database')
class Database:
    
    def __init__(self, db_path=None):
        if db_path is None:
            db_path = BaseConfig.DATABASE_URL.replace('sqlite:///', '')
        
        self.db_path = db_path
        self.conn = None
        self.cursor = None
    def connect(self):
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.cursor = self.conn.cursor()
            logging.info(f"✅ Connected to database: {self.db_path}")
            return True
        except sqlite3.Error as e:
            logging.error(f"❌ Error connecting to database: {e}")
            self.conn = None
            self.cursor = None
            return False
    def ensure_connected(self):
        if self.conn is None or self.cursor is None:
            logging.error("❌ Database is not connected. Call connect() first.")
            raise
    def check_if_the_table_exist(self, nameoftable):
            self.ensure_connected()
            self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?;",
                                (nameoftable,))
            result = self.cursor.fetchone()
            if result: logging.info(f"✅ Table {nameoftable} exists")
            else: logging.error(f"❌ Table {nameoftable} does NOT exist")
    def create_tables(self):
        self.ensure_connected()
        sql_stock_prices="""
        CREATE TABLE IF NOT EXISTS stock_prices(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            UNIQUE(ticker, date)
        );
        """
        sql_fundamental = """
        CREATE TABLE IF NOT EXISTS fundamentals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            revenue REAL NOT NULL,
            net_income REAL NOT NULL,
            eps REAL NOT NULL,
            pe_ratio REAL NOT NULL,
            UNIQUE(ticker, date)
        );
        """
        sql_news = """
        CREATE TABLE IF NOT EXISTS news(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            headline TEXT NOT NULL,
            summary TEXT NOT NULL,
            date TEXT NOT NULL,
            sentiment REAL NOT NULL,
            UNIQUE(ticker, date)
        );  
        """
        self.cursor.execute(sql_stock_prices)
        self.cursor.execute(sql_fundamental)
        self.cursor.execute(sql_news)
        self.conn.commit()
        logging.info("✅ Tables created")

    def drop_table(self, table_name):
        self.ensure_connected()
        self.cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?;",
        (table_name,))
        if self.cursor.fetchone() is None:
            logging.error(f"❌ Table '{table_name}' does not exist.")
            return
        sql = f"DROP TABLE {table_name};"
        try:
            self.cursor.execute(sql)
            self.conn.commit()
            logging.info(f"✅ Table '{table_name}' has been deleted.")
        except sqlite3.Error as e:
            logging.error(f"❌ Failed to delete table '{table_name}': {e}")

    def delete_data_from_table(self, nameoftable, ticker):
        self.ensure_connected()
        sql = f"DELETE FROM {nameoftable} WHERE ticker = ?"
        try:
            self.cursor.execute(sql, (ticker,))
            self.conn.commit()
            logging.info(f"✅ Deleted all rows for ticker {ticker} from {nameoftable}")
        except sqlite3.Error as e:
            logging.error(f"❌ Failed to delete data from {nameoftable}: {e}")

    def insert_stock_prices(self, ticker, date, open, high, low, close, volume):
        self.ensure_connected()
        self.check_if_the_table_exist("stock_prices")
        sql = """
        INSERT OR IGNORE INTO stock_prices(ticker, date, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        try:
            self.cursor.execute(sql, (ticker, date, open, high, low, close, volume))
            self.conn.commit()
            logging.info(f"✅ Stock price for {ticker} on {date} inserted")
        except sqlite3.Error as e:
            logging.error(f"❌ Failed to insert stock for {ticker} on {date}: {e}")
            
    def get_stock_prices(self, ticker, start_date=None, end_date=None):
        self.ensure_connected()
        sql = "SELECT * FROM stock_prices WHERE ticker = ?"
        params = [ticker]
        if start_date is not None:
            sql += " AND date >= ?"
            params.append(start_date)
        if end_date is not None:
            sql += " AND date <= ?"
            params.append(end_date)
        sql += " ORDER BY date ASC"
        self.cursor.execute(sql, params)
        rows = self.cursor.fetchall()
        return rows

    def insert_fundamental(self, ticker, date, revenue, net_income, eps, pe_ratio):
        self.ensure_connected()
        self.check_if_the_table_exist("fundamentals")
        sql = """
        INSERT OR IGNORE INTO fundamentals(ticker, date, revenue, net_income, eps, pe_ratio)
        VALUES (?, ?, ?, ?, ?, ?)
        """
        try:
            self.cursor.execute(sql, (ticker, date, revenue, net_income, eps, pe_ratio))
            self.conn.commit()
            logging.info(f"✅ fundamental param for {ticker} on {date} inserted")
        except sqlite3.Error as e:
            logging.error(f"❌ Failed to insert fundamental param for {ticker} on {date}: {e}")

    def get_fundamentals(self, ticker):
        self.ensure_connected()
        sql = "SELECT * FROM fundamentals WHERE ticker = ?"
        params = [ticker]
        self.cursor.execute(sql, params)
        rows = self.cursor.fetchall()
        return rows

    def insert_news(self, ticker, headline, summary, date, sentiment):
        self.ensure_connected()
        self.check_if_the_table_exist("news")
        sql = """
        INSERT OR IGNORE INTO news(ticker, headline, summary, date, sentiment)
        VALUES (?, ?, ?, ?, ?)
        """
        try:
            self.cursor.execute(sql, (ticker, headline, summary, date, sentiment))
            self.conn.commit()
            logging.info(f"✅ news param for {ticker} on {date} inserted")
        except sqlite3.Error as e:
            logging.error(f"❌ Failed to insert news param for {ticker} on {date}: {e}")

    def get_news(self, ticker, days=7):
        self.ensure_connected()
        start_date = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
        sql = """
        SELECT * FROM news
        WHERE ticker = ? AND date >= ?
        ORDER BY date DESC
        """
        self.cursor.execute(sql, (ticker, start_date))
        rows = self.cursor.fetchall()
        return rows

    def close(self):
        if self.cursor:
            self.cursor.close()
            self.cursor = None
        if self.conn:
            self.conn.close()
            self.conn = None
        logging.info("✅ Database connection closed.")

db = Database()

if __name__== "__main__":
    db.connect()
    try:
      # Test 1: Create tables
      logging.info("[TEST 1] Creating tables...")
      db.create_tables()
    
      # Test 2: Verify tables exist
      logging.info("[TEST 2] Checking if tables exist...")
      db.check_if_the_table_exist("stock_prices")
      db.check_if_the_table_exist("fundamentals")
      db.check_if_the_table_exist("news")
    
      # Test 3: Insert stock prices
      logging.info("[TEST 3] Inserting stock price data...")
      db.insert_stock_prices("AAPL", "2026-02-01", 150.0, 155.0, 148.0, 154.0, 1000000)
      db.insert_stock_prices("AAPL", "2026-02-02", 154.0, 158.0, 153.0, 157.0, 1200000)
      db.insert_stock_prices("GOOGL", "2026-02-01", 2800.0, 2850.0, 2790.0, 2840.0, 500000)
             
      # Test 4: Insert duplicate (should be ignored)
      logging.info("[TEST 4] Inserting duplicate (should be ignored)...")
      db.insert_stock_prices("AAPL", "2026-02-01", 999.0, 999.0, 999.0, 999.0, 999999)
      
      # Test 5: Retrieve stock prices
      logging.info("[TEST 5] Retrieving stock prices for AAPL...")
      rows = db.get_stock_prices("AAPL")
      logging.info(f"Found {len(rows)} records for AAPL:")
      for row in rows:
          print(f"  {row}")

      # Test 6: Retrieve with date range
      logging.info("[TEST 6] Retrieving AAPL prices for specific date range...")
      rows = db.get_stock_prices("AAPL", start_date="2026-02-01")
      logging.info(f"Found {len(rows)} records from 2026-02-02 onwards:")
      for row in rows:
          print(f"  {row}")

      # Test 7: Insert fundamentals
      logging.info("[TEST 7] Inserting fundamental data...")
      db.insert_fundamental("AAPL", "2026-Q1", 95000000000, 25000000000, 1.52, 28.5)
      db.insert_fundamental("GOOGL", "2026-Q1", 85000000000, 20000000000, 1.35, 25.0)
      
      # Test 8: Retrieve fundamentals
      logging.info("[TEST 8] Retrieving fundamentals for AAPL...")
      rows = db.get_fundamentals("AAPL")
      logging.info(f"Found {len(rows)} fundamental records:")
      for row in rows:
          print(f"  {row}")

      # Test 9: Insert news
      logging.info("[TEST 9] Inserting news data...")
      db.insert_news("AAPL", 
                    "Apple Announces New Product", 
                    "Apple unveiled its latest innovation...", 
                    "2026-02-08", 
                    0.85)
      db.insert_news("AAPL", 
                    "Apple Stock Reaches All-Time High", 
                    "Shares hit record levels...", 
                    "2026-02-07", 
                    0.92)
      
      # Test 10: Retrieve news
      logging.info("[TEST 10] Retrieving news for AAPL (last 7 days)...")
      rows = db.get_news("AAPL", days=7)
      logging.info(f"Found {len(rows)} news articles:")
      for row in rows:
          logging.debug(f"  {row}")
    
    # Test 11: Delete data
    #  print("\n[TEST 11] Deleting GOOGL stock prices...")
    #  db.delete_data_from_table("stock_prices", "GOOGL")
    #  rows = db.get_stock_prices("GOOGL")
    #  print(f"GOOGL records remaining: {len(rows)} (should be 0)")
    #  
    #  # Test 12: Drop and recreate table
    #  print("\n[TEST 12] Dropping news table...")
    #  db.drop_table("news")
    #  print("Recreating tables...")
    #  db.create_tables()
    #  
    #  print("\n" + "=" * 60)
    #  print("✅ ALL TESTS COMPLETED SUCCESSFULLY!")
    #  print("=" * 60)

    except Exception as e:
      logging.error(f"❌ TEST FAILED: {e}")
      import traceback
      traceback.print_exc()    
    db.close()