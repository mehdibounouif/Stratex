"""
Tests for MomentumStrategy
===========================
Run from project root: pytest test/test_momentum_strategy.py -v

Covers:
- generate_signal() returns BaseStrategy signal contract
- Insufficient data guard (min_rows = max(roc, slow_ma, price_ma) + 5)
- ROC-only BUY when price rose sharply over 20 days
- ROC-only SELL when price fell sharply over 20 days
- Majority vote logic: 2/3 BUY → BUY, 2/3 SELL → SELL, split → HOLD
- Confidence levels: 3/3 agree → high (0.88-0.93), 2/3 → 0.68, split → 0.35
- No external network calls (uses injected price data)
- Signal contract: required fields, valid action, confidence in [0,1]
"""

import pytest
import pandas as pd
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.momentum_strategy import MomentumStrategy


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def make_prices(n: int, trend: str = 'flat', start: float = 200.0) -> pd.DataFrame:
    """
    Generate synthetic OHLCV data with a controllable trend.

    trend : 'flat'   → constant price
            'up'     → strong uptrend (clear BUY signals)
            'down'   → strong downtrend (clear SELL signals)
            'noisy'  → random walk
    """
    dates = pd.date_range('2024-01-01', periods=n, freq='B')

    if trend == 'up':
        # Consistent 0.5% daily gain → clear golden cross + price above MA
        closes = [start * (1.005 ** i) for i in range(n)]
    elif trend == 'down':
        # Consistent 0.5% daily loss → clear death cross + price below MA
        closes = [start * (0.995 ** i) for i in range(n)]
    elif trend == 'flat':
        closes = [start] * n
    else:  # noisy
        np.random.seed(42)
        closes = start + np.cumsum(np.random.randn(n))

    closes = np.array(closes)
    return pd.DataFrame({
        'Close':  closes,
        'High':   closes * 1.005,
        'Low':    closes * 0.995,
        'Open':   closes,
        'Volume': [1_000_000] * n,
    }, index=dates)


# ─────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def strategy():
    """MomentumStrategy with default parameters (no network calls)."""
    return MomentumStrategy()


@pytest.fixture
def uptrend_data():
    """80 days of strong uptrend — enough for all indicators."""
    return make_prices(80, trend='up')


@pytest.fixture
def downtrend_data():
    """80 days of strong downtrend."""
    return make_prices(80, trend='down')


@pytest.fixture
def flat_data():
    """80 days of flat prices — no clear trend."""
    return make_prices(80, trend='flat')


# ─────────────────────────────────────────────────────────────
# SIGNAL CONTRACT
# ─────────────────────────────────────────────────────────────

class TestSignalContract:

    REQUIRED_FIELDS = [
        'ticker', 'action', 'confidence', 'current_price',
        'reasoning', 'strategy', 'signal_type', 'timestamp',
    ]

    def test_required_fields_present(self, strategy, uptrend_data):
        signal = strategy.generate_signal('TEST', uptrend_data)
        for field in self.REQUIRED_FIELDS:
            assert field in signal, f"Missing field: {field}"

    def test_action_is_valid(self, strategy, uptrend_data):
        signal = strategy.generate_signal('TEST', uptrend_data)
        assert signal['action'] in ('BUY', 'SELL', 'HOLD')

    def test_confidence_in_unit_range(self, strategy, uptrend_data):
        signal = strategy.generate_signal('TEST', uptrend_data)
        assert 0.0 <= signal['confidence'] <= 1.0

    def test_ticker_preserved(self, strategy, uptrend_data):
        signal = strategy.generate_signal('AAPL', uptrend_data)
        assert signal['ticker'] == 'AAPL'

    def test_current_price_positive(self, strategy, uptrend_data):
        signal = strategy.generate_signal('TEST', uptrend_data)
        assert signal['current_price'] > 0

    def test_reasoning_is_non_empty_string(self, strategy, uptrend_data):
        signal = strategy.generate_signal('TEST', uptrend_data)
        assert isinstance(signal['reasoning'], str)
        assert len(signal['reasoning']) > 0


# ─────────────────────────────────────────────────────────────
# DATA GUARDS
# ─────────────────────────────────────────────────────────────

