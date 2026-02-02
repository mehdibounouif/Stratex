import sys
from system.system_architect import trading_system

def main():
   
    print("\nSelect operation:")
    print("1. Analyze single stock")
    print("2. Scan entire watchlist")
    print("3. Run daily analysis")
    print("4. Exit")
    
    choice = input("\nEnter choice (1-4): ").strip()
    
    if choice == '1':
        ticker = input("Enter ticker symbol: ").strip().upper()
        result = trading_system.analyze_single_stock(ticker)
        print(f"\n{'='*60}")
        print("FINAL DECISION:")
        print(f"{'='*60}")
        print(result)
    
    elif choice == '2':
        results = trading_system.scan_watchlist()
    
    elif choice == '3':
        results = trading_system.run_daily_analysis()
    
    elif choice == '4':
        print("\nSee you homie!")
        sys.exit(0)
    
    else:
        print("\nInvalid choice")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()