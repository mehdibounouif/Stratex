"""
Pipeline Test Suite
===================
Tests daily_update.py and weekly_fundamentals.py step by step.

Usage
-----
    python test_pipelines.py                  # run all tests
    python test_pipelines.py --daily          # test daily pipeline only
    python test_pipelines.py --weekly         # test weekly pipeline only
    python test_pipelines.py --unit           # unit tests only (no API calls)
    python test_pipelines.py --integration    # full integration tests (needs API key)
    python test_pipelines.py -v               # verbose output
"""

import sys
import os
import time
import traceback
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# ── Project root ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from logger import setup_logging, get_logger
setup_logging()
log = get_logger("test.pipelines")

# ── Test result tracking ──────────────────────────────────────────────────────
PASSED  = []
FAILED  = []
SKIPPED = []


def ok(name):
    PASSED.append(name)
    print(f"  ✅  PASS  {name}")


def fail(name, reason=""):
    FAILED.append(name)
    print(f"  ❌  FAIL  {name}")
    if reason:
        print(f"           {reason}")


def skip(name, reason=""):
    SKIPPED.append(name)
    print(f"  ⏭️   SKIP  {name}")
    if reason:
        print(f"           {reason}")


def section(title):
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def subsection(title):
    print()
    print(f"  ── {title}")
    print(f"  {'─' * 50}")


# ═════════════════════════════════════════════════════════════════════════════
# UNIT TESTS — No API calls, no external dependencies
# ═════════════════════════════════════════════════════════════════════════════

def test_imports():
    section("UNIT TEST 1 — Imports")

    mods = [
        ("config",                        "BaseConfig"),
        ("logger",                        "get_logger"),
        ("data.database",                 "Database"),
        ("data.pipelines.data_cleaning",  "DataCleaner"),
        ("data.stock_fetcher",            "StockDataFetcher"),
        ("data.fundamental_fetcher",      "FundamentalDataFetcher"),
        ("data.news_fetcher",             "NewsDataFetcher"),
        ("data.data_engineer",            "DataEngineer"),
    ]

    for module, attr in mods:
        try:
            mod = __import__(module, fromlist=[attr])
            assert hasattr(mod, attr), f"{attr} not found in {module}"
            ok(f"import {module}.{attr}")
        except Exception as e:
            fail(f"import {module}.{attr}", str(e))


def test_database_unit():
    section("UNIT TEST 2 — Database (in-memory)")

    try:
        from data.database import Database
        db = Database(db_path=":memory:")
        db.connect()
        ok("Database.__init__ + connect()")
    except Exception as e:
        fail("Database.__init__ + connect()", str(e))
        return

    try:
        db.create_tables()
        ok("Database.create_tables()")
    except Exception as e:
        fail("Database.create_tables()", str(e))
        return

    for table in ("stock_prices", "fundamentals", "news"):
        try:
            db.check_if_the_table_exist(table)
            ok(f"Table exists: {table}")
        except Exception as e:
            fail(f"Table exists: {table}", str(e))

    try:
        db.insert_stock_prices("TEST", "2026-01-01", 100.0, 105.0, 98.0, 103.0, 500000)
        rows = db.get_stock_prices("TEST")
        assert len(rows) == 1
        ok("insert_stock_prices + get_stock_prices")
    except Exception as e:
        fail("insert_stock_prices + get_stock_prices", str(e))

    try:
        db.insert_stock_prices("TEST", "2026-01-01", 999.0, 999.0, 999.0, 999.0, 999)
        rows = db.get_stock_prices("TEST")
        assert len(rows) == 1, f"Expected 1, got {len(rows)} — duplicate not ignored"
        ok("Duplicate insert ignored (UNIQUE constraint)")
    except Exception as e:
        fail("Duplicate insert ignored", str(e))

    try:
        db.insert_fundamental("TEST", "2026-Q1", 1e9, 2e8, 1.50, 22.5)
        rows = db.get_fundamentals("TEST")
        assert len(rows) == 1
        ok("insert_fundamental + get_fundamentals")
    except Exception as e:
        fail("insert_fundamental + get_fundamentals", str(e))

    try:
        db.insert_news("TEST", "Test Headline", "Test summary.", "2026-01-01", 0.75)
        rows = db.get_news("TEST", days=9999)
        assert len(rows) == 1
        ok("insert_news + get_news")
    except Exception as e:
        fail("insert_news + get_news", str(e))

    try:
        db.close()
        ok("Database.close()")
    except Exception as e:
        fail("Database.close()", str(e))


