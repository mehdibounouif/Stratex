import sys
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../'))
sys.path.append(project_root)

from data.data_enginner import data_access

def calculate_rsi(prices, period=14):
    """Calculate Relative Strength Index (RSI)."""
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def backtest_rsi_strategy(ticker, data, rsi_buy, rsi_sell, holding_days, stop_loss):
    """Backtest RSI strategy with cleaner capital tracking."""
    data['RSI'] = calculate_rsi(data['Close'])
    
    INITIAL_CAPITAL = 10000
    current_capital = INITIAL_CAPITAL
    position = 0
    position_entry_capital = 0
    trades = []
    
    for i in range(len(data)):
        # BUY signal
        if data['RSI'].iloc[i] < rsi_buy and position == 0:
            entry_price = data['Close'].iloc[i].values[0]
            entry_date = data.index[i]
            
            # Invest all available capital
            shares = current_capital / entry_price
            position = shares
            position_entry_capital = current_capital
            current_capital = 0
            
            trades.append({
                'entry_date': entry_date,
                'entry_price': entry_price,
                'entry_capital': position_entry_capital,
                'action': 'BUY',
                'entry_index': i
            })
        
        # SELL signal
        elif position > 0:
            current_price = data['Close'].iloc[i].values[0]
            days_held = i - trades[-1].get('entry_index', i)
            pnl_pct = (current_price - trades[-1]['entry_price']) / trades[-1]['entry_price']
            
            if (data['RSI'].iloc[i] > rsi_sell or 
                days_held >= holding_days or 
                pnl_pct < -stop_loss):
                
                # Sell position
                current_capital = position * current_price
                pnl = current_capital - position_entry_capital
                
                trades[-1].update({
                    'exit_date': data.index[i],
                    'exit_price': current_price,
                    'exit_capital': current_capital,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'days_held': days_held
                })
                
                position = 0
                position_entry_capital = 0
                
    # Close any remaining open position at end of backtest
    if position > 0:
        final_price = data['Close'].iloc[-1].values[0]
        current_capital = position * final_price
        pnl = current_capital - position_entry_capital
        pnl_pct = (final_price - trades[-1]['entry_price']) / trades[-1]['entry_price']
        
        trades[-1].update({
            'exit_date': data.index[-1],
            'exit_price': float(final_price),
            'exit_capital': float(current_capital),
            'pnl': float(pnl),
            'pnl_pct': float(pnl_pct),
            'days_held': len(data) - trades[-1]['entry_index'],
            'exit_reason': 'End of backtest period'  # NEW field
        })
        
        position = 0
    
    # ✅ FIXED: Calculate metrics with safety checks
    completed_trades = [t for t in trades if 'pnl' in t]
    total_trades = len(completed_trades)
    
    if total_trades > 0:
        # Count wins based on percentage, not dollar amount
        winning_trades = len([t for t in completed_trades if t.get('pnl_pct', 0) > 0])
        
        win_rate = winning_trades / total_trades
        
        # Safe calculation of averages
        winning_pcts = [t['pnl_pct'] for t in completed_trades if t.get('pnl_pct', 0) > 0]
        losing_pcts = [t['pnl_pct'] for t in completed_trades if t.get('pnl_pct', 0) < 0]
        
        avg_win = np.mean(winning_pcts) if winning_pcts else 0
        avg_loss = np.mean(losing_pcts) if losing_pcts else 0
        
        total_return = (current_capital - INITIAL_CAPITAL) / INITIAL_CAPITAL if current_capital > 0 else -1
    else:
        win_rate = 0
        avg_win = 0
        avg_loss = 0
        total_return = 0
    
    return {
        'ticker': ticker,
        'rsi_buy': rsi_buy,
        'rsi_sell': rsi_sell,
        'holding_days': holding_days,
        'stop_loss': stop_loss,
        'initial_capital': INITIAL_CAPITAL,
        'final_capital': current_capital,
        'total_return': total_return,
        'total_trades': total_trades,
        'win_rate': win_rate,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'trades': trades
    }

def main():
    results = []
    tickers = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META']
    rsi_thresholds = [(20, 80), (25, 75), (30, 70), (35, 65)]
    holding_periods = [3, 5, 7, 10]
    stop_losses = [0.03, 0.05, 0.07]
    
    for ticker in tickers:
        print(f"Testing {ticker}...")
        data = data_access.get_price_history(ticker, days=365)
        
        for rsi_buy, rsi_sell in rsi_thresholds:
            for holding in holding_periods:
                for stop in stop_losses:
                    result = backtest_rsi_strategy(
                        ticker, data, rsi_buy, rsi_sell, holding, stop
                    )
                    results.append(result)
    
    # Save results
    results_df = pd.DataFrame(results)
    results_df.to_csv('strategies/research/rsi_optimization/backtest_results.csv', index=False)
    print("Results saved to: strategies/research/rsi_optimization/backtest_results.csv")
    
    # Analyze results - only show strategies with trades
#    results_with_trades = results_df[results_df['total_trades'] > 0]
#    
#    if len(results_with_trades) > 0:
#        print("\n" + "="*80)
#        print("STRATEGIES THAT GENERATED TRADES:")
#        print("="*80)
#        
#        best = results_with_trades.sort_values('total_return', ascending=False)
#        
#        print(best[['ticker', 'rsi_buy', 'rsi_sell', 'holding_days', 'stop_loss', 
#                    'total_return', 'total_trades', 'win_rate', 'avg_win', 'avg_loss']].to_string())
#        
#        print("\n" + "="*80)
#        print("AVERAGE RETURN BY RSI THRESHOLD (only configs with trades):")
#        print("="*80)
#        avg_by_rsi = results_with_trades.groupby(['rsi_buy', 'rsi_sell'])['total_return'].mean()
#        print(avg_by_rsi)
#    else:
#        print("\n  WARNING: No strategies generated any trades!")
#        print("This might indicate:")
#        print("  1. RSI thresholds are too strict")
#        print("  2. The stocks didn't reach oversold/overbought levels")
#        print("  3. Data quality issues")
#    
#    # Overall statistics
#    print("\n" + "="*80)
#    print("OVERALL STATISTICS:")
#    print("="*80)
    avg_by_rsi_all = results_df.groupby(['rsi_buy', 'rsi_sell'])['total_return'].mean()
#    print(avg_by_rsi_all)
    
    # Plot
    plt.figure(figsize=(12, 6))
    plt.bar(range(len(avg_by_rsi_all)), avg_by_rsi_all.values)
    plt.xticks(range(len(avg_by_rsi_all)), [f"{idx[0]}/{idx[1]}" for idx in avg_by_rsi_all.index])
    plt.xlabel('RSI Threshold (Buy/Sell)')
    plt.ylabel('Average Return')
    plt.title('Average Return by RSI Threshold')
    plt.axhline(y=0, color='r', linestyle='--', alpha=0.5)  # Add zero line
    plt.grid(axis='y', alpha=0.3)
    plt.savefig('strategies/research/rsi_optimization/rsi_comparison.png')
    print("\n✓ Chart saved to: strategies/research/rsi_optimization/rsi_comparison.png")

if __name__ == "__main__":
    main()
