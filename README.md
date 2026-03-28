# Stratex

> **A production-grade quantitative trading system** — multi-strategy signal generation, institutional-level risk management, backtesting engine, live paper trading via Alpaca, and a real-time Streamlit dashboard. Built in Python, designed for serious algorithmic trading research and deployment.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Strategies](#strategies)
- [Risk Management](#risk-management)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Usage](#usage)
- [Dashboard](#dashboard)
- [Backtesting](#backtesting)
- [Live Trading](#live-trading)
- [Data Layer](#data-layer)
- [Testing](#testing)
- [Team](#team)

---

## Overview

Quant_firm is a full-stack algorithmic trading platform built for quantitative research and live execution. It combines classical technical strategies (RSI, Momentum, Bollinger Bands, Pairs Trading) with an optional AI signal layer powered by GPT, all routed through a strict risk gate before any trade is executed.

The system is built around three core principles:

- **Signal quality over quantity** — multiple strategies must agree before a trade is taken
- **Risk first** — no trade bypasses the 6-check risk engine; two checks (daily loss, max drawdown) always fail closed
- **Graceful degradation** — the system runs on `yfinance` alone; AI and fundamentals are optional enhancements

**Initial capital:** $20,000 · **Default strategy:** RSI Mean Reversion · **Default watchlist:** AAPL, MSFT, NVDA, GOOGL, META, TSLA, AMZN, AMD, NFLX

---

## Architecture

```
main.py
├── --live          → LiveEngine (APScheduler cron jobs)
├── --backtest      → BacktestEngine (historical simulation)
├── --dashboard     → Streamlit dashboard
└── (default)       → Interactive CLI menu

TradingSystem (system_architect.py)
├── DataEngineer        → SQLite cache → yfinance
├── StrategyResearcher  → RSI / Momentum / MeanReversion / Pairs
├── SignalAggregator    → Conflict resolution, confidence scoring
├── RiskManager         → 6-check gate (position, cash, sector, loss, drawdown)
├── PositionSizer       → Fixed Fractional or Kelly Criterion
├── TradeAudit          → JSONL audit trail
└── AlpacaGateway       → Paper / live order execution
```

**Daily execution flow:**

```
run_daily_analysis()
    ├── update_all_prices()
    ├── check_stop_losses()
    ├── scan_watchlist()
    │     └── analyze_single_stock(ticker)
    │           ├── data_access.get_price_history()
    │           ├── strategy_engine.analyze()          ← technical signal
    │           ├── tradingagents.analyze()            ← AI signal (optional)
    │           ├── signal_aggregator.combine()        ← merge & resolve
    │           ├── risk_manager.approve_trade()       ← 6 checks
    │           └── _execute_trade()                   ← position + audit
    └── save_daily_report()
```

---

## Features

| Feature | Description |
|---|---|
| **Multi-strategy signals** | RSI, Momentum, Bollinger Bands, Pairs Trading — all run in parallel |
| **Signal aggregation** | Majority-vote conflict resolution with confidence bonuses |
| **6-check risk gate** | Position size, cash reserve, open positions, sector exposure, daily loss, max drawdown |
| **Position sizing** | Fixed fractional (confidence-scaled) or Kelly Criterion (half-Kelly default) |
| **Backtesting engine** | Realistic simulation with slippage (10bps) and commission ($0.005/share) |
| **Live paper trading** | Alpaca API integration with APScheduler cron jobs |
| **Smart data caching** | SQLite-first, yfinance fallback — strategies never wait for API calls |
| **Full audit trail** | Every trade decision logged to JSONL with full reasoning and risk check results |
| **Streamlit dashboard** | Real-time portfolio KPIs, strategy heatmap, order history, risk metrics |
| **AI signal layer** | Optional GPT-4o-mini via TradingAgents (disabled by default) |
| **Graceful degradation** | Runs without OpenAI or Alpha Vantage keys — yfinance is always the baseline |

---

## Strategies

All strategies inherit from `BaseStrategy` and follow a strict **signal contract**:

```python
{
    'ticker':        str,    # e.g. 'AAPL'
    'action':        str,    # 'BUY' | 'SELL' | 'HOLD'
    'confidence':    float,  # 0.0–1.0
    'current_price': float,  # last close price
    'reasoning':     str,    # human-readable explanation
    'signal_type':   str,    # e.g. 'RSI_OVERSOLD'
    'strategy':      str,    # strategy name
    'timestamp':     str,    # ISO-8601
}
```

### RSI Mean Reversion (default)

Uses Wilder's EWM smoothing (matching Bloomberg/TradingView standard).

| Parameter | Default | Meaning |
|---|---|---|
| `rsi_buy` | 25 | Buy when RSI drops below this |
| `rsi_sell` | 75 | Sell when RSI rises above this |
| `holding_days` | 5 | Max holding period |
| `stop_loss` | 5% | Hard downside cutoff |

### Momentum

Three-indicator system — trades only when indicators agree.

| Indicator | Signal |
|---|---|
| Rate of Change (ROC, 20d) | > +5% → bullish / < -5% → bearish |
| MA Crossover (10/30) | Golden cross → BUY / Death cross → SELL |
| Price vs MA (50d) | Price above → uptrend / below → downtrend |

Confidence scoring: all 3 agree → 85–95% · 2/3 agree → 65–75% · 1/3 → 50–60%

### Mean Reversion (Bollinger Bands + Z-Score)

Production-grade strategy with trend filter.

- **Entry:** Z-score > 1.5 std dev from mean + ADX < 25 (no strong trend) + volume confirmation (> 40th percentile)
- **Strong entry:** Z-score > 2.2
- **Stops:** ATR-based (1.5× ATR stop-loss, 3.0× ATR take-profit)
- **ADX filter:** Prevents trading in strong trends where mean reversion fails
- **Minimum data:** 60 bars required

### Pairs Trading (Statistical Arbitrage)

Advanced cointegration-based strategy .

- Engle-Granger cointegration test (rejects non-mean-reverting pairs)
- Dynamic OLS hedge ratio (proper β instead of hardcoded 1:1)
- Ornstein-Uhlenbeck half-life check (only trades pairs with realistic reversion speed)
- ATR-based stop-loss and take-profit on every signal

### Adding a New Strategy

```python
# 1. Create strategies/my_strategy.py
from strategies.base_strategy import BaseStrategy

class MyStrategy(BaseStrategy):
    def __init__(self):
        self.name = "My Strategy"

    def generate_signal(self, ticker, price_data) -> dict:
        # ... your logic ...
        return self._validate(signal)

my_strategy = MyStrategy()

# 2. Register in strategies/strategy_researcher.py
self.strategies = {
    'my_strategy': my_strategy,
    # ...
}
```

---

## Risk Management

Every trade passes through a **6-check gate** before execution. Two checks always fail closed — they cannot be overridden.

| Check | Limit | Fail behavior |
|---|---|---|
| Position size | ≤ 15% of portfolio per stock | Fail open (configurable) |
| Cash reserve | ≥ 10% cash at all times | Fail open |
| Open positions | ≤ 15 simultaneous positions | Fail open |
| Sector exposure | Per-sector caps (IT: 50%, Financials: 30%, etc.) | Fail open |
| Daily loss circuit | ≤ 3% daily loss | **Always fail closed** |
| Max drawdown halt | ≤ 15% peak-to-trough | **Always fail closed** |

Additional trade-level protection:
- Default stop-loss: **5%** per trade
- Default take-profit: **10%** per trade
- Minimum signal confidence: **55%** (configurable)
- Min Sharpe ratio threshold: **1.0**
- Max portfolio beta: **1.5**
- Max inter-asset correlation: **0.80**

### Position Sizing

Two methods selectable via `TradingConfig.POSITION_SIZING_METHOD`:

**Fixed Fractional (default):** Allocates a fixed percentage of portfolio per trade, optionally scaled by signal confidence.

**Kelly Criterion:** Mathematically optimal sizing for long-term growth.
```
f* = (p × b - q) / b
```
Where `p` = win probability (confidence), `b` = win/loss ratio (take-profit / stop-loss).
Default: **half-Kelly** (`KELLY_FRACTION = 0.5`) — retains growth benefit while cutting volatility. Capped at `MAX_POSITION_SIZE` (15%).

---

## Project Structure

```
Quant_firm/
│
├── main.py                         # Entry point — CLI flags and interactive menu
├── logger.py                       # Centralized logging (system, trades, errors, data, risk)
├── requirements.txt                # Dependencies
│
├── config/
│   ├── base_config.py              # Environment, API keys, paths, logging config
│   ├── trading_config.py           # Capital, watchlist, strategy, sizing, paper trading
│   └── risk_config.py              # All hard risk limits
│
├── data/
│   ├── data_engineer.py            # Central data facade (cache-first, API fallback)
│   ├── database.py                 # SQLite — prices, fundamentals, news
│   ├── stock_fetcher.py            # yfinance wrapper with retry and cleaning
│   ├── fundamental_fetcher.py      # Alpha Vantage fundamentals
│   ├── news_fetcher.py             # Alpha Vantage news
│   ├── retry.py                    # Retry decorator and fetch_with_retry utility
│   ├── health_check.py             # Data pipeline health monitoring
│   └── pipelines/
│       ├── data_cleaning.py        # OHLCV validation and cleaning
│       ├── daily_update.py         # Daily price update pipeline
│       └── weekly_update_fundamentals.py
│
├── strategies/
│   ├── base_strategy.py            # Abstract base + signal contract + _validate()
│   ├── strategy_researcher.py      # Strategy registry and analysis engine
│   ├── rsi_strategy.py             # RSI Mean Reversion
│   ├── momentum_strategy.py        # Multi-indicator Momentum
│   ├── mean_reversion_strategy.py  # Bollinger Bands + Z-Score
│   └── pairs_strategy.py           # Statistical Arbitrage (Pairs Trading)
│
├── system/
│   ├── system_architect.py         # TradingSystem — central orchestrator
│   ├── signal_aggregator.py        # Multi-signal conflict resolution
│   ├── backtest_engine.py          # Historical simulation with fill models
│   ├── live_engine.py              # APScheduler cron jobs (pre-market, open, close)
│   ├── market_calendar.py          # NYSE trading day checker
│   └── tradingagents_integration.py # Optional GPT signal layer
│
├── risk/
│   ├── risk_manager.py             # 6-check gate before every trade
│   ├── position_sizer.py           # Fixed fractional and Kelly Criterion
│   ├── trade_audit.py              # JSONL audit trail for every decision
│   └── portfolio/
│       ├── portfolio_tracker.py    # Positions, cash, P&L (persisted to CSV)
│       └── portfolio_calculator.py # Sector, beta, correlation, Sharpe, VaR
│
├── execution/
│   ├── alpaca_gateway.py           # Alpaca paper/live broker gateway
│   └── fill_models.py              # Slippage and commission simulation
│
├── dashboard/
│   ├── app.py                      # Streamlit dashboard entry point
│   └── components.py               # KPI cards, charts, heatmaps, export buttons
│
├── docs/                           # Research notes — strategies, risk metrics, terms
├── test/                           # pytest test suite
└── tradingagents/                  # Embedded MIT TradingAgents subproject (optional AI)
```

---

## Getting Started

### Prerequisites

- Python 3.10+
- Git

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/mehdibounouif/Quant_firm.git
cd Quant_firm

# 2. Create and activate a virtual environment
python -m venv venv

# Mac / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

### Environment Setup

```bash
cp .env.example .env
```

Open `.env` and fill in your keys:

```env
# Required for live trading
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_SECRET_KEY=your_alpaca_secret_key
ALPACA_BASE_URL=https://paper-api.alpaca.markets   # Use paper URL for testing

# Optional — fundamentals and news data
ALPHA_VANTAGE_API_KEY=your_alpha_vantage_key

# Optional — AI signal layer (only if USE_TRADING_AGENT=True in trading_config.py)
OPENAI_API_KEY=your_openai_api_key

# System
ENVIRONMENT=development
DEBUG=True
DATABASE_URL=sqlite:///data/trading_data.db
```

> **Note:** The system runs fully without Alpaca, Alpha Vantage, or OpenAI keys. Price data from yfinance requires no key. You will receive warnings in the logs for missing optional keys — these are safe to ignore during development.


**Workflow:**
```bash
# Always pull before starting work
git pull origin development

# Work on your branch
git checkout system   # or risk / data

# Merge into development (never push directly to main)
git checkout development
git pull origin development
git merge system
git push origin development
```



---

## Configuration

All configuration is centralized in three files under `/config`. No magic strings anywhere else.

### `config/trading_config.py`

```python
INITIAL_CAPITAL        = 20000          # Starting portfolio value ($)
DEFAULT_WATCHLIST      = ['AAPL', 'MSFT', 'NVDA', ...]
DEFAULT_STRATEGY       = 'rsi_mean_reversion'
MIN_SIGNAL_CONFIDENCE  = 0.55           # Minimum confidence to act (0.0–1.0)
POSITION_SIZE_PCT      = 0.05           # 5% of portfolio per trade
POSITION_SIZING_METHOD = 'fixed_fractional'  # or 'kelly'
KELLY_FRACTION         = 0.5            # Half-Kelly (conservative)
USE_PAPER_TRADING      = True           # Always start with paper trading
USE_TRADING_AGENT      = False          # Enable GPT signal layer
TRADINGAGENTS_MODEL    = 'gpt-4o-mini'
```

### `config/risk_config.py`

```python
MAX_POSITION_SIZE         = 0.15   # 15% max per stock
MIN_CASH_RESERVE          = 0.10   # Keep 10% cash always
MAX_TOTAL_POSITIONS       = 15     # Max simultaneous positions
MAX_DAILY_LOSS            = 0.03   # 3% daily loss circuit breaker
MAX_DRAWDOWN_BEFORE_HALT  = 0.15   # 15% max drawdown — halts all trading
DEFAULT_STOP_LOSS_PCT     = 0.05   # 5% stop-loss per trade
DEFAULT_TAKE_PROFIT_PCT   = 0.10   # 10% take-profit per trade
MIN_SHARPE_RATIO          = 1.0
MAX_PORTFOLIO_BETA        = 1.5
MAX_CORRELATION           = 0.80
```

---

## Usage

### Interactive Mode (recommended for first run)

```bash
python main.py
```

```
--- Quant_firm Interactive ---
1. Analyze Ticker
2. Scan Watchlist
3. Run Daily Analysis
4. Exit
Option:
```

### Command Line Flags

```bash
# Run a backtest on AAPL using the default strategy
python main.py --backtest AAPL 2024-01-01 2024-12-31

# Run a backtest with a specific strategy
python main.py --backtest NVDA 2024-01-01 2024-12-31 --strategy momentum

# Launch the Streamlit dashboard
python main.py --dashboard

# Start the live trading engine (paper trading by default)
python main.py --live
```

### Available Strategy Names

| Flag value | Strategy |
|---|---|
| `rsi_mean_reversion` | RSI Mean Reversion (default) |
| `momentum` | Multi-indicator Momentum |
| `mean_reversion` | Bollinger Bands + Z-Score |

### Backtest Output Example

```
=============================================
 BACKTEST: AAPL | RSI Mean Reversion
=============================================
Initial Capital:  $20,000.00
Final Value:      $24,830.00
Total Return:     24.15%
Max Drawdown:     -8.42%
Total Trades:     37
Commissions:      $12.45
Slippage Cost:    $23.80
=============================================
```

---

## Dashboard

Launch the Streamlit dashboard:

```bash
python main.py --dashboard
# or directly:
streamlit run dashboard/app.py
```

The dashboard provides:

- **Portfolio KPIs** — total value, cash balance, realized/unrealized P&L, return %
- **Risk metrics** — current drawdown, daily loss, portfolio beta, Sharpe ratio
- **Open positions** — real-time position table with entry price, current price, P&L
- **Strategy heatmap** — signal history across all tickers and strategies
- **Order history** — full list of executed trades with reasoning
- **System health** — data pipeline status, last update timestamps
- **Export buttons** — download portfolio report and audit log as CSV

The dashboard auto-refreshes every 60 seconds during market hours.

---

## Backtesting

The backtest engine simulates realistic trading with:

- **Slippage model:** Percentage-based (10 basis points default)
- **Commission model:** Per-share ($0.005/share default)
- **Fill simulation:** Configurable via `FillSimulator`
- **Isolated portfolio:** Backtests never touch live portfolio data
- **Multi-strategy support:** Run all strategies simultaneously with signal aggregation

```python
from system.backtest_engine import BacktestEngine
from strategies.rsi_strategy import rsi_strategy

engine = BacktestEngine(rsi_strategy, initial_capital=20000)
results = engine.run('AAPL', '2024-01-01', '2024-12-31')
```

Customize fill simulation:

```python
# config/trading_config.py
BACKTEST_SLIPPAGE_MODEL    = 'percentage'   # 'percentage' | 'fixed' | 'volume_based'
BACKTEST_SLIPPAGE_VALUE    = 0.001          # 10 bps
BACKTEST_COMMISSION_MODEL  = 'per_share'    # 'per_share' | 'percentage' | 'flat'
BACKTEST_COMMISSION_RATE   = 0.005          # $0.005 per share
```

---

## Live Trading

> **Important:** Always start with paper trading (`USE_PAPER_TRADING = True` in `trading_config.py`). Never switch to live capital without extensive backtesting.

The live engine uses **APScheduler** with four scheduled jobs:

| Time (NY) | Job | Description |
|---|---|---|
| 09:00 AM | Pre-market | Warms data cache for all watchlist tickers |
| 09:35 AM | Market open | Runs full watchlist scan, generates and executes signals |
| 12:30 PM | Mid-day | Checks stop-losses, updates position prices |
| 03:55 PM | Market close | Saves daily report, logs performance summary |

The system automatically skips non-trading days via `market_calendar.py`.

**Alpaca paper trading setup:**
1. Create a free account at [alpaca.markets](https://alpaca.markets)
2. Generate paper trading API keys from the dashboard
3. Add them to your `.env` file
4. Set `USE_PAPER_TRADING = True`
5. Run `python main.py --live`

---

## Data Layer

The data layer uses a **cache-first architecture** — strategies always receive clean, validated data with no API latency.

```
Strategy requests data
        ↓
Check SQLite cache (< 1 day old?)
        ↓ YES                    ↓ NO
Return cached data        Fetch from yfinance
                                ↓
                          Clean & validate (DataCleaner)
                                ↓
                          Save to SQLite cache
                                ↓
                          Return clean DataFrame
```

**Available data access methods:**

```python
from data.data_engineer import data_access

# Price history (OHLCV DataFrame)
df = data_access.get_price_history('AAPL', days=90)

# Latest price (float)
price = data_access.get_latest_price('AAPL')

# Multiple tickers at once (dict of DataFrames)
data = data_access.get_multiple_stocks(['AAPL', 'MSFT', 'NVDA'], days=60)

# Fundamentals (requires Alpha Vantage key)
fundamentals = data_access.get_fundamentals('AAPL')

# News (requires Alpha Vantage key)
news = data_access.get_news('AAPL', days=7)
```

**Data cleaning pipeline** (`data/pipelines/data_cleaning.py`):
- Removes duplicate rows and NaN OHLCV values
- Validates price consistency (Open/High/Low/Close ranges)
- Detects and handles outliers
- Ensures minimum data requirements are met before strategies receive the DataFrame

---

## Testing

The project uses **pytest** with a full test suite covering all major components.

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=. --cov-report=term-missing

# Run a specific test file
pytest test/test_risk_manger.py -v
pytest test/test_momentum_strategy.py -v
pytest test/test_portfolio_tracker.py -v
```

**Test coverage includes:**
- `test_data_cleaning.py` — DataCleaner edge cases
- `test_database.py` — SQLite CRUD and cache logic
- `test_momentum_strategy.py` — Signal generation for all market conditions
- `test_portfolio_calculator.py` — Sharpe, beta, correlation, VaR calculations
- `test_portfolio_tracker.py` — Position management and P&L tracking
- `test_position_sizer.py` — Fixed fractional and Kelly sizing math
- `test_risk_manger.py` — All 6 risk checks, including circuit breaker behavior
- `test_rsi_strategy.py` — RSI calculation and signal generation
- `test_trade_audit.py` — JSONL write/read and audit trail integrity
- `test_system.py` — End-to-end orchestration smoke tests

---

## Logging

The system writes to six separate log files under `/logs/`:

| File | Contents |
|---|---|
| `logs/system.log` | General application activity |
| `logs/trades.log` | Trade execution events only |
| `logs/errors.log` | Errors and exceptions only |
| `logs/data_fetch.log` | Data pipeline operations |
| `logs/strategies.log` | Strategy signal generation |
| `logs/risk.log` | Risk check results per trade |

Log rotation: 10MB per file, 5 backup files kept.

---

## Team

| Name | Role | Branch |
|---|---|---|
| **Mehdi Bounouif** | System Architect | `system` |
| **Kawtar bouarfa** | Risk Manager | `risk` |
| **Abdlilah afahmi** | Data Engineer | `data` |

---


*Created by - Mehdi-bounouif - Abdlilah afahmi - Kawtar bouarfa*
