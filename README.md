<div align="center">

# Stratex

**Production-grade algorithmic trading platform**

Multi-strategy signal generation · Institutional risk management · Walk-forward optimization · Live paper trading · REST API · Real-time dashboard

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?style=flat-square)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

</div>

---

## Overview

Stratex is a full-stack quantitative trading system built for serious algorithmic research and live execution. It combines four classical technical strategies with an optional AI signal layer, all routed through a strict institutional-grade risk engine before any trade is executed.

Three core principles drive every design decision:

- **Signal quality over quantity** — strategies must agree before a trade is taken; a confidence gate rejects weak signals below 55%
- **Risk first** — no trade bypasses the 6-check risk gate; daily loss and max drawdown checks always fail closed and cannot be overridden
- **Graceful degradation** — the system runs on `yfinance` alone; Alpaca, Alpha Vantage, and OpenAI are optional enhancements

**Capital:** $100,000 · **Default strategy:** RSI Mean Reversion · **Watchlist:** AAPL, MSFT, NVDA, GOOGL, META, TSLA, AMZN, AMD, NFLX

---

## Table of Contents

- [Architecture](#architecture)
- [Features](#features)
- [Strategies](#strategies)
- [Walk-Forward Optimization](#walk-forward-optimization)
- [Risk Management](#risk-management)
- [REST API](#rest-api)
- [Alert System](#alert-system)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Usage](#usage)
- [Dashboard](#dashboard)
- [Backtesting](#backtesting)
- [Live Trading](#live-trading)
- [Data Layer](#data-layer)
- [Docker Deployment](#docker-deployment)
- [Testing](#testing)
- [Team](#team)

---

## Architecture

```
main.py
├── --live          → LiveEngine       (APScheduler cron jobs)
├── --backtest      → BacktestEngine   (historical simulation)
├── --optimize      → WalkForwardOptimizer (parameter search)
├── --dashboard     → Streamlit dashboard
├── --api           → FastAPI REST API (uvicorn)
└── (default)       → Interactive CLI menu

TradingSystem (system_architect.py)
├── DataEngineer         → SQLite cache → yfinance
├── StrategyResearcher   → RSI / Momentum / MeanReversion / Pairs
├── SignalAggregator     → Conflict resolution, confidence scoring
├── RiskManager          → 6-check gate
├── PositionSizer        → Fixed Fractional or Kelly Criterion
├── TradeAudit           → JSONL audit trail
├── AlertManager         → Email + Telegram notifications
└── AlpacaGateway        → Paper / live order execution
```

**Daily execution flow:**

```
run_daily_analysis()
    ├── update_all_prices()
    ├── check_stop_losses()
    ├── scan_watchlist()
    │     └── analyze_single_stock(ticker)
    │           ├── data_access.get_price_history()
    │           ├── strategy_engine.analyze()        ← all active strategies
    │           ├── tradingagents.analyze()           ← AI signal (optional)
    │           ├── signal_aggregator.combine()       ← merge & resolve conflicts
    │           ├── confidence gate (< 55% → HOLD)
    │           ├── risk_manager.approve_trade()      ← 6 checks
    │           ├── _execute_trade()                  ← position + audit
    │           └── alert_manager.send()              ← email + Telegram
    └── save_daily_report()
```

---

## Features

| Feature | Description |
|---|---|
| **4 active strategies** | RSI, Momentum, Bollinger Bands, Pairs Trading — all run in parallel |
| **Signal aggregation** | Majority-vote conflict resolution with confidence bonuses |
| **6-check risk gate** | Position size, cash reserve, open positions, sector exposure, daily loss, max drawdown |
| **Walk-forward optimization** | Finds best strategy parameters without overfitting; auto-loads consensus into live trading |
| **Position sizing** | Fixed fractional (confidence-scaled) or Kelly Criterion (half-Kelly default) |
| **Backtesting engine** | Realistic simulation with slippage (10bps) and commission ($0.005/share) |
| **Live paper trading** | Alpaca API integration with APScheduler cron jobs |
| **REST API** | FastAPI with API key authentication, interactive docs at `/docs` |
| **Alert system** | Email (Gmail SMTP) + Telegram Bot — trade and risk events in real time |
| **Smart data caching** | SQLite-first, yfinance fallback — strategies never wait for API calls |
| **Full audit trail** | Every trade decision logged to JSONL with full reasoning and risk check results |
| **Streamlit dashboard** | Real-time portfolio KPIs, strategy heatmap, order history, risk metrics |
| **AI signal layer** | Optional GPT-4o-mini via TradingAgents (disabled by default) |
| **Docker deployment** | Full multi-service Compose setup (engine + dashboard + API) |
| **CI pipeline** | GitHub Actions with pytest and 45% coverage threshold |

---

## Strategies

All strategies inherit from `BaseStrategy` and return a standard signal contract:

```python
{
    'ticker':        str,    # e.g. 'AAPL'
    'action':        str,    # 'BUY' | 'SELL' | 'HOLD'
    'confidence':    float,  # 0.0–1.0
    'current_price': float,
    'reasoning':     str,
    'signal_type':   str,    # e.g. 'RSI_OVERSOLD'
    'strategy':      str,
    'timestamp':     str,    # ISO-8601
}
```

### RSI Mean Reversion (default)

Uses Wilder's EWM smoothing — matching Bloomberg and TradingView standard RSI values.

| Parameter | Default | Meaning |
|---|---|---|
| `rsi_buy` | 25 | Buy when RSI drops below this |
| `rsi_sell` | 75 | Sell when RSI rises above this |
| `holding_days` | 5 | Max holding period |
| `stop_loss` | 5% | Hard downside cutoff |

> Parameters are automatically overridden by Walk-Forward Optimization consensus on startup.

### Momentum

Three-indicator system — trades only when all indicators agree.

| Indicator | Signal |
|---|---|
| Rate of Change (ROC, 20d) | > +5% → bullish / < -5% → bearish |
| MA Crossover (10/30) | Golden cross → BUY / Death cross → SELL |
| Price vs MA (50d) | Price above → uptrend / below → downtrend |

Confidence: all 3 agree → 85–95% · 2/3 agree → 65–75% · 1/3 → 50–60%

### Mean Reversion (Bollinger Bands + Z-Score)

Production-grade strategy with trend filter.

- **Entry:** Z-score > 1.5 std dev from mean + ADX < 25 (no strong trend) + volume confirmation (> 40th percentile)
- **Strong entry:** Z-score > 2.2
- **Stops:** ATR-based (1.5× ATR stop-loss, 3.0× ATR take-profit)
- **Minimum data:** 60 bars required

### Pairs Trading (Statistical Arbitrage)

- Engle-Granger cointegration test — rejects non-mean-reverting pairs
- Dynamic OLS hedge ratio — proper β instead of hardcoded 1:1
- Ornstein-Uhlenbeck half-life check — only trades pairs with realistic reversion speed
- ATR-based stop-loss and take-profit on every signal

### Adding a New Strategy

```python
# 1. Create strategies/my_strategy.py
from strategies.base_strategy import BaseStrategy

class MyStrategy(BaseStrategy):
    def __init__(self):
        self.name = "My Strategy"

    def generate_signal(self, ticker, price_data) -> dict:
        # your logic
        return self._validate(signal)

my_strategy = MyStrategy()

# 2. Register in strategies/strategy_researcher.py
self.strategies['my_strategy'] = my_strategy
```

The system picks it up automatically — no changes needed in `system_architect.py`.

---

## Walk-Forward Optimization

Finds the best strategy parameters without overfitting to a single historical period.

**How it works:**

```
Full date range split into rolling windows
        ↓
Each window:
    IN-SAMPLE  (6 months) → test all param combinations → pick best
    OUT-OF-SAMPLE (2 months) → validate best params on unseen data
        ↓
Aggregate across all windows → consensus params
        ↓
Auto-loaded into live rsi_strategy on startup
```

**Run it:**

```bash
python main.py --optimize AAPL 2023-01-01 2024-12-31
```

Results are saved to `optimization_results/wfo_AAPL_<timestamp>.json` and immediately applied to the live strategy — no restart needed.

**Default parameter grid:**

```python
{
    "rsi_buy":      [20, 25, 30],
    "rsi_sell":     [70, 75, 80],
    "holding_days": [3, 5, 7],
    "stop_loss":    [0.03, 0.05, 0.07],
}
```

---

## Risk Management

Every trade passes through a **6-check gate**. Two checks always fail closed — they cannot be overridden by any configuration.

| Check | Limit | Fail behavior |
|---|---|---|
| Position size | ≤ 15% of portfolio per stock | Fail open (configurable) |
| Cash reserve | ≥ 10% cash at all times | Fail open |
| Open positions | ≤ 15 simultaneous positions | Fail open |
| Sector exposure | Per-sector caps (IT: 50%, Financials: 30%, …) | Fail open |
| Daily loss circuit | ≤ 3% daily loss | **Always fail closed** |
| Max drawdown halt | ≤ 15% peak-to-trough | **Always fail closed** |

Additional per-trade protection:

- Stop-loss: **5%** · Take-profit: **10%**
- Minimum signal confidence: **55%**
- Min Sharpe ratio: **1.0** · Max portfolio beta: **1.5** · Max correlation: **0.80**

### Position Sizing

**Fixed Fractional (default):** 5% of portfolio per trade, scaled by signal confidence.

**Kelly Criterion:**

```
f* = (p × b − q) / b
```

Where `p` = win probability (confidence), `b` = win/loss ratio (take-profit / stop-loss).
Default: **half-Kelly** (`KELLY_FRACTION = 0.5`). Capped at 15%.

---

## REST API

Full FastAPI interface with interactive docs and API key authentication.

**Start the API:**

```bash
python main.py --api
# Docs: http://localhost:8000/docs
```

**Authentication:**

All endpoints except `/health` require an `X-API-Key` header.

```bash
# Generate a key
python3 -c "import secrets; print(secrets.token_hex(32))"

# Add to .env
API_SECRET_KEY=your-generated-key

# Use in requests
curl -H "X-API-Key: your-key" http://localhost:8000/portfolio
```

**Endpoints:**

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `GET` | `/health` | API status check | Public |
| `GET` | `/portfolio` | Live positions and portfolio value | Required |
| `GET` | `/portfolio/performance` | Full performance metrics | Required |
| `GET` | `/signals/{ticker}` | Signal for a single ticker | Required |
| `GET` | `/signals/scan` | Scan full watchlist | Required |
| `POST` | `/backtest` | Run historical backtest | Required |
| `GET` | `/audit` | Last N trade decisions | Required |

**Backtest request body:**

```json
{
    "ticker": "AAPL",
    "start_date": "2024-01-01",
    "end_date": "2024-12-31",
    "strategy": "rsi_mean_reversion",
    "initial_capital": 100000
}
```

Available strategy values: `rsi_mean_reversion`, `momentum`, `mean_reversion`, `pairs`

---

## Alert System

Real-time notifications for trade execution and risk events via **Email** and **Telegram**.

| Event | Email | Telegram |
|---|---|---|
| BUY executed | ✅ | ✅ |
| SELL executed | ✅ | ✅ |
| Stop-loss triggered | ✅ | ✅ |
| Circuit breaker fired | ✅ | ✅ |
| Daily report saved | ✅ | — |

**Telegram setup (2 minutes):**

1. Message `@BotFather` on Telegram → `/newbot` → copy your token
2. Message your bot once, then visit: `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Copy the `id` field from the response — that is your `TELEGRAM_CHAT_ID`
4. Add both to `.env` and run `python test_alert.py` to verify

---

## Project Structure

```
Stratex/
│
├── main.py                              # Entry point — all CLI flags
├── logger.py                            # Centralized logging (6 log files)
├── requirements.txt
│
├── api/
│   └── main.py                          # FastAPI app — all REST endpoints
│
├── config/
│   ├── base_config.py                   # Environment, API keys, paths
│   ├── trading_config.py                # Capital, watchlist, strategy, sizing
│   └── risk_config.py                   # All hard risk limits
│
├── data/
│   ├── data_engineer.py                 # Central data facade (cache-first)
│   ├── database.py                      # SQLite — prices, fundamentals, news
│   ├── stock_fetcher.py                 # yfinance wrapper with retry
│   ├── fundamental_fetcher.py           # Alpha Vantage fundamentals
│   ├── news_fetcher.py                  # Alpha Vantage news
│   ├── retry.py                         # Retry decorator
│   ├── health_check.py                  # Data pipeline health monitoring
│   └── pipelines/
│       ├── data_cleaning.py             # OHLCV validation and cleaning
│       ├── daily_update.py
│       └── weekly_update_fundamentals.py
│
├── strategies/
│   ├── base_strategy.py                 # Abstract base + signal contract
│   ├── strategy_researcher.py           # Strategy registry and engine
│   ├── rsi_strategy.py                  # RSI Mean Reversion + WFO loader
│   ├── momentum_strategy.py             # Multi-indicator Momentum
│   ├── mean_reversion_strategy.py       # Bollinger Bands + Z-Score
│   └── pairs_strategy.py                # Statistical Arbitrage
│
├── system/
│   ├── system_architect.py              # TradingSystem — central orchestrator
│   ├── signal_aggregator.py             # Multi-signal conflict resolution
│   ├── backtest_engine.py               # Historical simulation
│   ├── live_engine.py                   # APScheduler cron jobs
│   ├── walk_forward_optimizer.py        # Parameter optimization
│   ├── alert_manager.py                 # Email + Telegram alerts
│   ├── market_calendar.py               # NYSE trading day checker
│   └── tradingagents_integration.py     # Optional GPT signal layer
│
├── risk/
│   ├── risk_manager.py                  # 6-check gate
│   ├── position_sizer.py                # Fixed fractional and Kelly
│   ├── trade_audit.py                   # JSONL audit trail
│   └── portfolio/
│       ├── portfolio_tracker.py         # Positions, cash, P&L
│       └── portfolio_calculator.py      # Sector, beta, Sharpe, VaR
│
├── execution/
│   ├── alpaca_gateway.py                # Alpaca paper/live broker
│   └── fill_models.py                   # Slippage and commission simulation
│
├── dashboard/
│   ├── app.py                           # Streamlit dashboard
│   └── components.py                    # KPI cards, charts, heatmaps
│
├── optimization_results/                # WFO output JSON files
├── docs/                                # Research notes
├── test/                                # pytest test suite (10 files)
├── scripts/
│   └── start.sh                         # Docker startup script
├── Dockerfile
└── docker-compose.yml
```

---

## Getting Started

### Prerequisites

- Python 3.10+
- Git
- Docker + Docker Compose (optional, for containerized deployment)

### Installation

```bash
# Clone the repository
git clone https://github.com/mehdibounouif/Stratex.git
cd Stratex

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate        # Linux / macOS
venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt
```

### Environment Setup

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# Required for live trading
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# REST API authentication
API_SECRET_KEY=your-generated-secret   # python3 -c "import secrets; print(secrets.token_hex(32))"

# Alerts — Email
ALERT_EMAIL_FROM=stratexalerts@gmail.com
ALERT_EMAIL_TO=you@email.com
ALERT_EMAIL_PASSWORD=your_gmail_app_password

# Alerts — Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Optional
OPENAI_API_KEY=sk-...          # AI signal layer
ALPHA_VANTAGE_API_KEY=...      # Fundamentals and news
```

> The system runs fully without any optional keys. You will see warnings in the logs for missing keys — these are safe to ignore during development.

---

## Configuration

All configuration lives in `/config`. No magic strings anywhere else in the codebase.

### `config/trading_config.py`

```python
INITIAL_CAPITAL        = 100000         # Starting portfolio value ($)
DEFAULT_WATCHLIST      = ['AAPL', 'MSFT', 'NVDA', ...]
DEFAULT_STRATEGY       = 'rsi_mean_reversion'
MIN_SIGNAL_CONFIDENCE  = 0.55           # Below this → HOLD regardless
POSITION_SIZE_PCT      = 0.05           # 5% per trade
POSITION_SIZING_METHOD = 'fixed_fractional'  # or 'kelly'
KELLY_FRACTION         = 0.5            # Half-Kelly (conservative)
USE_PAPER_TRADING      = True
USE_TRADING_AGENT      = False          # Enable GPT signal layer
```

### `config/risk_config.py`

```python
MAX_POSITION_SIZE        = 0.15   # 15% max per stock
MIN_CASH_RESERVE         = 0.10   # Keep 10% cash always
MAX_TOTAL_POSITIONS      = 15
MAX_DAILY_LOSS           = 0.03   # 3% daily loss circuit breaker
MAX_DRAWDOWN_BEFORE_HALT = 0.15   # 15% max drawdown — halts all trading
DEFAULT_STOP_LOSS_PCT    = 0.05
DEFAULT_TAKE_PROFIT_PCT  = 0.10
```

---

## Usage

### Interactive Mode

```bash
python main.py
```

```
--- Stratex Interactive ---
1. Analyze Ticker
2. Scan Watchlist
3. Run Daily Analysis
4. Exit
```

### Command Line Flags

```bash
# Live paper trading (scheduled cron jobs)
python main.py --live

# Backtest a strategy
python main.py --backtest AAPL 2024-01-01 2024-12-31
python main.py --backtest NVDA 2024-01-01 2024-12-31 --strategy momentum

# Walk-forward optimization
python main.py --optimize AAPL 2023-01-01 2024-12-31

# Streamlit dashboard
python main.py --dashboard

# REST API
python main.py --api
```

### Available Strategy Names

| Flag value | Strategy |
|---|---|
| `rsi_mean_reversion` | RSI Mean Reversion (default) |
| `momentum` | Multi-indicator Momentum |
| `mean_reversion` | Bollinger Bands + Z-Score |
| `pairs` | Statistical Arbitrage |

---

## Dashboard

```bash
python main.py --dashboard
# → http://localhost:8501
```

- Portfolio KPIs — value, cash, realized/unrealized P&L, return %
- Risk metrics — drawdown, daily loss, beta, Sharpe ratio
- Open positions — entry price, current price, P&L per position
- Strategy heatmap — signal history across all tickers and strategies
- Order history — full trade log with reasoning
- System health — data pipeline status and last update timestamps
- Export buttons — portfolio report and audit log as CSV

Auto-refreshes every 60 seconds during market hours.

---

## Backtesting

```bash
python main.py --backtest AAPL 2024-01-01 2024-12-31
```

```
=============================================
 BACKTEST: AAPL | RSI Mean Reversion
=============================================
Initial Capital:  $100,000.00
Final Value:      $124,150.00
Total Return:     24.15%
Max Drawdown:     -8.42%
Total Trades:     37
Win Rate:         62.2%
Sharpe Ratio:     1.43
Commissions:      $12.45
Slippage Cost:    $23.80
=============================================
```

**Fill simulation defaults:**

| Parameter | Default |
|---|---|
| Slippage model | Percentage-based |
| Slippage value | 10 basis points |
| Commission model | Per-share |
| Commission rate | $0.005 / share |

---

## Live Trading

> **Always start with paper trading.** Never switch `USE_PAPER_TRADING` to `False` without extensive backtesting.

The live engine uses **APScheduler** with four scheduled jobs in NYSE timezone:

| Time (NY) | Job | Description |
|---|---|---|
| 09:00 AM | Pre-market | Warms data cache for all watchlist tickers |
| 09:35 AM | Market open | Full watchlist scan → signals → risk gate → execution |
| 12:30 PM | Mid-day | Checks stop-losses, updates position prices |
| 03:55 PM | Market close | Saves daily report, logs performance summary |

Non-trading days are skipped automatically via `market_calendar.py`.

**Alpaca paper trading setup:**

1. Create a free account at [alpaca.markets](https://alpaca.markets)
2. Generate paper trading API keys from the dashboard
3. Add to `.env` with `ALPACA_BASE_URL=https://paper-api.alpaca.markets`
4. Run `python main.py --live`

---

## Data Layer

Cache-first architecture — strategies always get clean data instantly.

```
Strategy requests data
        ↓
Check SQLite cache (< 1 day old?)
   YES → return cached data
   NO  → fetch from yfinance
             ↓
         Clean & validate (DataCleaner)
             ↓
         Save to SQLite cache
             ↓
         Return clean DataFrame
```

**Available methods:**

```python
from data.data_engineer import data_access

df    = data_access.get_price_history('AAPL', days=90)   # OHLCV DataFrame
price = data_access.get_latest_price('AAPL')              # float
data  = data_access.get_multiple_stocks(['AAPL', 'MSFT']) # dict of DataFrames
fund  = data_access.get_fundamentals('AAPL')              # requires Alpha Vantage
news  = data_access.get_news('AAPL', days=7)              # requires Alpha Vantage
```

**Cleaning pipeline** (`data/pipelines/data_cleaning.py`):
- Removes duplicate rows and NaN OHLCV values
- Validates price consistency (Open/High/Low/Close ranges)
- Detects and removes outliers
- Enforces minimum data requirements before strategies receive data

---

## Docker Deployment

```bash
# Build all services
docker compose build --no-cache

# Start everything
docker compose up -d

# Individual services
docker compose up stratex      # Trading engine (--live)
docker compose up dashboard    # Streamlit on :8501
docker compose up api          # REST API on :8000
```

**Services:**

| Service | Port | Description |
|---|---|---|
| `stratex` | — | Live trading engine |
| `dashboard` | 8501 | Streamlit dashboard |
| `api` | 8000 | FastAPI REST API |

**Volume mounts (data persists across container restarts):**

```yaml
./data                → /app/data
./logs                → /app/logs
./risk/reports        → /app/risk/reports
./optimization_results → /app/optimization_results
```

---

## Logging

Six separate log files under `logs/`:

| File | Contents |
|---|---|
| `logs/system.log` | General application activity |
| `logs/trades.log` | Trade execution events only |
| `logs/errors.log` | Errors and exceptions |
| `logs/data_fetch.log` | Data pipeline operations |
| `logs/strategies.log` | Strategy signal generation |
| `logs/risk.log` | Risk check results per trade |

Rotation: 10MB per file, 5 backup files kept.

---

## Testing

```bash
# Run full test suite
pytest test/ -v

# With coverage report
pytest test/ --cov=. --cov-report=term-missing

# Single file
pytest test/test_risk_manger.py -v
```

**Test coverage (10 test files):**

| File | Coverage area |
|---|---|
| `test_data_cleaning.py` | DataCleaner edge cases |
| `test_database.py` | SQLite CRUD and cache logic |
| `test_momentum_strategy.py` | Signal generation across market conditions |
| `test_portfolio_calculator.py` | Sharpe, beta, correlation, VaR |
| `test_portfolio_tracker.py` | Position management and P&L |
| `test_position_sizer.py` | Fixed fractional and Kelly math |
| `test_risk_manger.py` | All 6 checks including circuit breakers |
| `test_rsi_strategy.py` | RSI calculation and signal generation |
| `test_mean_reversion_strategy.py` | Bollinger Bands + Z-Score signals |
| `test_pairs_strategy.py` | Cointegration and pairs signal logic |
| `test_trade_audit.py` | JSONL write/read and audit trail integrity |

CI runs on every push to `main` and `dev` via GitHub Actions with a 45% coverage threshold.

---

## Team

| Name | Role | Branch |
|---|---|---|
| **Mehdi Bounouif** | System Architect | `system` |
| **Kawtar Bouarfa** | Risk Manager | `risk` |
| **Abdilah Afahmi** | Data Engineer | `data` |

---

*Stratex — Built by Mehdi Bounouif, Kawtar Bouarfa, Abdilah Afahmi*