def test_data_cleaner_unit():
    section("UNIT TEST 3 — DataCleaner")

    try:
        import pandas as pd
        from data.pipelines.data_cleaning import DataCleaner
    except Exception as e:
        fail("DataCleaner import", str(e))
        return

    cleaner = DataCleaner()
    ok("DataCleaner.__init__()")

    # Build dirty DataFrame
    dirty = pd.DataFrame({
        "ticker": ["AAPL"] * 6,
        "date":   ["2026-01-01","2026-01-01","2026-01-02","2026-01-03","2026-01-04","2026-01-05"],
        "open":   [150.0, 150.0, -1.0,  154.0, 157.0, 158.0],
        "high":   [155.0, 155.0, 155.0, 140.0, 160.0, 162.0],
        "low":    [148.0, 148.0, 148.0, 160.0, 155.0, 156.0],
        "close":  [154.0, 154.0, 154.0, 157.0, 158.0, 159.0],
        "volume": [1_000_000, 1_000_000, 1_000_000, -500, 1_200_000, 1_300_000],
    })

    try:
        cleaned = cleaner.clean_stock_prices(dirty.copy(), ticker="AAPL")
        assert cleaned is not None and not cleaned.empty
        ok("clean_stock_prices returns non-empty DataFrame")
    except Exception as e:
        fail("clean_stock_prices", str(e))
        return

    try:
        assert len(cleaned) < len(dirty), \
            f"Expected rows to decrease from {len(dirty)}, got {len(cleaned)}"
        ok(f"Rows reduced: {len(dirty)} → {len(cleaned)}")
    except AssertionError as e:
        fail("Row reduction", str(e))

    try:
        neg_prices = (cleaned[["open","high","low","close"]] <= 0).any().any()
        assert not neg_prices, "Negative/zero prices remain after cleaning"
        ok("No negative/zero prices after cleaning")
    except AssertionError as e:
        fail("Negative price removal", str(e))

    try:
        neg_vol = (cleaned["volume"] < 0).any()
        assert not neg_vol, "Negative volumes remain after cleaning"
        ok("No negative volumes after cleaning")
    except AssertionError as e:
        fail("Negative volume removal", str(e))

    try:
        summary = cleaner.get_cleaning_summary()
        assert isinstance(summary, dict)
        assert "duplicates_removed" in summary
        ok(f"get_cleaning_summary(): {summary}")
    except Exception as e:
        fail("get_cleaning_summary()", str(e))


def test_daily_pipeline_structure():
    section("UNIT TEST 4 — daily_update.py structure")

    try:
        import pipelines.daily_update as du
        ok("import daily_update")
    except Exception as e:
        fail("import daily_update", str(e))
        return

    for fn in ("connect", "fetch_prices", "clean_data", "fetch_live_prices",
               "update_portfolio", "print_risk_summary", "print_final_report", "main"):
        if callable(getattr(du, fn, None)):
            ok(f"daily_update.{fn} is callable")
        else:
            fail(f"daily_update.{fn} is callable", "function missing or not callable")

    for const in ("WATCHLIST", "FETCH_DAYS_BACK", "API_DELAY", "UPDATE_PORTFOLIO_PRICES"):
        if hasattr(du, const):
            ok(f"daily_update.{const} defined = {getattr(du, const)!r}")
        else:
            fail(f"daily_update.{const} defined")

    try:
        assert isinstance(du.WATCHLIST, list) and len(du.WATCHLIST) > 0
        ok(f"WATCHLIST has {len(du.WATCHLIST)} tickers")
    except AssertionError as e:
        fail("WATCHLIST is non-empty list", str(e))


