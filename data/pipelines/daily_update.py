# daily_update.py
# ===============
# Runs every trading day (Mon-Fri) to keep price data fresh.
#
# Steps:
#   1. Connect  - database, fetcher, cleaner, tracker, risk manager
#   2. Prices   - fetch last FETCH_DAYS_BACK days of OHLCV per ticker
#   3. Clean    - duplicates, OHLC violations, invalid prices/volumes
#   4. Live     - fetch todays live price per ticker
#   5. Portfolio- push live prices into PositionTracker (updates P&L)
#   6. Risk     - print portfolio risk summary
#   7. Report   - final table: status + current prices
#
# Run:
#     python daily_update.py
# Force run on weekends (testing):
#     python daily_update.py --force
# Cron (Mon-Fri 5:30 PM):
#     30 17 * * 1-5 cd /Quant_Firm && venv/bin/python daily_update.py >> logs/daily.log 2>&1

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from logger import setup_logging, get_logger
setup_logging()
log = get_logger("pipeline.daily_update")

# CONFIGURATION
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

def _banner(msg):
    log.info("=" * 60)
    log.info(f"  {msg}")
    log.info("=" * 60)

def _section(msg):
    log.info("" )
    log.info("-" * 50)
    log.info(f"  {msg}")
    log.info("-" * 50)

def _is_trading_day():
    return datetime.now().weekday() < 5

def connect():
    _section("STEP 1 -- Connecting")
    from data.database import Database
    from data.stock_fetcher import StockDataFetcher
    from data.pipelines.data_cleaning import DataCleaner
    db = Database()
    db.connect()
    db.create_tables()
    log.info("  OK Database")
    fetcher = StockDataFetcher(db=db)
    log.info("  OK StockDataFetcher")
    cleaner = DataCleaner(db=db)
    log.info("  OK DataCleaner")
    tracker = None
    try:
        from risk.portfolio.portfolio_tracker import PositionTracker
        tracker = PositionTracker()
        log.info("  OK PositionTracker")
    except Exception as e:
        log.warning(f"  WARN PositionTracker: {e}")
    risk_manager = None
    try:
        from risk.risk_manager import RiskManager
        risk_manager = RiskManager()
        log.info("  OK RiskManager")
    except Exception as e:
        log.warning(f"  WARN RiskManager: {e}")
    return {"db": db, "fetcher": fetcher, "cleaner": cleaner,
            "tracker": tracker, "risk_manager": risk_manager}

def fetch_prices(ctx):
    _section(f"STEP 2 -- Fetching prices ({len(WATCHLIST)} tickers)")
    fetcher    = ctx["fetcher"]
    end_date   = datetime.now()
    start_str  = (end_date - timedelta(days=FETCH_DAYS_BACK)).strftime("%Y-%m-%d")
    end_str    = end_date.strftime("%Y-%m-%d")
    log.info(f"  Range: {start_str} to {end_str}")
    results, failed = {}, []
    for i, ticker in enumerate(WATCHLIST, 1):
        log.info(f"  [{i:02d}/{len(WATCHLIST)}] {ticker} ...")
        try:
            df = fetcher.fetch_or_use_cache(
                ticker=ticker, start_date=start_str, end_date=end_str, max_age_days=1)
            results[ticker] = df
            if df is not None and not df.empty:
                ld = df["Date"].max()
                lc = df.loc[df["Date"] == ld, "Close"].values[0]
                log.info(f"       OK {len(df)} rows | last close: ${float(lc):.2f} ({ld})")
            else:
                log.warning(f"       WARN no data")
                failed.append(ticker)
        except Exception as e:
            log.error(f"       ERR {e}")
            results[ticker] = None
            failed.append(ticker)
        if i < len(WATCHLIST):
            time.sleep(API_DELAY)
    log.info(f"  Result: {len(WATCHLIST)-len(failed)} OK | {len(failed)} failed: {failed or 'none'}")
    ctx["price_results"] = results
    return results

def clean_data(ctx, results):
    _section("STEP 3 -- Cleaning data")
    cleaner, total = ctx["cleaner"], 0
    for ticker, df in results.items():
        if df is None or df.empty:
            continue
        try:
            cleaner.reset_stats()
            results[ticker] = cleaner.clean_stock_prices(df, ticker=ticker)
            s = cleaner.get_cleaning_summary()
            issues = s["duplicates_removed"] + s["ohlc_violations_fixed"] + s["invalid_rows_removed"]
            total += issues
            if issues:
                log.info(f"  FIX {ticker}: {issues} issues fixed -- {s}")
        except Exception as e:
            log.warning(f"  WARN {ticker}: {e}")
    log.info(f"  Total issues fixed: {total}")
    return results

