# rsi_backtest.py
import sys
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# Ensure Python can find your 'data' module
sys.path.append(os.path.join(os.path.dirname(__file__), '../../data'))
from data.data_engineer import data_access  # make sure this matches your data folder structure

# -----------------------------
# Helper Functions
# -----------------------------
def calculate_rsi(prices, period=14):
    """Calculate Relative Strength Index (RSI)."""
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def backtest_rsi_strategy(ticker, data, rsi_buy, rsi_sell, holding_days, stop_loss):
    """Backtest RSI strategy for a single stock."""
    data['RSI'] = calculate_rsi(data['Close'])

    capital = 10000
    position = 0
    trades = []

    for i in range(len(data)):
        # BUY signal
        if data['RSI'].iloc[i] < rsi_buy and position == 0:
            entry_price = data['Close'].iloc[i]
            entry_date = data.index[i]
            shares = capital / entry_price
            position = shares
            capital = 0
            trades.append({
                'entry_date': entry_date,
                'entry_price': entry_price,
                'action': 'BUY',
                'entry_index': i
            })

        # SELL signal
        elif position > 0:
            current_price = data['Close'].iloc[i]
            days_held = i - trades[-1].get('entry_index', i)
            pnl_pct = (current_price - trades[-1]['entry_price']) / trades[-1]['entry_price']

            if (data['RSI'].iloc[i] > rsi_sell or 
                days_held >= holding_days or 
                pnl_pct < -stop_loss):
                capital = position * current_price
                pnl = capital - 10000
                trades[-1].update({
                    'exit_date': data.index[i],
                    'exit_price': current_price,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'days_held': days_held
                })
                position = 0

    # Metrics
    total_trades = len([t for t in trades if 'pnl' in t])
    winning_trades = len([t for t in trades if t.get('pnl', 0) > 0])

    if total_trades > 0:
        win_rate = winning_trades / total_trades
        avg_win = np.mean([t['pnl_pct'] for t in trades if t.get('pnl', 0) > 0])
        avg_loss = np.mean([t['pnl_pct'] for t in trades if t.get('pnl', 0) < 0])
        total_return = (capital - 10000) / 10000 if capital > 0 else -1
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
        'total_return': total_return,
        'total_trades': total_trades,
        'win_rate': win_rate,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'trades': trades
    }

# -----------------------------
# Main Function
# -----------------------------
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
    print("Results saved!")

    # Analyze results
    best = results_df.sort_values('total_return', ascending=False).head(10)
    print("\nTop 10 Parameter Combinations:")
    print(best)

    avg_by_rsi = results_df.groupby(['rsi_buy', 'rsi_sell'])['total_return'].mean()
    print("\nAverage Return by RSI Threshold:")
    print(avg_by_rsi)

    # Plot
    plt.figure(figsize=(12, 6))
    plt.bar(range(len(avg_by_rsi)), avg_by_rsi.values)
    plt.xticks(range(len(avg_by_rsi)), [f"{idx[0]}/{idx[1]}" for idx in avg_by_rsi.index])
    plt.xlabel('RSI Threshold (Buy/Sell)')
    plt.ylabel('Average Return')
    plt.title('Average Return by RSI Threshold')
    plt.savefig('strategies/research/rsi_optimization/rsi_comparison.png')
    plt.show()

# -----------------------------
# Run if script is executed
# -----------------------------
if __name__ == "__main__":
    main()
