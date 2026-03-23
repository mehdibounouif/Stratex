"""
sector exposure, and diversification measures.

Author: Kawtar (Risk Manager)
Compatible with: portfolio_tracker.py

Features:
- Sector breakdown and concentration analysis
- Volatility and beta calculations
- Sharpe ratio and risk-adjusted returns
- Diversification metrics (Herfindahl index)
- Correlation analysis
- Value at Risk (VaR)
- Maximum drawdown tracking
"""

import pandas as pd
import numpy as np
from decimal import Decimal
from datetime import datetime, timedelta
from collections import defaultdict
from logger import  get_logger
import yfinance as yf
import math

logger = get_logger('risk.portfolio.portfolio_calculator')

class PortfolioCalculator:
    """
    Calculate comprehensive portfolio metrics and risk measures.
    
    Responsibilities
    ----------------
    - Portfolio risk analytics
    - Sector exposure analysis
    - Concentration metrics
    - Performance ratios
    - Drawdown and tail-risk analysis
    """
    HHI_HIGH   = Decimal("0.25")
    HHI_MEDIUM = Decimal("0.15")

    def __init__(self, tracker=None, data_access=None):
        """
        Initialize Portfolio Calculator.

        Parameters
        ----------
        tracker : PositionTracker, optional
            Portfolio tracker instance providing positions,
            prices, and historical portfolio data.
        data_access : DataEngineer, optional
            Data access singleton for fetching price history through
            the cache layer. If None, falls back to direct yfinance.
        """
        if tracker is None:
            try:
                from risk.portfolio.portfolio_tracker import position_tracker
                tracker = position_tracker
            except ImportError as exc:
                logger.error("Failed to import default position_tracker")
                raise
        if not hasattr(tracker, "__dict__") and not hasattr(tracker, "__slots__"):
            logger.error(f"Invalid tracker type: {type(tracker)}")
            raise TypeError(f"tracker must be a class instance, got {type(tracker).__name__}")
        required_attrs = ("positions", "get_portfolio_value", "_normalize_ticker")
        for attr in required_attrs:
            if not hasattr(tracker, attr):
                logger.error(f"Tracker missing required attribute: '{attr}'")
                raise AttributeError(f"Tracker must implement '{attr}'")

            # having the attribute exist is not enough if it's just a plain value
            if attr == "get_portfolio_value" and not callable(getattr(tracker, attr)):
                logger.error("'get_portfolio_value' exists but is not callable")
                raise AttributeError("'get_portfolio_value' must be a callable method")
        if not isinstance(tracker.positions, (list, tuple, set)):
            logger.error(f"'positions' must be iterable, got {type(tracker.positions).__name__}")
            raise TypeError(
                f"'positions' must be an iterable collection, "
                f"got {type(tracker.positions).__name__}"
                )
        self.tracker = tracker

        # Data access — prefer injected instance, fall back to singleton, then raw yfinance
        if data_access is not None:
            self._data_access = data_access
        else:
            try:
                from data.data_engineer import data_access as _da
                self._data_access = _da
                logger.debug("PortfolioCalculator using data_engineer singleton for price fetching")
            except Exception:
                self._data_access = None
                logger.warning("data_engineer unavailable — portfolio calculator will use direct yfinance")

        try:
            self.sector_map = self._load_sector_map()
        except Exception as exc:
            logger.warning(f"Sector map failed to load, using empty map: {exc}")
            self.sector_map = {}
        logger.info("PortfolioCalculator initialized successfully")

    # =========================================================================
    # SECTOR ANALYSIS
    # =========================================================================
    def get_sector_breakdown(self):
        """
        Calculate sector exposure as percentage of portfolio.
        
        Returns
        -------
        dict
            Mapping of sector → portfolio weight.
        
        Description
        -----------
        - Maps each ticker to its sector
        - Aggregates position market values
        - Converts sector totals into percentages
        - Sorts sectors by exposure
        
        Use Cases
        ---------
        - Identify sector allocation
        - Detect overexposure to one industry
        """
        logger.info("Starting sector breakdown calculation.")
        try:
            if not self.tracker.positions:
                logger.warning("No positions found in tracker.")
                return {}

            # defaultdict removes the repeated Decimal("0") construction on every cache miss
            sector_values = defaultdict(lambda: Decimal("0"))

            for position in self.tracker.positions:
                if not position.quantity or position.quantity <= 0:
                    logger.warning(f"Skipping {position.ticker} — invalid quantity: {position.quantity}")
                    continue
                if not position.current_price or position.current_price <= 0:
                    logger.warning(f"Skipping {position.ticker} — invalid price: {position.current_price}")
                    continue

                try:
                    market_value = Decimal(str(position.quantity)) * Decimal(str(position.current_price))
                except (TypeError, ValueError) as exc:
                    logger.warning(f"Could not compute market value for {position.ticker}: {exc}")
                    continue

                sector = self._get_sector(position.ticker)
                sector_values[sector] += market_value
                logger.info(f"{position.ticker} | sector={sector} | market_value={market_value}")

            if not sector_values:
                logger.warning("No valid positions produced sector values.")
                return {}

            total = self.tracker.get_portfolio_value()
            if total <= 0:
                logger.warning("Portfolio total is zero or negative — cannot compute weights.")
                return {}

            sector_weights = {
                sector: round(value / total, 6)
                for sector, value in sector_values.items()
            }

            weight_sum = sum(sector_weights.values())

            try:
                if abs(weight_sum - Decimal("1.0")) > Decimal("0.01"):
                    logger.warning(
                        f"Sector weights sum to {weight_sum} — possible mismatch "
                        "between positions and portfolio value."
                    )
            except TypeError:
                logger.error(
                    f"Weight sum type mismatch — expected Decimal, got {type(weight_sum).__name__}"
                )
                return {}

            sector_weights = dict(
                sorted(sector_weights.items(), key=lambda x: x[1], reverse=True)
            )

            logger.info(f"Sector breakdown complete — {len(sector_weights)} sectors found.")
            return sector_weights

        except Exception as exc:
            logger.error(f"Sector breakdown failed: {exc}", exc_info=True)
            return {}

    def get_sector_concentration(self, sector_weights=None):
        """
        Measure sector concentration risk using HHI.
        
        Returns
        -------
        dict
            {
                'hhi': float,
                'equivalent_sectors': float,
                'risk_level': str
            }
        
        Description
        -----------
        - Uses Herfindahl-Hirschman Index
        - Squares sector weights and sums them
        - Estimates diversification level
        
        Interpretation
        --------------
        Low HHI   → diversified  
        High HHI  → concentrated risk
        """
        logger.info("Calculating sector concentration (HHI).")
        try:
            if sector_weights is None:
                sector_weights = self.get_sector_breakdown()

            if not sector_weights:
                logger.warning("No sector weights available — cannot compute HHI.")
                return {}

            weights = list(sector_weights.values())

            invalid = [w for w in weights if not isinstance(w, (int, float, Decimal)) or w < 0]
            if invalid:
                logger.error(f"Invalid weights detected: {invalid}")
                return {}

            weight_sum = sum(weights)
            if abs(weight_sum - Decimal("1.0")) > Decimal("0.01"):
                logger.warning(
                    f"Weights sum to {weight_sum:.6f} — HHI may be unreliable."
                )

            logger.debug(f"HHI input weights: {dict(zip(sector_weights.keys(), weights))}")

            hhi = round(sum(w ** 2 for w in weights), 6)

            if not (Decimal("0") < hhi <= Decimal("1.0")):
                logger.error(f"HHI out of valid range [0, 1]: {hhi}")
                return {}

            equivalent_sectors = round(Decimal("1") / hhi, 4)

            if hhi >= self.HHI_HIGH:
                risk_level = "HIGH"
            elif hhi >= self.HHI_MEDIUM:
                risk_level = "MEDIUM"
            else:
                risk_level = "LOW"

            result = {
                "hhi"                : hhi,
                "equivalent_sectors" : equivalent_sectors,
                "risk_level"         : risk_level,
            }

            logger.info(
                f"Sector concentration — HHI={hhi}, "
                f"equivalent_sectors={equivalent_sectors}, "
                f"risk_level={risk_level}"
            )
            return result

        except Exception as exc:
            logger.error(f"Sector concentration calculation failed: {exc}", exc_info=True)
            return {}

    def _get_sector(self, ticker):
        """
        Resolve ticker → sector mapping.

        Parameters
        ----------
        ticker : str
            Stock symbol

        Returns
        -------
        str
            Sector name, or 'Other' if ticker unknown or lookup fails.
        """
        ticker = self.tracker._normalize_ticker(ticker)
        if ticker in self.sector_map:
            return self.sector_map[ticker]

        try:
            # Try data_access first if available (it may cache sector info)
            info = {}
            if self._data_access is not None and hasattr(self._data_access, 'get_fundamentals'):
                try:
                    fundamentals = self._data_access.get_fundamentals(ticker)
                    if fundamentals and isinstance(fundamentals, dict):
                        info = fundamentals
                except Exception:
                    pass

            # Fall back to direct yfinance if data_access didn't provide sector
            if not info.get('sector'):
                logger.info("sector not found in map sectors, try yf...\n")
                stock  = yf.Ticker(ticker)
                info   = stock.info or {}

            sector = info.get("sector")

            if sector and isinstance(sector, str) and sector.strip():
                sector = sector.strip()
                self.sector_map[ticker] = sector
                logger.debug(f"Resolved {ticker} → sector: {sector}")
                return sector
            else:
                logger.warning(f"No sector found for {ticker} — defaulting to 'Other'")

        except Exception as exc:
            logger.warning(f"yfinance lookup failed for {ticker}: {exc}")

        self.sector_map[ticker] = "Other"
        return "Other"

    def _load_sector_map(self):
        """
        Load sector classification mapping.
        
        Returns
        -------
        dict
            {ticker: sector}
        
        Description
        -----------
        - Provides sector lookup table
        - Can be replaced by API or database source
        """
        logger.info("Loading sector classification map (GICS standard).")

        sector_map = {
            # Information Technology
            "AAPL":  "Information Technology",
            "MSFT":  "Information Technology",
            "GOOGL": "Communication Services",
            "NVDA":  "Information Technology",

            # Financials
            "JPM": "Financials",
            "BAC": "Financials",
            "GS":  "Financials",

            # Health Care
            "JNJ": "Health Care",
            "PFE": "Health Care",
            "MRK": "Health Care",

            # Consumer Discretionary
            "AMZN": "Consumer Discretionary",
            "TSLA": "Consumer Discretionary",
            "HD":   "Consumer Discretionary",

            # Consumer Staples
            "PG":  "Consumer Staples",
            "KO":  "Consumer Staples",
            "PEP": "Consumer Staples",

            # Energy
            "XOM": "Energy",
            "CVX": "Energy",

            # Industrials
            "BA":  "Industrials",
            "CAT": "Industrials",

            # Materials
            "LIN": "Materials",
            "APD": "Materials",

            # Utilities
            "NEE": "Utilities",
            "DUK": "Utilities",

            # Real Estate
            "AMT": "Real Estate",
            "PLD": "Real Estate",
        }

        logger.info(f"Loaded sector map with {len(sector_map)} tickers.")
        return sector_map

    # =========================================================================
    # POSITION ANALYSIS
    # =========================================================================
    def get_position_weights(self):
        """
        Calculate weight of each portfolio position.
        
        Returns
        -------
        dict
            {ticker: portfolio_weight}
        
        Description
        -----------
        - Uses market value of each position
        - Normalizes by total portfolio value
        - Sorted descending by weight
        """
        logger.info("Calculating position weights.")
        try:
            if not self.tracker.positions:
                logger.warning("No positions found in tracker.")
                return {}

            total = self.tracker.get_portfolio_value()
            if total <= 0:
                logger.warning("Portfolio total is zero or negative — cannot compute weights.")
                return {}

            position_weights = {}

            for position in self.tracker.positions:
                if not position.quantity or position.quantity <= 0:
                    logger.warning(f"Skipping {position.ticker} — invalid quantity: {position.quantity}")
                    continue
                if not position.current_price or position.current_price <= 0:
                    logger.warning(f"Skipping {position.ticker} — invalid price: {position.current_price}")
                    continue

                try:
                    market_value = Decimal(str(position.quantity)) * Decimal(str(position.current_price))
                except (TypeError, ValueError) as exc:
                    logger.warning(f"Could not compute market value for {position.ticker}: {exc}")
                    continue

                weight = round(market_value / total, 6)
                position_weights[position.ticker] = weight
                logger.info(f"{position.ticker} | market_value={market_value} | weight={weight}")

            if not position_weights:
                logger.warning("No valid positions produced weights.")
                return {}

            position_weights = dict(
                sorted(position_weights.items(), key=lambda x: x[1], reverse=True)
            )

            logger.info(f"Position weights complete — {len(position_weights)} positions.")
            return position_weights

        except Exception as exc:
            logger.error(f"Position weights calculation failed: {exc}", exc_info=True)
            return {}

    def get_largest_position(self, position_weights=None):
        """
        Identify largest holding by portfolio weight.
        
        Returns
        -------
        tuple
            (ticker, weight, market_value)
        
        Description
        -----------
        - Computes market value per position
        - Compares against total portfolio value
        - Returns dominant holding
        """
        logger.info("Identifying largest position.")
        try:
            if position_weights is None:
                position_weights = self.get_position_weights()

            if not position_weights:
                logger.warning("No position weights available — cannot identify largest position.")
                return None

            ticker = next(iter(position_weights))
            weight = position_weights[ticker]

            # Find the position object to get quantity and current_price
            position = next(
                (p for p in self.tracker.positions if p.ticker == ticker),
                None
            )

            if position is None:
                logger.error(f"Ticker '{ticker}' found in weights but missing from tracker positions.")
                return None

            try:
                market_value = Decimal(str(position.quantity)) * Decimal(str(position.current_price))
            except (TypeError, ValueError) as exc:
                logger.error(f"Could not compute market value for {ticker}: {exc}")
                return None

            result = (ticker, weight, market_value)

            logger.info(
                f"Largest position — ticker={ticker}, "
                f"weight={weight}, market_value={market_value}"
            )
            return result

        except Exception as exc:
            logger.error(f"Largest position calculation failed: {exc}", exc_info=True)
            return None

    def get_concentration_risk(self, position_weights=None):
        """
        Analyze position concentration risk.
        
        Returns
        -------
        dict
            {
                'top_5_weight': float,
                'top_10_weight': float,
                'hhi': float,
                'num_positions': int,
                'risk_level': str
            }
        
        Description
        -----------
        - Measures dominance of largest holdings
        - Calculates portfolio HHI
        - Classifies diversification risk
        """
        logger.info("Calculating position concentration risk.")
        try:
            if position_weights is None:
                position_weights = self.get_position_weights()

            if not position_weights:
                logger.warning("No position weights available — cannot compute concentration risk.")
                return {}

            # Weights are already sorted descending — extract values directly
            weights = list(position_weights.values())
            num_positions = len(weights)

            # Slice top 5 and top 10 — if fewer positions exist, sum all of them
            top_5_weight  = round(sum(weights[:5]),  6)
            top_10_weight = round(sum(weights[:10]), 6)

            # Position-level HHI — per ticker, not per sector
            hhi = round(sum(w ** 2 for w in weights), 6)

            if not (Decimal("0") < hhi <= Decimal("1.0")):
                logger.error(f"HHI out of valid range [0, 1]: {hhi}")
                return {}

            # Same thresholds as sector HHI — interpreted on the same scale
            if hhi >= self.HHI_HIGH:
                risk_level = "HIGH"
            elif hhi >= self.HHI_MEDIUM:
                risk_level = "MEDIUM"
            else:
                risk_level = "LOW"

            result = {
                "top_5_weight"  : top_5_weight,
                "top_10_weight" : top_10_weight,
                "hhi"           : hhi,
                "num_positions" : num_positions,
                "risk_level"    : risk_level,
            }

            logger.info(
                f"Concentration risk — top_5={top_5_weight}, top_10={top_10_weight}, "
                f"HHI={hhi}, positions={num_positions}, risk={risk_level}"
            )
            return result

        except Exception as exc:
            logger.error(f"Concentration risk calculation failed: {exc}", exc_info=True)
            return {}

    # =========================================================================
    # RISK METRICS
    # =========================================================================
    def _fetch_price_history(self, tickers, position_weights, period="252d"):
        """
        Fetch and validate historical price data from yfinance.

        Parameters
        ----------
        tickers : list
            List of ticker symbols.
        position_weights : dict
            {ticker: Decimal weight} — used to renormalize if tickers are dropped.
        period : str
            yfinance period string e.g. '252d', '1y'.

        Returns
        -------
        tuple
            (prices DataFrame, tickers list, weights list)
            All Decimal weights.
            Returns (None, None, None) on any failure.
        """
        try:
            # ── Prefer data_access cache layer ────────────────────
            if self._data_access is not None:
                all_prices = {}
                missing_tickers = []
                for t in tickers:
                    try:
                        # Convert yfinance period string to days integer
                        period_days = 252 if '1y' in period else int(''.join(filter(str.isdigit, period)) or 252)
                        df = self._data_access.get_price_history(t, days=period_days)
                        if df is not None and not df.empty and 'Close' in df.columns:
                            all_prices[t] = df['Close']
                        else:
                            missing_tickers.append(t)
                    except Exception:
                        missing_tickers.append(t)

                if missing_tickers:
                    logger.warning(f"No price data via cache for: {missing_tickers}")

                valid_tickers = [t for t in tickers if t in all_prices]
                if not valid_tickers:
                    logger.error("No valid price data from cache for any ticker.")
                    return None, None, None

                prices = pd.DataFrame(all_prices)
                prices = prices.dropna(axis=1, how='all')

            else:
                # ── Fallback: direct yfinance (no cache) ──────────
                logger.debug("Falling back to direct yfinance download (no cache available)")
                raw = yf.download(tickers, period=period, auto_adjust=True, progress=False)
                if isinstance(raw.columns, pd.MultiIndex):
                    prices = raw["Close"]
                else:
                    prices = raw[["Close"]]
                    prices.columns = tickers
                if prices.empty:
                    logger.warning("yfinance returned empty price data.")
                    return None, None, None
                prices = prices.dropna(axis=1, how="all")

            # Rebuild tickers list and renormalize weights after any drops
            valid_tickers = [t for t in tickers if t in prices.columns]
            missing = [t for t in tickers if t not in prices.columns]
            if missing:
                logger.warning(f"Missing price data for: {missing} — excluding.")
            if not valid_tickers:
                logger.error("No valid price data returned for any ticker.")
                return None, None, None

            total   = sum(position_weights[t] for t in valid_tickers)
            weights = [position_weights[t] / total for t in valid_tickers]

            return prices[valid_tickers], valid_tickers, weights

        except Exception as exc:
            logger.error(f"Price history fetch failed: {exc}", exc_info=True)
            return None, None, None

    def _portfolio_returns(self, prices, tickers, weights):
        """
        Convert price DataFrame to Decimal returns and compute weighted portfolio returns.

        Parameters
        ----------
        prices : pd.DataFrame
            Historical closing prices.
        tickers : list
            Ticker symbols matching weights order.
        weights : list
            Decimal weights corresponding to tickers.

        Returns
        -------
        pd.Series or None
            Daily Decimal portfolio returns. None on failure.
        """
        try:
            returns = prices[tickers].pct_change(fill_method=None).dropna()

            if returns.empty:
                logger.warning("Not enough price history to compute returns.")
                return None

            if len(returns) < 20:
                logger.warning(
                    f"Only {len(returns)} return observations — results may be unreliable."
                )

            # convert every cell to Decimal via str() — avoids float precision errors
            decimal_returns = returns.apply(
                lambda col: col.map(lambda x: Decimal(str(x)))
            )

            # weighted sum per day — one Decimal portfolio return per trading day
            #row["AAPL"] = 0.01
            #weights[0]  = 0.6
            portfolio_returns = decimal_returns.apply(
                lambda row: sum(row[t] * weights[i] for i, t in enumerate(tickers)),
                axis=1
            )

            return portfolio_returns

        except Exception as exc:
            logger.error(f"Portfolio returns computation failed: {exc}", exc_info=True)
            return None

    def calculate_portfolio_volatility(self, days=252):
            """
            Compute annualized portfolio volatility.
            
            Parameters
            ----------
            days : int
                Historical lookback window.
            
            Returns
            -------
            Decimal
                Annualized standard deviation of returns.
            
            Methodology
            -----------
            - Fetch historical prices
            - Compute daily returns
            - Weight by position allocation
            - Annualize via √252
            """
            logger.info(f"Calculating portfolio volatility over {days} days.")
            try:
                if not isinstance(days, int) or days <= 0:
                    logger.error(f"days must be a positive integer, got {days}")
                    return None

                position_weights = self.get_position_weights()
                if not position_weights:
                    logger.warning("No position weights available — cannot compute volatility.")
                    return None

                tickers = list(position_weights.keys())

                prices, tickers, weights = self._fetch_price_history(
                    tickers, position_weights, period=f"{days}d"
                )
                if prices is None:
                    return None

                portfolio_returns = self._portfolio_returns(prices, tickers, weights)
                if portfolio_returns is None:
                    return None

                # average daily return
                n                = Decimal(str(len(portfolio_returns)))
                avg_daily_return = sum(portfolio_returns) / n

                #How much returns move around their average.
                #Average squared distance from the mean
                squared_deviations = [(r - avg_daily_return) ** 2 for r in portfolio_returns]
                variance           = sum(squared_deviations) / n

                # daily volatility = square root of variance
                daily_vol = variance.sqrt()

                if daily_vol == Decimal("0"):
                    logger.warning("Daily volatility is zero — check price data.")
                    return None

                # annualize — scale by √252
                annual_vol = daily_vol * Decimal(str(np.sqrt(252)))

                logger.info(f"Portfolio volatility — daily={daily_vol:.6f}, annualized={annual_vol:.6f}")
                return annual_vol

            except Exception as exc:
                logger.error(f"Portfolio volatility calculation failed: {exc}", exc_info=True)
                return None
                    

    def calculate_sharpe_ratio(self, risk_free_rate=0.04):
        """
        Calculate risk-adjusted return (Sharpe ratio).
        
        Parameters
        ----------
        risk_free_rate : float
            Annual risk-free benchmark rate.
        
        Returns
        -------
        float
            Sharpe ratio.
        
        Formula
        -------
        (Portfolio Return − Risk-Free Rate) / Volatility
        """
        logger.info(f"Calculating Sharpe ratio with risk_free_rate={risk_free_rate}.")
        try:
            if not isinstance(risk_free_rate, (int, float, Decimal)):
                logger.error("risk_free_rate must be numeric.")
                return None

            if not (0 <= float(risk_free_rate) <= 1):
                logger.error("risk_free_rate must be between 0 and 1.")
                return None

            risk_free_rate = Decimal(str(risk_free_rate))

            position_weights = self.get_position_weights()
            if not position_weights:
                logger.warning("No positions available.")
                return None

            tickers = list(position_weights.keys())

            prices, tickers, weights = self._fetch_price_history(
                tickers, position_weights, period="252d"
            )
            if prices is None:
                return None

            portfolio_returns = self._portfolio_returns(prices, tickers, weights)
            if portfolio_returns is None or len(portfolio_returns) < 20:
                logger.warning("Insufficient return data.")
                return None

            # Annual Return
            n = Decimal(str(len(portfolio_returns)))
            avg_daily_return = sum(portfolio_returns) / n
            annual_return = avg_daily_return * Decimal("252")

            annual_vol = self.calculate_portfolio_volatility(days=252)
            if annual_vol is None or annual_vol == Decimal("0"):
                logger.warning("Cannot compute Sharpe without volatility.")
                return None
            
            sharpe = (annual_return - risk_free_rate) / annual_vol
            sharpe = round(sharpe, 4)

            logger.info(
                f"Sharpe ratio — annual_return={annual_return:.4f}, "
                f"annual_vol={annual_vol:.4f}, sharpe={sharpe}"
            )

            return sharpe

        except Exception as exc:
            logger.error(f"Sharpe ratio calculation failed: {exc}", exc_info=True)
            return None

    def calculate_var(self, confidence=0.95, days=10):
        """
        Estimate Value at Risk (VaR).
        
        Parameters
        ----------
        confidence : float
            Confidence level.
        
        days : int
            Holding period horizon.
        
        Returns
        -------
        dict
            {
                'var_dollar': Decimal,
                'var_percent': Decimal,
                'confidence': Decimal
            }
        
        Description
        -----------
        - Uses empirical historical VaR from actual return distribution
        - Derives cutoff directly from sorted portfolio returns
        - Scales to time horizon via √(days/252)
        """
        logger.info(f"Calculating VaR — confidence={confidence}, days={days}.")
        try:
            # validate confidence level
            if not isinstance(confidence, (int, float, Decimal)):
                logger.error(f"confidence must be a number, got {type(confidence).__name__}")
                return {}
            if not (Decimal("0") < Decimal(str(confidence)) < Decimal("1")):
                logger.error(f"confidence must be between 0 and 1, got {confidence}")
                return {}

            # validate holding period
            if not isinstance(days, int) or days <= 0:
                logger.error(f"days must be a positive integer, got {days}")
                return {}

            # convert to Decimal immediately — all calculations stay Decimal
            confidence = Decimal(str(confidence))
            days       = Decimal(str(days))

            # get portfolio value — needed for dollar VaR
            portfolio_value = self.tracker.get_portfolio_value()
            if not portfolio_value or portfolio_value <= 0:
                logger.warning("Portfolio value is zero or negative — cannot compute VaR.")
                return {}

            # reuse volatility — already built, no duplication

            # get position weights
            position_weights = self.get_position_weights()
            if not position_weights:
                logger.warning("No position weights — cannot compute VaR.")
                return {}

            tickers = list(position_weights.keys())

            prices, tickers, weights = self._fetch_price_history(
                tickers, position_weights, period="252d"
            )
            if prices is None:
                return {}

            portfolio_returns = self._portfolio_returns(prices, tickers, weights)
            if portfolio_returns is None or len(portfolio_returns) < 20:
                logger.warning("Insufficient return data for VaR.")
                return {}

            # sort worst to best — empirical approach, no scipy or z-score formula needed
            # uses your actual return history instead of assuming a bell curve
            sorted_returns = sorted(portfolio_returns)

            # find the cutoff index — worst (1 - confidence)% of days
            # e.g. 95% confidence, 252 days → index 12 → 13th worst day
            index = math.ceil(float(Decimal("1") - confidence) * len(sorted_returns))

            if index <= 0 or index >= len(sorted_returns):
                logger.warning(
                    f"VaR index out of range: {index} — "
                    f"insufficient data for confidence={confidence}."
                )
                return {}

            # the return at the cutoff — our empirical worst-case threshold
            cutoff_return = sorted_returns[index]

            logger.debug(
                f"VaR cutoff — index={index}, "
                f"cutoff_return={cutoff_return}, "
                f"total_observations={len(sorted_returns)}"
            )

            # scale from one-day to N-day VaR using √(days/252)
            # same square root of time rule as annualization but in reverse
            scaling_factor = (days / Decimal("252")).sqrt()

            # abs() — VaR is always expressed as a positive loss
            var_percent = abs(cutoff_return) * scaling_factor
            var_dollar  = var_percent * portfolio_value

            result = {
                "var_dollar"  : round(var_dollar,  2),
                "var_percent" : round(var_percent,  6),
                "confidence"  : confidence,
            }

            logger.info(
                f"VaR complete — var_dollar={var_dollar:.2f}, "
                f"var_percent={var_percent:.4f}, "
                f"confidence={confidence}"
            )
            return result

        except Exception as exc:
            logger.error(f"VaR calculation failed: {exc}", exc_info=True)
            return {}

    def calculate_max_drawdown(self):
        """
        Find the worst peak-to-trough drop in portfolio value over the last 252 days.
        Returns a dict with the drawdown %, and the dates/values of the peak and trough.
        """
        logger.info("Calculating maximum drawdown.")
        try:
            # --- 1. Get holdings and price history ---
            position_weights = self.get_position_weights()
            if not position_weights:
                logger.warning("No position weights — cannot compute max drawdown.")
                return {}

            tickers = list(position_weights.keys())
            prices, tickers, weights = self._fetch_price_history(tickers, position_weights, period="252d")
            if prices is None:
                return {}

            # --- 2. Get current portfolio value ---
            portfolio_value = self.tracker.get_portfolio_value()
            if not portfolio_value or portfolio_value <= 0:
                logger.warning("Portfolio value is zero or negative.")
                return {}

            # --- 3. Build a daily portfolio value series using pure float arithmetic ---
            # Decimal inside a pandas object-dtype Series multiplied by Decimal or mixed
            # with float raises TypeError in Python 3.11+. No Decimal needed here.
            portfolio_value_float = float(portfolio_value)
            weights_float = [float(weights[i]) for i in range(len(tickers))]
            float_prices  = prices[tickers].astype(float)
            first_float   = float_prices.iloc[0]
            daily_values  = float_prices.apply(
                lambda row: sum(
                    (row[t] / first_float[t]) * weights_float[i]
                    for i, t in enumerate(tickers)), axis=1
                ) * portfolio_value_float
            # Restore DatetimeIndex — apply(axis=1) drops it to integer index
            daily_values.index = float_prices.index

            if daily_values.empty:
                return {}

            # --- 4. Walk through each day to find the worst drawdown ---
            # daily_values is now a plain float Series — no Decimal needed here.
            peak        = float(daily_values.iloc[0])
            peak_date   = daily_values.index[0]
            max_dd      = 0.0                    # worst drawdown seen (negative number)
            best_peak   = peak                   # peak that led to the worst drawdown
            best_peak_date   = peak_date
            trough_val  = peak
            trough_date = peak_date

            for date, value in daily_values.items():
                # Update the running peak if today is a new high
                if value > peak:
                    peak      = value
                    peak_date = date

                # Drawdown = how far we've fallen from the peak (will be 0 or negative)
                drawdown = (value - peak) / peak

                # Save if this is the deepest drop we've seen
                if drawdown < max_dd:
                    max_dd         = drawdown
                    best_peak      = peak
                    best_peak_date = peak_date
                    trough_val     = value
                    trough_date    = date

            # --- 5. Return results ---
            result = {
                "max_drawdown" : round(Decimal(str(max_dd)),     6),
                "peak_value"   : round(Decimal(str(best_peak)),  2),
                "trough_value" : round(Decimal(str(trough_val)), 2),
                "peak_date"    : str(best_peak_date.date()),
                "trough_date"  : str(trough_date.date()),
            }

            logger.info(f"Max drawdown: {max_dd:.4%} | Peak: {best_peak:.2f} on {best_peak_date} | Trough: {trough_val:.2f} on {trough_date}")
            return result

        except Exception as exc:
            logger.error(f"Max drawdown calculation failed: {exc}", exc_info=True)
            return {}
    # =========================================================================
    # COMPREHENSIVE REPORTING
    # =========================================================================

    def generate_risk_report(self):
        """
        Generate full portfolio risk report.
        
        Returns
        -------
        dict
            Aggregated analytics including:
            - Portfolio summary
            - Sector exposure
            - Concentration metrics
            - Risk statistics
        
        Purpose
        -------
        Provides single structured risk snapshot.
        """
        logger.info("Generating full portfolio risk report.")
        try:
            position_weights = self.get_position_weights()
            if not position_weights:
                logger.warning("No position weights — cannot generate risk report.")
                return {}

            
            sector_weights = self.get_sector_breakdown()

            # portfolio summary
            portfolio_value  = self.tracker.get_portfolio_value()
            num_positions    = len(position_weights)
            largest_position = self.get_largest_position(position_weights)

            sector_breakdown     = sector_weights
            sector_concentration = self.get_sector_concentration(sector_weights)

            concentration_risk = self.get_concentration_risk(position_weights)

            volatility   = self.calculate_portfolio_volatility()
            sharpe       = self.calculate_sharpe_ratio()
            var_95       = self.calculate_var(confidence=0.95, days=10)
            max_drawdown = self.calculate_max_drawdown()

            report = {
                "portfolio_summary": {
                    "portfolio_value"  : portfolio_value,
                    "num_positions"    : num_positions,
                    "largest_position" : largest_position,
                },
                "sector_analysis": {
                    "breakdown"     : sector_breakdown,
                    "concentration" : sector_concentration,
                },
                "position_analysis": {
                    "weights"            : position_weights,
                    "concentration_risk" : concentration_risk,
                },
                "risk_metrics": {
                    "annual_volatility" : volatility,
                    "sharpe_ratio"      : sharpe,
                    "var_95_10d"        : var_95,
                    "max_drawdown"      : max_drawdown,
                },
            }

            logger.info("Risk report generated successfully.")
            return report

        except Exception as exc:
            logger.error(f"Risk report generation failed: {exc}", exc_info=True)
            return {}

    def print_risk_report(self):
        """
        Display formatted portfolio risk report.
        
        Description
        -----------
        - Human-readable console output
        - Summarizes key analytics
        - Suitable for monitoring dashboards
        """
        logger.info("Printing portfolio risk report.")
        try:
            report = self.generate_risk_report()
            if not report:
                print("No report data available.")
                return

            summary      = report.get("portfolio_summary",  {})
            sectors      = report.get("sector_analysis",    {})
            positions    = report.get("position_analysis",  {})
            risk_metrics = report.get("risk_metrics",       {})

            largest = summary.get("largest_position")

            print("\n" + "=" * 60)
            print("         PORTFOLIO RISK REPORT")
            print("=" * 60)

            # portfolio summary
            print("\n[ PORTFOLIO SUMMARY ]")
            print(f"  Total Value       : {summary.get('portfolio_value')}")
            print(f"  Positions         : {summary.get('num_positions')}")
            if largest:
                print(f"  Largest Position  : {largest[0]} "
                      f"({float(largest[1]) * 100:.2f}% | {largest[2]})")

            # sector breakdown
            print("\n[ SECTOR EXPOSURE ]")
            for sector, weight in sectors.get("breakdown", {}).items():
                bar = "█" * int(float(weight) * 40)
                print(f"  {sector:<35} {float(weight) * 100:>6.2f}%  {bar}")

            # sector concentration
            conc = sectors.get("concentration", {})
            print(f"\n  Sector HHI        : {conc.get('hhi')}")
            print(f"  Equiv. Sectors    : {conc.get('equivalent_sectors')}")
            print(f"  Sector Risk       : {conc.get('risk_level')}")

            # position concentration
            pos_risk = positions.get("concentration_risk", {})
            print("\n[ POSITION CONCENTRATION ]")
            print(f"  Top 5 Weight      : {float(pos_risk.get('top_5_weight',  0)) * 100:.2f}%")
            print(f"  Top 10 Weight     : {float(pos_risk.get('top_10_weight', 0)) * 100:.2f}%")
            print(f"  Position HHI      : {pos_risk.get('hhi')}")
            print(f"  Position Risk     : {pos_risk.get('risk_level')}")

            # position weights
            print("\n[ POSITION WEIGHTS ]")
            for ticker, weight in positions.get("weights", {}).items():
                bar = "█" * int(float(weight) * 40)
                print(f"  {ticker:<10} {float(weight) * 100:>6.2f}%  {bar}")

            # risk metrics
            var = risk_metrics.get("var_95_10d", {})
            dd  = risk_metrics.get("max_drawdown", {})

            print("\n[ RISK METRICS ]")
            print(f"  Annual Volatility : {float(risk_metrics.get('annual_volatility', 0)) * 100:.2f}%")
            print(f"  Sharpe Ratio      : {risk_metrics.get('sharpe_ratio')}")
            print(f"  VaR 95% / 10d     : {var.get('var_dollar')} ({float(var.get('var_percent', 0)) * 100:.2f}%)")
            print(f"  Max Drawdown      : {float(dd.get('max_drawdown', 0)) * 100:.2f}%")
            print(f"  Peak Date         : {dd.get('peak_date')}")
            print(f"  Trough Date       : {dd.get('trough_date')}")

            print("\n" + "=" * 60 + "\n")

        except Exception as exc:
            logger.error(f"print_risk_report failed: {exc}", exc_info=True)
            print("Failed to print risk report — check logs.")


