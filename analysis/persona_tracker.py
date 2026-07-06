"""Tracks persona-agent prediction accuracy and computes performance weights.

Each persona's historical predictions are stored with:
- The stock symbol and predicted rating
- The actual outcome (checked later via price movement)
- Confidence level

Weights are derived from calibration accuracy — how often a persona's
high-confidence predictions were correct.
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Decay factor: older predictions count less (0.95 = ~5% decay per entry)
DECAY_FACTOR = 0.95

# Default weight when no history exists
DEFAULT_WEIGHT = 1.0

# Minimum number of predictions before an agent's weight takes effect
MIN_HISTORY = 5


class PredictionRecord:
    """One stored prediction with outcome."""

    def __init__(self, persona: str, symbol: str, rating: str,
                 confidence: int, price: float, timestamp: str = ""):
        self.persona = persona
        self.symbol = symbol
        self.rating = rating
        self.confidence = confidence  # 0-100
        self.price = price
        self.timestamp = timestamp or datetime.utcnow().isoformat()
        self.outcome: Optional[str] = None   # "correct" / "wrong"
        self.outcome_checked: bool = False

    def to_dict(self) -> dict:
        return {
            "persona": self.persona,
            "symbol": self.symbol,
            "rating": self.rating,
            "confidence": self.confidence,
            "price": self.price,
            "timestamp": self.timestamp,
            "outcome": self.outcome,
            "outcome_checked": self.outcome_checked,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PredictionRecord":
        p = cls(
            persona=d["persona"],
            symbol=d["symbol"],
            rating=d["rating"],
            confidence=d.get("confidence", 50),
            price=d.get("price", 0),
            timestamp=d.get("timestamp", ""),
        )
        p.outcome = d.get("outcome")
        p.outcome_checked = d.get("outcome_checked", False)
        return p


class PersonaTracker:
    """Tracks and weights persona agents by historical accuracy.

    Usage
    -----
    >>> tracker = PersonaTracker()
    >>> tracker.record_prediction("value", "AAPL", "BUY", 80, 150.0)
    >>> # Later, when outcome is known:
    >>> tracker.record_outcome("value", "AAPL", "correct")
    >>> weights = tracker.get_weights()
    """

    def __init__(self, data_dir: Optional[Path] = None):
        self._data_dir = data_dir or Path(__file__).parent.parent / "data"
        self._file = self._data_dir / "persona_tracker.json"
        self._records: list[PredictionRecord] = []
        self._load()

    # ── Persistence ────────────────────────────

    def _load(self) -> None:
        try:
            if self._file.exists():
                data = json.loads(self._file.read_text())
                self._records = [PredictionRecord.from_dict(r) for r in data]
                logger.info(f"Loaded {len(self._records)} persona predictions")
        except Exception as e:
            logger.warning(f"Failed to load persona tracker: {e}")
            self._records = []

    def _save(self) -> None:
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            data = [r.to_dict() for r in self._records]
            self._file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save persona tracker: {e}")

    # ── Recording ──────────────────────────────

    def record_prediction(self, persona: str, symbol: str, rating: str,
                          confidence: int, price: float) -> None:
        """Store a persona's prediction for later verification."""
        self._records.append(PredictionRecord(
            persona=persona,
            symbol=symbol,
            rating=rating,
            confidence=confidence,
            price=price,
        ))
        self._save()

    def record_outcome(self, persona: str, symbol: str,
                       outcome: str, current_price: float) -> None:
        """Record whether a prediction was correct.

        outcome: "correct" or "wrong"
        """
        updated = 0
        for r in self._records:
            if (r.persona == persona and r.symbol == symbol
                    and not r.outcome_checked):
                r.outcome = outcome
                r.outcome_checked = True
                updated += 1
        if updated:
            logger.info(f"Recorded outcome '{outcome}' for {persona}/{symbol} "
                        f"({updated} predictions)")
            self._save()

    def record_outcomes_for_symbol(self, symbol: str,
                                   rating_to_price_change: dict) -> None:
        """Batch record outcomes using a mapping of expected directions.

        ``rating_to_price_change`` maps expected move direction to
        the actual outcome:

            {"BUY": "correct", "HOLD": "neutral", "SELL": "wrong"}

        A simple heuristic: if BUY and price went up → correct.
        """
        for r in self._records:
            if r.symbol == symbol and not r.outcome_checked:
                expected = rating_to_price_change.get(r.rating, "neutral")
                if expected == "correct":
                    r.outcome = "correct"
                elif expected == "wrong":
                    r.outcome = "wrong"
                else:
                    r.outcome = "neutral"
                r.outcome_checked = True
        self._save()

    # ── Weight calculation ─────────────────────

    def get_weights(self, min_history: int = MIN_HISTORY) -> dict[str, float]:
        """Compute performance-based weights for each persona.

        Weight formula:
            base = correct_ratio - 0.5  (how much better than random)
            weight = max(0.1, base * confidence_multiplier)

        ``confidence_multiplier`` rewards agents whose high-confidence
        predictions are more accurate than their low-confidence ones.
        """
        # Group by persona
        by_persona: dict[str, list[PredictionRecord]] = defaultdict(list)
        for r in self._records:
            if r.outcome_checked:
                by_persona[r.persona].append(r)

        weights: dict[str, float] = {}
        for persona, records in by_persona.items():
            if len(records) < min_history:
                weights[persona] = DEFAULT_WEIGHT
                continue

            correct = sum(1 for r in records if r.outcome == "correct")
            total = sum(1 for r in records if r.outcome in ("correct", "wrong"))
            if total == 0:
                weights[persona] = DEFAULT_WEIGHT
                continue

            correct_ratio = correct / total

            # Calibration score: how well confidence correlates with accuracy
            high_conf_correct = sum(
                1 for r in records
                if r.outcome == "correct" and r.confidence >= 70
            )
            high_conf_total = sum(
                1 for r in records
                if r.confidence >= 70 and r.outcome in ("correct", "wrong")
            )
            low_conf_correct = sum(
                1 for r in records
                if r.outcome == "correct" and r.confidence < 70
            )
            low_conf_total = sum(
                1 for r in records
                if r.confidence < 70 and r.outcome in ("correct", "wrong")
            )

            calibration = 1.0
            if high_conf_total >= 3 and low_conf_total >= 3:
                high_ratio = high_conf_correct / high_conf_total
                low_ratio = low_conf_correct / low_conf_total
                # If high-confidence predictions are more accurate → good calibration
                if high_ratio > low_ratio:
                    calibration = min(2.0, high_ratio / max(low_ratio, 0.01))
                else:
                    calibration = max(0.5, low_ratio / max(high_ratio, 0.01))

            # Weight: how much better than random (0.5)
            skill = correct_ratio - 0.5
            weight = max(0.1, (skill * 2) * calibration)
            weights[persona] = round(min(weight, 3.0), 2)

        # Add default weights for personas with no history
        known = {"value", "momentum", "growth", "contrarian", "risk_manager"}
        for p in known:
            if p not in weights:
                weights[p] = DEFAULT_WEIGHT

        logger.info(f"Persona weights: {weights}")
        return weights

    def text_summary(self) -> str:
        """Human-readable summary of tracked performance."""
        weights = self.get_weights()
        by_persona: dict[str, list[PredictionRecord]] = defaultdict(list)
        for r in self._records:
            if r.outcome_checked:
                by_persona[r.persona].append(r)

        lines = ["📊 Persona 績效追蹤\n"]
        for persona in ["value", "momentum", "growth", "contrarian", "risk_manager"]:
            records = by_persona.get(persona, [])
            weight = weights.get(persona, 1.0)
            label = {"value": "價值型", "momentum": "動能型",
                     "growth": "成長型", "contrarian": "逆向型",
                     "risk_manager": "風控型"}.get(persona, persona)

            if not records:
                lines.append(f"  {label}：尚無記錄（權重 {weight:.1f}）")
                continue

            correct = sum(1 for r in records if r.outcome == "correct")
            wrong = sum(1 for r in records if r.outcome == "wrong")
            total = correct + wrong
            acc = correct / total * 100 if total > 0 else 0

            lines.append(
                f"  {label}：{correct}/{total} 正確 ({acc:.0f}%) "
                f"權重 {weight:.2f}"
            )

        if not any(by_persona.values()):
            lines.append("  （尚無已驗證的預測記錄，需要先設定 outcome）")

        return "\n".join(lines)

    # ── Performance stats ────────────────────────

    def get_performance_stats(self) -> dict:
        """Structured performance data for reporting and auto-tuning.

        Returns
        -------
        dict with keys:
            overall_accuracy : float (0..1)
            total_verified  : int
            by_persona      : {persona: {correct, total, accuracy, weight}}
            by_confidence   : {high: {correct, total, accuracy},
                               low: {correct, total, accuracy}}
            by_symbol       : {symbol: {correct, total, accuracy}}
        """
        by_persona: dict = {}
        by_symbol: dict = {}
        high = {"correct": 0, "total": 0}
        low = {"correct": 0, "total": 0}
        total_correct = 0
        total_verified = 0

        for r in self._records:
            if not r.outcome_checked or r.outcome not in ("correct", "wrong"):
                continue

            is_correct = 1 if r.outcome == "correct" else 0
            total_correct += is_correct
            total_verified += 1

            # By persona
            if r.persona not in by_persona:
                by_persona[r.persona] = {"correct": 0, "total": 0}
            by_persona[r.persona]["correct"] += is_correct
            by_persona[r.persona]["total"] += 1

            # By symbol
            if r.symbol not in by_symbol:
                by_symbol[r.symbol] = {"correct": 0, "total": 0}
            by_symbol[r.symbol]["correct"] += is_correct
            by_symbol[r.symbol]["total"] += 1

            # By confidence
            if r.confidence >= 70:
                high["correct"] += is_correct
                high["total"] += 1
            else:
                low["correct"] += is_correct
                low["total"] += 1

        def _acc(c, t):
            return round(c / t, 4) if t > 0 else 0.0

        weights = self.get_weights()
        for p in by_persona:
            by_persona[p]["accuracy"] = _acc(by_persona[p]["correct"],
                                             by_persona[p]["total"])
            by_persona[p]["weight"] = weights.get(p, 1.0)

        for s in by_symbol:
            by_symbol[s]["accuracy"] = _acc(by_symbol[s]["correct"],
                                            by_symbol[s]["total"])

        return {
            "overall_accuracy": _acc(total_correct, total_verified),
            "total_verified": total_verified,
            "by_persona": by_persona,
            "by_confidence": {
                "high": {"correct": high["correct"], "total": high["total"],
                         "accuracy": _acc(high["correct"], high["total"])},
                "low": {"correct": low["correct"], "total": low["total"],
                        "accuracy": _acc(low["correct"], low["total"])},
            },
            "by_symbol": by_symbol,
        }

    @property
    def total_predictions(self) -> int:
        return len(self._records)

    @property
    def verified_predictions(self) -> int:
        return sum(1 for r in self._records if r.outcome_checked)
