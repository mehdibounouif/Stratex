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
    entry_price     float  original entry price (non-zero for STOPPED_OUT records)
    risk_approved   bool   whether the risk manager approved the trade
    risk_checks     dict   {check_name: bool} — which checks passed/failed
    reject_reason   str    why trade was rejected (empty string if executed)
    reasoning       str    strategy reasoning text

Author: Kawtar (Risk Manager)
"""

import json
import os
import threading
from datetime import datetime, timezone
from logger import get_logger, setup_logging

setup_logging()
log = get_logger('risk.trade_audit')


class TradeAudit:
    def __init__(self, log_path: str = "logs/trade_audit.jsonl"):
        """
        Initialize the trade auditing system.

        Parameters
        ----------
        log_path : str

            Path to the JSONL file used for storing audit records.

            Default location:

                logs/trade_audit.jsonl
        """

        #check if the path have a value and the value is a string
        if not log_path or not isinstance(log_path, str):
            raise ValueError(
                f"TradeAudit: log_path must be a non-empty string, "
                f"got {type(log_path).__name__!r}: {log_path!r}"
            )

        #checks the extention of the file it must end with .jsonl
        if not log_path.endswith('.jsonl'):
            raise ValueError(
                f"TradeAudit: log_path must end with '.jsonl', "
                f"got {log_path!r}"
            )
        #assiging the passed param path to local object path
        self.log_path = log_path

        try:
            os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
        except OSError as exc:
            raise OSError(
                f"TradeAudit: could not create log directory for "
                f"{log_path!r}: {exc}"
            ) from exc

        try:
            if not os.path.isfile(log_path):
                open(log_path, 'a').close()
        except OSError as exc:
            raise OSError(
                f"TradeAudit: could not create audit file "
                f"{log_path!r}: {exc}"
            ) from exc
        self._lock = threading.Lock()

        log.debug(f"TradeAudit initialized: {log_path}")


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

        # check if the ticker exists and it's a string 
        if not ticker or not isinstance(ticker, str):
            raise ValueError(
                f"record: ticker must be a non-empty string, "
                f"got {type(ticker).__name__!r}: {ticker!r}"
            )
        VALID_OUTCOMES = {"EXECUTED", "REJECTED", "HELD", "STOPPED_OUT"}
        if outcome not in VALID_OUTCOMES:
            raise ValueError(
                f"record: unknown outcome {outcome!r}. "
                f"Must be one of {VALID_OUTCOMES}"
            )

        # actions baynin
        VALID_ACTIONS = {"BUY", "SELL", "HOLD"}
        if action not in VALID_ACTIONS:
            raise ValueError(
                f"record: unknown action {action!r}. "
                f"Must be one of {VALID_ACTIONS}"
            )

        if not isinstance(quantity, int) or quantity < 0:
            raise ValueError(
                f"record: quantity must be a non-negative integer, "
                f"got {type(quantity).__name__!r}: {quantity!r}"
            )

        if not isinstance(price, (int, float)) or price < 0:
            raise ValueError(
                f"record: price must be a non-negative number, "
                f"got {type(price).__name__!r}: {price!r}"
            )

        if not isinstance(realized_pnl, (int, float)):
            raise ValueError(
                f"record: realized_pnl must be a number, "
                f"got {type(realized_pnl).__name__!r}: {realized_pnl!r}"
            )

        signal   = dict(signal)   if isinstance(signal,   dict) else {}
        approval = dict(approval) if isinstance(approval, dict) else {}
        sizing   = dict(sizing)   if isinstance(sizing,   dict) else {} 

        confidence = signal.get("confidence", 0.0)
        if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
            log.warning(
                f"record: confidence value {confidence!r} is outside "
                f"expected range [0.0, 1.0] for ticker={ticker}"
            )
            confidence = max(0.0, min(1.0, float(confidence))) if isinstance(confidence, (int, float)) else 0.0

        entry = {
            "timestamp":     datetime.now(timezone.utc).isoformat(),
            "ticker":        ticker.strip().upper(),
            "outcome":       outcome,
            "action":        action,
            "quantity":      quantity,
            "price":         price,
            "trade_value":   round(quantity * price, 4),
            "realized_pnl":  realized_pnl,
            "confidence":    confidence,
            "signal_type":   str(signal.get("signal_type", "")),
            "strategy":      str(signal.get("strategy",    "")),
            "reasoning":     str(signal.get("reasoning",   "")),
            "entry_price":   float(signal.get("entry_price", 0.0)),
            "sizing_method": str(sizing.get("method",      "none")),
            "size_pct":      float(sizing.get("size_pct",  0.0)),
            "risk_approved": bool(approval.get("approved", False)),
            "risk_checks":   approval.get("checks",        {}),
            "reject_reason": str(approval.get("reject_reason") or approval.get("reason") or ""),
        }
        self._append(entry)

        log.info(
            f"[AUDIT] {outcome:12s} | {ticker:6s} | {action:4s}"
            f" | qty={quantity:6d} | px={price:.2f}"
            f" | pnl={realized_pnl:+.2f}"
            f" | conf={confidence:.2f}"
            f" | {entry['signal_type']}"
        )


    def record_stop_loss(
        self,
        ticker: str,
        entry_price: float,
        exit_price: float,
        quantity: int,
        realized_pnl: float,
        reason: str
    ) -> None:
        if not ticker or not isinstance(ticker, str):
            raise ValueError(
                f"record_stop_loss: ticker must be a non-empty string, "
                f"got {type(ticker).__name__!r}: {ticker!r}"
            )

        for name, val in [("entry_price", entry_price), ("exit_price", exit_price)]:
            if not isinstance(val, (int, float)) or val <= 0:
                raise ValueError(
                    f"record_stop_loss: {name} must be a positive number, "
                    f"got {type(val).__name__!r}: {val!r}"
                )
        
        if not isinstance(quantity, int) or quantity < 0:
            raise ValueError(
                f"record_stop_loss: quantity must be a non-negative integer, "
                f"got {type(quantity).__name__!r}: {quantity!r}"
            )
        if not isinstance(realized_pnl, (int, float)):
            raise ValueError(
                f"record_stop_loss: realized_pnl must be a number, "
                f"got {type(realized_pnl).__name__!r}: {realized_pnl!r}"
            )

        if not reason or not isinstance(reason, str):
            raise ValueError(
                f"record_stop_loss: reason must be a non-empty string, "
                f"got {type(reason).__name__!r}: {reason!r}"
            )

        self.record(
            ticker=ticker,
            outcome="STOPPED_OUT",
            action="SELL",
            quantity=quantity,
            price=exit_price,
            signal={
                "confidence":  0.0,
                "signal_type": "STOP_LOSS",
                "strategy":    "Risk Management",
                "entry_price": entry_price,
                "reasoning":   (
                    f"{reason} | "
                    f"entry={entry_price:.2f} "
                    f"exit={exit_price:.2f} "
                    f"pnl={realized_pnl:+.2f}"
                ),
            },
            realized_pnl=realized_pnl,
        )


    def tail(self, n: int = 20) -> list:
        if not isinstance(n, int) or n <= 0:
            raise ValueError(
                f"tail: n must be a positive integer, "
                f"got {type(n).__name__!r}: {n!r}"
            )
        MAX_TAIL = 10_000
        if n > MAX_TAIL:
            log.warning(
                f"tail: n={n} exceeds maximum allowed ({MAX_TAIL}), "
                f"clamping to {MAX_TAIL}"
            )
            n = MAX_TAIL

        if not os.path.isfile(self.log_path):
            log.warning(f"tail: log file not found at {self.log_path!r}")
            return []
        lines = []
        try:
            with open(self.log_path, 'r', encoding='utf-8') as fh:
                lines = fh.readlines()
        except OSError as exc:
            log.error(f"tail: could not read log file: {exc}")
            return []

        records = []
        for line in lines[-n:]:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                log.warning(f"tail: skipping malformed line: {exc} | line={line[:80]!r}")

        return records


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

        # PROTECTION 1 — handle missing log file gracefully
        # the file may not exist yet on a fresh deployment
        # returning empty summary is more useful than crashing
        if not os.path.isfile(self.log_path):
            log.warning(f"summary: log file not found at {self.log_path!r}")
            return self._empty_summary()

        # PROTECTION 2 — guard the file read
        # permissions denied or disk error must not crash the system
        records = []
        try:
            with open(self.log_path, 'r', encoding='utf-8') as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    # PROTECTION 3 — skip malformed lines without aborting
                    # one corrupt record must not wipe out the entire summary
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        log.warning(
                            f"summary: skipping malformed line: {exc} | "
                            f"line={line[:80]!r}"
                        )
        except OSError as exc:
            log.error(f"summary: could not read log file: {exc}")
            return self._empty_summary()

        # PROTECTION 4 — handle empty file gracefully
        # file exists but has no valid records yet
        if not records:
            return self._empty_summary()

        # filter records by outcome and action
        executed = [r for r in records  if r.get("outcome") == "EXECUTED"]
        rejected = [r for r in records  if r.get("outcome") == "REJECTED"]
        stopped  = [r for r in records  if r.get("outcome") == "STOPPED_OUT"]
        buys     = [r for r in executed if r.get("action")  == "BUY"]
        sells    = [r for r in executed if r.get("action")  == "SELL"]

        # ── PnL aggregation ──────────────────────────────────────
        # PROTECTION 5 — guard each pnl value individually
        # a single non-numeric field must not corrupt the entire sum
        total_pnl    = 0.0
        pnl_count    = 0
        winning_count = 0

        for r in sells:
            raw = r.get("realized_pnl")
            # PROTECTION 6 — skip missing pnl fields
            if raw is None:
                log.warning(
                    f"summary: missing realized_pnl in record "
                    f"ticker={r.get('ticker', 'UNKNOWN')} "
                    f"timestamp={r.get('timestamp', 'UNKNOWN')}"
                )
                continue
            # PROTECTION 7 — skip non-numeric pnl values
            if not isinstance(raw, (int, float)):
                log.warning(
                    f"summary: non-numeric realized_pnl {raw!r} in record "
                    f"ticker={r.get('ticker', 'UNKNOWN')} "
                    f"timestamp={r.get('timestamp', 'UNKNOWN')}"
                )
                continue
            total_pnl += raw
            pnl_count += 1
            if raw > 0:
                winning_count += 1

        total_pnl = round(total_pnl, 4)

        # PROTECTION 8 — guard division by zero on win rate
        # no sells yet means win rate is not calculable
        if pnl_count > 0:
            win_rate = round(winning_count / pnl_count * 100, 2)
        else:
            win_rate = 0.0

        # ── Confidence aggregation ───────────────────────────────
        # PROTECTION 9 — guard each confidence value individually
        # only average over executed trades — rejected/held didn't commit capital
        confidence_sum   = 0.0
        confidence_count = 0

        for r in executed:
            raw = r.get("confidence")
            # PROTECTION 10 — skip missing confidence fields
            if raw is None:
                log.warning(
                    f"summary: missing confidence in record "
                    f"ticker={r.get('ticker', 'UNKNOWN')} "
                    f"timestamp={r.get('timestamp', 'UNKNOWN')}"
                )
                continue
            # PROTECTION 11 — skip non-numeric confidence values
            if not isinstance(raw, (int, float)):
                log.warning(
                    f"summary: non-numeric confidence {raw!r} in record "
                    f"ticker={r.get('ticker', 'UNKNOWN')} "
                    f"timestamp={r.get('timestamp', 'UNKNOWN')}"
                )
                continue
            confidence_sum   += raw
            confidence_count += 1

        # PROTECTION 12 — guard division by zero on average confidence
        # no executed trades yet means confidence is not calculable
        if confidence_count > 0:
            avg_confidence = round(confidence_sum / confidence_count, 4)
        else:
            avg_confidence = 0.0

        return {
            "total_decisions":    len(records),
            "executed":           len(executed),
            "rejected":           len(rejected),
            "stopped_out":        len(stopped),
            "buys":               len(buys),
            "sells":              len(sells),
            "total_realized_pnl": total_pnl,
            "win_rate":           win_rate,
            "avg_confidence":     avg_confidence,
        }

        # ─────────────────────────────────────────────
        # INTERNAL OPERATIONS
        # ─────────────────────────────────────────────

    def _append(self, entry: dict) -> None:
        if not self.log_path or not isinstance(self.log_path, str):
            log.error("_append: log_path is not set or invalid, skipping write")
            return

        if not isinstance(entry, dict) or not entry:
            log.error("_append: called with invalid entry, skipping")
            return

        expected_types = {
            "timestamp":    str,
            "ticker":       str,
            "outcome":      str,
            "action":       str,
            "quantity":     int,
            "price":        (int, float),
            "trade_value":  (int, float),
            "realized_pnl": (int, float),
            "confidence":   (int, float),
            "size_pct":     (int, float),
        }
        for field, expected in expected_types.items():
            val = entry.get(field)
            if val is not None and not isinstance(val, expected):
                log.warning(
                    f"_append: field '{field}' has unexpected type "
                    f"{type(val).__name__}, expected {expected} | "
                    f"ticker={entry.get('ticker', 'UNKNOWN')}"
                )

        
        try:
            line = json.dumps(entry, default=str) + "\n"
        except (TypeError, ValueError) as exc:
            log.error(
                f"_append: failed to serialize entry for "
                f"{entry.get('ticker', 'UNKNOWN')}: {exc}"
            )
            return

        try:
            with self._lock:
                with open(self.log_path, 'a', buffering=1, encoding='utf-8') as fh:
                    fh.write(line)
                    fh.flush()
                    os.fsync(fh.fileno())
        except OSError as exc:
            # catch filesystem errors without crashing
            # a failed audit write must never stop a trade from executing
            # inner try/except handles the case where the logger itself
            # fails (e.g. disk full) and would raise a second exception
            try:
                log.error(
                    f"_append: failed to write audit record for "
                    f"{entry.get('ticker', 'UNKNOWN')}: {exc} | "
                    f"entry={line.strip()}"
                )
            except Exception:
                pass  # logger itself failed — nothing left to do, must not crash


    def _empty_summary(self) -> dict:
        """Return a zeroed summary dict used when no records exist."""
        return {
            "total_decisions":    0,
            "executed":           0,
            "rejected":           0,
            "stopped_out":        0,
            "buys":               0,
            "sells":              0,
            "total_realized_pnl": 0.0,
            "win_rate":           0.0,
            "avg_confidence":     0.0,
        }


trade_audit = TradeAudit()