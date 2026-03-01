"""Polymarket AI-powered market analysis and recommendations."""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone

import httpx
import anthropic

logger = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"
TIMEOUT = 15
MODEL = "claude-haiku-4-5-20251001"


def _fetch_markets(limit: int = 100) -> list[dict]:
    """Fetch active markets sorted by volume."""
    try:
        resp = httpx.get(
            f"{GAMMA_API}/markets",
            params={
                "active": "true",
                "closed": "false",
                "limit": limit,
                "order": "volume",
                "ascending": "false",
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"fetch markets failed: {e}")
        return []


def _parse_market(m: dict) -> dict | None:
    """Parse and validate a market entry."""
    try:
        outcomes = m.get("outcomes", "[]")
        prices = m.get("outcomePrices", "[]")
        if isinstance(outcomes, str):
            outcomes = json.loads(outcomes)
            prices = json.loads(prices)

        if not outcomes or not prices or len(outcomes) != len(prices):
            return None

        price_pairs = list(zip(outcomes, [float(p) for p in prices]))

        # Skip markets where outcome is already essentially decided (>97% or <3%)
        max_price = max(float(p) for p in prices)
        if max_price > 0.97 or max_price < 0.03:
            return None

        end_date = (m.get("endDate") or "")[:10]
        volume = float(m.get("volume") or 0)

        return {
            "question": m.get("question", ""),
            "outcomes": price_pairs,
            "volume": volume,
            "end_date": end_date,
            "id": m.get("id", ""),
            "slug": m.get("slug", ""),
        }
    except Exception:
        return None


def _format_for_claude(markets: list[dict]) -> str:
    """Format market data for Claude analysis."""
    lines = []
    for i, m in enumerate(markets, 1):
        outcomes_str = " / ".join(
            f"{o}: {p*100:.1f}%" for o, p in m["outcomes"]
        )
        lines.append(
            f"{i}. {m['question']}\n"
            f"   賠率: {outcomes_str}\n"
            f"   成交量: ${m['volume']:,.0f}  截止: {m['end_date']}"
        )
    return "\n\n".join(lines)


def get_ai_recommendations(api_key: str, top_n: int = 5) -> str:
    """Use Claude to analyze markets and return top picks."""
    markets_raw = _fetch_markets(limit=80)
    markets = [m for m in (_parse_market(r) for r in markets_raw) if m]

    if not markets:
        return "無法取得市場資料。"

    # Take top 30 by volume for analysis
    markets = markets[:30]
    market_text = _format_for_claude(markets)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    prompt = f"""今天是 {today}。以下是 Polymarket 上的預測市場資料（按成交量排序）：

{market_text}

請分析並挑選出 {top_n} 個最值得投注的市場。評估標準：
1. 賠率是否合理（市場定價是否有錯誤）
2. 事件確定性高（有明確資訊支撐某個結果）
3. 成交量充足（流動性好）
4. 截止日期合理（不要太遠）

對每個推薦，給出：
- 推薦投注哪個選項（Yes/No 或具體選項）
- 信心程度（高/中/低）
- 簡短理由（一句話）
- 建議投注比例（佔總資金的 %，保守建議 2-5%）

格式：
1. [問題簡稱]
   投注：[選項] @ [賠率]%
   信心：[高/中/低]
   理由：[一句話]
   建議：資金的 [X]%"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        analysis = response.content[0].text

        header = (
            f"Polymarket 今日推薦 ({today})\n"
            f"分析了 {len(markets)} 個市場，Top {top_n} 推薦：\n\n"
        )
        footer = (
            "\n\n---\n"
            "以上為 AI 分析，僅供參考。\n"
            "前往 polymarket.com 手動下注。"
        )
        return header + analysis + footer

    except Exception as e:
        logger.error(f"Claude analysis failed: {e}")
        return f"AI 分析失敗：{e}"


def get_quick_picks(api_key: str) -> str:
    """Quick scan: markets with extreme odds that might indicate value."""
    markets_raw = _fetch_markets(limit=50)
    markets = [m for m in (_parse_market(r) for r in markets_raw) if m]

    if not markets:
        return "無法取得市場資料。"

    # Find markets where one outcome is 75-92% (high confidence but not decided)
    value_picks = []
    for m in markets:
        for outcome, price in m["outcomes"]:
            if 0.75 <= price <= 0.92 and m["volume"] > 10000:
                value_picks.append({
                    "question": m["question"],
                    "outcome": outcome,
                    "price": price,
                    "volume": m["volume"],
                    "end_date": m["end_date"],
                })

    if not value_picks:
        return "目前沒有符合條件的高信心市場。"

    value_picks.sort(key=lambda x: x["volume"], reverse=True)
    lines = [f"高信心市場（75-92% 勝率，成交量>$10K）\n"]
    for i, p in enumerate(value_picks[:5], 1):
        lines.append(
            f"{i}. {p['question']}\n"
            f"   投注 [{p['outcome']}] @ {p['price']*100:.1f}%\n"
            f"   成交量: ${p['volume']:,.0f}  截止: {p['end_date']}"
        )
    return "\n\n".join(lines)
