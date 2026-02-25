import httpx

GAMMA_API = "https://gamma-api.polymarket.com"
TIMEOUT = 10


def _format_price(price: str) -> str:
    try:
        return f"{float(price) * 100:.1f}%"
    except (ValueError, TypeError):
        return "N/A"


def _format_volume(volume: float) -> str:
    if volume >= 1_000_000:
        return f"${volume / 1_000_000:.1f}M"
    if volume >= 1_000:
        return f"${volume / 1_000:.0f}K"
    return f"${volume:.0f}"


def _format_market(market: dict) -> str:
    question = market.get("question", "未知")
    outcomes = market.get("outcomes", "[]")
    prices = market.get("outcomePrices", "[]")
    volume = market.get("volume", 0)
    end_date = (market.get("endDate") or "")[:10]

    # Parse JSON strings if needed
    if isinstance(outcomes, str):
        import json
        try:
            outcomes = json.loads(outcomes)
            prices = json.loads(prices)
        except Exception:
            outcomes, prices = [], []

    lines = [f"{question}"]
    if outcomes and prices:
        for outcome, price in zip(outcomes, prices):
            lines.append(f"  {outcome}: {_format_price(str(price))}")
    try:
        vol = float(volume)
        lines.append(f"成交量: {_format_volume(vol)}")
    except (ValueError, TypeError):
        pass
    if end_date:
        lines.append(f"截止: {end_date}")
    return "\n".join(lines)


def get_trending_markets(limit: int = 5) -> str:
    try:
        resp = httpx.get(
            f"{GAMMA_API}/markets",
            params={"active": "true", "closed": "false", "limit": limit, "order": "volume", "ascending": "false"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        markets = resp.json()
        if not markets:
            return "目前沒有熱門市場資料。"
        parts = [f"Polymarket 熱門市場 Top {len(markets)}\n"]
        for i, m in enumerate(markets, 1):
            parts.append(f"{i}. {_format_market(m)}")
        return "\n\n".join(parts)
    except Exception as e:
        return f"查詢 Polymarket 失敗：{e}"


def search_markets(query: str, limit: int = 5) -> str:
    try:
        resp = httpx.get(
            f"{GAMMA_API}/markets",
            params={"active": "true", "closed": "false", "limit": limit, "search": query},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        markets = resp.json()
        if not markets:
            return f"找不到關於「{query}」的市場。"
        parts = [f"搜尋「{query}」結果 ({len(markets)} 個市場)\n"]
        for i, m in enumerate(markets, 1):
            parts.append(f"{i}. {_format_market(m)}")
        return "\n\n".join(parts)
    except Exception as e:
        return f"搜尋失敗：{e}"
