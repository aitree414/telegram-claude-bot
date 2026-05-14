"""Stock analysis orchestration powered by multi-persona LLM agents.

Includes a 2-round debate: independent analysis → peer review → revised ratings.
Consensus is computed using performance-weighted voting from ``PersonaTracker``.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from analysis.persona_agents import (
    PERSONA_PROMPTS,
    PERSONA_NAMES,
    RATING_SCORE,
    analyze_with_persona,
    analyze_with_persona_debate,
    build_debate_context,
)
from analysis.persona_tracker import PersonaTracker
from analysis.trading_agents_bridge import analyze_with_trading_agents

logger = logging.getLogger(__name__)

# Default weights when tracker is unavailable or has no history
DEFAULT_WEIGHTS = {
    "value": 1.0,
    "momentum": 1.0,
    "growth": 1.0,
    "contrarian": 1.0,
    "risk_manager": 1.0,
}


def analyze_stock(stock_data: dict, timeout: int = 60,
                  enable_debate: bool = True,
                  tracker: Optional[PersonaTracker] = None) -> dict:
    """Run all persona agents through a 2-round debate and produce a consensus.

    Parameters
    ----------
    stock_data : dict
        Must contain keys: symbol, name, current, change_pct, ind, fund.
    timeout : int
        Max seconds per round.
    enable_debate : bool
        Whether to run the debate round (default True).
    tracker : PersonaTracker or None
        If provided, records predictions and uses performance weights.

    Returns
    -------
    dict with keys:
        symbol, name, current, change_pct,
        consensus_rating (BUY/SELL/HOLD),
        consensus_score (float, -1..1),
        confidence (float, 0..1),
        ratings (list of per-persona results from both rounds),
        weights_used (dict of persona → weight),
        summary (human-readable text)
    """
    symbol = stock_data.get("symbol", "?")
    price = stock_data.get("current", 0)
    name = stock_data.get("name", "")

    # ── Round 1: independent analysis ────────────
    round1_results = _run_personas(PERSONA_PROMPTS, stock_data, timeout)

    # ── Debate round ─────────────────────────────
    if enable_debate:
        debate_context = build_debate_context(round1_results)
        round2_results = _run_debate(round1_results, debate_context, stock_data, timeout)
        all_results = round1_results + round2_results
        final_results = round2_results  # use debate outcomes for consensus
    else:
        all_results = round1_results
        final_results = round1_results

    # ── TradingAgents (runs in parallel, slower) ──
    ta_result = analyze_with_trading_agents(symbol)
    if ta_result.get("error") and ta_result.get("elapsed"):
        logger.warning(
            "TradingAgents failed for %s after %.0fs: %s",
            symbol, ta_result["elapsed"], ta_result["error"],
        )
    all_results.append(ta_result)
    final_results = final_results + [ta_result]

    # ── Get performance weights ──────────────────
    weights = DEFAULT_WEIGHTS.copy()
    if tracker:
        try:
            weights = tracker.get_weights()
        except Exception:
            logger.warning("PersonaTracker weights unavailable, using defaults")

    # ── Weighted consensus ───────────────────────
    consensus_score, confidence = _compute_weighted_consensus(
        final_results, weights
    )

    if consensus_score > 0.3:
        consensus_rating = "BUY"
    elif consensus_score < -0.3:
        consensus_rating = "SELL"
    else:
        consensus_rating = "HOLD"

    # ── Record predictions for future tracking ───
    if tracker:
        for r in round1_results:
            try:
                tracker.record_prediction(
                    persona=r["persona"],
                    symbol=symbol,
                    rating=r["rating"],
                    confidence=r.get("confidence", 50),
                    price=price,
                )
            except Exception:
                continue

    # ── Build summary ────────────────────────────
    lines = [
        f"🤖 多維度 AI 分析 — {name} ({symbol})",
        f"現價：{price}",
        "",
    ]

    for r in round1_results:
        p = r.get("persona", "?")
        label = PERSONA_NAMES.get(p, p)
        rating = r.get("rating", "?")
        conf = r.get("confidence", 0)
        reason = r.get("reason", "")
        icon = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(rating, "⚪")
        w = weights.get(p, 1.0)
        lines.append(f"{icon} {label}：{rating} (信心 {conf}%, 權重 {w:.1f})")
        if reason:
            lines.append(f"   └ {reason}")

    # Show debate changes
    if enable_debate:
        debate_changes = _get_debate_changes(round1_results, round2_results)
        if debate_changes:
            lines.append("")
            lines.append("💬 辯論後變更：")
            for p, (old, new) in debate_changes.items():
                label = PERSONA_NAMES.get(p, p)
                lines.append(f"  {label}: {old} → {new}")

    # TradingAgents
    ta_r = next((r for r in all_results if r.get("persona") == "trading_agents"), None)
    if ta_r:
        signal = ta_r.get("ta_signal", "")
        extra = f" (TA: {signal})" if signal else ""
        lines.append(f"🧠 多智能體團隊：{ta_r.get('rating', '?')} (信心 {ta_r.get('confidence', 0)}%){extra}")
        if ta_r.get("elapsed"):
            lines.append(f"   ⚡ 耗時 {ta_r['elapsed']:.0f}s")

    lines.append("")
    if enable_debate:
        lines.append(f"📊 **經過 {len(round1_results)} 位分析師辯論**")
    if consensus_rating == "BUY":
        lines.append(f"✅ **共識：買入**（加權分 {consensus_score:.2f}，信心 {confidence:.0%}）")
    elif consensus_rating == "SELL":
        lines.append(f"⛔ **共識：賣出**（加權分 {consensus_score:.2f}，信心 {confidence:.0%}）")
    else:
        lines.append(f"➡️ **共識：持有觀望**（加權分 {consensus_score:.2f}，信心 {confidence:.0%}）")

    # Count final ratings
    buy_count = sum(1 for r in final_results if r.get("rating") == "BUY")
    sell_count = sum(1 for r in final_results if r.get("rating") == "SELL")
    hold_count = sum(1 for r in final_results if r.get("rating") == "HOLD")
    lines.append(f"買入 {buy_count} / 賣出 {sell_count} / 持有 {hold_count}")

    result = {
        "symbol": symbol,
        "name": name,
        "current": price,
        "change_pct": stock_data.get("change_pct"),
        "consensus_rating": consensus_rating,
        "consensus_score": round(consensus_score, 2),
        "confidence": round(confidence, 2),
        "ratings": all_results,
        "weights_used": weights,
        "summary": "\n".join(lines),
    }
    return result


# ── Helpers ──────────────────────────────────────


def _run_personas(prompts: dict, stock_data: dict,
                  timeout: int) -> list[dict]:
    """Run all personas in parallel (Round 1)."""
    results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        fut = {
            pool.submit(analyze_with_persona, name, prompt, stock_data): name
            for name, prompt in prompts.items()
        }
        for f in as_completed(fut, timeout=timeout):
            try:
                results.append(f.result())
            except Exception as e:
                persona = fut[f]
                logger.warning(f"Persona '{persona}' Round 1 timeout: {e}")
                results.append({
                    "persona": persona,
                    "rating": "HOLD",
                    "confidence": 0,
                    "reason": "分析超時",
                })
    return results


def _run_debate(round1: list[dict], debate_context: str,
                stock_data: dict, timeout: int) -> list[dict]:
    """Run debate round: each persona sees peer views and revises."""
    results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        fut = {}
        for r in round1:
            p = r["persona"]
            prompt = PERSONA_PROMPTS.get(p, "")
            if not prompt:
                continue
            fut[pool.submit(
                analyze_with_persona_debate, p, prompt, stock_data, debate_context
            )] = p
        for f in as_completed(fut, timeout=timeout):
            try:
                results.append(f.result())
            except Exception as e:
                persona = fut[f]
                logger.warning(f"Persona '{persona}' debate timeout: {e}")
                results.append({
                    "persona": persona,
                    "rating": "HOLD",
                    "confidence": 0,
                    "reason": "辯論超時",
                    "debate_round": True,
                })
    return results


def _compute_weighted_consensus(
    results: list[dict], weights: dict[str, float]
) -> tuple[float, float]:
    """Compute weighted consensus score and confidence.

    Returns (consensus_score, confidence).
    consensus_score ranges from -1 (strong SELL) to +1 (strong BUY).
    """
    total_weight = 0.0
    weighted_score = 0.0
    buy_count = sell_count = 0

    for r in results:
        p = r.get("persona", "")
        w = weights.get(p, 1.0) * (r.get("confidence", 50) / 100.0)
        total_weight += w
        weighted_score += RATING_SCORE.get(r.get("rating", "HOLD"), 0) * w

        rating = r.get("rating", "HOLD")
        if rating == "BUY":
            buy_count += 1
        elif rating == "SELL":
            sell_count += 1

    consensus_score = weighted_score / total_weight if total_weight > 0 else 0
    n = max(len(results), 1)
    confidence = max(abs(consensus_score), (buy_count + sell_count) / n)
    confidence = min(confidence, 1.0)

    return consensus_score, confidence


def _get_debate_changes(round1: list[dict],
                        round2: list[dict]) -> dict[str, tuple[str, str]]:
    """Compare Round 1 vs Round 2 ratings. Returns {persona: (old, new)}."""
    r1 = {r["persona"]: r["rating"] for r in round1}
    r2 = {r["persona"]: r["rating"] for r in round2}
    changes = {}
    for p in r1:
        if p in r2 and r1[p] != r2[p]:
            changes[p] = (r1[p], r2[p])
    return changes
