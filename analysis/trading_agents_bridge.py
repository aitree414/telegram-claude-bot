"""Bridge between Investree and the TradingAgents multi-agent trading framework.

Runs TradingAgents in an isolated Python 3.13 subprocess (``.venv-ta/``) and
returns a standardised dict compatible with the existing persona pipeline.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Path to the Python 3.13 venv that has tradingagents installed
_VENV_PYTHON = str(
    Path(__file__).resolve().parent.parent / ".venv-ta" / "bin" / "python3"
)

# ---------------------------------------------------------------------------
# 5-tier → 3-tier mapping (TradingAgents → Investree)
# ---------------------------------------------------------------------------
_TIER_MAP = {
    "Buy": "BUY",
    "Overweight": "BUY",
    "Hold": "HOLD",
    "Underweight": "SELL",
    "Sell": "SELL",
}

_CONFIDENCE_MAP = {
    "Buy": 90,
    "Overweight": 70,
    "Hold": 50,
    "Underweight": 30,
    "Sell": 10,
}

_SCRIPT_TEMPLATE = """\
import json, os, sys

# Configure API keys from environment
os.environ["DEEPSEEK_API_KEY"] = {deepseek_key!r}

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = {provider!r}
config["deep_think_llm"] = {deep_think_model!r}
config["quick_think_llm"] = {quick_think_model!r}
config["checkpoint_enabled"] = False
config["output_language"] = "en"
config["max_debate_rounds"] = {debate_rounds}
config["data_vendors"] = {{"core_stock_apis": "yfinance", "technical_indicators": "yfinance", "fundamental_data": "yfinance", "news_data": "yfinance"}}

ta = TradingAgentsGraph(debug=False, config=config)
try:
    final_state, signal = ta.propagate({ticker!r}, {trade_date!r})
except Exception as e:
    print(json.dumps({{"error": str(e), "error_type": type(e).__name__}}))
    sys.exit(1)

