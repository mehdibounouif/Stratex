"""
Daily Update Pipeline
=====================

Purpose
-------
This pipeline runs once per trading day to keep the trading system's
market data, portfolio valuations, and risk metrics up to date.

It orchestrates multiple subsystems:

    Data Layer
        - Database
        - StockDataFetcher
        - DataCleaner

    Portfolio Layer
        - PositionTracker

    Risk Layer
        - RiskManager

The pipeline performs a sequential workflow where each step prepares
data required by the next stage.

Typical Execution Time
----------------------
1–3 minutes depending on:
    - Number of tickers
    - API response time
    - Data cleaning complexity

Execution
---------
Manual:
    python daily_update.py

Force execution (weekends/testing):
    python daily_update.py --force

Automated (cron example):

    30 17 * * 1-5 cd /Quant_Firm && venv/bin/python daily_update.py
"""


import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from logger import setup_logging, get_logger
setup_logging()
log = get_logger("pipeline.daily_update")


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

FETCH_DAYS_BACK         = 5
API_DELAY               = 1.0
UPDATE_PORTFOLIO_PRICES = True


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


# ============================================================================
# MARKET SCHEDULE
# ============================================================================

def _is_trading_day():
    return datetime.now().weekday() < 5


# ============================================================================
# STEP 1 — SYSTEM CONNECTION
# ============================================================================

def connect():
    _section("STEP 1 -- Connecting")

    ctx = {}

    # --- Database ---
    try:
        from data.database import Database
        db = Database()
        db.connect()
        db.create_tables()
        ctx["db"] = db
        log.info("✅ Database connected")
    except Exception as e:
        log.error(f"❌ Failed to connect to database: {e}")
        return None

    # --- StockDataFetcher ---
    try:
        from data.stock_fetcher import StockDataFetcher
        ctx["fetcher"] = StockDataFetcher(db=ctx["db"])
        log.info("✅ StockDataFetcher ready")
    except Exception as e:
        log.error(f"❌ Failed to initialize StockDataFetcher: {e}")
        return None

    # --- DataCleaner ---
    try:
        from data.pipelines.data_cleaning import DataCleaner
        ctx["cleaner"] = DataCleaner(db=ctx["db"])
        log.info("✅ DataCleaner ready")
    except Exception as e:
        log.warning(f"⚠️  DataCleaner unavailable: {e}")
        ctx["cleaner"] = None

    # --- PositionTracker ---
    try:
        from risk.portfolio.portfolio_tracker import PositionTracker
        ctx["tracker"] = PositionTracker(db=ctx["db"])
        log.info("✅ PositionTracker ready")
    except Exception as e:
        log.warning(f"⚠️  PositionTracker unavailable: {e}")
        ctx["tracker"] = None

    # --- RiskManager ---
    try:
        from risk.risk_manager import RiskManager
        ctx["risk_manager"] = RiskManager(db=ctx["db"])
        log.info("✅ RiskManager ready")
    except Exception as e:
        log.warning(f"⚠️  RiskManager unavailable: {e}")
        ctx["risk_manager"] = None

    log.info(f"✅ All services initialized")
    return ctx


# ============================================================================
# STEP 2 — HISTORICAL PRICE FETCH
# ============================================================================

def fetch_prices(ctx):
    _section(f"STEP 2 -- Fetching prices ({len(WATCHLIST)} tickers)")

    if ctx is None or "fetcher" not in ctx:
        log.error("❌ No fetcher in context — skipping price fetch")
        return {}

    fetcher = ctx["fetcher"]
    end_date   = datetime.now()
    start_date = end_date - timedelta(days=FETCH_DAYS_BACK)

    start_str = start_date.strftime("%Y-%m-%d")
    end_str   = end_date.strftime("%Y-%m-%d")

    results   = {}
    success   = 0
    failed    = 0

    for i, ticker in enumerate(WATCHLIST, 1):
        log.info(f"[{i}/{len(WATCHLIST)}] Fetching {ticker} ...")
        try:
            df = fetcher.fetch_stock_prices(ticker, start_str, end_str)
            results[ticker] = df

            if df is not None and not df.empty:
                log.info(f"  ✅ {ticker}: {len(df)} rows")
                success += 1
            else:
                log.warning(f"  ⚠️  {ticker}: no data returned")
                failed += 1

        except Exception as e:
            log.error(f"  ❌ {ticker}: fetch failed — {e}")
            results[ticker] = None
            failed += 1

        # Rate limiting — skip delay after last ticker
        if i < len(WATCHLIST):
            time.sleep(API_DELAY)

    log.info(f"✅ Price fetch done: {success} success, {failed} failed")
    return results


# ============================================================================
# STEP 3 — DATA CLEANING
# ============================================================================

def clean_data(ctx, results):
    _section("STEP 3 -- Cleaning data")

    if ctx is None or ctx.get("cleaner") is None:
        log.warning("⚠️  DataCleaner not available — skipping cleaning step")
        return results

    cleaner = ctx["cleaner"]
    cleaned = {}

    for ticker, df in results.items():
        if df is None or df.empty:
            cleaned[ticker] = df
            continue

        try:
            clean_df = cleaner.clean_stock_prices(df, ticker=ticker)
            cleaned[ticker] = clean_df
            log.info(f"  ✅ {ticker}: cleaned ({len(clean_df)} rows)")
        except Exception as e:
            log.error(f"  ❌ {ticker}: cleaning failed — {e}")
            cleaned[ticker] = df   # fall back to raw data

    summary = cleaner.get_cleaning_summary()
    log.info(f"✅ Cleaning complete: {summary}")
    return cleaned


# ============================================================================
# STEP 4 — LIVE PRICE FETCH
# ============================================================================

