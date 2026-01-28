import os
from dotenv import load_dotenv

load_dotenv()

class BaseConfig:
    ENVIRONMENT = os.getenv('ENVIRONMENT', 'development')
    DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'

    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    ALPHA_VANTAGE_API_KEY = os.getenv('ALPHA_VANTAGE_API_KEY')

    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///data/trading_data.db')
    