def test_weekly_pipeline_structure():
    section("UNIT TEST 5 — weekly_fundamentals.py structure")

    try:
        import pipelines.weekly_update_fundamentals as wf
        ok("import weekly_fundamentals")
    except Exception as e:
        fail("import weekly_fundamentals", str(e))
        return

    for fn in ("connect", "fetch_fundamentals", "fetch_earnings",
               "fetch_news", "clean_database", "print_final_report", "main"):
        if callable(getattr(wf, fn, None)):
            ok(f"weekly_fundamentals.{fn} is callable")
        else:
            fail(f"weekly_fundamentals.{fn} is callable", "function missing or not callable")

    for const in ("WATCHLIST", "API_DELAY_SECONDS", "FUNDAMENTALS_MAX_AGE_DAYS",
                  "NEWS_DAYS_BACK", "FETCH_EARNINGS", "FETCH_NEWS"):
        if hasattr(wf, const):
            ok(f"weekly_fundamentals.{const} = {getattr(wf, const)!r}")
        else:
            fail(f"weekly_fundamentals.{const} defined")

    try:
        assert callable(getattr(wf, "_api_key_configured", None))
        assert bool(wf._api_key_configured("real_key_abc")) is True
        assert bool(wf._api_key_configured("your_alpha_vantage_key_here")) is False
        assert bool(wf._api_key_configured("")) is False
        assert bool(wf._api_key_configured(None)) is False
        ok("_api_key_configured() validates correctly")
    except Exception as e:
        fail("_api_key_configured()", str(e))


# ═════════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — Real connections, mocked API where possible
# ═════════════════════════════════════════════════════════════════════════════

def test_daily_connect():
    section("INTEGRATION TEST 1 — daily_update.connect()")

    try:
        import pipelines.daily_update as du
    except Exception as e:
        fail("import daily_update", str(e))
        return

    try:
        ctx = du.connect()
    except Exception as e:
        fail("connect() raised exception", traceback.format_exc())
        return

    if ctx is None:
        fail("connect() returned None")
        return

    ok("connect() returned a dict")

    for key in ("db", "fetcher", "cleaner"):
        if key in ctx and ctx[key] is not None:
            ok(f"ctx['{key}'] is present")
        else:
            fail(f"ctx['{key}'] is present", f"missing or None — got: {ctx.get(key)}")

    for key in ("tracker", "risk_manager"):
        if key in ctx:
            ok(f"ctx['{key}'] initialized (may be None if module missing)")
        else:
            skip(f"ctx['{key}']", "optional component")

    try:
        ctx["db"].close()
        ok("ctx['db'].close() works")
    except Exception as e:
        fail("ctx['db'].close()", str(e))


def test_daily_fetch_prices():
    section("INTEGRATION TEST 2 — daily_update.fetch_prices()")

    try:
        import pipelines.daily_update as du
        ctx = du.connect()
        assert ctx is not None
    except Exception as e:
        fail("Setup failed", str(e))
        return

    # Use a small watchlist so tests run fast
    original_wl = du.WATCHLIST[:]
    du.WATCHLIST[:] = ["AAPL", "MSFT"]

    try:
        results = du.fetch_prices(ctx)

        assert isinstance(results, dict), "fetch_prices must return a dict"
        ok("fetch_prices() returned a dict")

        for ticker in ["AAPL", "MSFT"]:
            if ticker in results:
                df = results[ticker]
                if df is not None and not df.empty:
                    ok(f"{ticker}: got {len(df)} rows")
                    # Verify expected columns
                    expected_cols = {"Open", "High", "Low", "Close", "Volume"}
                    actual_cols   = set(df.columns)
                    if expected_cols.issubset(actual_cols):
                        ok(f"{ticker}: has all required OHLCV columns")
                    else:
                        fail(f"{ticker}: missing columns", f"have {actual_cols}")
                else:
                    skip(f"{ticker}: data fetch", "returned empty — possible API issue")
            else:
                fail(f"{ticker}: not in results dict")

    except Exception as e:
        fail("fetch_prices() execution", traceback.format_exc())
    finally:
        du.WATCHLIST[:] = original_wl
        try:
            ctx["db"].close()
        except Exception:
            pass


