"""LLM-powered investor persona agents for multi-perspective stock analysis.

Each agent adopts a distinct investment philosophy and analyses the same
market data independently, producing diverse signals that feed into
the portfolio manager.

Supports a 2-round debate: Round 1 = independent analysis,
Round 2 = agents see each other's views and update their rating.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

import openai

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lightweight LLM caller (OpenAI GPT, configurable via env vars)
# ---------------------------------------------------------------------------

def _call_llm(system_prompt: str, user_prompt: str,
              max_tokens: int = 1024, temperature: float = 0.7) -> str:
    """Single-turn LLM chat call with retry.

    Uses OPENAI_API_KEY (or DEEPSEEK_API_KEY as fallback).
    Override endpoint via OPENAI_BASE_URL, model via OPENAI_MODEL env var.
    """
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        return "錯誤：未設定 API 金鑰（OPENAI_API_KEY 或 DEEPSEEK_API_KEY）"

    base_url = os.environ.get("OPENAI_BASE_URL", None)
    model = os.environ.get("OPENAI_MODEL", "gpt-4o")
    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    last_error = ""

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return resp.choices[0].message.content or ""
        except openai.RateLimitError:
            time.sleep(2 ** attempt)
            continue
        except (openai.APIConnectionError, openai.APITimeoutError) as e:
            last_error = str(e)
            time.sleep(2 ** attempt)
            continue
        except openai.InternalServerError as e:
            last_error = str(e)
            time.sleep(2 ** attempt)
            continue
        except Exception as e:
            last_error = str(e)
            break

    logger.error(f"LLM call failed after 3 retries: {last_error}")
    return f"分析失敗（API 錯誤）"


# ---------------------------------------------------------------------------
# Persona definitions
# ---------------------------------------------------------------------------

PERSONA_PROMPTS: dict[str, str] = {
    "value": (
        "你是班傑明·葛拉罕（Benjamin Graham）風格的價值投資分析師。\n\n"
        "你的分析哲學：\n"
        "- 看重本益比（PER）、股價淨值比（PBR）、殖利率等基本面指標\n"
        "- 尋找「安全邊際」（margin of safety）\n"
        "- 不追逐熱門股，偏好被低估的優質公司\n"
        "- 對過高的估值保持懷疑\n\n"
        "請根據提供的數據給出評級（BUY / SELL / HOLD）和信心程度（0-100）。\n"
        "回覆格式（嚴格 JSON）：\n"
        '{"rating": "BUY/SELL/HOLD", "confidence": 0-100, "reason": "一句話理由"}'
    ),
    "momentum": (
        "你是動能交易分析師，擅長捕捉市場趨勢。\n\n"
        "你的分析哲學：\n"
        "- 趨勢是你的朋友，順勢而為\n"
        "- 重視 MA 排列、RSI 強弱、MACD 動能\n"
        "- 成交量放大是趨勢確認的關鍵信號\n"
        "- 不在乎估值高低，只在乎動能是否持續\n\n"
        "請根據提供的數據給出評級（BUY / SELL / HOLD）和信心程度（0-100）。\n"
        "回覆格式（嚴格 JSON）：\n"
        '{"rating": "BUY/SELL/HOLD", "confidence": 0-100, "reason": "一句話理由"}'
    ),
    "growth": (
        "你是成長股分析師，專注於公司的成長潛力。\n\n"
        "你的分析哲學：\n"
        "- 尋找營收和獲利高速成長的公司\n"
        "- 高 ROE 和高營收成長比低 PER 更重要\n"
        "- 願意為高品質的成長支付較高估值\n"
        "- 關注公司的競爭優勢和市場擴張能力\n\n"
        "請根據提供的數據給出評級（BUY / SELL / HOLD）和信心程度（0-100）。\n"
        "回覆格式（嚴格 JSON）：\n"
        '{"rating": "BUY/SELL/HOLD", "confidence": 0-100, "reason": "一句話理由"}'
    ),
    "contrarian": (
        "你是逆向投資分析師，在別人恐懼時貪婪。\n\n"
        "你的分析哲學：\n"
        "- 當市場恐慌抛售時尋找機會\n"
        "- RSI 超賣、價格跌破均線可能是買點而非賣訊\n"
        "- 市場往往過度反應短期利空\n"
        "- 尋找基本面尚可但被市場錯殺的標的\n\n"
        "請根據提供的數據給出評級（BUY / SELL / HOLD）和信心程度（0-100）。\n"
        "回覆格式（嚴格 JSON）：\n"
        '{"rating": "BUY/SELL/HOLD", "confidence": 0-100, "reason": "一句話理由"}'
    ),
    "risk_manager": (
        "你是風險控管分析師，負責評估 downside 風險。\n\n"
        "你的分析哲學：\n"
        "- 第一原則：不要賠錢\n"
        "- 評估最大可能跌幅和風險報酬比\n"
        "- 關注波動率、52 週高低點位置\n"
        "- 當市場不確定性高時建議減倉或避險\n\n"
        "請根據提供的數據給出評級（BUY / SELL / HOLD）和信心程度（0-100）。\n"
        "回覆格式（嚴格 JSON）：\n"
        '{"rating": "BUY/SELL/HOLD", "confidence": 0-100, "reason": "一句話理由"}'
    ),
}


def analyze_with_persona(persona: str, system_prompt: str,
                         stock_data: dict) -> dict:
    """Run one persona on a stock and parse the JSON response."""
    # Build a concise data summary for the LLM
    data_lines = [
        f"股票代碼：{stock_data.get('symbol', 'N/A')}",
        f"公司名稱：{stock_data.get('name', 'N/A')}",
        f"現價：{stock_data.get('current', 'N/A')}",
        f"漲跌幅：{stock_data.get('change_pct', 0):+.2f}%",
        "",
        "--- 技術指標 ---",
    ]
    ind = stock_data.get("ind", {})
    if ind:
        data_lines.append(f"MA5: {ind.get('ma5', 'N/A')}")
        data_lines.append(f"MA20: {ind.get('ma20', 'N/A')}")
        data_lines.append(f"RSI(14): {ind.get('rsi', 'N/A')}")
        data_lines.append(f"MACD柱: {ind.get('macd_hist', 'N/A')}")
        data_lines.append(f"布林%B: {ind.get('bb_pct', 'N/A')}")
        data_lines.append(f"KD: K={ind.get('k', 'N/A')} D={ind.get('d', 'N/A')}")
        data_lines.append(f"量比: {ind.get('vol_ratio', 'N/A')}x")

    fund = stock_data.get("fund", {})
    if fund:
        data_lines.append("")
        data_lines.append("--- 基本面 ---")
        data_lines.append(f"PER: {fund.get('per', 'N/A')}")
        data_lines.append(f"PBR: {fund.get('pbr', 'N/A')}")
        data_lines.append(f"殖利率: {fund.get('dividend_yield', 'N/A')}%")
        data_lines.append(f"ROE: {fund.get('roe', 'N/A')}%")
        data_lines.append(f"營收成長: {fund.get('revenue_growth', 'N/A')}%")

    user_prompt = "請分析以下股票數據並給出評級：\n\n" + "\n".join(data_lines)
    raw = _call_llm(system_prompt, user_prompt, max_tokens=512, temperature=0.7)

    # Parse JSON from response
    try:
        # Try to extract JSON block if wrapped in ```json ... ```
        json_str = raw
        if "```json" in raw:
            json_str = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            json_str = raw.split("```")[1].split("```")[0].strip()
        result = json.loads(json_str)
        result["persona"] = persona
        return result
    except (json.JSONDecodeError, KeyError, IndexError):
        logger.warning(f"Persona '{persona}' returned unparseable response: {raw[:200]}")
        return {
            "persona": persona,
            "rating": "HOLD",
            "confidence": 0,
            "reason": "LLM 回應解析失敗",
        }


# ---------------------------------------------------------------------------
# Convenience: ratings weight mapping
# ---------------------------------------------------------------------------

RATING_SCORE = {"BUY": 1, "HOLD": 0, "SELL": -1}
PERSONA_NAMES = {
    "value": "價值型 (葛拉罕)",
    "momentum": "動能型",
    "growth": "成長型",
    "contrarian": "逆向型",
    "risk_manager": "風控型",
}


# ---------------------------------------------------------------------------
# Debate round
# ---------------------------------------------------------------------------

DEBATE_PROMPT = """你是{persona_name}投資分析師。

