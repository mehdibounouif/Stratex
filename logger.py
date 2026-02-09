import logging
import os
from config import BaseConfig

def setup_logging():
    """
    Configure logging based on BaseConfig settings.
    
    Behavior
    --------
    - Reads LOG_LEVEL from config (DEBUG or INFO)
    - Logs to both console and file
    - File location: system.log (from config)
    - Format includes timestamp, level, module name, and message
    """
    
    # Ensure log directory exists
    log_dir = os.path.dirname(BaseConfig.LOG_FILE)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Convert string level to logging constant
    log_level = getattr(logging, BaseConfig.LOG_LEVEL)
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers (if any)
    root_logger.handlers.clear()
    
    # Console Handler (prints to terminal)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(console_handler)
    
    # File Handler (saves to file)
    file_handler = logging.FileHandler(BaseConfig.LOG_FILE)
    file_handler.setLevel(log_level)
    file_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(file_handler)
    
    logging.info(f"Logging initialized at {BaseConfig.LOG_LEVEL} level")
    logging.info(f"Log file: {BaseConfig.LOG_FILE}")

def get_logger(name):
    """
    Get a logger instance for a specific module.
    
    Parameters
    ----------
    name : str
        Usually __name__ to get the module name
    
    Returns
    -------
    logging.Logger
        Logger instance for this module
    
    Usage
    -----
    logger = get_logger(__name__)
    logger.info("This is an info message")
    logger.debug("This is a debug message")
    logger.error("This is an error message")
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