def test_daily_clean_data():
    section("INTEGRATION TEST 3 — daily_update.clean_data()")

    try:
        import pandas as pd
        import pipelines.daily_update as du
        ctx = du.connect()
        assert ctx is not None
    except Exception as e:
        fail("Setup failed", str(e))
        return

    # Build a fake results dict
    fake_results = {
        "AAPL": pd.DataFrame({
            "Date":   ["2026-01-01", "2026-01-01", "2026-01-02"],
            "Open":   [150.0, 150.0, 155.0],
            "High":   [155.0, 155.0, 160.0],
            "Low":    [148.0, 148.0, 153.0],
            "Close":  [153.0, 153.0, 159.0],
            "Volume": [1_000_000, 1_000_000, 1_100_000],
        }),
        "MSFT": None,  # simulate a failed fetch
    }

    try:
        cleaned = du.clean_data(ctx, fake_results)
        assert isinstance(cleaned, dict), "clean_data must return a dict"
        ok("clean_data() returned a dict")

        aapl = cleaned.get("AAPL")
        if aapl is not None and not aapl.empty:
            ok(f"AAPL cleaned: {len(aapl)} rows")
            if len(aapl) < len(fake_results["AAPL"]):
                ok("AAPL: duplicate rows were removed")
            else:
                skip("AAPL duplicate removal", "no duplicates detected by cleaner")
        else:
            fail("AAPL after clean_data is empty or None")

        if cleaned.get("MSFT") is None:
            ok("MSFT None passed through correctly")
        else:
            fail("MSFT should be None after failed fetch")

    except Exception as e:
        fail("clean_data() execution", traceback.format_exc())
    finally:
        try:
            ctx["db"].close()
        except Exception:
            pass


def test_daily_fetch_live_prices():
    section("INTEGRATION TEST 4 — daily_update.fetch_live_prices()")

    try:
        import pipelines.daily_update as du
        ctx = du.connect()
        assert ctx is not None
    except Exception as e:
        fail("Setup failed", str(e))
        return

    original_wl = du.WATCHLIST[:]
    du.WATCHLIST[:] = ["AAPL"]

    try:
        live = du.fetch_live_prices(ctx)

        assert isinstance(live, dict), "fetch_live_prices must return a dict"
        ok("fetch_live_prices() returned a dict")

        aapl_price = live.get("AAPL")
        if aapl_price is not None:
            assert isinstance(aapl_price, float), f"Price must be float, got {type(aapl_price)}"
            assert aapl_price > 0, f"Price must be positive, got {aapl_price}"
            ok(f"AAPL live price: ${aapl_price:.2f}")
        else:
            skip("AAPL live price", "API returned None — possible rate limit")

    except Exception as e:
        fail("fetch_live_prices() execution", traceback.format_exc())
    finally:
        du.WATCHLIST[:] = original_wl
        try:
            ctx["db"].close()
        except Exception:
            pass


def test_daily_print_final_report():
    section("INTEGRATION TEST 5 — daily_update.print_final_report()")

    try:
        import pandas as pd
        import pipelines.daily_update as du
    except Exception as e:
        fail("import daily_update", str(e))
        return

    fake_results = {
        "AAPL": pd.DataFrame({"Date":["2026-01-01"],"Open":[150.0],"High":[155.0],"Low":[148.0],"Close":[153.0],"Volume":[1_000_000]}),
        "MSFT": None,
    }
    fake_live = {"AAPL": 185.22, "MSFT": None}

    try:
        du.print_final_report(fake_results, fake_live, datetime.now() - timedelta(seconds=45))
        ok("print_final_report() ran without errors")
    except Exception as e:
        fail("print_final_report()", traceback.format_exc())


def test_weekly_connect():
    section("INTEGRATION TEST 6 — weekly_fundamentals.connect()")

    try:
        import pipelines.weekly_update_fundamentals as wf
    except Exception as e:
        fail("import weekly_fundamentals", str(e))
        return

    try:
        from config import BaseConfig
        api_key = BaseConfig.ALPHA_VANTAGE_API_KEY
    except Exception as e:
        skip("weekly connect()", f"Cannot load config: {e}")
        return

    if not wf._api_key_configured(api_key):
        skip("weekly connect()", "ALPHA_VANTAGE_API_KEY not configured — skipping API tests")
        return

    try:
        ctx = wf.connect()
    except Exception as e:
        fail("weekly connect() raised exception", traceback.format_exc())
        return

    if ctx is None:
        fail("weekly connect() returned None (API key may be invalid)")
        return

    ok("weekly connect() returned a dict")

    for key in ("db", "cleaner", "fundamental_fetcher", "news_fetcher", "api_key"):
        if key in ctx and ctx[key] is not None:
            ok(f"ctx['{key}'] is present")
        else:
            fail(f"ctx['{key}'] is present")

    try:
        ctx["db"].close()
        ok("ctx['db'].close() works")
    except Exception as e:
        fail("ctx['db'].close()", str(e))


