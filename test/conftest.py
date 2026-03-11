"""
conftest.py — shared pytest fixtures for the Quant_firm test suite.

Available to all test files without importing.

ISOLATION RULES
---------------
- Never use production portfolio files (current_positions.csv, cash_balance.json, etc.)
- Always redirect file paths to tmp_path for any test touching PositionTracker
- Use make_price_df() or the price data fixtures for strategy tests — no yfinance calls
"""

import pytest
import pandas as pd
import numpy as np
import os
import sys

# Ensure project root is always on sys.path when running tests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────
# PRICE DATA HELPERS
# ─────────────────────────────────────────────────────────────

def make_price_df(n: int = 80, trend: str = 'flat',
                  start: float = 200.0, seed: int = 42) -> pd.DataFrame:
    """
    Generate synthetic OHLCV DataFrame for strategy tests.

    Parameters
    ----------
    n     : number of trading days
    trend : 'flat' | 'up' | 'down' | 'noisy'
    start : starting close price
    seed  : random seed (only used for 'noisy')
    """
    dates = pd.date_range('2024-01-01', periods=n, freq='B')

    if trend == 'up':
        closes = np.array([start * (1.005 ** i) for i in range(n)])
    elif trend == 'down':
        closes = np.array([start * (0.995 ** i) for i in range(n)])
    elif trend == 'flat':
        closes = np.full(n, start)
    else:  # noisy
        np.random.seed(seed)
        closes = start + np.cumsum(np.random.randn(n))
        closes = np.maximum(closes, 1.0)  # prevent negatives

    return pd.DataFrame({
        'Close':  closes,
        'High':   closes * 1.005,
        'Low':    closes * 0.995,
        'Open':   closes,
        'Volume': np.full(n, 1_000_000, dtype=int),
    }, index=dates)


# ─────────────────────────────────────────────────────────────
# SHARED PRICE FIXTURES
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def price_data_80_flat():
    """80 days of flat prices — suitable for all strategy tests."""
    return make_price_df(80, 'flat')


@pytest.fixture
def price_data_80_up():
    """80 days of strong uptrend."""
    return make_price_df(80, 'up')


@pytest.fixture
def price_data_80_down():
    """80 days of strong downtrend."""
    return make_price_df(80, 'down')


@pytest.fixture
def price_data_100_up():
    """100 days of uptrend — enough for unanimous 3/3 momentum votes."""
    return make_price_df(100, 'up')


# ─────────────────────────────────────────────────────────────
# ISOLATED PORTFOLIO TRACKER FIXTURE
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_tracker(tmp_path):
    """
    PositionTracker wired to a fresh temp directory.
    Safe to use in any test — never touches production CSV files.
    """
    from risk.portfolio.portfolio_tracker import PositionTracker

    tracker = PositionTracker(initial_capital=20_000)
    tracker.positions_file = str(tmp_path / 'positions.csv')
    tracker.history_file   = str(tmp_path / 'history.csv')
    tracker.cash_file      = str(tmp_path / 'cash.json')
    tracker.trades_file    = str(tmp_path / 'trades.csv')
    tracker.lock_dir       = str(tmp_path / '.locks')
    os.makedirs(tracker.lock_dir, exist_ok=True)
    return tracker


# ─────────────────────────────────────────────────────────────
# STANDARD SIGNAL DICT
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def sample_buy_signal():
    """A well-formed BUY signal dict that satisfies the BaseStrategy contract."""
    from datetime import datetime
    return {
        'ticker':        'AAPL',
        'action':        'BUY',
        'confidence':    0.78,
        'current_price': 200.0,
        'reasoning':     'RSI oversold at 28',
        'signal_type':   'RSI_OVERSOLD',
        'strategy':      'RSI Mean Reversion',
        'timestamp':     datetime.now().isoformat(),
        'source':        'rsi_mean_reversion',
    }


@pytest.fixture
def sample_sell_signal():
    """A well-formed SELL signal dict."""
    from datetime import datetime
    return {
        'ticker':        'MSFT',
        'action':        'SELL',
        'confidence':    0.72,
        'current_price': 390.0,
        'reasoning':     'RSI overbought at 74',
        'signal_type':   'RSI_OVERBOUGHT',
        'strategy':      'RSI Mean Reversion',
        'timestamp':     datetime.now().isoformat(),
        'source':        'rsi_mean_reversion',
    }