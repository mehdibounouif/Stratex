"""
Risk Manager
============
Enforces all trading risk rules before any trade is executed.

Uses:
- RiskConfig  → the hard limits (position size, sector %, drawdown, etc.)
- TradingConfig → INITIAL_CAPITAL = $20,000
- PositionTracker → real portfolio state (cash, positions, P&L)
- PortfolioCalculator → sector breakdown, concentration, VaR

Author: Kawtar (Risk Manager)
"""

from config import RiskConfig, TradingConfig
from logger import get_logger, setup_logging

setup_logging()
log = get_logger("risk.risk_manager")


class RiskManager:
    """
    Gate keeper: every trade must pass through here before execution.

    Checks (in order):
    1. Position size           ≤ RiskConfig.MAX_POSITION_SIZE (15%)
    2. Cash reserve            ≥ RiskConfig.MIN_CASH_RESERVE  (10%)
    3. Max open positions      ≤ RiskConfig.MAX_TOTAL_POSITIONS (15)
    4. Sector exposure         ≤ RiskConfig.MAX_SECTOR_EXPOSURE per sector
    5. Daily loss circuit      ≤ RiskConfig.MAX_DAILY_LOSS (3%)
    6. Max drawdown halt       ≤ RiskConfig.MAX_DRAWDOWN_BEFORE_HALT (15%)
    """

    def __init__(self):
        self.config = RiskConfig()
        self.trading_config = TradingConfig()

        # ── Lazy imports to avoid circular dependency ──────────
        # These are loaded on first use, not at module import time.
        self._tracker = None
        self._calculator = None

        log.info("✅ RiskManager initialized")
        log.info(f"   Initial capital:      ${TradingConfig.INITIAL_CAPITAL:,.2f}")
        log.info(f"   Max position size:    {self.config.MAX_POSITION_SIZE:.0%}")
        log.info(f"   Min cash reserve:     {self.config.MIN_CASH_RESERVE:.0%}")
        log.info(f"   Max total positions:  {self.config.MAX_TOTAL_POSITIONS}")
        log.info(f"   Max daily loss:       {self.config.MAX_DAILY_LOSS:.0%}")
        log.info(f"   Max drawdown halt:    {self.config.MAX_DRAWDOWN_BEFORE_HALT:.0%}")

    # ── Lazy property: portfolio tracker ──────────────────────
    @property
    def tracker(self):
        if self._tracker is None:
            from risk.portfolio.portfolio_tracker import position_tracker
            self._tracker = position_tracker
        return self._tracker

    # ── Lazy property: portfolio calculator ───────────────────
    @property
    def calculator(self):
        if self._calculator is None:
            from risk.portfolio.portfolio_calculator import PortfolioCalculator
            self._calculator = PortfolioCalculator(tracker=self.tracker)
        return self._calculator

    # ── Live portfolio helpers ─────────────────────────────────
    @property
    def portfolio_value(self):
        """Real total portfolio value from tracker."""
        summary = self.tracker.get_portfolio_summary()
        return float(summary['portfolio_value'])

    @property
    def current_cash(self):
        """Real cash balance from tracker."""
        return float(self.tracker.cash)

    @property
    def num_positions(self):
        """Real number of open positions from tracker."""
        return len(self.tracker.positions)

    # ==========================================================
    # PUBLIC API
    # ==========================================================

    def approve_trade(self, trade):
        """
        Run all risk checks on a proposed trade.

        Parameters
        ----------
        trade : dict
            {
                'ticker':        str,
                'action':        'BUY' | 'SELL' | 'HOLD',
                'quantity':      int,
                'current_price': float,
                'confidence':    float  (0–1),
                'reasoning':     str
            }

        Returns
        -------
        dict
            {
                'approved': bool,
                'trade':    dict,
                'checks':   {check_name: bool},
                'reason':   str   (first failure reason, or 'All checks passed')
            }
        """
        ticker = trade.get('ticker', 'UNKNOWN')
        action = trade.get('action', 'HOLD')

        log.info(f"─" * 50)
        log.info(f"🔍 Risk review: {action} {ticker}")

        checks = {}
        first_failure = None

        if action == 'BUY':
            quantity      = trade.get('quantity', 0)
            current_price = trade.get('current_price', 0)
            trade_value   = quantity * current_price

            log.info(f"   Trade value: ${trade_value:,.2f}")
            log.info(f"   Portfolio:   ${self.portfolio_value:,.2f}")
            log.info(f"   Cash:        ${self.current_cash:,.2f}")
            log.info(f"   Positions:   {self.num_positions}")

            # 1. Position size
            ok, msg = self._check_position_size(trade_value)
            checks['position_size'] = ok
            log.info(f"   {'✅' if ok else '❌'} Position size:   {msg}")
            if not ok and first_failure is None:
                first_failure = msg

            # 2. Cash reserve
            ok, msg = self._check_cash_reserve(trade_value)
            checks['cash_reserve'] = ok
            log.info(f"   {'✅' if ok else '❌'} Cash reserve:    {msg}")
            if not ok and first_failure is None:
                first_failure = msg

            # 3. Max positions
            ok, msg = self._check_max_positions()
            checks['max_positions'] = ok
            log.info(f"   {'✅' if ok else '❌'} Max positions:   {msg}")
            if not ok and first_failure is None:
                first_failure = msg

            # 4. Sector exposure
            ok, msg = self._check_sector_exposure(ticker, trade_value)
            checks['sector_exposure'] = ok
            log.info(f"   {'✅' if ok else '❌'} Sector exposure: {msg}")
            if not ok and first_failure is None:
                first_failure = msg

            # 5. Daily loss circuit breaker
            ok, msg = self._check_daily_loss()
            checks['daily_loss'] = ok
            log.info(f"   {'✅' if ok else '❌'} Daily loss:      {msg}")
            if not ok and first_failure is None:
                first_failure = msg

            # 6. Max drawdown halt
            ok, msg = self._check_drawdown()
            checks['max_drawdown'] = ok
            log.info(f"   {'✅' if ok else '❌'} Max drawdown:    {msg}")
            if not ok and first_failure is None:
                first_failure = msg

        elif action == 'SELL':
            # SELL checks: verify we actually own this stock
            ok, msg = self._check_position_exists(ticker)
            checks['position_exists'] = ok
            log.info(f"   {'✅' if ok else '❌'} Position exists: {msg}")
            if not ok and first_failure is None:
                first_failure = msg

        else:  # HOLD
            checks['hold'] = True
            log.info(f"   ✅ HOLD — no checks required")

        approved = all(checks.values())
        reason   = first_failure if first_failure else 'All checks passed'

        if approved:
            log.info(f"✅ APPROVED:  {action} {ticker}")
        else:
            log.warning(f"❌ REJECTED:  {action} {ticker} — {reason}")

        return {
            'approved': approved,
            'trade':    trade,
            'checks':   checks,
            'reason':   reason
        }

    def get_risk_summary(self):
        """
        Return current risk metrics snapshot.

        Useful for dashboard and daily reports.
        """
        summary = self.tracker.get_portfolio_summary()

        return {
            'portfolio_value':   round(self.portfolio_value, 2),
            'cash':              round(self.current_cash, 2),
            'cash_pct':          round(self.current_cash / self.portfolio_value, 3) if self.portfolio_value > 0 else 0,
            'num_positions':     self.num_positions,
            'total_return_pct':  round(float(summary.get('return_pct', 0)), 2),
            'unrealized_pnl':    round(float(summary.get('total_unrealized_pnl', 0)), 2),
            'realized_pnl':      round(float(summary.get('total_realized_pnl', 0)), 2),
            'sector_breakdown':  self.calculator.get_sector_breakdown(),
            'largest_position':  self.calculator.get_largest_position(),
        }

    # ==========================================================
    # INDIVIDUAL CHECKS  (private)
    # ==========================================================

    def _check_position_size(self, trade_value):
        """Trade must not exceed MAX_POSITION_SIZE (15%) of portfolio."""
        if self.portfolio_value == 0:
            return False, "Portfolio value is zero"

        position_pct = trade_value / self.portfolio_value
        limit        = self.config.MAX_POSITION_SIZE

        if position_pct > limit:
            return False, (
                f"{position_pct:.1%} exceeds max {limit:.0%}  "
                f"(trade=${trade_value:,.0f}, portfolio=${self.portfolio_value:,.0f})"
            )
        return True, f"{position_pct:.1%} ≤ {limit:.0%} limit  ✓"

    def _check_cash_reserve(self, trade_value):
        """After trade, cash must stay ≥ MIN_CASH_RESERVE (10%) of portfolio."""
        cash_after   = self.current_cash - trade_value
        reserve_pct  = cash_after / self.portfolio_value if self.portfolio_value > 0 else 0
        limit        = self.config.MIN_CASH_RESERVE

        if cash_after < 0:
            return False, (
                f"Insufficient cash — need ${trade_value:,.0f}, have ${self.current_cash:,.0f}"
            )
        if reserve_pct < limit:
            return False, (
                f"Cash reserve would drop to {reserve_pct:.1%}, below {limit:.0%} minimum"
            )
        return True, f"Cash reserve after trade: {reserve_pct:.1%}  ✓"

    def _check_max_positions(self):
        """Open positions must stay below MAX_TOTAL_POSITIONS (15)."""
        limit = self.config.MAX_TOTAL_POSITIONS

        if self.num_positions >= limit:
            return False, f"{self.num_positions} positions already at max {limit}"
        return True, f"{self.num_positions}/{limit} positions  ✓"

    def _check_sector_exposure(self, ticker, trade_value):
        """
        After trade, sector exposure must stay within MAX_SECTOR_EXPOSURE limits.

        Uses portfolio_calculator for sector mapping and current breakdown.
        Sector keys in RiskConfig are lowercase (e.g. 'technology').
        """
        try:
            sector           = self.calculator._get_sector(ticker).lower()
            current_sectors  = self.calculator.get_sector_breakdown()

            # Convert keys to lowercase for matching
            current_sectors_lower = {k.lower(): v for k, v in current_sectors.items()}

            current_pct  = current_sectors_lower.get(sector, 0.0)
            new_trade_pct = trade_value / self.portfolio_value if self.portfolio_value > 0 else 0
            new_pct       = current_pct + new_trade_pct

            # Look up the limit for this sector (fall back to 'other')
            limit = self.config.MAX_SECTOR_EXPOSURE.get(
                sector,
                self.config.MAX_SECTOR_EXPOSURE.get('other', 0.40)
            )

            if new_pct > limit:
                return False, (
                    f"{sector} would reach {new_pct:.1%}, exceeds {limit:.0%} limit"
                )
            return True, f"{sector} exposure after trade: {new_pct:.1%} ≤ {limit:.0%}  ✓"

        except Exception as e:
            log.warning(f"Sector check failed ({e}), allowing trade")
            return True, "Sector check skipped (no data)"

    def _check_daily_loss(self):
        """
        Portfolio must not have already lost more than MAX_DAILY_LOSS (3%) today.

        Uses portfolio_history.csv to get today's starting value.
        """
        try:
            import pandas as pd
            from datetime import datetime, timezone

            history_file = self.tracker.history_file

            import os
            if not os.path.exists(history_file):
                return True, "No history yet — check skipped"

            df = pd.read_csv(history_file)
            if df.empty:
                return True, "Empty history — check skipped"

            # Get today's date
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

            # Filter today's rows
            df['date'] = pd.to_datetime(df['timestamp']).dt.strftime('%Y-%m-%d')
            today_rows = df[df['date'] == today]

            if today_rows.empty:
                return True, "No trades today yet — check skipped"

            # Opening value = first record of today
            opening_value = float(today_rows.iloc[0]['total_value'])
            current_value = self.portfolio_value

            if opening_value == 0:
                return True, "Opening value zero — check skipped"

            daily_loss_pct = (current_value - opening_value) / opening_value

            limit = -self.config.MAX_DAILY_LOSS  # negative = loss

            if daily_loss_pct < limit:
                return False, (
                    f"Daily loss {daily_loss_pct:.1%} exceeds {self.config.MAX_DAILY_LOSS:.0%} limit — CIRCUIT BREAKER"
                )
            return True, f"Daily P&L: {daily_loss_pct:+.1%}  ✓"

        except Exception as e:
            log.warning(f"Daily loss check failed ({e}), allowing trade")
            return True, "Daily loss check skipped"

    def _check_drawdown(self):
        """
        Portfolio must not be in a drawdown exceeding MAX_DRAWDOWN_BEFORE_HALT (15%).
        """
        try:
            max_dd_info = self.calculator.calculate_max_drawdown()
            max_dd      = abs(float(max_dd_info.get('max_drawdown', 0)))  # positive %
            limit       = self.config.MAX_DRAWDOWN_BEFORE_HALT

            if max_dd > limit:
                return False, (
                    f"Drawdown {max_dd:.1f}% exceeds {limit:.0f}% halt limit — TRADING HALTED"
                )
            return True, f"Max drawdown: {max_dd:.1f}% ≤ {limit:.0f}% limit  ✓"

        except Exception as e:
            log.warning(f"Drawdown check failed ({e}), allowing trade")
            return True, "Drawdown check skipped"

    def _check_position_exists(self, ticker):
        """For SELL orders: verify we actually own this ticker."""
        ticker = ticker.strip().upper()
        owned = [p.ticker for p in self.tracker.positions]

        if ticker not in owned:
            return False, f"No position in {ticker} to sell (owned: {owned})"
        return True, f"{ticker} position exists  ✓"


