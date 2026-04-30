"""Portfolio Manager Agent — the central decision-maker.

Collects signals from every subsystem:
1. Stock scan (technical / fundamental scores)
2. On-chain signal generator
3. Nightly backtest best strategy
4. Polymarket insights
5. Price alerts (recent triggered events)

Then uses an LLM to synthesise a unified recommendation.
"""

import json
import logging
import os
from datetime import datetime, date
from pathlib import Path
from typing import Any, Optional

import openai

from analysis.persona_agents import _call_deepseek

logger = logging.getLogger(__name__)


def _load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        logger.exception(f"Failed to load {path}")
    return {}


def _get_nightly_best_strategy() -> str:
    """Read the best strategy from last night's backtest."""
    report_dir = Path(__file__).parent.parent / "reports" / "nightly_backtest"
    today_str = date.today().strftime("%Y%m%d")

    # Try today first, then walk backwards a few days
    for days_ago in range(7):
        target = report_dir / f"backtest_data_{date.today().isoformat().replace('-', '')}"
        # Actually the format is YYYYMMDD
        from datetime import timedelta
        d = date.today() - timedelta(days=days_ago)
        candidate = report_dir / f"backtest_data_{d.strftime('%Y%m%d')}.json"
        if candidate.exists():
            data = _load_json(candidate)
            best = data.get("best_strategy")
            if best:
                return best
    return "無可用回測資料"


class PortfolioManagerAgent:
    """Synthesises signals from all subsystems into unified recommendations."""

    def __init__(self):
        self._best_strategy_cache: Optional[str] = None
        self._cache_date: Optional[date] = None

    # ------------------------------------------------------------------
    # Signal sources
    # ------------------------------------------------------------------

    def get_best_strategy(self) -> str:
        """Cached nightly best strategy (refreshes once per day)."""
        today = date.today()
        if self._cache_date != today:
            self._best_strategy_cache = _get_nightly_best_strategy()
            self._cache_date = today
        return self._best_strategy_cache or "無"

    def get_stock_signals(self, scan_results: list[dict]) -> list[dict]:
        """Extract signal from stock scan results."""
        signals = []
        for r in scan_results:
            signals.append({
                "source": "stock_scan",
                "symbol": r.get("symbol"),
                "name": r.get("name"),
                "tech_score": r.get("tech_score"),
                "fund_score": r.get("fund_score"),
                "current": r.get("current"),
            })
        return signals

    def get_onchain_summary(self, orchestrator) -> dict:
        """Get a digest of on-chain activity."""
        try:
            status = orchestrator.get_status()
            return {
                "source": "onchain",
                "running": status.get("is_running", False),
                "total_signals": status.get("stats", {}).get("total_signals_processed", 0),
                "successful_trades": status.get("stats", {}).get("successful_trades", 0),
                "wallet": status.get("wallet_address", "none"),
            }
        except Exception:
            return {"source": "onchain", "error": "unavailable"}

    # ------------------------------------------------------------------
    # LLM synthesis
    # ------------------------------------------------------------------

    def synthesize(
        self,
        scan_results: list[dict],
        orchestrator=None,
    ) -> str:
        """Produce a human-readable consolidated market briefing.

        Parameters
        ----------
        scan_results : list[dict]
            Results from ``stock.scan_strong_stocks(…)`` raw data.
        orchestrator : TradeOrchestrator or None

        Returns
        -------
        Markdown-formatted briefing string.
        """
        today = datetime.now().strftime("%Y-%m-%d %H:%M")
        best_strategy = self.get_best_strategy()
        stock_signals = self.get_stock_signals(scan_results)
        onchain = self.get_onchain_summary(orchestrator) if orchestrator else {}

        # Build prompt
        lines = [f"日期：{today}", ""]

        # Stock signals
        if stock_signals:
            lines.append("--- 股票掃描信號 ---")
            for s in stock_signals[:8]:
                lines.append(
                    f"{s['symbol']} {s.get('name','')} | "
                    f"技術{s.get('tech_score','?')}/8 | "
                    f"基本面{s.get('fund_score','?')}/100"
                )
        else:
            lines.append("--- 股票掃描：無數據 ---")

        lines.append("")
        lines.append(f"--- 夜間回測最佳策略 ---")
        lines.append(best_strategy)

        if onchain and "error" not in onchain:
            lines.append("")
            lines.append("--- 鏈上活動 ---")
            lines.append(f"處理信號：{onchain.get('total_signals', 0)}")
            lines.append(f"成功交易：{onchain.get('successful_trades', 0)}")

        prompt = (
            "你是專業的投資組合經理，請根據以下數據給出今日的投資建議。\n"
            "請用繁體中文，格式簡潔，包含：\n"
            "1. 市場整體看法（一句話）\n"
            "2. 最值得關注的 2-3 個標的\n"
            "3. 風險提醒（如有）\n"
            "4. 今日操作建議（增倉/減倉/持有）\n\n"
            + "\n".join(lines)
        )

        raw = _call_deepseek(
            system_prompt=(
                "你是一個謹慎的投資組合經理。你的建議必須保守、有理有據。"
                "每次回覆控制在 200 字以內。"
            ),
            user_prompt=prompt,
            max_tokens=1024,
            temperature=0.5,
        )

        header = (
            f"📋 投資組合日報 — {today}\n"
            f"{'=' * 30}\n\n"
        )
        return header + raw
