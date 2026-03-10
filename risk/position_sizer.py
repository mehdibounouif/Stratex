"""
Position Sizer
==============
Calculates how many shares to buy for a given trade signal.

Two sizing strategies are available, selectable via RiskConfig:

FIXED FRACTIONAL (default)
--------------------------
Risk a fixed percentage of portfolio value per trade.
Simple, predictable, and widely used.

    trade_value = portfolio_value × position_size_pct

The fraction can optionally scale with signal confidence
(high confidence → slightly larger position, low → smaller).
This is called "confidence-scaled fixed fractional."

    scaled_pct = base_pct + (confidence_above_min / confidence_range) × scale_range
    clamped to [min_pct, max_pct]

KELLY CRITERION
--------------
Mathematically optimal fraction for maximising long-term portfolio growth.
Derived from information theory (Claude Shannon / John Kelly, 1956).

    f* = (p × b - q) / b

Where:
    p  = probability of winning   (signal confidence, 0.0–1.0)
    q  = probability of losing    (1 - p)
    b  = win/loss ratio           (target_pct / stop_loss_pct, e.g. 10%/5% = 2.0)

IMPORTANT: Full Kelly is aggressive. We use a "fractional Kelly" — by default
half-Kelly (kelly_fraction=0.5) — which cuts volatility significantly while
retaining most of the growth benefit.

Full Kelly can recommend putting 30–40% of portfolio in a single trade.
Half-Kelly with our caps never exceeds MAX_POSITION_SIZE (15%).

USAGE
-----
    from risk.position_sizer import PositionSizer

    sizer  = PositionSizer()
    result = sizer.calculate(
        portfolio_value = 20_000.0,
        current_price   = 150.0,
        confidence      = 0.75,
        signal          = {'target_price': 165.0, 'stop_loss': 142.5}
    )

    quantity = result['quantity']         # shares to buy
    value    = result['trade_value']      # $ amount
    method   = result['method']           # 'fixed_fractional' or 'kelly'

CONFIGURATION
-------------
Set POSITION_SIZING_METHOD in trading_config.py:

    POSITION_SIZING_METHOD = 'fixed_fractional'   # default
    POSITION_SIZING_METHOD = 'kelly'               # experimental

Limits (from risk_config.py):
    MAX_POSITION_SIZE = 0.15   → cap at 15% of portfolio
    MIN_POSITION_SIZE = 0.02   → floor at 2% of portfolio
"""

from logger import get_logger, setup_logging

setup_logging()
log = get_logger('risk.position_sizer')






