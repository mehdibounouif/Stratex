import pandas as pd
import yfinance as yf
from datetime import datatime, timedelta
import os
from config import BaseConfig, DataConfig


class DataEngineer:
    def __init__(self):
        self.config = DataConfig()
        print("Using text DataEngineer (Abdo placeholder)")

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


















