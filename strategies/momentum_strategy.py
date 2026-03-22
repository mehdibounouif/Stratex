"""
Buys stocks with strong upward momentum, sells with downward momentum.

Uses multiple momentum indicators:
- Rate of Change (ROC)
- Moving Average Crossover
- Price vs Moving Average

Author: Kawtar
"""


import pandas as pd
from decimal import Decimal
import numpy as np
from datetime import datetime
from logger import get_logger
from strategies.base_strategy import BaseStrategy

log = get_logger('strategies.momentum_strategy')


class MomentumStrategy(BaseStrategy):
    """
    Momentum-based trading strategy.
    
    ARCHITECTURE:
    - Uses data_access singleton (NO direct yfinance calls)
    - Compatible with data_engineer caching system
    - Same pattern as RSIStrategy
    
    INDICATORS USED:
    1. ROC (Rate of Change): Price change over N days
    2. MA Crossover: Fast MA crosses slow MA
    3. Price vs MA: Current price relative to moving average
    
    BUY SIGNALS:
    - ROC > threshold (e.g., +5% over 20 days)
    - Fast MA crosses above Slow MA (Golden Cross)
    - Price > MA (uptrend)
    
    SELL SIGNALS:
    - ROC < negative threshold (e.g., -5% over 20 days)
    - Fast MA crosses below Slow MA (Death Cross)
    - Price < MA (downtrend)
    
    CONFIDENCE SCORING:
    - All 3 indicators agree: 85-95%
    - 2/3 indicators agree: 65-75%
    - 1/3 indicators: 50-60%
    """

    def __init__(self,
                 roc_period=20,
                 roc_threshold=5.0,
                 fast_ma=10,
                 slow_ma=30,
                 price_ma=50,
                 data_access=None):
        
        self.roc_period = roc_period
        self.roc_threshold = roc_threshold
        self.fast_ma = fast_ma
        self.slow_ma = slow_ma
        self.price_ma = price_ma

        if data_access is None:
            from data.data_engineer import data_access
            self.data_access = data_access
        else:
            self.data_access = data_access
        
        log.info(f"✅ MomentumStrategy initialized:")
        log.info(f"   ROC: {roc_period} days, ±{roc_threshold}% threshold")
        log.info(f"   MA Crossover: {fast_ma}/{slow_ma} days")
        log.info(f"   Price vs MA: {price_ma} days")
        log.info(f"   Data source: {'data_access singleton' if data_access else 'imported'}")
    

    def generate_signal(self, ticker: str, price_data=None) -> dict:
        """
        Analyze a stock's momentum and generate a signal.
        (See docstring above for full details.)
        """
        if price_data is None:
            days_needed = max(self.roc_period, self.slow_ma, self.price_ma) + 10
            price_data = self.data_access.get_price_history(ticker, days=days_needed)

        min_rows = max(self.roc_period, self.slow_ma, self.price_ma) + 2
        if price_data is None or len(price_data) < min_rows:
            log.warning(f"⚠️ [{ticker}] Insufficient data — returning HOLD")
            return self._no_signal(ticker, f"Insufficient data (need ≥ {min_rows} rows)")

        indicators = self._calculate_indicators(price_data)

        if not indicators:
            log.warning(f"⚠️ [{ticker}] _calculate_indicators() returned empty — returning HOLD")
            return self._no_signal(ticker, "Indicator calculation failed")

        signal = self._generate_signal(ticker, indicators)

        return self._validate(signal)


    def _calculate_indicators(self, df: pd.DataFrame) -> dict:
        """
        Compute technical indicators used by the strategy.

        Indicators Calculated
        ---------------------

        1. Rate of Change (ROC)
        2. Fast Moving Average
        3. Slow Moving Average
        4. Price Moving Average
        5. Golden Cross detection
        6. Death Cross detection
        7. Price distance from moving average
        8. Trend direction

        Rate of Change (ROC)
        --------------------

        Measures percentage price change over
        a fixed lookback period.

        Formula:

            ROC = ((Price_today - Price_N_days_ago)
                   / Price_N_days_ago) * 100

        Interpretation:

            ROC > 0  → positive momentum
            ROC < 0  → negative momentum

        Moving Averages
        ---------------

        A moving average smooths price data to
        identify underlying trends.

        Formula:

            MA = average(price over N days)

        Crossover Detection
        -------------------

        Golden Cross:

            Fast MA crosses ABOVE slow MA

        Death Cross:

            Fast MA crosses BELOW slow MA

        Trend Strength
        --------------

        Measures how far price deviates from
        its moving average.

        Formula:

            price_vs_ma_pct =
                (price - MA) / MA * 100

        Returns
        -------

        dict

            Dictionary containing computed
            indicator values.
        """
        try:
            #checks the names in the columns and normalize them to lowercase
            df.columns = [c.lower() for c in df.columns]
        except Exception as e:
            log.error(f"❌ Failed to normalize column names: {e}")
            return {}

        if "close" not in df.columns:
            log.error(f"❌ 'close' column not found. Available: {list(df.columns)}")
            return {}

        min_required = max(self.roc_period, self.slow_ma, self.price_ma) + 2
        #checks if the N of rows in the data frame are enough
        if len(df) < min_required:
            log.warning(f"⚠️ Insufficient data: {len(df)} rows, need {min_required}.")
            return {}

        try:
            #converts the data to pd series with one columns of closing prices
            closes = pd.Series(
                [Decimal(str(x)) for x in df["close"].values],
                index=df.index
            )
        except Exception as e:
            log.error(f"❌ Failed to extract closing prices: {e}")
            return {}

        if closes.isnull().any():
            closes = closes.dropna()
            #dropna drops the null values and recompute the closes
            if len(closes) < min_required:
                log.error(f"❌ After dropping NaNs: {len(closes)} rows, need {min_required}.")
                return {}

        log.info(f"✅ DataFrame validated: {len(closes)} rows | First={closes.iloc[0]} | Last={closes.iloc[-1]}")

        try:
            price_today = closes.iloc[-1]
            price_n_ago = closes.iloc[-1 - self.roc_period]

            if price_n_ago == 0:
                log.error("❌ price_n_ago is zero — division by zero.")
                return {}

            roc = ((price_today - price_n_ago) / price_n_ago) * Decimal("100")
            log.debug(f"ROC={roc:.4f}% | today={price_today} | {self.roc_period}d_ago={price_n_ago}")

        except Exception as e:
            log.error(f"❌ ROC calculation failed: {e}")
            return {}

        try:
            #drops the days (NAN) that are no in the range for the ma and then computes the ma for the left values in the closes
            fast_ma_series  = closes.rolling(window=self.fast_ma).mean()
            slow_ma_series  = closes.rolling(window=self.slow_ma).mean()
            price_ma_series = closes.rolling(window=self.price_ma).mean()

            fast_ma_today     = Decimal(str(fast_ma_series.iloc[-1]))
            fast_ma_yesterday = Decimal(str(fast_ma_series.iloc[-2]))
            slow_ma_today     = Decimal(str(slow_ma_series.iloc[-1]))
            slow_ma_yesterday = Decimal(str(slow_ma_series.iloc[-2]))
            price_ma_today    = Decimal(str(price_ma_series.iloc[-1]))

            for name, val in {
                "fast_ma_today"     : fast_ma_today,
                "fast_ma_yesterday" : fast_ma_yesterday,
                "slow_ma_today"     : slow_ma_today,
                "slow_ma_yesterday" : slow_ma_yesterday,
                "price_ma_today"    : price_ma_today,
            }.items():
                #it tranfer the values into strings to check if any of it is none
                if str(val) == "NaN":
                    log.error(f"❌ {name} is NaN — increase days in get_price_history().")
                    return {}

            log.debug(
                f"FastMA={fast_ma_today:.4f} (prev={fast_ma_yesterday:.4f}) | "
                f"SlowMA={slow_ma_today:.4f} (prev={slow_ma_yesterday:.4f}) | "
                f"PriceMA={price_ma_today:.4f}"
            )

        except Exception as e:
            log.error(f"❌ Moving average calculation failed: {e}")
            return {}

        try:
            golden_cross = bool(
                fast_ma_yesterday < slow_ma_yesterday and
                fast_ma_today     > slow_ma_today
            )
            death_cross = bool(
                fast_ma_yesterday > slow_ma_yesterday and
                fast_ma_today     < slow_ma_today
            )
            log.debug(f"GoldenCross={golden_cross} | DeathCross={death_cross}")

        except Exception as e:
            log.error(f"❌ Crossover detection failed: {e}")
            return {}

        try:
            if price_ma_today == 0:
                log.error("❌ price_ma_today is zero — division by zero.")
                return {}

            price_vs_ma_pct = (
                (price_today - price_ma_today) / price_ma_today
            ) * Decimal("100")

            log.debug(f"PriceVsMA={price_vs_ma_pct:.4f}% | price={price_today} | MA={price_ma_today:.4f}")

        except Exception as e:
            log.error(f"❌ Price vs MA calculation failed: {e}")
            return {}

        try:
            indicators = {
                "roc"             : round(roc,             4),
                "fast_ma"         : round(fast_ma_today,   4),
                "slow_ma"         : round(slow_ma_today,   4),
                "price_ma"        : round(price_ma_today,  4),
                "price_vs_ma_pct" : round(price_vs_ma_pct, 4),
                "golden_cross"    : golden_cross,
                "death_cross"     : death_cross,
                "price_today"     : round(price_today,     4),
            }

            log.info(
                f"✅ Indicators ready | "
                f"ROC={roc:.2f}% | "
                f"FastMA={fast_ma_today:.2f} | "
                f"SlowMA={slow_ma_today:.2f} | "
                f"PriceVsMA={price_vs_ma_pct:.2f}% | "
                f"GoldenCross={golden_cross} | "
                f"DeathCross={death_cross}"
            )

            return indicators

        except Exception as e:
            log.error(f"❌ Failed to pack indicators dict: {e}")
            return {}


    def _generate_signal(self, ticker: str, ind: dict) -> dict:

        required_keys = {
            "roc", "price_vs_ma_pct", "golden_cross", "death_cross",
            "price_today", "fast_ma", "slow_ma"
        }
        missing = required_keys - ind.keys()
        if missing:
            log.error(f"❌ [{ticker}] Missing indicator keys: {missing}")
            return self._no_signal(ticker, f"Missing indicators: {missing}")

        try:
            roc          = ind["roc"]
            price_vs_ma  = ind["price_vs_ma_pct"]
            golden_cross = ind["golden_cross"]
            death_cross  = ind["death_cross"]
            price_today  = ind["price_today"]
            fast_ma      = ind["fast_ma"]
            slow_ma      = ind["slow_ma"]
            threshold    = Decimal(str(self.roc_threshold))
            tolerance    = Decimal("2.0")
        except Exception as e:
            log.error(f"❌ [{ticker}] Failed to unpack indicators: {e}")
            return self._no_signal(ticker, "Indicator unpacking failed")

        for name, val in {
            "roc"         : roc,
            "price_vs_ma" : price_vs_ma,
            "price_today" : price_today,
            "fast_ma"     : fast_ma,
            "slow_ma"     : slow_ma,
        }.items():
            if val is None or str(val) == "NaN":
                log.error(f"❌ [{ticker}] {name} is invalid: {val}")
                return self._no_signal(ticker, f"Invalid indicator value: {name}={val}")

        if price_today <= 0:
            log.error(f"❌ [{ticker}] price_today is non-positive: {price_today}")
            return self._no_signal(ticker, f"Invalid price: {price_today}")

        try:
            if roc > threshold:
                roc_vote = "BUY"
            elif roc < -threshold:
                roc_vote = "SELL"
            else:
                roc_vote = "HOLD"
        except Exception as e:
            log.error(f"❌ [{ticker}] ROC vote failed: {e}")
            return self._no_signal(ticker, "ROC vote failed")

        try:
            if golden_cross:
                crossover_vote = "BUY"
            elif death_cross:
                crossover_vote = "SELL"
            else:
                #we need to recheck the fast ma vs slow because the crossover doesn't happen often so the trend may be up or down and the co still says hold
                if fast_ma > slow_ma:
                    crossover_vote = "BUY"
                elif fast_ma < slow_ma:
                    crossover_vote = "SELL"
                else:
                    crossover_vote = "HOLD"
        except Exception as e:
            log.error(f"❌ [{ticker}] Crossover vote failed: {e}")
            return self._no_signal(ticker, "Crossover vote failed")

        try:
            if price_vs_ma > tolerance:
                price_ma_vote = "BUY"
            elif price_vs_ma < -tolerance:
                price_ma_vote = "SELL"
            else:
                price_ma_vote = "HOLD"
        except Exception as e:
            log.error(f"❌ [{ticker}] Price vs MA vote failed: {e}")
            return self._no_signal(ticker, "Price vs MA vote failed")

        votes      = [roc_vote, crossover_vote, price_ma_vote]
        buy_count  = votes.count("BUY")
        sell_count = votes.count("SELL")

        log.info(
            f"[{ticker}] Votes → "
            f"ROC:{roc_vote} | Crossover:{crossover_vote} | PriceVsMA:{price_ma_vote} | "
            f"BUY={buy_count} SELL={sell_count}"
        )

        if buy_count > sell_count and buy_count >= 2:
            action      = "BUY"
            agree_count = buy_count
        elif sell_count > buy_count and sell_count >= 2:
            action      = "SELL"
            agree_count = sell_count
        else:
            action      = "HOLD"
            agree_count = max(buy_count, sell_count)

        if agree_count == 3:
            base_confidence = Decimal("0.90")
        elif agree_count == 2:
            base_confidence = Decimal("0.70")
        else:
            base_confidence = Decimal("0.50")

        momentum_boost = Decimal("0.0")
        if action == "BUY"  and roc >  2 * threshold:
            momentum_boost = Decimal("0.05")
        elif action == "SELL" and roc < -(2 * threshold):
            momentum_boost = Decimal("0.05")

        confidence = min(base_confidence + momentum_boost, Decimal("0.95"))

        cross_str = (
            "Golden Cross detected. " if golden_cross else
            "Death Cross detected. "  if death_cross  else ""
        )

        reasoning = (
            f"Momentum analysis ({agree_count}/3 indicators agree on {action}). "
            f"ROC({self.roc_period}d)={roc} (threshold +/-{threshold}). "
            f"{cross_str}"
            f"Price is {price_vs_ma} vs {self.price_ma}-day MA (tolerance +/-{tolerance}%). "
            f"Votes → ROC:{roc_vote} | Crossover:{crossover_vote} | PriceVsMA:{price_ma_vote}."
        )

        signal = {
            "ticker"        : ticker,
            "action"        : action,
            "signal_type"   : f"MOMENTUM_{action}",
            "confidence"    : confidence,
            "current_price" : price_today,
            "reasoning"     : reasoning,
            "source"        : "Momentum",
            "strategy"      : "MomentumStrategy",
            "indicators"    : ind,
            "timestamp"     : datetime.now().isoformat(),
        }

        log.info(
            f"✅ [{ticker}] Signal → {action} | "
            f"Confidence={confidence} | "
            f"Price={price_today}"
        )

        return self._validate(signal)


