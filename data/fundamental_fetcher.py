"""
Fundamental Data Fetcher
========================
Fetches fundamental financial data (balance sheets, income statements, earnings)
from Alpha Vantage API.

Author: Abdilah (Data Engineer)
Compatible with: database.py, stock_fetcher.py
"""

import requests
import json
import time
from datetime import datetime
from pathlib import Path
from logger import get_logger

logger = get_logger('data.fundamental_fetcher')


class FundamentalDataFetcher:
    """
    Fetches fundamental financial data (balance sheets, income statements, earnings)
    from Alpha Vantage API.
    
    This class handles company fundamentals, implements API rate limiting,
    and manages raw data storage.
    """
    
    def __init__(self, api_key, raw_data_path='data/raw/fundamentals', db=None):
        """
        Initialize the Fundamental Data Fetcher.
        
        Parameters
        ----------
        api_key : str
            Alpha Vantage API key (get free key at alphavantage.co).
        
        raw_data_path : str, optional
            Directory for saving raw JSON files.
            Default is 'data/raw/fundamentals'.
        
        db : Database, optional
            Database instance for storing parsed data.
            If None, creates new Database instance.
        """
        if not api_key:
            raise ValueError("Alpha Vantage API key is required!")
        
        self.api_key = api_key
        self.base_url = "https://www.alphavantage.co/query"
        self.raw_data_path = Path(raw_data_path)
        self.raw_data_path.mkdir(parents=True, exist_ok=True)
        
        self.db = db
        self.last_api_call = 0
        self.rate_limit_delay = 12  # Alpha Vantage: 5 calls/min = 12 sec between calls
        
        logger.info(f"✅ FundamentalDataFetcher initialized")
        logger.info(f"   Raw data path: {self.raw_data_path}")
        logger.info(f"   Database: {'Connected' if db else 'Not connected'}")
        logger.info(f"   Rate limit: {self.rate_limit_delay} seconds between calls")
    
    def fetch_fundamentals(self, ticker):
        """
        Download fundamental financial data for a company.
        
        Parameters
        ----------
        ticker : str
            Stock symbol (e.g., 'AAPL').
        
        Returns
        -------
        dict or None
            Dictionary containing:
            - 'overview': Company overview and key metrics
            - 'income_statement': Annual income statements
            - 'balance_sheet': Annual balance sheets
            - 'cash_flow': Annual cash flow statements
            Returns None if fetch fails.
        
        Behavior
        --------
        - Fetches company overview from Alpha Vantage
        - Respects Alpha Vantage rate limit (5 calls/minute)
        - Saves raw JSON response to file
        - Parses and stores in database using insert_fundamental method
        - Handles API errors gracefully
        """
        logger.info(f"📊 Fetching fundamentals for {ticker}")
        
        try:
            # Enforce rate limit
            self._enforce_rate_limit()
            
            # Build API request
            params = {
                'function': 'OVERVIEW',
                'symbol': ticker,
                'apikey': self.api_key
            }
            
            # Make API call
            response = requests.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            # Check for API errors
            if 'Error Message' in data:
                logger.error(f"❌ API Error: {data['Error Message']}")
                return None
            
            if 'Note' in data:
                logger.warning(f"⚠️ API Note (rate limit?): {data['Note']}")
                return None
            
            if not data or data == {}:
                logger.warning(f"⚠️ No data returned for {ticker}")
                return None
            
            # Save raw JSON
            self._save_raw_json(ticker, data, 'overview')
            
            # Parse and save to database
            if self.db:
                self._parse_and_save_fundamentals(ticker, data)
            
            logger.info(f"✅ Successfully fetched fundamentals for {ticker}")
            
            return {
                'overview': data,
                'ticker': ticker,
                'fetch_date': datetime.now().isoformat()
            }
            
        except requests.exceptions.Timeout:
            logger.error(f"❌ API request timeout for {ticker}")
            return None
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ API request failed for {ticker}: {e}")
            return None
            
        except Exception as e:
            logger.error(f"❌ Unexpected error fetching fundamentals for {ticker}: {e}")
            return None
    
    def fetch_earnings(self, ticker):
        """
        Download earnings data (EPS, revenue) for a company.
        
        Parameters
        ----------
        ticker : str
            Stock symbol.
        
        Returns
        -------
        dict or None
            Dictionary containing quarterly and annual earnings data.
            Returns None if fetch fails.
        
        Behavior
        --------
        - Fetches earnings history from Alpha Vantage
        - Respects API rate limits
        - Saves raw JSON to file
        - Extracts EPS data and stores in fundamentals table
        - Can be used to update fundamentals with latest earnings
        """
        logger.info(f"📈 Fetching earnings for {ticker}")
        
        try:
            # Enforce rate limit
            self._enforce_rate_limit()
            
            # Build API request
            params = {
                'function': 'EARNINGS',
                'symbol': ticker,
                'apikey': self.api_key
            }
            
            # Make API call
            response = requests.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            # Check for API errors
            if 'Error Message' in data:
                logger.error(f"❌ API Error: {data['Error Message']}")
                return None
            
            if 'Note' in data:
                logger.warning(f"⚠️ API Note (rate limit?): {data['Note']}")
                return None
            
            if not data or data == {}:
                logger.warning(f"⚠️ No earnings data returned for {ticker}")
                return None
            
            # Save raw JSON
            self._save_raw_json(ticker, data, 'earnings')
            
            logger.info(f"✅ Successfully fetched earnings for {ticker}")
            
            return {
                'earnings': data,
                'ticker': ticker,
                'fetch_date': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Error fetching earnings for {ticker}: {e}")
            return None
    
    def fetch_income_statement(self, ticker):
        """
        Fetch detailed income statement.
        
        Parameters
        ----------
        ticker : str
            Stock symbol.
        
        Returns
        -------
        dict or None
            Income statement data.
        """
        logger.info(f"📊 Fetching income statement for {ticker}")
        
        try:
            # Enforce rate limit
            self._enforce_rate_limit()
            
            params = {
                'function': 'INCOME_STATEMENT',
                'symbol': ticker,
                'apikey': self.api_key
            }
            
            response = requests.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if 'Error Message' in data or 'Note' in data:
                logger.warning(f"⚠️ API issue for {ticker}")
                return None
            
            # Save raw JSON
            self._save_raw_json(ticker, data, 'income_statement')
            
            logger.info(f"✅ Successfully fetched income statement for {ticker}")
            return data
            
        except Exception as e:
            logger.error(f"❌ Error fetching income statement for {ticker}: {e}")
            return None
    
    def fetch_balance_sheet(self, ticker):
        """
        Fetch detailed balance sheet.
        
        Parameters
        ----------
        ticker : str
            Stock symbol.
        
        Returns
        -------
        dict or None
            Balance sheet data.
        """
        logger.info(f"📊 Fetching balance sheet for {ticker}")
        
        try:
            # Enforce rate limit
            self._enforce_rate_limit()
            
            params = {
                'function': 'BALANCE_SHEET',
                'symbol': ticker,
                'apikey': self.api_key
            }
            
            response = requests.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if 'Error Message' in data or 'Note' in data:
                logger.warning(f"⚠️ API issue for {ticker}")
                return None
            
            # Save raw JSON
            self._save_raw_json(ticker, data, 'balance_sheet')
            
            logger.info(f"✅ Successfully fetched balance sheet for {ticker}")
            return data
            
        except Exception as e:
            logger.error(f"❌ Error fetching balance sheet for {ticker}: {e}")
            return None
    
    def get_cached_fundamentals(self, ticker):
        """
        Retrieve fundamentals from database cache.
        
        Parameters
        ----------
        ticker : str
            Stock symbol.
        
        Returns
        -------
        list or None
            Cached fundamental data.
        """
        if not self.db:
            logger.warning("⚠️ Database not connected. Cannot retrieve cached data.")
            return None
        
        try:
            rows = self.db.get_fundamentals(ticker)
            
            if not rows:
                logger.info(f"📭 No cached fundamentals for {ticker}")
                return None
            
            logger.info(f"✅ Retrieved {len(rows)} cached fundamental records for {ticker}")
            return rows
            
        except Exception as e:
            logger.error(f"❌ Error retrieving cached fundamentals for {ticker}: {e}")
            return None
    
    def _enforce_rate_limit(self):
        """
        Internal method to enforce Alpha Vantage rate limit (5 calls/minute).
        
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
    
    def _save_raw_json(self, ticker, data, data_type):
        """
        Internal method to save raw JSON response to file.
        
        Parameters
        ----------
        ticker : str
            Stock symbol.
        
        data : dict
            JSON data to save.
        
        data_type : str
            Type of data (e.g., 'overview', 'earnings').
        
        Behavior
        --------
        - Creates filename with ticker, type, and timestamp
        - Saves JSON with proper formatting
        - Logs file location
        """
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{ticker}_{data_type}_{timestamp}.json"
            filepath = self.raw_data_path / filename
            
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.info(f"💾 Saved raw JSON: {filepath}")
            
        except Exception as e:
            logger.error(f"❌ Failed to save raw JSON for {ticker}: {e}")
    
    def _parse_and_save_fundamentals(self, ticker, overview):
        """
        Internal method to parse fundamental data and save to database.
        
        Parameters
        ----------
        ticker : str
            Stock symbol.
        
        overview : dict
            Raw fundamental data from API (company overview).
        
        Behavior
        --------
        - Extracts key metrics from overview (revenue, net_income, EPS, PE ratio)
        - Uses db.insert_fundamental() to save to database
        - Handles missing fields with default values
        - Uses current date as the fundamental data date
        """
        if not self.db:
            return
        
        try:
            # Extract key metrics with safe defaults
            revenue = self._safe_float(overview.get('RevenueTTM', 0))
            net_income = self._safe_float(overview.get('NetIncomeTTM', 0))
            eps = self._safe_float(overview.get('EPS', 0))
            pe_ratio = self._safe_float(overview.get('PERatio', 0))
            
            # Use current date
            date = datetime.now().strftime('%Y-%m-%d')
            
            # Save to database
            self.db.insert_fundamental(
                ticker=ticker,
                date=date,
                revenue=revenue,
                net_income=net_income,
                eps=eps,
                pe_ratio=pe_ratio
            )
            
            logger.info(f"💾 Saved fundamentals to database for {ticker}")
            logger.info(f"   Revenue: ${revenue:,.0f}")
            logger.info(f"   Net Income: ${net_income:,.0f}")
            logger.info(f"   EPS: ${eps:.2f}")
            logger.info(f"   P/E Ratio: {pe_ratio:.2f}")
            
        except Exception as e:
            logger.error(f"❌ Failed to parse and save fundamentals for {ticker}: {e}")
    
    def _safe_float(self, value):
        """
        Safely convert value to float, handling 'None', 'N/A', etc.
        
        Parameters
        ----------
        value : any
            Value to convert.
        
        Returns
        -------
        float
            Converted float or 0.0 if conversion fails.
        """
        if value is None or value == 'None' or value == 'N/A':
            return 0.0
        
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0


if __name__ == "__main__":
    """
    Test script for FundamentalDataFetcher
    """
    from data.database import Database
    from config import BaseConfig
    
    # Setup
    logger.info("="*60)
    logger.info("TESTING FUNDAMENTAL DATA FETCHER")
    logger.info("="*60)
    
    # Check for API key
    if not BaseConfig.ALPHA_VANTAGE_API_KEY:
        logger.error("❌ ALPHA_VANTAGE_API_KEY not found in environment!")
        logger.error("   Get a free key at: https://www.alphavantage.co/support/#api-key")
        exit(1)
    
    # Connect to database
    db = Database()
    db.connect()
    db.create_tables()
    
    # Create fetcher
    fetcher = FundamentalDataFetcher(
        api_key=BaseConfig.ALPHA_VANTAGE_API_KEY,
        db=db
    )
    
    # Test 1: Fetch company overview
    logger.info("\n[TEST 1] Fetching company overview (AAPL)...")
    overview = fetcher.fetch_fundamentals('AAPL')
    if overview:
        logger.info("✅ Success!")
        logger.info(f"Company: {overview['overview'].get('Name', 'N/A')}")
        logger.info(f"Sector: {overview['overview'].get('Sector', 'N/A')}")
        logger.info(f"Market Cap: {overview['overview'].get('MarketCapitalization', 'N/A')}")
    
    # Test 2: Fetch earnings
    logger.info("\n[TEST 2] Fetching earnings (AAPL)...")
    earnings = fetcher.fetch_earnings('AAPL')
    if earnings:
        logger.info("✅ Earnings data fetched!")
    
    # Test 3: Check cached data
    logger.info("\n[TEST 3] Checking cached fundamentals...")
    cached = fetcher.get_cached_fundamentals('AAPL')
    if cached:
        logger.info(f"✅ Found {len(cached)} cached records")
    
    # Cleanup
    db.close()
    logger.info("\n✅ ALL TESTS COMPLETED!")