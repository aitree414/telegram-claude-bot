"""
Daily Investment Committee — analysis service.

Runs the 5-agent AI committee on the portfolio holdings and generates
buy/sell proposals.  Results are stored as JSON for the web dashboard
and can be pushed to Telegram.

Usage
-----
    python -m ai_quant.committee_service --daily    # Full daily run
    python -m ai_quant.committee_service --quick    # Quick run (fallback only)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_quant.strategies.committee import run_committee, _result_to_dict
from ai_quant.strategies.agents import Signal
from ai_quant.utils.data_loader import load_single

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_FILE = Path(os.getenv("PORTFOLIO_FILE", str(Path.home() / "Documents/investment/config/portfolio.json")))
RESULTS_DIR = PROJECT_ROOT / "data" / "committee"
RESULTS_FILE = RESULTS_DIR / "daily_signals.json"
HISTORY_DIR = RESULTS_DIR / "history"

# ── Portfolio Holdings ────────────────────────────────────────────────────


def load_portfolio() -> list[dict]:
    """Load portfolio holdings from JSON."""
    if not PORTFOLIO_FILE.exists():
        logger.warning("Portfolio file not found: %s", PORTFOLIO_FILE)
        return _default_portfolio()
    try:
        data = json.loads(PORTFOLIO_FILE.read_text())
        return data.get("tw_stocks", [])
    except Exception as e:
        logger.error("Failed to load portfolio: %s", e)
        return _default_portfolio()


def _default_portfolio() -> list[dict]:
    """Fallback portfolio if file not found."""
    return [
        {"code": "2317", "name": "鴻海", "shares": 2000, "cost": 250.50},
        {"code": "2327", "name": "國巨", "shares": 2000, "cost": 271.25},
        {"code": "2330", "name": "台積電", "shares": 100, "cost": 1940.00},
        {"code": "2331", "name": "精英", "shares": 1000, "cost": 38.89},
        {"code": "2356", "name": "英業達", "shares": 1000, "cost": 64.80},
        {"code": "2454", "name": "聯發科", "shares": 300, "cost": 1273.26},
        {"code": "2515", "name": "中工", "shares": 10000, "cost": 13.40},
        {"code": "2618", "name": "長榮航", "shares": 12000, "cost": 44.07},
        {"code": "2881", "name": "富邦金", "shares": 168, "cost": 50.91},
        {"code": "2887", "name": "台新新光金", "shares": 3000, "cost": 19.70},
        {"code": "3042", "name": "晶技", "shares": 2000, "cost": 112.30},
        {"code": "3529", "name": "力旺", "shares": 20, "cost": 3163.00},
        {"code": "3680", "name": "家登", "shares": 100, "cost": 576.20},
        {"code": "4506", "name": "崇友", "shares": 2000, "cost": 73.70},
        {"code": "4532", "name": "瑞智", "shares": 5000, "cost": 31.04},
        {"code": "6139", "name": "亞翔", "shares": 200, "cost": 612.00},
        {"code": "6180", "name": "橘子", "shares": 1000, "cost": 72.90},
    ]


# ── Committee Analysis ────────────────────────────────────────────────────


# OTC stocks (櫃買) use .TWO suffix instead of .TW
OTC_STOCKS = {"3529", "6180", "4506", "3680"}  # 力旺, 橘子, 崇友, 家登


def resolve_committee_ticker(code: str) -> str:
    """Resolve ticker symbol, handling OTC stocks."""
    if code in OTC_STOCKS:
        return code + ".TWO"
    return code  # data_loader.resolve_ticker handles .TW for TSE stocks


# ── Technical Analysis Helpers ─────────────────────────────────────────────


def _sma(values: list, period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _calc_rsi(closes: list, period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(-period - 1, -1):
        diff = closes[i + 1] - closes[i]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def _calc_macd(closes: list) -> dict:
    if len(closes) < 35:
        return {"macd": 0, "signal": 0, "histogram": 0}
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    if ema12 is None or ema26 is None:
        return {"macd": 0, "signal": 0, "histogram": 0}
    macd_val = ema12 - ema26
    signal_line = _ema([_ema(closes[:i+1], 12) - _ema(closes[:i+1], 26)
                        for i in range(25, len(closes))
                        if _ema(closes[:i+1], 12) and _ema(closes[:i+1], 26)], 9) or macd_val
    return {"macd": round(macd_val, 2), "signal": round(signal_line, 2),
            "histogram": round(macd_val - signal_line, 2)}


def _ema(values: list, period: int) -> Optional[float]:
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    result = sum(values[:period]) / period
    for v in values[period:]:
        result = (v - result) * multiplier + result
    return result


def get_technical_signals(code: str, days: int = 90) -> dict:
    """Compute real-time technical indicators from yfinance data."""
    ticker = resolve_committee_ticker(code)
    start = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")

    data = load_single(ticker, start=start, end=date.today().strftime("%Y-%m-%d"), interval="1d")
    if data.empty or "Close" not in data.columns:
        return {"error": "no data", "signal": "hold", "score": 0}

    closes = data["Close"].dropna().tolist()
    if len(closes) < 20:
        return {"error": "insufficient data", "signal": "hold", "score": 0}

    current_price = closes[-1]
    ma5 = _sma(closes, 5)
    ma20 = _sma(closes, 20)
    ma60 = _sma(closes, 60)
    rsi = _calc_rsi(closes)
    macd = _calc_macd(closes)

    # Volume analysis
    volumes = data["Volume"].dropna().tolist() if "Volume" in data.columns else []
    vol_ma20 = _sma(volumes, 20) if len(volumes) >= 20 else None
    volume_ratio = round(volumes[-1] / vol_ma20, 2) if (vol_ma20 and vol_ma20 > 0) else None

    # Scoring (-100 to +100)
    score = 0
    details = []

    # RSI
    if rsi is not None:
        if rsi < 35:
            score += 30
            details.append(f"RSI({rsi})超賣區")
        elif rsi > 70:
            score -= 30
            details.append(f"RSI({rsi})超買區")
        elif rsi > 55:
            score += 15
            details.append(f"RSI({rsi})偏多")
        elif rsi < 45:
            score -= 10
            details.append(f"RSI({rsi})偏空")
        else:
            details.append(f"RSI({rsi})中性")

    # MA trend
    if ma5 is not None and ma20 is not None:
        if ma5 > ma20:
            score += 20
            details.append(f"MA5({ma5:.0f})>MA20({ma20:.0f})多頭")
        else:
            score -= 20
            details.append(f"MA5({ma5:.0f})<MA20({ma20:.0f})空頭")

    # Price vs MA20
    if ma20 is not None and current_price > ma20:
        score += 15
        details.append(f"價>MA20")
    elif ma20 is not None:
        score -= 15
        details.append(f"價<MA20")

    # MACD
    if macd["histogram"] > 0:
        score += 15
        details.append("MACD柱向上")
    else:
        score -= 15
        details.append("MACD柱向下")

    # Volume
    if volume_ratio is not None:
        if volume_ratio > 1.5:
            score += 10 if score > 0 else -5
            details.append(f"量增({volume_ratio}x)")
        elif volume_ratio < 0.5:
            score -= 5
            details.append(f"量縮({volume_ratio}x)")

    # Determine signal
    if score >= 30:
        signal = "buy"
    elif score <= -30:
        signal = "sell"
    else:
        signal = "hold"

    return {
        "signal": signal,
        "score": score,
        "rsi": rsi,
        "ma5": round(ma5, 1) if ma5 else None,
        "ma20": round(ma20, 1) if ma20 else None,
        "ma60": round(ma60, 1) if ma60 else None,
        "macd": macd,
        "volume_ratio": volume_ratio,
        "current_price": current_price,
        "details": details,
    }


def analyze_stock(
    code: str,
    name: str,
    days: int = 90,
    fallback: bool = False,
    deepseek_key: Optional[str] = None,
) -> dict:
    """Run the AI committee + technical analysis on a single stock.

    Combines backtest-based committee signals with real-time technical
    indicators for a more actionable recommendation.
    """
    ticker = resolve_committee_ticker(code)
    start = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        # ---- Step 1: Committee backtest ----
        committee_result = None
        try:
            committee_result = run_committee(
                ticker=ticker,
                start=start,
                end=date.today().strftime("%Y-%m-%d"),
                interval="1d",
                fallback=fallback or not deepseek_key,
                initial_capital=100000.0,
                commission=0.001425,
                use_claude=False,
                use_macro=True,
                use_sentiment=not fallback,
                deepseek_api_key=deepseek_key,
            )
            metrics = _result_to_dict(committee_result)
            bt_signals = _extract_latest_signals(committee_result, code, name)
        except SystemExit:
            logger.warning("No committee data for %s (%s), using tech-only", code, name)
            metrics = {}
            bt_signals = [{"action": "hold", "confidence": 0.3, "reason": "回測無數據",
                           "sharpe_ratio": 0, "total_return_pct": 0,
                           "max_drawdown_pct": 0, "win_rate": 0, "total_trades": 0}]

        # ---- Step 2: Real-time technical analysis ----
        tech = get_technical_signals(code, days)

        # ---- Step 3: Combined signal ----
        final_action, final_confidence, final_reason = _combine_signals(bt_signals, tech)

        combined_signals = [{
            "action": final_action,
            "confidence": round(final_confidence, 2),
            "reason": final_reason,
            # Include backtest metrics for reference
            "sharpe_ratio": metrics.get("sharpe_ratio", 0),
            "total_return_pct": metrics.get("total_return_pct", 0),
            "max_drawdown_pct": metrics.get("max_drawdown_pct", 0),
            "win_rate": metrics.get("win_rate", 0),
            "total_trades": metrics.get("total_trades", 0),
        }]

        return {
            "code": code,
            "name": name,
            "status": "ok",
            "signals": combined_signals,
            "metrics": metrics,
            "technical": tech,
            "analyzed_at": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error("Analysis failed for %s (%s): %s", code, name, e)
        return {
            "code": code,
            "name": name,
            "status": "error",
            "error": str(e),
            "signals": [],
            "metrics": {},
            "technical": {},
            "analyzed_at": datetime.now().isoformat(),
        }


def _combine_signals(bt_signals: list[dict], tech: dict) -> tuple:
    """Combine backtest signals with technical analysis for final recommendation.

    Returns (action, confidence, reason).
    """
    # Default from backtest
    bt_action = "hold"
    bt_confidence = 0.5
    bt_reason = ""
    if bt_signals:
        bt_action = bt_signals[0].get("action", "hold")
        bt_confidence = bt_signals[0].get("confidence", 0.5)
        bt_reason = bt_signals[0].get("reason", "")

    tech_signal = tech.get("signal", "hold")
    tech_score = tech.get("score", 0)
    tech_details = tech.get("details", [])

    # Scoring grid: tech_score ranges -100 to +100
    if tech_signal == "buy" and bt_action in ("strong_buy", "buy"):
        action = "strong_buy"
        confidence = min(0.95, bt_confidence + 0.2)
        reason = f"技術面(分數{tech_score}) + 回測({bt_reason})"
    elif tech_signal == "sell" and bt_action in ("strong_sell", "sell"):
        action = "strong_sell"
        confidence = min(0.95, bt_confidence + 0.2)
        reason = f"技術面(分數{tech_score}) + 回測({bt_reason})"
    elif tech_signal == "buy" and bt_action in ("hold",):
        action = "buy"
        confidence = 0.65
        reason = f"技術面偏多(分數{tech_score})"
        if tech_details:
            reason += f" [{'; '.join(tech_details[:2])}]"
    elif tech_signal == "sell" and bt_action in ("hold",):
        action = "sell"
        confidence = 0.65
        reason = f"技術面偏空(分數{tech_score})"
        if tech_details:
            reason += f" [{'; '.join(tech_details[:2])}]"
    elif bt_action in ("buy", "sell") and abs(tech_score) < 15:
        # Backtest says something but tech is neutral — trust backtest
        action = bt_action
        confidence = bt_confidence * 0.8
        reason = bt_reason
    else:
        action = bt_action if bt_action != "hold" else "hold"
        confidence = bt_confidence
        reason = bt_reason or f"技術分數{tech_score}，觀望"

    return action, confidence, reason


def _extract_latest_signals(result, code: str, name: str) -> list[dict]:
    """Extract actionable signals from backtest results.

    Uses metrics to derive recommendations:
    - Strong Buy: high Sharpe, positive return, low drawdown
    - Buy: positive signals
    - Hold: mixed
    - Sell: negative signals
    - Strong Sell: poor metrics
    """
    signals = []

    sr = result.sharpe_ratio
    ret = result.total_return_pct
    dd = result.max_drawdown_pct
    wr = result.win_rate
    trades = result.total_trades

    # Determine signal based on committee performance
    # For low-trade fallback, use Sharpe + return thresholds
    if trades >= 3 and sr > 1.0 and ret > 5:
        action = "strong_buy"
        confidence = min(abs(sr) / 2, 0.95)
        reason = f"Sharpe {sr:.2f}, 報酬 {ret:+.1f}%, 勝率 {wr:.0f}%"
    elif trades >= 2 and sr > 0.5 and ret > 0:
        action = "buy"
        confidence = min(abs(sr) / 3, 0.75)
        reason = f"Sharpe {sr:.2f}, 報酬 {ret:+.1f}%"
    elif trades == 1 and sr > 2.0 and ret > 3:
        # Single trade: strong positive → buy
        action = "buy"
        confidence = min(abs(sr) / 5, 0.6)
        reason = f"Sharpe {sr:.2f}, 報酬 {ret:+.1f}%, 勝率 {wr:.0f}%"
    elif trades >= 2 and sr < -0.5 and ret < -3:
        action = "sell"
        confidence = min(abs(sr) / 3, 0.75)
        reason = f"Sharpe {sr:.2f}, 報酬 {ret:+.1f}%, 最大回撤 {dd:.1f}%"
    elif trades >= 3 and sr < -1.0 and ret < -8:
        action = "strong_sell"
        confidence = min(abs(sr) / 2, 0.95)
        reason = f"Sharpe {sr:.2f}, 報酬 {ret:+.1f}%, 回撤 {dd:.1f}%"
    elif trades == 1 and sr < -5.0 and ret < -5:
        # Single trade: strong negative → sell
        action = "sell"
        confidence = min(abs(sr) / 5, 0.6)
        reason = f"Sharpe {sr:.2f}, 報酬 {ret:+.1f}%, 回撤 {dd:.1f}%"
    else:
        action = "hold"
        confidence = 0.5
        reason = f"Sharpe {sr:.2f}, 報酬 {ret:+.1f}%, 交易 {trades} 次"

    signals.append({
        "action": action,
        "confidence": round(confidence, 2),
        "reason": reason,
        "sharpe_ratio": round(sr, 2),
        "total_return_pct": round(ret, 2),
        "max_drawdown_pct": round(dd, 2),
        "win_rate": round(wr, 1),
        "total_trades": trades,
    })

    return signals


# ── Batch Analysis ────────────────────────────────────────────────────────


def run_daily_analysis(fallback: bool = False) -> list[dict]:
    """Run the committee on all portfolio holdings."""
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if not deepseek_key:
        logger.warning("DEEPSEEK_API_KEY not set — using fallback mode")
        fallback = True

    holdings = load_portfolio()
    logger.info("Running daily committee analysis on %d holdings", len(holdings))

    results = []
    for i, h in enumerate(holdings, 1):
        logger.info("[%d/%d] Analyzing %s (%s)...", i, len(holdings), h["name"], h["code"])
        result = analyze_stock(
            code=h["code"],
            name=h["name"],
            days=90,
            fallback=fallback,
            deepseek_key=deepseek_key,
        )
        results.append(result)

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    output = {
        "date": date.today().isoformat(),
        "generated_at": datetime.now().isoformat(),
        "fallback_mode": fallback,
        "total_stocks": len(results),
        "stocks": results,
        "summary": generate_summary(results),
    }

    RESULTS_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2))

    # Save history
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    history_file = HISTORY_DIR / f"{date.today().isoformat()}.json"
    history_file.write_text(json.dumps(output, ensure_ascii=False, indent=2))

    logger.info("Results saved to %s", RESULTS_FILE)
    return results


def generate_summary(results: list[dict]) -> dict:
    """Generate a summary of today's analysis."""
    strong_buys = [r for r in results if any(s["action"] == "strong_buy" for s in r.get("signals", []))]
    buys = [r for r in results if any(s["action"] == "buy" for s in r.get("signals", []))]
    holds = [r for r in results if any(s["action"] == "hold" for s in r.get("signals", []))]
    sells = [r for r in results if any(s["action"] == "sell" for s in r.get("signals", []))]
    strong_sells = [r for r in results if any(s["action"] == "strong_sell" for s in r.get("signals", []))]
    errors = [r for r in results if r.get("status") == "error"]

    return {
        "total_analyzed": len(results),
        "strong_buy_count": len(strong_buys),
        "buy_count": len(buys),
        "hold_count": len(holds),
        "sell_count": len(sells),
        "strong_sell_count": len(strong_sells),
        "error_count": len(errors),
        "strong_buys": [{"code": r["code"], "name": r["name"]} for r in strong_buys],
        "buys": [{"code": r["code"], "name": r["name"]} for r in buys],
        "holds": [{"code": r["code"], "name": r["name"]} for r in holds],
        "sells": [{"code": r["code"], "name": r["name"]} for r in sells],
        "strong_sells": [{"code": r["code"], "name": r["name"]} for r in strong_sells],
    }