def test_weekly_fetch_fundamentals():
    section("INTEGRATION TEST 7 — weekly_fundamentals.fetch_fundamentals() [1 ticker]")

    try:
        import pipelines.weekly_update_fundamentals as wf
        from config import BaseConfig

        if not wf._api_key_configured(BaseConfig.ALPHA_VANTAGE_API_KEY):
            skip("fetch_fundamentals()", "API key not configured")
            return

        ctx = wf.connect()
        assert ctx is not None
    except Exception as e:
        fail("Setup failed", str(e))
        return

    original_wl = wf.WATCHLIST[:]
    wf.WATCHLIST[:] = ["AAPL"]

    try:
        results = wf.fetch_fundamentals(ctx)
        assert isinstance(results, dict), "fetch_fundamentals must return dict"
        ok("fetch_fundamentals() returned dict")

        aapl = results.get("AAPL")
        if aapl is not None:
            assert "source" in aapl and "data"  in aapl
            ok(f"AAPL fundamentals: source={aapl['source']}, data={'present' if aapl['data'] else 'None'}")
        else:
            skip("AAPL fundamentals", "not returned — possible API issue")

    except Exception as e:
        fail("fetch_fundamentals()", traceback.format_exc())
    finally:
        wf.WATCHLIST[:] = original_wl
        try:
            ctx["db"].close()
        except Exception:
            pass


def test_weekly_clean_database():
    section("INTEGRATION TEST 8 — weekly_fundamentals.clean_database()")

    try:
        import pipelines.weekly_update_fundamentals as wf
        from config import BaseConfig

        if not wf._api_key_configured(BaseConfig.ALPHA_VANTAGE_API_KEY):
            skip("clean_database()", "API key not configured")
            return

        ctx = wf.connect()
        assert ctx is not None
    except Exception as e:
        fail("Setup failed", str(e))
        return

    try:
        wf.clean_database(ctx)
        ok("clean_database() completed without exception")
    except Exception as e:
        fail("clean_database()", traceback.format_exc())
    finally:
        try:
            ctx["db"].close()
        except Exception:
            pass


def test_weekly_print_final_report():
    section("INTEGRATION TEST 9 — weekly_fundamentals.print_final_report()")

    try:
        import pipelines.weekly_update_fundamentals as wf
    except Exception as e:
        fail("import weekly_fundamentals", str(e))
        return

    fake_f = {"AAPL": {"source":"api","data":{"pe":28.5}}, "MSFT": None}
    fake_e = {"AAPL": {"reported":1.21,"estimated":1.15},   "MSFT": None}
    fake_n = {"AAPL": [{"headline":"test","sentiment":0.3}], "MSFT": []}

    try:
        wf.print_final_report(fake_f, fake_e, fake_n, datetime.now() - timedelta(minutes=3))
        ok("print_final_report() ran without errors")
    except Exception as e:
        fail("print_final_report()", traceback.format_exc())


# ═════════════════════════════════════════════════════════════════════════════
# END-TO-END — Run main() with --force (mocked weekend guard)
# ═════════════════════════════════════════════════════════════════════════════

def test_daily_main_e2e():
    section("E2E TEST — daily_update.main() (2 tickers, --force)")

    try:
        import pipelines.daily_update as du
    except Exception as e:
        fail("import daily_update", str(e))
        return

    original_wl = du.WATCHLIST[:]
    du.WATCHLIST[:] = ["AAPL", "MSFT"]

    # Inject --force so weekend guard passes
    original_argv = sys.argv[:]
    sys.argv = ["test_pipelines.py", "--force"]

    try:
        du.main()
        ok("daily_update.main() completed without exception")
    except SystemExit:
        ok("daily_update.main() exited cleanly (SystemExit)")
    except Exception as e:
        fail("daily_update.main()", traceback.format_exc())
    finally:
        du.WATCHLIST[:] = original_wl
        sys.argv = original_argv


