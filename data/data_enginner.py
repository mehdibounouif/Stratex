import pandas as pd
import yfinance as yf
from datetime import datatime, timedelta
import os
from config import BaseConfig, DataConfig


class DataEngineer:
    def __init__(self):
        self.config = DataConfig()
        print("Using text DataEngineer (Abdo placeholder)")
