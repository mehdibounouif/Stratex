# config/risk_config.py

class RiskConfig:
    """
    Centralized configuration for portfolio risk management.
    This file defines HARD LIMITS that all trading logic must obey.
    """

    # =========================
    # POSITION SIZE LIMITS
    # =========================

    # Maximum allocation allowed in a single stock
    # Prevents one position from dominating the portfolio
    MAX_POSITION_SIZE = 0.15  # 15% of total portfolio per stock

    # Minimum allocation for any position
    # Avoids tiny, meaningless positions (noise / overtrading)
    MIN_POSITION_SIZE = 0.02  # 2% minimum per stock


    # =========================
    # SECTOR EXPOSURE LIMITS
    # =========================

    # Maximum percentage of portfolio allowed per sector
    # Protects against sector-wide crashes (concentration risk)
    MAX_SECTOR_EXPOSURE = {
        'technology': 0.50,   # Tech stocks capped at 50%
        'finance': 0.30,      # Financials capped at 30%
        'healthcare': 0.30,   # Healthcare capped at 30%
        'consumer': 0.30,     # Consumer goods capped at 30%
        'energy': 0.20,       # Energy capped at 20% (typically volatile)
        'other': 0.40         # Catch-all for uncategorized assets
    }


    # =========================
    # PORTFOLIO STRUCTURE RULES
    # =========================

    # Minimum cash held at all times
    # Ensures liquidity and ability to react to market changes
    MIN_CASH_RESERVE = 0.10  # Keep at least 10% in cash

    # Maximum number of open positions
    # Prevents over-diversification and operational complexity
    MAX_TOTAL_POSITIONS = 15

    # Minimum number of positions
    # Prevents excessive concentration in too few assets
    MIN_TOTAL_POSITIONS = 5


    # =========================
    # LOSS & DRAWDOWN LIMITS
    # =========================

    # Maximum allowed loss in a single trading day
    # Acts as a circuit breaker during bad market conditions
    MAX_DAILY_LOSS = 0.03  # 3% daily loss limit

    # Maximum allowed cumulative loss over a week
    # Protects against prolonged drawdowns
    MAX_WEEKLY_LOSS = 0.07  # 7% weekly loss limit

    # Maximum peak-to-trough portfolio drawdown
    # Trading should halt if this is breached
    MAX_DRAWDOWN_BEFORE_HALT = 0.15  # 15% max drawdown
    # b3aybach calculate drawdown and compare it with MAX_DRAWDOWN_BEFORE_HALT

    # =========================
    # RISK METRICS LIMITS
    # =========================

    # Maximum portfolio beta
    # Controls sensitivity to overall market movements
    # Beta > 1 means portfolio moves more than the market
    MAX_PORTFOLIO_BETA = 1.5 # b3aybach calculate sensitive are we and compare it with MAX_PORTFOLIO

    # Maximum allowed correlation between assets
    # Prevents adding highly correlated positions
    # (avoids fake diversification)
    MAX_CORRELATION = 0.80 # b3ayback calculate correlation between assets and compare it with MAX_CORRELATION

    # Minimum acceptable Sharpe ratio
    # Ensures risk taken is justified by returns
    # Sharpe < 1 means poor risk-adjusted performance
    MIN_SHARPE_RATIO = 1.0


    # =========================
    # DEFAULT TRADE PROTECTION
    # =========================

    # Default stop-loss percentage per trade
    # Automatically limits downside risk
    DEFAULT_STOP_LOSS_PCT = 0.05  # 5% loss cutoff

    # Default take-profit percentage per trade
    # Locks in gains and avoids greed-driven losses
    DEFAULT_TAKE_PROFIT_PCT = 0.10  # 10% profit target

