"""AutoTuner: adjusts strategy thresholds based on persona prediction accuracy.

Uses historical prediction outcomes to dial buy/sell thresholds up or down,
creating a self-optimizing loop: more accurate predictions → more aggressive
trading; less accurate → more conservative.
"""

from __future__ import annotations

import logging
from typing import Optional

from analysis.persona_tracker import PersonaTracker

logger = logging.getLogger(__name__)


class AutoTuner:
    """Analyzes prediction performance and recommends threshold adjustments."""

    # Minimum verified predictions before tuning takes effect
    MIN_VERIFIED = 20

    # How much to adjust per tuning cycle (multiplier)
    ADJUST_FACTOR = 0.9  # 10% adjustment per cycle

    def __init__(self, tracker: PersonaTracker):
        self.tracker = tracker

    def tune(self, current_buy_threshold: float = 0.4,
             current_sell_threshold: float = -0.3,
             current_min_confidence: float = 0.6) -> dict:
        """Analyze performance and return adjusted thresholds.

        Parameters
        ----------
        current_buy_threshold : float
            Current min consensus_score to trigger BUY (default 0.4).
        current_sell_threshold : float
            Current max consensus_score to trigger SELL (default -0.3).
        current_min_confidence : float
            Current min confidence required to act (default 0.6).

        Returns
        -------
        dict with keys:
            buy_threshold : float (recommended new value)
            sell_threshold : float
            min_confidence : float
            reasoning : str (human-readable explanation)
            adjusted : bool (whether any change was made)
        """
        stats = self.tracker.get_performance_stats()
        total = stats["total_verified"]

        if total < self.MIN_VERIFIED:
            return {
                "buy_threshold": current_buy_threshold,
                "sell_threshold": current_sell_threshold,
                "min_confidence": current_min_confidence,
                "reasoning": f"數據不足：僅 {total} 筆驗證（需 ≥{self.MIN_VERIFIED}）",
                "adjusted": False,
            }

        accuracy = stats["overall_accuracy"]
        high_conf_acc = stats["by_confidence"]["high"]["accuracy"]
        low_conf_acc = stats["by_confidence"]["low"]["accuracy"]

        buy_threshold = current_buy_threshold
        sell_threshold = current_sell_threshold
        min_confidence = current_min_confidence
        reasons = []

        # ---- Adjust confidence threshold based on calibration ----
        if high_conf_acc > 0.75 and low_conf_acc < 0.5:
            # High-confidence predictions are much better → trust them more,
            # raise the confidence bar to filter out low-quality signals
            min_confidence = min(0.8, min_confidence * (1 / self.ADJUST_FACTOR))
            reasons.append(f"高信心準確 ({high_conf_acc:.0%}) >> 低信心 ({low_conf_acc:.0%})，提高信心門檻")
        elif high_conf_acc < 0.5:
            # Even high-confidence predictions are bad → be more cautious
            min_confidence = min(0.85, min_confidence * (1 / self.ADJUST_FACTOR))
            reasons.append(f"高信心僅 {high_conf_acc:.0%} 正確，提高信心門檻並更保守")
        elif high_conf_acc > 0.85 and low_conf_acc > 0.6:
            # Everything is working well → can relax confidence threshold
            min_confidence = max(0.4, min_confidence * self.ADJUST_FACTOR)
            reasons.append(f"各類信心皆準確，放寬信心門檻")

        # ---- Adjust buy/sell thresholds based on overall accuracy ----
        if accuracy > 0.7:
            # Predictions are reliable → trade more aggressively
            buy_threshold = max(0.1, current_buy_threshold * self.ADJUST_FACTOR)
            sell_threshold = min(-0.1, current_sell_threshold * self.ADJUST_FACTOR)
            reasons.append(f"總體準確率 {accuracy:.0%} > 70%，放寬買賣門檻")
        elif accuracy < 0.5:
            # Predictions unreliable → require stronger signals
            buy_threshold = min(0.7, current_buy_threshold * (1 / self.ADJUST_FACTOR))
            sell_threshold = max(-0.5, current_sell_threshold * (1 / self.ADJUST_FACTOR))
            reasons.append(f"總體準確率僅 {accuracy:.0%} < 50%，收緊買賣門檻")

        # Round for readability
        buy_threshold = round(buy_threshold, 2)
        sell_threshold = round(sell_threshold, 2)
        min_confidence = round(min_confidence, 2)

        adjusted = (
            buy_threshold != current_buy_threshold
            or sell_threshold != current_sell_threshold
            or min_confidence != current_min_confidence
        )

        if not reasons:
            reasons.append("無需調整")

        logger.info(
            f"AutoTuner: thresholds {current_buy_threshold}/{current_sell_threshold}/"
            f"{current_min_confidence} → {buy_threshold}/{sell_threshold}/"
            f"{min_confidence} (acc={accuracy:.0%})"
        )

        return {
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
            "min_confidence": min_confidence,
            "reasoning": "；".join(reasons),
            "adjusted": adjusted,
        }
