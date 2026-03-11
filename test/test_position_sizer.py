"""
Tests for PositionSizer
=======================
Run from project root: pytest test/test_position_sizer.py -v

Covers:
- Fixed fractional sizing at low / mid / high confidence
- Kelly criterion sizing with and without signal prices
- Hard clamp to [MIN_POSITION_SIZE, MAX_POSITION_SIZE]
- Zero-result path when trade is not feasible
- Invalid input guard (zero portfolio value, zero price)
- Method switch via constructor argument
- Return dict structure and field types
"""

import pytest
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk.position_sizer import PositionSizer


# ─────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def ff_sizer():
    """Fixed fractional sizer — default method."""
    return PositionSizer(method='fixed_fractional')


@pytest.fixture
def kelly_sizer():
    """Kelly criterion sizer."""
    return PositionSizer(method='kelly')


@pytest.fixture
def base_signal():
    """Minimal signal dict (no target/stop prices)."""
    return {
        'ticker': 'AAPL',
        'action': 'BUY',
        'confidence': 0.75,
        'current_price': 200.0,
        'reasoning': 'Test signal',
        'strategy': 'Test',
        'signal_type': 'TEST',
    }


@pytest.fixture
def signal_with_prices():
    """Signal dict with explicit target and stop prices for Kelly."""
    return {
        'ticker': 'NVDA',
        'action': 'BUY',
        'confidence': 0.80,
        'current_price': 500.0,
        'target_price': 550.0,   # +10%
        'stop_loss': 475.0,      # -5%
        'reasoning': 'Test signal with prices',
        'strategy': 'Test',
        'signal_type': 'TEST',
    }


# ─────────────────────────────────────────────────────────────
# RETURN STRUCTURE
# ─────────────────────────────────────────────────────────────

class TestReturnStructure:

    def test_required_keys_present(self, ff_sizer):
        result = ff_sizer.calculate(20_000, 200.0, 0.75)
        for key in ('quantity', 'trade_value', 'size_pct', 'method', 'reasoning'):
            assert key in result, f"Missing key: {key}"

    def test_quantity_is_int(self, ff_sizer):
        result = ff_sizer.calculate(20_000, 200.0, 0.75)
        assert isinstance(result['quantity'], int)

    def test_trade_value_is_float(self, ff_sizer):
        result = ff_sizer.calculate(20_000, 200.0, 0.75)
        assert isinstance(result['trade_value'], float)

    def test_size_pct_is_float(self, ff_sizer):
        result = ff_sizer.calculate(20_000, 200.0, 0.75)
        assert isinstance(result['size_pct'], float)

    def test_method_label_matches(self, ff_sizer, kelly_sizer):
        assert ff_sizer.calculate(20_000, 200.0, 0.75)['method'] == 'fixed_fractional'
        assert kelly_sizer.calculate(20_000, 200.0, 0.75)['method'] == 'kelly'


# ─────────────────────────────────────────────────────────────
# FIXED FRACTIONAL
# ─────────────────────────────────────────────────────────────

class TestFixedFractional:

    def test_normal_buy_returns_positive_quantity(self, ff_sizer):
        result = ff_sizer.calculate(20_000, 200.0, 0.75)
        assert result['quantity'] >= 1

    def test_trade_value_approximately_5_pct_at_mid_confidence(self, ff_sizer):
        """At confidence=0.75 (middle range), size should be close to base 5%."""
        result = ff_sizer.calculate(20_000, 200.0, 0.75)
        # Allow ±3% around $1000 (5% of $20k)
        assert 700 <= result['trade_value'] <= 1400

    def test_high_confidence_gives_larger_size(self, ff_sizer):
        low  = ff_sizer.calculate(20_000, 100.0, 0.56)
        high = ff_sizer.calculate(20_000, 100.0, 0.95)
        assert high['size_pct'] >= low['size_pct']

    def test_size_never_exceeds_max_position(self, ff_sizer):
        """Even at 100% confidence, size is capped at MAX_POSITION_SIZE (15%)."""
        result = ff_sizer.calculate(20_000, 10.0, 1.0)  # cheap stock → lots of shares
        assert result['size_pct'] <= ff_sizer.max_pct + 0.001  # small float tolerance

    def test_size_never_below_min_position(self, ff_sizer):
        """Even at minimum confidence, size is floored at MIN_POSITION_SIZE (2%)."""
        result = ff_sizer.calculate(20_000, 50.0, 0.55)
        assert result['size_pct'] >= ff_sizer.min_pct - 0.001

    def test_trade_value_equals_quantity_times_price(self, ff_sizer):
        result = ff_sizer.calculate(20_000, 150.0, 0.75)
        expected = result['quantity'] * 150.0
        assert abs(result['trade_value'] - expected) < 0.01


