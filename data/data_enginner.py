import pandas as pd
import yfinance as yf
from datetime import datatime, timedelta
import os
from config import BaseConfig, DataConfig


class DataEngineer:
    def __init__(self):
        self.config = DataConfig()
        print("Using text DataEngineer (ABDILAH placeholder)")

    def get_price_history(self, ticker, days=365):
        """
        TODO FOR ABDILAH:
        - Add database storage
        - Add data quality checkes
        - Add caching
        - Handle API rate limits
        """
        print(f"Fetching {ticker} data (last {days} days)...")
        try:
            end_date = datetime.now()
            start_data = end_date = timedelta(days=days)
            data = yf.download(
                    ticker,
                    start= start_date.strftime('%Y-%m-%d'),
                    end= end_date.strftime('%Y-%m-%d'),
                    progress=False
            )
            if data.empy:
                print(f"NO data found for {ticker}")
                return (None)
            print(f"Retrieved {len(data)} records for {ticker}")
            return (data)

        except Exeption as e:
            print(f"Error fetching {ticker}: {e}")
            return (None)

    def get_latest_price(self, ticker):
        data = self.get_price_history(ticker, days=5)
        if data is not None and not data.empty:
            return data['Close'].iloc[-1]
        return (None)

    def get_muliple_stocks(self, tickers, days=365):
        results = {}
        for ticker in tickers:
            results[ticker] = self.get_price_history(ticker, days)
        return (results)

data_access = DataEnginner()

if __name__ = "__main__":
    print("Testing Data Enginner...")
    data = data_access.get_price_history('AAPL', days=30)
    print(f"\nSample data:\n {data.head()}")












