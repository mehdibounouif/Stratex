
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
from datetime import datetime
from config import BaseConfig
import pandas as pd

class Database:
    
    def __init__(self, db_path=None):
        if db_path is None:
            db_path = BaseConfig.DATABASE_URL.replace('sqlite:///', '')
        
        self.db_path = db_path
        self.conn = None

    def connect(self):
        """
        Establish a connection to the database.

        Responsibility:
        - Open a connection to the database file
        - Create and store a connection object (e.g. self.conn)
        - Create a cursor for executing SQL queries

        Called when:
        - The application needs to read/write data
        """
        pass


    def create_tables(self):
        """
        Create all required database tables if they do not exist.

        Responsibility:
        - Create tables such as:
            - stock_prices
            - fundamentals
            - news
        - Ensure schema exists before inserting data

        Called:
        - Once at application startup
        """
        pass


    def insert_stock_price(self, ticker, date, open, high, low, close, volume):
        """
        Insert historical price data for a stock.

        Parameters:
        - ticker (str): Stock symbol (e.g. 'AAPL')
        - date (str): Trading date (YYYY-MM-DD)
        - open (float): Opening price
        - high (float): Highest price of the day
        - low (float): Lowest price of the day
        - close (float): Closing price
        - volume (int): Number of shares traded

        Responsibility:
        - Store OHLCV market data into the database
        """
        pass


    def get_stock_prices(self, ticker, start_date=None, end_date=None):
        """
        Retrieve historical stock prices.

        Parameters:
        - ticker (str): Stock symbol
        - start_date (str | None):
            Optional start date filter (YYYY-MM-DD)
        - end_date (str | None):
            Optional end date filter (YYYY-MM-DD)

        Responsibility:
        - Query stock prices for a ticker
        - Optionally filter by date range

        Returns:
        - List of price records (rows)
        """
        pass


    def insert_fundamental(self, ticker, date, revenue, net_income, eps, pe_ratio):
        """
        Insert fundamental financial data for a company.

        Parameters:
        - ticker (str): Stock symbol
        - date (str): Financial report date
        - revenue (float): Total revenue
        - net_income (float): Net profit
        - eps (float): Earnings per share
        - pe_ratio (float): Price-to-earnings ratio

        Responsibility:
        - Store company financial fundamentals
        """
        pass


    def get_fundamentals(self, ticker):
        """
        Retrieve fundamental data for a stock.

        Parameters:
        - ticker (str): Stock symbol

        Responsibility:
        - Fetch all stored fundamental data for the company

        Returns:
        - List of fundamental records
        """
        pass


    def insert_news(self, ticker, headline, summary, date, sentiment):
        """
        Insert a news article related to a stock.

        Parameters:
        - ticker (str): Stock symbol
        - headline (str): News title
        - summary (str): Short article summary
        - date (str): Publication date
        - sentiment (float):
            Sentiment score (e.g. -1 bearish, +1 bullish)

        Responsibility:
        - Store news and sentiment analysis data
        """
        pass


    def get_news(self, ticker, days=7):
        """
        Retrieve recent news for a stock.

        Parameters:
        - ticker (str): Stock symbol
        - days (int):
            Number of past days to fetch news for

        Responsibility:
        - Fetch recent news articles related to the stock

        Returns:
        - List of news records
        """
        pass


    def close(self):
        """
        Close the database connection.

        Responsibility:
        - Safely close the database connection
        - Release system resources

        Called:
        - When the application shuts down
        """
        pass


db = Database()

if __name__ == "__main__":

    db.connect()
    db.create_tables()
    print("Database setup complete!")