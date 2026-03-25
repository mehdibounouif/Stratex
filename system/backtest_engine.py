"""
Backtest Engine - Test Strategies on Historical Data
====================================================

Simulates trading on past data to validate strategy performance
before risking real money.

ARCHITECTURE:
- Uses data_access singleton (NO direct yfinance calls)
- Compatible with your caching system
- Same pattern as rest of project
- Includes transaction costs (slippage, commission)

Author: Mehdi
"""
import os
import pandas as pd
from datetime import datetime
from decimal import Decimal
from logger import get_logger
from risk.portfolio.portfolio_tracker import PositionTracker
from risk.risk_manager import RiskManager
from config.trading_config import TradingConfig
from execution.fill_models import FillSimulator, default_fill_simulator

log = get_logger('system.backtest_engine')


class BacktestEngine:
    """
    Simulates trading on historical data.
    
    ARCHITECTURE:
    - Uses data_access for ALL data fetching
    - Uses cached data when available
    - Isolated from live portfolio data
    - Includes fill simulation for realistic results
    """
    
    def __init__(self, strategy, initial_capital=None, use_aggregator=False, data_access=None, fill_simulator=None):
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
        self.fill_simulator = fill_simulator or default_fill_simulator
        
        # Use data_access singleton
        if data_access is None:
            from data.data_engineer import data_access
            self.data_access = data_access
        else:
            self.data_access = data_access
        
        # ── CRITICAL: ISOLATE TRACKER FOR BACKTEST ────────────
        # Create fresh portfolio for simulation
        self.tracker = PositionTracker(initial_capital=initial_capital)
        
        # Override file paths to temporary locations to avoid corrupting live data
        os.makedirs('risk/portfolio/backtests', exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.tracker.positions_file = f'risk/portfolio/backtests/backtest_positions_{ts}.csv'
        self.tracker.history_file = f'risk/portfolio/backtests/backtest_history_{ts}.csv'
        self.tracker.cash_file = f'risk/portfolio/backtests/backtest_cash_{ts}.json'
        self.tracker.trades_file = f'risk/portfolio/backtests/backtest_trades_{ts}.csv'
        
        # Reset state after path override
        self.tracker.positions = []
        self.tracker.cash = self.initial_capital
        self.tracker.total_realized_pnl = Decimal('0')
        
        self.risk = RiskManager()
        # Point risk manager to our backtest tracker
        self.risk._tracker = self.tracker
        
        # Track performance
        self.trades = []
        self.daily_values = []
        self.total_commission = 0.0
        self.total_slippage = 0.0
        
        log.info(f"✅ BacktestEngine initialized (Isolated Tracker)")
    
    def run(self, ticker, start_date, end_date, position_size=0.15):
        log.info(f"🎯 Backtesting {ticker}: {start_date} to {end_date}")
        
        try:
            # Get historical data
            df = self.data_access.get_price_history(ticker, days=730)
            if df is None or df.empty:
                log.error(f"❌ No data returned for {ticker}")
                return {}
            
            # Filter and Normalize
            date_col = 'Date' if 'Date' in df.columns else 'date'
            close_col = 'Close' if 'Close' in df.columns else 'close'
            df[date_col] = pd.to_datetime(df[date_col])
            df = df[(df[date_col] >= start_date) & (df[date_col] <= end_date)].reset_index(drop=True)
            
            if df.empty:
                log.error(f"❌ No data in date range {start_date} to {end_date}")
                return {}
        except Exception as e:
            log.error(f"❌ Failed to get data: {e}")
            return {}
        
        log.info(f"📊 Loaded {len(df)} trading days")
        
        for i in range(len(df)):
            date = df.iloc[i][date_col]
            current_price = float(df.iloc[i][close_col])
            
            # Update tracker prices
            if self.tracker.positions:
                self.tracker.update_prices({ticker: current_price})
            
            # Record daily value
            summary = self.tracker.get_portfolio_summary()
            self.daily_values.append(float(summary['portfolio_value']))
            
           # Generate signal from data UP TO but NOT INCLUDING current bar
            # (we only know close[i] after the bar closes — fill next bar's open)
            if i < 1:
                continue  # need at least 1 prior bar to generate a signal

            historical_data = df.iloc[:i]  # everything before current bar
            signal = self._get_signal(ticker, historical_data)

            # Fill at current bar's OPEN (the earliest realistic execution price)
            open_col = 'Open' if 'Open' in df.columns else 'open'
            fill_price = float(df.iloc[i][open_col])

            # Execute
            if signal['action'] != 'HOLD':
                self._execute_signal(ticker, signal, fill_price, date, position_size, historical_data) 
        # Calculate metrics
        metrics = self._calculate_metrics()
        
        # Cleanup temporary files (optional, but good practice)
        for f in [self.tracker.positions_file, self.tracker.history_file, self.tracker.cash_file, self.tracker.trades_file]:
            if os.path.exists(f): os.remove(f)
            
        return metrics
    
    def _get_signal(self, ticker, df):
        if len(self.strategies) == 1:
            return self.strategies[0].generate_signal(ticker, df)
        
        signals = [s.generate_signal(ticker, df) for s in self.strategies]
        if self.use_aggregator:
            return self.aggregator.combine_multiple(signals)
        return signals[0]

    def _execute_signal(self, ticker, signal, current_price, date, position_size, hist):
        if signal['action'] == 'BUY':
            if self.tracker.get_position(ticker): return
            
            # Calculate quantity
            cash = float(self.tracker.cash)
            quantity = int((cash * position_size) / current_price)
            if quantity <= 0: return
            
            # Risk check
            trade_req = {'ticker': ticker, 'action': 'BUY', 'quantity': quantity, 'current_price': current_price}
            approval = self.risk.approve_trade(trade_req)
            if not approval.get('approved', False): return
            
            # Fill Simulation
            avg_vol = int(hist['Volume'].rolling(20).mean().iloc[-1]) if 'Volume' in hist.columns else 1000000
            fill = self.fill_simulator.simulate_fill(current_price, quantity, avg_vol, 'BUY')
            
            self.total_commission += fill['commission']
            self.total_slippage += fill['slippage_cost']
            
            try:
                self.tracker.add_position(ticker, quantity, fill['fill_price'], entry_date=date.isoformat())
                self.trades.append({'date': date, 'action': 'BUY', 'ticker': ticker, 'price': fill['fill_price'], 'qty': quantity, 'reason': signal['reasoning']})
            except Exception as e: log.debug(f"BUY failed: {e}")
            
        elif signal['action'] == 'SELL':
            pos = self.tracker.get_position(ticker)
            if not pos: return
            
            quantity = int(pos['quantity'])
            avg_vol = int(hist['Volume'].rolling(20).mean().iloc[-1]) if 'Volume' in hist.columns else 1000000
            fill = self.fill_simulator.simulate_fill(current_price, quantity, avg_vol, 'SELL')
            
            self.total_commission += fill['commission']
            self.total_slippage += fill['slippage_cost']
            
            try:
                res = self.tracker.remove_position(ticker, exit_price=fill['fill_price'])
                self.trades.append({'date': date, 'action': 'SELL', 'ticker': ticker, 'price': fill['fill_price'], 'qty': quantity, 'pnl': float(res['realized_pnl']), 'reason': signal['reasoning']})
            except Exception as e: log.debug(f"SELL failed: {e}")

    def _calculate_metrics(self):
        if not self.daily_values: return {}
        
        final_val = self.daily_values[-1]
        initial_val = float(self.initial_capital)
        total_return = (final_val - initial_val) / initial_val
        
        # Sharpe ratio
        rets = pd.Series(self.daily_values).pct_change().dropna()
        sharpe = (rets.mean() / rets.std() * (252**0.5)) if not rets.empty and rets.std() > 0 else 0
        
        # Drawdown
        vals = pd.Series(self.daily_values)
        mdd = ((vals - vals.cummax()) / vals.cummax()).min()
        
        winning_trades = [t for t in self.trades if t.get('pnl', 0) > 0]
        losing_trades = [t for t in self.trades if t.get('pnl', 0) < 0]
        win_rate = (len(winning_trades) / len(self.trades) * 100) if self.trades else 0
        
        avg_win = (sum(t['pnl'] for t in winning_trades) / len(winning_trades)) if winning_trades else 0
        avg_loss = (sum(t['pnl'] for t in losing_trades) / len(losing_trades)) if losing_trades else 0
        
        metrics = {
            'initial_capital': initial_val,
            'final_value': round(final_val, 2),
            'total_return': round(total_return * 100, 2),
            'sharpe_ratio': round(sharpe, 2),
            'max_drawdown': round(mdd * 100, 2),
            'total_trades': len(self.trades),
            'win_rate': round(win_rate, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'total_commission': round(self.total_commission, 2),
            'total_slippage': round(self.total_slippage, 2),
            'gross_return': round(total_return * 100, 2), # Simplified
            'daily_values': self.daily_values,
            'trades': self.trades
        }
        
        gross_pnl = final_val - initial_val
        if gross_pnl > 0 and (self.total_commission + self.total_slippage) > 0.15 * gross_pnl:
            log.warning("⚠️  Transaction costs exceed 15% of gross profit")
            
        return metrics