# ── CLI ───────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="AI Investment Committee — Daily Analysis")
    parser.add_argument("--daily", action="store_true", help="Full daily analysis")
    parser.add_argument("--quick", action="store_true", help="Quick analysis (fallback only)")
    parser.add_argument("--ticker", type=str, default=None, help="Single stock to analyze")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.ticker:
        # Single stock analysis
        from ai_quant.utils.data_loader import resolve_ticker
        ticker = resolve_ticker(args.ticker)
        name = args.ticker
        result = analyze_stock(ticker, name, fallback=args.quick or not os.getenv("DEEPSEEK_API_KEY"))
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"\n=== {result['name']} ({result['code']}) ===")
            print(f"Status: {result['status']}")
            for s in result.get("signals", []):
                print(f"Signal: {s['action']} (confidence: {s['confidence']})")
                print(f"Reason: {s['reason']}")
            print(f"Sharpe: {result.get('metrics', {}).get('sharpe_ratio', 'N/A')}")
        return

    # Run daily analysis
    fallback = args.quick or not os.getenv("DEEPSEEK_API_KEY")
    results = run_daily_analysis(fallback=fallback)

    summary = generate_summary(results)
    print("\n" + "=" * 60)
    print(f"  AI 投資委員會 — 每日分析報告 ({date.today()})")
    print("=" * 60)
    print(f"  強力買入: {summary['strong_buy_count']} 檔")
    print(f"  買入:     {summary['buy_count']} 檔")
    print(f"  持有:     {summary['hold_count']} 檔")
    print(f"  賣出:     {summary['sell_count']} 檔")
    print(f"  強力賣出: {summary['strong_sell_count']} 檔")
    if summary['error_count']:
        print(f"  分析失敗: {summary['error_count']} 檔")
    print("=" * 60)

    if summary['strong_buys']:
        print("\n🟢 強力買入建議:")
        for s in summary['strong_buys']:
            print(f"  {s['code']} {s['name']}")
    if summary['buys']:
        print("\n🔵 買入建議:")
        for s in summary['buys']:
            print(f"  {s['code']} {s['name']}")
    if summary['sells']:
        print("\n🔴 賣出建議:")
        for s in summary['sells']:
            print(f"  {s['code']} {s['name']}")
    if summary['strong_sells']:
        print("\n⛔ 強力賣出建議:")
        for s in summary['strong_sells']:
            print(f"  {s['code']} {s['name']}")

    if args.json:
        print(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
