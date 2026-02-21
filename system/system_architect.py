"""
System Architect — TradingSystem
=================================
The brain of the entire trading system.

Orchestrates every component in the correct order:
    1. Update prices      (portfolio_tracker)
    2. Check stop-losses  (portfolio_tracker → remove_position)
    3. Scan watchlist     (data → strategy → signal_aggregator → risk → execute)
    4. Save daily report  (portfolio_calculator)

Daily flow:
    run_daily_analysis()
        ├── update_all_prices()
        ├── check_stop_losses()
        ├── scan_watchlist()
        │     └── analyze_single_stock(ticker)
        │           ├── data_access.get_price_history()
        │           ├── strategy_engine.analyze()         ← RSI signal
        │           ├── tradingagents.analyze()           ← AI signal (optional)
        │           ├── _combine_signals()                ← merge both
        │           ├── risk_manager.approve_trade()      ← 6 checks
        │           └── _execute_trade()                  ← tracker.add_position()
        └── save_daily_report()

Author: Mehdi (System Architect)
"""

import os
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from config import BaseConfig, TradingConfig, RiskConfig
from data.data_enginner import data_access
from strategies.strategy_researcher import strategy_engine
from risk.risk_manager import risk_manager
from logger import setup_logging, get_logger

setup_logging()
log = get_logger('system.system_architect')


