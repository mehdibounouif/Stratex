"""
Data Pipeline Health Check
============================
Validates the entire data layer at startup and returns a structured report.

Checks are split into two severity tiers:

    CRITICAL  — system cannot trade without this
                 e.g. database unreachable, required directories missing,
                      stock fetcher broken

    DEGRADED  — system can still trade, but with reduced functionality
                 e.g. Alpha Vantage key missing (no fundamentals/news),
                      cache is stale, disk space low

USAGE
-----

Standalone (print report and exit):
    python -m data.health_check

In code (import and call):
    from data.health_check import run_health_check

    report = run_health_check()

    if report['status'] == 'CRITICAL':
        sys.exit("System cannot start — data pipeline unhealthy")
    elif report['status'] == 'DEGRADED':
        log.warning("System starting in degraded mode")

    # Full report dict always available:
    for check in report['checks']:
        print(check['name'], check['status'], check['detail'])

REPORT FORMAT
-------------
{
    'status':    'OK' | 'DEGRADED' | 'CRITICAL',
    'timestamp': str (ISO-8601),
    'checks': [
        {
            'name':     str,         # human-readable check name
            'status':   'OK' | 'WARN' | 'FAIL',
            'severity': 'CRITICAL' | 'DEGRADED',
            'detail':   str          # what was found / what failed
        },
        ...
    ],
    'summary': {
        'total': int,
        'ok':    int,
        'warn':  int,
        'fail':  int,
    }
}
"""

import os
import sys
import sqlite3
from datetime import datetime
from logger import get_logger

log = get_logger('data.health_check')


# ── Individual check functions ────────────────────────────────────
# Each returns (status, detail) where status is 'OK', 'WARN', or 'FAIL'.

def _check_directories() -> tuple:
    """All required data directories must exist and be writable."""
    required = ['data', 'data/raw', 'data/processed', 'logs']
    missing  = []
    unwritable = []

    for d in required:
        if not os.path.isdir(d):
            missing.append(d)
        elif not os.access(d, os.W_OK):
            unwritable.append(d)

    if missing:
        return 'FAIL', f"Missing directories: {missing}"
    if unwritable:
        return 'FAIL', f"Directories not writable: {unwritable}"
    return 'OK', f"All {len(required)} required directories exist and writable"


def _check_database() -> tuple:
    """SQLite database must be connectable and have all 3 required tables."""
    try:
        from config import BaseConfig
        db_path = BaseConfig.DATABASE_URL.replace('sqlite:///', '')
    except Exception as e:
        return 'FAIL', f"Cannot read DATABASE_URL from config: {e}"

    if not os.path.isfile(db_path):
        return 'WARN', f"Database file does not exist yet: {db_path} (will be created on first run)"

    try:
        conn   = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}

        required_tables = {'stock_prices', 'fundamentals', 'news'}
        missing = required_tables - tables

        # Check row counts so we know if cache has any data
        counts = {}
        for table in (required_tables & tables):
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = cursor.fetchone()[0]

        conn.close()

        if missing:
            return 'WARN', (
                f"Database connected but missing tables: {missing}. "
                f"Will be created on first run."
            )

        count_str = ', '.join(f"{t}={c}" for t, c in counts.items())
        return 'OK', f"Database OK — tables present, rows: {count_str}"

    except sqlite3.Error as e:
        return 'FAIL', f"Database connection failed: {e}"


def _check_stock_fetcher() -> tuple:
    """yfinance must be importable — the core data source."""
    try:
        import yfinance as yf
        version = getattr(yf, '__version__', 'unknown')
        return 'OK', f"yfinance {version} available"
    except ImportError as e:
        return 'FAIL', f"yfinance not installed: {e}. Run: pip install yfinance"


def _check_pandas() -> tuple:
    """pandas must be importable — used everywhere."""
    try:
        import pandas as pd
        return 'OK', f"pandas {pd.__version__} available"
    except ImportError as e:
        return 'FAIL', f"pandas not installed: {e}"


def _check_alpha_vantage_key() -> tuple:
    """Alpha Vantage key enables fundamentals and news (optional)."""
    try:
        from config import BaseConfig
        key = BaseConfig.ALPHA_VANTAGE_API_KEY
        if not key or key in ('', 'your_alpha_vantage_key_here'):
            return 'WARN', (
                "ALPHA_VANTAGE_API_KEY not set in .env — "
                "fundamentals and news data unavailable. "
                "Trading will work but only with price/RSI/momentum signals."
            )
        # Mask key in logs: show first 4 chars only
        masked = key[:4] + '****'
        return 'OK', f"Alpha Vantage key configured ({masked})"
    except Exception as e:
        return 'WARN', f"Could not read Alpha Vantage key: {e}"


def _check_env_file() -> tuple:
    """.env file should exist in the project root."""
    if os.path.isfile('.env'):
        return 'OK', ".env file found"
    return 'WARN', (
        ".env file not found in project root. "
        "API keys and settings should be defined there. "
        "Copy .env.example to .env and fill in your values."
    )


