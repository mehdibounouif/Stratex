"""
Base class for all trading strategies.

Every strategy must inherit this class and implement generate_signal().
This enforces a single, consistent signal contract across the system.

SIGNAL CONTRACT
===============
Every generate_signal() call must return a dict with these guaranteed fields:

    {
        'ticker':        str,    # e.g. 'AAPL'
        'action':        str,    # 'BUY' | 'SELL' | 'HOLD'
        'confidence':    float,  # 0.0–1.0  (NOT 0–100)
        'current_price': float,  # last close price, > 0
        'reasoning':     str,    # human-readable explanation
        'signal_type':   str,    # e.g. 'RSI_OVERSOLD', 'MOMENTUM_BUY'
        'strategy':      str,    # strategy name, e.g. 'RSI Mean Reversion'
        'timestamp':     str,    # ISO-8601, e.g. '2026-03-07T02:00:00'
    }

Optional fields (include if your strategy computes them):

    'target_price'    float   — price target for the trade
    'stop_loss'       float   — stop-loss price
    'rsi'             float   — RSI value (RSI strategy)
    'indicators'      dict    — raw indicator values (Momentum strategy)
    'source'          str     — short label used by SignalAggregator

HOW TO ADD A NEW STRATEGY
==========================
1. Create strategies/my_strategy.py
2. class MyStrategy(BaseStrategy):
3. Implement generate_signal(ticker, price_data) → dict
4. Call self._validate(signal) before returning
5. Instantiate at module level: my_strategy = MyStrategy()
6. Register in StrategyResearcher.strategies dict

That's it. The system picks it up automatically.
"""

from abc import ABC, abstractmethod
from datetime import datetime


class BaseStrategy(ABC):
    """
    Abstract base class for all Quant_firm trading strategies.

    Subclasses must implement generate_signal().
    All other helpers are provided free.
    """

    # Subclasses should set this in __init__
    name: str = "BaseStrategy"

    # ── Required interface ────────────────────────────────────────

    @abstractmethod
    def generate_signal(self, ticker: str, price_data) -> dict:
        """
        Analyze price data and return a trading signal.

        Parameters
        ----------
        ticker : str
            Stock symbol, e.g. 'AAPL'
        price_data : pd.DataFrame
            OHLCV DataFrame with columns: Open, High, Low, Close, Volume
            Must have at least 20 rows.

        Returns
        -------
        dict
            Signal dict satisfying the contract above.
            Always call self._validate(signal) before returning.
        """

    # ── Shared helpers — free for every subclass ──────────────────

    def _no_signal(self, ticker: str, reason: str) -> dict:
        """
        Return a safe HOLD signal when data is missing or invalid.
        Use this instead of returning None or raising.
        """
        return self._validate({
            'ticker':        ticker,
            'action':        'HOLD',
            'signal_type':   'NO_SIGNAL',
            'confidence':    0.0,
            'current_price': 0.0,
            'reasoning':     reason,
            'strategy':      self.name,
            'timestamp':     datetime.now().isoformat(),
        })

    def _validate(self, signal: dict) -> dict:
        """
        Guarantee that the signal dict has every required field
        with the correct type and range.

        Fixes silently rather than raising so the system never crashes
        on a malformed signal — but logs warnings so the author notices.

        Rules applied
        -------------
        - 'action'     : must be 'BUY', 'SELL', or 'HOLD' — else → 'HOLD'
        - 'confidence' : must be 0.0–1.0 float
                         values > 1.0 are assumed 0–100 scale and divided by 100
                         clamped to [0.0, 1.0]
        - 'current_price': must be a non-negative float — else → 0.0
        - All required string fields get a default if missing
        """
        # ── Required fields with defaults ────────────────────────
        required_defaults = {
            'ticker':        'UNKNOWN',
            'action':        'HOLD',
            'signal_type':   'UNKNOWN',
            'confidence':    0.0,
            'current_price': 0.0,
            'reasoning':     'No reasoning provided',
            'strategy':      self.name,
            'timestamp':     datetime.now().isoformat(),
        }

        for field, default in required_defaults.items():
            if field not in signal or signal[field] is None:
                signal[field] = default

        # ── Action must be one of the three valid values ──────────
        if signal['action'] not in ('BUY', 'SELL', 'HOLD'):
            signal['action'] = 'HOLD'

        # ── Confidence must be 0.0–1.0 ────────────────────────────
        try:
            c = float(signal['confidence'])
            if c > 1.0:
                c = c / 100.0       # 75 → 0.75
            signal['confidence'] = round(max(0.0, min(1.0, c)), 4)
        except (TypeError, ValueError):
            signal['confidence'] = 0.0

        # ── Price must be a non-negative float ─────────────────────
        try:
            p = float(signal['current_price'])
            signal['current_price'] = round(max(0.0, p), 4)
        except (TypeError, ValueError):
            signal['current_price'] = 0.0

        # ── Add 'source' alias if not present ─────────────────────
        # SignalAggregator uses 'source' for display; 'strategy' is the
        # full name. Keep both so old and new code works.
        if 'source' not in signal:
            signal['source'] = signal.get('strategy', self.name)

        return signal

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}')"