"""
Walk-Forward Optimizer
======================

Automatically finds the best strategy parameters using rolling time windows,
so you don't overfit to a single historical period.

HOW IT WORKS
------------
1. Split the full date range into overlapping windows.
2. Each window has two parts:
   - IN-SAMPLE  (train): Try all parameter combinations, pick the best.
   - OUT-OF-SAMPLE (test): Run the best params on unseen data. Record the result.
3. After all windows, aggregate results → tells you which params survive real conditions.

USAGE (CLI)
-----------
    python main.py --optimize --ticker AAPL --start 2023-01-01 --end 2024-12-31

USAGE (Python)
--------------
    from system.walk_forward_optimizer import WalkForwardOptimizer
    from strategies.rsi_strategy import RSIStrategy

    opt = WalkForwardOptimizer(RSIStrategy)
    results = opt.run('AAPL', '2023-01-01', '2024-12-31')
    opt.save_results(results)

OUTPUT
------
Saves a JSON file to:  optimization_results/wfo_<ticker>_<timestamp>.json
Prints a summary table to the console.

Author: Mehdi (Quant_firm)
"""

import json
import os
import itertools
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta  # pip install python-dateutil

import pandas as pd

from logger import get_logger
from system.backtest_engine import BacktestEngine

log = get_logger("system.walk_forward_optimizer")


# ─────────────────────────────────────────────────────────────────────────────
# Default parameter grid for RSIStrategy
# Add or remove values to expand/shrink the search space.
# More values = more accurate results, but slower to run.
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_RSI_PARAM_GRID = {
    "rsi_buy":      [20, 25, 30],          # RSI oversold threshold (BUY signal)
    "rsi_sell":     [70, 75, 80],          # RSI overbought threshold (SELL signal)
    "holding_days": [3, 5, 7],             # Max days to hold a position
    "stop_loss":    [0.03, 0.05, 0.07],   # Stop-loss as a fraction (3%, 5%, 7%)
}


