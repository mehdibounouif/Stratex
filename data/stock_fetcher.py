"""
Stock Price Data Fetcher - FIXED VERSION
=========================================
Fetches historical and real-time stock price data from Yahoo Finance.
Integrates with Database class for persistent storage.

Author: Abdilah (Data Engineer)

FIXES:
- Robust column name handling for yfinance quirks
- Better error messages for debugging
- Handles both single and multi-ticker downloads
"""

import pandas as pd
import yfinance as yf
import time
from datetime import datetime, timedelta
from pathlib import Path
from data.pipelines.data_cleaning import DataCleaner
from data.retry import retry, fetch_with_retry
from logger import setup_logging, get_logger

setup_logging()
logger = get_logger('data.stock_fetcher')


class StockDataFetcher:
    """
    Fetches historical and real-time stock price data from Yahoo Finance.
    """
    
    def __init__(self, raw_data_path='data/raw/stocks', db=None):
        """Initialize the Stock Data Fetcher."""
        self.raw_data_path = Path(raw_data_path)
        self.raw_data_path.mkdir(parents=True, exist_ok=True)
        
        self.db = db
        self.max_retries = 3
        self.retry_delay = 2
        self.cleaner = DataCleaner()
        self.last_api_call = 0
        self.rate_limit_delay = 3  # 3 seconds between Yahoo Finance calls
        

        logger.info(f"✅ StockDataFetcher initialized")
        logger.info(f"   Raw data path: {self.raw_data_path}")
        logger.info(f"   Rate limit: {self.rate_limit_delay} seconds between calls")
        logger.info(f"   Database: {'Connected' if db else 'Not connected'}")
            
    @retry(max_attempts=3, base_delay=2.0, exceptions=(Exception,))
    def fetch_stock_prices(self, ticker, start_date, end_date):
        """
        Download historical stock price data for a single ticker.
        Retries up to 3 times with exponential backoff on any failure.

        Returns
        -------
        pd.DataFrame or None
        """
        self._enforce_rate_limit()
        logger.info(f"📊 Fetching stock prices for {ticker} ({start_date} to {end_date})")

        df = yf.download(ticker, start=start_date, end=end_date, progress=False)

        if df is None or df.empty:
            logger.warning(f"⚠️ No data returned for {ticker}")
            return None

        df = self._clean_dataframe(df, ticker)
        if df is None:
            logger.error(f"❌ Failed to clean DataFrame for {ticker}")
            return None

        df_clean = self.cleaner.clean_stock_prices(df, ticker)
        logger.info(f"✅ Downloaded {len(df_clean)} records for {ticker}")

        self._save_to_csv(ticker, df_clean, start_date, end_date)

        if self.db:
            self._save_to_database(ticker, df_clean)
        else:
            logger.warning("⚠️ Database not connected — skipping database save.")

        return df_clean

    def _enforce_rate_limit(self):
        """
        Internal method to enforce API rate limit (5 calls/minute).
        
        Behavior
        --------
        - Calculates time since last API call
        - Sleeps if necessary to maintain rate limit
        - Updates last call timestamp
        """
        current_time = time.time()
        time_since_last_call = current_time - self.last_api_call
        
        if time_since_last_call < self.rate_limit_delay:
            wait_time = self.rate_limit_delay - time_since_last_call
            logger.info(f"⏳ Rate limit: waiting {wait_time:.1f} seconds...")
            time.sleep(wait_time)
        
        self.last_api_call = time.time()

    def _clean_dataframe(self, df, ticker):
        """
        Clean DataFrame from yfinance to have standard column names.
        
        yfinance can return columns in various formats:
        - Simple: ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
        - MultiIndex: [('Open', 'AAPL'), ('High', 'AAPL'), ...]
        - Tuple strings: ["('Open', 'AAPL')", ...]
        
        This method handles all cases and returns a clean DataFrame.
        """
        try:
            # Make a copy
            df = df.copy()
            
            # Reset index to make Date a regular column
            df = df.reset_index()
            
            logger.info(f"   Raw columns: {list(df.columns)}")
            logger.info(f"   Column types: {[type(c).__name__ for c in df.columns]}")
            
            # Handle MultiIndex columns
            if isinstance(df.columns, pd.MultiIndex):
                logger.info("   Detected MultiIndex columns, flattening...")
                # For MultiIndex, take the first level (column type)
                df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
            
            # Handle tuple columns (sometimes yfinance returns these)
            new_columns = []
            for col in df.columns:
                if isinstance(col, tuple):
                    # Extract first element of tuple
                    clean_col = col[0]
                elif isinstance(col, str):
                    clean_col = col
                else:
                    clean_col = str(col)
                new_columns.append(clean_col)
            
            df.columns = new_columns
            logger.info(f"   Cleaned columns: {list(df.columns)}")
            
            # Standardize column names to our expected format
            column_map = {}
            for col in df.columns:
                col_upper = str(col).upper().strip()
                
                if col_upper in ['DATE', 'INDEX']:
                    column_map[col] = 'Date'
                elif 'OPEN' in col_upper:
                    column_map[col] = 'Open'
                elif 'HIGH' in col_upper:
                    column_map[col] = 'High'
                elif 'LOW' in col_upper:
                    column_map[col] = 'Low'
                elif 'CLOSE' in col_upper and 'ADJ' not in col_upper:
                    column_map[col] = 'Close'
                elif 'ADJ' in col_upper:
                    column_map[col] = 'Adj_Close'
                elif 'VOLUME' in col_upper:
                    column_map[col] = 'Volume'
            
            df = df.rename(columns=column_map)
            
            # Verify we have all required columns
            required = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
            missing = [col for col in required if col not in df.columns]
            
            if missing:
                logger.error(f"❌ Missing required columns: {missing}")
                logger.error(f"   Available columns: {list(df.columns)}")
                return None
            
            # Keep only required columns
            df = df[required]
            
            logger.info(f"   Final columns: {list(df.columns)}")
            
            return df
            
        except Exception as e:
            logger.error(f"❌ Error cleaning DataFrame: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    @retry(max_attempts=3, base_delay=2.0, exceptions=(Exception,))
    def fetch_latest_price(self, ticker):
        """
        Get the most recent trading price for a stock.
        Retries up to 3 times with exponential backoff.
        """
        self._enforce_rate_limit()
        logger.info(f"📈 Fetching latest price for {ticker}")

        stock = yf.Ticker(ticker)
        info  = stock.info

        price = (info.get('currentPrice')
                 or info.get('regularMarketPrice')
                 or info.get('previousClose'))

        if price is None:
            logger.warning(f"⚠️ Could not find price for {ticker}")
            return None

        result = {
            'ticker':     ticker,
            'price':      float(price),
            'timestamp':  datetime.now().isoformat(),
            'volume':     info.get('volume', 0),
            'market_cap': info.get('marketCap', 0),
            'currency':   info.get('currency', 'USD')
        }

        logger.info(f"✅ Latest price for {ticker}: ${result['price']:.2f}")
        return result
    
    def fetch_multiple_stocks(self, tickers, start_date, end_date, delay=1):
        """Download historical data for multiple stocks with rate limiting."""
        logger.info(f"📊 Fetching data for {len(tickers)} stocks")
        logger.info(f"   Tickers: {', '.join(tickers)}")
        logger.info(f"   Date range: {start_date} to {end_date}")
        
        results = {}
        successful = 0
        failed = 0
        
        for i, ticker in enumerate(tickers, 1):
            logger.info(f"\n[{i}/{len(tickers)}] Processing {ticker}...")
            
            df = self.fetch_stock_prices(ticker, start_date, end_date)
            results[ticker] = df
            
            if df is not None:
                successful += 1
            else:
                failed += 1
            
            if i < len(tickers):
                logger.info(f"⏳ Waiting {delay} seconds before next request...")
                time.sleep(delay)
        
        logger.info(f"\n{'='*60}")
        logger.info(f"FETCH SUMMARY:")
        logger.info(f"  Total tickers: {len(tickers)}")
        logger.info(f"  ✅ Successful: {successful}")
        logger.info(f"  ❌ Failed: {failed}")
        logger.info(f"{'='*60}\n")
        
        return results
    
    def get_cached_data(self, ticker, start_date, end_date):
        """Retrieve stock data from database cache."""
        if not self.db:
            logger.warning("⚠️ Database not connected. Cannot retrieve cached data.")
            return None
        
        try:
            rows = self.db.get_stock_prices(ticker, start_date, end_date)
            
            if not rows:
                logger.info(f"📭 No cached data for {ticker} ({start_date} to {end_date})")
                return None
            
            df = pd.DataFrame(rows, columns=['id', 'ticker', 'date', 'open', 'high', 'low', 'close', 'volume'])
            df = df.drop('id', axis=1)
            df['date'] = pd.to_datetime(df['date'])
            
            # Rename to match our standard format
            df = df.rename(columns={
                'date': 'Date',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume'
            })
            
            logger.info(f"✅ Retrieved {len(df)} cached records for {ticker}")
            return df
            
        except Exception as e:
            logger.error(f"❌ Error retrieving cached data for {ticker}: {e}")
            return None
    
    def fetch_or_use_cache(self, ticker, start_date, end_date, max_age_days=1):
        """Smart fetcher: uses cache if recent, fetches fresh if stale."""
        logger.info(f"🔍 Smart fetch for {ticker} ({start_date} to {end_date})")
        
        cached_df = self.get_cached_data(ticker, start_date, end_date)
        
        if cached_df is not None and not cached_df.empty:
            latest_date = pd.to_datetime(cached_df['Date'].max())
            age_days = (datetime.now() - latest_date).days
            
            if age_days <= max_age_days:
                logger.info(f"✅ Using cached data (age: {age_days} days)")
                return cached_df
            else:
                logger.info(f"⚠️ Cache is stale (age: {age_days} days). Fetching fresh data...")
        
        return self.fetch_stock_prices(ticker, start_date, end_date)
    
    def _save_to_csv(self, ticker, df, start_date, end_date):
        """Save DataFrame to CSV file."""
        try:
            filename = f"{ticker}_{start_date}_to_{end_date}.csv"
            filepath = self.raw_data_path / filename
            
            df.to_csv(filepath, index=False)
            logger.info(f"💾 Saved to CSV: {filepath}")
            
        except Exception as e:
            logger.error(f"❌ Failed to save CSV for {ticker}: {e}")
    
    def _save_to_database(self, ticker, df):
        """Save DataFrame to database."""
        if not self.db:
            return
        
        try:
            saved_count = 0
            
            # Verify columns
            required = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
            missing = [col for col in required if col not in df.columns]
            
            if missing:
                logger.error(f"❌ Cannot save to database. Missing columns: {missing}")
                logger.error(f"   Available columns: {list(df.columns)}")
                return
            
            # Save each row
            for _, row in df.iterrows():
                try:
                    date_str = pd.to_datetime(row['Date']).strftime('%Y-%m-%d')
                    
                    self.db.insert_stock_prices(
                        ticker=ticker,
                        date=date_str,
                        open=float(row['Open']),
                        high=float(row['High']),
                        low=float(row['Low']),
                        close=float(row['Close']),
                        volume=int(row['Volume'])
                    )
                    saved_count += 1
                except Exception as row_error:
                    logger.warning(f"⚠️ Failed to save row {date_str}: {row_error}")
                    continue
            
            logger.info(f"💾 Saved {saved_count}/{len(df)} records to database for {ticker}")
            
        except Exception as e:
            logger.error(f"❌ Failed to save to database for {ticker}: {e}")
            import traceback
            logger.error(traceback.format_exc())


if __name__ == "__main__":
    """Test script for StockDataFetcher"""
    from data.database import Database
    from config import BaseConfig
    
    logger.info("="*60)
    logger.info("TESTING STOCK DATA FETCHER - FIXED VERSION")
    logger.info("="*60)
    
    # Connect to database
    db = Database()
    db.connect()
    db.create_tables()
    
    # Create fetcher
    fetcher = StockDataFetcher(db=db)
    
    # Test 1: Fetch single stock
    logger.info("\n[TEST 1] Fetching single stock (AAPL)...")
    df = fetcher.fetch_stock_prices('AAPL', '2024-01-01', '2024-01-31')
    if df is not None:
        logger.info(f"✅ Success! Retrieved {len(df)} records")
        logger.info(f"Columns: {list(df.columns)}")
        logger.info(f"Sample:\n{df.head()}")
    
    # Test 2: Fetch latest price
    logger.info("\n[TEST 2] Fetching latest price...")
    latest = fetcher.fetch_latest_price('AAPL')
    if latest:
        logger.info(f"✅ Latest price: ${latest['price']:.2f}")
    
    # Test 3: Test cache
    logger.info("\n[TEST 3] Testing cache (should retrieve from database)...")
    cached = fetcher.fetch_or_use_cache('AAPL', '2024-01-01', '2024-01-31', max_age_days=30)
    if cached is not None:
        logger.info(f"✅ Cache test passed! {len(cached)} records")
    
    # Cleanup
    db.close()
    logger.info("\n✅ ALL TESTS COMPLETED!")