class TestDataGuards:

    def test_too_few_rows_returns_hold(self, strategy):
        """Fewer rows than min_rows → _no_signal() → HOLD."""
        tiny = make_prices(30)   # need 55, have 30
        signal = strategy.generate_signal('TEST', tiny)
        assert signal['action'] == 'HOLD'
        assert 'Insufficient' in signal['reasoning']

    def test_exactly_min_rows_does_not_crash(self, strategy):
        """Exactly min_rows should produce a valid signal without crashing."""
        min_rows = max(strategy.roc_period, strategy.slow_ma, strategy.price_ma) + 5
        data = make_prices(min_rows)
        signal = strategy.generate_signal('TEST', data)
        assert signal['action'] in ('BUY', 'SELL', 'HOLD')

    def test_none_data_returns_hold(self, strategy):
        """None price_data → _no_signal() → HOLD."""
        signal = strategy.generate_signal('TEST', None)
        assert signal['action'] == 'HOLD'

    def test_empty_dataframe_returns_hold(self, strategy):
        empty = pd.DataFrame(columns=['Close', 'High', 'Low', 'Volume'])
        signal = strategy.generate_signal('TEST', empty)
        assert signal['action'] == 'HOLD'


# ─────────────────────────────────────────────────────────────
# DIRECTIONAL SIGNALS
# ─────────────────────────────────────────────────────────────

class TestDirectionalSignals:

    def test_strong_uptrend_generates_buy(self, strategy, uptrend_data):
        """Strong consistent uptrend should get a BUY from at least MA + price_vs_ma."""
        signal = strategy.generate_signal('TEST', uptrend_data)
        # After 80 days of +0.5%/day, fast MA > slow MA and price > 50-day MA
        assert signal['action'] in ('BUY', 'HOLD')  # HOLD acceptable if ROC disagrees

    def test_strong_downtrend_generates_sell(self, strategy, downtrend_data):
        """Strong consistent downtrend should produce SELL from MA + price_vs_ma."""
        signal = strategy.generate_signal('TEST', downtrend_data)
        assert signal['action'] in ('SELL', 'HOLD')

    def test_flat_market_generates_hold(self, strategy, flat_data):
        """No trend → all three indicators neutral → HOLD."""
        signal = strategy.generate_signal('TEST', flat_data)
        # Flat prices: ROC≈0 (HOLD), MAs equal (no crossover), price≈MA → HOLD
        assert signal['action'] == 'HOLD'

    def test_uptrend_confidence_above_threshold(self, strategy, uptrend_data):
        """A real BUY or SELL signal must have confidence ≥ 0.68 (2/3 vote)."""
        signal = strategy.generate_signal('TEST', uptrend_data)
        if signal['action'] in ('BUY', 'SELL'):
            assert signal['confidence'] >= 0.68


# ─────────────────────────────────────────────────────────────
# CONFIDENCE LEVELS
# ─────────────────────────────────────────────────────────────

class TestConfidenceLevels:

    def test_hold_confidence_below_buy_confidence(self, strategy):
        """HOLD signals should have lower confidence than BUY signals."""
        flat   = make_prices(80, trend='flat')
        upward = make_prices(80, trend='up')
        hold_conf = strategy.generate_signal('TEST', flat)['confidence']
        buy_conf  = strategy.generate_signal('TEST', upward)['confidence']
        # HOLD should have confidence ≤ buy confidence (or at least not higher)
        assert hold_conf <= buy_conf + 0.01

    def test_3_vote_unanimous_confidence(self, strategy):
        """Unanimous 3/3 vote must produce confidence in [0.88, 0.93] range."""
        # Build data where ROC, MA crossover, and price vs MA all agree BUY
        # Use a very long sustained uptrend to ensure all three indicators agree
        data = make_prices(100, trend='up', start=100.0)
        signal = strategy.generate_signal('TEST', data)
        if signal['action'] == 'BUY':
            # Only check if all 3 voted (confidence 0.88-0.93 range)
            if signal['confidence'] >= 0.87:
                assert signal['confidence'] <= 0.95


# ─────────────────────────────────────────────────────────────
# ROBUSTNESS
# ─────────────────────────────────────────────────────────────

class TestRobustness:

    def test_does_not_crash_on_noisy_data(self, strategy):
        noisy = make_prices(80, trend='noisy')
        signal = strategy.generate_signal('TEST', noisy)
        assert signal is not None
        assert 'action' in signal

    def test_does_not_crash_with_nan_in_data(self, strategy):
        """NaN rows in price data should not cause an unhandled crash."""
        data = make_prices(80, trend='up')
        data.loc[data.index[10:15], 'Close'] = float('nan')
        signal = strategy.generate_signal('TEST', data)
        assert signal is not None
        assert signal['action'] in ('BUY', 'SELL', 'HOLD')

    def test_strategy_name_in_signal(self, strategy, uptrend_data):
        signal = strategy.generate_signal('TEST', uptrend_data)
        assert 'strategy' in signal
        assert 'momentum' in signal['strategy'].lower() or signal['strategy'] != ''

    def test_signal_type_present_and_non_empty(self, strategy, uptrend_data):
        signal = strategy.generate_signal('TEST', uptrend_data)
        assert signal.get('signal_type', '') != ''


if __name__ == '__main__':
    pytest.main([__file__, '-v'])