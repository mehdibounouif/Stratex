"""
Exponential Backoff Retry Utility
===================================
Provides a clean, reusable retry mechanism for all external API calls
in the data pipeline (yfinance, Alpha Vantage).

WHY EXPONENTIAL BACKOFF?
------------------------
External APIs fail in bursts. A rate-limited yfinance call will still be
rate-limited 1 second later. Waiting 2s, then 4s, then 8s gives the API
time to recover and dramatically reduces total failures vs. a fixed delay.

USAGE
-----

1. As a decorator on any function:

    from data.retry import retry

    @retry(max_attempts=3, base_delay=2.0, exceptions=(Exception,))
    def fetch_something():
        return yf.download(...)

2. As a one-off call with a callable:

    from data.retry import fetch_with_retry

    df = fetch_with_retry(
        fn=lambda: yf.download('AAPL', ...),
        label='AAPL price fetch',
        max_attempts=3,
        base_delay=2.0,
    )

RETRY SCHEDULE (base_delay=2.0, jitter=True)
---------------------------------------------
Attempt 1 → immediate
Attempt 2 → ~2s wait  (2^1 = 2, ± jitter)
Attempt 3 → ~4s wait  (2^2 = 4, ± jitter)
Attempt 4 → ~8s wait  (2^3 = 8, ± jitter) — if max_attempts=4
Max wait is capped at max_delay (default 60s).

JITTER
------
A small random offset (±25% of the calculated delay) is added to each
wait. This prevents multiple concurrent callers from synchronizing their
retries and hammering the API at the same moment (thundering herd problem).
"""

import time
import random
import functools
from logger import get_logger, setup_logging

setup_logging()
log = get_logger('data.retry')


# ── Default values ────────────────────────────────────────────────
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_DELAY   = 2.0    # seconds before first retry
DEFAULT_MAX_DELAY    = 60.0   # never wait longer than this
DEFAULT_EXCEPTIONS   = (Exception,)


def _calc_delay(attempt: int, base_delay: float, max_delay: float,
                jitter: bool) -> float:
    """
    Calculate how long to wait before retry `attempt`.

    Parameters
    ----------
    attempt    : int    1-based retry number (1 = first retry after failure)
    base_delay : float  base wait in seconds
    max_delay  : float  upper cap in seconds
    jitter     : bool   add ±25% random offset

    Returns
    -------
    float  seconds to sleep
    """
    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
    if jitter:
        delay *= (0.75 + random.random() * 0.5)   # ×0.75 to ×1.25
    return round(delay, 2)


def retry(max_attempts: int = DEFAULT_MAX_ATTEMPTS,
          base_delay:   float = DEFAULT_BASE_DELAY,
          max_delay:    float = DEFAULT_MAX_DELAY,
          exceptions:   tuple = DEFAULT_EXCEPTIONS,
          jitter:       bool  = True):
    """
    Decorator: retry the wrapped function with exponential backoff.

    Parameters
    ----------
    max_attempts : int    Total attempts (including the first). Default 3.
    base_delay   : float  Seconds before first retry. Default 2.0.
    max_delay    : float  Maximum wait between retries. Default 60.0.
    exceptions   : tuple  Exception types to catch. Default (Exception,).
    jitter       : bool   Add randomness to delays. Default True.

    Returns
    -------
    Decorated function that returns the wrapped function's return value,
    or None if all attempts fail.

    Example
    -------
    @retry(max_attempts=3, base_delay=2.0)
    def fetch_prices(ticker):
        return yf.download(ticker, ...)
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            label = fn.__qualname__
            last_exc = None

            for attempt in range(1, max_attempts + 1):
                try:
                    result = fn(*args, **kwargs)
                    if attempt > 1:
                        log.info(f"   ✅ {label} succeeded on attempt {attempt}")
                    return result

                except exceptions as e:
                    last_exc = e
                    if attempt < max_attempts:
                        wait = _calc_delay(attempt, base_delay, max_delay, jitter)
                        log.warning(
                            f"   ⚠️  {label} attempt {attempt}/{max_attempts} failed: {e}"
                            f" — retrying in {wait:.1f}s"
                        )
                        time.sleep(wait)
                    else:
                        log.error(
                            f"   ❌ {label} failed after {max_attempts} attempts. "
                            f"Last error: {e}"
                        )

            return None   # all attempts exhausted

        return wrapper
    return decorator


def fetch_with_retry(fn,
                     label:        str   = 'fetch',
                     max_attempts: int   = DEFAULT_MAX_ATTEMPTS,
                     base_delay:   float = DEFAULT_BASE_DELAY,
                     max_delay:    float = DEFAULT_MAX_DELAY,
                     exceptions:   tuple = DEFAULT_EXCEPTIONS,
                     jitter:       bool  = True):
    """
    Call a zero-argument callable with exponential backoff.

    Use this when you cannot use the decorator (e.g., inline lambdas).

    Parameters
    ----------
    fn           : callable  Zero-argument function to call, e.g. lambda: yf.download(...)
    label        : str       Human-readable name for log messages
    max_attempts : int
    base_delay   : float
    max_delay    : float
    exceptions   : tuple
    jitter       : bool

    Returns
    -------
    The return value of fn(), or None if all attempts fail.

    Example
    -------
    df = fetch_with_retry(
        fn=lambda: yf.download('AAPL', start='2025-01-01'),
        label='AAPL price download',
        max_attempts=3,
    )
    """
    last_exc = None

    for attempt in range(1, max_attempts + 1):
        try:
            result = fn()
            if attempt > 1:
                log.info(f"   ✅ {label} succeeded on attempt {attempt}")
            return result

        except exceptions as e:
            last_exc = e
            if attempt < max_attempts:
                wait = _calc_delay(attempt, base_delay, max_delay, jitter)
                log.warning(
                    f"   ⚠️  {label} attempt {attempt}/{max_attempts} failed: {e}"
                    f" — retrying in {wait:.1f}s"
                )
                time.sleep(wait)
            else:
                log.error(
                    f"   ❌ {label} failed after {max_attempts} attempts. "
                    f"Last error: {last_exc}"
                )

    return None