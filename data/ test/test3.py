# import sqlite3
# from datetime import datetime, timedelta
# from config import BaseConfig
# import pandas as pd

# class Database:
    
#     def __init__(self, db_path=None):
#         if db_path is None:
#             db_path = BaseConfig.DATABASE_URL.replace('sqlite:///', '')
        
#         self.db_path = db_path
#         self.conn = None
#         self.cursor = None
#     def connect(self):
#         try:
#             self.conn = sqlite3.connect(self.db_path)
#             self.cursor = self.conn.cursor()
#             print(f"✅ Connected to database: {self.db_path}")
#             return True
#         except sqlite3.Error as e:
#             print(f"❌ Error connecting to database: {e}")
#             self.conn = None
#             self.cursor = None
#             return False
#     def ensure_connected(self):
#         if self.conn is None or self.cursor is None:
#             raise RuntimeError("❌ Database is not connected. Call connect() first.")
#     def check_if_the_table_exist(self, nameoftable):
#             self.ensure_connected()
#             self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?;",
#                                 (nameoftable,))
#             result = self.cursor.fetchone()
#             if result: print(f"✅ Table {nameoftable} exists")
#             else: print(f"❌ Table {nameoftable} does NOT exist")
#     def create_tables(self):
#         self.ensure_connected()
#         sql_stock_prices="""
#         CREATE TABLE IF NOT EXISTS stock_prices(
#             id INTEGER PRIMARY KEY AUTOINCREMENT,
#             ticker TEXT NOT NULL,
#             date TEXT NOT NULL,
#             open REAL NOT NULL,
#             high REAL NOT NULL,
#             low REAL NOT NULL,
#             close REAL NOT NULL,
#             volume REAL NOT NULL,
#             UNIQUE(ticker, date)
#         );
#         """
#         sql_fundamental = """
#         CREATE TABLE IF NOT EXISTS fundamentals(
#             id INTEGER PRIMARY KEY AUTOINCREMENT,
#             ticker TEXT NOT NULL,
#             date TEXT NOT NULL,
#             revenue REAL NOT NULL,
#             net_income REAL NOT NULL,
#             eps REAL NOT NULL,
#             pe_ratio REAL NOT NULL,
#             UNIQUE(ticker, date)
#         );
#         """
#         sql_news = """
#         CREATE TABLE IF NOT EXISTS news(
#             id INTEGER PRIMARY KEY AUTOINCREMENT,
#             ticker TEXT NOT NULL,
#             headline TEXT NOT NULL,
#             summary TEXT NOT NULL,
#             date TEXT NOT NULL,
#             sentiment REAL NOT NULL,
#             UNIQUE(ticker, date)
#         );  
#         """
#         self.cursor.execute(sql_stock_prices)
#         self.cursor.execute(sql_fundamental)
#         self.cursor.execute(sql_news)
#         self.conn.commit()
#         print("✅ Tables created")
#     def drop_table(self, table_name):
#         self.ensure_connected()
#         self.cursor.execute(
#         "SELECT name FROM sqlite_master WHERE type='table' AND name=?;",
#         (table_name,))
#         if self.cursor.fetchone() is None:
#             print(f"❌ Table '{table_name}' does not exist.")
#             return
#         sql = f"DROP TABLE {table_name};"
#         try:
#             self.cursor.execute(sql)
#             self.conn.commit()
#             print(f"✅ Table '{table_name}' has been deleted.")
#         except sqlite3.Error as e:
#             print(f"❌ Failed to delete table '{table_name}': {e}")
#     def insert_stock_prices(self, ticker, date, open, high, low, close, volume):
#         self.ensure_connected()
#         self.check_if_the_table_exist("stock_prices")
#         sql = """
#         INSERT OR IGNORE INTO stock_prices(ticker, date, open, high, low, close, volume)
#         VALUES (?, ?, ?, ?, ?, ?, ?)
#         """
#         try:
#             self.cursor.execute(sql, (ticker, date, open, high, low, close, volume))
#             self.conn.commit()
#             print(f"✅ Stock price for {ticker} on {date} inserted")
#         except sqlite3.Error as e:
#             print(f"❌ Failed to insert stock for {ticker} on {date}: {e}")
#     def get_stock_prices(self, ticker, start_date=None, end_date=None):
#         self.ensure_connected()
#         sql = "SELECT * FROM stock_prices WHERE ticker = ?"
#         params = [ticker]
#         if start_date is not None:
#             sql += " AND date >= ?"
#             params.append(start_date)
#         if end_date is not None:
#             sql += " AND date <= ?"
#             params.append(end_date)
#         sql += " ORDER BY date ASC"
#         self.cursor.execute(sql, params)
#         rows = self.cursor.fetchall()
#         return rows
#     def insert_fundamental(self, ticker, date, revenue, net_income, eps, pe_ratio):
#         self.ensure_connected()
#         self.check_if_the_table_exist("fundamental")
#         sql = """
#         INSERT OR IGNORE INTO fundamentals(ticker, date, revenue, net_income, eps, pe_ratio)
#         VALUES (?, ?, ?, ?, ?, ?)
#         """
#         try:
#             self.cursor.execute(sql, (ticker, date, revenue, net_income, eps, pe_ratio))
#             self.conn.commit()
#             print(f"✅ fundamental param for {ticker} on {date} inserted")
#         except sqlite3.Error as e:
#             print(f"❌ Failed to insert fundamental param for {ticker} on {date}: {e}")
#     def get_fundamentals(self, ticker):
#         self.ensure_connected()
#         sql = "SELECT * FROM fundamentals WHERE ticker = ?"
#         params = [ticker]
#         self.cursor.execute(sql, params)
#         rows = self.cursor.fetchall()
#         return rows
#     def insert_news(self, ticker, headline, summary, date, sentiment):
#         self.ensure_connected()
#         self.check_if_the_table_exist("news")
#         sql = """
#         INSERT OR IGNORE INTO news(ticker, headline, summary, date, sentiment)
#         VALUES (?, ?, ?, ?, ?)
#         """
#         try:
#             self.cursor.execute(sql, (ticker, headline, summary, date, sentiment))
#             self.conn.commit()
#             print(f"✅ news param for {ticker} on {date} inserted")
#         except sqlite3.Error as e:
#             print(f"❌ Failed to insert news param for {ticker} on {date}: {e}")
#     def get_news(self, ticker, days=7):
#         self.ensure_connected()
#         start_date = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
#         sql = """
#         SELECT * FROM news
#         WHERE ticker = ? AND date >= ?
#         ORDER BY date DESC
#         """
#         self.cursor.execute(sql, (ticker, start_date))
#         rows = self.cursor.fetchall()
#         return rows
#     def close(self):
#         if self.cursor:
#             self.cursor.close()
#             self.cursor = None
#         if self.conn:
#             self.conn.close()
#             self.conn = None
#         print("✅ Database connection closed.")
# db = Database()
# if __name__== "__main__":
#     db.connect()
#     db.close()

