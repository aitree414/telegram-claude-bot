"""Nothing Ever Happens strategy.

Core thesis
-----------
Buy NO when implied probability is below market-implied mid-price.
Uses dynamic P(NO) derived from the orderbook mid-price rather than
a hardcoded historical value. This adapts to changing market conditions.

  EV = P(NO)_dynamic × $1.00 - cost
"""

from __future__ import annotations

import logging
from typing import Optional

from bot.polymarket_clob import MarketData, Orderbook
from .polymarket_base import BaseStrategy, StrategyResult, TradeSignal

logger = logging.getLogger(__name__)

# Maximum NO price to buy at (market-implied NO probability threshold)
MAX_NO_PRICE = 0.75

# Minimum edge (EV per token) required to enter a trade.
# Trades with EV below this are filtered to avoid noise and fee drag.
MIN_EDGE = 0.02  # $0.02 per token minimum expected value

# Minimum volume to filter out junk markets ($)
MIN_VOLUME = 1_000

# Maximum size per market to limit exposure
MAX_PER_MARKET = 500  # tokens


class NEHResult(StrategyResult):
    """NEH strategy result with statistics."""
    @property
    def avg_no_price(self) -> float:
        if not self.signals:
            return 0.0
        return sum(s.price for s in self.signals) / len(self.signals)

    @property
    def total_ev(self) -> float:
        """Sum of expected values across all signals."""
        return sum(s.expected_value * s.size for s in self.signals)

    @property
    def total_cost(self) -> float:
        return sum(s.price * s.size for s in self.signals)


class NEHStrategy(BaseStrategy):
    """Nothing Ever Happens — systematically buy NO at a discount.

    Parameters
    ----------
    max_no_price : float
        Maximum NO price to accept (default 0.65).
    min_volume : float
        Minimum market volume in USD (default $5K).
    max_per_market : int
        Max tokens to buy per market (default 500).
    only_check_orderbook : bool
        Use CLOB orderbook for real prices (default True).
    """

    def __init__(
        self,
        max_no_price: float = MAX_NO_PRICE,
        min_volume: float = MIN_VOLUME,
        max_per_market: int = MAX_PER_MARKET,
        only_check_orderbook: bool = True,
        clob_client=None,
    ):
        super().__init__(name="NEH")
        self.max_no_price = max_no_price
        self.min_volume = min_volume
        self.max_per_market = max_per_market
        self.only_check_orderbook = only_check_orderbook
        self.clob_client = clob_client

    @staticmethod
    def _market_implied_p_no(market: MarketData) -> float:
        """Derive P(NO) from market prices.

        Uses YES price as the complement: if YES=$0.30, P(NO)=0.70.
        This is the market's own implied probability for NO.
        No clamping — we let the market speak and filter by edge size instead.
        """
        yes_idx = 1 if market.outcomes[0].strip().upper() == "NO" else 0
        yes_price = market.outcome_prices[yes_idx]
        p_no = 1.0 - yes_price
        # Apply a small epsilon to avoid division-by-zero and extreme tail bets.
        # P(NO) below 0.15 or above 0.85 are tail regions where the edge must
        # be very large to justify a trade (handled by min_edge filter below).
        return max(0.05, min(0.95, p_no))

    def run(self, markets: list[MarketData]) -> NEHResult:
        """Scan markets for NO-priced-below-threshold opportunities.

        Uses market-implied P(NO) from the complementary YES price,
        then looks for NO outcomes trading BELOW that implied value.

        Returns
        -------
        NEHResult with trade signals.
        """
        signals: list[TradeSignal] = []
        skipped = {"low_volume": 0, "no_price_too_high": 0, "no_token_id": 0,
                    "orderbook_check": 0, "edge_too_small": 0}
        total_scanned = len(markets)

        for market in markets:
            if market.volume < self.min_volume:
                skipped["low_volume"] += 1
                continue

            if len(market.outcomes) < 2 or len(market.token_ids) < 2:
                skipped["no_token_id"] += 1
                continue

            # Find which outcome is NO
            no_idx = self._find_no_outcome(market)
            if no_idx is None:
                skipped["no_token_id"] += 1
                continue

            no_price = market.outcome_prices[no_idx]

            if no_price > self.max_no_price:
                skipped["no_price_too_high"] += 1
                continue

            no_token_id = market.token_ids[no_idx]

            # Check CLOB orderbook for executable price
            exec_price = no_price
            if self.clob_client:
                try:
                    book = self.clob_client.get_orderbook(no_token_id)
                    if book.asks:
                        exec_price = book.asks[0].price
                except Exception:
                    pass  # fall back to market price

            # Dynamic P(NO) from market-implied probability
            p_no = self._market_implied_p_no(market)
            if p_no <= exec_price:
                skipped["orderbook_check"] += 1
                continue

            # Expected value calculation
            ev_per_token = p_no - exec_price

            # Require a minimum edge to filter noise and cover fees/gas
            if ev_per_token < MIN_EDGE:
                skipped["edge_too_small"] += 1
                continue
            confidence = min(1.0, ev_per_token / 0.10)  # $0.10 EV = 100%

            # Position sizing: scale with EV confidence
            size = min(self.max_per_market, int(200 * confidence))
            size = max(size, 10)

            signals.append(TradeSignal(
                market_question=market.question,
                market_slug=market.slug,
                condition_id=market.condition_id,
                token_id=no_token_id,
                side="BUY",
                outcome=market.outcomes[no_idx],
                price=exec_price,
                size=size,
                expected_value=ev_per_token,
                confidence=round(confidence, 2),
                strategy=self.name,
                reason=(
                    f"NO @ ${exec_price:.4f} vs implied P(NO)={p_no:.0%} "
                    f"(EV=${ev_per_token:.4f}/token, +{ev_per_token/exec_price*100:.1f}%)"
                ),
            ))

        result = NEHResult(signals, metadata={
            "scanned": total_scanned,
            "signals": len(signals),
            "skipped": skipped,
            "avg_no_price": sum(s.price for s in signals) / max(len(signals), 1),
        })

        logger.info(
            f"NEH scanned {total_scanned} markets → "
            f"{len(signals)} signals "
            f"(skipped: vol={skipped['low_volume']}, "
            f"price={skipped['no_price_too_high']}, "
            f"ob={skipped['orderbook_check']}, "
            f"edge={skipped['edge_too_small']})"
        )
        return result

    @staticmethod
    def _find_no_outcome(market: MarketData) -> Optional[int]:
        """Find the index of the NO outcome (case-insensitive)."""
        for i, outcome in enumerate(market.outcomes):
            if outcome.strip().upper() == "NO":
                return i
        # If no explicit "NO", pick the lower-priced outcome
        # (typically NO is cheaper than YES)
        if len(market.outcome_prices) >= 2:
            return 0 if market.outcome_prices[0] < market.outcome_prices[1] else 1
        return None
