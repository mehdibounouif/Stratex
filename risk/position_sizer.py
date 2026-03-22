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

Author: Kawtar (Risk Manager)
"""
from logger import get_logger, setup_logging
from decimal import Decimal, InvalidOperation

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
        #iport inside init to avoid loop calling
        from config.trading_config import TradingConfig
        from config.risk_config import RiskConfig

        try:
            self.tconfig = TradingConfig()
            self.rconfig = RiskConfig()
        except Exception as e:
            log.error(f"PositionSizer: config load failed: {e}")
            raise
        #if no method was passed initially it tries to get the method from the tconf esle default
        self.method = (
            method
            or getattr(self.tconfig, 'POSITION_SIZING_METHOD', 'fixed_fractional')
        )

        VALID_METHODS = {'fixed_fractional', 'kelly'}
        if self.method not in VALID_METHODS:
            raise ValueError(
                f"Unknown sizing method '{self.method}'. "
                f"Must be one of {VALID_METHODS}"
            )

        # how max / min trade can take from the portfolio based on configs + default confid
        self.base_pct = getattr(self.tconfig, 'POSITION_SIZE_PCT',     0.05)
        self.min_pct  = getattr(self.rconfig, 'MIN_POSITION_SIZE',     0.02)
        self.max_pct  = getattr(self.rconfig, 'MAX_POSITION_SIZE',     0.15)
        self.min_conf = getattr(self.tconfig, 'MIN_SIGNAL_CONFIDENCE', 0.55)

        if not (0 < self.min_pct < self.max_pct <= 1.0):
            raise ValueError(
                f"Invalid position size bounds: "
                f"min={self.min_pct}, max={self.max_pct}"
            )

        # Kelly parameters
        self.kelly_fraction = getattr(self.tconfig, 'KELLY_FRACTION',          0.5)
        # assume we gain 10% on a winning trade
        self.target_pct     = getattr(self.rconfig, 'DEFAULT_TAKE_PROFIT_PCT', 0.10)
        # assume we lose 5% on a losing trade
        self.stop_pct       = getattr(self.rconfig, 'DEFAULT_STOP_LOSS_PCT',   0.05)

        if not (0 < self.stop_pct < self.target_pct <= 1.0):
            raise ValueError(
                f"Invalid Kelly bounds: "
                f"stop={self.stop_pct}, target={self.target_pct}"
            )

        if not (0 < self.kelly_fraction <= 1.0):
            raise ValueError(
                f"kelly_fraction must be between 0 and 1, "
                f"got {self.kelly_fraction}"
            )

        log.debug(
            f"PositionSizer ready — "
            f"method={self.method}, "
            f"base={self.base_pct:.0%}, "
            f"range=[{self.min_pct:.0%}, {self.max_pct:.0%}], "
            f"kelly_fraction={self.kelly_fraction}"
        )


    # ─────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────

    def calculate(
        self,
        portfolio_value: float,
        current_price:   float,
        confidence:      float,
        signal:          dict = None
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

        try:
            portfolio_value = Decimal(str(portfolio_value))
            current_price   = Decimal(str(current_price))
            confidence      = Decimal(str(confidence))
        except InvalidOperation as e:
            return self._zero_result(
                f"Could not convert inputs to Decimal: {e}"
            )

        if portfolio_value <= Decimal('0.0'):
            return self._zero_result(
                f"Invalid portfolio value: {portfolio_value}"
            )

        if current_price <= Decimal('0.0'):
            return self._zero_result(
                f"Invalid current price: {current_price}"
            )

        if not (Decimal('0.0') <= confidence <= Decimal('1.0')):
            return self._zero_result(
                f"Invalid confidence: {confidence}. Must be between 0.0 and 1.0"
            )

        try:
            if self.method == 'kelly':
                size_pct, reasoning = self._kelly_size(confidence, signal)
            else:
                size_pct, reasoning = self._fixed_fractional_size(confidence)
        except ValueError as e:
            return self._zero_result(
                f"Sizing algorithm failed: {e}"
            )

        # clamp to risk limits
        min_pct  = Decimal(str(self.min_pct))
        max_pct  = Decimal(str(self.max_pct))
        size_pct = max(min_pct, min(max_pct, size_pct))

        trade_value = portfolio_value * size_pct

        quantity = int(trade_value // current_price)

        if quantity < 1:
            return self._zero_result(
                f"Position too small: "
                f"trade_value={trade_value} "
                f"< current_price={current_price}"
            )

        actual_trade_value = Decimal(str(quantity)) * current_price
        actual_size_pct    = actual_trade_value / portfolio_value

        log.info(
            f"calculate: "
            f"method={self.method}, "
            f"portfolio={portfolio_value}, "
            f"price={current_price}, "
            f"confidence={confidence}, "
            f"size_pct={size_pct}, "
            f"quantity={quantity}, "
            f"actual_trade_value={actual_trade_value}, "
            f"actual_size_pct={actual_size_pct}"
        )

        return {
            "quantity":    quantity,
            "trade_value": float(actual_trade_value),
            "size_pct":    float(actual_size_pct),
            "method":      self.method,
            "reasoning":   reasoning,
        }


    # ─────────────────────────────────────────────
    # SIZING ALGORITHMS
    # ─────────────────────────────────────────────

    def _fixed_fractional_size(self, confidence: Decimal) -> tuple:
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
                Target portfolio percentage as Decimal.

            reasoning
                Explanation string for logging.
        """

        try:
            min_conf = Decimal(str(self.min_conf))
            min_pct  = Decimal(str(self.min_pct))
            max_pct  = Decimal(str(self.max_pct))
        except InvalidOperation as e:
            raise ValueError(
                f"Could not convert config values to Decimal: {e}"
            )

        conf_range = Decimal('1.0') - min_conf
        if conf_range <= Decimal('0.0'):
            raise ValueError(
                f"min_conf={min_conf} leaves no room for scaling. "
                f"Must be less than 1.0"
            )

        scale_range = max_pct - min_pct

        if scale_range <= Decimal('0.0'):
            raise ValueError(
                f"max_pct={max_pct} must be greater than "
                f"min_pct={min_pct}"
            )

        # how far above the minimum is this confidence score
        # max(0) protects against tiny negatives from floating point noise
        conf_above_min = max(Decimal('0.0'), confidence - min_conf)

        # map confidence range onto position size range
        ratio      = conf_above_min / conf_range
        raw_scale  = ratio * scale_range
        scaled_pct = min_pct + raw_scale

        # clamp to risk limits as a final safety net
        size_pct = max(min_pct, min(max_pct, scaled_pct))

        reasoning = (
            f"Fixed fractional: "
            f"confidence={confidence}, "
            f"min_conf={min_conf}, "
            f"conf_above_min={conf_above_min}, "
            f"conf_range={conf_range}, "
            f"ratio={ratio}, "
            f"scale_range={scale_range}, "
            f"raw_scale={raw_scale}, "
            f"scaled_pct={scaled_pct}, "
            f"final_size={size_pct}"
        )

        log.debug(reasoning)

        # return Decimal — no float conversion here
        return size_pct, reasoning


    def _kelly_size(self, confidence: Decimal, signal: dict = None) -> tuple:
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
                Target portfolio percentage as Decimal.

            reasoning
                Explanation string describing the calculation.
        """

        # confidence arrives as Decimal from calculate
        signal = signal or {}

        # extract prices from signal if available
        current_price = signal.get("current_price")
        target_price  = signal.get("target_price")
        stop_loss     = signal.get("stop_loss")

        # try to build real win/loss ratio from signal prices
        if current_price and target_price and stop_loss:
            try:
                current_price = Decimal(str(current_price))
                target_price  = Decimal(str(target_price))
                stop_loss     = Decimal(str(stop_loss))
            except InvalidOperation as e:
                raise ValueError(
                    f"Could not convert signal prices to Decimal: {e}"
                )

            # guard: prices must be positive and logical
            if current_price <= Decimal('0.0'):
                raise ValueError(
                    f"current_price={current_price} must be greater than 0"
                )
            if stop_loss >= current_price:
                raise ValueError(
                    f"stop_loss={stop_loss} must be less than "
                    f"current_price={current_price}"
                )
            if target_price <= current_price:
                raise ValueError(
                    f"target_price={target_price} must be greater than "
                    f"current_price={current_price}"
                )

            win_pct      = (target_price - current_price) / current_price
            loss_pct     = (current_price - stop_loss)    / current_price
            price_source = "signal"

        else:
            # fall back to config defaults
            try:
                win_pct  = Decimal(str(self.target_pct))
                loss_pct = Decimal(str(self.stop_pct))
            except InvalidOperation as e:
                raise ValueError(
                    f"Could not convert config defaults to Decimal: {e}"
                )
            price_source = "config defaults"

        # guard: loss_pct cannot be zero, it is the denominator in b
        if loss_pct <= Decimal('0.0'):
            raise ValueError(
                f"loss_pct={loss_pct} must be greater than 0"
            )

        # win/loss ratio: for every $1 risked, how much do we gain on a win
        b = win_pct / loss_pct

        # kelly formula: f* = (p x b - q) / b
        p = confidence
        q = Decimal('1.0') - p

        full_kelly = max(Decimal('0.0'), (p * b - q) / b)

        # apply fractional kelly multiplier
        try:
            kelly_fraction = Decimal(str(self.kelly_fraction))
            min_pct        = Decimal(str(self.min_pct))
            max_pct        = Decimal(str(self.max_pct))
        except InvalidOperation as e:
            raise ValueError(
                f"Could not convert Kelly config values to Decimal: {e}"
            )

        size_pct = full_kelly * kelly_fraction

        # clamp to risk limits as final safety net
        size_pct = max(min_pct, min(max_pct, size_pct))

        reasoning = (
            f"Kelly ({price_source}): "
            f"confidence={confidence}, "
            f"p={p}, "
            f"q={q}, "
            f"win_pct={win_pct}, "
            f"loss_pct={loss_pct}, "
            f"b={b}, "
            f"full_kelly={full_kelly}, "
            f"kelly_fraction={kelly_fraction}, "
            f"final_size={size_pct}"
        )

        log.debug(reasoning)

        # return Decimal — no float conversion here
        return size_pct, reasoning


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
        return {
            "quantity":    0,
            "trade_value": 0.0,
            "size_pct":    0.0,
            "method":      "none",
            "reasoning":   reason,
        }