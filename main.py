"""
Quant_firm Main Entrypoint.
Supports Live Trading, Backtesting, Dashboard, and Interactive Analysis.
"""
import argparse
import sys
import subprocess
from logger import get_logger, setup_logging
from config.trading_config import TradingConfig

setup_logging()
log = get_logger('main')

def run_live():
    from system.live_engine import live_engine
    log.info("Starting Live Trading Engine (Paper Trading Mode)")
    live_engine.start()

def run_backtest(ticker, start, end, strategy_name):
    from system.backtest_engine import BacktestEngine
    from strategies.strategy_researcher import strategy_engine
    
    strategy = strategy_engine.strategies.get(strategy_name)
    if not strategy:
        print(f"Error: Strategy {strategy_name} not found.")
        return

    engine = BacktestEngine(strategy)
    results = engine.run(ticker, start, end)
    
    if results:
        print("\n" + "="*45)
        print(f" BACKTEST: {ticker} | {strategy_name} ")
        print("="*45)
        print(f"Initial Capital:  ${results['initial_capital']:,.2f}")
        print(f"Final Value:      ${results['final_value']:,.2f}")
        print(f"Total Return:     {results['total_return']}%")
        print(f"Max Drawdown:     {results['max_drawdown']}%")
        print(f"Total Trades:     {results['total_trades']}")
        print(f"Commissions:      ${results['total_commission']:,.2f}")
        print(f"Slippage Cost:    ${results['total_slippage']:,.2f}")
        print("="*45)
    else:
        print("Backtest failed or returned no data.")

def run_dashboard():
    log.info("Launching Dashboard...")
    try:
        subprocess.run(['streamlit', 'run', 'dashboard/app.py'])
    except KeyboardInterrupt:
        pass


def run_optimize(ticker, start, end, strategy_name):
    from system.walk_forward_optimizer import WalkForwardOptimizer

    # Import the strategy CLASS (not the instance — we need fresh ones per combo)
    if strategy_name == 'rsi_mean_reversion':
        from strategies.rsi_strategy import RSIStrategy
        strategy_class = RSIStrategy
    elif strategy_name == 'momentum':
        print("⚠️  Walk-forward optimizer currently supports rsi_mean_reversion.")
        print("    Defaulting to RSIStrategy.")
        from strategies.rsi_strategy import RSIStrategy
        strategy_class = RSIStrategy
    else:
        print(f"Error: Strategy '{strategy_name}' not supported for optimization.")
        return

    print(f"\n🔍 Running Walk-Forward Optimization")
    print(f"   Ticker  : {ticker}")
    print(f"   Period  : {start} → {end}")
    print(f"   Strategy: {strategy_name}")
    print("   This may take a few minutes...\n")

    opt = WalkForwardOptimizer(strategy_class)
    results = opt.run(ticker, start, end)

    if results:
        filepath = opt.save_results(results)
        print(f"\n✅ Results saved to: {filepath}")

        # Immediately apply the new consensus params to the live strategy singleton.
        # This means you don't need to restart the system after optimizing.
        from strategies.rsi_strategy import load_wfo_params, rsi_strategy
        applied = load_wfo_params(rsi_strategy)
        if applied:
            print(f"\n🔄 Live strategy updated: {applied}")
    else:
        print("\n❌ Optimization failed. Check logs above.")

def interactive_menu():
    from system.system_architect import trading_system
    while True:
        print("\n--- Quant_firm Interactive ---")
        print("1. Analyze Ticker")
        print("2. Scan Watchlist")
        print("3. Run Daily Analysis")
        print("4. Exit")
        choice = input("Option: ")
        if choice == '1':
            ticker = input("Ticker: ").upper()
            trading_system.analyze_single_stock(ticker)
        elif choice == '2':
            trading_system.scan_watchlist()
        elif choice == '3':
            trading_system.run_daily_analysis()
        elif choice == '4':
            sys.exit(0)

def main():
    parser = argparse.ArgumentParser(description="Quant_firm Trading")
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--api', action='store_true')
    parser.add_argument('--backtest', nargs=3, metavar=('TICKER', 'START', 'END'))
    parser.add_argument('--strategy', default=TradingConfig.DEFAULT_STRATEGY)
    parser.add_argument('--dashboard', action='store_true')
    parser.add_argument('--optimize', nargs=3, metavar=('TICKER', 'START', 'END'),
                        help='Walk-forward optimization. e.g. --optimize AAPL 2023-01-01 2024-12-31')
    
    args = parser.parse_args()
    
    try:
        if args.live:
            run_live()
        elif args.optimize:
            run_optimize(args.optimize[0], args.optimize[1], args.optimize[2], args.strategy)
        elif args.backtest:
            run_backtest(args.backtest[0], args.backtest[1], args.backtest[2], args.strategy)
        elif args.dashboard:
            run_dashboard()
        elif args.api:
            try:
                import uvicorn
            except ImportError:
                print("❌ uvicorn not installed. Run: pip install uvicorn")
                sys.exit(1)
            log.info("Starting Stratex REST API on http://0.0.0.0:8000")
            log.info("Docs available at: http://localhost:8000/docs")
            uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
        else:
            interactive_menu()
    except KeyboardInterrupt:
        log.info("Exiting...")

if __name__ == "__main__":
    main()
