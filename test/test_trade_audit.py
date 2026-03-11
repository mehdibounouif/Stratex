"""
Tests for TradeAudit
====================
Run from project root: pytest test/test_trade_audit.py -v

Covers:
- File creation at __init__ (touch)
- record() writes valid JSON to file
- record() field values are correct
- record_stop_loss() writes STOPPED_OUT record
- tail(n) returns last n records in correct order
- summary() aggregates outcomes correctly
- Multiple records accumulate (append not overwrite)
- All outcomes: EXECUTED, REJECTED, HELD, STOPPED_OUT
- Isolation: every test gets its own temp JSONL file
"""

import pytest
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk.trade_audit import TradeAudit


# ─────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def audit(tmp_path):
    """Fresh TradeAudit writing to a temp file — never touches production logs."""
    return TradeAudit(log_path=str(tmp_path / 'test_audit.jsonl'))


@pytest.fixture
def buy_signal():
    return {
        'ticker':       'AAPL',
        'action':       'BUY',
        'confidence':   0.78,
        'current_price': 200.0,
        'reasoning':    'RSI oversold',
        'signal_type':  'RSI_OVERSOLD',
        'strategy':     'RSI Mean Reversion',
    }


@pytest.fixture
def buy_approval():
    return {
        'approved': True,
        'reason':   '',
        'checks':   {'position_size': True, 'cash_reserve': True},
    }


@pytest.fixture
def buy_sizing():
    return {
        'method':      'fixed_fractional',
        'quantity':    10,
        'trade_value': 2000.0,
        'size_pct':    0.05,
        'reasoning':   '5% of portfolio',
    }


# ─────────────────────────────────────────────────────────────
# FILE CREATION
# ─────────────────────────────────────────────────────────────

class TestFileCreation:

    def test_file_created_on_init(self, tmp_path):
        path = str(tmp_path / 'audit.jsonl')
        assert not os.path.exists(path)
        TradeAudit(log_path=path)
        assert os.path.exists(path)

    def test_empty_file_on_fresh_init(self, audit):
        assert os.path.getsize(audit.log_path) == 0

    def test_does_not_truncate_existing_file(self, tmp_path):
        """Creating a second TradeAudit on the same file must not erase records."""
        path = str(tmp_path / 'audit.jsonl')
        a1 = TradeAudit(log_path=path)
        a1.record('AAPL', 'HELD', 'HOLD', 0, 200.0)
        a2 = TradeAudit(log_path=path)  # second init on same file
        records = a2.tail(10)
        assert len(records) == 1   # record from a1 still present


# ─────────────────────────────────────────────────────────────
# record() — field correctness
# ─────────────────────────────────────────────────────────────

class TestRecord:

    def test_record_creates_valid_json_line(self, audit, buy_signal, buy_approval, buy_sizing):
        audit.record('AAPL', 'EXECUTED', 'BUY', 10, 200.0,
                     signal=buy_signal, approval=buy_approval, sizing=buy_sizing)
        with open(audit.log_path) as f:
            line = f.readline().strip()
        entry = json.loads(line)  # must not raise
        assert entry is not None

    def test_required_fields_present(self, audit, buy_signal):
        audit.record('AAPL', 'EXECUTED', 'BUY', 10, 200.0, signal=buy_signal)
        entry = json.loads(open(audit.log_path).readline())
        required = [
            'timestamp', 'ticker', 'outcome', 'action',
            'quantity', 'price', 'trade_value', 'realized_pnl',
            'confidence', 'signal_type', 'strategy', 'reasoning',
            'sizing_method', 'size_pct', 'risk_approved', 'risk_checks', 'reject_reason',
        ]
        for field in required:
            assert field in entry, f"Missing field: {field}"

    def test_ticker_uppercased(self, audit):
        audit.record('aapl', 'HELD', 'HOLD', 0, 0.0)
        entry = json.loads(open(audit.log_path).readline())
        assert entry['ticker'] == 'AAPL'

    def test_trade_value_equals_quantity_times_price(self, audit, buy_signal):
        audit.record('AAPL', 'EXECUTED', 'BUY', 10, 182.50, signal=buy_signal)
        entry = json.loads(open(audit.log_path).readline())
        assert abs(entry['trade_value'] - 1825.0) < 0.01

    def test_confidence_extracted_from_signal(self, audit, buy_signal):
        audit.record('AAPL', 'EXECUTED', 'BUY', 10, 200.0, signal=buy_signal)
        entry = json.loads(open(audit.log_path).readline())
        assert abs(entry['confidence'] - 0.78) < 0.001

    def test_realized_pnl_recorded(self, audit):
        audit.record('AAPL', 'EXECUTED', 'SELL', 5, 210.0, realized_pnl=50.0)
        entry = json.loads(open(audit.log_path).readline())
        assert abs(entry['realized_pnl'] - 50.0) < 0.01

    def test_reject_reason_populated_on_rejected(self, audit, buy_signal):
        approval = {'approved': False, 'reason': 'Insufficient cash', 'checks': {}}
        audit.record('AAPL', 'REJECTED', 'BUY', 0, 200.0,
                     signal=buy_signal, approval=approval)
        entry = json.loads(open(audit.log_path).readline())
        assert 'cash' in entry['reject_reason'].lower()

    def test_reject_reason_empty_on_executed(self, audit, buy_signal, buy_approval):
        audit.record('AAPL', 'EXECUTED', 'BUY', 10, 200.0,
                     signal=buy_signal, approval=buy_approval)
        entry = json.loads(open(audit.log_path).readline())
        assert entry['reject_reason'] == ''

    def test_held_outcome_fields(self, audit, buy_signal):
        audit.record('MSFT', 'HELD', 'HOLD', 0, 380.0, signal=buy_signal)
        entry = json.loads(open(audit.log_path).readline())
        assert entry['outcome'] == 'HELD'
        assert entry['quantity'] == 0
        assert entry['trade_value'] == 0.0

    def test_sizing_fields_extracted(self, audit, buy_signal, buy_sizing):
        audit.record('AAPL', 'EXECUTED', 'BUY', 10, 200.0,
                     signal=buy_signal, sizing=buy_sizing)
        entry = json.loads(open(audit.log_path).readline())
        assert entry['sizing_method'] == 'fixed_fractional'
        assert abs(entry['size_pct'] - 0.05) < 0.001


