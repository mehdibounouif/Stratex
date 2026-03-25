"""
Scheduled live trading loop using APScheduler.
Handles pre-market, open, mid-day, and close jobs with explicit NY timezone.
"""
from datetime import datetime
import json
import os
import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from logger import get_logger
from config.trading_config import TradingConfig

log = get_logger('system.live_engine')

class LiveEngine:
    def __init__(self):
        # Explicitly define the New York Timezone
        self.ny_tz = pytz.timezone('America/New_York')
        self.scheduler = BlockingScheduler(timezone=self.ny_tz)

    def _get_services(self):
        from system.system_architect import trading_system
        from execution.alpaca_gateway import order_manager
        from system.market_calendar import market_calendar
        from risk.portfolio.portfolio_tracker import position_tracker
        from data.data_engineer import data_access
        return trading_system, order_manager, market_calendar, position_tracker, data_access

    def pre_market_job(self):
        try:
            ts, om, cal, tracker, da = self._get_services()
            if not cal.is_trading_day():
                log.info("Skipping pre-market job: Not a trading day.")
                return
            
            log.info("Running pre-market preparation...")
            for ticker in TradingConfig.DEFAULT_WATCHLIST:
                da.get_price_history(ticker, days=365) # Ensure cache is warm
            
            summary = tracker.get_portfolio_summary()
            log.info(f"Pre-market summary: Cash=${summary['cash']:,.2f}, Value=${summary['portfolio_value']:,.2f}")
        except Exception as e:
            log.error(f"Error in pre_market_job: {e}", exc_info=True)


    def market_open_job(self):
        try:
            ts, om, cal, tracker, da = self._get_services()
            from risk.risk_manager import risk_manager          # ADD
            from risk.position_sizer import PositionSizer       # ADD
            sizer = PositionSizer()                             # ADD
    
            if not cal.is_trading_day(): return
            
            log.info("Market Open: Scanning watchlist...")
            signals = ts.scan_watchlist()
            
            orders_submitted = 0
            for signal in signals:
                if signal['action'] == 'HOLD':
                    continue
                if signal['confidence'] < TradingConfig.MIN_SIGNAL_CONFIDENCE:
                    continue
                
                price = signal['current_price']
                if price <= 0:
                    continue
                
                # Size the trade
                portfolio_val = float(tracker.get_portfolio_summary()['portfolio_value'])
                quantity = sizer.calculate(signal, portfolio_val)   # or your sizing logic
                if quantity <= 0:
                    continue
                
                # ── RISK GATE (was missing entirely) ──────────────
                trade = {
                    'ticker':        signal['ticker'],
                    'action':        signal['action'],
                    'quantity':      quantity,
                    'current_price': price,        # <-- correct key
                    'confidence':    signal['confidence'],
                    'reasoning':     signal.get('reasoning', ''),
                }
                result = risk_manager.approve_trade(trade)
                if not result['approved']:
                    log.warning(f"Risk rejected {signal['ticker']}: {result['reason']}")
                    continue
                # ────────────────────────────────────────────────────
    
                om.submit_from_signal(signal, quantity)
                orders_submitted += 1
            
            log.info(f"Submitted {orders_submitted} orders after risk screening.")
        except Exception as e:
            log.error(f"Error in market_open_job: {e}", exc_info=True)



    def mid_day_job(self):
        try:
            ts, om, cal, tracker, da = self._get_services()
            if not cal.is_trading_day(): return
            
            log.info("Mid-day job: Syncing positions...")
            om.sync_positions()
            summary = tracker.get_portfolio_summary()
            log.info(f"Current Value: ${summary['portfolio_value']:,.2f}. Positions: {len(tracker.get_all_positions())}")
        except Exception as e:
            log.error(f"Error in mid_day_job: {e}", exc_info=True)

    def market_close_job(self):
        try:
            ts, om, cal, tracker, da = self._get_services()
            if not cal.is_trading_day(): return
            
            log.info("Market Close: Generating daily report...")
            report = ts.run_daily_analysis()
            
            # Use NY time for the report filename
            date_str = datetime.now(self.ny_tz).strftime('%Y%m%d')
            report_path = f"risk/reports/risk_{date_str}.json"
            os.makedirs('risk/reports', exist_ok=True)
            
            with open(report_path, 'w') as f:
                json.dump(report, f, indent=4)
            
            log.info(f"Daily summary: End Value ${report.get('portfolio', {}).get('portfolio_value', 0):,.2f}")
        except Exception as e:
            log.error(f"Error in market_close_job: {e}", exc_info=True)

    def start(self):
        log.info("Live engine starting...")
        
        # Register all jobs with explicit NY Timezone enforcement
        self.scheduler.add_job(self.pre_market_job, CronTrigger(hour=9, minute=15, day_of_week='mon-fri', timezone=self.ny_tz))
        self.scheduler.add_job(self.market_open_job, CronTrigger(hour=9, minute=31, day_of_week='mon-fri', timezone=self.ny_tz))
        self.scheduler.add_job(self.mid_day_job, CronTrigger(hour=12, minute=0, day_of_week='mon-fri', timezone=self.ny_tz))
        self.scheduler.add_job(self.market_close_job, CronTrigger(hour=15, minute=55, day_of_week='mon-fri', timezone=self.ny_tz))
        
        try:
            ny_now = datetime.now(self.ny_tz).strftime('%Y-%m-%d %H:%M:%S')
            log.info(f"Live engine running. NY Current Time: {ny_now}")
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
