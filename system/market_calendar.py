"""
US market holiday calendar and trading day utilities.
"""
from datetime import datetime, date, time, timedelta
import pytz
from logger import get_logger

log = get_logger('system.market_calendar')

class MarketCalendar:
    def __init__(self):
        # US Market Holidays 2025 and 2026
        self.holidays = {
            # 2025
            '2025-01-01', '2025-01-20', '2025-02-17', '2025-04-18', 
            '2025-05-26', '2025-06-19', '2025-07-04', '2025-09-01', 
            '2025-11-27', '2025-12-25',
            # 2026
            '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03',
            '2026-05-25', '2026-06-19', '2026-07-03', '2026-09-07',
            '2026-11-26', '2026-12-25'
        }
        self.tz = pytz.timezone('America/New_York')

    def is_trading_day(self, dt=None) -> bool:
        if dt is None:
            dt = datetime.now(self.tz).date()
        if isinstance(dt, datetime):
            dt = dt.date()
      
        if dt.weekday() >= 5: # Saturday or Sunday
            return False
        if dt.strftime('%Y-%m-%d') in self.holidays:
            return False
        return True

    def is_market_open(self) -> bool:
        now = datetime.now(self.tz)
        if not self.is_trading_day(now.date()):
            return False
      
        open_time = time(9, 30)
        close_time = time(16, 0)
        return open_time <= now.time() <= close_time

    def time_to_open(self) -> timedelta:
        now = datetime.now(self.tz)
        target_date = now.date()
      
        # If today is weekend/holiday or already after close
        if not self.is_trading_day(target_date) or now.time() >= time(16, 0):
            target_date = self.next_trading_day(target_date)
          
        target_open = self.tz.localize(datetime.combine(target_date, time(9, 30)))
        diff = target_open - now
        return max(diff, timedelta(0))

    def time_to_close(self) -> timedelta:
        now = datetime.now(self.tz)
        if not self.is_trading_day(now.date()):
            return timedelta(seconds=-1)
      
        target_close = self.tz.localize(datetime.combine(now.date(), time(16, 0)))
        return target_close - now

    def next_trading_day(self, dt=None) -> date:
        if dt is None:
            dt = datetime.now(self.tz).date()
      
        next_day = dt + timedelta(days=1)
        while not self.is_trading_day(next_day):
            next_day += timedelta(days=1)
        return next_day

market_calendar = MarketCalendar()
