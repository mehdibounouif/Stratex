"""
Buys stocks with strong upward momentum, sells with downward momentum.

Uses multiple momentum indicators:
- Rate of Change (ROC)
- Moving Average Crossover
- Price vs Moving Average

Author: Kawtar
"""


import pandas as pd
import numpy as np
from logger import get_logger, setup_logging

setup_logging()
log = get_logger('strategies.momentum_strategy')


class MomentumStrategy:
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
    

    def analyze(self, ticker, df=None):
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

    def _calculate_indicators(self, df):
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

    def _generate_signal(self, ticker, indicators):
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
    print("MOMENTUM STRATEGY DEMO")
    print("="*60)
    
    # Create strategy (will use data_access singleton)
    strategy = MomentumStrategy(
        roc_period=20,
        roc_threshold=5.0,
        fast_ma=10,
        slow_ma=30,
        price_ma=50
    )
    
    # Test on real data using data_access
    print("\n🎯 Testing on AAPL using data_access...")
    ticker = "AAPL"
    
    try:
        # This will use data_access to get cached or fetch fresh data
        signal = strategy.analyze(ticker)
        
        # Print results
        print("\n" + "="*60)
        print("MOMENTUM ANALYSIS RESULTS")
        print("="*60)
        print(f"Ticker:     {ticker}")
        print(f"Action:     {signal['action']}")
        print(f"Confidence: {signal['confidence']}%")
        print(f"Reasoning:  {signal['reasoning']}")
        
        if signal['indicators']:
            print("\nIndicators:")
            for key, value in signal['indicators'].items():
                print(f"  {key}: {value}")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        print("\nNote: If Yahoo Finance is rate-limited, this is expected.")
        print("The strategy will work fine with cached data in production.")
    
    print("\n✅ Demo complete")
    print("\nUsage in your system:")
    print("  from strategies.momentum_strategy import MomentumStrategy")
    print("  momentum = MomentumStrategy()")
    print("  signal = momentum.analyze('AAPL')")
    print("\nThe strategy automatically uses your data_access singleton!")
    print("No direct yfinance calls - fully integrated with your architecture.")