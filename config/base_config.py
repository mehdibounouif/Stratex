import os
from dotenv import load_dotenv
load_dotenv()

class BaseConfig:
    ENVIRONMENT = os.getenv('ENVIRONMENT', 'development')
    DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    ALPHA_VANTAGE_API_KEY = os.getenv('ALPHA_VANTAGE_API_KEY')
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///data/trading_data.db')
   
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
    RAW_DATA_DIR = os.path.join(DATA_DIR, 'raw')
    PROCESSED_DATA_DIR = os.path.join(DATA_DIR, 'processed')
   
    # ===== LOGGING CONFIGURATION =====
    LOG_DIR = os.path.join(PROJECT_ROOT, 'logs')
    LOG_LEVEL = 'DEBUG' if DEBUG else 'INFO'
    
    # Different log files for different purposes
    SYSTEM_LOG = os.path.join(LOG_DIR, 'system.log')      # Main application log
    TRADE_LOG = os.path.join(LOG_DIR, 'trades.log')       # Trading activity only
    ERROR_LOG = os.path.join(LOG_DIR, 'errors.log')       # Errors only
    DATA_LOG = os.path.join(LOG_DIR, 'data_fetch.log')    # Data fetching operations
    STRATEGIES_LOG = os.path.join(LOG_DIR, 'strategies.log')    # strategies operations
    
    # Log rotation settings
    LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB per file
    LOG_BACKUP_COUNT = 5              # Keep 5 backup files
    
    # Third-party library log levels
    YFINANCE_LOG_LEVEL = os.getenv('YFINANCE_LOG_LEVEL', 'WARNING')
    REQUESTS_LOG_LEVEL = os.getenv('REQUESTS_LOG_LEVEL', 'WARNING')
   
    @classmethod
    def validate(cls):
        """Validate required environment variables and create necessary directories."""
        missing = []
 
        if not cls.OPENAI_API_KEY:
            missing.append('OPENAI_API_KEY')
 
        if not cls.ALPHA_VANTAGE_API_KEY:
            missing.append('ALPHA_VANTAGE_API_KEY')
 
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        
        # Create necessary directories
        for directory in [cls.DATA_DIR, cls.RAW_DATA_DIR, cls.PROCESSED_DATA_DIR, cls.LOG_DIR]:
            os.makedirs(directory, exist_ok=True)
        
        return True