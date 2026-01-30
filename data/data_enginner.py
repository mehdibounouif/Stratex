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