# class Database:
    
#     def __init__(self, db_path=None):
#         if db_path is None:
#             db_path = BaseConfig.DATABASE_URL.replace('sqlite:///', '')
        
#         self.db_path = db_path
#         self.conn = None

#     def connect(self):
#         """
#         Establish a connection to the database.

#         Responsibility:
#         - Open a connection to the database file
#         - Create and store a connection object (e.g. self.conn)
#         - Create a cursor for executing SQL queries

#         Called when:
#         - The application needs to read/write data
#         """
#         pass


#     def create_tables(self):
#         """
#         Create all required database tables if they do not exist.

#         Responsibility:
#         - Create tables such as:
#             - stock_prices
#             - fundamentals
#             - news
#         - Ensure schema exists before inserting data

#         Called:
#         - Once at application startup
#         """
#         pass


#     def insert_stock_price(self, ticker, date, open, high, low, close, volume):
#         """
#         Insert historical price data for a stock.

#         Parameters:
#         - ticker (str): Stock symbol (e.g. 'AAPL')
#         - date (str): Trading date (YYYY-MM-DD)
#         - open (float): Opening price
#         - high (float): Highest price of the day
#         - low (float): Lowest price of the day
#         - close (float): Closing price
#         - volume (int): Number of shares traded

#         Responsibility:
#         - Store OHLCV market data into the database
#         """
#         pass


#     def get_stock_prices(self, ticker, start_date=None, end_date=None):
#         """
#         Retrieve historical stock prices.

#         Parameters:
#         - ticker (str): Stock symbol
#         - start_date (str | None):
#             Optional start date filter (YYYY-MM-DD)
#         - end_date (str | None):
#             Optional end date filter (YYYY-MM-DD)

#         Responsibility:
#         - Query stock prices for a ticker
#         - Optionally filter by date range

#         Returns:
#         - List of price records (rows)
#         """
#         pass


#     def insert_fundamental(self, ticker, date, revenue, net_income, eps, pe_ratio):
#         """
#         Insert fundamental financial data for a company.

#         Parameters:
#         - ticker (str): Stock symbol
#         - date (str): Financial report date
#         - revenue (float): Total revenue
#         - net_income (float): Net profit
#         - eps (float): Earnings per share
#         - pe_ratio (float): Price-to-earnings ratio

#         Responsibility:
#         - Store company financial fundamentals
#         """
#         pass


#     def get_fundamentals(self, ticker):
#         """
#         Retrieve fundamental data for a stock.

#         Parameters:
#         - ticker (str): Stock symbol

#         Responsibility:
#         - Fetch all stored fundamental data for the company

#         Returns:
#         - List of fundamental records
#         """
#         pass


#     def insert_news(self, ticker, headline, summary, date, sentiment):
#         """
#         Insert a news article related to a stock.

#         Parameters:
#         - ticker (str): Stock symbol
#         - headline (str): News title
#         - summary (str): Short article summary
#         - date (str): Publication date
#         - sentiment (float):
#             Sentiment score (e.g. -1 bearish, +1 bullish)

#         Responsibility:
#         - Store news and sentiment analysis data
#         """
#         pass


#     def get_news(self, ticker, days=7):
#         """
#         Retrieve recent news for a stock.

#         Parameters:
#         - ticker (str): Stock symbol
#         - days (int):
#             Number of past days to fetch news for

#         Responsibility:
#         - Fetch recent news articles related to the stock

#         Returns:
#         - List of news records
#         """
#         pass


#     def close(self):
#         """
#         Close the database connection.

#         Responsibility:
#         - Safely close the database connection
#         - Release system resources

#         Called:
#         - When the application shuts down
#         """
#         pass


# db = Database()

# if __name__ == "__main__":

#     db.connect()
#     db.create_tables()
#     print("Database setup complete!")



    
        