try:
    momentum_strategy = MomentumStrategy()
    log.info("✅ momentum_strategy singleton ready")
except Exception as e:
    log.error(f"❌ Failed to initialize momentum_strategy singleton: {e}")
    momentum_strategy = None


# ══════════════════════════════════════════════════════════════
# DEMO & TESTING
# ══════════════════════════════════════════════════════════════


if __name__ == "__main__":
    print("\n" + "="*60)
    print("MOMENTUM STRATEGY — _calculate_indicators() TEST")
    print("="*60)

    TICKERS = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]
    DAYS    = 90

    # ── create strategy instance ───────────────────────────
    strategy = MomentumStrategy(
        roc_period    = 20,
        roc_threshold = 5.0,
        fast_ma       = 10,
        slow_ma       = 30,
        price_ma      = 50
    )

    # ── run test for each ticker ───────────────────────────
    results  = {}
    failed   = []

    for ticker in TICKERS:
        print(f"\n{'='*60}")
        print(f"TESTING: {ticker}")
        print(f"{'='*60}")

        df = strategy.data_access.get_price_history(ticker, days=DAYS)

        if df is None or df.empty:
            print(f"❌ No data returned for {ticker}.")
            failed.append(ticker)
            continue

        print(f"✅ Got {len(df)} rows | From {df['Date'].iloc[0]} → {df['Date'].iloc[-1]}")

        indicators = strategy._calculate_indicators(df)

        if not indicators:
            print(f"❌ _calculate_indicators() returned empty dict for {ticker}.")
            failed.append(ticker)
            continue

        results[ticker] = indicators

        print(f"  {'roc':<20} : {indicators['roc']}")
        print(f"  {'fast_ma':<20} : {indicators['fast_ma']}")
        print(f"  {'slow_ma':<20} : {indicators['slow_ma']}")
        print(f"  {'price_ma':<20} : {indicators['price_ma']}")
        print(f"  {'price_vs_ma_pct':<20} : {indicators['price_vs_ma_pct']}")
        print(f"  {'golden_cross':<20} : {indicators['golden_cross']}")
        print(f"  {'death_cross':<20} : {indicators['death_cross']}")
        print(f"  {'price_today':<20} : {indicators['price_today']}")

    # ── summary ────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"  Total   : {len(TICKERS)}")
    print(f"  Passed  : {len(results)}  → {list(results.keys())}")
    print(f"  Failed  : {len(failed)}   → {failed if failed else 'none'}")
    print(f"{'='*60}")

    if failed:
        print(f"\n⚠️  Some tickers failed. Check logs above.")
        raise SystemExit(1)

    print("\n✅ All tickers passed — ready to build _generate_signal()")