你已在第一輪分析了 {symbol} 的數據並給出了初步評級。

以下是其他分析師的看法：

{peer_views}

請參考同行觀點，重新評估你的判断。你可以：
- 堅持原有的分析（如果你認為其他人忽略了關鍵因素）
- 調整評級（如果同行提出了你沒有考慮到的觀點）

回覆格式（嚴格 JSON）：
{{"rating": "BUY/SELL/HOLD", "confidence": 0-100, "reason": "一句話理由（可提及是否受同行影響）"}}"""


def build_debate_context(round1_results: list[dict]) -> str:
    """Compile Round 1 results into a debate summary for the LLM."""
    lines = []
    for r in round1_results:
        p = r.get("persona", "?")
        label = PERSONA_NAMES.get(p, p)
        rating = r.get("rating", "HOLD")
        conf = r.get("confidence", 0)
        reason = r.get("reason", "")
        lines.append(f"- [{label}] {rating} (信心 {conf}%): {reason}")
    return "\n".join(lines)


def analyze_with_persona_debate(persona: str, system_prompt: str,
                                 stock_data: dict,
                                 peer_views: str) -> dict:
    """Debate round: persona sees peer analyses and updates their rating.

    Parameters
    ----------
    persona : str            — agent key (e.g. "value")
    system_prompt : str      — the persona's system prompt (PERSONA_PROMPTS[persona])
    stock_data : dict        — same stock data as round 1
    peer_views : str         — ``build_debate_context()`` output

    Returns
    -------
    dict with rating, confidence, reason, persona keys.
    """
    symbol = stock_data.get("symbol", "N/A")
    label = PERSONA_NAMES.get(persona, persona)
    user_prompt = DEBATE_PROMPT.format(
        persona_name=label,
        symbol=symbol,
        peer_views=peer_views,
    )
    raw = _call_llm(system_prompt, user_prompt, max_tokens=512, temperature=0.5)

    try:
        json_str = raw
        if "```json" in raw:
            json_str = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            json_str = raw.split("```")[1].split("```")[0].strip()
        result = json.loads(json_str)
        result["persona"] = persona
        result["debate_round"] = True
        return result
    except (json.JSONDecodeError, KeyError, IndexError):
        logger.warning(f"Persona '{persona}' debate response unparseable: {raw[:200]}")
        return {
            "persona": persona,
            "rating": "HOLD",
            "confidence": 0,
            "reason": "辯論回覆解析失敗",
            "debate_round": True,
        }
