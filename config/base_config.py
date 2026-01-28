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
   
   LOG_LEVEL = 'DEBUG' if DEBUG else 'INFO'
   LOG_FILE = os.path.join(PROJECT_ROOT, 'system.log')
