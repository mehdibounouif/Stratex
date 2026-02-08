"""
Professional Unit Tests for Database Class
Install: pip install pytest --break-system-packages
Run: pytest test_database_pytest.py -v
"""

import pytest
import sqlite3
import os
from datetime import datetime, timedelta
from data.database import Database  # Assuming your file is database.py


@pytest.fixture
def db():
    """Create a test database instance for each test"""
    test_db_path = "test_database.db"
    
    # Remove existing test database
    if os.path.exists(test_db_path):
        os.remove(test_db_path)
    
    # Create and connect
    database = Database(db_path=test_db_path)
    database.connect()
    database.create_tables()
    
    yield database  # Provide to test
    
    # Cleanup after test
    database.close()
    if os.path.exists(test_db_path):
        os.remove(test_db_path)


class TestDatabaseConnection:
    """Test connection and initialization"""
    
    def test_connection_success(self, db):
        """Test successful database connection"""
        assert db.conn is not None
        assert db.cursor is not None
    
    def test_ensure_connected_raises_error(self):
        """Test that ensure_connected raises error when not connected"""
        db = Database(db_path="temp.db")
        with pytest.raises(RuntimeError):
            db.ensure_connected()
    
    def test_close_connection(self, db):
        """Test closing connection"""
        db.close()
        assert db.conn is None
        assert db.cursor is None


class TestTableOperations:
    """Test table creation and management"""
    
    def test_create_tables(self, db):
        """Test that all tables are created"""
        db.check_if_the_table_exist("stock_prices")
        db.check_if_the_table_exist("fundamentals")
        db.check_if_the_table_exist("news")
        
        # Verify by querying sqlite_master
        db.cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in db.cursor.fetchall()]
        assert "stock_prices" in tables
        assert "fundamentals" in tables
        assert "news" in tables
    
    def test_drop_table(self, db):
        """Test dropping a table"""
        db.drop_table("news")
        db.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='news'")
        assert db.cursor.fetchone() is None
    
    def test_drop_nonexistent_table(self, db):
        """Test dropping a table that doesn't exist (should not error)"""
        db.drop_table("nonexistent_table")  # Should handle gracefully


class TestStockPrices:
    """Test stock price operations"""
    
    def test_insert_stock_price(self, db):
        """Test inserting stock price"""
        db.insert_stock_prices("AAPL", "2026-02-01", 150.0, 155.0, 148.0, 154.0, 1000000)
        
        rows = db.get_stock_prices("AAPL")
        assert len(rows) == 1
        assert rows[0][1] == "AAPL"  # ticker
        assert rows[0][6] == 154.0   # close price
    
    def test_insert_duplicate_ignored(self, db):
        """Test that duplicate inserts are ignored"""
        db.insert_stock_prices("AAPL", "2026-02-01", 150.0, 155.0, 148.0, 154.0, 1000000)
        db.insert_stock_prices("AAPL", "2026-02-01", 999.0, 999.0, 999.0, 999.0, 999999)
        
        rows = db.get_stock_prices("AAPL")
        assert len(rows) == 1
        assert rows[0][6] == 154.0  # Should keep first insert, not 999.0
    
    def test_get_stock_prices_with_date_range(self, db):
        """Test retrieving stock prices with date filtering"""
        db.insert_stock_prices("AAPL", "2026-02-01", 150.0, 155.0, 148.0, 154.0, 1000000)
        db.insert_stock_prices("AAPL", "2026-02-02", 154.0, 158.0, 153.0, 157.0, 1200000)
        db.insert_stock_prices("AAPL", "2026-02-03", 157.0, 160.0, 156.0, 159.0, 1300000)
        
        # Test with start date only
        rows = db.get_stock_prices("AAPL", start_date="2026-02-02")
        assert len(rows) == 2
        
        # Test with end date only
        rows = db.get_stock_prices("AAPL", end_date="2026-02-02")
        assert len(rows) == 2
        
        # Test with both dates
        rows = db.get_stock_prices("AAPL", start_date="2026-02-02", end_date="2026-02-02")
        assert len(rows) == 1
    
    def test_get_stock_prices_empty(self, db):
        """Test retrieving stock prices for non-existent ticker"""
        rows = db.get_stock_prices("NONEXISTENT")
        assert len(rows) == 0
    
    def test_delete_stock_data(self, db):
        """Test deleting stock data for a ticker"""
        db.insert_stock_prices("AAPL", "2026-02-01", 150.0, 155.0, 148.0, 154.0, 1000000)
        db.insert_stock_prices("AAPL", "2026-02-02", 154.0, 158.0, 153.0, 157.0, 1200000)
        
        db.delete_data_from_table("stock_prices", "AAPL")
        rows = db.get_stock_prices("AAPL")
        assert len(rows) == 0