class TradingSystem:
    """
    Central orchestrator — calls every other component in the right order.

    Components it owns:
    - data_access          → price data
    - strategy_engine      → RSI signals
    - risk_manager         → 6-check gate (reads portfolio_tracker + calculator)
    - portfolio_tracker    → positions, cash, P&L  (via risk_manager.tracker)
    - portfolio_calculator → risk metrics           (via risk_manager.calculator)
    - tradingagents        → AI signal (optional, controlled by TradingConfig)
    """

    def __init__(self):
        log.info("=" * 60)
        log.info("  TRADING SYSTEM INITIALIZING")
        log.info("=" * 60)

        # Validate environment
        BaseConfig.validate()

        # Core components
        self.data     = data_access
        self.strategy = strategy_engine
        self.risk     = risk_manager
        self.config   = TradingConfig()
        self.rconfig  = RiskConfig()

        # TradingAgents (AI signal) — optional
        self.ta = None
        if self.config.USE_TRADING_AGENT:
            try:
                from system.tradingagents_integration import TradingAgentsIntegration
                self.ta = TradingAgentsIntegration()
                log.info("✅ TradingAgents integration loaded")
            except Exception as e:
                log.warning(f"⚠️  TradingAgents unavailable: {e}. Running RSI-only.")

        # Report output directory
        self.report_dir = 'risk/reports'
        os.makedirs(self.report_dir, exist_ok=True)

        log.info(f"✅ System ready")
        log.info(f"   Environment:  {BaseConfig.ENVIRONMENT}")
        log.info(f"   Capital:      ${TradingConfig.INITIAL_CAPITAL:,.0f}")
        log.info(f"   Watchlist:    {len(self.config.DEFAULT_WATCHLIST)} stocks")
        log.info(f"   AI signals:   {'ON' if self.ta else 'OFF'}")
        log.info("=" * 60)

    # ================================================================
    # PROPERTIES — live shortcuts to portfolio state
    # ================================================================

    @property
    def tracker(self):
        """Live access to portfolio_tracker (via risk_manager to avoid circular imports)."""
        return self.risk.tracker

    @property
    def calculator(self):
        """Live access to portfolio_calculator."""
        return self.risk.calculator

    # ================================================================
    # STEP 1 — UPDATE PRICES
    # ================================================================

    def update_all_prices(self):
        """
        Fetch latest prices for every open position and update the tracker.

        Must be called FIRST every day before any analysis — otherwise
        the risk manager checks stale portfolio values.

        Returns:
            dict: {ticker: price} for all updated tickers
        """
        positions = self.tracker.positions

        if not positions:
            log.info("No open positions to update.")
            return {}

        tickers = [p.ticker for p in positions]
        log.info(f"📡 Updating prices for {len(tickers)} positions: {tickers}")

        updated_prices = {}
        failed = []

        for ticker in tickers:
            try:
                price = self.data.get_latest_price(ticker)
                if price is not None:
                    updated_prices[ticker] = float(price)
                    log.debug(f"   {ticker}: ${float(price):.2f}")
                else:
                    log.warning(f"   {ticker}: no price data returned")
                    failed.append(ticker)
            except Exception as e:
                log.error(f"   {ticker}: price fetch failed — {e}")
                failed.append(ticker)

        if updated_prices:
            self.tracker.update_prices(updated_prices)
            log.info(f"✅ Updated {len(updated_prices)} prices"
                     + (f"  |  ⚠️ Failed: {failed}" if failed else ""))
        else:
            log.warning("⚠️ No prices were updated")

        return updated_prices

    # ================================================================
    # STEP 2 — CHECK STOP-LOSSES
    # ================================================================

    def check_stop_losses(self):
        """
        Proactively check every open position against:
        1. Stop-loss price  (entry_price × (1 − stop_loss_pct))
        2. Max holding days (RSI strategy: 5 days max)

        This is what was MISSING from the old system_architect.
        Without this, losing positions stay open forever.

        Returns:
            list: Tickers that were force-sold
        """
        positions = self.tracker.positions

        if not positions:
            return []

        log.info(f"🔍 Checking stop-losses for {len(positions)} positions...")

        stop_loss_pct  = self.rconfig.DEFAULT_STOP_LOSS_PCT   # 0.05 = 5%
        max_hold_days  = 5                                      # RSI strategy holding period

        force_sold = []

        # Iterate over a copy — we may modify self.tracker.positions during loop
        for position in list(positions):
            ticker        = position.ticker
            entry_price   = float(position.entry_price)
            current_price = float(position.current_price)
            entry_date    = position.entry_date

            # ── Check 1: Stop-loss price ──────────────────────
            stop_price = entry_price * (1 - stop_loss_pct)

            if current_price <= stop_price:
                loss_pct = (current_price - entry_price) / entry_price
                log.warning(f"🛑 STOP-LOSS: {ticker}")
                log.warning(f"   Entry=${entry_price:.2f}  Current=${current_price:.2f}  "
                             f"Stop=${stop_price:.2f}  Loss={loss_pct:.1%}")

                sold = self._force_sell(ticker, current_price, reason='STOP_LOSS')
                if sold:
                    force_sold.append(ticker)
                continue   # don't double-check holding period

            # ── Check 2: Max holding period ───────────────────
            try:
                entry_dt = datetime.fromisoformat(entry_date.replace('Z', '+00:00'))
                days_held = (datetime.now(timezone.utc) - entry_dt).days

                if days_held >= max_hold_days:
                    gain_pct = (current_price - entry_price) / entry_price
                    log.info(f"⏰ MAX HOLD: {ticker} held {days_held} days "
                              f"(entry=${entry_price:.2f}, now=${current_price:.2f}, {gain_pct:+.1%})")

                    sold = self._force_sell(ticker, current_price, reason='MAX_HOLD_PERIOD')
                    if sold:
                        force_sold.append(ticker)

            except Exception as e:
                log.warning(f"   {ticker}: Could not check holding period — {e}")

        if force_sold:
            log.info(f"✅ Force-sold {len(force_sold)} positions: {force_sold}")
        else:
            log.info("✅ No stop-losses triggered")

        return force_sold

    def _force_sell(self, ticker, current_price, reason):
        """
        Execute a forced sell (stop-loss or max hold period).

        Runs through risk_manager for audit trail, then executes.

        Returns:
            bool: True if sold successfully
        """
        position = self.tracker._find_position(ticker)
        if not position:
            return False

        trade = {
            'ticker':        ticker,
            'action':        'SELL',
            'quantity':      float(position.quantity),
            'current_price': current_price,
            'confidence':    1.0,
            'reasoning':     f'Forced exit: {reason}'
        }

        approval = self.risk.approve_trade(trade)

        if approval['approved']:
            try:
                result = self.tracker.remove_position(
                    ticker=ticker,
                    quantity=float(position.quantity),
                    exit_price=current_price
                )
                pnl = float(result['realized_pnl']) if result else 0
                log.info(f"   ✅ {reason}: sold {ticker} — P&L: ${pnl:+,.2f}")
                return True
            except Exception as e:
                log.error(f"   ❌ Force sell failed for {ticker}: {e}")
                return False
        else:
            # SELL should almost always pass — log if it doesn't
            log.error(f"   ❌ Force sell REJECTED by risk manager: {approval['reason']}")
            return False

    # ================================================================
    # STEP 3 — ANALYZE SINGLE STOCK
    # ================================================================

    def analyze_single_stock(self, ticker):
        """
        Full analysis pipeline for one ticker:
            data → RSI signal → AI signal → combine → risk check → execute

        Returns:
            dict: Result with keys: ticker, action, status, signal, approval
        """
        log.info(f"\n{'─'*50}")
        log.info(f"📊 Analyzing {ticker}")

        # ── 1. Fetch price data ───────────────────────────────
        price_data = self.data.get_price_history(ticker, days=90)

        if price_data is None or price_data.empty:
            log.error(f"   No data for {ticker}")
            return self._result(ticker, 'HOLD', 'NO_DATA', 'No price data available')

        # ── 2. RSI strategy signal ────────────────────────────
        rsi_signal = self.strategy.analyze(ticker, price_data)

        if rsi_signal is None:
            log.error(f"   RSI strategy failed for {ticker}")
            return self._result(ticker, 'HOLD', 'ERROR', 'Strategy failed')

        log.info(f"   RSI signal:  {rsi_signal['action']} "
                 f"(confidence={rsi_signal['confidence']:.0%}, "
                 f"RSI={rsi_signal.get('rsi', '?')})")

        # ── 3. AI signal (optional) ───────────────────────────
        ta_signal = None
        if self.ta and self.config.USE_TRADING_AGENT:
            try:
                ta_signal = self.ta.analyze(ticker)
                log.info(f"   AI signal:   {ta_signal['action']} "
                         f"(confidence={ta_signal.get('confidence', 0):.0%})")
            except Exception as e:
                log.warning(f"   AI signal failed for {ticker}: {e}. Using RSI only.")

        # ── 4. Combine signals ────────────────────────────────
        final_signal = self._combine_signals(rsi_signal, ta_signal)
        log.info(f"   Final:       {final_signal['action']} "
                 f"(confidence={final_signal['confidence']:.0%})")
        log.info(f"   Reasoning:   {final_signal['reasoning'][:80]}...")

        # ── 5. Route by action ────────────────────────────────
        if final_signal['action'] == 'BUY':
            return self._handle_buy(ticker, final_signal)

        elif final_signal['action'] == 'SELL':
            return self._handle_sell(ticker, final_signal)

        else:  # HOLD
            return self._result(ticker, 'HOLD', 'NO_ACTION', final_signal['reasoning'],
                                signal=final_signal)

    # ── Buy handler ──────────────────────────────────────────────
    def _handle_buy(self, ticker, signal):
        """Process a BUY signal through risk checks and execution."""

        # Calculate quantity: 5% of portfolio per trade
        position_size_pct = 0.05
        portfolio_value   = self.risk.portfolio_value
        trade_value       = portfolio_value * position_size_pct
        quantity          = int(trade_value / signal['current_price'])

        if quantity < 1:
            log.warning(f"   Quantity too small (<1 share) for {ticker} at ${signal['current_price']:.2f}")
            return self._result(ticker, 'HOLD', 'TOO_SMALL',
                                f'Cannot afford even 1 share at ${signal["current_price"]:.2f}')

        trade_proposal = {
            'ticker':        ticker,
            'action':        'BUY',
            'quantity':      quantity,
            'current_price': signal['current_price'],
            'confidence':    signal['confidence'],
            'reasoning':     signal['reasoning']
        }

        log.info(f"\n   📋 Trade proposal: BUY {quantity} × {ticker} @ ${signal['current_price']:.2f} "
                 f"= ${quantity * signal['current_price']:,.0f}")

        # Risk gate
        approval = self.risk.approve_trade(trade_proposal)

        if not approval['approved']:
            log.warning(f"   ❌ Rejected: {approval['reason']}")
            return self._result(ticker, 'HOLD', 'REJECTED', approval['reason'],
                                signal=signal, approval=approval)

        # Execute
        try:
            self.tracker.add_position(
                ticker=ticker,
                quantity=quantity,
                entry_price=signal['current_price']
            )
            log.info(f"   ✅ Executed: BUY {quantity} × {ticker} @ ${signal['current_price']:.2f}")

            return {
                'ticker':   ticker,
                'action':   'BUY',
                'quantity': quantity,
                'price':    signal['current_price'],
                'status':   'EXECUTED',
                'signal':   signal,
                'approval': approval
            }
        except Exception as e:
            log.error(f"   ❌ Execution failed for {ticker}: {e}")
            return self._result(ticker, 'HOLD', 'EXEC_FAILED', str(e),
                                signal=signal, approval=approval)

    # ── Sell handler ─────────────────────────────────────────────
    def _handle_sell(self, ticker, signal):
        """Process a SELL signal — only if we own this stock."""

        # Check if we own it
        position = self.tracker._find_position(ticker)

        if not position:
            log.info(f"   SELL signal for {ticker} but no position held — HOLD")
            return self._result(ticker, 'HOLD', 'NOT_OWNED',
                                f'SELL signal but no {ticker} position open',
                                signal=signal)

        trade_proposal = {
            'ticker':        ticker,
            'action':        'SELL',
            'quantity':      float(position.quantity),
            'current_price': signal['current_price'],
            'confidence':    signal['confidence'],
            'reasoning':     signal['reasoning']
        }

        log.info(f"\n   📋 Trade proposal: SELL {position.quantity} × {ticker} "
                 f"@ ${signal['current_price']:.2f}")

        # Risk gate
        approval = self.risk.approve_trade(trade_proposal)

        if not approval['approved']:
            log.warning(f"   ❌ Sell rejected: {approval['reason']}")
            return self._result(ticker, 'HOLD', 'REJECTED', approval['reason'],
                                signal=signal, approval=approval)

        # Execute
        try:
            result = self.tracker.remove_position(
                ticker=ticker,
                quantity=float(position.quantity),
                exit_price=signal['current_price']
            )
            pnl = float(result['realized_pnl']) if result else 0
            log.info(f"   ✅ Executed: SELL {ticker} — Realized P&L: ${pnl:+,.2f}")

            return {
                'ticker':       ticker,
                'action':       'SELL',
                'quantity':     float(position.quantity),
                'price':        signal['current_price'],
                'realized_pnl': pnl,
                'status':       'EXECUTED',
                'signal':       signal,
                'approval':     approval
            }
        except Exception as e:
            log.error(f"   ❌ Sell execution failed for {ticker}: {e}")
            return self._result(ticker, 'HOLD', 'EXEC_FAILED', str(e),
                                signal=signal, approval=approval)

    # ================================================================
    # STEP 3b — COMBINE SIGNALS
    # ================================================================

    def _combine_signals(self, rsi_signal, ta_signal=None):
        """
        Merge RSI signal and AI signal into one final decision.

        Rules:
        - Only RSI available → use RSI signal as-is
        - Both agree (same action) → boost confidence, use combined reasoning
        - Both disagree → HOLD (conflict, wait for clarity)
        - One says HOLD → defer to the other but lower confidence

        Returns:
            dict: Same signal format as rsi_signal
        """
        # No AI signal — use RSI directly
        if ta_signal is None or ta_signal.get('action') is None:
            rsi_signal['source'] = 'RSI_ONLY'
            return rsi_signal

        rsi_action = rsi_signal.get('action', 'HOLD')
        ta_action  = ta_signal.get('action', 'HOLD')
        rsi_conf   = rsi_signal.get('confidence', 0.5)
        ta_conf    = ta_signal.get('confidence', 0.5)

        # ── Both agree ────────────────────────────────────────
        if rsi_action == ta_action:
            # Boost confidence when both models agree
            combined_conf = min(0.95, (rsi_conf + ta_conf) / 2 + 0.10)
            return {
                **rsi_signal,
                'confidence': combined_conf,
                'source':     'RSI+AI_AGREE',
                'reasoning':  (f"[RSI] {rsi_signal.get('reasoning', '')} "
                               f"| [AI] {ta_signal.get('reasoning', '')}"),
            }

        # ── One says HOLD ─────────────────────────────────────
        if rsi_action == 'HOLD':
            return {**ta_signal, 'confidence': ta_conf * 0.8, 'source': 'AI_ONLY_LOW'}
        if ta_action == 'HOLD':
            return {**rsi_signal, 'confidence': rsi_conf * 0.8, 'source': 'RSI_ONLY_LOW'}

        # ── Direct conflict (BUY vs SELL) ─────────────────────
        log.info(f"   ⚠️  Signal conflict: RSI={rsi_action} vs AI={ta_action} → HOLD")
        return {
            **rsi_signal,
            'action':     'HOLD',
            'confidence': 0.30,
            'source':     'CONFLICT_HOLD',
            'reasoning':  f'Conflicting signals: RSI={rsi_action}, AI={ta_action}. Waiting for clarity.',
        }

    # ================================================================
    # STEP 3c — SCAN WATCHLIST
    # ================================================================

    def scan_watchlist(self, watchlist=None):
        """
        Analyze every stock in the watchlist sequentially.

        Args:
            watchlist: list of tickers (default: TradingConfig.DEFAULT_WATCHLIST)

        Returns:
            dict: Summary with all results
        """
        if watchlist is None:
            watchlist = self.config.DEFAULT_WATCHLIST

        log.info(f"\n{'═'*60}")
        log.info(f"  SCANNING WATCHLIST ({len(watchlist)} stocks)")
        log.info(f"{'═'*60}")

        results      = []
        executed_buy  = []
        executed_sell = []
        rejected      = []
        hold          = []

        for ticker in watchlist:
            try:
                decision = self.analyze_single_stock(ticker)
                if decision:
                    results.append(decision)
                    status = decision.get('status', '')
                    action = decision.get('action', 'HOLD')

                    if status == 'EXECUTED' and action == 'BUY':
                        executed_buy.append(ticker)
                    elif status == 'EXECUTED' and action == 'SELL':
                        executed_sell.append(ticker)
                    elif status == 'REJECTED':
                        rejected.append(ticker)
                    else:
                        hold.append(ticker)

            except Exception as e:
                log.error(f"   Error analyzing {ticker}: {e}")
                import traceback
                log.debug(traceback.format_exc())
                continue

        # ── Summary ───────────────────────────────────────────
        log.info(f"\n{'─'*50}")
        log.info(f"  SCAN COMPLETE")
        log.info(f"{'─'*50}")
        log.info(f"  Analyzed:      {len(results)}/{len(watchlist)}")
        log.info(f"  Bought:        {len(executed_buy)}   {executed_buy}")
        log.info(f"  Sold:          {len(executed_sell)}  {executed_sell}")
        log.info(f"  Risk rejected: {len(rejected)}  {rejected}")
        log.info(f"  Hold:          {len(hold)}")
        log.info(f"{'─'*50}")

        # Portfolio state after scan
        summary = self.tracker.get_portfolio_summary()
        log.info(f"  Portfolio:     ${float(summary['portfolio_value']):,.2f}")
        log.info(f"  Cash:          ${float(summary['cash']):,.2f} "
                 f"({float(summary['cash_pct']):.1f}%)")
        log.info(f"  Positions:     {summary['total_positions']}")
        log.info(f"  Unrealized:    ${float(summary['total_unrealized_pnl']):+,.2f}")
        log.info(f"  Realized:      ${float(summary['total_realized_pnl']):+,.2f}")
        log.info(f"  Return:        {float(summary['return_pct']):+.2f}%")

        return {
            'results':       results,
            'executed_buy':  executed_buy,
            'executed_sell': executed_sell,
            'rejected':      rejected,
            'hold':          hold,
            'summary':       {k: float(v) for k, v in summary.items()
                              if k not in ['cash', 'positions_value',
                                           'portfolio_value',
                                           'total_unrealized_pnl',
                                           'total_realized_pnl',
                                           'return_pct',
                                           'cash_pct', 'total_positions']
                              or True}
        }

    # ================================================================
    # STEP 4 — SAVE DAILY REPORT
    # ================================================================

    def save_daily_report(self, scan_results=None):
        """
        Generate and save the daily risk + performance report.

        Written to: risk/reports/risk_YYYYMMDD.json

        Returns:
            str: Path to saved report
        """
        log.info("📋 Generating daily report...")

        today = datetime.now().strftime('%Y%m%d')
        filepath = os.path.join(self.report_dir, f"risk_{today}.json")

        try:
            # Get portfolio summary
            portfolio_summary = self.tracker.get_portfolio_summary()
            
            # Get risk metrics from calculator (returns None if no positions)
            risk_report = self.calculator.generate_risk_report()
            
            # Handle empty portfolio case
            if risk_report is None:
                risk_report = {
                    'portfolio_summary': {},
                    'risk_metrics': {},
                    'sector_breakdown': {},
                    'position_concentration': {}
                }

            # Build full report
            report = {
                'date':          datetime.now().isoformat(),
                'portfolio':     {
                    'portfolio_value': float(portfolio_summary.get('portfolio_value', 0)),
                    'cash':            float(portfolio_summary.get('cash', 0)),
                    'cash_pct':        float(portfolio_summary.get('cash_pct', 0)),
                    'positions':       int(portfolio_summary.get('total_positions', 0)),
                    'unrealized_pnl':  float(portfolio_summary.get('total_unrealized_pnl', 0)),
                    'realized_pnl':    float(portfolio_summary.get('total_realized_pnl', 0)),
                    'return_pct':      float(portfolio_summary.get('return_pct', 0))
                },
                'risk_metrics':  risk_report.get('risk_metrics', {}),
                'sector':        risk_report.get('sector_breakdown', {}),
                'concentration': risk_report.get('position_concentration', {}),
                'scan_results':  {
                    'executed_buy':  scan_results.get('executed_buy', []) if scan_results else [],
                    'executed_sell': scan_results.get('executed_sell', []) if scan_results else [],
                    'rejected':      scan_results.get('rejected', []) if scan_results else [],
                } if scan_results else {}
            }

            # Convert Decimal values to float for JSON serialization
            report = _serialize(report)

            with open(filepath, 'w') as f:
                json.dump(report, f, indent=2)

            log.info(f"✅ Report saved: {filepath}")
            return filepath

        except Exception as e:
            log.error(f"❌ Failed to save report: {e}")
            import traceback
            log.debug(traceback.format_exc())
            return None

    # ================================================================
    # MAIN ENTRY POINT
    # ================================================================

    def run_daily_analysis(self, watchlist=None):
        """
        Full daily trading cycle. Call this once per trading day.

        Steps:
            1. Update all open-position prices
            2. Check & enforce stop-losses
            3. Scan watchlist → analyze → execute
            4. Save daily report

        Returns:
            dict: Full results from the day's trading session
        """
        log.info("\n" + "█" * 60)
        log.info(f"  DAILY TRADING ANALYSIS")
        log.info(f"  {datetime.now().strftime('%A, %B %d %Y  %H:%M:%S')}")
        log.info("█" * 60)

        # ── 1. Update prices ──────────────────────────────────
        log.info("\n[1/4] Updating portfolio prices...")
        updated_prices = self.update_all_prices()

        # ── 2. Check stop-losses ──────────────────────────────
        log.info("\n[2/4] Checking stop-losses...")
        force_sold = self.check_stop_losses()

        # ── 3. Scan watchlist ─────────────────────────────────
        log.info("\n[3/4] Scanning watchlist...")
        scan_results = self.scan_watchlist(watchlist)

        # ── 4. Save report ────────────────────────────────────
        log.info("\n[4/4] Saving daily report...")
        report_path = self.save_daily_report(scan_results)

        log.info("\n" + "█" * 60)
        log.info("  DAILY ANALYSIS COMPLETE")
        log.info("█" * 60 + "\n")

        return {
            'date':           datetime.now().isoformat(),
            'updated_prices': updated_prices,
            'force_sold':     force_sold,
            'scan':           scan_results,
            'report_path':    report_path
        }

    # ================================================================
    # HELPERS
    # ================================================================

    def _result(self, ticker, action, status, reason,
                signal=None, approval=None):
        """Build a standard result dict."""
        return {
            'ticker':   ticker,
            'action':   action,
            'status':   status,
            'reason':   reason,
            'signal':   signal,
            'approval': approval
        }

    def display_portfolio(self):
        """Print current portfolio state to console."""
        self.tracker.display_positions()

    def display_risk(self):
        """Print current risk metrics to console."""
        self.calculator.print_risk_report()


