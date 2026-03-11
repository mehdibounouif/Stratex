"""
Weekly Fundamentals Pipeline
============================

Purpose
-------
This pipeline refreshes *fundamental financial data* and *news sentiment*
for every stock in the system watchlist.

Unlike price data (which updates daily), company fundamentals such as:

    • P/E ratio
    • EPS (earnings per share)
    • Revenue
    • Market capitalization
    • Debt levels

only change **quarterly or occasionally**, therefore refreshing them daily
would waste API calls.

This pipeline runs **once per week** to:

    1. Update company fundamentals
    2. Update earnings reports
    3. Fetch news sentiment
    4. Clean duplicate news
    5. Maintain database health

Typical Schedule
----------------

Run via cron:

    Sunday night or Monday morning

Example cron job:

    0 20 * * 0 python weekly_fundamentals.py

This keeps fundamental information reasonably fresh without exceeding
free API rate limits.

External Dependencies
---------------------

Data Sources:
    • Alpha Vantage API (fundamentals + earnings)
    • News API (news + sentiment)

Internal Components:
    • Database
    • DataCleaner
    • FundamentalDataFetcher
    • NewsDataFetcher
"""


import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from logger import setup_logging, get_logger
setup_logging()
log = get_logger("pipeline.weekly_fundamentals")


# ============================================================================
# CONFIGURATION
# ============================================================================

WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN",
    "JPM",  "BAC",  "GS",
    "JNJ",  "PFE",
    "XOM",  "CVX",
    "TSLA", "HD",
]

API_DELAY_SECONDS         = 15
FUNDAMENTALS_MAX_AGE_DAYS = 6
NEWS_DAYS_BACK            = 7
FETCH_EARNINGS            = True
FETCH_NEWS                = True


# ============================================================================
# LOGGING HELPERS
# ============================================================================

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


# ============================================================================
# STEP 1 — CONNECT
# ============================================================================

def connect():
    _section("STEP 1 -- Connecting")

    # --- Validate API key first ---
    try:
        from config import BaseConfig
        api_key = BaseConfig.ALPHA_VANTAGE_API_KEY
    except Exception as e:
        log.error(f"❌ Could not load config: {e}")
        return None

    if not _api_key_configured(api_key):
        log.error("❌ ALPHA_VANTAGE_API_KEY is not configured.")
        log.error("   Get a free key at: https://www.alphavantage.co/support/#api-key")
        return None

    log.info(f"✅ Alpha Vantage API key found")

    ctx = {"api_key": api_key}

    # --- Database ---
    try:
        from data.database import Database
        db = Database()
        db.connect()
        db.create_tables()
        ctx["db"] = db
        log.info("✅ Database connected")
    except Exception as e:
        log.error(f"❌ Database connection failed: {e}")
        return None

    # --- DataCleaner ---
    try:
        from data.pipelines.data_cleaning import DataCleaner
        ctx["cleaner"] = DataCleaner(db=ctx["db"])
        log.info("✅ DataCleaner ready")
    except Exception as e:
        log.warning(f"⚠️  DataCleaner unavailable: {e}")
        ctx["cleaner"] = None

    # --- FundamentalDataFetcher ---
    try:
        from data.fundamental_fetcher import FundamentalDataFetcher
        ctx["fundamental_fetcher"] = FundamentalDataFetcher(
            api_key=api_key,
            db=ctx["db"]
        )
        log.info("✅ FundamentalDataFetcher ready")
    except Exception as e:
        log.error(f"❌ FundamentalDataFetcher failed: {e}")
        return None

    # --- NewsDataFetcher ---
    try:
        from data.news_fetcher import NewsDataFetcher
        ctx["news_fetcher"] = NewsDataFetcher(
            api_key=api_key,
            db=ctx["db"]
        )
        log.info("✅ NewsDataFetcher ready")
    except Exception as e:
        log.warning(f"⚠️  NewsDataFetcher unavailable: {e}")
        ctx["news_fetcher"] = None

    log.info("✅ All services initialized")
    return ctx


# ============================================================================
# STEP 2 — FETCH FUNDAMENTALS
# ============================================================================

