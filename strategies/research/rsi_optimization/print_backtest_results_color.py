"""
Enhanced Backtest Results Viewer with Colors and Visual Elements
"""

import pandas as pd
import ast
from datetime import datetime
from typing import List, Dict
import sys

# ANSI color codes
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def colorize(text: str, color: str) -> str:
    """Add color to text"""
    return f"{color}{text}{Colors.ENDC}"

def print_header(text: str, char: str = "=", width: int = 100):
    """Print a colorful formatted header"""
    print("\n" + colorize(char * width, Colors.CYAN))
    print(colorize(text.center(width), Colors.BOLD + Colors.CYAN))
    print(colorize(char * width, Colors.CYAN))

def print_section(text: str, char: str = "-", width: int = 100):
    """Print a section divider"""
    print("\n" + colorize(char * width, Colors.BLUE))
    print(colorize(text, Colors.BOLD + Colors.BLUE))
    print(colorize(char * width, Colors.BLUE))

def format_currency(amount: float, colored: bool = True) -> str:
    """Format number as currency with optional color"""
    formatted = f"${amount:,.2f}"
    if colored:
        if amount > 0:
            return colorize(formatted, Colors.GREEN)
        elif amount < 0:
            return colorize(formatted, Colors.RED)
    return formatted

def format_percent(value: float, colored: bool = True) -> str:
    """Format number as percentage with optional color"""
    formatted = f"{value * 100:+.2f}%"
    if colored:
        if value > 0:
            return colorize(formatted, Colors.GREEN)
        elif value < 0:
            return colorize(formatted, Colors.RED)
        return colorize(formatted, Colors.YELLOW)
    return formatted

def create_progress_bar(value: float, max_value: float, width: int = 30) -> str:
    """Create a visual progress bar"""
    if max_value == 0:
        percentage = 0
    else:
        percentage = abs(value) / abs(max_value)
    
    filled = int(percentage * width)
    bar = "█" * filled + "░" * (width - filled)
    
    if value > 0:
        return colorize(bar, Colors.GREEN)
    elif value < 0:
        return colorize(bar, Colors.RED)
    return colorize(bar, Colors.YELLOW)

def format_trade(trade: Dict, trade_num: int, max_pnl: float = None) -> str:
    """Format a single trade for display with colors and visual elements"""
    output = []
    
    # Trade header
    output.append(f"\n  {colorize(f'━━━ TRADE #{trade_num} ━━━', Colors.BOLD + Colors.CYAN)}")
    
    # Entry info
    entry_date = pd.to_datetime(trade['entry_date']).strftime('%Y-%m-%d')
    output.append(f"  {colorize('🟢 ENTRY:', Colors.GREEN)}  {entry_date} @ {format_currency(trade['entry_price'], colored=False)}")
    output.append(f"     Capital Invested: {format_currency(trade['entry_capital'], colored=False)}")
    
    # Exit info (if trade is closed)
    if 'exit_date' in trade:
        exit_date = pd.to_datetime(trade['exit_date']).strftime('%Y-%m-%d')
        output.append(f"  {colorize('🔴 EXIT:', Colors.RED)}   {exit_date} @ {format_currency(trade['exit_price'], colored=False)}")
        output.append(f"     Capital Received: {format_currency(trade['exit_capital'], colored=False)}")
        
        # P&L info with visual bar
        pnl_dollar = trade['pnl']
        pnl_pct = trade['pnl_pct']
        days = trade['days_held']
        
        # Create visual bar
        if max_pnl:
            bar = create_progress_bar(pnl_dollar, max_pnl, width=30)
            output.append(f"  {bar}")
        
        # Color-code based on profit/loss
        if pnl_dollar > 0:
            emoji = "✅"
            label = colorize("PROFIT:", Colors.GREEN + Colors.BOLD)
        elif pnl_dollar < 0:
            emoji = "❌"
            label = colorize("LOSS:  ", Colors.RED + Colors.BOLD)
        else:
            emoji = "⚪"
            label = colorize("BREAK-EVEN:", Colors.YELLOW)
        
        output.append(f"  {emoji} {label} {format_currency(pnl_dollar)} ({format_percent(pnl_pct)})")
        output.append(f"     {colorize('⏱️  Days Held:', Colors.CYAN)} {days} days")
        
        # Exit reason if available
        if 'exit_reason' in trade:
            output.append(f"     {colorize('Exit Reason:', Colors.YELLOW)} {trade['exit_reason']}")
    else:
        output.append(f"  {colorize('⏳ OPEN POSITION (not yet closed)', Colors.YELLOW)}")
    
    return "\n".join(output)

