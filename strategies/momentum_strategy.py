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
from logger import get_logger, setup_logging
from strategies.base_strategy import BaseStrategy

setup_logging()
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

        Parameters
        ----------

        ticker : str
            Stock symbol to analyze.

            Examples:

                "AAPL"
                "MSFT"
                "NVDA"

        df : pandas.DataFrame, optional
            Historical OHLCV price data.

            Required columns:

                Date
                Open
                High
                Low
                Close
                Volume

            If no dataframe is provided, the strategy
            automatically retrieves data using:

                data_access.get_price_history()

        Data Retrieval Process
        ----------------------

        If `df` is None:

            1. Strategy calculates required history length
            2. Calls data_access.get_price_history()
            3. Receives cached or freshly downloaded data

        This ensures efficient reuse of market data.

        Data Requirements
        -----------------

        The dataset must contain enough rows to compute
        the largest indicator window.

        Required rows:

            max(roc_period, slow_ma, price_ma) + buffer

        Example:

            roc_period = 20
            slow_ma = 30
            price_ma = 50

            Required ≈ 55 days.

        If insufficient data is available,
        the strategy returns HOLD.

        Processing Steps
        ----------------

        1. Retrieve historical price data
        2. Validate dataset length
        3. Normalize column names
        4. Clean numeric price data
        5. Compute momentum indicators
        6. Generate trading signal
        7. Return standardized signal dictionary

        Returns
        -------

        dict

        {
            "action": BUY | SELL | HOLD,
            "confidence": 0-100,
            "reasoning": explanation string,
            "source": "Momentum",
            "indicators": {...}
        }
        """

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
            df.columns = [c.lower() for c in df.columns]
        except Exception as e:
            log.error(f"❌ Failed to normalize column names: {e}")
            return {}

        if "close" not in df.columns:
            log.error(f"❌ 'close' column not found. Available: {list(df.columns)}")
            return {}

        min_required = max(self.roc_period, self.slow_ma, self.price_ma) + 2

        if len(df) < min_required:
            log.warning(f"⚠️ Insufficient data: {len(df)} rows, need {min_required}.")
            return {}

        try:
            closes = pd.Series(
                [Decimal(str(x)) for x in df["close"].values],
                index=df.index
            )
        except Exception as e:
            log.error(f"❌ Failed to extract closing prices: {e}")
            return {}

        if closes.isnull().any():
            closes = closes.dropna()
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
        """
        Convert indicator values into a trading signal.

        Decision Method
        ---------------

        The strategy uses a **majority voting system**.

        Each indicator casts a vote:

            BUY
            SELL
            HOLD

        Indicators Voting
        -----------------

        • Rate of Change
        • Moving Average crossover
        • Price relative to moving average

        Final decision is determined by the majority.

        Example
        -------

        Indicator votes:

            ROC → BUY
            MA crossover → BUY
            Price vs MA → HOLD

        Final decision:

            BUY (2 out of 3 votes)

        Confidence Calculation
        ----------------------

        Confidence reflects the level of agreement.

            3/3 votes → strong signal (~90%)
            2/3 votes → moderate signal (~70%)
            1/3 votes → weak signal (~50%)

        Momentum Boost
        --------------

        If momentum is extremely strong:

            ROC > 2 × threshold

        confidence is slightly increased.

        Returns
        -------

        dict

        {
            "action": BUY | SELL | HOLD,
            "confidence": 0-100,
            "reasoning": explanation string,
            "source": "Momentum",
            "indicators": indicator dictionary
        }
        """

momentum_strategy = MomentumStrategy()
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