def _check_cache_freshness() -> tuple:
    """
    Check whether the price cache has any data and how stale it is.
    A completely empty cache is fine on first run, just flagged as WARN
    so the team knows the first daily run will be slow (fetching all tickers).
    """
    try:
        from config import BaseConfig
        db_path = BaseConfig.DATABASE_URL.replace('sqlite:///', '')

        if not os.path.isfile(db_path):
            return 'WARN', "No database yet — first run will fetch all tickers fresh"

        conn   = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_prices'"
        )
        if not cursor.fetchone():
            conn.close()
            return 'WARN', "stock_prices table missing — will be created on first run"

        cursor.execute("SELECT COUNT(*), MAX(date) FROM stock_prices")
        row = cursor.fetchone()
        conn.close()

        count    = row[0] or 0
        max_date = row[1]

        if count == 0:
            return 'WARN', "Price cache is empty — first run will fetch all tickers (slow)"

        # How old is the most recent record?
        latest    = datetime.strptime(max_date, '%Y-%m-%d')
        age_days  = (datetime.now() - latest).days

        if age_days == 0:
            return 'OK', f"Cache fresh — {count:,} records, latest: {max_date}"
        elif age_days <= 3:
            return 'OK', f"Cache {age_days}d old — {count:,} records, latest: {max_date}"
        elif age_days <= 7:
            return 'WARN', (
                f"Cache is {age_days} days old — consider running a refresh. "
                f"{count:,} records, latest: {max_date}"
            )
        else:
            return 'WARN', (
                f"Cache is {age_days} days old — stale data may affect signal quality. "
                f"{count:,} records, latest: {max_date}"
            )

    except Exception as e:
        return 'WARN', f"Could not check cache freshness: {e}"


def _check_disk_space() -> tuple:
    """Warn if less than 500 MB free — SQLite and CSV files grow over time."""
    try:
        stat  = os.statvfs('.')
        free  = stat.f_bavail * stat.f_frsize
        free_mb = free / (1024 * 1024)

        if free_mb < 100:
            return 'FAIL', f"Critically low disk space: {free_mb:.0f} MB free"
        elif free_mb < 500:
            return 'WARN', f"Low disk space: {free_mb:.0f} MB free (recommend > 500 MB)"
        return 'OK', f"{free_mb:.0f} MB free"

    except AttributeError:
        # os.statvfs not available on Windows
        return 'OK', "Disk space check skipped (Windows)"
    except Exception as e:
        return 'WARN', f"Could not check disk space: {e}"


# ── Check registry ────────────────────────────────────────────────
# (check_fn, display_name, severity)
_CHECKS = [
    (_check_directories,        "Directories",            'CRITICAL'),
    (_check_database,           "Database",               'CRITICAL'),
    (_check_stock_fetcher,      "Stock fetcher (yfinance)",'CRITICAL'),
    (_check_pandas,             "pandas",                 'CRITICAL'),
    (_check_env_file,           ".env file",              'DEGRADED'),
    (_check_alpha_vantage_key,  "Alpha Vantage key",      'DEGRADED'),
    (_check_cache_freshness,    "Price cache freshness",  'DEGRADED'),
    (_check_disk_space,         "Disk space",             'DEGRADED'),
]


# ── Public API ────────────────────────────────────────────────────

def run_health_check(silent: bool = False) -> dict:
    """
    Run all health checks and return a structured report.

    Parameters
    ----------
    silent : bool
        If True, suppress log output (useful in tests). Default False.

    Returns
    -------
    dict  See module docstring for full format.
    """
    results = []

    for fn, name, severity in _CHECKS:
        try:
            status, detail = fn()
        except Exception as e:
            status = 'FAIL'
            detail = f"Check raised unexpected error: {e}"

        results.append({
            'name':     name,
            'status':   status,
            'severity': severity,
            'detail':   detail,
        })

    # ── Determine overall status ──────────────────────────────
    critical_fail = any(
        r['status'] == 'FAIL' and r['severity'] == 'CRITICAL'
        for r in results
    )
    any_fail = any(r['status'] == 'FAIL' for r in results)
    any_warn = any(r['status'] == 'WARN' for r in results)

    if critical_fail:
        overall = 'CRITICAL'
    elif any_fail or any_warn:
        overall = 'DEGRADED'
    else:
        overall = 'OK'

    ok_count   = sum(1 for r in results if r['status'] == 'OK')
    warn_count = sum(1 for r in results if r['status'] == 'WARN')
    fail_count = sum(1 for r in results if r['status'] == 'FAIL')

    report = {
        'status':    overall,
        'timestamp': datetime.now().isoformat(),
        'checks':    results,
        'summary':   {
            'total': len(results),
            'ok':    ok_count,
            'warn':  warn_count,
            'fail':  fail_count,
        }
    }

    if not silent:
        _print_report(report)

    return report


def _print_report(report: dict) -> None:
    """Print a human-readable health check report to the log."""
    status  = report['status']
    emoji   = {'OK': '✅', 'DEGRADED': '⚠️ ', 'CRITICAL': '❌'}.get(status, '?')
    summary = report['summary']

    log.info("=" * 60)
    log.info(f"  DATA PIPELINE HEALTH CHECK  {emoji} {status}")
    log.info("=" * 60)

    for r in report['checks']:
        icon = {'OK': '✅', 'WARN': '⚠️ ', 'FAIL': '❌'}.get(r['status'], '?')
        log.info(f"  {icon}  [{r['severity'][:4]}]  {r['name']}")
        if r['status'] != 'OK':
            log.info(f"         → {r['detail']}")

    log.info("-" * 60)
    log.info(
        f"  Result: {summary['ok']} OK  |  "
        f"{summary['warn']} WARN  |  "
        f"{summary['fail']} FAIL"
    )
    log.info("=" * 60)

    if status == 'CRITICAL':
        log.error(
            "CRITICAL: System cannot trade. Fix the FAIL checks above before starting."
        )
    elif status == 'DEGRADED':
        log.warning(
            "DEGRADED: System can trade but some features are unavailable. "
            "Review WARN/FAIL checks above."
        )
    else:
        log.info("All checks passed. System ready to trade.")


# ── Standalone entry point ────────────────────────────────────────

if __name__ == '__main__':
    report = run_health_check()
    sys.exit(0 if report['status'] != 'CRITICAL' else 1)