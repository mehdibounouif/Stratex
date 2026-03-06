class TradingConfig:

    # Defualt capital
    INITIAL_CAPITAL = 20000 #$

    # Defualt Stock Watchlist
    DEFAULT_WATCHLIST = [
            'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META',
            'TSLA', 'AMZN', 'AMD', 'NFLX']

    # Trading hours
    MARKET_OPEN = "09:30"
    MARKET_CLOSE = "16:00"

    # Defualt strategy
    DEFAULT_STRATEGY = "rsi_mean_reversion"

    # TradingAgents
    USE_TRADING_AGENT = False
    TRADINGAGENTS_MODEL = 'gpt-4o-mini'
    TRADINGAGENTS_DEBATE_ROUNDS = 2
