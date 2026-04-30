"""Stock analysis orchestration powered by multi-persona LLM agents.

Runs all 5 investor personas on a given stock and aggregates their
signals into a consensus rating.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from analysis.persona_agents import (
    PERSONA_PROMPTS,
    PERSONA_NAMES,
    RATING_SCORE,
    analyze_with_persona,
)

logger = logging.getLogger(__name__)


def analyze_stock(stock_data: dict, timeout: int = 30) -> dict:
    """Run all persona agents on a stock and produce a consensus.

    Parameters
    ----------
    stock_data : dict
        Must contain keys: symbol, name, current, change_pct, ind, fund.
        See ``bot.stock._scan_single`` for the expected shape.
    timeout : int
        Max seconds to wait for all personas to respond.

    Returns
    -------
    dict with keys:
        symbol, name, current, change_pct,
        consensus_rating (BUY/SELL/HOLD),
        consensus_score (float, -1..1),
        confidence (float, 0..1),
        ratings (list of per-persona results),
        summary (human-readable text)
    """
    symbol = stock_data.get("symbol", "?")
    results = []

    with ThreadPoolExecutor(max_workers=5) as pool:
        fut = {
            pool.submit(
                analyze_with_persona, name, prompt, stock_data
            ): name
            for name, prompt in PERSONA_PROMPTS.items()
        }
        for f in as_completed(fut, timeout=timeout):
            try:
                results.append(f.result())
            except Exception as e:
                persona = fut[f]
                logger.warning(f"Persona '{persona}' timed out: {e}")
                results.append({
                    "persona": persona,
                    "rating": "HOLD",
                    "confidence": 0,
                    "reason": "分析超時",
                })

    # Aggregate by weighted voting
    total_weight = 0.0
    weighted_score = 0.0
    buy_count = sell_count = hold_count = 0

    for r in results:
        w = r.get("confidence", 50) / 100.0
        total_weight += w
        weighted_score += RATING_SCORE.get(r.get("rating", "HOLD"), 0) * w
        # Simple count
        rating = r.get("rating", "HOLD")
        if rating == "BUY":
            buy_count += 1
        elif rating == "SELL":
            sell_count += 1
        else:
            hold_count += 1

    consensus_score = weighted_score / total_weight if total_weight > 0 else 0
    confidence = max(abs(consensus_score), (buy_count + sell_count) / 5)

    if consensus_score > 0.3:
        consensus_rating = "BUY"
    elif consensus_score < -0.3:
        consensus_rating = "SELL"
    else:
        consensus_rating = "HOLD"

    # Build human-readable summary
    lines = [
        f"🤖 多維度 AI 分析 — {stock_data.get('name', symbol)} ({symbol})",
        f"現價：{stock_data.get('current', '?')}",
        "",
    ]

    for r in results:
        p = r.get("persona", "?")
        label = PERSONA_NAMES.get(p, p)
        rating = r.get("rating", "?")
        conf = r.get("confidence", 0)
        reason = r.get("reason", "")
        icon = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(rating, "⚪")
        lines.append(f"{icon} {label}：{rating} (信心 {conf}%)")
        if reason:
            lines.append(f"   └ {reason}")

    lines.append("")
    if consensus_rating == "BUY":
        lines.append(f"✅ **共識：買入**（加權分 {consensus_score:.2f}，信心 {confidence:.0%}）")
    elif consensus_rating == "SELL":
        lines.append(f"⛔ **共識：賣出**（加權分 {consensus_score:.2f}）")
    else:
        lines.append(f"➡️ **共識：持有觀望**（加權分 {consensus_score:.2f}）")

    lines.append(f"買入 {buy_count} / 賣出 {sell_count} / 持有 {hold_count}")

    result = {
        "symbol": symbol,
        "name": stock_data.get("name", ""),
        "current": stock_data.get("current"),
        "change_pct": stock_data.get("change_pct"),
        "consensus_rating": consensus_rating,
        "consensus_score": round(consensus_score, 2),
        "confidence": round(confidence, 2),
        "ratings": results,
        "summary": "\n".join(lines),
    }
    return result
