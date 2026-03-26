"""
Scheduled live trading loop using APScheduler.
Handles pre-market, open, mid-day, and close jobs with explicit NY timezone.
"""
from datetime import datetime
import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from logger import get_logger
from config.trading_config import TradingConfig

log = get_logger('system.live_engine')


class LiveEngine:
    def __init__(self):
        self.ny_tz    = pytz.timezone('America/New_York')
        self.scheduler = BlockingScheduler(timezone=self.ny_tz)

    def _get_services(self):
        # ── Use get_trading_system() — NOT the module-level `trading_system`
        # which is None by design until first call.
        from system.system_architect import get_trading_system
        from execution.alpaca_gateway import order_manager
        from system.market_calendar import market_calendar
        from risk.portfolio.portfolio_tracker import position_tracker
        from data.data_engineer import data_access
        return get_trading_system(), order_manager, market_calendar, position_tracker, data_access

    def pre_market_job(self):
        """Warm the data cache before the open."""
        try:
            ts, om, cal, tracker, da = self._get_services()
            if not cal.is_trading_day():
                log.info("Skipping pre-market job: not a trading day.")
                return

            log.info("Pre-market: warming data cache...")
            for ticker in TradingConfig.DEFAULT_WATCHLIST:
                da.get_price_history(ticker, days=365)

            summary = tracker.get_portfolio_summary()
            log.info(
                f"Pre-market summary: "
                f"Cash=${float(summary['cash']):,.2f}, "
                f"Value=${float(summary['portfolio_value']):,.2f}"
            )
        except Exception as e:
            log.error(f"Error in pre_market_job: {e}", exc_info=True)

    def market_open_job(self):
        """
        Main daily trading job.
        Delegates entirely to run_daily_analysis() which owns the correct sequence:
            1. update_all_prices()
            2. check_stop_losses()
            3. scan_watchlist() → analyze → size → risk gate → execute → audit
            4. save_daily_report()
        """
        try:
            ts, om, cal, tracker, da = self._get_services()
            if not cal.is_trading_day():
                log.info("Skipping market_open_job: not a trading day.")
                return

            log.info("Market Open: starting daily analysis...")
            results = ts.run_daily_analysis()

            scan = results.get('scan', {})
            log.info(
                f"Market open complete — "
                f"Bought: {scan.get('executed_buy', [])}, "
                f"Sold: {scan.get('executed_sell', [])}, "
                f"Rejected: {len(scan.get('rejected', []))}, "
                f"Portfolio: ${scan.get('summary', {}).get('portfolio_value', 0):,.2f}"
            )
        except Exception as e:
            log.error(f"Error in market_open_job: {e}", exc_info=True)

    def mid_day_job(self):
        """Reconcile local positions against live Alpaca state."""
        try:
            ts, om, cal, tracker, da = self._get_services()
            if not cal.is_trading_day(): return

            log.info("Mid-day: syncing positions with Alpaca...")
            om.sync_positions()

            summary = tracker.get_portfolio_summary()
            log.info(
                f"Mid-day value: ${float(summary['portfolio_value']):,.2f} | "
                f"Positions: {int(summary['total_positions'])}"
            )
        except Exception as e:
            log.error(f"Error in mid_day_job: {e}", exc_info=True)

    def market_close_job(self):
        """
        End-of-day close job.
        Does NOT re-scan — trading already happened at open.
        Only: sync positions, update to final closing prices, save EOD report.
        """
        try:
            ts, om, cal, tracker, da = self._get_services()
            if not cal.is_trading_day(): return

            log.info("Market Close: syncing final positions...")
            om.sync_positions()

            log.info("Market Close: updating final closing prices...")
            ts.update_all_prices()

            log.info("Market Close: saving EOD report...")
            report_path = ts.save_daily_report()   # handles serialization + correct file path

            summary = tracker.get_portfolio_summary()
            log.info(
                f"EOD — Portfolio: ${float(summary['portfolio_value']):,.2f} | "
                f"Cash: ${float(summary['cash']):,.2f} | "
                f"Return: {float(summary['return_pct']):+.2f}%"
            )
            log.info(f"EOD report saved: {report_path}")

        except Exception as e:
            log.error(f"Error in market_close_job: {e}", exc_info=True)

    def start(self):
        log.info("Live engine starting...")
        self.scheduler.add_job(self.pre_market_job,   CronTrigger(hour=9,  minute=15, day_of_week='mon-fri', timezone=self.ny_tz))
        self.scheduler.add_job(self.market_open_job,  CronTrigger(hour=9,  minute=31, day_of_week='mon-fri', timezone=self.ny_tz))
        self.scheduler.add_job(self.mid_day_job,      CronTrigger(hour=12, minute=0,  day_of_week='mon-fri', timezone=self.ny_tz))
        self.scheduler.add_job(self.market_close_job, CronTrigger(hour=15, minute=55, day_of_week='mon-fri', timezone=self.ny_tz))

        try:
            ny_now = datetime.now(self.ny_tz).strftime('%Y-%m-%d %H:%M:%S')
            log.info(f"Live engine running. NY time: {ny_now}")
            log.info("Press Ctrl+C to stop.")
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            log.info("Live engine stopping...")
            self.stop()

    def stop(self):
        if self.scheduler.running:
            self.scheduler.shutdown()
        log.info("Live engine stopped.")


live_engine = LiveEngine()
