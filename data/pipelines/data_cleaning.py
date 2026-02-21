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
logger = get_logger('data.data_cleaning')


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
        """
        self.db = db
        self.stats = {
            'records_processed': 0,
            'duplicates_removed': 0,
            'missing_values_filled': 0,
            'outliers_detected': 0,
            'invalid_rows_removed': 0,
            'ohlc_violations_fixed': 0,
        }
        logger.info("✅ DataCleaner initialized.")

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
        """
        label = ticker or "Unknown"
        logger.info(f"🧹 Starting clean_stock_prices for [{label}] — {len(df)} rows")

        self.stats['records_processed'] += len(df)

        # Step 1: Remove exact duplicates
        df, n = self._remove_exact_duplicates(df)
        self.stats['duplicates_removed'] += n

        # Step 2: Remove duplicate dates (keep latest)
        df, n = self._remove_duplicate_dates(df)
        self.stats['duplicates_removed'] += n

        # Step 3: Sort by date
        if 'date' in df.columns:
            df = df.sort_values('date').reset_index(drop=True)
        elif 'Date' in df.columns:
            df = df.sort_values('Date').reset_index(drop=True)

        # Step 4: Remove fully empty rows
        before = len(df)
        df = df.dropna(how='all').reset_index(drop=True)
        removed = before - len(df)
        if removed > 0:
            logger.info(f"  🗑️ Removed {removed} fully empty rows")

        # Step 5: Remove zero/negative prices
        df, n = self._fix_invalid_prices(df)
        self.stats['invalid_rows_removed'] += n

        # Step 6: Fix OHLC logic violations
        df, n = self._fix_ohlc_violations(df)
        self.stats['ohlc_violations_fixed'] += n

        # Step 7: Fill missing values
        df, n = self._fill_missing_values(df)
        self.stats['missing_values_filled'] += n

        # Step 8: Detect price outliers
        n = self._detect_price_outliers(df, ticker=ticker)
        self.stats['outliers_detected'] += n

        # Step 9: Validate volume data
        df = self._validate_volumes(df)

        logger.info(f"✅ Cleaned [{label}]: {len(df)} rows remain.")
        return df

    def _remove_exact_duplicates(self, df):
        """
        Remove rows that are exact duplicates.

        Returns
        -------
        tuple : (cleaned_df, duplicates_removed_count)
        """
        before = len(df)
        df = df.drop_duplicates().reset_index(drop=True)
        removed = before - len(df)
        if removed > 0:
            logger.info(f"  🗑️ Removed {removed} exact duplicate rows")
        return df, removed

    def _remove_duplicate_dates(self, df):
        """
        Remove duplicate dates while keeping the latest record.

        Returns
        -------
        tuple : (cleaned_df, duplicates_removed_count)
        """
        date_col = 'date' if 'date' in df.columns else 'Date'
        before = len(df)
        # keep='last' keeps the latest inserted/encountered record
        df = df.drop_duplicates(subset=[date_col], keep='last').reset_index(drop=True)
        removed = before - len(df)
        if removed > 0:
            logger.info(f"  🗑️ Removed {removed} duplicate-date rows (kept latest)")
        return df, removed

    def _fix_invalid_prices(self, df):
        """
        Remove rows with zero or negative prices.

        Validation Rules
        ----------------
        - Open > 0
        - High > 0
        - Low > 0
        - Close > 0

        Returns
        -------
        tuple : (cleaned_df, invalid_rows_removed)
        """
        price_cols = [c for c in ['open', 'high', 'low', 'close',
                                   'Open', 'High', 'Low', 'Close'] if c in df.columns]
        before = len(df)
        if price_cols:
            # Keep rows where ALL price columns are > 0
            mask = (df[price_cols] > 0).all(axis=1)
            df = df[mask].reset_index(drop=True)
        removed = before - len(df)
        if removed > 0:
            logger.warning(f"  ⚠️ Removed {removed} rows with zero/negative prices")
        return df, removed

    def _fix_ohlc_violations(self, df):
        """
        Fix OHLC logical violations.

        OHLC Rules
        ----------
        - High ≥ Open, Close
        - Low  ≤ Open, Close
        - High ≥ Low

        Strategy: clip High/Low to be consistent rather than drop rows.

        Returns
        -------
        tuple : (cleaned_df, violations_fixed_count)
        """
        # Normalize column names to lowercase for processing
        col_map = {c.lower(): c for c in df.columns}
        open_c  = col_map.get('open')
        high_c  = col_map.get('high')
        low_c   = col_map.get('low')
        close_c = col_map.get('close')

        if not all([open_c, high_c, low_c, close_c]):
            logger.warning("  ⚠️ OHLC columns not found — skipping OHLC validation")
            return df, 0

        violations = 0

        # High must be >= max(Open, Close)
        expected_high = df[[open_c, close_c]].max(axis=1)
        bad_high = df[high_c] < expected_high
        if bad_high.any():
            violations += bad_high.sum()
            df.loc[bad_high, high_c] = expected_high[bad_high]
            logger.warning(f"  🔧 Fixed {bad_high.sum()} High < max(Open,Close) violations")

        # Low must be <= min(Open, Close)
        expected_low = df[[open_c, close_c]].min(axis=1)
        bad_low = df[low_c] > expected_low
        if bad_low.any():
            violations += bad_low.sum()
            df.loc[bad_low, low_c] = expected_low[bad_low]
            logger.warning(f"  🔧 Fixed {bad_low.sum()} Low > min(Open,Close) violations")

        # High must be >= Low
        bad_hl = df[high_c] < df[low_c]
        if bad_hl.any():
            violations += bad_hl.sum()
            # Swap them
            df.loc[bad_hl, [high_c, low_c]] = df.loc[bad_hl, [low_c, high_c]].values
            logger.warning(f"  🔧 Fixed {bad_hl.sum()} High < Low violations (swapped)")

        return df, violations

    def _fill_missing_values(self, df):
        """
        Fill missing values intelligently.

        Strategy
        --------
        - Prices → Forward fill (then backward fill if leading NaNs exist)
        - Volume → Fill with 0

        Returns
        -------
        tuple : (cleaned_df, filled_values_count)
        """
        before_nulls = df.isnull().sum().sum()

        price_cols = [c for c in ['open', 'high', 'low', 'close',
                                   'Open', 'High', 'Low', 'Close'] if c in df.columns]
        vol_cols   = [c for c in ['volume', 'Volume'] if c in df.columns]

        if price_cols:
            df[price_cols] = df[price_cols].ffill().bfill()

        if vol_cols:
            df[vol_cols] = df[vol_cols].fillna(0)

        after_nulls = df.isnull().sum().sum()
        filled = int(before_nulls - after_nulls)
        if filled > 0:
            logger.info(f"  🩹 Filled {filled} missing values")
        return df, filled

    def _detect_price_outliers(self, df, ticker=None):
        """
        Detect extreme price outliers using IQR on daily returns.
        Logs anomalies but does NOT remove them.

        Returns
        -------
        int : Number of outliers detected
        """
        close_col = 'close' if 'close' in df.columns else ('Close' if 'Close' in df.columns else None)
        if close_col is None or len(df) < 5:
            return 0

        returns = df[close_col].pct_change().dropna()
        Q1, Q3 = returns.quantile(0.25), returns.quantile(0.75)
        IQR = Q3 - Q1
        lower, upper = Q1 - 3 * IQR, Q3 + 3 * IQR

        outlier_mask = (returns < lower) | (returns > upper)
        count = int(outlier_mask.sum())

        if count > 0:
            label = ticker or "Unknown"
            outlier_dates = df.loc[returns[outlier_mask].index, 'date' if 'date' in df.columns else 'Date'].tolist()
            logger.warning(f"  🔍 [{label}] Detected {count} price outliers on: {outlier_dates}")

        return count

    def _validate_volumes(self, df):
        """
        Validate and clean volume data.

        Validation Steps
        ----------------
        - Ensure non-negative volume
        - Replace negatives with 0
        - Convert to integers

        Returns
        -------
        pd.DataFrame
        """
        vol_col = 'volume' if 'volume' in df.columns else ('Volume' if 'Volume' in df.columns else None)
        if vol_col is None:
            return df

        neg_count = (df[vol_col] < 0).sum()
        if neg_count > 0:
            logger.warning(f"  ⚠️ Replaced {neg_count} negative volume values with 0")
            df[vol_col] = df[vol_col].clip(lower=0)

        df[vol_col] = df[vol_col].fillna(0).astype(int)
        return df

    # =========================================================================
    # DATABASE CLEANING
    # =========================================================================

    def clean_database_stock_prices(self, ticker=None):
        """
        Clean stock prices directly in the database.

        Parameters
        ----------
        ticker : str, optional
            Clean only one ticker. If None → cleans all tickers.

        Returns
        -------
        dict : Cleaning statistics
        """
        if self.db is None:
            logger.error("❌ No database connection provided.")
            return {}

        self.reset_stats()

        # Step 1: Fetch raw data
        raw_rows = self.db.get_all_stock_prices(ticker=ticker)
        if not raw_rows:
            logger.warning("⚠️ No stock price data found in database.")
            return self.get_cleaning_summary()

        # Step 2: Convert to DataFrame
        df = pd.DataFrame(raw_rows)

        # Step 3: Apply cleaning pipeline per ticker
        tickers = df['ticker'].unique() if ticker is None else [ticker]
        cleaned_frames = []

        for t in tickers:
            t_df = df[df['ticker'] == t].copy()
            cleaned = self.clean_stock_prices(t_df, ticker=t)
            cleaned_frames.append(cleaned)

        if not cleaned_frames:
            logger.warning("⚠️ No data after cleaning.")
            return self.get_cleaning_summary()

        full_cleaned_df = pd.concat(cleaned_frames, ignore_index=True)

        # Step 4 & 5: Replace old records with cleaned ones (atomic operation)
        self.db.replace_stock_prices(ticker, full_cleaned_df)

        logger.info(f"✅ Database stock prices cleaned. Summary: {self.get_cleaning_summary()}")
        return self.get_cleaning_summary()

    def remove_duplicate_news(self):
        """
        Remove duplicate news articles from database.

        Duplicate Definition: Same Ticker + Headline + Date

        Returns
        -------
        int : Number of duplicates removed
        """
        if self.db is None:
            logger.error("❌ No database connection provided.")
            return 0

        count = self.db.delete_duplicate_news_records()
        logger.info(f"✅ Removed {count} duplicate news records.")
        return count

    def remove_old_data(self, days_to_keep=730):
        """
        Remove outdated records.

        Parameters
        ----------
        days_to_keep : int
            Number of days of stock data to retain.

        Returns
        -------
        dict : Records removed per table
        """
        if self.db is None:
            logger.error("❌ No database connection provided.")
            return {}

        cutoff_stock = (datetime.today() - timedelta(days=days_to_keep)).strftime("%Y-%m-%d")
        cutoff_news  = (datetime.today() - timedelta(days=30)).strftime("%Y-%m-%d")  # news: 30 days

        removed = {}

        removed['stock_prices'] = self.db.delete_older_than('stock_prices', cutoff_stock)
        removed['news']         = self.db.delete_older_than('news', cutoff_news)

        logger.info(f"✅ Old data removed: {removed}")
        return removed

    def vacuum_database(self):
        """
        Optimize database storage by running VACUUM.

        Returns
        -------
        bool : Success status
        """
        if self.db is None:
            logger.error("❌ No database connection provided.")
            return False

        try:
            self.db.vacuum_database()
            logger.info("✅ Database vacuumed successfully.")
            return True
        except Exception as e:
            logger.error(f"❌ Vacuum failed: {e}")
            return False

    # =========================================================================
    # DATA VALIDATION
    # =========================================================================

    def validate_stock_data(self, df, ticker=None):
        """
        Validate stock data quality and return a detailed report.

        Parameters
        ----------
        df : pd.DataFrame
        ticker : str, optional

        Returns
        -------
        dict : Validation report
        """
        label = ticker or "Unknown"
        report = {
            'ticker': label,
            'total_rows': len(df),
            'missing_trading_days': 0,
            'large_price_gaps': [],
            'volume_anomalies': 0,
            'null_counts': {},
            'data_quality_score': 100.0,
            'issues': []
        }

        date_col  = 'date'  if 'date'  in df.columns else ('Date'  if 'Date'  in df.columns else None)
        close_col = 'close' if 'close' in df.columns else ('Close' if 'Close' in df.columns else None)
        vol_col   = 'volume' if 'volume' in df.columns else ('Volume' if 'Volume' in df.columns else None)

        # --- Null counts ---
        report['null_counts'] = df.isnull().sum().to_dict()
        total_nulls = sum(report['null_counts'].values())
        if total_nulls > 0:
            report['issues'].append(f"{total_nulls} missing values detected")
            report['data_quality_score'] -= min(20, total_nulls * 0.5)

        # --- Missing trading days ---
        if date_col:
            df[date_col] = pd.to_datetime(df[date_col])
            date_range = pd.bdate_range(df[date_col].min(), df[date_col].max())  # business days only
            missing_days = set(date_range.date) - set(df[date_col].dt.date)
            report['missing_trading_days'] = len(missing_days)
            if missing_days:
                report['issues'].append(f"{len(missing_days)} missing trading days")
                report['data_quality_score'] -= min(20, len(missing_days) * 0.2)

        # --- Large price gaps (>10% daily move) ---
        if close_col and len(df) > 1:
            returns = df[close_col].pct_change().abs()
            large_gaps = returns[returns > 0.10]
            if date_col:
                gap_dates = df.loc[large_gaps.index, date_col].dt.strftime('%Y-%m-%d').tolist()
            else:
                gap_dates = large_gaps.index.tolist()
            report['large_price_gaps'] = gap_dates
            if gap_dates:
                report['issues'].append(f"{len(gap_dates)} large price gaps (>10%)")
                report['data_quality_score'] -= min(10, len(gap_dates) * 1)

        # --- Volume anomalies (zero or extreme) ---
        if vol_col:
            zero_vol = (df[vol_col] == 0).sum()
            if zero_vol > 0:
                report['volume_anomalies'] += int(zero_vol)
                report['issues'].append(f"{zero_vol} zero-volume days")
                report['data_quality_score'] -= min(10, zero_vol * 0.5)

            # Extreme volume: more than 5x the rolling mean
            rolling_mean = df[vol_col].rolling(window=20, min_periods=1).mean()
            extreme_vol = (df[vol_col] > 5 * rolling_mean).sum()
            if extreme_vol > 0:
                report['volume_anomalies'] += int(extreme_vol)
                report['issues'].append(f"{extreme_vol} extreme-volume days (>5x rolling avg)")

        report['data_quality_score'] = round(max(0.0, report['data_quality_score']), 2)

        logger.info(f"📊 Validation for [{label}]: score={report['data_quality_score']}%, issues={report['issues']}")
        return report

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def get_cleaning_summary(self):
        """
        Retrieve summary of cleaning operations.

        Returns
        -------
        dict : Aggregated cleaning statistics
        """
        return {
            'records_processed':    self.stats['records_processed'],
            'duplicates_removed':   self.stats['duplicates_removed'],
            'missing_values_filled': self.stats['missing_values_filled'],
            'outliers_detected':    self.stats['outliers_detected'],
            'invalid_rows_removed': self.stats['invalid_rows_removed'],
            'ohlc_violations_fixed': self.stats['ohlc_violations_fixed'],
        }

    def reset_stats(self):
        """
        Reset all cleaning statistics for a fresh run.
        """
        self.stats = {
            'records_processed': 0,
            'duplicates_removed': 0,
            'missing_values_filled': 0,
            'outliers_detected': 0,
            'invalid_rows_removed': 0,
            'ohlc_violations_fixed': 0,
        }
        logger.info("🔄 Cleaning stats reset.")
if __name__ == "__main__":
    from data.database import db

    # 1. Connect and set up DB
    db.connect()
    db.create_tables()

    # 2. Insert some dirty test data
    db.insert_stock_prices("AAPL", "2026-01-01", 150, 155, 148, 154, 1000000)
    db.insert_stock_prices("AAPL", "2026-01-01", 150, 155, 148, 154, 1000000)  # exact duplicate
    db.insert_stock_prices("AAPL", "2026-01-02", -1,  155, 148, 154, 1000000)  # negative price
    db.insert_stock_prices("AAPL", "2026-01-03", 154, 140, 160, 157, -500)     # OHLC violation + neg volume
    db.insert_stock_prices("AAPL", "2026-01-04", 157, 160, 155, 158, 1200000)

    # 3. Run the cleaner
    cleaner = DataCleaner(db=db)
    cleaner.clean_database_stock_prices(ticker="AAPL")

    # 4. Check results
    rows = db.get_stock_prices("AAPL")
    print(f"\n✅ Rows after cleaning: {len(rows)}")
    for r in rows:
        print(r)

    # 5. Print summary
    print("\n📊 Summary:", cleaner.get_cleaning_summary())

    db.close()