def fetch_live_prices(ctx):
    _section("STEP 4 -- Fetching live prices")
    fetcher, live = ctx["fetcher"], {}
    for i, ticker in enumerate(WATCHLIST, 1):
        try:
            info = fetcher.fetch_latest_price(ticker)
            if info and "price" in info:
                live[ticker] = float(info["price"])
                log.info(f"  {ticker:<8} ${live[ticker]:>9.2f}")
            else:
                live[ticker] = None
                log.warning(f"  {ticker:<8}  no price")
        except Exception as e:
            live[ticker] = None
            log.warning(f"  {ticker:<8}  error: {e}")
        if i < len(WATCHLIST):
            time.sleep(API_DELAY)
    log.info(f"  Fetched: {sum(1 for v in live.values() if v)}/{len(WATCHLIST)}")
    ctx["live_prices"] = live
    return live

def update_portfolio(ctx, live):
    _section("STEP 5 -- Updating portfolio prices")
    tracker = ctx.get("tracker")
    if not tracker or not UPDATE_PORTFOLIO_PRICES:
        log.info("  INFO Skipped")
        return
    try:
        owned = {p.ticker for p in tracker.positions}
        if not owned:
            log.info("  INFO No open positions")
            return
        to_update = {t: p for t, p in live.items() if t in owned and p}
        if to_update:
            tracker.update_prices(to_update)
            log.info(f"  OK Updated {len(to_update)} positions:")
            for t, p in to_update.items():
                log.info(f"     {t:<8} ${p:.2f}")
        else:
            log.info("  INFO No live prices for held positions")
    except Exception as e:
        log.error(f"  ERR {e}")

def print_risk_summary(ctx):
    _section("STEP 6 -- Risk summary")
    rm = ctx.get("risk_manager")
    if not rm:
        log.info("  INFO RiskManager not available")
        return
    try:
        s = rm.get_risk_summary()
        log.info(f"  Portfolio value  : ${s.get('portfolio_value',0):>12,.2f}")
        log.info(f"  Cash             : ${s.get('cash',0):>12,.2f}  ({s.get('cash_pct',0)*100:.1f}%)")
        log.info(f"  Open positions   : {s.get('num_positions',0)}")
        log.info(f"  Unrealized P&L   : ${s.get('unrealized_pnl',0):>+12,.2f}")
        log.info(f"  Realized P&L     : ${s.get('realized_pnl',0):>+12,.2f}")
        log.info(f"  Total return     : {s.get('total_return_pct',0)*100:>+.2f}%")
    except Exception as e:
        log.error(f"  ERR {e}")

def print_final_report(results, live, start_ts):
    _section("STEP 7 -- Final report")
    elapsed = (datetime.now() - start_ts).total_seconds()
    ok     = [t for t, df in results.items() if df is not None and not df.empty]
    failed = [t for t, df in results.items() if df is None or df.empty]
    log.info(f"  Run date  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"  Elapsed   : {elapsed:.1f}s")
    log.info(f"  Watchlist : {len(WATCHLIST)} tickers")
    log.info(f"  OK        : {len(ok)}")
    log.info(f"  Failed    : {len(failed)}  {failed or ''}")
    log.info("")
    log.info(f"  {'Ticker':<8}  {'Live Price':>11}  Status")
    log.info(f"  {'─'*8}  {'─'*11}  {'─'*8}")
    for t in WATCHLIST:
        df = results.get(t)
        price = live.get(t)
        marker = "OK" if (df is not None and not df.empty) else "FAILED"
        p_str  = f"${price:>9.2f}" if price else "          -"
        log.info(f"  {t:<8}  {p_str}  {marker}")

def main():
    start_ts = datetime.now()
    _banner(f"DAILY UPDATE  --  {start_ts.strftime('%Y-%m-%d  %H:%M')}")
    if not _is_trading_day() and "--force" not in sys.argv:
        log.info("Today is a weekend -- skipping. Use --force to override.")
        return
    ctx     = connect()
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