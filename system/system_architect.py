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

Author: Mehdi 
"""

import os
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from config import BaseConfig, TradingConfig, RiskConfig
from data.data_engineer import data_access
from strategies.strategy_researcher import strategy_engine   # owns ALL strategy instances
from risk.risk_manager import risk_manager
from risk.position_sizer import PositionSizer
from risk.trade_audit import trade_audit
from system.signal_aggregator import SignalAggregator
from logger import  get_logger
from system.alert_manager import alert_manager

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

        
        BaseConfig.validate()

        # Core components
        self.data       = data_access
        self.strategy   = strategy_engine   # StrategyResearcher owns ALL strategies
        self.aggregator = SignalAggregator()
        self.risk       = risk_manager
        self.config     = TradingConfig()
        self.rconfig    = RiskConfig()
        self.sizer      = PositionSizer()        # position sizing (fixed fractional or Kelly)
        self.audit      = trade_audit            # JSONL trade audit log

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

        # ── Data pipeline health check ─────────────────────────
        # Runs once at startup. CRITICAL failures are logged as errors
        # but never crash the system — Mehdi can decide whether to abort.
        try:
            from data.health_check import run_health_check
            health = run_health_check()
            self.health_status = health['status']
            if health['status'] == 'CRITICAL':
                log.error(
                    "⚠️  Data pipeline health check: CRITICAL — "
                    "system may not function correctly. "
                    "Run: python -m data.health_check for details."
                )
        except Exception as e:
            log.warning(f"Health check could not run: {e}")
            self.health_status = 'UNKNOWN'

        log.info(f"✅ System ready")
        log.info(f"   Environment:  {BaseConfig.ENVIRONMENT}")
        log.info(f"   Capital:      ${TradingConfig.INITIAL_CAPITAL:,.0f}")
        log.info(f"   Watchlist:    {len(self.config.DEFAULT_WATCHLIST)} stocks")
        log.info(f"   AI signals:   {'ON' if self.ta else 'OFF'}")
        log.info(f"   Data health:  {self.health_status}")
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
                self.audit.record_stop_loss(
                    ticker=ticker,
                    entry_price=float(position.entry_price),
                    exit_price=current_price,
                    quantity=int(float(position.quantity)),
                    realized_pnl=pnl,
                    reason=reason,
                )
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
        Analyze stock using ALL enabled strategies.

        Automatically detects and uses:
        - RSI Strategy (always enabled)
        - Momentum Strategy (if exists)
        - AI/TradingAgents (if enabled)
        - Any future strategies you add

        Parameters
        ----------
        ticker : str
            Stock symbol to analyze

        Returns
        -------
        dict : Combined signal from all strategies
        """
        log.info(f"🔍 Analyzing {ticker}")

        try:
            # ── 1. Get Price Data ──────────────────────────────────
            df = data_access.get_price_history(ticker, days=90)

            if df is None or df.empty:
                log.warning(f"   ⚠️  No data for {ticker}")
                return None

            # ── 2. Collect Signals from ALL Strategies ─────────────
            signals = []

            # RSI Signal (always enabled)
            try:
                rsi_signal = self.strategy.analyze(ticker, df, 'rsi_mean_reversion')
                log.info(f"   📊 RSI: {rsi_signal['action']} @ {rsi_signal['confidence']:.0%}")
                signals.append(rsi_signal)
            except Exception as e:
                log.warning(f"   ⚠️  RSI failed: {e}")

            # Momentum Signal (if registered in strategy_engine)
            if 'momentum' in self.strategy.strategies:
                try:
                    momentum_signal = self.strategy.analyze(ticker, df, 'momentum')
                    log.info(f"   📊 Momentum: {momentum_signal['action']} @ {momentum_signal['confidence']:.0%}")
                    signals.append(momentum_signal)
                except Exception as e:
                    log.warning(f"   ⚠️  Momentum failed: {e}")

            # AI Signal (if TradingAgents enabled and loaded successfully)
            if self.ta is not None:
                try:
                    ai_signal = self.ta.analyze(ticker)
                    if ai_signal:
                        log.info(f"   🤖 AI: {ai_signal['action']} @ {ai_signal['confidence']:.0%}")
                        signals.append(ai_signal)
                except Exception as e:
                    log.warning(f"   ⚠️  AI failed: {e}")

            # Future strategies — add them to StrategyResearcher registry and they
            # will be picked up automatically here without touching this file.
            for strategy_name in self.strategy.list_strategies():
                if strategy_name in ('rsi_mean_reversion', 'momentum'):
                    continue  # already handled above
                try:
                    extra_signal = self.strategy.analyze(ticker, df, strategy_name)
                    log.info(f"   📊 {strategy_name}: {extra_signal['action']} @ {extra_signal['confidence']:.0%}")
                    signals.append(extra_signal)
                except Exception as e:
                    log.warning(f"   ⚠️  {strategy_name} failed: {e}")

            # ── 3. Validate We Have Signals ────────────────────────
            if not signals:
                log.error(f"   ❌ No strategies returned signals for {ticker}")
                return None

            # ── 4. Combine Signals Using Aggregator ────────────────
            if len(signals) == 1:
                combined = signals[0]
                log.info(f"   📊 Single strategy: {combined['action']} @ {combined['confidence']:.0%}")

            elif len(signals) == 2:
                combined = self.aggregator.combine_two(signals[0], signals[1])
                log.info(f"   🎯 Combined (2): {combined['action']} @ {combined['confidence']:.0%}")

            else:
                combined = self.aggregator.combine_multiple(signals)
                log.info(f"   🎯 Combined ({len(signals)}): {combined['action']} @ {combined['confidence']:.0%}")

            # ── 5. Ensure current_price is always present ──────────
            # SignalAggregator may not preserve current_price when merging.
            # Fall back to the first signal's price (they all use same data).
            if 'current_price' not in combined or not combined.get('current_price'):
                for s in signals:
                    if s.get('current_price'):
                        combined['current_price'] = s['current_price']
                        break

            if not combined.get('current_price'):
                log.warning(f"   ⚠️  No current_price in combined signal for {ticker} — fetching live")
                live_price = self.data.get_latest_price(ticker)
                combined['current_price'] = float(live_price) if live_price else 0.0

            # Log reasoning
            log.info(f"   📝 {combined.get('reasoning', '')}")

            # ── 6. Confidence gate ─────────────────────────────────
            # Reject weak signals before they reach the risk manager.
            # Confidence is stored as a 0.0–1.0 float.
            confidence    = combined.get('confidence', 0.0)
            min_confidence = self.config.MIN_SIGNAL_CONFIDENCE

            if confidence < min_confidence:
                log.info(
                    f"   ⏸️  LOW CONFIDENCE: {confidence:.0%} < {min_confidence:.0%} minimum — HOLD"
                )
                self.audit.record(
                    ticker=ticker, outcome='HELD', action='HOLD',
                    quantity=0, price=combined.get('current_price', 0.0),
                    signal=combined,
                    approval={'approved': False,
                               'reason': f'confidence {confidence:.0%} < minimum {min_confidence:.0%}',
                               'checks': {}},
                )
                return self._result(
                    ticker, 'HOLD', 'LOW_CONFIDENCE',
                    f"Signal confidence {confidence:.0%} below minimum {min_confidence:.0%}",
                    signal=combined
                )

            # ── 7. Route to trade execution ────────────────────────
            action = combined.get('action', 'HOLD')

            if action == 'BUY':
                return self._handle_buy(ticker, combined)
            elif action == 'SELL':
                return self._handle_sell(ticker, combined)
            else:
                log.info(f"   ⏸️  HOLD — no trade executed for {ticker}")
                self.audit.record(
                    ticker=ticker, outcome='HELD', action='HOLD',
                    quantity=0, price=combined.get('current_price', 0.0),
                    signal=combined,
                )
                return self._result(ticker, 'HOLD', 'SIGNAL_HOLD',
                                    combined.get('reasoning', 'Strategy says HOLD'),
                                    signal=combined)

        except Exception as e:
            log.error(f"   ❌ Analysis failed for {ticker}: {e}")
            return None
    
    # ── Buy handler ──────────────────────────────────────────────
    def _handle_buy(self, ticker, signal):
        """
        Process a BUY signal through pre-trade checks, risk gate, and execution.

        Flow:
        1. Duplicate guard       — skip if we already own this ticker
        2. Price validity        — reject if price is 0 or missing
        3. PositionSizer         — calculate quantity from portfolio & confidence
        4. Quantity check        — reject if sizer returns 0 shares
        5. Risk gate (6 checks)  — approve_trade()
        6. Execute               — tracker.add_position()
        7. TradeAudit            — record outcome regardless of result
        """
        current_price = signal.get('current_price', 0.0)
        confidence    = signal.get('confidence', 0.0)

        # ── Pre-check 1: Duplicate position guard ─────────────
        existing = self.tracker._find_position(ticker)
        if existing:
            log.info(
                f"   ⏭️  Already own {ticker} "
                f"({float(existing.quantity):.0f} shares @ "
                f"${float(existing.entry_price):.2f}) — skipping BUY"
            )
            return self._result(
                ticker, 'HOLD', 'ALREADY_OWNED',
                f'Already holding {ticker} — no pyramiding',
                signal=signal
            )

        # ── Pre-check 2: Price validity ────────────────────────
        if not current_price or current_price <= 0:
            log.warning(f"   ❌ Invalid price for {ticker}: {current_price}")
            return self._result(
                ticker, 'HOLD', 'INVALID_PRICE',
                f'Cannot buy {ticker} — invalid price: {current_price}',
                signal=signal
            )

        # ── Position sizing via PositionSizer ─────────────────
        sizing = self.sizer.calculate(
            portfolio_value = self.risk.portfolio_value,
            current_price   = current_price,
            confidence      = confidence,
            signal          = signal,
        )
        quantity = sizing['quantity']

        # ── Pre-check 3: Quantity validity ─────────────────────
        if quantity < 1:
            log.warning(f"   ❌ Sizer returned 0 shares: {sizing['reasoning']}")
            self.audit.record(
                ticker=ticker, outcome='REJECTED', action='BUY',
                quantity=0, price=current_price,
                signal=signal,
                approval={'approved': False, 'reason': sizing['reasoning'], 'checks': {}},
                sizing=sizing,
            )
            return self._result(
                ticker, 'HOLD', 'TOO_SMALL', sizing['reasoning'], signal=signal
            )

        trade_proposal = {
            'ticker':        ticker,
            'action':        'BUY',
            'quantity':      quantity,
            'current_price': current_price,
            'confidence':    confidence,
            'reasoning':     signal.get('reasoning', '')
        }

        log.info(
            f"\n   📋 Trade proposal:"
            f"\n      Action:     BUY"
            f"\n      Ticker:     {ticker}"
            f"\n      Quantity:   {quantity} shares"
            f"\n      Price:      ${current_price:.2f}"
            f"\n      Value:      ${quantity * current_price:,.2f}"
            f"\n      Size:       {sizing['size_pct']:.1%} ({sizing['method']})"
            f"\n      Confidence: {confidence:.0%}"
        )

        # ── Risk gate (6 checks) ───────────────────────────────
        approval = self.risk.approve_trade(trade_proposal)

        if not approval['approved']:
            log.warning(f"   ❌ Risk rejected: {approval['reason']}")
            self.audit.record(
                ticker=ticker, outcome='REJECTED', action='BUY',
                quantity=quantity, price=current_price,
                signal=signal, approval=approval, sizing=sizing,
            )
            return self._result(
                ticker, 'HOLD', 'REJECTED', approval['reason'],
                signal=signal, approval=approval
            )

        # ── Execute ────────────────────────────────────────────
        try:
            self.tracker.add_position(
                ticker=ticker,
                quantity=quantity,
                entry_price=current_price
            )
            log.info(
                f"   ✅ EXECUTED: BUY {quantity} × {ticker} "
                f"@ ${current_price:.2f} = ${quantity * current_price:,.2f}"
            )
            self.audit.record(
                ticker=ticker, outcome='EXECUTED', action='BUY',
                quantity=quantity, price=current_price,
                signal=signal, approval=approval, sizing=sizing,
            )
            # ── Alert ──────────────────────────────────────────
            alert_manager.send(
                subject=f"BUY executed — {ticker}",
                body=(
                    f"Shares: {quantity}\n"
                    f"Price: ${current_price:.2f}\n"
                    f"Value: ${quantity * current_price:,.2f}\n"
                    f"Confidence: {confidence:.0%}\n"
                    f"Reason: {signal.get('reasoning', '')}"
                ),
                level="trade"
            )
            return {
                'ticker':    ticker,
                'action':    'BUY',
                'quantity':  quantity,
                'price':     current_price,
                'value':     round(quantity * current_price, 2),
                'status':    'EXECUTED',
                'signal':    signal,
                'approval':  approval,
                'sizing':    sizing,
            }

        except Exception as e:
            log.error(f"   ❌ Execution failed for {ticker}: {e}")
            self.audit.record(
                ticker=ticker, outcome='REJECTED', action='BUY',
                quantity=quantity, price=current_price,
                signal=signal,
                approval={'approved': False, 'reason': str(e), 'checks': {}},
                sizing=sizing,
            )
            return self._result(
                ticker, 'HOLD', 'EXEC_FAILED', str(e),
                signal=signal, approval=approval
            )

    # ── Sell handler ─────────────────────────────────────────────
    def _handle_sell(self, ticker, signal):
        """
        Process a SELL signal — only executes if we own this ticker.

        If we don't own the stock, returns HOLD (not an error — it just
        means the strategy saw an overbought signal on a stock we never bought).
        """
        current_price = signal.get('current_price', 0.0)
        confidence    = signal.get('confidence', 0.0)

        # ── Check: do we own this stock? ──────────────────────
        position = self.tracker._find_position(ticker)

        if not position:
            log.info(
                f"   ⏭️  SELL signal for {ticker} but no position held — HOLD "
                f"(not an error: we never bought it)"
            )
            return self._result(
                ticker, 'HOLD', 'NOT_OWNED',
                f'SELL signal for {ticker} but no open position — skipping',
                signal=signal
            )

        entry_price  = float(position.entry_price)
        qty          = float(position.quantity)
        unrealized   = (current_price - entry_price) / entry_price if entry_price > 0 else 0

        trade_proposal = {
            'ticker':        ticker,
            'action':        'SELL',
            'quantity':      qty,
            'current_price': current_price,
            'confidence':    confidence,
            'reasoning':     signal.get('reasoning', '')
        }

        log.info(
            f"\n   📋 Trade proposal:"
            f"\n      Action:     SELL"
            f"\n      Ticker:     {ticker}"
            f"\n      Quantity:   {qty:.0f} shares"
            f"\n      Entry:      ${entry_price:.2f}"
            f"\n      Current:    ${current_price:.2f}"
            f"\n      Unrealized: {unrealized:+.1%}"
            f"\n      Confidence: {confidence:.0%}"
        )

        # ── Risk gate ──────────────────────────────────────────
        approval = self.risk.approve_trade(trade_proposal)

        if not approval['approved']:
            log.warning(f"   ❌ Sell rejected: {approval['reason']}")
            self.audit.record(
                ticker=ticker, outcome='REJECTED', action='SELL',
                quantity=int(qty), price=current_price,
                signal=signal, approval=approval,
            )
            return self._result(
                ticker, 'HOLD', 'REJECTED', approval['reason'],
                signal=signal, approval=approval
            )

        # ── Execute ────────────────────────────────────────────
        try:
            result = self.tracker.remove_position(
                ticker=ticker,
                quantity=qty,
                exit_price=current_price
            )
            pnl = float(result['realized_pnl']) if result else 0.0
            log.info(
                f"   ✅ EXECUTED: SELL {qty:.0f} × {ticker} "
                f"@ ${current_price:.2f}  |  Realized P&L: ${pnl:+,.2f}"
            )
            self.audit.record(
                ticker=ticker, outcome='EXECUTED', action='SELL',
                quantity=int(qty), price=current_price,
                signal=signal, approval=approval,
                realized_pnl=pnl,
            )
            # ── Alert ──────────────────────────────────────────
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            alert_manager.send(
                subject=f"SELL executed — {ticker}",
                body=(
                    f"Shares: {qty:.0f}\n"
                    f"Price: ${current_price:.2f}\n"
                    f"Realized P&L: {pnl_emoji} ${pnl:+,.2f}\n"
                    f"Confidence: {confidence:.0%}\n"
                    f"Reason: {signal.get('reasoning', '')}"
                ),
                level="trade"
            )
            return {
                'ticker':       ticker,
                'action':       'SELL',
                'quantity':     qty,
                'price':        current_price,
                'realized_pnl': round(pnl, 2),
                'status':       'EXECUTED',
                'signal':       signal,
                'approval':     approval,
            }

        except Exception as e:
            log.error(f"   ❌ Sell execution failed for {ticker}: {e}")
            self.audit.record(
                ticker=ticker, outcome='REJECTED', action='SELL',
                quantity=int(qty), price=current_price,
                signal=signal,
                approval={'approved': False, 'reason': str(e), 'checks': {}},
            )
            return self._result(
                ticker, 'HOLD', 'EXEC_FAILED', str(e),
                signal=signal, approval=approval
            )

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
            'summary':       {
                'portfolio_value':       float(summary.get('portfolio_value', 0)),
                'cash':                  float(summary.get('cash', 0)),
                'cash_pct':              float(summary.get('cash_pct', 0)),
                'total_positions':       int(summary.get('total_positions', 0)),
                'total_unrealized_pnl':  float(summary.get('total_unrealized_pnl', 0)),
                'total_realized_pnl':    float(summary.get('total_realized_pnl', 0)),
                'return_pct':            float(summary.get('return_pct', 0)),
            }
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