def parse_trades(trades_str: str) -> List[Dict]:
    """Parse the trades string from CSV into Python objects"""
    if pd.isna(trades_str) or trades_str == '[]':
        return []
    
    try:
        trades = ast.literal_eval(trades_str)
        return trades
    except:
        return []

def print_strategy_summary(row: pd.Series, rank: int = None):
    """Print summary for a single strategy configuration"""
    ticker = row['ticker']
    rsi_buy = row['rsi_buy']
    rsi_sell = row['rsi_sell']
    holding_days = row['holding_days']
    stop_loss = row['stop_loss']
    
    # Add rank emoji
    rank_emoji = ""
    if rank == 1:
        rank_emoji = "🥇 "
    elif rank == 2:
        rank_emoji = "🥈 "
    elif rank == 3:
        rank_emoji = "🥉 "
    
    print_header(f"{rank_emoji}{ticker} - RSI {rsi_buy}/{rsi_sell} | Hold: {holding_days}d | Stop: {stop_loss*100:.0f}%", "=", 100)
    
    # Performance metrics
    print(f"\n{colorize('📈 PERFORMANCE SUMMARY', Colors.BOLD + Colors.CYAN)}")
    print("─" * 100)
    print(f"  Initial Capital:    {format_currency(row['initial_capital'], colored=False)}")
    print(f"  Final Capital:      {format_currency(row['final_capital'])}")
    print(f"  Total Return:       {format_percent(row['total_return'])}")
    print(f"  Total Trades:       {colorize(str(int(row['total_trades'])), Colors.BOLD)}")
    
    if row['total_trades'] > 0:
        win_rate_color = Colors.GREEN if row['win_rate'] >= 0.5 else Colors.RED
        print(f"  Win Rate:           {colorize(f'{row["win_rate"] * 100:.1f}%', win_rate_color)}")
        print(f"  Average Win:        {format_percent(row['avg_win'])}")
        
        if row['avg_loss'] != 0:
            print(f"  Average Loss:       {format_percent(row['avg_loss'])}")
    
    # Parse and display trades
    trades = parse_trades(row['trades'])
    
    if trades:
        print_section(f"\n📋 DETAILED TRADES ({len(trades)} total)", "─", 100)
        
        # Calculate max PnL for visual bars
        completed_trades = [t for t in trades if 'pnl' in t]
        max_pnl = max([abs(t['pnl']) for t in completed_trades]) if completed_trades else None
        
        for i, trade in enumerate(trades, 1):
            print(format_trade(trade, i, max_pnl))
        
        # Trade statistics
        if completed_trades:
            print_section(f"\n📊 TRADE STATISTICS", "─", 100)
            
            total_pnl = sum(t['pnl'] for t in completed_trades)
            winning = [t for t in completed_trades if t['pnl'] > 0]
            losing = [t for t in completed_trades if t['pnl'] < 0]
            
            print(f"\n  Completed Trades:     {len(completed_trades)}")
            print(f"  {colorize('✅ Winning Trades:', Colors.GREEN)}    {len(winning)}")
            print(f"  {colorize('❌ Losing Trades:', Colors.RED)}     {len(losing)}")
            
            if winning:
                total_wins = sum(t['pnl'] for t in winning)
                best_win = max(winning, key=lambda x: x['pnl'])
                print(f"\n  {colorize('💰 WINS:', Colors.GREEN + Colors.BOLD)}")
                print(f"     Total Profits:     {format_currency(total_wins)}")
                print(f"     Best Trade:        {format_currency(best_win['pnl'])} ({format_percent(best_win['pnl_pct'])})")
                print(f"     Average Win:       {format_currency(total_wins / len(winning))}")
            
            if losing:
                total_losses = sum(t['pnl'] for t in losing)
                worst_loss = min(losing, key=lambda x: x['pnl'])
                print(f"\n  {colorize('💸 LOSSES:', Colors.RED + Colors.BOLD)}")
                print(f"     Total Losses:      {format_currency(total_losses)}")
                print(f"     Worst Trade:       {format_currency(worst_loss['pnl'])} ({format_percent(worst_loss['pnl_pct'])})")
                print(f"     Average Loss:      {format_currency(total_losses / len(losing))}")
            
            avg_days = sum(t['days_held'] for t in completed_trades) / len(completed_trades)
            print(f"\n  {colorize('⏱️  HOLDING PERIOD:', Colors.CYAN)}")
            print(f"     Average:           {avg_days:.1f} days")
            print(f"     Shortest:          {min(t['days_held'] for t in completed_trades)} days")
            print(f"     Longest:           {max(t['days_held'] for t in completed_trades)} days")
    
    print("\n" + "=" * 100)