# ── Global instance ────────────────────────────────────────────
risk_manager = RiskManager()


# ── Standalone test ────────────────────────────────────────────
if __name__ == "__main__":
    from risk.portfolio.portfolio_tracker import PositionTracker

    log.info("=" * 60)
    log.info("TESTING RISK MANAGER")
    log.info("=" * 60)

    # Fresh tracker with $20,000 (matches TradingConfig)
    tracker = PositionTracker(initial_capital=TradingConfig.INITIAL_CAPITAL)
    rm = RiskManager()
    rm._tracker = tracker

    # ── Test 1: Normal trade — should PASS ──────────────────
    log.info("\n[TEST 1] Normal trade ($1,000 = 5% of $20k) → expect APPROVED")
    result = rm.approve_trade({
        'ticker': 'AAPL',
        'action': 'BUY',
        'quantity': 5,
        'current_price': 200.0,   # $1,000 total = 5%
        'confidence': 0.75,
        'reasoning': 'RSI oversold'
    })
    log.info(f"Result: {'✅ APPROVED' if result['approved'] else '❌ REJECTED'}")
    log.info(f"Reason: {result['reason']}")

    # ── Test 2: Oversized trade — should FAIL position size ──
    log.info("\n[TEST 2] Oversized trade ($4,000 = 20% of $20k) → expect REJECTED")
    result = rm.approve_trade({
        'ticker': 'MSFT',
        'action': 'BUY',
        'quantity': 10,
        'current_price': 400.0,   # $4,000 total = 20% > 15% limit
        'confidence': 0.80,
        'reasoning': 'Momentum signal'
    })
    log.info(f"Result: {'✅ APPROVED' if result['approved'] else '❌ REJECTED'}")
    log.info(f"Reason: {result['reason']}")

    # ── Test 3: SELL without owning stock — should FAIL ──────
    log.info("\n[TEST 3] SELL NVDA (not owned) → expect REJECTED")
    result = rm.approve_trade({
        'ticker': 'NVDA',
        'action': 'SELL',
        'quantity': 5,
        'current_price': 500.0,
        'confidence': 0.70,
        'reasoning': 'Take profit'
    })
    log.info(f"Result: {'✅ APPROVED' if result['approved'] else '❌ REJECTED'}")
    log.info(f"Reason: {result['reason']}")

    # ── Test 4: Risk summary ──────────────────────────────────
    log.info("\n[TEST 4] Risk summary")
    summary = rm.get_risk_summary()
    log.info(f"Portfolio value:  ${summary['portfolio_value']:,.2f}")
    log.info(f"Cash:             ${summary['cash']:,.2f} ({summary['cash_pct']:.0%})")
    log.info(f"Open positions:   {summary['num_positions']}")

    log.info("\n✅ ALL TESTS COMPLETED!")







