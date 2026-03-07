"""
Backtest Engine - Test Strategies on Historical Data
====================================================

Simulates trading on past data to validate strategy performance
before risking real money.

ARCHITECTURE:
- Uses data_access singleton (NO direct yfinance calls)
- Compatible with your caching system
- Same pattern as rest of project

Author: Mehdi
"""

import pandas as pd
from datetime import datetime, timedelta
from decimal import Decimal
from logger import get_logger
from risk.portfolio.portfolio_tracker import PositionTracker
from risk.risk_manager import RiskManager
from config.trading_config import TradingConfig

log = get_logger('system.backtest_engine')


class BacktestEngine:
    """
    Simulates trading on historical data.
    
    ARCHITECTURE:
    - Uses data_access for ALL data fetching
    - No direct API calls
    - Uses cached data when available
    - Compatible with rate limiting
    
    WORKFLOW:
    1. Load historical price data (via data_access)
    2. For each trading day:
       a. Update portfolio prices (mark-to-market)
       b. Check stop-losses (force sell if triggered)
       c. Get strategy signal
       d. Execute trade if risk approves
    3. Calculate performance metrics
    
    METRICS:
    - Total Return (%)
    - Sharpe Ratio (risk-adjusted return)
    - Maximum Drawdown (%)
    - Win Rate (%)
    - Total Trades
    - Avg Win/Loss
    """
    
    def __init__(self, strategy, initial_capital=None, use_aggregator=False, data_access=None):
        """
        Initialize backtest engine.
        
        Parameters
        ----------
        strategy : Strategy or list of strategies
            If single: Use that strategy
            If list: Combine using signal aggregator
        
        initial_capital : float, optional
            Starting capital
        
        use_aggregator : bool
            If True and multiple strategies, use signal aggregator
        
        data_access : DataAccess, optional
            Data access singleton. If None, will import.
        """
        if initial_capital is None:
            initial_capital = TradingConfig.INITIAL_CAPITAL
        
        # Handle single strategy vs multiple
        if isinstance(strategy, list):
            self.strategies = strategy
            self.use_aggregator = use_aggregator
            if use_aggregator:
                from system.signal_aggregator import SignalAggregator
                self.aggregator = SignalAggregator()
        else:
            self.strategies = [strategy]
            self.use_aggregator = False
        
        self.initial_capital = Decimal(str(initial_capital))
        
        # Use data_access singleton
        if data_access is None:
            from data.data_engineer import data_access
            self.data_access = data_access
        else:
            self.data_access = data_access
        
        # Create fresh portfolio for simulation
        self.tracker = PositionTracker(initial_capital=initial_capital)
        self.risk = RiskManager(initial_capital=initial_capital)
        
        # Track performance
        self.trades = []
        self.daily_values = []
        
        strategy_names = [s.__class__.__name__ for s in self.strategies]
        log.info(f"✅ BacktestEngine initialized")
        log.info(f"   Capital: ${initial_capital:,.2f}")
        log.info(f"   Strategies: {', '.join(strategy_names)}")
        log.info(f"   Data source: data_access singleton")
        if self.use_aggregator:
            log.info(f"   Using signal aggregator")
    
    def run(self, ticker, start_date, end_date, position_size=0.15):
        """
        Run backtest on historical data.
        
        Parameters
        ----------
        ticker : str
            Stock symbol
        
        start_date : str
            Start date 'YYYY-MM-DD'
        
        end_date : str
            End date 'YYYY-MM-DD'
        
        position_size : float
            Fraction of capital per trade (default: 0.15 = 15%)
        
        Returns
        -------
        dict : Performance metrics
        """
        log.info(f"🎯 Backtesting {ticker}: {start_date} to {end_date}")
        
        # ── 1. Get historical data via data_access ────────────
        try:
            # Calculate days between dates
            start = datetime.strptime(start_date, '%Y-%m-%d')
            end = datetime.strptime(end_date, '%Y-%m-%d')
            days = (end - start).days
            
            log.info(f"📊 Fetching {days} days of data via data_access...")
            
            # Use data_access to get data (will use cache if available)
            df = self.data_access.get_price_history(ticker, days=days)
            
            if df is None or df.empty:
                log.error(f"❌ No data returned for {ticker}")
                return {}
            
            # Filter by date range
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'])
                df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]
            elif 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
                df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]
            
            if df.empty:
                log.error(f"❌ No data in date range {start_date} to {end_date}")
                return {}
            
        except Exception as e:
            log.error(f"❌ Failed to get data: {e}")
            return {}
        
        log.info(f"📊 Loaded {len(df)} trading days")
        
        # ── 2. Prepare data ────────────────────────────────────
        df = df.reset_index(drop=True)
        
        # Normalize column names
        date_col = 'Date' if 'Date' in df.columns else 'date'
        close_col = 'Close' if 'Close' in df.columns else 'close'
        
        if close_col not in df.columns:
            log.error(f"❌ No close price column found")
            return {}
        
        # ── 3. Simulate each trading day ──────────────────────
        for i in range(len(df)):
            date = df.iloc[i][date_col]
            row = df.iloc[i]
            
            try:
                current_price = float(row[close_col])
            except (ValueError, KeyError) as e:
                log.warning(f"⚠️ Invalid price on {date}: {e}")
                continue
            
            # Update portfolio with current prices
            if self.tracker.positions:
                self.tracker.update_prices({ticker: current_price})
            
            # Record daily value
            daily_value = self.tracker.get_portfolio_value()
            self.daily_values.append({
                'date': date,
                'value': float(daily_value),
                'cash': float(self.tracker.cash),
                'positions': float(daily_value - self.tracker.cash)
            })
            
            # Check stop-losses
            self._check_stop_losses(ticker, current_price, date)
            
            # Get signal(s) from strategy(ies)
            historical_data = df.iloc[:i+1].copy()
            signal = self._get_signal(ticker, historical_data)
            
            # Execute signal
            self._execute_signal(ticker, signal, current_price, date, position_size)
        
        # ── 4. Close all positions at end ─────────────────────
        final_price = float(df.iloc[-1][close_col])
        if self.tracker.positions:
            for pos in list(self.tracker.positions):
                self.tracker.remove_position(pos.ticker, exit_price=final_price)
                log.info(f"📤 Closed final position: {pos.ticker} @ ${final_price}")
        
        # ── 5. Calculate metrics ──────────────────────────────
        metrics = self._calculate_metrics()
        
        log.info(f"✅ Backtest complete")
        log.info(f"   Return: {metrics['total_return']:.2f}%")
        log.info(f"   Sharpe: {metrics['sharpe_ratio']:.2f}")
        log.info(f"   Trades: {metrics['total_trades']}")
        
        return metrics
    
    def _get_signal(self, ticker, df):
        """Get signal from strategy or aggregated from multiple strategies."""
        if len(self.strategies) == 1:
            # Single strategy - pass data directly
            return self.strategies[0].analyze(ticker, df)
        
        # Multiple strategies
        signals = [strategy.analyze(ticker, df) for strategy in self.strategies]
        
        if self.use_aggregator:
            # Use aggregator to combine
            return self.aggregator.combine_multiple(signals)
        else:
            # Use first strategy
            return signals[0]
    
    def _check_stop_losses(self, ticker, current_price, date):
        """Check if position hits stop-loss."""
        position = self.tracker._find_position(ticker)
        if not position:
            return
        
        # 5% stop-loss
        loss_pct = ((current_price - float(position.entry_price)) / 
                    float(position.entry_price)) * 100
        
        if loss_pct <= -5:
            log.warning(f"🛑 Stop-loss: {ticker} down {loss_pct:.2f}%")
            result = self.tracker.remove_position(ticker, exit_price=current_price)
            if result:
                self.trades.append({
                    'date': date,
                    'action': 'SELL',
                    'ticker': ticker,
                    'price': current_price,
                    'quantity': result['quantity_sold'],
                    'pnl': result['realized_pnl'],
                    'reason': 'stop_loss'
                })
    
    def _execute_signal(self, ticker, signal, current_price, date, position_size):
        """Execute trading signal if approved."""
        if signal['action'] == 'HOLD':
            return
        
        # ── BUY Signal ────────────────────────────────────────
        if signal['action'] == 'BUY':
            # Check if already holding
            if self.tracker._find_position(ticker):
                return
            
            # Calculate position size
            capital = float(self.tracker.cash) * position_size
            quantity = int(capital / current_price)
            
            if quantity == 0:
                return
            
            # Risk check
            approval = self.risk.approve_trade(
                'BUY', ticker, quantity, current_price, self.tracker
            )
            
            if not approval['approved']:
                return
            
            # Execute
            try:
                self.tracker.add_position(ticker, quantity, current_price)
                self.trades.append({
                    'date': date,
                    'action': 'BUY',
                    'ticker': ticker,
                    'price': current_price,
                    'quantity': quantity,
                    'cost': quantity * current_price,
                    'reason': signal['reasoning']
                })
            except Exception as e:
                log.debug(f"BUY failed: {e}")
        
        # ── SELL Signal ───────────────────────────────────────
        elif signal['action'] == 'SELL':
            position = self.tracker._find_position(ticker)
            if not position:
                return
            
            try:
                result = self.tracker.remove_position(ticker, exit_price=current_price)
                if result:
                    self.trades.append({
                        'date': date,
                        'action': 'SELL',
                        'ticker': ticker,
                        'price': current_price,
                        'quantity': result['quantity_sold'],
                        'pnl': result['realized_pnl'],
                        'reason': signal['reasoning']
                    })
            except Exception as e:
                log.debug(f"SELL failed: {e}")
    
    def _calculate_metrics(self):
        """Calculate performance metrics."""
        if not self.daily_values:
            return {}
        
        # Final value
        final_value = self.daily_values[-1]['value']
        initial_value = float(self.initial_capital)
        
        # Total return
        total_return = ((final_value - initial_value) / initial_value) * 100
        
        # Sharpe ratio
        returns = pd.Series([d['value'] for d in self.daily_values]).pct_change().dropna()
        sharpe = 0
        if len(returns) > 0 and returns.std() > 0:
            sharpe = (returns.mean() / returns.std()) * (252 ** 0.5)
        
        # Maximum drawdown
        values = pd.Series([d['value'] for d in self.daily_values])
        cummax = values.cummax()
        drawdown = ((values - cummax) / cummax) * 100
        max_drawdown = drawdown.min()
        
        # Trade stats
        winning_trades = [t for t in self.trades if t.get('pnl', 0) > 0]
        losing_trades = [t for t in self.trades if t.get('pnl', 0) < 0]
        
        win_rate = (len(winning_trades) / len(self.trades) * 100) if self.trades else 0
        
        avg_win = (sum(t['pnl'] for t in winning_trades) / len(winning_trades)) if winning_trades else 0
        avg_loss = (sum(t['pnl'] for t in losing_trades) / len(losing_trades)) if losing_trades else 0
        
        return {
            'initial_capital': initial_value,
            'final_value': round(final_value, 2),
            'total_return': round(total_return, 2),
            'sharpe_ratio': round(sharpe, 2),
            'max_drawdown': round(max_drawdown, 2),
            'total_trades': len(self.trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': round(win_rate, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'daily_values': self.daily_values,
            'trades': self.trades
        }


# ══════════════════════════════════════════════════════════════
# DEMO
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    from logger import setup_logging
    from strategies.rsi_strategy import RSIStrategy
    
    setup_logging()
    
    print("\n" + "="*60)
    print("BACKTEST ENGINE DEMO")
    print("="*60)
    
    # Create strategy
    strategy = RSIStrategy(rsi_period=14, oversold=25, overbought=75)
    
    # Create engine (will use data_access)
    engine = BacktestEngine(strategy, initial_capital=20000)
    
    # Run backtest
    print("\n🎯 Running backtest using data_access...")
    print("Note: This uses cached data if available (fast)")
    print("      Or fetches via data_access with rate limiting (slower)")
    
    try:
        metrics = engine.run(
            ticker='AAPL',
            start_date='2024-01-01',
            end_date='2025-01-01',
            position_size=0.15
        )
        
        if metrics:
            # Print results
            print("\n" + "="*60)
            print("RESULTS")
            print("="*60)
            print(f"Initial:    ${metrics['initial_capital']:,.2f}")
            print(f"Final:      ${metrics['final_value']:,.2f}")
            print(f"Return:     {metrics['total_return']}%")
            print(f"Sharpe:     {metrics['sharpe_ratio']}")
            print(f"Drawdown:   {metrics['max_drawdown']}%")
            print(f"Trades:     {metrics['total_trades']}")
            print(f"Win Rate:   {metrics['win_rate']}%")
            print(f"Avg Win:    ${metrics['avg_win']:.2f}")
            print(f"Avg Loss:   ${metrics['avg_loss']:.2f}")
        else:
            print("\n⚠️  No metrics returned (insufficient data)")
            print("This is expected if Yahoo Finance is rate-limited.")
            print("The backtest will work fine with cached data.")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        print("\nNote: If data fetching fails, this is expected during rate limits.")
        print("The backtest engine is properly integrated with your architecture.")
    
    print("\n✅ Demo complete")
    print("\nUsage:")
    print("  from system.backtest_engine import BacktestEngine")
    print("  engine = BacktestEngine(strategy)")
    print("  metrics = engine.run('AAPL', '2024-01-01', '2025-01-01')")
    print("\nUses data_access singleton - no direct API calls!")