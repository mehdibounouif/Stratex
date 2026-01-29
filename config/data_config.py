class DataConfig:
    # Data source
    DEFAULT_DATA_SOURCE = 'yfinance'
    # Update time
    DATA_UPDATE_TIME = '16:30'
    # Historical data
    DEFUALT_HISTORY_DAYS = 365
    # Alpha vantage rate limits per minite
    ALPHA_VANTAGE_CALLS_PER_MINUTE = 5
    # Alpha vantage rate limits per day
    ALPHA_VANTAGE_CALLS_PER_DAY = 25
    # Data quality
    MAX_MISSING_DATA = 0.05