# ── Global singleton — lazy initialization ────────────────────
# We do NOT call TradingSystem() at module import time.
# Importing this module is now safe without a .env file.
#
# main.py and other callers access the singleton via get_trading_system():
#
#   from system.system_architect import get_trading_system
#   trading_system = get_trading_system()
#
_trading_system_instance = None

def get_trading_system():
    """
    Return the global TradingSystem singleton, creating it on first call.

    This pattern prevents the system from crashing at import time when
    API keys are missing or the environment is not yet configured.
    """
    global _trading_system_instance
    if _trading_system_instance is None:
        _trading_system_instance = TradingSystem()
    return _trading_system_instance


# ── Backwards-compatible alias ────────────────────────────────
# Code that does `from system.system_architect import trading_system`
# will get None until get_trading_system() is called first.
# Prefer using get_trading_system() in all new code.
trading_system = None  # populated by get_trading_system() on first use


# ================================================================
# STANDALONE TEST
# ================================================================

if __name__ == "__main__":
    log.info("Running system_architect test...\n")

    # ── Initialize the system via the lazy factory ────────────
    # trading_system (the module-level variable) is None by design.
    # get_trading_system() creates the instance on first call.
    ts = get_trading_system()
    ts.config.USE_TRADING_AGENT = False
    ts.ta = None

    log.info("TEST 1: Single stock analysis")
    result = ts.analyze_single_stock('AAPL')
    if result:
        log.info(f"Result: action={result.get('action')}, status={result.get('status')}")
    else:
        log.warning("No result returned (no data or all HOLD)")

    log.info("\nTEST 2: Watchlist scan (3 stocks)")
    scan = ts.scan_watchlist(['AAPL', 'MSFT', 'NVDA'])
    log.info(f"Bought: {scan['executed_buy']}")
    log.info(f"Held:   {scan['hold']}")

    log.info("\nTEST 3: Portfolio state")
    ts.display_portfolio()

    log.info("\nTEST 4: Stop-loss check")
    sold = ts.check_stop_losses()
    log.info(f"Force-sold: {sold}")

    log.info("\nTEST 5: Full daily run")
    daily = ts.run_daily_analysis(['AAPL', 'MSFT', 'NVDA'])
    log.info(f"Report saved: {daily['report_path']}")