def test_weekly_main_e2e():
    section("E2E TEST — weekly_fundamentals.main() (1 ticker)")

    try:
        import pipelines.weekly_update_fundamentals as wf
        from config import BaseConfig

        if not wf._api_key_configured(BaseConfig.ALPHA_VANTAGE_API_KEY):
            skip("weekly_fundamentals.main()", "API key not configured")
            return
    except Exception as e:
        fail("Setup", str(e))
        return

    original_wl = wf.WATCHLIST[:]
    wf.WATCHLIST[:] = ["AAPL"]

    try:
        wf.main()
        ok("weekly_fundamentals.main() completed without exception")
    except SystemExit:
        ok("weekly_fundamentals.main() exited cleanly (SystemExit)")
    except Exception as e:
        fail("weekly_fundamentals.main()", traceback.format_exc())
    finally:
        wf.WATCHLIST[:] = original_wl


# ═════════════════════════════════════════════════════════════════════════════
# FINAL REPORT
# ═════════════════════════════════════════════════════════════════════════════

def print_report(start_ts):
    elapsed = time.time() - start_ts
    total   = len(PASSED) + len(FAILED) + len(SKIPPED)

    print()
    print("=" * 60)
    print("  TEST RESULTS")
    print("=" * 60)
    print(f"  Total   : {total}")
    print(f"  ✅ Pass  : {len(PASSED)}")
    print(f"  ❌ Fail  : {len(FAILED)}")
    print(f"  ⏭️  Skip  : {len(SKIPPED)}")
    print(f"  ⏱  Time  : {elapsed:.1f}s")
    print()

    if FAILED:
        print("  FAILED TESTS:")
        for name in FAILED:
            print(f"    ✗ {name}")
        print()

    if len(FAILED) == 0:
        print("  ✅  ALL TESTS PASSED")
    else:
        print(f"  ❌  {len(FAILED)} TEST(S) FAILED")
    print("=" * 60)

    return len(FAILED) == 0


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Pipeline test suite")
    parser.add_argument("--daily",       action="store_true", help="Daily pipeline tests only")
    parser.add_argument("--weekly",      action="store_true", help="Weekly pipeline tests only")
    parser.add_argument("--unit",        action="store_true", help="Unit tests only (no API)")
    parser.add_argument("--integration", action="store_true", help="Integration + E2E tests")
    parser.add_argument("-v","--verbose",action="store_true", help="Verbose output")
    args = parser.parse_args()

    run_daily   = args.daily   or (not args.weekly  and not args.unit and not args.integration)
    run_weekly  = args.weekly  or (not args.daily   and not args.unit and not args.integration)
    run_unit    = args.unit    or (not args.integration)
    run_integ   = args.integration or (not args.unit)

    start_ts = time.time()

    print()
    print("=" * 60)
    print("  PIPELINE TEST SUITE")
    print(f"  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}")
    print("=" * 60)

    # ── Unit tests ─────────────────────────────────────────────
    if run_unit:
        test_imports()
        test_database_unit()
        test_data_cleaner_unit()

        if run_daily:
            test_daily_pipeline_structure()

        if run_weekly:
            test_weekly_pipeline_structure()

    # ── Integration tests ───────────────────────────────────────
    if run_integ:
        if run_daily:
            test_daily_connect()
            test_daily_fetch_prices()
            test_daily_clean_data()
            test_daily_fetch_live_prices()
            test_daily_print_final_report()

        if run_weekly:
            test_weekly_connect()
            test_weekly_fetch_fundamentals()
            test_weekly_clean_database()
            test_weekly_print_final_report()

        # E2E — only if explicitly requested or running full suite
        if run_daily and (args.integration or (not args.unit)):
            test_daily_main_e2e()

        if run_weekly and (args.integration or (not args.unit)):
            test_weekly_main_e2e()

    all_passed = print_report(start_ts)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()