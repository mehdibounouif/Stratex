# Stratex

> **A production-grade quantitative trading system** — multi-strategy signal generation, institutional-level risk management, walk-forward optimization, backtesting engine, live paper trading via Alpaca, real-time Streamlit dashboard, and full Docker deployment. Built in Python, designed for serious algorithmic trading research and deployment.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Strategies](#strategies)
- [Walk-Forward Optimization](#walk-forward-optimization)
- [Risk Management](#risk-management)
- [Docker Deployment](#docker-deployment)
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

Stratex is a full-stack algorithmic trading platform built for quantitative research and live execution. It combines classical technical strategies (RSI, Momentum, Bollinger Bands, Pairs Trading) with an optional AI signal layer powered by GPT, all routed through a strict risk gate before any trade is executed.

The system is built around three core principles:

- **Signal quality over quantity** — multiple strategies must agree before a trade is taken
- **Risk first** — no trade bypasses the 6-check risk engine; two checks (daily loss, max drawdown) always fail closed
- **Graceful degradation** — the system runs on `yfinance` alone; AI and fundamentals are optional enhancements

**Initial capital:** $100,000 · **Default strategy:** RSI Mean Reversion · **Default watchlist:** AAPL, MSFT, NVDA, GOOGL, META, TSLA, AMZN, AMD, NFLX

---

## Architecture

```
main.py
├── --live          → LiveEngine (APScheduler cron jobs)
├── --backtest      → BacktestEngine (historical simulation)
├── --optimize      → WalkForwardOptimizer (parameter search)
├── --dashboard     → Streamlit dashboard
└── (default)       → Interactive CLI menu

TradingSystem (system_architect.py)
├── DataEngineer            → SQLite cache → yfinance
├── StrategyResearcher      → RSI / Momentum / MeanReversion / Pairs
├── SignalAggregator        → Conflict resolution, confidence scoring
├── RiskManager             → 6-check gate (position, cash, sector, loss, drawdown)
├── PositionSizer           → Fixed Fractional or Kelly Criterion
├── TradeAudit              → JSONL audit trail
├── WalkForwardOptimizer    → Rolling-window parameter optimization
└── AlpacaGateway           → Paper / live order execution
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
| **Walk-forward optimization** | Automatically finds best strategy parameters using rolling time windows |
| **Signal aggregation** | Majority-vote conflict resolution with confidence bonuses |
| **6-check risk gate** | Position size, cash reserve, open positions, sector exposure, daily loss, max drawdown |
| **Position sizing** | Fixed fractional (confidence-scaled) or Kelly Criterion (half-Kelly default) |
| **Backtesting engine** | Realistic simulation with slippage (10bps) and commission ($0.005/share) |
| **Live paper trading** | Alpaca API integration with APScheduler cron jobs |
| **Smart data caching** | SQLite-first, yfinance fallback — strategies never wait for API calls |
| **Full audit trail** | Every trade decision logged to JSONL with full reasoning and risk check results |
| **Streamlit dashboard** | Real-time portfolio KPIs, strategy heatmap, order history, risk metrics |
| **Docker deployment** | Full containerized deployment with docker-compose — runs anywhere |
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

Advanced cointegration-based strategy.

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

## Walk-Forward Optimization

Walk-forward optimization (WFO) automatically finds the best strategy parameters without overfitting to historical data. Instead of testing one parameter set over the full date range, it uses rolling windows:

```
Window 1: Train Jan–Jun 2023 → find best params → Test Jul–Aug 2023
Window 2: Train Mar–Aug 2023 → find best params → Test Sep–Oct 2023
Window 3: Train May–Oct 2023 → find best params → Test Nov–Dec 2023
...
```

Each "train" phase searches all parameter combinations. The "test" phase validates them on unseen data. The final output shows which parameters actually hold up across real market conditions.

### Running the Optimizer

```bash
# Optimize RSI strategy on AAPL over 2 years
python main.py --optimize AAPL 2023-01-01 2024-12-31

# Use with a specific strategy
python main.py --optimize NVDA 2022-01-01 2024-12-31 --strategy rsi_mean_reversion
```

### Output

Results are saved to `optimization_results/wfo_<TICKER>_<timestamp>.json` and printed to the console:

```
============================================================
  WALK-FORWARD OPTIMIZATION RESULTS — AAPL
============================================================
  Metric used for ranking : sharpe_ratio
  Total windows tested    : 6
  Profitable windows      : 4 (66.7%)
  Avg test return         : +2.14%
  Avg test Sharpe ratio   : 0.812
  Avg test max drawdown   : -3.21%
------------------------------------------------------------
  CONSENSUS (most-selected) parameters:
    rsi_buy              = 20
    rsi_sell             = 75
    holding_days         = 5
    stop_loss            = 0.05
  Selected in 50% of windows
============================================================
```

### Applying Results to Your Strategy

Open `strategies/rsi_strategy.py` and update the singleton at the bottom:

```python
# Update with your consensus_params from the optimizer output
rsi_strategy = RSIStrategy(rsi_buy=20, rsi_sell=75, holding_days=5, stop_loss=0.05)
```

### Customizing the Parameter Grid

Edit `DEFAULT_RSI_PARAM_GRID` in `system/walk_forward_optimizer.py`:

```python
DEFAULT_RSI_PARAM_GRID = {
    "rsi_buy":      [20, 25, 30],
    "rsi_sell":     [70, 75, 80],
    "holding_days": [3, 5, 7],
    "stop_loss":    [0.03, 0.05, 0.07],
}
```

> **Note:** 4 parameters × 3 values = 81 combinations per window. With 6 windows, expect 3–7 minutes to complete.

---

## Risk Management

Every trade passes through a **6-check gate** before execution. Two checks always fail closed.

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
- Minimum signal confidence: **55%**
- Min Sharpe ratio threshold: **1.0**
- Max portfolio beta: **1.5**
- Max inter-asset correlation: **0.80**

### Position Sizing

**Fixed Fractional (default):** Allocates a fixed percentage of portfolio per trade, scaled by signal confidence.

**Kelly Criterion:** Mathematically optimal sizing.
```
f* = (p × b - q) / b
```
Default: **half-Kelly** (`KELLY_FRACTION = 0.5`). Capped at `MAX_POSITION_SIZE` (15%).

---

## Docker Deployment

Stratex ships with a full Docker setup. The entire system runs in isolated containers that work identically on any machine or cloud server.

### Services

| Service | Description | Port |
|---|---|---|
| `stratex_engine` | Live trading engine — runs 24/7 | — |
| `stratex_dashboard` | Streamlit dashboard | 8501 |
| `stratex_api` | REST API layer (coming soon) | 8000 |

All three share `./data`, `./logs`, and `./risk/reports` on your real disk via volume mounts.

### Quick Start

```bash
# 1. Copy environment template
cp .env.example .env
# Fill in your API keys in .env

# 2. Create log files (required on first run — Fedora/SELinux note below)
mkdir -p logs data risk/reports
touch logs/system.log logs/trades.log logs/errors.log \
      logs/risk.log logs/strategies.log logs/data_fetch.log

# 3. Build the containers (~5 minutes first time)
docker compose build

# 4. Start all services
docker compose up

# Open your browser → http://localhost:8501
```

> **Fedora / SELinux users:** The volume mounts in `docker-compose.yml` use the `:z` flag (`./logs:/app/logs:z`) which tells SELinux to allow Docker access. This is already configured in the provided `docker-compose.yml`.

### Common Commands

```bash
# Start in background
docker compose up -d

# View live logs
docker compose logs -f

# View one service only
docker compose logs -f stratex_engine

# Stop everything
docker compose down

# Rebuild after code changes
docker compose build --no-cache && docker compose up

# Open a shell inside a container (for debugging)
docker exec -it stratex_engine bash
```

### Deploying to a Cloud Server

```bash
# On your VPS (DigitalOcean, AWS, Hetzner, etc.)
curl -fsSL https://get.docker.com | sh

git clone https://github.com/mehdibounouif/Quant_firm.git
cd Quant_firm

cp .env.example .env && nano .env

mkdir -p logs data risk/reports
touch logs/system.log logs/trades.log logs/errors.log \
      logs/risk.log logs/strategies.log logs/data_fetch.log

docker compose build
docker compose up -d
```

Dashboard accessible at `http://YOUR_SERVER_IP:8501`.

---

## Project Structure

```
Quant_firm/
│
├── main.py                         # Entry point — CLI flags and interactive menu
├── logger.py                       # Centralized logging
├── requirements.txt                # Dependencies
├── Dockerfile                      # Container build instructions
├── docker-compose.yml              # Multi-service orchestration
├── .env.example                    # Environment variable template
├── .dockerignore                   # Files excluded from Docker image
│
├── config/
│   ├── base_config.py              # Environment, API keys, paths
│   ├── trading_config.py           # Capital, watchlist, strategy, sizing
│   └── risk_config.py              # All hard risk limits
│
├── data/
│   ├── data_engineer.py            # Central data facade (cache-first)
│   ├── database.py                 # SQLite — prices, fundamentals, news
│   ├── stock_fetcher.py            # yfinance wrapper with retry
│   ├── fundamental_fetcher.py      # Alpha Vantage fundamentals
│   ├── news_fetcher.py             # Alpha Vantage news
│   ├── retry.py                    # Retry decorator
│   ├── health_check.py             # Data pipeline health monitoring
│   └── pipelines/
│       ├── data_cleaning.py        # OHLCV validation and cleaning
│       ├── daily_update.py         # Daily price update pipeline
│       └── weekly_update_fundamentals.py
│
├── strategies/
│   ├── base_strategy.py            # Abstract base + signal contract
│   ├── strategy_researcher.py      # Strategy registry
│   ├── rsi_strategy.py             # RSI Mean Reversion
│   ├── momentum_strategy.py        # Multi-indicator Momentum
│   ├── mean_reversion_strategy.py  # Bollinger Bands + Z-Score
│   └── pairs_strategy.py           # Statistical Arbitrage
│
├── system/
│   ├── system_architect.py         # TradingSystem — central orchestrator
│   ├── signal_aggregator.py        # Multi-signal conflict resolution
│   ├── backtest_engine.py          # Historical simulation
│   ├── walk_forward_optimizer.py   # Rolling-window parameter optimization ← NEW
│   ├── live_engine.py              # APScheduler cron jobs
│   ├── market_calendar.py          # NYSE trading day checker
│   └── tradingagents_integration.py
│
├── risk/
│   ├── risk_manager.py             # 6-check gate
│   ├── position_sizer.py           # Fixed fractional and Kelly
│   ├── trade_audit.py              # JSONL audit trail
│   └── portfolio/
│       ├── portfolio_tracker.py    # Positions, cash, P&L
│       └── portfolio_calculator.py # Sharpe, beta, correlation, VaR
│
├── execution/
│   ├── alpaca_gateway.py           # Alpaca broker gateway
│   └── fill_models.py              # Slippage and commission simulation
│
├── dashboard/
│   ├── app.py                      # Streamlit dashboard
│   └── components.py               # KPI cards, charts, heatmaps
│
├── scripts/
│   └── start.sh                    # Docker container startup script ← NEW
│
├── optimization_results/           # WFO output JSON files (auto-generated) ← NEW
├── logs/                           # Runtime log files
├── docs/                           # Research notes
├── test/                           # pytest test suite
└── tradingagents/                  # Optional AI subproject
```

---

## Getting Started

### Local (Python)

```bash
git clone https://github.com/mehdibounouif/Quant_firm.git
cd Quant_firm

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env            # fill in your keys
python main.py
```

### Docker

See [Docker Deployment](#docker-deployment) above.

---

## Configuration

### `config/trading_config.py`

```python
INITIAL_CAPITAL        = 100000
DEFAULT_STRATEGY       = 'rsi_mean_reversion'
MIN_SIGNAL_CONFIDENCE  = 0.55
POSITION_SIZE_PCT      = 0.05
POSITION_SIZING_METHOD = 'fixed_fractional'   # or 'kelly'
KELLY_FRACTION         = 0.5
USE_PAPER_TRADING      = True
USE_TRADING_AGENT      = False
```

### `config/risk_config.py`

```python
MAX_POSITION_SIZE         = 0.15
MIN_CASH_RESERVE          = 0.10
MAX_TOTAL_POSITIONS       = 15
MAX_DAILY_LOSS            = 0.03
MAX_DRAWDOWN_BEFORE_HALT  = 0.15
DEFAULT_STOP_LOSS_PCT     = 0.05
DEFAULT_TAKE_PROFIT_PCT   = 0.10
```

---

## Usage

```bash
# Interactive menu
python main.py

# Backtest
python main.py --backtest AAPL 2024-01-01 2024-12-31
python main.py --backtest NVDA 2024-01-01 2024-12-31 --strategy momentum

# Walk-forward optimization
python main.py --optimize AAPL 2023-01-01 2024-12-31

# Dashboard
python main.py --dashboard

# Live trading (paper mode)
python main.py --live
```

---

## Dashboard

```bash
python main.py --dashboard
# or via Docker:
docker compose up dashboard
# → http://localhost:8501
```

- Portfolio KPIs — total value, cash, P&L, return %
- Risk metrics — drawdown, daily loss, beta, Sharpe
- Open positions with entry price, current price, P&L
- Strategy heatmap across all tickers
- Full order history with reasoning
- CSV export for portfolio report and audit log

---

## Backtesting

```python
from system.backtest_engine import BacktestEngine
from strategies.rsi_strategy import rsi_strategy

engine = BacktestEngine(rsi_strategy, initial_capital=100000)
results = engine.run('AAPL', '2024-01-01', '2024-12-31')
```

Includes slippage (10bps), commission ($0.005/share), isolated portfolio, and fill simulation.

---

## Live Trading

> Always start with paper trading. Never use live capital without extensive backtesting and walk-forward validation.

**APScheduler jobs:**

| Time (NY) | Job |
|---|---|
| 09:00 AM | Pre-market cache warm-up |
| 09:35 AM | Full watchlist scan + signal execution |
| 12:30 PM | Stop-loss checks + price updates |
| 03:55 PM | Daily report + performance summary |

**Setup:** Create a free [Alpaca](https://alpaca.markets) account → generate paper trading keys → add to `.env` → `python main.py --live`

---

## Data Layer

Cache-first architecture — strategies always receive clean, validated data with no API latency.

```python
from data.data_engineer import data_access

df    = data_access.get_price_history('AAPL', days=90)
price = data_access.get_latest_price('AAPL')
data  = data_access.get_multiple_stocks(['AAPL', 'MSFT'], days=60)
```

---

## Testing

```bash
pytest
pytest --cov=. --cov-report=term-missing
pytest test/test_risk_manger.py -v
```

---

## Logging

| File | Contents |
|---|---|
| `logs/system.log` | General activity |
| `logs/trades.log` | Trade execution events |
| `logs/errors.log` | Errors and exceptions |
| `logs/data_fetch.log` | Data pipeline operations |
| `logs/strategies.log` | Signal generation |
| `logs/risk.log` | Risk check results |

Log rotation: 10MB per file, 5 backups kept.

---

## Team

| Name | Role | Branch |
|---|---|---|
| **Mehdi Bounouif** | System Architect | `system` |
| **Kawtar Bouarfa** | Risk Manager | `risk` |
| **Abdilah Afahmi** | Data Engineer | `data` |

---

*Stratex — Built by Mehdi Bounouif, Kawtar Bouarfa, Abdilah Afahmi*