class TestFundamentals:
    """Test fundamental data operations"""
    
    def test_insert_fundamental(self, db):
        """Test inserting fundamental data"""
        db.insert_fundamental("AAPL", "2026-Q1", 95000000000, 25000000000, 1.52, 28.5)
        
        rows = db.get_fundamentals("AAPL")
        assert len(rows) == 1
        assert rows[0][1] == "AAPL"
        assert rows[0][5] == 1.52  # eps
    
    def test_get_fundamentals_multiple(self, db):
        """Test retrieving multiple fundamental records"""
        db.insert_fundamental("AAPL", "2026-Q1", 95000000000, 25000000000, 1.52, 28.5)
        db.insert_fundamental("AAPL", "2026-Q2", 98000000000, 26000000000, 1.58, 29.0)
        
        rows = db.get_fundamentals("AAPL")
        assert len(rows) == 2


class TestNews:
    """Test news operations"""
    
    def test_insert_news(self, db):
        """Test inserting news"""
        db.insert_news("AAPL", "Big News", "This is important", "2026-02-08", 0.85)
        
        rows = db.get_news("AAPL", days=7)
        assert len(rows) == 1
        assert rows[0][1] == "AAPL"
        assert rows[0][2] == "Big News"
        assert rows[0][5] == 0.85  # sentiment
    
    def test_get_news_date_filtering(self, db):
        """Test news date filtering"""
        # Insert news from today
        today = datetime.today().strftime("%Y-%m-%d")
        db.insert_news("AAPL", "Recent News", "Summary", today, 0.8)
        
        # Insert news from 10 days ago
        old_date = (datetime.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        db.insert_news("AAPL", "Old News", "Summary", old_date, 0.7)
        
        # Should only get recent news (within 7 days)
        rows = db.get_news("AAPL", days=7)
        assert len(rows) == 1
        assert rows[0][2] == "Recent News"
        
        # With 14 days, should get both
        rows = db.get_news("AAPL", days=14)
        assert len(rows) == 2


class TestDataIntegrity:
    """Test data integrity and edge cases"""
    
    def test_multiple_tickers(self, db):
        """Test handling multiple tickers"""
        db.insert_stock_prices("AAPL", "2026-02-01", 150.0, 155.0, 148.0, 154.0, 1000000)
        db.insert_stock_prices("GOOGL", "2026-02-01", 2800.0, 2850.0, 2790.0, 2840.0, 500000)
        db.insert_stock_prices("MSFT", "2026-02-01", 380.0, 385.0, 378.0, 383.0, 800000)
        
        assert len(db.get_stock_prices("AAPL")) == 1
        assert len(db.get_stock_prices("GOOGL")) == 1
        assert len(db.get_stock_prices("MSFT")) == 1
    
    def test_special_characters_in_data(self, db):
        """Test handling special characters"""
        db.insert_news("AAPL", 
                      "Apple's \"Revolutionary\" Product", 
                      "Company says it's 'game-changing'", 
                      "2026-02-08", 
                      0.9)
        
        rows = db.get_news("AAPL")
        assert len(rows) == 1


# Run tests with: pytest test_database_pytest.py -v
# Run with coverage: pytest test_database_pytest.py --cov=database --cov-report=html