class PositionSizer:
    """
    Interface for the trading system position sizing engine.

    This class defines the public API used by the execution
    system to determine how large a trade should be.

    Implementations may use different algorithms internally,
    but must conform to this interface.
    """

    def __init__(self, method: str = None):
        """
        Initialize the position sizing engine.

        Parameters
        ----------
        method : str, optional

            Specifies which sizing algorithm should be used.

            Supported values:

                'fixed_fractional'
                'kelly'

            If not provided, the system will load the default
            method from TradingConfig.POSITION_SIZING_METHOD.


        Responsibilities
        ----------------

        During initialization the position sizer should:

        • Load trading configuration values
        • Load global risk constraints
        • Select the sizing algorithm
        • Prepare internal parameters required for sizing
        """

        from config.trading_config import TradingConfig
        from config.risk_config import RiskConfig

        self.tconfig = TradingConfig()
        self.rconfig = RiskConfig()

        # Method: explicit arg > config value > hardcoded default
        self.method = (
            method
            or getattr(self.tconfig, 'POSITION_SIZING_METHOD', 'fixed_fractional')
        )

        # Fixed fractional parameters
        self.base_pct   = getattr(self.tconfig, 'POSITION_SIZE_PCT', 0.05)
        self.min_pct    = self.rconfig.MIN_POSITION_SIZE        # 0.02
        self.max_pct    = self.rconfig.MAX_POSITION_SIZE        # 0.15
        self.min_conf   = getattr(self.tconfig, 'MIN_SIGNAL_CONFIDENCE', 0.55)

        # Kelly parameters
        self.kelly_fraction = getattr(self.tconfig, 'KELLY_FRACTION', 0.5)
        self.target_pct     = getattr(self.rconfig, 'DEFAULT_TAKE_PROFIT_PCT', 0.10)
        self.stop_pct       = getattr(self.rconfig, 'DEFAULT_STOP_LOSS_PCT',   0.05)

        log.debug(
            f"PositionSizer: method={self.method}, "
            f"base={self.base_pct:.0%}, "
            f"range=[{self.min_pct:.0%}, {self.max_pct:.0%}]"
        )



        pass


    # ─────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────

    def calculate(
        self,
        portfolio_value: float,
        current_price: float,
        confidence: float,
        signal: dict = None
    ) -> dict:
        """
        Calculate the appropriate position size for a trade.

        This is the primary method used by the trading system
        to determine trade allocation.

        Parameters
        ----------
        portfolio_value : float

            Total capital in the portfolio.

        current_price : float

            Current market price of the asset.

        confidence : float

            Strategy confidence score ranging from 0.0 to 1.0.

        signal : dict, optional

            Full signal object produced by the strategy.

            May contain:

                current_price
                target_price
                stop_loss


        Processing Steps
        ----------------

        The implementation should:

        1) Validate inputs

        2) Select the active sizing algorithm

        3) Calculate desired portfolio percentage

        4) Clamp result to risk limits

        5) Convert percentage into dollar allocation

        6) Convert dollar allocation into share quantity

        7) Return structured result


        Returns
        -------

        dict with fields:

        quantity
            Number of shares to trade.

        trade_value
            Dollar value of the position.

        size_pct
            Fraction of portfolio allocated.

        method
            Sizing algorithm used.

        reasoning
            Explanation of calculation for logging/debugging.
        """

        pass


    # ─────────────────────────────────────────────
    # SIZING ALGORITHMS
    # ─────────────────────────────────────────────

    def _fixed_fractional_size(self, confidence: float) -> tuple:
        """
        Fixed Fractional Position Sizing.

        This method allocates a base percentage of the portfolio
        to each trade and scales that percentage based on signal
        confidence.

        Concept
        -------

        Higher confidence signals receive slightly larger
        position sizes.

        Lower confidence signals receive smaller allocations.

        Example
        -------

        Base size = 5%

        Confidence scaling:

            confidence = 0.55 → ~4%
            confidence = 0.75 → ~5%
            confidence = 0.95 → ~7%

        Returns
        -------

        tuple:

            size_pct
                Target portfolio percentage.

            reasoning
                Explanation string for logging.
        """

        pass


    def _kelly_size(self, confidence: float, signal: dict = None) -> tuple:
        """
        Kelly Criterion Position Sizing.

        This method determines position size using the Kelly formula,
        which maximizes long-term capital growth based on statistical
        edge.

        Kelly Formula
        -------------

            f* = (p × b − q) / b

        where

            p = probability of winning
            q = probability of losing
            b = win/loss ratio


        Inputs
        ------

        probability of winning (p)

            Derived from the strategy confidence score.

        win/loss ratio (b)

            Derived from:

                target_price
                stop_loss

            If those values are unavailable, the system falls back
            to default risk/reward ratios defined in RiskConfig.


        Risk Adjustment
        ---------------

        Because full Kelly is extremely aggressive, implementations
        typically apply a fractional multiplier:

            fractional_kelly = full_kelly × KELLY_FRACTION

        Example:

            full Kelly = 12%
            KELLY_FRACTION = 0.5

            final size = 6%


        Returns
        -------

        tuple:

            size_pct
                Target portfolio percentage.

            reasoning
                Explanation string describing the calculation.
        """

        pass


    # ─────────────────────────────────────────────
    # HELPER METHODS
    # ─────────────────────────────────────────────

    @staticmethod
    def _zero_result(reason: str) -> dict:
        """
        Return a 'no trade' result.

        This method is used when a valid position size
        cannot be computed.

        Example cases

        • portfolio value is invalid
        • asset price is invalid
        • position size too small to purchase a single share


        Returns
        -------

        dict with zero position values and explanation.
        """

        pass