def print_comparison_table(df: pd.DataFrame):
    """Print a colorful comparison table"""
    strategies_with_trades = df[df['total_trades'] > 0].copy()
    
    if len(strategies_with_trades) == 0:
        print(f"\n{colorize('⚠️  No strategies generated any trades!', Colors.YELLOW)}")
        return
    
    print_header("📊 STRATEGY LEADERBOARD", "=", 120)
    
    # Sort by total return
    strategies_with_trades = strategies_with_trades.sort_values('total_return', ascending=False)
    
    # Header
    header = "{:<6} {:<8} {:<10} {:<10} {:<8} {:<10} {:<14} {:<8} {:<10} {:<14}".format(
        "Rank", "Ticker", "RSI Buy", "RSI Sell", "Hold", "Stop", "Return", "Trades", "Win Rate", "Final Capital"
    )
    print(f"\n{colorize(header, Colors.BOLD)}")
    print("─" * 120)
    
    for rank, (_, row) in enumerate(strategies_with_trades.iterrows(), 1):
        # Rank emoji
        if rank == 1:
            rank_str = "🥇"
        elif rank == 2:
            rank_str = "🥈"
        elif rank == 3:
            rank_str = "🥉"
        else:
            rank_str = f"{rank}."
        
        print("{:<6} {:<8} {:<10} {:<10} {:<8} {:<10} {:<14} {:<8} {:<10} {:<14}".format(
            rank_str,
            row['ticker'],
            int(row['rsi_buy']),
            int(row['rsi_sell']),
            f"{int(row['holding_days'])}d",
            f"{row['stop_loss']*100:.0f}%",
            format_percent(row['total_return'], colored=False),
            int(row['total_trades']),
            f"{row['win_rate']*100:.1f}%" if row['total_trades'] > 0 else "N/A",
            format_currency(row['final_capital'], colored=False)
        ))
    
    print("=" * 120)