def fetch_fundamentals(ctx):
    _section(f"STEP 2 -- Fetching fundamentals ({len(WATCHLIST)} tickers)")

    if ctx is None or "fundamental_fetcher" not in ctx:
        log.error("❌ FundamentalDataFetcher not in context — skipping")
        return {}

    fetcher  = ctx["fundamental_fetcher"]
    results  = {}
    success  = 0
    skipped  = 0
    failed   = 0
    today    = datetime.today().date()

    for i, ticker in enumerate(WATCHLIST, 1):
        log.info(f"[{i}/{len(WATCHLIST)}] {ticker}")

        try:
            # Check cache freshness
            cached = fetcher.get_cached_fundamentals(ticker)

            if cached:
                # cached is a list of tuples: (id, ticker, date, revenue, net_income, eps, pe_ratio)
                latest_row  = cached[-1]
                cached_date = datetime.strptime(latest_row[2][:10], "%Y-%m-%d").date()
                age_days    = (today - cached_date).days

                if age_days <= FUNDAMENTALS_MAX_AGE_DAYS:
                    log.info(f"  ✅ {ticker}: using cache (age {age_days}d)")
                    results[ticker] = {"source": "cache", "data": cached}
                    skipped += 1
                    continue

            # Cache stale or missing — fetch from API
            data = fetcher.fetch_fundamentals(ticker)

            if data:
                results[ticker] = {"source": "api", "data": data}
                log.info(f"  ✅ {ticker}: fetched from API")
                success += 1
            else:
                log.warning(f"  ⚠️  {ticker}: no data returned")
                results[ticker] = {"source": "api", "data": None}
                failed += 1

        except Exception as e:
            log.error(f"  ❌ {ticker}: fundamentals fetch failed — {e}")
            results[ticker] = {"source": "api", "data": None}
            failed += 1

        # Rate limiting — skip delay after last ticker
        if i < len(WATCHLIST):
            log.info(f"  ⏳ Waiting {API_DELAY_SECONDS}s (rate limit)...")
            time.sleep(API_DELAY_SECONDS)

    log.info(f"✅ Fundamentals: {success} API, {skipped} cached, {failed} failed")
    return results


# ============================================================================
# STEP 3 — FETCH EARNINGS
# ============================================================================

def fetch_earnings(ctx):
    _section(f"STEP 3 -- Fetching earnings ({len(WATCHLIST)} tickers)")

    if not FETCH_EARNINGS:
        log.info("ℹ️  FETCH_EARNINGS=False — skipping earnings step")
        return {}

    if ctx is None or "fundamental_fetcher" not in ctx:
        log.error("❌ FundamentalDataFetcher not in context — skipping earnings")
        return {}

    fetcher  = ctx["fundamental_fetcher"]
    results  = {}
    success  = 0
    failed   = 0

    for i, ticker in enumerate(WATCHLIST, 1):
        log.info(f"[{i}/{len(WATCHLIST)}] {ticker}")

        try:
            data = fetcher.fetch_earnings(ticker)

            if data:
                results[ticker] = data
                log.info(f"  ✅ {ticker}: earnings fetched")
                success += 1
            else:
                log.warning(f"  ⚠️  {ticker}: no earnings data returned")
                results[ticker] = None
                failed += 1

        except Exception as e:
            log.error(f"  ❌ {ticker}: earnings fetch failed — {e}")
            results[ticker] = None
            failed += 1

        if i < len(WATCHLIST):
            log.info(f"  ⏳ Waiting {API_DELAY_SECONDS}s (rate limit)...")
            time.sleep(API_DELAY_SECONDS)

    log.info(f"✅ Earnings: {success} success, {failed} failed")
    return results


# ============================================================================
# STEP 4 — FETCH NEWS
# ============================================================================

