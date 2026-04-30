"""LLM-powered investor persona agents for multi-perspective stock analysis.

Each agent adopts a distinct investment philosophy and analyzes the same
market data independently, producing diverse signals that feed into
the portfolio manager.
"""

import json
import logging
import os
import time
from typing import Optional

import openai

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lightweight DeepSeek caller (no session/tool overhead like ClaudeClient)
# ---------------------------------------------------------------------------

def _call_deepseek(system_prompt: str, user_prompt: str,
                   max_tokens: int = 1024, temperature: float = 0.7) -> str:
    """Single-turn DeepSeek chat call with retry."""
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        return "錯誤：未設定 DEEPSEEK_API_KEY"

    client = openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")
    last_error = ""

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="deepseek-chat",
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

    logger.error(f"DeepSeek call failed after 3 retries: {last_error}")
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
    raw = _call_deepseek(system_prompt, user_prompt, max_tokens=512, temperature=0.7)

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
