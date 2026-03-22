"""
News Data Fetcher
=================
Fetches financial news articles and sentiment scores from Alpha Vantage News API.

Author: Abdilah (Data Engineer)
Compatible with: database.py, stock_fetcher.py, fundamental_fetcher.py
"""

import requests
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from logger import get_logger

logger = get_logger('data.news_fetcher')


class NewsDataFetcher:
    """
    Fetches financial news articles and sentiment scores from Alpha Vantage News API.
    
    This class handles news retrieval, sentiment analysis, and storage for
    both ticker-specific and general market news.
    """
    
    def __init__(self, api_key, raw_data_path='data/raw/news', db=None):
        """
        Initialize the News Data Fetcher.
        
        Parameters
        ----------
        api_key : str
            Alpha Vantage API key.
        
        raw_data_path : str, optional
            Directory for saving raw news JSON files.
            Default is 'data/raw/news'.
        
        db : Database, optional
            Database instance for storing news data.
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
        
        logger.info(f"✅ NewsDataFetcher initialized")
        logger.info(f"   Raw data path: {self.raw_data_path}")
        logger.info(f"   Database: {'Connected' if db else 'Not connected'}")
        logger.info(f"   Rate limit: {self.rate_limit_delay} seconds between calls")
    
    def fetch_news(self, ticker, days=7):
        """
        Fetch recent news articles for a specific stock ticker.
        
        Parameters
        ----------
        ticker : str
            Stock symbol (e.g., 'AAPL').
        
        days : int, optional
            Number of days back to fetch news.
            Default is 7 days.
        
        Returns
        -------
        list of dict or None
            List of news articles, each containing:
            - 'ticker': Stock symbol
            - 'headline': Article title
            - 'summary': Article summary/description
            - 'date': Publication date
            - 'sentiment': Sentiment score (-1 to 1)
            - 'url': Article URL
            - 'source': News source name
            Returns None if fetch fails.
        
        Behavior
        --------
        - Fetches news from Alpha Vantage News API
        - Filters articles from last N days
        - Extracts sentiment scores
        - Saves raw JSON to file
        - Stores parsed articles in database using insert_news method
        - Respects API rate limits
        """
        logger.info(f"📰 Fetching news for {ticker} (last {days} days)")
        
        try:
            # Enforce rate limit
            self._enforce_rate_limit()
            
            # Calculate time range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            # Format dates for API (YYYYMMDDTHHMM)
            time_from = start_date.strftime('%Y%m%dT0000')
            time_to = end_date.strftime('%Y%m%dT2359')
            
            # Build API request
            params = {
                'function': 'NEWS_SENTIMENT',
                'tickers': ticker,
                'time_from': time_from,
                'time_to': time_to,
                'limit': 200,  # Max results
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
            
            if 'feed' not in data or not data['feed']:
                logger.warning(f"⚠️ No news articles found for {ticker}")
                return []
            
            # Parse articles
            articles = self._parse_news_articles(data, ticker)
            
            logger.info(f"✅ Found {len(articles)} news articles for {ticker}")
            
            # Save raw JSON
            self._save_raw_json(ticker, data, f'news_{days}d')
            
            # Save to database
            if self.db and articles:
                self._save_news_to_db(articles)
            
            return articles
            
        except requests.exceptions.Timeout:
            logger.error(f"❌ API request timeout for {ticker}")
            return None
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ API request failed for {ticker}: {e}")
            return None
            
        except Exception as e:
            logger.error(f"❌ Unexpected error fetching news for {ticker}: {e}")
            return None
    
    def fetch_market_news(self, days=1):
        """
        Fetch general market news (not ticker-specific).
        
        Parameters
        ----------
        days : int, optional
            Number of days back to fetch news.
            Default is 1 day.
        
        Returns
        -------
        list of dict or None
            List of market news articles with same structure as fetch_news.
            Returns None if fetch fails.
        
        Behavior
        --------
        - Fetches broad market news
        - Uses 'MARKET' as ticker in database
        - Includes major indices and market trends
        - Extracts overall market sentiment
        - Useful for understanding market context
        """
        logger.info(f"📰 Fetching general market news (last {days} days)")
        
        try:
            # Enforce rate limit
            self._enforce_rate_limit()
            
            # Calculate time range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            # Format dates for API
            time_from = start_date.strftime('%Y%m%dT0000')
            time_to = end_date.strftime('%Y%m%dT2359')
            
            # Build API request (no specific ticker = general market news)
            params = {
                'function': 'NEWS_SENTIMENT',
                'topics': 'financial_markets',
                'time_from': time_from,
                'time_to': time_to,
                'limit': 50,
                'apikey': self.api_key
            }
            
            # Make API call
            response = requests.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            # Check for errors
            if 'Error Message' in data or 'Note' in data:
                logger.warning(f"⚠️ API issue fetching market news")
                return None
            
            if 'feed' not in data or not data['feed']:
                logger.warning(f"⚠️ No market news found")
                return []
            
            # Parse articles (use 'MARKET' as ticker)
            articles = self._parse_news_articles(data, 'MARKET')
            
            logger.info(f"✅ Found {len(articles)} market news articles")
            
            # Save raw JSON
            self._save_raw_json('MARKET', data, f'market_news_{days}d')
            
            # Save to database
            if self.db and articles:
                self._save_news_to_db(articles)
            
            return articles
            
        except Exception as e:
            logger.error(f"❌ Error fetching market news: {e}")
            return None
    
    def get_cached_news(self, ticker, days=7):
        """
        Retrieve news from database cache.
        
        Parameters
        ----------
        ticker : str
            Stock symbol or 'MARKET'.
        
        days : int, optional
            Number of days back to retrieve.
            Default is 7 days.
        
        Returns
        -------
        list or None
            Cached news articles.
        """
        if not self.db:
            logger.warning("⚠️ Database not connected. Cannot retrieve cached news.")
            return None
        
        try:
            rows = self.db.get_news(ticker, days=days)
            
            if not rows:
                logger.info(f"📭 No cached news for {ticker} (last {days} days)")
                return None
            
            logger.info(f"✅ Retrieved {len(rows)} cached news articles for {ticker}")
            return rows
            
        except Exception as e:
            logger.error(f"❌ Error retrieving cached news for {ticker}: {e}")
            return None
    
    def _parse_news_articles(self, news_data, ticker):
        """
        Internal method to parse raw news API response into structured format.
        
        Parameters
        ----------
        news_data : dict
            Raw JSON response from News API.
        
        ticker : str
            Stock symbol or 'MARKET' for general news.
        
        Returns
        -------
        list of dict
            Parsed news articles matching database schema:
            - ticker, headline, summary, date, sentiment
        
        Behavior
        --------
        - Extracts relevant fields from each article
        - Prioritizes ticker-specific sentiment over overall sentiment
        - Converts timestamps to YYYY-MM-DD format
        - Handles missing fields gracefully
        """
        articles = []
        
        for item in news_data.get('feed', []):
            try:
                # Extract basic info
                headline = item.get('title', '')
                summary = item.get('summary', '')
                url = item.get('url', '')
                source = item.get('source', '')
                
                # Parse date
                time_published = item.get('time_published', '')
                if time_published:
                    # Convert YYYYMMDDTHHMMSS to YYYY-MM-DD
                    date = datetime.strptime(time_published[:8], '%Y%m%d').strftime('%Y-%m-%d')
                else:
                    date = datetime.now().strftime('%Y-%m-%d')
                
                # Extract sentiment
                sentiment_score = 0.0
                
                # Try ticker-specific sentiment first
                if 'ticker_sentiment' in item and item['ticker_sentiment']:
                    for ts in item['ticker_sentiment']:
                        if ts.get('ticker', '').upper() == ticker.upper():
                            sentiment_score = float(ts.get('ticker_sentiment_score', 0.0))
                            break
                
                # Fall back to overall sentiment
                if sentiment_score == 0.0:
                    sentiment_score = float(item.get('overall_sentiment_score', 0.0))
                
                # Create article dictionary
                article = {
                    'ticker': ticker,
                    'headline': headline[:500],  # Limit length
                    'summary': summary[:1000],   # Limit length
                    'date': date,
                    'sentiment': round(sentiment_score, 3),
                    'url': url,
                    'source': source
                }
                
                articles.append(article)
                
            except Exception as e:
                logger.warning(f"⚠️ Failed to parse article: {e}")
                continue
        
        return articles
    
    def _save_news_to_db(self, articles):
        """
        Internal method to save parsed news articles to database.
        
        Parameters
        ----------
        articles : list of dict
            Parsed news articles with keys: ticker, headline, summary, date, sentiment.
        
        Behavior
        --------
        - Iterates through article list
        - Uses db.insert_news() for each article
        - Handles duplicates (INSERT OR IGNORE in database)
        - Logs success count
        """
        if not self.db:
            return
        
        try:
            saved_count = 0
            
            for article in articles:
                self.db.insert_news(
                    ticker=article['ticker'],
                    headline=article['headline'],
                    summary=article['summary'],
                    date=article['date'],
                    sentiment=article['sentiment']
                )
                saved_count += 1
            
            logger.info(f"💾 Saved {saved_count} news articles to database")
            
        except Exception as e:
            logger.error(f"❌ Failed to save news to database: {e}")
    
    def _save_raw_json(self, ticker, data, data_type):
        """
        Internal method to save raw news JSON to file.
        
        Parameters
        ----------
        ticker : str
            Stock symbol or 'MARKET'.
        
        data : dict
            Raw news data from API.
        
        data_type : str
            Description of news type (e.g., 'news_7d', 'market_news_1d').
        
        Behavior
        --------
        - Creates timestamped filename
        - Saves JSON with formatting
        - Logs save location
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
    
    def calculate_sentiment_summary(self, articles):
        """
        Calculate aggregate sentiment metrics from articles.
        
        Parameters
        ----------
        articles : list of dict
            News articles with 'sentiment' field.
        
        Returns
        -------
        dict
            Sentiment summary containing:
            - average_sentiment: Mean sentiment score
            - positive_count: Number of positive articles
            - negative_count: Number of negative articles
            - neutral_count: Number of neutral articles
            - total_articles: Total number of articles
        """
        if not articles:
            return {
                'average_sentiment': 0.0,
                'positive_count': 0,
                'negative_count': 0,
                'neutral_count': 0,
                'total_articles': 0
            }
        
        sentiments = [a['sentiment'] for a in articles if 'sentiment' in a]
        
        positive = sum(1 for s in sentiments if s > 0.1)
        negative = sum(1 for s in sentiments if s < -0.1)
        neutral = sum(1 for s in sentiments if -0.1 <= s <= 0.1)
        
        avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0.0
        
        return {
            'average_sentiment': round(avg_sentiment, 3),
            'positive_count': positive,
            'negative_count': negative,
            'neutral_count': neutral,
            'total_articles': len(articles)
        }