#from config import RiskConfig
#from logger import get_logger, setup_logging
#
#setup_logging()
#logging = get_logger("risk.risk_manager")
#
#class RiskManager:
#    def __init__(self):
#        self.config = RiskConfig()
#        self.current_portfolio_value = 10000
#        self.current_cach = 1000
#        self.num_positions = 20
#        logging.info("Using test risk manager (Message for B3aybach)")
#
#    def check_position_size(self, size):
#        """Check if position size is limited"""
#        if size > self.config.MAX_POSITION_SIZE:
#            return False, f"Position size {size:.1%} exceeds max {self.config.MAX_POSITION_SIZE} "
#        return True, "Position size Ok"
#
#    def check_cash_reserve(self, trade_value):
#        cash_after_trade = self.current_cach - trade_value
#        cash_pct = cash_after_trade / self.current_portfolio_value
#        if cash_pct < self.config.MIN_CASH_RESERVE:
#            return False, f"insuffcient cash reserve would have {cash_pct:.1%}"
#        return True, "cash reserve Ok"
#
#    def approve_trade(self, trade):
#        logging.info(f"\nReviewing trade: {trade['ticker']}")
#        checks = {}
#        if trade['action'] == 'BUY':
#            trade_value = trade.get('quantity', 0) * trade.get('current_price', 0)
#            position_size = trade_value / self.current_portfolio_value
#
#            """check position size"""
#            passed, msg = self.check_position_size(trade_value)
#            checks['position_size'] = passed
#            logging.info(f"{msg}")
#
#            """check cash reserve"""
#            passed, msg = self.check_cash_reserve(trade_value)
#            checks['cash_reserve'] = passed
#            logging.info(f"{msg}")
#
#            """check max position"""
#            if self.num_positions >= self.config.MAX_TOTAL_POSITIONS:
#                checks['max_position'] = False
#                logging.warning(f"{self.num_positions} is too much, Max positions is: {self.config.MAX_TOTAL_POSITIONS}")
#            else:
#                checks['max_position'] = True
#                logging.info(f"{self.num_positions} is good, Max positions is: {self.config.MAX_TOTAL_POSITIONS}")
#
#        else: # sell or hold b3aybach logic
#            checks = {'position_size': True, 'cash_reserve': True, 'max_positions': True}
#            logging.info("SELL/HOLD order - checks passed")
#        aproved = all(checks.values())
#        if aproved:
#            logging.info("trade APPROVED")
#        else:
#            logging.info("Trade REJECTED")
#
#        return {
#            'trade': trade,
#            'checks': checks,
#            'approved': aproved
#        }
#    
#risk_manager = RiskManager()
#
#if __name__ == "__main__":
#    logging.info("Testing risk manager...")
#    test_trade = {
#        'ticker': 'AAPL',
#        'action': 'BUY',
#        'quantity': 7,
#        'current_price': 25.00
#    }
#
#    result = risk_manager.approve_trade(test_trade)
#    logging.info(f"Result: {result}")