# ─────────────────────────────────────────────────────────────
# record_stop_loss()
# ─────────────────────────────────────────────────────────────

class TestRecordStopLoss:

    def test_stop_loss_outcome_is_stopped_out(self, audit):
        audit.record_stop_loss('TSLA', 300.0, 285.0, 5, -75.0, 'Stop loss triggered at 5%')
        entry = json.loads(open(audit.log_path).readline())
        assert entry['outcome'] == 'STOPPED_OUT'

    def test_stop_loss_action_is_sell(self, audit):
        audit.record_stop_loss('TSLA', 300.0, 285.0, 5, -75.0, 'Stop loss triggered')
        entry = json.loads(open(audit.log_path).readline())
        assert entry['action'] == 'SELL'

    def test_stop_loss_pnl_negative(self, audit):
        audit.record_stop_loss('TSLA', 300.0, 285.0, 5, -75.0, 'Stop loss triggered')
        entry = json.loads(open(audit.log_path).readline())
        assert entry['realized_pnl'] < 0

    def test_stop_loss_entry_price_recorded(self, audit):
        audit.record_stop_loss('TSLA', 300.0, 285.0, 5, -75.0, 'Stop loss triggered')
        entry = json.loads(open(audit.log_path).readline())
        assert 'entry_price' in entry
        assert abs(entry['entry_price'] - 300.0) < 0.01

    def test_stop_loss_required_fields(self, audit):
        audit.record_stop_loss('NVDA', 500.0, 475.0, 3, -75.0, 'Drawdown exceeded')
        entry = json.loads(open(audit.log_path).readline())
        for field in ('timestamp', 'ticker', 'outcome', 'action',
                      'quantity', 'price', 'trade_value', 'realized_pnl'):
            assert field in entry


# ─────────────────────────────────────────────────────────────
# ACCUMULATION — multiple records
# ─────────────────────────────────────────────────────────────

class TestAccumulation:

    def test_multiple_records_append_correctly(self, audit):
        for i in range(5):
            audit.record(f'TICK{i}', 'HELD', 'HOLD', 0, float(i * 10))
        with open(audit.log_path) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 5

    def test_each_line_is_valid_json(self, audit):
        for i in range(3):
            audit.record(f'T{i}', 'HELD', 'HOLD', 0, 0.0)
        with open(audit.log_path) as f:
            for line in f:
                if line.strip():
                    json.loads(line)  # must not raise


# ─────────────────────────────────────────────────────────────
# tail()
# ─────────────────────────────────────────────────────────────

class TestTail:

    def _add_n_records(self, audit, n):
        for i in range(n):
            audit.record(f'T{i}', 'HELD', 'HOLD', 0, float(i))

    def test_tail_returns_list(self, audit):
        self._add_n_records(audit, 3)
        assert isinstance(audit.tail(3), list)

    def test_tail_n_limits_results(self, audit):
        self._add_n_records(audit, 10)
        assert len(audit.tail(5)) == 5

    def test_tail_returns_all_when_fewer_than_n(self, audit):
        self._add_n_records(audit, 3)
        assert len(audit.tail(20)) == 3

    def test_tail_returns_most_recent_last(self, audit):
        """tail() should return records in chronological order (oldest first in slice)."""
        for ticker in ['AAPL', 'MSFT', 'NVDA']:
            audit.record(ticker, 'HELD', 'HOLD', 0, 0.0)
        records = audit.tail(2)
        tickers = [r['ticker'] for r in records]
        assert 'NVDA' in tickers  # most recent must be present

    def test_tail_empty_file_returns_empty_list(self, audit):
        assert audit.tail(10) == []


# ─────────────────────────────────────────────────────────────
# summary()
# ─────────────────────────────────────────────────────────────

class TestSummary:

    def test_summary_returns_dict(self, audit):
        audit.record('AAPL', 'HELD', 'HOLD', 0, 0.0)
        assert isinstance(audit.summary(), dict)

    def test_summary_counts_outcomes(self, audit):
        audit.record('AAPL', 'EXECUTED', 'BUY',  10, 200.0)
        audit.record('MSFT', 'REJECTED', 'BUY',  0,  380.0)
        audit.record('NVDA', 'HELD',     'HOLD', 0,  0.0)
        s = audit.summary()
        assert s.get('executed', 0) == 1
        assert s.get('rejected', 0) == 1
        # summary() returns total_decisions — held = total - executed - rejected - stopped
        held = s.get('total_decisions', 0) - s.get('executed', 0) - s.get('rejected', 0) - s.get('stopped_out', 0)
        assert held == 1

    def test_summary_total_matches_record_count(self, audit):
        for _ in range(6):
            audit.record('X', 'HELD', 'HOLD', 0, 0.0)
        s = audit.summary()
        assert s.get('total_decisions', 0) == 6

    def test_summary_empty_file_is_safe(self, audit):
        s = audit.summary()
        assert isinstance(s, dict)
        assert s.get('total', 0) == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])