def fetch_news(ctx):
    _section(f"STEP 4 -- Fetching news ({len(WATCHLIST)} tickers, last {NEWS_DAYS_BACK} days)")

    if not FETCH_NEWS:
        log.info("ℹ️  FETCH_NEWS=False — skipping news step")
        return {}

    if ctx is None or ctx.get("news_fetcher") is None:
        log.warning("⚠️  NewsDataFetcher not available — skipping news")
        return {}

    fetcher  = ctx["news_fetcher"]
    results  = {}
    success  = 0
    skipped  = 0
    failed   = 0

    for i, ticker in enumerate(WATCHLIST, 1):
        log.info(f"[{i}/{len(WATCHLIST)}] {ticker}")

        try:
            # Check cache first
            cached = fetcher.get_cached_news(ticker, days=NEWS_DAYS_BACK)

            if cached:
                log.info(f"  ✅ {ticker}: using cached news ({len(cached)} articles)")
                results[ticker] = cached
                skipped += 1
                continue

            # Fetch from API
            articles = fetcher.fetch_market_news(ticker, days=NEWS_DAYS_BACK)

            if articles is not None:
                results[ticker] = articles

                if articles:
                    # Log sentiment summary
                    sentiment_summary = fetcher.calculate_sentiment_summary(articles)
                    avg = sentiment_summary["average_sentiment"]
                    mood = "BULLISH" if avg > 0.1 else ("BEARISH" if avg < -0.1 else "NEUTRAL")
                    log.info(f"  ✅ {ticker}: {len(articles)} articles | sentiment={avg:.3f} ({mood})")
                else:
                    log.info(f"  ℹ️  {ticker}: 0 articles found")

                success += 1
            else:
                log.warning(f"  ⚠️  {ticker}: news fetch failed")
                results[ticker] = []
                failed += 1

        except Exception as e:
            log.error(f"  ❌ {ticker}: news fetch failed — {e}")
            results[ticker] = []
            failed += 1

        if i < len(WATCHLIST):
            log.info(f"  ⏳ Waiting {API_DELAY_SECONDS}s (rate limit)...")
            time.sleep(API_DELAY_SECONDS)

    log.info(f"✅ News: {success} API, {skipped} cached, {failed} failed")
    return results


# ============================================================================
# STEP 5 — CLEAN DATABASE
# ============================================================================

def clean_database(ctx):
    _section("STEP 5 -- Cleaning database")

    if ctx is None or ctx.get("cleaner") is None:
        log.warning("⚠️  DataCleaner not available — skipping database cleaning")
        return

    cleaner = ctx["cleaner"]

    # Remove duplicate news
    try:
        removed = cleaner.remove_duplicate_news()
        log.info(f"  ✅ Duplicate news removed: {removed}")
    except Exception as e:
        log.error(f"  ❌ Failed to remove duplicate news: {e}")

    # Remove old data
    try:
        removed_old = cleaner.remove_old_data(days_to_keep=730)
        log.info(f"  ✅ Old data removed: {removed_old}")
    except Exception as e:
        log.error(f"  ❌ Failed to remove old data: {e}")

    # Vacuum database
    try:
        ok = cleaner.vacuum_database()
        if ok:
            log.info("  ✅ Database vacuumed successfully")
        else:
            log.warning("  ⚠️  Vacuum returned False")
    except Exception as e:
        log.error(f"  ❌ Vacuum failed: {e}")

    log.info("✅ Database cleaning complete")


# ============================================================================
# STEP 6 — FINAL REPORT
# ============================================================================

def print_final_report(f_results, e_results, n_results, start_ts):
    _section("STEP 6 -- Final report")

    runtime  = (datetime.now() - start_ts).total_seconds()
    total    = len(WATCHLIST)

    f_ok  = sum(1 for v in f_results.values() if v and v.get("data"))
    e_ok  = sum(1 for v in e_results.values() if v is not None)
    n_ok  = sum(1 for v in n_results.values() if v is not None)

    log.info(f"  Run timestamp    : {start_ts.strftime('%Y-%m-%d  %H:%M:%S')}")
    log.info(f"  Runtime          : {runtime:.1f} seconds")
    log.info(f"  Tickers          : {total}")
    log.info(f"  Fundamentals OK  : {f_ok}/{total}")
    log.info(f"  Earnings OK      : {e_ok}/{total}")
    log.info(f"  News OK          : {n_ok}/{total}")

    log.info("")
    log.info(f"  {'Ticker':<8}  {'Fundamentals':>14}  {'Earnings':>10}  {'News':>10}")
    log.info(f"  {'-'*8}  {'-'*14}  {'-'*10}  {'-'*10}")

    for ticker in WATCHLIST:
        # Fundamentals
        fv = f_results.get(ticker)
        if fv and fv.get("data"):
            f_str = f"OK ({fv['source']})"
        else:
            f_str = "FAILED"

        # Earnings
        ev = e_results.get(ticker)
        e_str = "OK" if ev else "FAILED"

        # News
        nv = n_results.get(ticker)
        if nv is None:
            n_str = "FAILED"
        elif isinstance(nv, list):
            n_str = f"{len(nv)} art"
        else:
            n_str = "OK"

        log.info(f"  {ticker:<8}  {f_str:>14}  {e_str:>10}  {n_str:>10}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    start_ts = datetime.now()
    _banner(f"WEEKLY FUNDAMENTALS  --  {start_ts.strftime('%Y-%m-%d  %H:%M')}")

    ctx = connect()
    if ctx is None:
        log.error("❌ Aborting -- missing API key or connection failure.")
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