# ── Utility: make any dict JSON-serializable ──────────────────
def _serialize(obj):
    """Recursively convert Decimal/ndarray/etc. to JSON-safe types."""
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, 'item'):   # numpy scalar
        return obj.item()
    return obj


# ── Global instance ───────────────────────────────────────────
trading_system = TradingSystem()


# ================================================================
# STANDALONE TEST
# ================================================================

if __name__ == "__main__":
    log.info("Running system_architect test...\n")

    # ── Quick test (small watchlist, no AI to save time) ─────
    trading_system.config.USE_TRADING_AGENT = False
    trading_system.ta = None

    log.info("TEST 1: Single stock analysis")
    result = trading_system.analyze_single_stock('AAPL')
    log.info(f"Result: action={result['action']}, status={result['status']}")

    log.info("\nTEST 2: Watchlist scan (3 stocks)")
    scan = trading_system.scan_watchlist(['AAPL', 'MSFT', 'NVDA'])
    log.info(f"Bought: {scan['executed_buy']}")
    log.info(f"Held:   {scan['hold']}")

    log.info("\nTEST 3: Portfolio state")
    trading_system.display_portfolio()

    log.info("\nTEST 4: Stop-loss check")
    sold = trading_system.check_stop_losses()
    log.info(f"Force-sold: {sold}")

    log.info("\nTEST 5: Full daily run")
    daily = trading_system.run_daily_analysis(['AAPL', 'MSFT', 'NVDA'])
    log.info(f"Report saved: {daily['report_path']}")