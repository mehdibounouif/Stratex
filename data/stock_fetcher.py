"""
Stock Price Data Fetcher
========================
Fetches historical and real-time stock price data from Yahoo Finance.
Integrates with Database class for persistent storage.

Author: Abdilah (Data Engineer)
Compatible with: database.py, data_engineer.py
"""

import pandas as pd
import yfinance as yf
import time
from datetime import datetime, timedelta
from pathlib import Path
from logger import setup_logging, get_logger

setup_logging()
logger = get_logger('data.stock_fetcher')


class StockDataFetcher:
    """
    Fetches historical and real-time stock price data from Yahoo Finance.
    
    This class handles downloading stock prices, managing retries on failures,
    implementing rate limiting, and saving data both as raw files and to database.
    """
    
    def __init__(self, raw_data_path='data/raw/stocks', db=None):
        """
        Initialize the Stock Data Fetcher.
        
        Parameters
        ----------
        raw_data_path : str, optional
            Directory path where raw CSV files will be saved.
            Default is 'data/raw/stocks'.
        
        db : Database, optional
            Database instance for storing fetched data.
            If None, creates new Database instance.
        """
        self.raw_data_path = Path(raw_data_path)
        self.raw_data_path.mkdir(parents=True, exist_ok=True)
        
        self.db = db
        self.max_retries = 3
        self.retry_delay = 2  # seconds
        
        logger.info(f"✅ StockDataFetcher initialized")
        logger.info(f"   Raw data path: {self.raw_data_path}")
        logger.info(f"   Database: {'Connected' if db else 'Not connected'}")
    
    def fetch_stock_prices(self, ticker, start_date, end_date):
        """
        Download historical stock price data for a single ticker.
        
        Parameters
        ----------
        ticker : str
            Stock symbol (e.g., 'AAPL', 'TSLA').
        
        start_date : str
            Start date in 'YYYY-MM-DD' format.
        
        end_date : str
            End date in 'YYYY-MM-DD' format.
        
        Returns
        -------
        pd.DataFrame or None
            DataFrame with columns: Date, Open, High, Low, Close, Volume.
            Returns None if download fails after max retries.
        
        Behavior
        --------
        - Downloads data from Yahoo Finance using yfinance
        - Retries up to 3 times on failure with exponential backoff
        - Saves raw data to CSV file in raw_data_path
        - Stores data in database using insert_stock_prices method
        - Logs all operations and errors
        """
        logger.info(f"📊 Fetching stock prices for {ticker} ({start_date} to {end_date})")
        
        for attempt in range(1, self.max_retries + 1):
            try:
                # Download data from yfinance
                df = yf.download(
                    ticker,
                    start=start_date,
                    end=end_date,
                    progress=False
                )
                
                if df.empty:
                    logger.warning(f"⚠️ No data returned for {ticker}")
                    return None
                
                # Reset index to make Date a column
                df = df.reset_index()
                
                # Ensure column names are strings (yfinance sometimes returns tuples)
                df.columns = [str(col).replace("('", "").replace("',)", "") if isinstance(col, tuple) else str(col) for col in df.columns]
                
                # Standardize column names
                column_mapping = {
                    'Date': 'Date',
                    'Open': 'Open',
                    'High': 'High',
                    'Low': 'Low',
                    'Close': 'Close',
                    'Adj Close': 'Adj_Close',
                    'Volume': 'Volume'
                }
                
                # Rename columns to standard format
                for old_name, new_name in column_mapping.items():
                    if old_name in df.columns:
                        df.rename(columns={old_name: new_name}, inplace=True)
                
                logger.info(f"✅ Downloaded {len(df)} records for {ticker}")
                
                # Save to CSV file
                self._save_to_csv(ticker, df, start_date, end_date)
                
                # Save to database
                if self.db:
                    self._save_to_database(ticker, df)
                else:
                    logger.warning("⚠️ Database not connected. Skipping database save.")
                
                return df
                
            except Exception as e:
                logger.error(f"❌ Attempt {attempt}/{self.max_retries} failed for {ticker}: {e}")
                
                if attempt < self.max_retries:
                    wait_time = self.retry_delay * (2 ** (attempt - 1))  # Exponential backoff
                    logger.info(f"⏳ Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"❌ All retries exhausted for {ticker}")
                    return None
    
    def fetch_latest_price(self, ticker):
        """
        Get the most recent trading price for a stock.
        
        Parameters
        ----------
        ticker : str
            Stock symbol (e.g., 'AAPL').
        
        Returns
        -------
        dict or None
            Dictionary containing:
            - 'ticker': Stock symbol
            - 'price': Current/last traded price
            - 'timestamp': Time of the price quote
            - 'volume': Trading volume
            - 'market_cap': Market capitalization
            Returns None if fetch fails.
        
        Behavior
        --------
        - Fetches real-time or latest available price from yfinance
        - Implements retry logic with rate limiting
        - Returns dictionary with latest price information
        - Does NOT save to database (use fetch_stock_prices for that)
        """
        logger.info(f"📈 Fetching latest price for {ticker}")
        
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            
            # Get latest price from multiple possible fields
            price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
            
            if price is None:
                logger.warning(f"⚠️ Could not find price for {ticker}")
                return None
            
            result = {
                'ticker': ticker,
                'price': float(price),
                'timestamp': datetime.now().isoformat(),
                'volume': info.get('volume', 0),
                'market_cap': info.get('marketCap', 0),
                'currency': info.get('currency', 'USD')
            }
            
            logger.info(f"✅ Latest price for {ticker}: ${result['price']:.2f}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Failed to fetch latest price for {ticker}: {e}")
            return None
    
    def fetch_multiple_stocks(self, tickers, start_date, end_date, delay=1):
        """
        Download historical data for multiple stocks with rate limiting.
        
        Parameters
        ----------
        tickers : list of str
            List of stock symbols (e.g., ['AAPL', 'MSFT', 'GOOGL']).
        
        start_date : str
            Start date in 'YYYY-MM-DD' format.
        
        end_date : str
            End date in 'YYYY-MM-DD' format.
        
        delay : float, optional
            Seconds to wait between API calls to avoid rate limits.
            Default is 1 second.
        
        Returns
        -------
        dict
            Dictionary mapping ticker symbols to their DataFrames.
            Failed tickers will have None as their value.
        
        Behavior
        --------
        - Iterates through ticker list with delay between requests
        - Aggregates all successful downloads
        - Logs summary of successful vs failed downloads
        - Returns all results even if some tickers fail
        """
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
            
            # Rate limiting: wait between requests (except for last ticker)
            if i < len(tickers):
                logger.info(f"⏳ Waiting {delay} seconds before next request...")
                time.sleep(delay)
        
        # Summary
        logger.info(f"\n{'='*60}")
        logger.info(f"FETCH SUMMARY:")
        logger.info(f"  Total tickers: {len(tickers)}")
        logger.info(f"  ✅ Successful: {successful}")
        logger.info(f"  ❌ Failed: {failed}")
        logger.info(f"{'='*60}\n")
        
        return results
    
    def get_cached_data(self, ticker, start_date, end_date):
        """
        Retrieve stock data from database cache.
        
        Parameters
        ----------
        ticker : str
            Stock symbol.
        
        start_date : str
            Start date in 'YYYY-MM-DD' format.
        
        end_date : str
            End date in 'YYYY-MM-DD' format.
        
        Returns
        -------
        pd.DataFrame or None
            Cached data if available, None otherwise.
        """
        if not self.db:
            logger.warning("⚠️ Database not connected. Cannot retrieve cached data.")
            return None
        
        try:
            rows = self.db.get_stock_prices(ticker, start_date, end_date)
            
            if not rows:
                logger.info(f"📭 No cached data for {ticker} ({start_date} to {end_date})")
                return None
            
            # Convert to DataFrame
            df = pd.DataFrame(rows, columns=['id', 'ticker', 'date', 'open', 'high', 'low', 'close', 'volume'])
            df = df.drop('id', axis=1)
            df['date'] = pd.to_datetime(df['date'])
            
            logger.info(f"✅ Retrieved {len(df)} cached records for {ticker}")
            return df
            
        except Exception as e:
            logger.error(f"❌ Error retrieving cached data for {ticker}: {e}")
            return None
    
    def fetch_or_use_cache(self, ticker, start_date, end_date, max_age_days=1):
        """
        Smart fetcher: uses cache if recent, fetches fresh if stale.
        
        Parameters
        ----------
        ticker : str
            Stock symbol.
        
        start_date : str
            Start date in 'YYYY-MM-DD' format.
        
        end_date : str
            End date in 'YYYY-MM-DD' format.
        
        max_age_days : int, optional
            Maximum age of cached data in days before fetching fresh.
            Default is 1 day.
        
        Returns
        -------
        pd.DataFrame or None
            Stock price data.
        """
        logger.info(f"🔍 Smart fetch for {ticker} ({start_date} to {end_date})")
        
        # Try to get cached data
        cached_df = self.get_cached_data(ticker, start_date, end_date)
        
        if cached_df is not None and not cached_df.empty:
            # Check if cache is recent enough
            latest_date = pd.to_datetime(cached_df['date'].max())
            age_days = (datetime.now() - latest_date).days
            
            if age_days <= max_age_days:
                logger.info(f"✅ Using cached data (age: {age_days} days)")
                return cached_df
            else:
                logger.info(f"⚠️ Cache is stale (age: {age_days} days). Fetching fresh data...")
        
        # Fetch fresh data
        return self.fetch_stock_prices(ticker, start_date, end_date)
    
    def _save_to_csv(self, ticker, df, start_date, end_date):
        """
        Save DataFrame to CSV file.
        
        Parameters
        ----------
        ticker : str
            Stock symbol.
        
        df : pd.DataFrame
            Data to save.
        
        start_date : str
            Start date for filename.
        
        end_date : str
            End date for filename.
        """
        try:
            filename = f"{ticker}_{start_date}_to_{end_date}.csv"
            filepath = self.raw_data_path / filename
            
            df.to_csv(filepath, index=False)
            logger.info(f"💾 Saved to CSV: {filepath}")
            
        except Exception as e:
            logger.error(f"❌ Failed to save CSV for {ticker}: {e}")
    
    def _save_to_database(self, ticker, df):
        """
        Save DataFrame to database using Database class methods.
        
        Parameters
        ----------
        ticker : str
            Stock symbol for labeling the data.
        
        df : pd.DataFrame
            Data to save with columns: Date, Open, High, Low, Close, Volume.
        """
        if not self.db:
            return
        
        try:
            saved_count = 0
            
            for _, row in df.iterrows():
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
            
            logger.info(f"💾 Saved {saved_count} records to database for {ticker}")
            
        except Exception as e:
            logger.error(f"❌ Failed to save to database for {ticker}: {e}")


if __name__ == "__main__":
    """
    Test script for StockDataFetcher
    """
    from data.database import Database
    from config import BaseConfig
    
    # Setup
    logger.info("="*60)
    logger.info("TESTING STOCK DATA FETCHER")
    logger.info("="*60)
    
    # Connect to database
    db = Database()
    db.connect()
    db.create_tables()
    
    # Create fetcher
    fetcher = StockDataFetcher(db=db)
    
    # Test 1: Fetch single stock
    logger.info("\n[TEST 1] Fetching single stock (AAPL)...")
    df = fetcher.fetch_stock_prices('AAPL', '2024-01-01', '2024-12-31')
    if df is not None:
        logger.info(f"✅ Success! Retrieved {len(df)} records")
        logger.info(f"Sample:\n{df.head()}")
    
    # Test 2: Fetch latest price
    logger.info("\n[TEST 2] Fetching latest price...")
    latest = fetcher.fetch_latest_price('AAPL')
    if latest:
        logger.info(f"✅ Latest price: ${latest['price']:.2f}")
    
    # Test 3: Fetch multiple stocks
    logger.info("\n[TEST 3] Fetching multiple stocks...")
    results = fetcher.fetch_multiple_stocks(
        ['AAPL', 'MSFT', 'GOOGL'],
        '2024-01-01',
        '2024-01-31',
        delay=1
    )
    
    # Test 4: Use cache
    logger.info("\n[TEST 4] Testing cache functionality...")
    cached = fetcher.fetch_or_use_cache('AAPL', '2024-01-01', '2024-01-31')
    if cached is not None:
        logger.info(f"✅ Cache test passed! {len(cached)} records")
    
    # Cleanup
    db.close()
    logger.info("\n✅ ALL TESTS COMPLETED!")