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

    # ── Signal quality gate ───────────────────────────────────
    # Minimum combined confidence (0.0–1.0) required to act on a signal.
    # Below this threshold the system holds regardless of direction.
    #
    # 0.55 means: "only trade when the strategy is at least 55% confident"
    # This filters out weak, borderline signals that are little better
    # than a coin flip.  Raise this to be more conservative.
    MIN_SIGNAL_CONFIDENCE = 0.55

    # ── Position sizing ───────────────────────────────────────
    # Fraction of total portfolio value allocated per new trade.
    # 0.05 = 5% per trade  →  max ~13 simultaneous positions within
    # the 10% cash reserve requirement.
    POSITION_SIZE_PCT = 0.05

    # TradingAgents
    USE_TRADING_AGENT = False
    TRADINGAGENTS_MODEL = 'gpt-4o-mini'
    TRADINGAGENTS_DEBATE_ROUNDS = 2
