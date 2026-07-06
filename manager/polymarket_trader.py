"""Polymarket auto-trader — runs strategies and executes on CLOB.

Orchestration flow
-------------------
1. Fetch active binary markets from Gamma API
2. Run each registered strategy (NEH, PairCostArb, …)
3. Filter signals by confidence & portfolio limits
4. Execute signals via CLOB client
5. Track positions & P&L
6. Report results
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from bot.polymarket_clob import PolymarketCLOB
from strategies.polymarket_base import BaseStrategy, StrategyResult, TradeSignal
from strategies.polymarket_neh import NEHStrategy
from strategies.polymarket_arb import PairCostArbStrategy
from strategies.polymarket_value import ValueHunterStrategy
from manager.portfolio_risk import PortfolioRiskManager

logger = logging.getLogger(__name__)


class PolymarketTraderConfig:
    """Read-only config from env with sensible defaults."""

    @property
    def enabled(self) -> bool:
        return os.environ.get("POLYMARKET_TRADER_ENABLED", "false").lower() == "true"

    @property
    def min_confidence(self) -> float:
        """Minimum confidence to execute a trade (0-1)."""
        return float(os.environ.get("POLYMARKET_MIN_CONFIDENCE", "0.7"))

    @property
    def max_daily_trades(self) -> int:
        return int(os.environ.get("POLYMARKET_MAX_DAILY_TRADES", "10"))

    @property
    def max_daily_spend_usdc(self) -> float:
        return float(os.environ.get("POLYMARKET_MAX_DAILY_SPEND", "100.0"))

    @property
    def max_per_market_usdc(self) -> float:
        return float(os.environ.get("POLYMARKET_MAX_PER_MARKET", "20.0"))

    @property
    def dry_run(self) -> bool:
        """If true, log orders without executing."""
        return os.environ.get("POLYMARKET_DRY_RUN", "false").lower() == "true"

    @property
    def scan_interval_minutes(self) -> int:
        return int(os.environ.get("POLYMARKET_SCAN_INTERVAL", "60"))

    @property
    def enable_neh(self) -> bool:
        return os.environ.get("POLYMARKET_ENABLE_NEH", "true").lower() == "true"

    @property
    def enable_arb(self) -> bool:
        return os.environ.get("POLYMARKET_ENABLE_ARB", "true").lower() == "true"


class PolymarketTrader:
    """Orchestrates strategy evaluation and trade execution on Polymarket.

    Usage
    -----
    >>> trader = PolymarketTrader()
    >>> result = trader.run_cycle()
    >>> print(result.summary())
    """

    def __init__(self, clob_client: Optional[PolymarketCLOB] = None,
                 strategies: Optional[list[BaseStrategy]] = None,
                 risk_manager: Optional[PortfolioRiskManager] = None):
        self.config = PolymarketTraderConfig()
        self.clob = clob_client or PolymarketCLOB()
        self.strategies = strategies or self._default_strategies()
        self.risk_manager = risk_manager
        self._state_file = Path(__file__).parent.parent / "data" / "polymarket_state.json"
        self._state = self._load_state()

    def _default_strategies(self) -> list[BaseStrategy]:
        strategies = []
        if self.config.enable_neh:
            strategies.append(NEHStrategy(clob_client=self.clob))
        if self.config.enable_arb:
            strategies.append(PairCostArbStrategy(clob_client=self.clob))
        # ValueHunter is always active — it's a simple safety net
        strategies.append(ValueHunterStrategy())
        return strategies

    # ── State persistence ──────────────────────

    def _load_state(self) -> dict:
        try:
            if self._state_file.exists():
                return json.loads(self._state_file.read_text())
        except Exception:
            logger.exception("Failed to load polymarket state")
        return self._default_state()

    def _default_state(self) -> dict:
        return {
            "enabled": self.config.enabled,
            "date": str(date.today()),
            "trades_today": 0,
            "spend_today": 0.0,
            "total_trades": 0,
            "total_pnl": 0.0,
            "last_scan": None,
            "history": [],
            "positions": [],
            "executed_markets": [],  # slugs already traded (avoid duplicates)
        }

    def _save_state(self) -> None:
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(json.dumps(self._state, indent=2))
        except Exception:
            logger.exception("Failed to save polymarket state")

    def _check_reset(self) -> None:
        today = str(date.today())
        if self._state.get("date") != today:
            self._state["trades_today"] = 0
            self._state["spend_today"] = 0.0
            self._state["date"] = today

    # ── Core cycle ─────────────────────────────

    def run_cycle(self) -> "CycleResult":
        """Run one full scan-strategy-execute cycle."""
        self._check_reset()
        if not self._state["enabled"]:
            return CycleResult([], skipped="trader disabled")

        # 1. Fetch markets
        markets = PolymarketCLOB.fetch_active_markets(limit=100)
        if not markets:
            return CycleResult([], skipped="no markets fetched")

        # 2. Run strategies
        all_signals: list[TradeSignal] = []
        strategy_results: dict[str, StrategyResult] = {}
        for strategy in self.strategies:
            try:
                result = strategy.run(markets)
                strategy_results[strategy.name] = result
                all_signals.extend(result.signals)
            except Exception as e:
                logger.exception(f"Strategy {strategy.name} failed: {e}")

        if not all_signals:
            return CycleResult(strategy_results, skipped="no signals generated")

        # 3. Filter: skip already-traded markets
        executed = set(self._state.get("executed_markets", []))
        all_signals = [s for s in all_signals if s.market_slug not in executed]

        # 4. Filter: apply confidence and spend limits
        executable = self._filter_signals(all_signals)

        # 4b. Risk manager override
        executable = self._apply_risk_limits(executable)

        # 5. Execute
        executed_list: list[dict] = []
        for signal in executable:
            if self._state["trades_today"] >= self.config.max_daily_trades:
                break
            if self._state["spend_today"] >= self.config.max_daily_spend_usdc:
                break

            result = self._execute_signal(signal)
            if result:
                executed_list.append(result)
                self._state["trades_today"] += 1
                self._state["spend_today"] += signal.price * signal.size
                self._state["total_trades"] += 1
                self._state["executed_markets"].append(signal.market_slug)

        # 6. Update state
        self._state["last_scan"] = datetime.now().isoformat()
        if executed_list:
            self._state["history"].append({
                "time": datetime.now().isoformat(),
                "trades": len(executed_list),
                "strategies": list(strategy_results.keys()),
            })
            self._state["history"] = self._state["history"][-50:]
        self._save_state()

        return CycleResult(
            strategy_results=strategy_results,
            executed=executed_list,
            total_signals=len(all_signals),
            total_executed=len(executed_list),
        )

    def _filter_signals(self, signals: list[TradeSignal]) -> list[TradeSignal]:
        """Apply confidence, spend, and diversification filters."""
        # Sort by confidence descending
        signals.sort(key=lambda s: s.confidence, reverse=True)

        filtered = []
        for s in signals:
            if s.confidence < self.config.min_confidence:
                continue
            cost = s.price * s.size
            if cost > self.config.max_per_market_usdc:
                # Reduce size to fit max per market
                reduced_size = int(self.config.max_per_market_usdc / s.price)
                if reduced_size < 10:
                    continue
                s.size = reduced_size
            filtered.append(s)
            if len(filtered) >= 20:
                break

        return filtered

    def _apply_risk_limits(self, signals: list[TradeSignal]) -> list[TradeSignal]:
        """Filter signals through PortfolioRiskManager if configured."""
        if not self.risk_manager:
            return signals
        filtered = []
        for s in signals:
            cost = s.price * s.size
            allowed, reason = self.risk_manager.validate_polymarket_trade(
                amount=cost,
                current_positions=len(self._state.get("positions", [])),
            )
            if allowed:
                filtered.append(s)
            else:
                logger.info(f"Risk block {s.strategy} {s.market_slug[:30]}: {reason}")
        return filtered

    def _execute_signal(self, signal: TradeSignal) -> Optional[dict]:
        """Execute a single trade signal.

        Returns dict with execution details, or None on failure.
        """
        if self.config.dry_run:
            logger.info(
                f"[DRY-RUN] {signal.side} {signal.size}× {signal.outcome} "
                f"@{signal.price:.4f}  |  {signal.market_question[:60]}..."
            )
            if self.risk_manager:
                self.risk_manager.record_polymarket_trade(amount=0)
            return {
                "status": "dry_run",
                "strategy": signal.strategy,
                "side": signal.side,
                "outcome": signal.outcome,
                "size": signal.size,
                "price": signal.price,
                "slug": signal.market_slug,
                "question": signal.market_question,
                "dry_run": True,
            }

        # Real execution
        receipt = self.clob.place_order(
            token_id=signal.token_id,
            side=signal.side,
            price=signal.price,
            size=signal.size,
        )
        if receipt:
            if self.risk_manager:
                cost = signal.price * signal.size
                self.risk_manager.record_polymarket_trade(amount=cost)
            cost = signal.price * signal.size
            logger.info(
                f"EXECUTED {signal.side} {signal.size}× {signal.outcome} "
                f"on {signal.market_slug[:40]} @ ${signal.price:.4f} "
                f"(cost ${cost:.2f})"
            )
            return {
                "status": "executed",
                "strategy": signal.strategy,
                "side": signal.side,
                "outcome": signal.outcome,
                "size": signal.size,
                "price": signal.price,
                "cost": cost,
                "slug": signal.market_slug,
                "question": signal.market_question,
                "receipt": receipt,
            }

        logger.warning(f"Failed to execute {signal}")
        return None

    # ── Toggle ─────────────────────────────────

    def enable(self) -> None:
        self._state["enabled"] = True
        self._save_state()
        logger.info("Polymarket trader enabled")

    def disable(self) -> None:
        self._state["enabled"] = False
        self._save_state()
        logger.info("Polymarket trader disabled")

    @property
    def is_enabled(self) -> bool:
        return self._state.get("enabled", False)

    @property
    def is_dry_run(self) -> bool:
        return self.config.dry_run

    def set_dry_run(self, val: bool) -> None:
        """Change dry-run mode at runtime."""
        # Persist to override the env-derived config
        os.environ["POLYMARKET_DRY_RUN"] = str(val).lower()
        self.config.__init__()  # reload (simple re-init)
        logger.info(f"Polymarket dry-run set to {val}")

    # ── Reporting ──────────────────────────────

    def status_text(self) -> str:
        self._check_reset()
        lines = [
            "🎲 Polymarket 自動交易引擎",
            f"狀態：{'🟢 啟用' if self.is_enabled else '🔴 停用'}",
            f"模式：{'🧪 模擬（不下單）' if self.is_dry_run else '⚡ 真實交易'}",
            f"今日交易：{self._state['trades_today']}/{self.config.max_daily_trades}",
            f"今日花費：${self._state['spend_today']:.2f} / ${self.config.max_daily_spend_usdc:.2f}",
            f"總交易次數：{self._state['total_trades']}",
            f"上次掃描：{self._state.get('last_scan', '從未')}",
            "",
        ]

        hist = self._state.get("history", [])
        if hist:
            lines.append("📜 最近交易：")
            for entry in hist[-5:]:
                for action in entry.get("actions", hist[-1].get("trades", 0)):
                    if isinstance(action, dict):
                        lines.append(
                            f"  {action.get('strategy','?')}: "
                            f"{action.get('side','?')} {action.get('outcome','?')} "
                            f"@{action.get('price',0):.4f}"
                        )
                    else:
                        lines.append(f"  {entry.get('trades', 0)} trades executed")

        lines.extend([
            "",
            "/polymarket on — 啟用",
            "/polymarket off — 停用",
            "/polymarket dry — 切換模擬/真實模式",
            "/polymarket scan — 立即掃描一次",
            "/polymarket status — 顯示狀態",
        ])
        return "\n".join(lines)


# ── Cycle result ─────────────────────────────


class CycleResult:
    """Result of one ``run_cycle()`` call."""

    def __init__(self, strategy_results: dict | list,
                 executed: Optional[list[dict]] = None,
                 total_signals: int = 0,
                 total_executed: int = 0,
                 skipped: str = ""):
        self.strategy_results = strategy_results
        self.executed = executed or []
        self.total_signals = total_signals
        self.total_executed = total_executed
        self.skipped = skipped

    @property
    def has_signals(self) -> bool:
        return self.total_signals > 0 or bool(self.executed)

    def summary(self) -> str:
        if self.skipped:
            return f"⏭️ {self.skipped}"
        if not self.has_signals:
            return "沒有找到可執行的交易機會"

        lines = [f"🎯 掃描完成：{self.total_signals} 個信號 → {self.total_executed} 個已執行"]
        for e in self.executed[:10]:
            lines.append(
                f"  {'🧪' if e.get('dry_run') else '⚡'} "
                f"{e['strategy']}: {e['side']} {e['outcome']} "
                f"x{e['size']} @ ${e['price']:.4f}"
            )
        if self.executed:
            lines.append(f"總花費：${sum(e.get('cost', 0) for e in self.executed):.2f}")
        return "\n".join(lines)

    def __bool__(self) -> bool:
        return self.has_signals
