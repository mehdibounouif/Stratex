# weekly_fundamentals.py
# =======================
# Runs once a week (Sunday night or Monday morning) to refresh
# fundamental data (P/E, EPS, revenue, debt, etc.) for every
# ticker in WATCHLIST.
#
# Why weekly and not daily?
#   - Alpha Vantage free tier: 25 requests/day, 5/minute.
#   - Fundamentals change quarterly -- daily refresh is wasteful.
#   - One weekly run fetches all tickers within the daily limit.
#
# Steps:
#   1. Connect     - database + fetchers
#   2. Fundamentals- fetch company overview (P/E, EPS, revenue ...)
#   3. Earnings    - fetch latest earnings per ticker
#   4. News        - fetch last 7 days of news + sentiment
#   5. Clean       - remove duplicate news, vacuum database
#   6. Report      - print what was fetched / skipped / failed
#
# Run:
#     python weekly_fundamentals.py
#
# Force re-fetch even if cache is fresh:
#     python weekly_fundamentals.py --force
#
# Cron (every Sunday at 8 PM):
#     0 20 * * 0 cd /Quant_Firm && venv/bin/python weekly_fundamentals.py >> logs/weekly.log 2>&1
#
# REQUIREMENTS:
#   - ALPHA_VANTAGE_API_KEY must be set in config.py (BaseConfig)
#   - Free tier: 25 requests/day max.
#     With 15 tickers x 3 calls each = 45 calls needed.
#     Split over 2 days if on free tier (7-8 tickers per day).
#     Premium tier handles all 15 in one run.

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from logger import setup_logging, get_logger
setup_logging()
log = get_logger("pipeline.weekly_fundamentals")


# CONFIGURATION
WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN",
    "JPM",  "BAC",  "GS",
    "JNJ",  "PFE",
    "XOM",  "CVX",
    "TSLA", "HD",
]

# Alpha Vantage free tier: 5 calls/min, 25 calls/day
# Set to 15 seconds to stay safely under 5/min (4/min = 60/4 = 15s)
API_DELAY_SECONDS = 15

# How many days old fundamentals can be before we re-fetch
FUNDAMENTALS_MAX_AGE_DAYS = 6   # re-fetch if older than 6 days

# How many days of news to fetch per ticker
NEWS_DAYS_BACK = 7

# Fetch earnings data in addition to overview? (costs 1 extra API call per ticker)
FETCH_EARNINGS = True

# Fetch news? (costs 1 extra API call per ticker)
FETCH_NEWS = True


def _banner(msg):
    log.info("=" * 60)
    log.info(f"  {msg}")
    log.info("=" * 60)

def _section(msg):
    log.info("")
    log.info("-" * 50)
    log.info(f"  {msg}")
    log.info("-" * 50)

def _api_key_configured(api_key):
    return api_key and api_key not in ("your_alpha_vantage_key_here", "", None)


# STEP 1 -- CONNECT
def connect():
    _section("STEP 1 -- Connecting")

    from data.database import Database
    from data.pipelines.data_cleaning import DataCleaner

    db = Database()
    db.connect()
    db.create_tables()
    log.info("  OK Database")

    cleaner = DataCleaner(db=db)
    log.info("  OK DataCleaner")

    # Check Alpha Vantage key
    try:
        from config import BaseConfig
        api_key = BaseConfig.ALPHA_VANTAGE_API_KEY
    except Exception:
        api_key = None

    if not _api_key_configured(api_key):
        log.error("  ERR ALPHA_VANTAGE_API_KEY not configured in config.py")
        log.error("      Get a free key at: https://www.alphavantage.co/support/#api-key")
        log.error("      Then set BaseConfig.ALPHA_VANTAGE_API_KEY = 'your_key'")
        return None

    log.info(f"  OK Alpha Vantage key: {api_key[:6]}...")

    from data.fundamental_fetcher import FundamentalDataFetcher
    fundamental_fetcher = FundamentalDataFetcher(api_key=api_key, db=db)
    log.info("  OK FundamentalDataFetcher")

    news_fetcher = None
    try:
        from data.news_fetcher import NewsDataFetcher
        news_fetcher = NewsDataFetcher(api_key=api_key, db=db)
        log.info("  OK NewsDataFetcher")
    except Exception as e:
        log.warning(f"  WARN NewsDataFetcher: {e}")

    return {
        "db":                  db,
        "cleaner":             cleaner,
        "fundamental_fetcher": fundamental_fetcher,
        "news_fetcher":        news_fetcher,
        "api_key":             api_key,
    }


