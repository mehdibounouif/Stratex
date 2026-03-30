from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from system.system_architect import get_trading_system
from system.backtest_engine import BacktestEngine
from strategies.strategy_researcher import strategy_engine
from data.data_engineer import data_access
# BUG FIX 1: singleton is named position_tracker, not portfolio_tracker
# portfolio_tracker alias was added to portfolio_tracker.py line 933
from risk.portfolio.portfolio_tracker import portfolio_tracker

app = FastAPI(title="Stratex API", version="0.1.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Use lazy factory — safe if .env is missing at import time
trading_system = get_trading_system()

# --- Portfolio ---

@app.get("/portfolio")
def get_portfolio():
    # BUG FIX 1: PositionTracker has no get_positions() or total_value property.
    # Use get_portfolio_summary() which is the actual public API.
    summary = portfolio_tracker.get_portfolio_summary()
    return {
        "positions": [
            {
                "ticker":        p.ticker,
                "quantity":      float(p.quantity),
                "entry_price":   float(p.entry_price),
                "current_price": float(p.current_price),
                "unrealized_pnl": float(p.current_price - p.entry_price) * float(p.quantity),
            }
            for p in portfolio_tracker.positions
        ],
        "cash":             float(summary["cash"]),
        "portfolio_value":  float(summary["portfolio_value"]),
        "return_pct":       float(summary["return_pct"]),
        "total_positions":  int(summary["total_positions"]),
        "timestamp":        datetime.utcnow().isoformat()
    }

@app.get("/portfolio/performance")
def get_performance():
    return portfolio_tracker.get_portfolio_summary()

# --- Signals ---

@app.get("/signals/scan")
def scan_watchlist():
    # NOTE: this route must be defined BEFORE /signals/{ticker}
    # otherwise FastAPI matches "scan" as the ticker param
    results = trading_system.scan_watchlist()
    return {"signals": results, "timestamp": datetime.utcnow().isoformat()}

@app.get("/signals/{ticker}")
def get_signal(ticker: str, strategy: str = Query(default="rsi_mean_reversion")):
    try:
        result = trading_system.analyze_single_stock(ticker.upper())
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Backtest ---

class BacktestRequest(BaseModel):
    ticker: str
    start_date: str  # YYYY-MM-DD
    end_date: str
    strategy: str = "rsi_mean_reversion"
    initial_capital: float = 20000

@app.post("/backtest")
def run_backtest(req: BacktestRequest):
    try:
        # BUG FIX 2: BacktestEngine takes a strategy INSTANCE, not a strategy name string.
        # Resolve the name → instance via strategy_engine registry first.
        strategy = strategy_engine.strategies.get(req.strategy)
        if not strategy:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown strategy '{req.strategy}'. "
                       f"Available: {list(strategy_engine.strategies.keys())}"
            )
        engine = BacktestEngine(strategy=strategy, initial_capital=req.initial_capital)
        results = engine.run(req.ticker, req.start_date, req.end_date)
        return results
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- System ---

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.get("/audit")
def get_audit_log(limit: int = Query(default=50)):
    from risk.trade_audit import trade_audit
    return trade_audit.get_recent(limit)
