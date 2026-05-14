"""Unified signal format shared across stocks and prediction markets.

Both ``auto_trader.py`` (stocks) and ``polymarket_trader.py``
produce ``Signal`` objects so that portfolio tracking, risk management,
and reporting can treat them uniformly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class MarketType(str, Enum):
    STOCK = "stock"
    POLYMARKET = "polymarket"
    CRYPTO = "crypto"


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Signal:
    """Normalised trading signal from any source.

    Both ``stock_analyzer.py`` and the Polymarket strategies produce
    this structure, enabling shared infrastructure (risk checks, P&L
    tracking, reporting).
    """
    # Core
    market: MarketType
    symbol: str                 # stock ticker or Polymarket slug
    action: Action
    price: float                # limit price or current price
    quantity: float             # shares (stocks) or tokens (Polymarket)

    # Attribution
    source: str                 # e.g. "value", "NEH", "consensus"
    strategy: str = ""          # e.g. "persona_debate", "nothing_ever_happens"
    confidence: float = 0.5     # 0-1

    # Polymarket-specific
    outcome: str = ""           # "Yes" / "No" (Polymarket only)
    token_id: str = ""          # Polymarket outcome token ID (Polymarket only)
    condition_id: str = ""      # Polymarket condition ID (Polymarket only)
    market_question: str = ""   # human-readable question

    # Metadata
    reason: str = ""
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    signal_id: str = ""         # set by SignalBook if registered

    @property
    def value_usd(self) -> float:
        return self.price * self.quantity

    @property
    def is_polymarket(self) -> bool:
        return self.market == MarketType.POLYMARKET

    @property
    def is_stock(self) -> bool:
        return self.market == MarketType.STOCK

    def to_short_str(self) -> str:
        return (
            f"{self.action.value} {self.symbol} "
            f"x{self.quantity:.0f} @ ${self.price:.4f}"
        )

    def to_dict(self) -> dict:
        return {
            "market": self.market.value,
            "symbol": self.symbol,
            "action": self.action.value,
            "price": self.price,
            "quantity": self.quantity,
            "source": self.source,
            "strategy": self.strategy,
            "confidence": self.confidence,
            "outcome": self.outcome,
            "reason": self.reason,
            "value_usd": self.value_usd,
            "generated_at": self.generated_at,
        }


# ── Adapter helpers ──────────────────────────────


def from_stock_analysis(analysis: dict) -> Optional[Signal]:
    """Convert an ``analyze_stock()`` result dict to a Signal."""
    rating = analysis.get("consensus_rating", "HOLD")
    if rating == "HOLD":
        return None  # HOLD is not an actionable signal

    return Signal(
        market=MarketType.STOCK,
        symbol=analysis.get("symbol", ""),
        action=Action.BUY if rating == "BUY" else Action.SELL,
        price=analysis.get("current", 0) or 0,
        quantity=0,  # caller must fill in position sizing
        source="consensus",
        strategy="persona_debate",
        confidence=analysis.get("confidence", 0.5),
        reason=analysis.get("summary", "")[:200],
    )


def from_polymarket_signal(trade_signal) -> Signal:
    """Convert a ``strategies.polymarket_base.TradeSignal`` to a unified Signal."""
    return Signal(
        market=MarketType.POLYMARKET,
        symbol=trade_signal.market_slug,
        action=Action.BUY if trade_signal.side.upper() == "BUY" else Action.SELL,
        price=trade_signal.price,
        quantity=trade_signal.size,
        source=trade_signal.strategy,
        strategy=trade_signal.strategy,
        confidence=trade_signal.confidence,
        outcome=trade_signal.outcome,
        token_id=trade_signal.token_id,
        condition_id=trade_signal.condition_id,
        market_question=trade_signal.market_question,
        reason=trade_signal.reason,
    )


# ── Signal registry (optional, for cross-system tracking) ──


class SignalBook:
    """In-memory registry of all signals generated in this session.

    Allows the risk manager, portfolio tracker, and reporting to
    query signals from both stock and Polymarket sources uniformly.
    """

    def __init__(self):
        self._signals: list[Signal] = []
        self._next_id = 1

    def register(self, signal: Signal) -> Signal:
        signal.signal_id = f"SIG-{self._next_id}"
        self._next_id += 1
        self._signals.append(signal)
        return signal

    def recent(self, n: int = 20) -> list[Signal]:
        return self._signals[-n:]

    def by_source(self, source: str) -> list[Signal]:
        return [s for s in self._signals if s.source == source]

    def by_market(self, market: MarketType) -> list[Signal]:
        return [s for s in self._signals if s.market == market]

    def total_signals(self) -> int:
        return len(self._signals)

    def clear(self) -> None:
        self._signals.clear()
        self._next_id = 1
