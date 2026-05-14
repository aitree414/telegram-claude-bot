"""Pair Cost Arbitrage strategy.

Core thesis
-----------
When YES price + NO price < $1.00, buying both outcomes guarantees
a risk-free profit:

  Profit = $1.00 - (YES_price + NO_price) per pair

This happens when the market is inefficient (orderbook spread,
temporary imbalance, or stale orders).

Example
-------
YES = $0.60, NO = $0.35  →  Sum = $0.95  →  Profit = $0.05/pair (5.26%)
"""

from __future__ import annotations

import logging
from typing import Optional

from bot.polymarket_clob import MarketData, Orderbook
from .polymarket_base import BaseStrategy, StrategyResult, TradeSignal

logger = logging.getLogger(__name__)

# Minimum arb spread to execute (after gas consideration)
MIN_PROFIT_PCT = 2.0  # percent (2% = $0.02 per $1.00 pair)

# Minimum market volume ($)
MIN_VOLUME = 10_000

# Max tokens per pair side
MAX_PER_SIDE = 200


class ArbResult(StrategyResult):
    """Arbitrage result with statistics."""
    @property
    def avg_spread(self) -> float:
        if not self.signals:
            return 0.0
        # Signals are paired (buy YES + buy NO), count as half
        pairs = len(self.signals) // 2
        if pairs == 0:
            return 0.0
        total_spread = 0.0
        for i in range(pairs):
            yes_sig = self.signals[i * 2]
            no_sig = self.signals[i * 2 + 1]
            total_spread += (1.0 - (yes_sig.price + no_sig.price)) * 100
        return total_spread / pairs

    @property
    def total_profit(self) -> float:
        """Estimated total profit in USD."""
        pairs = len(self.signals) // 2
        profit = 0.0
        for i in range(pairs):
            yes_sig = self.signals[i * 2]
            no_sig = self.signals[i * 2 + 1]
            spread = 1.0 - (yes_sig.price + no_sig.price)
            profit += spread * min(yes_sig.size, no_sig.size)
        return profit

    @property
    def pair_count(self) -> int:
        return len(self.signals) // 2


class PairCostArbStrategy(BaseStrategy):
    """Scan for YES+NO < $1.00 arbitrage opportunities.

    Parameters
    ----------
    min_profit_pct : float
        Minimum profit percentage to execute (default 2.0).
    min_volume : float
        Minimum market volume (default $10K).
    max_per_side : int
        Max tokens to buy per outcome (default 200).
    use_orderbook : bool
        Use CLOB orderbook for real prices (default True).
    """

    def __init__(
        self,
        min_profit_pct: float = MIN_PROFIT_PCT,
        min_volume: float = MIN_VOLUME,
        max_per_side: int = MAX_PER_SIDE,
        use_orderbook: bool = True,
        clob_client=None,
    ):
        super().__init__(name="PairCostArb")
        self.min_profit_pct = min_profit_pct
        self.min_volume = min_volume
        self.max_per_side = max_per_side
        self.use_orderbook = use_orderbook
        self.clob_client = clob_client

    def run(self, markets: list[MarketData]) -> ArbResult:
        """Scan for pair cost arbitrage opportunities.

        Parameters
        ----------
        markets : list[MarketData]
            Active binary markets.

        Returns
        -------
        ArbResult with paired trade signals.
        """
        signals: list[TradeSignal] = []
        skipped = {"low_volume": 0, "not_binary": 0, "below_threshold": 0, "orderbook": 0}
        total_scanned = len(markets)

        for market in markets:
            if market.volume < self.min_volume:
                skipped["low_volume"] += 1
                continue

            if len(market.outcomes) != 2 or len(market.token_ids) < 2:
                skipped["not_binary"] += 1
                continue

            yes_price, no_price = market.outcome_prices[0], market.outcome_prices[1]
            yes_token_id, no_token_id = market.token_ids[0], market.token_ids[1]

            # Use orderbook prices if available
            if self.use_orderbook and self.clob_client:
                yes_book = self.clob_client.get_orderbook(yes_token_id)
                no_book = self.clob_client.get_orderbook(no_token_id)

                yes_exec_price = yes_book.asks[0].price if yes_book.asks else yes_price
                no_exec_price = no_book.asks[0].price if no_book.asks else no_price
                yes_bid = yes_book.bids[0].price if yes_book.bids else yes_price
                no_bid = no_book.bids[0].price if no_book.bids else no_price

                # For arb: buy YES at ask, buy NO at ask; sell to bid after resolution
                # But we only care about buy cost for pair cost arbitrage
                buy_cost = yes_exec_price + no_exec_price
            else:
                buy_cost = yes_price + no_price
                yes_exec_price = yes_price
                no_exec_price = no_price

            spread_pct = (1.0 - buy_cost) * 100

            if spread_pct < self.min_profit_pct:
                skipped["below_threshold"] += 1
                continue

            # Position sizing: scale with spread confidence
            confidence = min(1.0, spread_pct / 10.0)  # 10% spread = 100% confidence
            size = min(self.max_per_side, int(100 * spread_pct / 5.0))
            size = max(size, 10)

            # Buy YES
            signals.append(TradeSignal(
                market_question=market.question,
                market_slug=market.slug,
                condition_id=market.condition_id,
                token_id=yes_token_id,
                side="BUY",
                outcome=market.outcomes[0],
                price=yes_exec_price,
                size=size,
                expected_value=min(yes_exec_price + spread_pct / 100, 1.0),
                confidence=round(confidence, 2),
                strategy=self.name,
                reason=f"Buy YES @ ${yes_exec_price:.4f} (leg of pair arb)",
            ))

            # Buy NO
            signals.append(TradeSignal(
                market_question=market.question,
                market_slug=market.slug,
                condition_id=market.condition_id,
                token_id=no_token_id,
                side="BUY",
                outcome=market.outcomes[1],
                price=no_exec_price,
                size=size,
                expected_value=min(no_exec_price + spread_pct / 100, 1.0),
                confidence=round(confidence, 2),
                strategy=self.name,
                reason=(
                    f"Pair arb: ({market.outcomes[0]}={yes_exec_price:.4f} + "
                    f"{market.outcomes[1]}={no_exec_price:.4f}) = "
                    f"${buy_cost:.4f}, profit ${(1-buy_cost):.4f}/token "
                    f"({spread_pct:.2f}%)"
                ),
            ))

        result = ArbResult(signals, metadata={
            "scanned": total_scanned,
            "pairs": len(signals) // 2,
            "skipped": skipped,
        })

        logger.info(
            f"PairCostArb scanned {total_scanned} markets → "
            f"{len(signals)//2} arb pairs "
            f"(skipped: vol={skipped['low_volume']}, "
            f"threshold={skipped['below_threshold']})"
        )
        return result