def fetch_live_prices(ctx):
    _section("STEP 4 -- Fetching live prices")

    if ctx is None or "fetcher" not in ctx:
        log.error("❌ No fetcher in context — skipping live prices")
        return {}

    fetcher     = ctx["fetcher"]
    live_prices = {}

    for i, ticker in enumerate(WATCHLIST, 1):
        try:
            result = fetcher.fetch_latest_price(ticker)
            if result and "price" in result:
                price = float(result["price"])
                live_prices[ticker] = price
                log.info(f"  ✅ {ticker}: ${price:.2f}")
            else:
                log.warning(f"  ⚠️  {ticker}: no live price returned")
                live_prices[ticker] = None

        except Exception as e:
            log.error(f"  ❌ {ticker}: live price fetch failed — {e}")
            live_prices[ticker] = None

        # Small delay between calls to avoid rate limiting
        if i < len(WATCHLIST):
            time.sleep(API_DELAY)

    fetched = sum(1 for v in live_prices.values() if v is not None)
    log.info(f"✅ Live prices: {fetched}/{len(WATCHLIST)} retrieved")
    return live_prices


# ============================================================================
# STEP 5 — PORTFOLIO UPDATE
# ============================================================================

def update_portfolio(ctx, live_prices):
    _section("STEP 5 -- Updating portfolio prices")

    if not UPDATE_PORTFOLIO_PRICES:
        log.info("ℹ️  UPDATE_PORTFOLIO_PRICES=False — skipping portfolio update")
        return

    if ctx is None or ctx.get("tracker") is None:
        log.warning("⚠️  PositionTracker not available — skipping portfolio update")
        return

    tracker = ctx["tracker"]
    updated = 0
    skipped = 0

    for ticker, price in live_prices.items():
        if price is None:
            skipped += 1
            continue

        try:
            tracker.update_market_price(ticker, price)
            updated += 1
            log.info(f"  ✅ {ticker}: portfolio price updated to ${price:.2f}")
        except Exception as e:
            log.error(f"  ❌ {ticker}: portfolio update failed — {e}")
            skipped += 1

    log.info(f"✅ Portfolio update: {updated} updated, {skipped} skipped")


# ============================================================================
# STEP 6 — RISK SUMMARY
# ============================================================================

def print_risk_summary(ctx):
    _section("STEP 6 -- Risk summary")

    if ctx is None or ctx.get("risk_manager") is None:
        log.warning("⚠️  RiskManager not available — skipping risk summary")
        return

    try:
        rm      = ctx["risk_manager"]
        summary = rm.get_portfolio_summary()

        log.info(f"  Portfolio Value   : ${summary.get('portfolio_value', 0):>12,.2f}")
        log.info(f"  Cash Allocation   : {summary.get('cash_pct', 0):>10.1f}%")
        log.info(f"  Open Positions    : {summary.get('open_positions', 0):>10}")
        log.info(f"  Unrealized P&L    : ${summary.get('unrealized_pnl', 0):>12,.2f}")
        log.info(f"  Realized P&L      : ${summary.get('realized_pnl', 0):>12,.2f}")
        log.info(f"  Total Return      : {summary.get('total_return_pct', 0):>10.2f}%")

    except Exception as e:
        log.error(f"❌ Failed to retrieve risk summary: {e}")


# ============================================================================
# STEP 7 — FINAL REPORT
# ============================================================================

def print_final_report(results, live_prices, start_ts):
    _section("STEP 7 -- Final report")

    runtime = (datetime.now() - start_ts).total_seconds()

    total    = len(WATCHLIST)
    success  = sum(1 for df in results.values() if df is not None and not df.empty)
    failed   = total - success
    got_live = sum(1 for p in live_prices.values() if p is not None)

    log.info(f"  Run timestamp : {start_ts.strftime('%Y-%m-%d  %H:%M:%S')}")
    log.info(f"  Runtime       : {runtime:.1f} seconds")
    log.info(f"  Tickers       : {total}")
    log.info(f"  History OK    : {success}")
    log.info(f"  History FAIL  : {failed}")
    log.info(f"  Live prices   : {got_live}/{total}")

    log.info("")
    log.info(f"  {'Ticker':<8}  {'Live Price':>12}  {'History':>10}  {'Status'}")
    log.info(f"  {'-'*8}  {'-'*12}  {'-'*10}  {'-'*8}")

    for ticker in WATCHLIST:
        df    = results.get(ticker)
        price = live_prices.get(ticker)

        price_str   = f"${price:.2f}" if price else "N/A"
        history_str = f"{len(df)} rows" if df is not None and not df.empty else "FAILED"
        status      = "OK" if (df is not None and not df.empty and price) else "PARTIAL" if (df is not None or price) else "FAILED"

        log.info(f"  {ticker:<8}  {price_str:>12}  {history_str:>10}  {status}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    start_ts = datetime.now()
    _banner(f"DAILY UPDATE  --  {start_ts.strftime('%Y-%m-%d  %H:%M')}")

    if not _is_trading_day() and "--force" not in sys.argv:
        log.info("Today is a weekend -- skipping. Use --force to override.")
        return

    ctx     = connect()
    if ctx is None:
        log.error("❌ Aborting — failed to connect system components.")
        return

    results = fetch_prices(ctx)
    results = clean_data(ctx, results)
    live    = fetch_live_prices(ctx)
    update_portfolio(ctx, live)
    print_risk_summary(ctx)
    print_final_report(results, live, start_ts)

    try:
        ctx["db"].close()
    except Exception:
        pass

    _banner("DAILY UPDATE COMPLETE")


if __name__ == "__main__":
    main()