class WalkForwardOptimizer:
    """
    Runs walk-forward optimization for a given strategy class.

    Parameters
    ----------
    strategy_class : class
        The strategy CLASS (not instance). e.g. RSIStrategy (not rsi_strategy).
        We create new instances for each parameter combination.

    param_grid : dict, optional
        Dictionary of parameter names → list of values to test.
        Defaults to DEFAULT_RSI_PARAM_GRID.

    train_months : int
        How many months of data to use for finding best params (in-sample).
        Default: 6 months.

    test_months : int
        How many months of data to validate best params on (out-of-sample).
        Default: 2 months.

    step_months : int
        How many months to slide the window forward each iteration.
        Default: 2 months (matches test_months so windows don't overlap).

    metric : str
        Which backtest metric to use for ranking parameter sets.
        Options: 'sharpe_ratio', 'total_return', 'win_rate'
        Default: 'sharpe_ratio' (best risk-adjusted measure).
    """

    def __init__(
        self,
        strategy_class,
        param_grid=None,
        train_months=6,
        test_months=2,
        step_months=2,
        metric="sharpe_ratio",
    ):
        self.strategy_class = strategy_class
        self.param_grid = param_grid or DEFAULT_RSI_PARAM_GRID
        self.train_months = train_months
        self.test_months = test_months
        self.step_months = step_months
        self.metric = metric

        # All combinations of parameters we'll test
        # e.g. if rsi_buy=[20,25] and rsi_sell=[70,75], this gives:
        #      [(20,70), (20,75), (25,70), (25,75)]
        keys = list(self.param_grid.keys())
        values = list(self.param_grid.values())
        self.all_combinations = [
            dict(zip(keys, combo)) for combo in itertools.product(*values)
        ]

        log.info(
            f"WalkForwardOptimizer ready | "
            f"{len(self.all_combinations)} param combos | "
            f"train={train_months}mo, test={test_months}mo, step={step_months}mo | "
            f"metric={metric}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def run(self, ticker: str, start_date: str, end_date: str) -> dict:
        """
        Run the full walk-forward optimization.

        Parameters
        ----------
        ticker : str      e.g. 'AAPL'
        start_date : str  e.g. '2023-01-01'
        end_date : str    e.g. '2024-12-31'

        Returns
        -------
        dict with keys:
            'ticker', 'start_date', 'end_date', 'metric', 'windows', 'summary'
        """
        log.info(f"Starting walk-forward optimization: {ticker} | {start_date} → {end_date}")

        windows = self._build_windows(start_date, end_date)
        if not windows:
            log.error("Not enough data for even one window. Use a longer date range.")
            return {}

        log.info(f"Built {len(windows)} walk-forward windows")

        window_results = []
        for i, (train_start, train_end, test_start, test_end) in enumerate(windows):
            log.info(
                f"  Window {i+1}/{len(windows)} | "
                f"Train: {train_start}→{train_end} | "
                f"Test:  {test_start}→{test_end}"
            )
            result = self._run_single_window(
                ticker, train_start, train_end, test_start, test_end, window_num=i + 1
            )
            if result:
                window_results.append(result)

        if not window_results:
            log.error("All windows failed. Check your data source or date range.")
            return {}

        summary = self._summarize(window_results)
        self._print_summary(ticker, window_results, summary)

        return {
            "ticker": ticker,
            "start_date": start_date,
            "end_date": end_date,
            "metric": self.metric,
            "param_grid": self.param_grid,
            "windows": window_results,
            "summary": summary,
        }

    def save_results(self, results: dict, output_dir: str = "optimization_results") -> str:
        """
        Save optimization results to a JSON file.

        Returns the filepath of the saved file.
        """
        if not results:
            log.warning("No results to save.")
            return ""

        os.makedirs(output_dir, exist_ok=True)

        ticker = results.get("ticker", "UNKNOWN")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"wfo_{ticker}_{ts}.json"
        filepath = os.path.join(output_dir, filename)

        # Make the results JSON-serializable (remove non-serializable objects)
        clean = self._make_serializable(results)

        with open(filepath, "w") as f:
            json.dump(clean, f, indent=2)

        log.info(f"✅ Results saved → {filepath}")
        return filepath

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _build_windows(self, start_date: str, end_date: str) -> list:
        """
        Create a list of (train_start, train_end, test_start, test_end) tuples.

        Example with train=6mo, test=2mo, step=2mo, start=2023-01-01:
            Window 1: train=Jan→Jun, test=Jul→Aug
            Window 2: train=Mar→Aug, test=Sep→Oct
            Window 3: train=May→Oct, test=Nov→Dec
            ...
        """
        windows = []
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")

        train_start = start
        while True:
            train_end = train_start + relativedelta(months=self.train_months) - timedelta(days=1)
            test_start = train_end + timedelta(days=1)
            test_end = test_start + relativedelta(months=self.test_months) - timedelta(days=1)

            # Stop if test window goes beyond our data
            if test_end > end:
                break

            windows.append((
                train_start.strftime("%Y-%m-%d"),
                train_end.strftime("%Y-%m-%d"),
                test_start.strftime("%Y-%m-%d"),
                test_end.strftime("%Y-%m-%d"),
            ))

            # Slide forward by step_months
            train_start += relativedelta(months=self.step_months)

        return windows

    def _run_single_window(
        self, ticker, train_start, train_end, test_start, test_end, window_num
    ) -> dict:
        """
        For one window:
        1. Find the best params on the train period.
        2. Validate those params on the test period.
        3. Return a result dict.
        """

        # ── STEP 1: Find best params on train period ──────────────────────
        best_params = None
        best_score = float("-inf")
        best_train_metrics = {}

        log.info(f"    Training on {train_start}→{train_end} ({len(self.all_combinations)} combos)...")

        for params in self.all_combinations:
            try:
                strategy = self.strategy_class(**params)
                engine = BacktestEngine(strategy)
                metrics = engine.run(ticker, train_start, train_end)

                if not metrics:
                    continue

                score = metrics.get(self.metric, float("-inf"))

                # Skip degenerate results (0 trades = no signal, not useful)
                if metrics.get("total_trades", 0) == 0:
                    continue

                if score > best_score:
                    best_score = score
                    best_params = params
                    best_train_metrics = metrics

            except Exception as e:
                # A bad param combo (e.g. rsi_buy > rsi_sell) will just fail — skip it
                log.debug(f"    Skipping {params}: {e}")
                continue

        if best_params is None:
            log.warning(f"    Window {window_num}: No valid param combo found. Skipping.")
            return {}

        log.info(
            f"    Best train params: {best_params} | "
            f"{self.metric}={best_score:.3f} | "
            f"trades={best_train_metrics.get('total_trades', 0)}"
        )

        # ── STEP 2: Validate best params on test period ───────────────────
        try:
            strategy = self.strategy_class(**best_params)
            engine = BacktestEngine(strategy)
            test_metrics = engine.run(ticker, test_start, test_end)
        except Exception as e:
            log.warning(f"    Window {window_num}: Test period failed: {e}")
            return {}

        if not test_metrics:
            log.warning(f"    Window {window_num}: Test period returned no metrics.")
            return {}

        test_score = test_metrics.get(self.metric, 0)
        log.info(
            f"    Test result: {self.metric}={test_score:.3f} | "
            f"return={test_metrics.get('total_return', 0):.1f}% | "
            f"trades={test_metrics.get('total_trades', 0)}"
        )

        return {
            "window": window_num,
            "train_start": train_start,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
            "best_params": best_params,
            "train_score": round(best_score, 4),
            "test_score": round(test_score, 4),
            "test_return_pct": round(test_metrics.get("total_return", 0), 2),
            "test_trades": test_metrics.get("total_trades", 0),
            "test_win_rate": round(test_metrics.get("win_rate", 0), 2),
            "test_sharpe": round(test_metrics.get("sharpe_ratio", 0), 4),
            "test_max_drawdown": round(test_metrics.get("max_drawdown", 0), 2),
        }

    def _summarize(self, window_results: list) -> dict:
        """
        Aggregate results across all windows.

        Returns:
          - avg test return, sharpe, drawdown
          - most common best params across windows (the "consensus" params)
          - % of windows that were profitable
        """
        if not window_results:
            return {}

        returns = [w["test_return_pct"] for w in window_results]
        sharpes = [w["test_sharpe"] for w in window_results]
        drawdowns = [w["test_max_drawdown"] for w in window_results]
        profitable = [w for w in window_results if w["test_return_pct"] > 0]

        # Find the most frequently selected "best params"
        param_counts: dict = {}
        for w in window_results:
            key = json.dumps(w["best_params"], sort_keys=True)
            param_counts[key] = param_counts.get(key, 0) + 1

        most_common_key = max(param_counts, key=param_counts.get)
        consensus_params = json.loads(most_common_key)
        consensus_frequency = param_counts[most_common_key] / len(window_results)

        return {
            "total_windows": len(window_results),
            "profitable_windows": len(profitable),
            "pct_profitable": round(len(profitable) / len(window_results) * 100, 1),
            "avg_test_return": round(sum(returns) / len(returns), 2),
            "avg_test_sharpe": round(sum(sharpes) / len(sharpes), 4),
            "avg_test_drawdown": round(sum(drawdowns) / len(drawdowns), 2),
            "consensus_params": consensus_params,
            "consensus_frequency_pct": round(consensus_frequency * 100, 1),
        }

    def _print_summary(self, ticker: str, window_results: list, summary: dict):
        """Print a clean summary table to the console."""
        print("\n" + "=" * 60)
        print(f"  WALK-FORWARD OPTIMIZATION RESULTS — {ticker}")
        print("=" * 60)
        print(f"  Metric used for ranking : {self.metric}")
        print(f"  Total windows tested    : {summary.get('total_windows', 0)}")
        print(f"  Profitable windows      : {summary.get('profitable_windows', 0)} "
              f"({summary.get('pct_profitable', 0)}%)")
        print(f"  Avg test return         : {summary.get('avg_test_return', 0):+.2f}%")
        print(f"  Avg test Sharpe ratio   : {summary.get('avg_test_sharpe', 0):.3f}")
        print(f"  Avg test max drawdown   : {summary.get('avg_test_drawdown', 0):.2f}%")
        print("-" * 60)
        print(f"  CONSENSUS (most-selected) parameters:")
        for k, v in summary.get("consensus_params", {}).items():
            print(f"    {k:20s} = {v}")
        print(f"  Selected in {summary.get('consensus_frequency_pct', 0):.0f}% of windows")
        print("-" * 60)
        print("  Window-by-window breakdown:")
        print(f"  {'Win':>3}  {'Train':^23}  {'Test':^23}  {'Return':>7}  {'Sharpe':>7}  {'Params'}")
        print(f"  {'-'*3}  {'-'*23}  {'-'*23}  {'-'*7}  {'-'*7}  {'-'*20}")
        for w in window_results:
            params_short = ", ".join(f"{k}={v}" for k, v in w["best_params"].items())
            print(
                f"  {w['window']:>3}  "
                f"{w['train_start']}→{w['train_end']}  "
                f"{w['test_start']}→{w['test_end']}  "
                f"{w['test_return_pct']:>+7.2f}%  "
                f"{w['test_sharpe']:>7.3f}  "
                f"{params_short}"
            )
        print("=" * 60)
        print(f"\n  💡 RECOMMENDATION: Use consensus params above as your")
        print(f"     RSIStrategy default — they held up across {summary.get('total_windows',0)} real test periods.\n")

    @staticmethod
    def _make_serializable(obj):
        """Recursively convert non-JSON-serializable types (e.g. numpy floats)."""
        if isinstance(obj, dict):
            return {k: WalkForwardOptimizer._make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [WalkForwardOptimizer._make_serializable(v) for v in obj]
        elif hasattr(obj, "item"):  # numpy scalar
            return obj.item()
        elif isinstance(obj, float) and (obj != obj):  # NaN check
            return None
        return obj
