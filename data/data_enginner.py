"""
Data Engineer — DataEngineer
==============================
Central data access layer for the trading system.

Responsibilities:
- Provides clean, validated price data to strategies
- Uses database cache FIRST (fast), fetches from APIs only if needed
- Handles multiple data sources: stock_fetcher, fundamental_fetcher, news_fetcher
- Cleans data automatically using data_cleaner before returning

Interface:
- get_price_history(ticker, days)   → DataFrame  (OHLCV)
- get_latest_price(ticker)          → float
- get_multiple_stocks(tickers, days)→ dict
- get_fundamentals(ticker)          → dict
- get_news(ticker, days)            → list

Data flow:
    Strategy calls get_price_history('AAPL', days=90)
        ↓
    Check database cache first (fast)
        ↓
    If cache fresh (< 1 day old) → return cached data
        ↓
    If cache stale → fetch from yfinance → clean → save → return
        ↓
    Strategy receives clean DataFrame ready to use

Author: Abdilah (Data Engineer)
"""

import pandas as pd
from datetime import datetime, timedelta
from logger import setup_logging, get_logger
from data.database import Database

setup_logging()
log = get_logger("data.data_engineer")


class DataEngineer:
    """
    Central data access layer — strategies call this for ALL data needs.
    
    Uses smart caching: database first (fast), API only if stale.
    """
    
    def __init__(self):
        log.info("=" * 60)
        log.info("  DATA ENGINEER INITIALIZING")
        log.info("=" * 60)
        
        # Database
        self.db = Database()
        self.db.connect()
        self.db.create_tables()
        log.info("✅ Database connected")
        
        # Stock price fetcher (yfinance)
        try:
            from data.stock_fetcher import StockDataFetcher
            self.stock_fetcher = StockDataFetcher(db=self.db)
            log.info("✅ Stock fetcher loaded (yfinance)")
        except Exception as e:
            log.warning(f"⚠️  Stock fetcher unavailable: {e}")
            self.stock_fetcher = None
        
        # Data cleaner
        try:
            from data.pipelines.data_cleaning import DataCleaner
            self.cleaner = DataCleaner(db=self.db)
            log.info("✅ Data cleaner loaded")
        except Exception as e:
            log.warning(f"⚠️  Data cleaner unavailable: {e}. Data won't be auto-cleaned.")
            self.cleaner = None
        
        # Fundamental fetcher (Alpha Vantage) — optional
        try:
            from config import BaseConfig
            from data.fundamental_fetcher import FundamentalDataFetcher
            
            api_key = BaseConfig.ALPHA_VANTAGE_API_KEY
            if api_key and api_key != 'your_alpha_vantage_key_here':
                self.fundamental_fetcher = FundamentalDataFetcher(api_key=api_key, db=self.db)
                log.info("✅ Fundamental fetcher loaded (Alpha Vantage)")
            else:
                log.info("ℹ️  Alpha Vantage key not configured — fundamentals unavailable")
                self.fundamental_fetcher = None
        except Exception as e:
            log.warning(f"⚠️  Fundamental fetcher unavailable: {e}")
            self.fundamental_fetcher = None
        
        # News fetcher (Alpha Vantage) — optional
        try:
            from config import BaseConfig
            from data.news_fetcher import NewsDataFetcher
            
            api_key = BaseConfig.ALPHA_VANTAGE_API_KEY
            if api_key and api_key != 'your_alpha_vantage_key_here':
                self.news_fetcher = NewsDataFetcher(api_key=api_key, db=self.db)
                log.info("✅ News fetcher loaded (Alpha Vantage)")
            else:
                log.info("ℹ️  Alpha Vantage key not configured — news unavailable")
                self.news_fetcher = None
        except Exception as e:
            log.warning(f"⚠️  News fetcher unavailable: {e}")
            self.news_fetcher = None
        
        log.info("=" * 60)
    
    # ================================================================
    # STOCK PRICES — Primary interface for strategies
    # ================================================================
    
    def get_price_history(self, ticker, days=365, force_fetch=False):
        """
        Get historical stock prices. Uses cache first (fast).
        
        Parameters
        ----------
        ticker : str
            Stock symbol (e.g., 'AAPL').
        
        days : int, optional
            Number of days of history to retrieve. Default is 365.
        
        force_fetch : bool, optional
            If True, bypass cache and fetch fresh data from API.
            Default is False.
        
        Returns
        -------
        pd.DataFrame or None
            DataFrame with columns: Date, Open, High, Low, Close, Volume.
            Returns None if data unavailable.
        
        Behavior
        --------
        1. Checks database cache first (< 1 day old = fresh)
        2. If cache fresh → return cached data (fast)
        3. If cache stale → fetch from yfinance → clean → save → return
        4. All returned data is automatically cleaned (duplicates removed, OHLC fixed)
        """
        log.info(f"📊 Getting price history: {ticker} (last {days} days)")
        
        if not self.stock_fetcher:
            log.error("Stock fetcher not available")
            return None
        
        # Calculate date range
        end_date   = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        start_str = start_date.strftime('%Y-%m-%d')
        end_str   = end_date.strftime('%Y-%m-%d')
        
        # Force fetch mode → skip cache
        if force_fetch:
            log.info(f"   Force fetch mode — bypassing cache")
            return self._fetch_and_clean(ticker, start_str, end_str)
        
        # Smart cache mode → use fetch_or_use_cache
        try:
            df = self.stock_fetcher.fetch_or_use_cache(
                ticker=ticker,
                start_date=start_str,
                end_date=end_str,
                max_age_days=1   # Cache is fresh if < 1 day old
            )
            
            if df is not None and not df.empty:
                log.info(f"✅ Retrieved {len(df)} records for {ticker}")
                return df
            else:
                log.warning(f"⚠️  No data returned for {ticker}")
                return None
                
        except Exception as e:
            log.error(f"❌ Failed to get price history for {ticker}: {e}")
            return None
    
    def get_latest_price(self, ticker):
        """
        Get the most recent price for a stock.
        
        Parameters
        ----------
        ticker : str
            Stock symbol.
        
        Returns
        -------
        float or None
            Latest closing price, or None if unavailable.
        
        Behavior
        --------
        - Tries database first (fastest)
        - If database empty or very stale, fetches from API
        - Returns just the price as a float (not full DataFrame)
        """
        log.debug(f"Getting latest price for {ticker}")
        
        if not self.stock_fetcher:
            log.error("Stock fetcher not available")
            return None
        
        try:
            # Try database first
            # Get all rows for this ticker, we'll take the most recent
            rows = self.db.get_stock_prices(ticker)
            
            if rows:
                # Rows are ordered by date DESC, so first row is most recent
                # Row format: (id, ticker, date, open, high, low, close, volume)
                latest_date_str = rows[0][2]  # date column
                latest_date = datetime.strptime(latest_date_str, '%Y-%m-%d')
                age_hours = (datetime.now() - latest_date).total_seconds() / 3600
                
                # If less than 6 hours old, use cached price
                if age_hours < 6:
                    price = float(rows[0][6])  # close price column
                    log.debug(f"   Using cached price: ${price:.2f} (age: {age_hours:.1f}h)")
                    return price
            
            # Fetch fresh price from API
            price_info = self.stock_fetcher.fetch_latest_price(ticker)
            
            if price_info and 'price' in price_info:
                price = float(price_info['price'])
                log.debug(f"   Fetched fresh price: ${price:.2f}")
                return price
            
            log.warning(f"Could not get price for {ticker}")
            return None
            
        except Exception as e:
            log.error(f"Error getting latest price for {ticker}: {e}")
            return None
    
    def get_multiple_stocks(self, tickers, days=365):
        """
        Get price history for multiple stocks efficiently.
        
        Parameters
        ----------
        tickers : list of str
            List of stock symbols.
        
        days : int, optional
            Number of days of history. Default is 365.
        
        Returns
        -------
        dict
            {ticker: DataFrame} mapping.
            Tickers that fail will have None as value.
        
        Behavior
        --------
        - Fetches each ticker sequentially
        - Uses cache for each ticker (same as get_price_history)
        - Adds 1 second delay between API calls to respect rate limits
        - Returns all results, even if some tickers fail
        """
        log.info(f"📊 Fetching {len(tickers)} stocks (last {days} days)")
        
        results = {}
        
        for i, ticker in enumerate(tickers):
            log.info(f"[{i+1}/{len(tickers)}] {ticker}")
            
            try:
                df = self.get_price_history(ticker, days=days)
                results[ticker] = df
                
                # Rate limiting: 1 second delay between tickers
                if i < len(tickers) - 1:  # Don't delay after last ticker
                    import time
                    time.sleep(1)
                    
            except Exception as e:
                log.error(f"Failed to fetch {ticker}: {e}")
                results[ticker] = None
        
        successful = sum(1 for v in results.values() if v is not None)
        log.info(f"✅ Completed: {successful}/{len(tickers)} successful")
        
        return results
    
    def _fetch_and_clean(self, ticker, start_date, end_date):
        """
        Internal: fetch fresh data and clean it.
        
        This is called when cache is bypassed or stale.
        """
        df = self.stock_fetcher.fetch_stock_prices(ticker, start_date, end_date)
        
        if df is not None and not df.empty and self.cleaner:
            df = self.cleaner.clean_stock_prices(df, ticker=ticker)
        
        return df
    
    # ================================================================
    # FUNDAMENTALS — Company financial data
    # ================================================================
    
    def get_fundamentals(self, ticker):
        """
        Get fundamental financial data for a company.
        
        Parameters
        ----------
        ticker : str
            Stock symbol.
        
        Returns
        -------
        dict or None
            Fundamental data including:
            - revenue, net_income, eps, pe_ratio
            - market_cap, book_value, dividend_yield
            Returns None if unavailable or Alpha Vantage key not configured.
        
        Behavior
        --------
        - Requires Alpha Vantage API key in config
        - Uses database cache (checks get_cached_fundamentals first)
        - Respects Alpha Vantage rate limits (5 calls/min)
        - Returns None gracefully if API unavailable
        """
        if not self.fundamental_fetcher:
            log.debug(f"Fundamentals unavailable for {ticker} (no API key)")
            return None
        
        log.info(f"📈 Getting fundamentals: {ticker}")
        
        try:
            # Check cache first
            cached = self.fundamental_fetcher.get_cached_fundamentals(ticker)
            if cached:
                log.info(f"   Using cached fundamentals")
                return cached
            
            # Fetch fresh
            fundamentals = self.fundamental_fetcher.fetch_fundamentals(ticker)
            return fundamentals
            
        except Exception as e:
            log.error(f"Error getting fundamentals for {ticker}: {e}")
            return None
    
    # ================================================================
    # NEWS — Sentiment and headlines
    # ================================================================
    
    def get_news(self, ticker, days=7):
        """
        Get recent news articles with sentiment for a stock.
        
        Parameters
        ----------
        ticker : str
            Stock symbol.
        
        days : int, optional
            Number of days of news history. Default is 7.
        
        Returns
        -------
        list or None
            List of news articles with sentiment scores.
            Each article is a dict with: headline, source, date, sentiment.
            Returns None if unavailable or Alpha Vantage key not configured.
        
        Behavior
        --------
        - Requires Alpha Vantage API key
        - Uses database cache first
        - Sentiment scores range from -1 (bearish) to +1 (bullish)
        - Returns None gracefully if API unavailable
        """
        if not self.news_fetcher:
            log.debug(f"News unavailable for {ticker} (no API key)")
            return None
        
        log.info(f"📰 Getting news: {ticker} (last {days} days)")
        
        try:
            # Check cache first
            cached = self.news_fetcher.get_cached_news(ticker, days=days)
            if cached:
                log.info(f"   Using cached news ({len(cached)} articles)")
                return cached
            
            # Fetch fresh
            news = self.news_fetcher.fetch_news(ticker, days=days)
            return news
            
        except Exception as e:
            log.error(f"Error getting news for {ticker}: {e}")
            return None
    
    def get_market_news(self, days=1):
        """
        Get general market news (not ticker-specific).
        
        Parameters
        ----------
        days : int, optional
            Number of days of news. Default is 1.
        
        Returns
        -------
        list or None
            List of general market news articles.
        """
        if not self.news_fetcher:
            return None
        
        try:
            return self.news_fetcher.fetch_market_news(days=days)
        except Exception as e:
            log.error(f"Error getting market news: {e}")
            return None
    
    # ================================================================
    # UTILITIES
    # ================================================================
    
    def clean_database(self):
        """
        Run data cleaning on all data in database.
        
        This removes duplicates, fixes OHLC violations, etc.
        Should be run periodically (weekly).
        """
        if not self.cleaner:
            log.warning("Data cleaner not available")
            return
        
        log.info("🧹 Running database cleaning...")
        self.cleaner.clean_database_stock_prices()
        self.cleaner.remove_duplicate_news()
        self.cleaner.vacuum_database()
        log.info("✅ Database cleaning complete")
    
    def clear_cache(self, ticker=None):
        """
        Clear cached data to force fresh fetch next time.
        
        Parameters
        ----------
        ticker : str, optional
            If provided, clear only this ticker.
            If None, clear all cached data.
        """
        if ticker:
            log.info(f"Clearing cache for {ticker}")
            self.db.delete_data_from_table('stock_prices', ticker)
        else:
            log.warning("Clearing entire cache")
            self.db.drop_table('stock_prices')
            self.db.create_tables()
    
    def get_cache_stats(self):
        """
        Get statistics about cached data.
        
        Returns
        -------
        dict
            Cache statistics: num_tickers, oldest_date, newest_date, total_records
        """
        try:
            cursor = self.db.cursor
            
            # Count tickers
            cursor.execute("SELECT COUNT(DISTINCT ticker) FROM stock_prices")
            num_tickers = cursor.fetchone()[0]
            
            # Date range
            cursor.execute("SELECT MIN(date), MAX(date) FROM stock_prices")
            oldest, newest = cursor.fetchone()
            
            # Total records
            cursor.execute("SELECT COUNT(*) FROM stock_prices")
            total_records = cursor.fetchone()[0]
            
            return {
                'num_tickers': num_tickers,
                'oldest_date': oldest,
                'newest_date': newest,
                'total_records': total_records
            }
        except Exception as e:
            log.error(f"Error getting cache stats: {e}")
            return {}
    
    def close(self):
        """Close database connection."""
        if self.db:
            self.db.close()
            log.info("Database connection closed")


