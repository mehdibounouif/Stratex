"""
Trade Audit Logger
==================
Writes a structured JSONL record for every trade decision — executed, rejected,
or held — so the full reasoning chain can be reconstructed after the fact.

WHY JSONL (JSON Lines)?
-----------------------
One JSON object per line. Each line is self-contained and independently parseable.
This means:
- grep works on it:        grep '"action": "BUY"' logs/trade_audit.jsonl
- pandas can read it:      pd.read_json('logs/trade_audit.jsonl', lines=True)
- Appending is atomic:     no risk of corrupting existing records on crash
- No size limit:           the file grows indefinitely, one line per decision

WHAT GETS LOGGED
----------------
Every call to record() writes a dict with these fields:

    timestamp       str    ISO-8601 when the decision was made
    ticker          str    e.g. 'AAPL'
    outcome         str    'EXECUTED' | 'REJECTED' | 'HELD' | 'STOPPED_OUT'
    action          str    'BUY' | 'SELL' | 'HOLD'
    quantity        int    shares (0 for HOLD/REJECTED before sizing)
    price           float  execution price
    trade_value     float  quantity × price
    realized_pnl    float  for SELL trades (0.0 for BUY/HOLD)
    confidence      float  signal confidence 0.0–1.0
    signal_type     str    e.g. 'RSI_OVERSOLD', 'MOMENTUM_BUY'
    strategy        str    e.g. 'RSI Mean Reversion'
    sizing_method   str    'fixed_fractional' | 'kelly' | 'none'
    size_pct        float  fraction of portfolio
    risk_checks     dict   {check_name: bool} — which checks passed/failed
    reject_reason   str    why trade was rejected (empty string if executed)
    reasoning       str    strategy reasoning text

Author: Kawtar (Risk Manager)
"""

import json
import os
from datetime import datetime
from logger import get_logger

log = get_logger('risk.trade_audit')


class TradeAudit:
    """
    Interface for the trade auditing system.

    This class is responsible for recording every trading decision
    made by the system.

    Each decision is serialized into a JSON object and appended
    to a persistent log file.

    The audit system allows developers and analysts to inspect
    historical decisions, analyze performance, and debug issues.
    """

    def __init__(self, log_path: str = "logs/trade_audit.jsonl"):
        self.log_path = log_path
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        # Touch the file so it always exists from startup,
        # even before the first trade decision is recorded.
        if not os.path.isfile(log_path):
            open(log_path, 'a').close()
        log.debug(f"TradeAudit initialized: {log_path}")
 
        """
        Initialize the trade auditing system.

        Parameters
        ----------
        log_path : str

            Path to the JSONL file used for storing audit records.

            Default location:

                logs/trade_audit.jsonl
        """

    # ─────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────

    def record(
        self,
        ticker: str,
        outcome: str,
        action: str,
        quantity: int,
        price: float,
        signal: dict = None,
        approval: dict = None,
        sizing: dict = None,
        realized_pnl: float = 0.0
    ) -> None:
        """
        Record a trade decision in the audit log.

        This method writes one structured record describing the
        outcome of a trading decision.

        Parameters
        ----------

        ticker : str
            Asset symbol (example: "AAPL").

        outcome : str
            Final decision result.

            Allowed values include:

                EXECUTED
                REJECTED
                HELD
                STOPPED_OUT

        action : str
            Intended trade action.

            Possible values:

                BUY
                SELL
                HOLD

        quantity : int
            Number of shares traded.

            For rejected or held trades this may be zero.

        price : float
            Execution price for the trade.

        signal : dict, optional
            Signal data produced by the strategy.

            May include:

                confidence
                signal_type
                strategy name
                reasoning text

        approval : dict, optional
            Risk manager approval result.

            May include:

                approval status
                risk checks
                rejection reason

        sizing : dict, optional
            Position sizing result produced by the PositionSizer.

            May include:

                sizing method
                position percentage

        realized_pnl : float
            Profit or loss realized by the trade.

            Typically non-zero for SELL trades closing positions.


        Behavior
        --------

        The implementation should:

        1) Construct a structured audit record

        2) Include metadata such as timestamps

        3) Include strategy reasoning and signal confidence

        4) Append the record to the JSONL audit file

        5) Optionally emit a human-readable log line


        Result
        ------

        No return value.

        The audit record is persisted to disk.
        """

        pass


    def record_stop_loss(
        self,
        ticker: str,
        entry_price: float,
        exit_price: float,
        quantity: int,
        realized_pnl: float,
        reason: str
    ) -> None:
        """
        Record a forced exit event such as a stop-loss or take-profit.

        Stop-loss events are triggered automatically by the risk
        management system and therefore bypass normal strategy logic.

        Parameters
        ----------

        ticker : str
            Asset symbol.

        entry_price : float
            Price at which the position was originally opened.

        exit_price : float
            Price at which the position was closed.

        quantity : int
            Number of shares closed.

        realized_pnl : float
            Profit or loss realized when closing the position.

        reason : str
            Human-readable explanation of why the stop was triggered.

            Examples:

                "Stop loss triggered"
                "Trailing stop hit"
                "Take profit reached"


        Behavior
        --------

        The implementation should write a record with outcome:

            STOPPED_OUT

        This record indicates that the exit was enforced
        by the risk management system rather than a strategy signal.
        """

        pass


    def tail(self, n: int = 20) -> list:
        """
        Retrieve the most recent audit records.

        This method allows developers or monitoring tools to inspect
        the latest trading decisions without reading the entire log.

        Parameters
        ----------

        n : int
            Number of recent records to return.

        Returns
        -------

        list of dict

            A list containing the last N audit records
            in chronological order.


        Typical Uses
        ------------

        • debugging recent trades
        • monitoring system activity
        • testing and validation
        """

        pass


    def summary(self) -> dict:
        """
        Compute aggregate statistics from the audit log.

        This method analyzes historical trade records and
        returns high-level performance metrics.

        Metrics May Include
        -------------------

        total_decisions
            Total number of trade decisions recorded.

        executed
            Number of trades successfully executed.

        rejected
            Number of signals rejected by risk management.

        stopped_out
            Number of forced exits due to stop-loss or take-profit.

        buys
            Number of BUY trades executed.

        sells
            Number of SELL trades executed.

        total_realized_pnl
            Total realized profit or loss across closed trades.

        win_rate
            Percentage of profitable closed trades.

        avg_confidence
            Average signal confidence across executed trades.


        Returns
        -------

        dict

            Aggregated statistics summarizing system behavior.
        """

        pass


    # ─────────────────────────────────────────────
    # INTERNAL OPERATIONS
    # ─────────────────────────────────────────────

    def _append(self, entry: dict) -> None:
        """
        Append a single audit record to the log file.

        This method performs the low-level file write operation.

        Implementation requirements:

        • serialize the record as JSON
        • append it as a single line to the JSONL file
        • ensure the write is atomic
        • handle file system errors gracefully

        This method is considered internal and should not
        be called directly by external components.
        """

        pass


# ── Module-level singleton ────────────────────────────────────────
trade_audit = TradeAudit()