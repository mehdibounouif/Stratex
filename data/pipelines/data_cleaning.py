"""
Data Cleaning and Validation Module
==================================
Handles data quality issues: duplicates, missing values, outliers, anomalies.

Author: Abdilah (Data Engineer)
Compatible with: database.py, stock_fetcher.py

Features:
- Remove duplicate records
- Fill missing values intelligently
- Detect and handle outliers
- Validate data integrity
- Fix common data issues
"""


import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from logger import setup_logging, get_logger
from data.database import Database

setup_logging()
logger = get_logger('data.data_cleaner')


class DataCleaner:
    """
    Comprehensive data cleaning and validation for trading data.
    """

    def __init__(self, db=None):
        """
        Initialize the Data Cleaner.

        Parameters
        ----------
        db : Database, optional
            Database instance for cleaning data in-place.

        Responsibilities
        ----------------
        - Store database connection
        - Initialize cleaning statistics
        - Prepare logging
        """

    # =========================================================================
    # STOCK PRICE CLEANING
    # =========================================================================

    def clean_stock_prices(self, df, ticker=None):
        """
        Clean stock price DataFrame.

        Parameters
        ----------
        df : pd.DataFrame
            Stock price data with columns:
            Date, Open, High, Low, Close, Volume

        ticker : str, optional
            Stock symbol for logging purposes

        Returns
        -------
        pd.DataFrame
            Cleaned DataFrame

        Cleaning Steps
        --------------
        1. Remove exact duplicates
        2. Remove duplicate dates (keep latest)
        3. Sort by date
        4. Remove fully empty rows
        5. Remove zero/negative prices
        6. Fix OHLC logic violations
        7. Fill missing values
        8. Detect price outliers
        9. Validate volume data
        """

    def _remove_exact_duplicates(self, df):
        """
        Remove rows that are exact duplicates.

        Parameters
        ----------
        df : pd.DataFrame

        Returns
        -------
        tuple
            (cleaned_df, duplicates_removed_count)
        """

    def _remove_duplicate_dates(self, df):
        """
        Remove duplicate dates while keeping the latest record.

        Parameters
        ----------
        df : pd.DataFrame

        Returns
        -------
        tuple
            (cleaned_df, duplicates_removed_count)

        Notes
        -----
        - Requires 'Date' column
        """

    def _fix_invalid_prices(self, df):
        """
        Remove rows with zero or negative prices.

        Parameters
        ----------
        df : pd.DataFrame

        Returns
        -------
        tuple
            (cleaned_df, invalid_rows_removed)

        Validation Rules
        ----------------
        - Open > 0
        - High > 0
        - Low > 0
        - Close > 0
        """

    def _fix_ohlc_violations(self, df):
        """
        Fix OHLC logical violations.

        Parameters
        ----------
        df : pd.DataFrame

        Returns
        -------
        tuple
            (cleaned_df, violations_fixed_count)

        OHLC Rules
        ----------
        - High ≥ Open, Close
        - Low ≤ Open, Close
        - High ≥ Low
        """

    def _fill_missing_values(self, df):
        """
        Fill missing values intelligently.

        Parameters
        ----------
        df : pd.DataFrame

        Returns
        -------
        tuple
            (cleaned_df, filled_values_count)

        Strategy
        --------
        - Prices → Forward fill
        - Volume → Fill with 0
        """

    def _detect_price_outliers(self, df, ticker=None):
        """
        Detect extreme price outliers.

        Parameters
        ----------
        df : pd.DataFrame
        ticker : str, optional

        Returns
        -------
        int
            Number of outliers detected

        Method
        ------
        - Uses IQR on daily returns
        - Logs anomalies but does not remove them
        """

    def _validate_volumes(self, df):
        """
        Validate and clean volume data.

        Parameters
        ----------
        df : pd.DataFrame

        Returns
        -------
        pd.DataFrame

        Validation Steps
        ----------------
        - Ensure non-negative volume
        - Replace negatives with 0
        - Convert to integers
        """

    # =========================================================================
    # DATABASE CLEANING
    # =========================================================================

    def clean_database_stock_prices(self, ticker=None):
        """
        Clean stock prices directly in the database.

        Parameters
        ----------
        ticker : str, optional
            Clean only one ticker.
            If None → cleans all tickers.

        Returns
        -------
        dict
            Cleaning statistics

        Process
        -------
        1. Fetch raw data
        2. Convert to DataFrame
        3. Apply cleaning pipeline
        4. Delete old records
        5. Insert cleaned records
        """

    def remove_duplicate_news(self):
        """
        Remove duplicate news articles from database.

        Duplicate Definition
        --------------------
        Same:
        - Ticker
        - Headline
        - Date

        Returns
        -------
        int
            Number of duplicates removed
        """

    def remove_old_data(self, days_to_keep=730):
        """
        Remove outdated records.

        Parameters
        ----------
        days_to_keep : int
            Number of days of stock data to retain.

        Returns
        -------
        dict
            Records removed per table

        Retention Policy
        ----------------
        - Stock prices → configurable
        - News → typically shorter window
        """

    def vacuum_database(self):
        """
        Optimize database storage.

        Purpose
        -------
        - Reclaim unused disk space
        - Improve query performance

        Returns
        -------
        bool
            Success status
        """

    # =========================================================================
    # DATA VALIDATION
    # =========================================================================

    def validate_stock_data(self, df, ticker=None):
        """
        Validate stock data quality.

        Parameters
        ----------
        df : pd.DataFrame
        ticker : str, optional

        Returns
        -------
        dict
            Validation report

        Validation Checks
        -----------------
        - Missing trading days
        - Large price gaps
        - Volume anomalies
        - Data quality score
        """

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def get_cleaning_summary(self):
        """
        Retrieve summary of cleaning operations.

        Returns
        -------
        dict
            Aggregated cleaning statistics

        Metrics
        -------
        - Records processed
        - Duplicates removed
        - Missing values filled
        - Outliers fixed
        """

    def reset_stats(self):
        """
        Reset all cleaning statistics.

        Purpose
        -------
        Prepare cleaner for a fresh run.
        """
