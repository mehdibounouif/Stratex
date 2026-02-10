import logging
import os
from logging.handlers import RotatingFileHandler
from config import BaseConfig

def setup_logging():
    """
    Configure comprehensive logging system with multiple log files.
    
    Creates:
    - system.log: All application logs (DEBUG/INFO level based on config)
    - trades.log: Trading operations only (INFO level)
    - errors.log: Errors only (ERROR level)
    - data_fetch.log: Data fetching operations (INFO level)
    
    Features:
    - Automatic log rotation (10MB per file, 5 backups)
    - Silences noisy third-party libraries
    - Creates log directory if it doesn't exist
    """
    
    # Ensure log directory exists
    os.makedirs(BaseConfig.LOG_DIR, exist_ok=True)
    
    # Convert string level to logging constant
    log_level = getattr(logging, BaseConfig.LOG_LEVEL)
    
    # Define log format
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # ===== CONFIGURE ROOT LOGGER =====
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()  # Remove any existing handlers
    
    # Console Handler (prints to terminal)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(console_handler)
    
    # System Log (everything)
    system_handler = RotatingFileHandler(
        BaseConfig.SYSTEM_LOG,
        maxBytes=BaseConfig.LOG_MAX_BYTES,
        backupCount=BaseConfig.LOG_BACKUP_COUNT
    )
    system_handler.setLevel(log_level)
    system_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(system_handler)
    
    # ===== CONFIGURE SPECIALIZED LOGGERS =====
    
    # Trading Logger (trades only)
    trading_logger = logging.getLogger('system')
    trading_handler = RotatingFileHandler(
        BaseConfig.TRADE_LOG,
        maxBytes=BaseConfig.LOG_MAX_BYTES,
        backupCount=BaseConfig.LOG_BACKUP_COUNT
    )
    trading_handler.setLevel(logging.INFO)
    trading_handler.setFormatter(detailed_formatter)
    trading_logger.addHandler(trading_handler)
    
    # Error Logger (errors only)
    error_handler = RotatingFileHandler(
        BaseConfig.ERROR_LOG,
        maxBytes=BaseConfig.LOG_MAX_BYTES,
        backupCount=BaseConfig.LOG_BACKUP_COUNT
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(error_handler)
    
    # Data Fetching Logger
    data_logger = logging.getLogger('data')
    data_handler = RotatingFileHandler(
        BaseConfig.DATA_LOG,
        maxBytes=BaseConfig.LOG_MAX_BYTES,
        backupCount=BaseConfig.LOG_BACKUP_COUNT
    )
    data_handler.setLevel(logging.INFO)
    data_handler.setFormatter(detailed_formatter)
    data_logger.addHandler(data_handler)
    
    # ===== SILENCE NOISY THIRD-PARTY LIBRARIES =====
    yf_level = getattr(logging, BaseConfig.YFINANCE_LOG_LEVEL)
    req_level = getattr(logging, BaseConfig.REQUESTS_LOG_LEVEL)
    
    logging.getLogger('yfinance').setLevel(yf_level)
    logging.getLogger('peewee').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(req_level)
    logging.getLogger('requests').setLevel(req_level)
    
    # ===== LOG INITIALIZATION COMPLETE =====
    logging.info("=" * 60)
    logging.info(f"Logging system initialized")
    logging.info(f"Environment: {BaseConfig.ENVIRONMENT}")
    logging.info(f"Log Level: {BaseConfig.LOG_LEVEL}")
    logging.info(f"System Log: {BaseConfig.SYSTEM_LOG}")
    logging.info(f"Trade Log: {BaseConfig.TRADE_LOG}")
    logging.info(f"Error Log: {BaseConfig.ERROR_LOG}")
    logging.info(f"Data Log: {BaseConfig.DATA_LOG}")
    logging.info("=" * 60)


def get_logger(name):
    """
    Get a logger instance for a specific module.
    
    Parameters
    ----------
    name : str
        Usually __name__ to get the module name.
        Use specific names for specialized logging:
        - 'trading' for trade execution logs
        - 'data' for data fetching logs
        - Anything else for general application logs
    
    Returns
    -------
    logging.Logger
        Logger instance for this module
    
    Usage Examples
    --------------
    # In data fetcher
    logger = get_logger('data.stock_fetcher')
    logger.info("Fetching AAPL data")  # Goes to system.log AND data_fetch.log
    
    # In trading module
    logger = get_logger('trading.executor')
    logger.info("Executed BUY order")  # Goes to system.log AND trades.log
    
    # In any other module
    logger = get_logger(__name__)
    logger.info("Regular log message")  # Goes to system.log only
    logger.error("Something broke!")    # Goes to system.log AND errors.log
    """
    return logging.getLogger(name)

#| Level    | Method              | Meaning                               |
#| -------- | ------------------- | ------------------------------------- |
#| DEBUG    | `logger.debug()`    | Detailed internal info                |
#| INFO     | `logger.info()`     | Normal app events                     |
#| WARNING  | `logger.warning()`  | Something unexpected but not breaking |
#| ERROR    | `logger.error()`    | A failure occurred                    |
#| CRITICAL | `logger.critical()` | System is unusable / may crash        |

#DEBUG     → Developer details
#INFO      → Normal events
#WARNING   → Suspicious but ok
#ERROR     → Operation failed
#CRITICAL  → System failure
