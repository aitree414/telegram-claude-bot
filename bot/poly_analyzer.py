"""Polymarket AI-powered market analysis and recommendations."""
from __future__ import annotations
import json
import logging
import time
from datetime import datetime, timezone

import httpx
from httpx import ConnectError, TimeoutException, HTTPStatusError, RequestError
import openai
from openai import AuthenticationError, RateLimitError, APIError, APIConnectionError, APITimeoutError

logger = logging.getLogger(__name__)

from .retry import retry, retry_with_exponential_backoff

GAMMA_API = "https://gamma-api.polymarket.com"
TIMEOUT = 15
MODEL = "deepseek-chat"
MAX_TOKENS = 1500  # For Polymarket analysis requests


def _fetch_markets(limit: int = 100, max_retries: int = 3) -> list[dict]:
    """Fetch active markets sorted by volume with retry for transient errors."""

    def is_retryable_error(e: Exception) -> bool:
        """Determine if an exception should trigger a retry."""
        # Network errors always retry
        if isinstance(e, (ConnectError, TimeoutException)):
            return True

        # HTTP status errors: retry on 429 and 5xx
        if isinstance(e, HTTPStatusError):
            status_code = e.response.status_code
            return status_code == 429 or (500 <= status_code < 600)

        # Other errors should not retry
        return False

    def get_retry_delay(attempt: int, exception: Exception) -> float:
        """Calculate retry delay with exponential backoff and Retry-After header support."""
        base_delay = 1.0 * (2 ** (attempt - 1))  # Exponential backoff: 1, 2, 4, ...

        # If it's an HTTPStatusError with Retry-After header, use that
        if isinstance(exception, HTTPStatusError):
            retry_after = exception.response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                return float(retry_after)

        # Cap the delay
        return min(base_delay, 30.0)

    # Use retry decorator with custom logic
    retry_decorator = retry(
        max_retries=max_retries,
        initial_delay=1.0,
        max_delay=30.0,
        backoff_factor=2.0,
        jitter=0.1,
        retry_condition=is_retryable_error,
        on_retry=lambda attempt, exc: logger.warning(
            f"Polymarket API 錯誤 (嘗試 {attempt}/{max_retries}): {exc}"
        )
    )

    @retry_decorator
    def fetch():
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

    try:
        return fetch()
    except (ConnectError, TimeoutException) as e:
        logger.error(f"所有重試失敗，無法連線到 Polymarket API: {e}")
        return []
    except HTTPStatusError as e:
        status_code = e.response.status_code
        logger.error(f"Polymarket API 返回錯誤狀態碼 {status_code}: {e}")
        return []
    except (RequestError, json.JSONDecodeError) as e:
        logger.error(f"Polymarket API 請求或解析失敗: {e}")
        return []
    except Exception as e:
        logger.error(f"取得市場資料時發生未預期錯誤: {e}")
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
            logger.debug(f"跳過無效市場數據: outcomes={outcomes}, prices={prices}")
            return None

        # 轉換價格為 float，可能失敗
        try:
            price_floats = [float(p) for p in prices]
        except (ValueError, TypeError) as e:
            logger.debug(f"價格轉換失敗: {prices}, 錯誤: {e}")
            return None

        price_pairs = list(zip(outcomes, price_floats))

        # Skip markets where outcome is already essentially decided (>97% or <3%)
        max_price = max(price_floats)
        if max_price > 0.97 or max_price < 0.03:
            logger.debug(f"跳開已決定的市場: max_price={max_price}")
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
    except json.JSONDecodeError as e:
        logger.debug(f"JSON 解析失敗: {e}")
        return None
    except (ValueError, TypeError) as e:
        logger.debug(f"數據類型轉換失敗: {e}")
        return None
    except Exception as e:
        logger.debug(f"解析市場時發生未預期錯誤: {e}")
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
        client = openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        analysis = response.choices[0].message.content

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

    except AuthenticationError as e:
        logger.error(f"DeepSeek API 金鑰驗證失敗: {e}")
        return "AI 分析失敗：API 金鑰無效或已過期。請檢查 DEEPSEEK_API_KEY 環境變數。"
    except RateLimitError as e:
        logger.error(f"DeepSeek API 請求頻率超限: {e}")
        return "AI 分析失敗：API 請求頻率超限，請稍後再試。"
    except APIConnectionError as e:
        logger.error(f"無法連線到 DeepSeek API: {e}")
        return "AI 分析失敗：無法連線到 AI 服務，請檢查網路連線。"
    except APITimeoutError as e:
        logger.error(f"DeepSeek API 請求超時: {e}")
        return "AI 分析失敗：AI 服務回應超時，請稍後再試。"
    except APIError as e:
        logger.error(f"DeepSeek API 錯誤: {e}")
        return f"AI 分析失敗：AI 服務發生錯誤 (狀態碼: {e.status_code if hasattr(e, 'status_code') else '未知'})。"
    except Exception as e:
        logger.error(f"AI 分析發生未預期錯誤: {e}")
        return f"AI 分析失敗：{e}"


def get_quick_picks(api_key: str) -> str:
    """Quick scan: markets with extreme odds that might indicate value."""
    markets_raw = _fetch_markets(limit=50)
    markets = [m for m in (_parse_market(r) for r in markets_raw) if m]

    if not markets:
        if not markets_raw:
            # _fetch_markets 返回空列表，表示 API 請求失敗
            logger.error("無法從 Polymarket API 取得任何市場數據")
            return "無法取得市場資料：Polymarket API 請求失敗，請檢查網路連線或稍後再試。"
        else:
            # markets_raw 有數據但無法解析
            logger.warning(f"取得 {len(markets_raw)} 個市場但全部無法解析")
            return "無法解析市場資料，可能是 API 格式變更。"

    logger.info(f"成功解析 {len(markets)} 個市場進行快速掃描")

    # Find markets where one outcome is 75-92% (high confidence but not decided)
    value_picks = []
    for m in markets:
        try:
            for outcome, price in m["outcomes"]:
                if 0.75 <= price <= 0.92 and m["volume"] > 10000:
                    value_picks.append({
                        "question": m["question"],
                        "outcome": outcome,
                        "price": price,
                        "volume": m["volume"],
                        "end_date": m["end_date"],
                    })
        except (KeyError, TypeError) as e:
            logger.debug(f"市場數據結構錯誤: {e}, 跳過該市場")
            continue

    if not value_picks:
        logger.info("沒有找到符合條件的高信心市場")
        return "目前沒有符合條件的高信心市場。"

    value_picks.sort(key=lambda x: x["volume"], reverse=True)
    lines = [f"高信心市場（75-92% 勝率，成交量>$10K）\n"]
    for i, p in enumerate(value_picks[:5], 1):
        try:
            lines.append(
                f"{i}. {p['question']}\n"
                f"   投注 [{p['outcome']}] @ {p['price']*100:.1f}%\n"
                f"   成交量: ${p['volume']:,.0f}  截止: {p['end_date']}"
            )
        except (KeyError, TypeError) as e:
            logger.debug(f"格式化推薦時發生錯誤: {e}, 跳過該推薦")
            continue

    if len(lines) == 1:  # 只有標題
        return "沒有找到可顯示的高信心市場。"

    return "\n\n".join(lines)
