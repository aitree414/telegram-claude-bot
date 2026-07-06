"""Value Hunter strategy — buys heavily discounted outcomes on active markets.

Core thesis
-----------
Markets occasionally overreact. When YES is priced < $0.20 or NO < $0.15
on a reasonably liquid market, the true probability is often higher —
taking the contrarian position offers positive expected value.

Three filters:
  1. Minimum volume ($1K) — avoid junk / illiquid markets
  2. Extreme discount threshold — YES < $0.20 or NO < $0.15
  3. Confidence scales with how deep the discount is
"""

from __future__ import annotations

import logging
from typing import Optional

from bot.polymarket_clob import MarketData
from .polymarket_base import BaseStrategy, StrategyResult, TradeSignal

logger = logging.getLogger(__name__)

# Price thresholds
MAX_YES_PRICE = 0.20  # buy YES when cheaper than this
MAX_NO_PRICE = 0.15   # buy NO when cheaper than this

# Market quality
MIN_VOLUME = 1_000

# Position limits
MAX_PER_MARKET = 300  # tokens
MIN_PER_TRADE = 10    # tokens


class ValueHunterStrategy(BaseStrategy):
    """Buy heavily discounted outcomes on liquid markets.

    Parameters
    ----------
    max_yes_price : float
        Max YES price to trigger a buy (default 0.20).
    max_no_price : float
        Max NO price to trigger a buy (default 0.15).
    min_volume : float
        Minimum market volume (default $1K).
    max_per_market : int
        Max tokens per market (default 300).
    """

    def __init__(
        self,
        max_yes_price: float = MAX_YES_PRICE,
        max_no_price: float = MAX_NO_PRICE,
        min_volume: float = MIN_VOLUME,
        max_per_market: int = MAX_PER_MARKET,
    ):
        super().__init__(name="ValueHunter")
        self.max_yes_price = max_yes_price
        self.max_no_price = max_no_price
        self.min_volume = min_volume
        self.max_per_market = max_per_market

    def run(self, markets: list[MarketData]) -> StrategyResult:
        """Scan markets for deeply discounted outcomes.

        Parameters
        ----------
        markets : list[MarketData]
            Active binary markets from the Gamma API.

        Returns
        -------
        StrategyResult with trade signals.
        """
        signals: list[TradeSignal] = []
        skipped = {"low_volume": 0, "no_discount": 0}

        for market in markets:
            if market.volume < self.min_volume:
                skipped["low_volume"] += 1
                continue

            if len(market.outcomes) < 2 or len(market.token_ids) < 2:
                skipped["no_discount"] += 1
                continue

            yes_price = market.outcome_prices[0]
            no_price = market.outcome_prices[1]

            # Determine which outcome (if any) is at a deep discount
            if yes_price <= self.max_yes_price and no_price <= self.max_no_price:
                # Both are cheap — skip, too ambiguous
                skipped["no_discount"] += 1
                continue

            if yes_price <= self.max_yes_price:
                # YES is deeply discounted — market is bearish, we go long
                threshold = self.max_yes_price
                price = yes_price
                token_id = market.token_ids[0]
                outcome = market.outcomes[0]
                side = "BUY"
                reason_prefix = "YES deeply discounted"
            elif no_price <= self.max_no_price:
                # NO is deeply discounted — market is bullish, we go contrarian
                threshold = self.max_no_price
                price = no_price
                token_id = market.token_ids[1]
                outcome = market.outcomes[1]
                side = "BUY"
                reason_prefix = "NO deeply discounted"
            else:
                skipped["no_discount"] += 1
                continue

            # Confidence: how deep is the discount?
            discount = (threshold - price) / threshold  # 0.0 to 1.0
            confidence = min(1.0, discount * 1.5)  # 67% discount = 100% confidence

            # Position sizing
            size = min(self.max_per_market, int(200 * confidence))
            size = max(size, MIN_PER_TRADE)

            # Expected value: rough estimate = threshold - price
            # (conservative: assumes true value is at our threshold)
            ev_per_token = threshold - price

            signals.append(TradeSignal(
                market_question=market.question,
                market_slug=market.slug,
                condition_id=market.condition_id,
                token_id=token_id,
                side=side,
                outcome=outcome,
                price=price,
                size=size,
                expected_value=round(ev_per_token, 4),
                confidence=round(confidence, 2),
                strategy=self.name,
                reason=(
                    f"{reason_prefix}: {outcome} @ ${price:.4f} "
                    f"(discount={(1-price/threshold)*100:.0f}%, "
                    f"vol=${market.volume:,.0f})"
                ),
            ))

        result = StrategyResult(signals, metadata={
            "scanned": len(markets),
            "signals": len(signals),
            "skipped": skipped,
        })

        logger.info(
            f"ValueHunter scanned {len(markets)} markets → "
            f"{len(signals)} signals "
            f"(skipped: vol={skipped['low_volume']}, "
            f"nodis={skipped['no_discount']})"
        )
        return result