# ── Global instance ───────────────────────────────────────────
data_access = DataEngineer()


# ================================================================
# STANDALONE TEST
# ================================================================

if __name__ == "__main__":
    log.info("=" * 60)
    log.info("TESTING DATA ENGINEER")
    log.info("=" * 60)
    
    # Test 1: Get price history (uses cache)
    log.info("\n[TEST 1] Get price history for AAPL (90 days)")
    df = data_access.get_price_history('AAPL', days=90)
    
    if df is not None:
        log.info(f"✅ Retrieved {len(df)} records")
        log.info(f"\nSample data (last 5 days):")
        print(df.tail())
    else:
        log.error("❌ Failed to get data")
    
    # Test 2: Get latest price
    log.info("\n[TEST 2] Get latest price for AAPL")
    price = data_access.get_latest_price('AAPL')
    
    if price:
        log.info(f"✅ Latest price: ${price:.2f}")
    else:
        log.error("❌ Failed to get price")
    
    # Test 3: Multiple stocks
    log.info("\n[TEST 3] Get multiple stocks")
    results = data_access.get_multiple_stocks(['AAPL', 'MSFT', 'GOOGL'], days=30)
    
    for ticker, df in results.items():
        if df is not None:
            log.info(f"✅ {ticker}: {len(df)} records")
        else:
            log.error(f"❌ {ticker}: failed")
    
    # Test 4: Cache stats
    log.info("\n[TEST 4] Cache statistics")
    stats = data_access.get_cache_stats()
    log.info(f"Cache stats: {stats}")
    
    # Test 5: Fundamentals (if API key configured)
    log.info("\n[TEST 5] Get fundamentals for AAPL")
    fundamentals = data_access.get_fundamentals('AAPL')
    
    if fundamentals:
        log.info(f"✅ Fundamentals retrieved")
        # fundamental_fetcher returns database rows as tuples
        # Format: (id, ticker, date, revenue, net_income, eps, pe_ratio)
        if isinstance(fundamentals, list) and len(fundamentals) > 0:
            row = fundamentals[0]
            if isinstance(row, tuple) and len(row) >= 7:
                log.info(f"   Ticker: {row[1]}")
                log.info(f"   Date: {row[2]}")
                log.info(f"   Revenue: {row[3]}")
                log.info(f"   EPS: {row[5]}")
            elif isinstance(row, dict):
                log.info(f"   Revenue: {row.get('revenue', 'N/A')}")
                log.info(f"   EPS: {row.get('eps', 'N/A')}")
        elif isinstance(fundamentals, dict):
            log.info(f"   Revenue: {fundamentals.get('revenue', 'N/A')}")
            log.info(f"   EPS: {fundamentals.get('eps', 'N/A')}")
    else:
        log.info("ℹ️  Fundamentals unavailable (API key not configured)")
    
    # Test 6: News (if API key configured)
    log.info("\n[TEST 6] Get news for AAPL")
    news = data_access.get_news('AAPL', days=7)
    
    if news:
        log.info(f"✅ Retrieved {len(news)} news articles")
    else:
        log.info("ℹ️  News unavailable (API key not configured)")
    
    log.info("\n✅ ALL TESTS COMPLETED!")