calculator = PortfolioCalculator()


if __name__ == "__main__":
    """
    Test and demonstrate portfolio calculator
    """
    from risk.portfolio.portfolio_tracker import PositionTracker

    logger.info("="*60)
    logger.info("TESTING PORTFOLIO CALCULATOR")
    logger.info("="*60)

    # Create test portfolio
    tracker = PositionTracker(initial_capital=90000)

    # Add some positions
    tracker.add_position('AAPL', 50, 180.0)
    tracker.add_position('MSFT', 30, 380.0)
    tracker.add_position('GOOGL', 20, 140.0)
    tracker.add_position('JPM', 40, 160.0)
    tracker.add_position('JNJ', 25, 160.0)

    # Update prices
    tracker.update_prices({
        'AAPL': 185.0,
        'MSFT': 390.0,
        'GOOGL': 145.0,
        'JPM': 165.0,
        'JNJ': 165.0
    })

    # Create calculator
    calc = PortfolioCalculator(tracker=tracker)

    # Test features
    logger.info("\n[TEST 1] Sector breakdown")
    sectors = calc.get_sector_breakdown()
    print(f"Sectors: {sectors}")

    logger.info("\n[TEST 2] Sector concentration")
    sector_conc = calc.get_sector_concentration()
    print(f"Sector HHI: {sector_conc}")
    
    logger.info("\n[TEST 3] Position concentration")
    pos_conc = calc.get_concentration_risk()
    print(f"Position risk: {pos_conc}")

    logger.info("\n[TEST 4] Risk metrics")
    var = calc.calculate_var()
    print(f"VaR: {var}")

    logger.info("\n[TEST 5] Full risk report")
    calc.print_risk_report()
    
    logger.info("\n✅ ALL TESTS COMPLETED!")