# ─────────────────────────────────────────────────────────────
# KELLY CRITERION
# ─────────────────────────────────────────────────────────────

class TestKellyCriterion:

    def test_kelly_returns_positive_quantity(self, kelly_sizer, signal_with_prices):
        result = kelly_sizer.calculate(20_000, 500.0, 0.80, signal=signal_with_prices)
        assert result['quantity'] >= 1

    def test_kelly_uses_signal_prices_when_available(self, kelly_sizer, signal_with_prices):
        """With target +10% and stop -5%, win/loss ratio = 2.0 → moderate Kelly."""
        result = kelly_sizer.calculate(20_000, 500.0, 0.80, signal=signal_with_prices)
        assert result['size_pct'] > 0

    def test_kelly_falls_back_to_defaults_without_signal_prices(self, kelly_sizer):
        """Without target/stop in signal, Kelly uses RiskConfig defaults."""
        result = kelly_sizer.calculate(20_000, 200.0, 0.75, signal={'confidence': 0.75})
        assert result['quantity'] >= 1

    def test_kelly_clamped_to_max(self, kelly_sizer):
        """High confidence + favorable odds should not exceed MAX_POSITION_SIZE."""
        result = kelly_sizer.calculate(20_000, 50.0, 0.99,
                                        signal={'target_price': 100.0, 'stop_loss': 45.0})
        assert result['size_pct'] <= kelly_sizer.max_pct + 0.001

    def test_kelly_negative_fraction_floors_to_min(self, kelly_sizer):
        """Very low confidence can produce negative Kelly → should floor to min."""
        result = kelly_sizer.calculate(20_000, 200.0, 0.56,
                                        signal={'target_price': 202.0, 'stop_loss': 195.0})
        # Quantity may be 0 if even min_pct can't afford 1 share — that's acceptable.
        # But if it returns shares, size_pct must be >= min_pct.
        if result['quantity'] > 0:
            assert result['size_pct'] >= kelly_sizer.min_pct - 0.001


# ─────────────────────────────────────────────────────────────
# EDGE CASES & GUARDS
# ─────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_zero_portfolio_value_returns_zero_result(self, ff_sizer):
        result = ff_sizer.calculate(0, 200.0, 0.75)
        assert result['quantity'] == 0

    def test_zero_price_returns_zero_result(self, ff_sizer):
        result = ff_sizer.calculate(20_000, 0.0, 0.75)
        assert result['quantity'] == 0

    def test_very_expensive_stock_may_return_zero(self, ff_sizer):
        """
        5% of $1000 portfolio = $50. Can't buy 1 share of $10,000 stock.
        Should return zero result gracefully, not crash.
        """
        result = ff_sizer.calculate(1_000, 10_000.0, 0.75)
        assert result['quantity'] == 0
        assert 'reasoning' in result

    def test_quantity_times_price_le_portfolio(self, ff_sizer):
        """Trade value must never exceed portfolio value."""
        result = ff_sizer.calculate(20_000, 200.0, 0.90)
        assert result['trade_value'] <= 20_000

    def test_reasoning_is_non_empty_string(self, ff_sizer):
        result = ff_sizer.calculate(20_000, 200.0, 0.75)
        assert isinstance(result['reasoning'], str)
        assert len(result['reasoning']) > 0

    def test_zero_result_has_correct_structure(self, ff_sizer):
        """Even a zero/infeasible result must have all required keys."""
        result = ff_sizer.calculate(0, 200.0, 0.75)
        for key in ('quantity', 'trade_value', 'size_pct', 'method', 'reasoning'):
            assert key in result


if __name__ == '__main__':
    pytest.main([__file__, '-v'])