# STEP 2 -- FUNDAMENTALS (company overview: P/E, EPS, revenue ...)
def fetch_fundamentals(ctx):
    _section(f"STEP 2 -- Fetching fundamentals ({len(WATCHLIST)} tickers)")

    ff      = ctx["fundamental_fetcher"]
    db      = ctx["db"]
    force   = "--force" in sys.argv
    results = {}

    for i, ticker in enumerate(WATCHLIST, 1):
        log.info(f"  [{i:02d}/{len(WATCHLIST)}] {ticker} ...")

        # Check if cache is fresh enough (skip API call if so)
        if not force:
            try:
                cached = ff.get_cached_fundamentals(ticker)
                if cached:
                    # cached is a list of DB rows; check the date of the most recent
                    # Row format: (id, ticker, date, revenue, net_income, eps, pe_ratio)
                    latest_row  = cached[0]
                    cached_date = datetime.strptime(str(latest_row[2]), "%Y-%m-%d")
                    age_days    = (datetime.now() - cached_date).days
                    if age_days <= FUNDAMENTALS_MAX_AGE_DAYS:
                        log.info(f"       SKIP cache is {age_days}d old (limit {FUNDAMENTALS_MAX_AGE_DAYS}d)")
                        results[ticker] = {"source": "cache", "data": cached}
                        continue
                    else:
                        log.info(f"       STALE cache is {age_days}d old -- re-fetching")
            except Exception:
                pass  # no cache or parse error -> fetch anyway

        # Fetch from API
        try:
            data = ff.fetch_fundamentals(ticker)
            if data:
                overview = data.get("overview", {})
                pe  = overview.get("PERatio", "N/A")
                eps = overview.get("EPS",     "N/A")
                rev = overview.get("RevenueTTM", "N/A")
                mc  = overview.get("MarketCapitalization", "N/A")
                log.info(f"       OK  P/E={pe}  EPS={eps}  Rev={rev}  MCap={mc}")
                results[ticker] = {"source": "api", "data": data}
            else:
                log.warning(f"       WARN No data returned")
                results[ticker] = None
        except Exception as e:
            log.error(f"       ERR {e}")
            results[ticker] = None

        if i < len(WATCHLIST):
            log.info(f"       waiting {API_DELAY_SECONDS}s (rate limit) ...")
            time.sleep(API_DELAY_SECONDS)

    ok     = sum(1 for v in results.values() if v is not None)
    failed = [t for t, v in results.items() if v is None]
    log.info(f"  Result: {ok} OK | {len(failed)} failed: {failed or 'none'}")
    ctx["fundamental_results"] = results
    return results


# STEP 3 -- EARNINGS (latest EPS vs estimate)
def fetch_earnings(ctx):
    _section(f"STEP 3 -- Fetching earnings ({len(WATCHLIST)} tickers)")

    if not FETCH_EARNINGS:
        log.info("  INFO FETCH_EARNINGS=False -- skipping")
        return {}

    ff      = ctx["fundamental_fetcher"]
    results = {}

    for i, ticker in enumerate(WATCHLIST, 1):
        log.info(f"  [{i:02d}/{len(WATCHLIST)}] {ticker} ...")
        try:
            data = ff.fetch_earnings(ticker)
            if data:
                earnings_data = data.get("earnings", {})
                # Show most recent quarterly EPS
                quarterly = earnings_data.get("quarterlyEarnings", [])
                if quarterly:
                    latest = quarterly[0]
                    reported = latest.get("reportedEPS", "N/A")
                    estimate = latest.get("estimatedEPS", "N/A")
                    surprise = latest.get("surprisePercentage", "N/A")
                    period   = latest.get("fiscalDateEnding", "N/A")
                    log.info(f"       OK  {period}: reported={reported}  est={estimate}  surprise={surprise}%")
                results[ticker] = data
            else:
                log.warning(f"       WARN No earnings data")
                results[ticker] = None
        except Exception as e:
            log.error(f"       ERR {e}")
            results[ticker] = None

        if i < len(WATCHLIST):
            log.info(f"       waiting {API_DELAY_SECONDS}s ...")
            time.sleep(API_DELAY_SECONDS)

    ok     = sum(1 for v in results.values() if v is not None)
    failed = [t for t, v in results.items() if v is None]
    log.info(f"  Result: {ok} OK | {len(failed)} failed: {failed or 'none'}")
    ctx["earnings_results"] = results
    return results