def print_overall_statistics(df: pd.DataFrame):
    """Print colorful overall statistics"""
    print_header("🎯 OVERALL BACKTEST STATISTICS", "=", 100)
    
    strategies_with_trades = df[df['total_trades'] > 0]
    
    print(f"\n  {colorize('📋 STRATEGY COVERAGE:', Colors.BOLD)}")
    print(f"     Total Strategies Tested:        {colorize(str(len(df)), Colors.BOLD)}")
    print(f"     Strategies with Trades:         {colorize(str(len(strategies_with_trades)), Colors.GREEN)}")
    print(f"     Strategies with No Trades:      {colorize(str(len(df) - len(strategies_with_trades)), Colors.YELLOW)}")
    print(f"     Success Rate:                   {colorize(f'{len(strategies_with_trades)/len(df)*100:.1f}%', Colors.CYAN)}")
    
    if len(strategies_with_trades) > 0:
        best_return = strategies_with_trades['total_return'].max()
        worst_return = strategies_with_trades['total_return'].min()
        avg_return = strategies_with_trades['total_return'].mean()
        
        print(f"\n  {colorize('📊 PERFORMANCE ACROSS WORKING STRATEGIES:', Colors.BOLD)}")
        print(f"     Best Return:                 {format_percent(best_return)} 🚀")
        print(f"     Worst Return:                {format_percent(worst_return)}")
        print(f"     Average Return:              {format_percent(avg_return)}")
        print(f"     Median Return:               {format_percent(strategies_with_trades['total_return'].median())}")
        
        total_trades = strategies_with_trades['total_trades'].sum()
        avg_win_rate = strategies_with_trades[strategies_with_trades['total_trades'] > 0]['win_rate'].mean()
        
        print(f"\n  {colorize('📈 TRADING ACTIVITY:', Colors.BOLD)}")
        print(f"     Total Trades:                {colorize(str(int(total_trades)), Colors.BOLD)}")
        print(f"     Average Win Rate:            {colorize(f'{avg_win_rate * 100:.1f}%', Colors.GREEN if avg_win_rate >= 0.5 else Colors.RED)}")
        print(f"     Avg Trades per Strategy:     {total_trades / len(strategies_with_trades):.1f}")
    
    # Stock-specific breakdown
    print(f"\n  {colorize('📌 RESULTS BY STOCK:', Colors.BOLD)}")
    for ticker in sorted(df['ticker'].unique()):
        ticker_df = df[df['ticker'] == ticker]
        ticker_trades = ticker_df[ticker_df['total_trades'] > 0]
        
        if len(ticker_trades) > 0:
            avg_return = ticker_trades['total_return'].mean()
            status = colorize(f'{len(ticker_trades)} working ({avg_return*100:+.2f}% avg)', Colors.GREEN)
        else:
            status = colorize('No trades', Colors.RED)
        
        print(f"     {ticker:<6} - {status}")
    
    print("\n" + "=" * 100)

def main():
    # Get filename from command line or use default
    if len(sys.argv) > 1:
        filename = sys.argv[1]
    else:
        filename = 'strategies/research/rsi_optimization/backtest_results.csv'
    
    try:
        # Print welcome message
        print(colorize("\n" + "═" * 100, Colors.CYAN))
        print(colorize("📊 BACKTEST RESULTS ANALYZER 📊".center(100), Colors.BOLD + Colors.CYAN))
        print(colorize("═" * 100 + "\n", Colors.CYAN))
        
        # Read the CSV
        print(f"📂 Loading: {colorize(filename, Colors.BOLD)}")
        df = pd.read_csv(filename)
        print(f"✅ Loaded {colorize(str(len(df)), Colors.GREEN)} strategy configurations\n")
        
        # Print overall statistics first
        print_overall_statistics(df)
        
        # Print comparison table
        print_comparison_table(df)
        
        # Print detailed view for each strategy with trades
        strategies_with_trades = df[df['total_trades'] > 0].sort_values('total_return', ascending=False)
        
        if len(strategies_with_trades) > 0:
            print_header("📝 DETAILED STRATEGY REPORTS", "=", 100)
            
            for rank, (idx, row) in enumerate(strategies_with_trades.iterrows(), 1):
                print_strategy_summary(row, rank)
        
        # Summary footer
        print_header("🏁 END OF REPORT", "=", 100)
        print(f"\n{colorize('✅ Analysis Complete!', Colors.GREEN + Colors.BOLD)}")
        print(f"   • Analyzed {colorize(str(len(df)), Colors.BOLD)} strategy configurations")
        print(f"   • {colorize(str(len(strategies_with_trades)), Colors.GREEN)} strategies generated trades")
        print(f"   • Report generated: {colorize(datetime.now().strftime('%Y-%m-%d %H:%M:%S'), Colors.CYAN)}\n")
        
    except FileNotFoundError:
        print(f"\n{colorize('❌ Error:', Colors.RED + Colors.BOLD)} File '{filename}' not found!")
        print(f"{colorize('Usage:', Colors.YELLOW)} python print_backtest_results_color.py [path/to/backtest_results.csv]")
        sys.exit(1)
    except Exception as e:
        print(f"\n{colorize('❌ Error:', Colors.RED + Colors.BOLD)} {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
