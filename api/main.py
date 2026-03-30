from fastapi import FastAPI, HTTPException, Query, Security, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import os

from system.system_architect import get_trading_system
from system.backtest_engine import BacktestEngine
from strategies.strategy_researcher import strategy_engine
from data.data_engineer import data_access
from risk.portfolio.portfolio_tracker import portfolio_tracker

app = FastAPI(title="Stratex API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

trading_system = get_trading_system()

# ══════════════════════════════════════════════════════════════
# AUTHENTICATION
# ══════════════════════════════════════════════════════════════
#
# Every protected endpoint requires this header:
#     X-API-Key: your-secret-key
#
# Set the key in your .env:
#     API_SECRET_KEY=some-long-random-string
#
# If API_SECRET_KEY is not set or is still the placeholder,
# auth is DISABLED — fine for local dev, never do this in prod.
#
# Generate a strong key:
#     python3 -c "import secrets; print(secrets.token_hex(32))"

_API_KEY = os.getenv("API_SECRET_KEY", "")
_AUTH_ENABLED = bool(_API_KEY and _API_KEY != "change-me-in-production")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(key: str = Security(api_key_header)):
    if not _AUTH_ENABLED:
        return  # auth disabled — local dev mode
    if not key or key != _API_KEY:
        raise HTTPException(
            status_code=403,
            detail="Invalid or missing API key. "
                   "Set X-API-Key header with your API_SECRET_KEY value."
        )


@app.on_event("startup")
async def startup_warning():
    if not _AUTH_ENABLED:
        print(
            "\n⚠️  WARNING: API_SECRET_KEY not set or still placeholder.\n"
            "   API running WITHOUT authentication — anyone can access it.\n"
            "   Set in .env: API_SECRET_KEY=your-secret\n"
            "   Generate:    python3 -c \"import secrets; print(secrets.token_hex(32))\"\n"
        )
    else:
        print("✅ API authentication enabled (X-API-Key header required)")


# ══════════════════════════════════════════════════════════════
# PUBLIC  (no auth)
# ══════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ══════════════════════════════════════════════════════════════
# PROTECTED  (X-API-Key required)
# ══════════════════════════════════════════════════════════════

@app.get("/portfolio", dependencies=[Depends(require_api_key)])
def get_portfolio():
    summary = portfolio_tracker.get_portfolio_summary()
    return {
        "positions": [
            {
                "ticker":         p.ticker,
                "quantity":       float(p.quantity),
                "entry_price":    float(p.entry_price),
                "current_price":  float(p.current_price),
                "unrealized_pnl": float(p.current_price - p.entry_price) * float(p.quantity),
            }
            for p in portfolio_tracker.positions
        ],
        "cash":            float(summary["cash"]),
        "portfolio_value": float(summary["portfolio_value"]),
        "return_pct":      float(summary["return_pct"]),
        "total_positions": int(summary["total_positions"]),
        "timestamp":       datetime.utcnow().isoformat()
    }


@app.get("/portfolio/performance", dependencies=[Depends(require_api_key)])
def get_performance():
    return portfolio_tracker.get_portfolio_summary()


@app.get("/signals/scan", dependencies=[Depends(require_api_key)])
def scan_watchlist():
    results = trading_system.scan_watchlist()
    return {"signals": results, "timestamp": datetime.utcnow().isoformat()}


@app.get("/signals/{ticker}", dependencies=[Depends(require_api_key)])
def get_signal(ticker: str, strategy: str = Query(default="rsi_mean_reversion")):
    try:
        result = trading_system.analyze_single_stock(ticker.upper())
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class BacktestRequest(BaseModel):
    ticker: str
    start_date: str
    end_date: str
    strategy: str = "rsi_mean_reversion"
    initial_capital: float = 20000


@app.post("/backtest", dependencies=[Depends(require_api_key)])
def run_backtest(req: BacktestRequest):
    try:
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


@app.get("/audit", dependencies=[Depends(require_api_key)])
def get_audit_log(limit: int = Query(default=50)):
    from risk.trade_audit import trade_audit
    return trade_audit.get_recent(limit)