# STEP 4 -- NEWS + SENTIMENT
def fetch_news(ctx):
    _section(f"STEP 4 -- Fetching news ({len(WATCHLIST)} tickers, last {NEWS_DAYS_BACK} days)")

    if not FETCH_NEWS:
        log.info("  INFO FETCH_NEWS=False -- skipping")
        return {}

    nf = ctx.get("news_fetcher")
    if not nf:
        log.info("  INFO NewsDataFetcher not available -- skipping")
        return {}

    results = {}

    for i, ticker in enumerate(WATCHLIST, 1):
        log.info(f"  [{i:02d}/{len(WATCHLIST)}] {ticker} ...")
        try:
            # Check cache first
            cached = nf.get_cached_news(ticker, days=NEWS_DAYS_BACK)
            if cached and "--force" not in sys.argv:
                log.info(f"       SKIP {len(cached)} articles in cache")
                results[ticker] = cached
            else:
                articles = nf.fetch_news(ticker, days=NEWS_DAYS_BACK)
                if articles:
                    sentiment = nf.calculate_sentiment_summary(articles)
                    avg = sentiment["average_sentiment"]
                    pos = sentiment["positive_count"]
                    neg = sentiment["negative_count"]
                    total = sentiment["total_articles"]
                    mood  = "BULLISH" if avg > 0.1 else ("BEARISH" if avg < -0.1 else "NEUTRAL")
                    log.info(f"       OK  {total} articles | avg={avg:+.3f} ({mood}) | +{pos}/-{neg}")
                    results[ticker] = articles
                else:
                    log.warning(f"       WARN No articles found")
                    results[ticker] = []
        except Exception as e:
            log.error(f"       ERR {e}")
            results[ticker] = None

        if i < len(WATCHLIST):
            log.info(f"       waiting {API_DELAY_SECONDS}s ...")
            time.sleep(API_DELAY_SECONDS)

    ok     = sum(1 for v in results.values() if v is not None)
    failed = [t for t, v in results.items() if v is None]
    log.info(f"  Result: {ok} OK | {len(failed)} failed: {failed or 'none'}")
    ctx["news_results"] = results
    return results


# STEP 5 -- CLEAN DATABASE
def clean_database(ctx):
    _section("STEP 5 -- Cleaning database")

    cleaner = ctx["cleaner"]

    # Remove duplicate news
    try:
        removed = cleaner.remove_duplicate_news()
        log.info(f"  OK Removed {removed} duplicate news records")
    except Exception as e:
        log.warning(f"  WARN remove_duplicate_news: {e}")

    # Remove old data (keep 2 years of prices, 30 days of news)
    try:
        removed = cleaner.remove_old_data(days_to_keep=730)
        log.info(f"  OK Removed old data: {removed}")
    except Exception as e:
        log.warning(f"  WARN remove_old_data: {e}")

    # Vacuum
    try:
        cleaner.vacuum_database()
        log.info("  OK Database vacuumed")
    except Exception as e:
        log.warning(f"  WARN vacuum: {e}")


# STEP 6 -- FINAL REPORT
def print_final_report(f_results, e_results, n_results, start_ts):
    _section("STEP 6 -- Final report")

    elapsed = (datetime.now() - start_ts).total_seconds()

    f_ok  = sum(1 for v in f_results.values() if v is not None)
    e_ok  = sum(1 for v in e_results.values() if v is not None) if e_results else 0
    n_ok  = sum(1 for v in n_results.values() if v is not None) if n_results else 0

    log.info(f"  Run date      : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"  Elapsed       : {elapsed:.1f}s")
    log.info(f"  Tickers       : {len(WATCHLIST)}")
    log.info(f"  Fundamentals  : {f_ok}/{len(WATCHLIST)} OK")
    log.info(f"  Earnings      : {e_ok}/{len(WATCHLIST)} OK")
    log.info(f"  News          : {n_ok}/{len(WATCHLIST)} OK")

    log.info("")
    log.info(f"  {'Ticker':<8}  {'Fundamentals':>14}  {'Earnings':>10}  {'News':>8}")
    log.info(f"  {'─'*8}  {'─'*14}  {'─'*10}  {'─'*8}")

    for t in WATCHLIST:
        f_ok_t = "OK" if f_results.get(t) else "FAILED"

        e_ok_t = "OK"
        if e_results:
            e_ok_t = "OK" if e_results.get(t) else "SKIPPED" if not FETCH_EARNINGS else "FAILED"

        articles = n_results.get(t) if n_results else None
        if articles is None:
            n_ok_t = "SKIPPED" if not FETCH_NEWS else "FAILED"
        else:
            n_ok_t = f"{len(articles)} art"

        log.info(f"  {t:<8}  {f_ok_t:>14}  {e_ok_t:>10}  {n_ok_t:>8}")


# MAIN
def main():
    start_ts = datetime.now()
    _banner(f"WEEKLY FUNDAMENTALS  --  {start_ts.strftime('%Y-%m-%d  %H:%M')}")

    ctx = connect()
    if ctx is None:
        log.error("Aborting -- missing API key.")
        return

    f_results = fetch_fundamentals(ctx)
    e_results = fetch_earnings(ctx)
    n_results = fetch_news(ctx)
    clean_database(ctx)
    print_final_report(f_results, e_results, n_results, start_ts)

    try:
        ctx["db"].close()
    except Exception:
        pass

    _banner("WEEKLY FUNDAMENTALS COMPLETE")


if __name__ == "__main__":
    main()