# Extract key info from final state
result = {{
    "signal": signal,
    "fundamentals_report": final_state.get("fundamentals_report", ""),
    "sentiment_report": final_state.get("sentiment_report", ""),
    "news_report": final_state.get("news_report", ""),
    "market_report": final_state.get("market_report", ""),
    "trader_decision": final_state.get("trader_investment_plan", ""),
    "risk_decision": final_state.get("investment_plan", ""),
    "final_trade_decision": final_state.get("final_trade_decision", ""),
    "debate_judge": final_state.get("investment_debate_state", {{}}).get("judge_decision", ""),
}}
print(json.dumps(result))
"""


def _get_config() -> dict:
    """Resolve TradingAgents config from environment, with sensible defaults."""
    provider = os.environ.get("TRADINGAGENTS_LLM_PROVIDER", "deepseek")

    model_map = {
        "deepseek": ("deepseek-chat", "deepseek-chat"),
        "openai": ("gpt-4o", "gpt-4o-mini"),
        "anthropic": ("claude-sonnet-4-6", "claude-haiku-4-5"),
    }

    deep_think, quick_think = model_map.get(
        provider,
        (f"{provider}-chat", f"{provider}-chat"),
    )

    # Allow per-model overrides via env
    deep_think = os.environ.get("TRADINGAGENTS_DEEP_THINK_LLM", deep_think)
    quick_think = os.environ.get("TRADINGAGENTS_QUICK_THINK_LLM", quick_think)

    return {
        "provider": provider,
        "deep_think_model": deep_think,
        "quick_think_model": quick_think,
        "debate_rounds": int(os.environ.get("TRADINGAGENTS_DEBATE_ROUNDS", "1")),
        "timeout": int(os.environ.get("TRADINGAGENTS_TIMEOUT", "300")),
    }


def analyze_with_trading_agents(
    ticker: str,
    trade_date: Optional[str] = None,
) -> dict:
    """Run TradingAgents multi-agent analysis on a stock.

    Parameters
    ----------
    ticker : str
        Stock ticker symbol (e.g. ``"AAPL"``, ``"2330.TW"``).
    trade_date : str or None
        Analysis date in ``"YYYY-MM-DD"`` format.  Defaults to today.

    Returns
    -------
    dict with keys compatible with the persona pipeline:
        persona       -> ``"trading_agents"``
        rating        -> ``"BUY"`` / ``"SELL"`` / ``"HOLD"``
        confidence    -> int 0..100
        reason        -> short summary of the TA decision
        details       -> full TradingAgents output (raw reports, debates, etc.)
        ta_signal     -> original 5-tier signal
        elapsed       -> seconds taken
        error         -> error message if failed
    """
    if not os.environ.get("TRADINGAGENTS_ENABLED", "").lower() == "true":
        return {
            "persona": "trading_agents",
            "rating": "HOLD",
            "confidence": 0,
            "reason": "TradingAgents 未啟用 (TRADINGAGENTS_ENABLED != true)",
            "ta_signal": "Hold",
        }

    if not trade_date:
        from datetime import date

        trade_date = str(date.today())

    ta_config = _get_config()
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
    venv_python = os.environ.get("TRADINGAGENTS_PYTHON", _VENV_PYTHON)

    if not os.path.isfile(venv_python):
        return {
            "persona": "trading_agents",
            "rating": "HOLD",
            "confidence": 0,
            "reason": f"TradingAgents venv not found at {venv_python}",
            "ta_signal": "Hold",
        }

    # Build the inline script
    script = _SCRIPT_TEMPLATE.format(
        ticker=ticker,
        trade_date=trade_date,
        deepseek_key=deepseek_key,
        provider=ta_config["provider"],
        deep_think_model=ta_config["deep_think_model"],
        quick_think_model=ta_config["quick_think_model"],
        debate_rounds=ta_config["debate_rounds"],
    )

    t0 = time.time()
    try:
        proc = subprocess.run(
            [venv_python, "-c", script],
            capture_output=True,
            text=True,
            timeout=ta_config["timeout"],
            env={**os.environ, "TRADINGAGENTS_ENABLED": "true"},
        )
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        logger.warning("TradingAgents timed out after %.0fs for %s", elapsed, ticker)
        return {
            "persona": "trading_agents",
            "rating": "HOLD",
            "confidence": 0,
            "reason": f"TradingAgents 分析超時 ({elapsed:.0f}s)",
            "ta_signal": "Hold",
            "elapsed": elapsed,
        }
    except FileNotFoundError:
        return {
            "persona": "trading_agents",
            "rating": "HOLD",
            "confidence": 0,
            "reason": f"Python interpreter not found: {venv_python}",
            "ta_signal": "Hold",
        }

    elapsed = time.time() - t0

    if proc.returncode != 0:
        # Try to parse error from stdout first
        try:
            err_data = json.loads(proc.stdout)
            error_msg = err_data.get("error", proc.stderr[:500])
        except (json.JSONDecodeError, ValueError):
            error_msg = (proc.stderr or proc.stdout)[:500]

        logger.error(
            "TradingAgents failed for %s (rc=%d): %s",
            ticker, proc.returncode, error_msg,
        )
        return {
            "persona": "trading_agents",
            "rating": "HOLD",
            "confidence": 0,
            "reason": f"TradingAgents 分析失敗: {error_msg[:200]}",
            "ta_signal": "Hold",
            "error": error_msg,
            "elapsed": elapsed,
        }

    # Parse JSON result
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        logger.error(
            "TradingAgents JSON parse error for %s: %s\nstdout=%s",
            ticker, e, proc.stdout[:500],
        )
        return {
            "persona": "trading_agents",
            "rating": "HOLD",
            "confidence": 0,
            "reason": "TradingAgents 回傳解析失敗",
            "ta_signal": "Hold",
            "elapsed": elapsed,
        }

    signal = result.get("signal", "Hold")
    rating = _TIER_MAP.get(signal, "HOLD")
    confidence = _CONFIDENCE_MAP.get(signal, 50)

    # Build a concise reason from the raw reports
    fragments = []
    if result.get("market_report"):
        fragments.append(result["market_report"][:200])
    if result.get("trader_decision"):
        fragments.append(result["trader_decision"][:200])
    reason = " | ".join(fragments)[:300] if fragments else f"TA 評級: {signal}"

    return {
        "persona": "trading_agents",
        "rating": rating,
        "confidence": confidence,
        "reason": reason,
        "ta_signal": signal,
        "details": result,
        "elapsed": elapsed,
    }