if __name__ == "__main__":
    """
    Test script for NewsDataFetcher
    """
    from data.database import Database
    from config import BaseConfig
    
    # Setup
    logger.info("="*60)
    logger.info("TESTING NEWS DATA FETCHER")
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
    fetcher = NewsDataFetcher(
        api_key=BaseConfig.ALPHA_VANTAGE_API_KEY,
        db=db
    )
    
    # Test 1: Fetch ticker-specific news
    logger.info("\n[TEST 1] Fetching news for AAPL (last 7 days)...")
    articles = fetcher.fetch_news('AAPL', days=7)
    if articles:
        logger.info(f"✅ Found {len(articles)} articles")
        
        # Show sentiment summary
        sentiment = fetcher.calculate_sentiment_summary(articles)
        logger.info(f"📊 Sentiment Summary:")
        logger.info(f"   Average: {sentiment['average_sentiment']:.3f}")
        logger.info(f"   Positive: {sentiment['positive_count']}")
        logger.info(f"   Negative: {sentiment['negative_count']}")
        logger.info(f"   Neutral: {sentiment['neutral_count']}")
        
        # Show first article
        if articles:
            logger.info(f"\n📰 Sample Article:")
            logger.info(f"   Headline: {articles[0]['headline']}")
            logger.info(f"   Sentiment: {articles[0]['sentiment']:.3f}")
            logger.info(f"   Date: {articles[0]['date']}")
    
    # Test 2: Fetch market news
    logger.info("\n[TEST 2] Fetching general market news...")
    market_articles = fetcher.fetch_market_news(days=1)
    if market_articles:
        logger.info(f"✅ Found {len(market_articles)} market news articles")
    
    # Test 3: Check cached news
    logger.info("\n[TEST 3] Checking cached news...")
    cached = fetcher.get_cached_news('AAPL', days=7)
    if cached:
        logger.info(f"✅ Found {len(cached)} cached news articles")
    
    # Cleanup
    db.close()
    logger.info("\n✅ ALL TESTS COMPLETED!")