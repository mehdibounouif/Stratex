import sys
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

from logger import setup_logging, get_logger
from data.data_engineer import data_access

# --------------------------------------------------
# Logging setup
# --------------------------------------------------
setup_logging()
logging = get_logger(
    "strategies.research.rsi_optimization.rsi_research"
)

# --------------------------------------------------
# RSI Calculation
# --------------------------------------------------
def calculate_rsi(prices, period=14):
    """
    Calculate Relative Strength Index (RSI).

    Args:
        prices (pd.Series): Closing prices
        period (int): RSI lookback period

    Returns:
        pd.Series: RSI values
    """

    delta = prices.diff()

    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()

    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    return rsi


# --------------------------------------------------
# Backtest Engine
# --------------------------------------------------
def backtest_rsi_strategy(
    ticker,
    data,
    rsi_buy,
    rsi_sell,
    holding_days,
    stop_loss
):
    """
    Backtest RSI trading strategy.
    """

    data = data.copy()   # 🔧 FIX 1 — avoid modifying original dataframe
    data["RSI"] = calculate_rsi(data["Close"])

    INITIAL_CAPITAL = 10000
    current_capital = INITIAL_CAPITAL

    position = 0
    position_entry_capital = 0

    trades = []

    # Track equity curve
    equity_curve = []

    for i in range(len(data)):

        price = float(data["Close"].iloc[i])
        rsi_value = data["RSI"].iloc[i]

        # ---------------- BUY ----------------
        if rsi_value < rsi_buy and position == 0:

            shares = current_capital / price
            position = shares
            position_entry_capital = current_capital
            current_capital = 0

            trades.append({
                "entry_date": data.index[i],
                "entry_price": price,
                "entry_capital": position_entry_capital,
                "entry_index": i,
                "action": "BUY"
            })

        # ---------------- SELL ----------------
        elif position > 0:

            days_held = i - trades[-1]["entry_index"]

            pnl_pct = (
                price - trades[-1]["entry_price"]
            ) / trades[-1]["entry_price"]

            sell_signal = (
                rsi_value > rsi_sell or
                days_held >= holding_days or
                pnl_pct < -stop_loss
            )

            if sell_signal:

                current_capital = position * price
                pnl = current_capital - position_entry_capital

                trades[-1].update({
                    "exit_date": data.index[i],
                    "exit_price": price,
                    "exit_capital": current_capital,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "days_held": days_held
                })

                position = 0
                position_entry_capital = 0

        # Track portfolio value daily
        portfolio_value = (
            current_capital
            if position == 0
            else position * price
        )

        equity_curve.append(portfolio_value)

    # --------------------------------------------------
    # Close open trade at end
    # --------------------------------------------------
    if position > 0:

        final_price = float(data["Close"].iloc[-1])

        current_capital = position * final_price
        pnl = current_capital - position_entry_capital
        pnl_pct = (
            final_price - trades[-1]["entry_price"]
        ) / trades[-1]["entry_price"]

        trades[-1].update({
            "exit_date": data.index[-1],
            "exit_price": final_price,
            "exit_capital": current_capital,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "days_held": len(data) - trades[-1]["entry_index"],
            "exit_reason": "End of backtest"
        })

        position = 0

    # --------------------------------------------------
    # Metrics Calculation
    # --------------------------------------------------
    completed_trades = [t for t in trades if "pnl" in t]
    total_trades = len(completed_trades)

    if total_trades > 0:

        winning_trades = len(
            [t for t in completed_trades if t["pnl_pct"] > 0]
        )

        win_rate = winning_trades / total_trades

        winning_pcts = [
            t["pnl_pct"]
            for t in completed_trades
            if t["pnl_pct"] > 0
        ]

        losing_pcts = [
            t["pnl_pct"]
            for t in completed_trades
            if t["pnl_pct"] < 0
        ]

        avg_win = np.mean(winning_pcts) if winning_pcts else 0
        avg_loss = np.mean(losing_pcts) if losing_pcts else 0

        total_return = (
            current_capital - INITIAL_CAPITAL
        ) / INITIAL_CAPITAL

    else:
        win_rate = 0
        avg_win = 0
        avg_loss = 0
        total_return = 0

    # --------------------------------------------------
    # NEW METRICS
    # --------------------------------------------------

    equity_series = pd.Series(equity_curve)

    # Max Drawdown
    rolling_max = equity_series.cummax()
    drawdown = equity_series / rolling_max - 1
    max_drawdown = drawdown.min()

    # Sharpe Ratio (daily)
    returns = equity_series.pct_change().dropna()

    sharpe_ratio = (
        np.sqrt(252) * returns.mean() / returns.std()
        if returns.std() != 0
        else 0
    )

    return {
        "ticker": ticker,
        "rsi_buy": rsi_buy,
        "rsi_sell": rsi_sell,
        "holding_days": holding_days,
        "stop_loss": stop_loss,
        "initial_capital": INITIAL_CAPITAL,
        "final_capital": current_capital,
        "total_return": total_return,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe_ratio,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "trades": trades
    }


# --------------------------------------------------
# Research Runner
# --------------------------------------------------
def main():

    results = []

    tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "META"]
    rsi_thresholds = [(20, 80), (25, 75), (30, 70), (35, 65)]
    holding_periods = [3, 5, 7, 10]
    stop_losses = [0.03, 0.05, 0.07]

    for ticker in tickers:

        logging.info(f"Testing {ticker}")

        data = data_access.get_price_history(
            ticker,
            days=365
        )

        for rsi_buy, rsi_sell in rsi_thresholds:
            for holding in holding_periods:
                for stop in stop_losses:

                    result = backtest_rsi_strategy(
                        ticker,
                        data,
                        rsi_buy,
                        rsi_sell,
                        holding,
                        stop
                    )

                    results.append(result)

    results_df = pd.DataFrame(results)

    output_path = (
        "strategies/research/rsi_optimization/"
        "backtest_results.csv"
    )

    results_df.to_csv(output_path, index=False)

    logging.info(f"Results saved → {output_path}")


if __name__ == "__main__":
    main()
