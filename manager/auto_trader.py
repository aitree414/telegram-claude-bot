"""Auto-trader: closes the loop between analysis signals and trade execution.

When enabled, periodically runs persona analysis on watched symbols and
auto-executes simulated (or real) trades when consensus signals exceed
configurable confidence thresholds.
"""

import json
import logging
import os
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from analysis.stock_analyzer import analyze_stock
from analysis.persona_agents import PERSONA_NAMES, RATING_SCORE
from manager.portfolio_risk import PortfolioRiskManager
from manager.real_trader_bridge import RealTradeBridge

logger = logging.getLogger(__name__)


class AutoTraderConfig:
    """Read-only config from env with sensible defaults."""

    @property
    def enabled(self) -> bool:
        return os.environ.get("AUTO_TRADER_ENABLED", "false").lower() == "true"

    @property
    def buy_threshold(self) -> float:
        """Min consensus_score (-1..1) to trigger a BUY."""
        return float(os.environ.get("AUTO_TRADER_BUY_THRESHOLD", "0.4"))

    @property
    def sell_threshold(self) -> float:
        """Max consensus_score to trigger a SELL (below this = sell signal)."""
        return float(os.environ.get("AUTO_TRADER_SELL_THRESHOLD", "-0.3"))

    @property
    def min_confidence(self) -> float:
        """Min confidence (0..1) required to act."""
        return float(os.environ.get("AUTO_TRADER_MIN_CONFIDENCE", "0.6"))

    @property
    def max_position_pct(self) -> float:
        """Max % of sim-portfolio value for a single auto-trade."""
        return float(os.environ.get("AUTO_TRADER_MAX_POSITION_PCT", "10"))

    @property
    def interval_minutes(self) -> int:
        return int(os.environ.get("AUTO_TRADER_INTERVAL_MINUTES", "60"))

    @property
    def max_trades_per_day(self) -> int:
        return int(os.environ.get("AUTO_TRADER_MAX_PER_DAY", "3"))

    # ------------------------------------------------------------------
    # Real (on-chain) trade config
    # ------------------------------------------------------------------

    @property
    def real_amount_eth(self) -> float:
        """ETH amount per real on-chain trade."""
        return float(os.environ.get("REAL_TRADE_AMOUNT_ETH", "0.005"))

    @property
    def real_min_confidence(self) -> float:
        """Min confidence (0..1) required to execute a real trade."""
        return float(os.environ.get("REAL_MIN_CONFIDENCE", "0.8"))

    @property
    def real_max_per_day(self) -> int:
        return int(os.environ.get("REAL_TRADES_MAX_PER_DAY", "2"))


class AutoTrader:
    """Periodically scans watchlist via persona agents and auto-trades.

    State is persisted to ``auto_trader_state.json`` so it survives restarts.
    """

    def __init__(self, sim_portfolio=None, risk_manager: Optional[PortfolioRiskManager] = None,
                 real_trade_bridge: Optional[RealTradeBridge] = None):
        self.config = AutoTraderConfig()
        self.sim_portfolio = sim_portfolio
        self.risk_manager = risk_manager or PortfolioRiskManager()
        self.real_trade_bridge = real_trade_bridge or RealTradeBridge()
        self._state_file = Path(__file__).parent.parent / "data" / "auto_trader_state.json"
        self._state = self._load_state()

    # ------------------------------------------------------------------
    # Persisted state
    # ------------------------------------------------------------------

    def _load_state(self) -> dict:
        try:
            if self._state_file.exists():
                return json.loads(self._state_file.read_text())
        except Exception:
            logger.exception("Failed to load auto_trader state")
        return self._default_state()

    def _default_state(self) -> dict:
        return {
            "enabled": self.config.enabled,
            "real_mode": False,
            "trades_today": 0,
            "real_trades_today": 0,
            "date": str(date.today()),
            "last_scan": None,
            "history": [],
        }

    def _save_state(self) -> None:
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(json.dumps(self._state, indent=2))
        except Exception:
            logger.exception("Failed to save auto_trader state")

    def _check_reset(self) -> None:
        today = str(date.today())
        if self._state.get("date") != today:
            self._state["trades_today"] = 0
            self._state["real_trades_today"] = 0
            self._state["date"] = today

    # ------------------------------------------------------------------
    # Toggle
    # ------------------------------------------------------------------

    def enable(self) -> None:
        self._state["enabled"] = True
        self._save_state()
        logger.info("Auto-trader enabled")

    def disable(self) -> None:
        self._state["enabled"] = False
        self._save_state()
        logger.info("Auto-trader disabled")

    @property
    def is_enabled(self) -> bool:
        return self._state.get("enabled", False)

    # ------------------------------------------------------------------
    # Real-mode toggle
    # ------------------------------------------------------------------

    def enable_real_mode(self) -> None:
        self._state["real_mode"] = True
        self._save_state()
        logger.info("Real-trade mode enabled")

    def disable_real_mode(self) -> None:
        self._state["real_mode"] = False
        self._save_state()
        logger.info("Real-trade mode disabled")

    @property
    def is_real_mode(self) -> bool:
        return self._state.get("real_mode", False)

    # ------------------------------------------------------------------
    # Core scan-trade cycle
    # ------------------------------------------------------------------

    async def run_cycle(self, symbols: list[str]) -> list[dict]:
        """Run one analysis cycle: scan symbols → evaluate → auto-trade.

        Parameters
        ----------
        symbols : list[str]
            Stock symbols to analyse (e.g. ["2330.TW", "AAPL"]).

        Returns
        -------
        list[dict]  — actions taken (each has symbol, action, reason, …).
        """
        self._check_reset()
        if not self.is_enabled:
            logger.debug("Auto-trader disabled, skipping cycle")
            return []

        if self._state["trades_today"] >= self.config.max_trades_per_day:
            logger.info("Daily trade limit reached, skipping cycle")
            return []

        from bot.stock import _scan_single

        actions = []

        for symbol in symbols:
            if self._state["trades_today"] >= self.config.max_trades_per_day:
                break

            data = _scan_single(symbol)
            if not data:
                continue

            result = analyze_stock(data)
            consensus = result["consensus_rating"]
            confidence = result["confidence"]
            score = result["consensus_score"]
            current = result.get("current") or data.get("current")

            if not current or current <= 0:
                continue

            # ---- BUY logic ----
            if (consensus == "BUY"
                    and score >= self.config.buy_threshold
                    and confidence >= self.config.min_confidence):

                # Risk check
                current_value = self._estimate_portfolio_value()
                position_value = current_value * (self.config.max_position_pct / 100)
                shares = max(1, int(position_value / current))

                allowed, reason = self.risk_manager.validate_new_position(
                    symbol, position_value, current_value, []
                )
                if not allowed:
                    logger.info(f"Auto-trade BUY {symbol} blocked: {reason}")
                    actions.append({"symbol": symbol, "action": "BLOCKED", "reason": reason})
                    continue

                # Execute sim trade
                if self.sim_portfolio:
                    note = f"auto: {result['consensus_score']:.2f} conf {confidence:.0%}"
                    tid = self.sim_portfolio.buy(symbol, shares, current, note)
                    self._state["trades_today"] += 1
                    self.risk_manager.record_trade(is_stock=True)
                    logger.info(f"🤖 Auto-BUY {symbol} x{shares} @ {current}  (trade #{tid})")
                    actions.append({
                        "symbol": symbol,
                        "action": "BUY",
                        "shares": shares,
                        "price": current,
                        "confidence": confidence,
                        "score": score,
                        "reason": result["ratings"],
                    })

                    # Real on-chain BUY
                    if (self.is_real_mode
                            and self._state["real_trades_today"] < self.config.real_max_per_day
                            and confidence >= self.config.real_min_confidence):
                        real_result = await self.real_trade_bridge.execute_buy(
                            symbol=symbol,
                            amount_eth=self.config.real_amount_eth,
                            confidence=confidence,
                            reason=f"auto: score={score}",
                        )
                        if real_result.get("success"):
                            self._state["real_trades_today"] += 1
                            actions[-1]["real_tx"] = real_result["tx_hash"]
                            actions[-1]["real_trade_id"] = real_result["trade_id"]
                            logger.info(
                                f"Real on-chain BUY {symbol} "
                                f"tx={real_result['tx_hash'][:10]}..."
                            )
                        else:
                            logger.warning(
                                f"Real BUY {symbol} failed: {real_result.get('error')}"
                            )

            # ---- SELL logic ----
            elif (consensus == "SELL"
                  and score <= self.config.sell_threshold
                  and confidence >= self.config.min_confidence
                  and self.sim_portfolio):

                holdings = self.sim_portfolio.list_holdings()
                holding = next((h for h in holdings if h["symbol"] == symbol), None)
                if holding and holding["net_shares"] > 0:
                    sell_result = self.sim_portfolio.sell(symbol, holding["net_shares"], current)
                    if sell_result["ok"]:
                        self._state["trades_today"] += 1
                        self.risk_manager.record_trade(is_stock=True)
                        logger.info(
                            f"🤖 Auto-SELL {symbol} x{holding['net_shares']} @ {current} "
                            f"pnl {sell_result['realized_pnl']:.2f}"
                        )
                        actions.append({
                            "symbol": symbol,
                            "action": "SELL",
                            "shares": holding["net_shares"],
                            "price": current,
                            "pnl": sell_result["realized_pnl"],
                            "confidence": confidence,
                            "score": score,
                        })

                        # Real on-chain SELL
                        if (self.is_real_mode
                                and self._state["real_trades_today"] < self.config.real_max_per_day
                                and confidence >= self.config.real_min_confidence):
                            real_result = await self.real_trade_bridge.execute_sell(
                                symbol, confidence
                            )
                            if real_result.get("success"):
                                self._state["real_trades_today"] += 1
                                actions[-1]["real_tx"] = real_result["tx_hash"]
                                logger.info(f"Real on-chain SELL {symbol}")
                            else:
                                logger.warning(
                                    f"Real SELL {symbol} failed: {real_result.get('error')}"
                                )

        self._state["last_scan"] = datetime.now().isoformat()
        if actions:
            self._state["history"].append({
                "time": datetime.now().isoformat(),
                "actions": actions,
            })
            # Keep last 50
            self._state["history"] = self._state["history"][-50:]
        self._save_state()

        return actions

    def _estimate_portfolio_value(self) -> float:
        """Rough estimate of portfolio value from sim holdings."""
        if not self.sim_portfolio:
            return 100000.0
        from bot.stock import get_current_price
        total = 0.0
        for h in self.sim_portfolio.list_holdings():
            price = get_current_price(h["symbol"]) or h["avg_cost"]
            total += price * h["net_shares"]
        return max(total, 10000.0)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def status_text(self) -> str:
        self._check_reset()
        real_status = ""
        if self.is_real_mode:
            real_status = (
                f"鏈上交易：{'🟢 啟用' if self.is_real_mode else '🔴 停用'}\n"
                f"今日鏈上：{self._state['real_trades_today']}/{self.config.real_max_per_day}\n"
                f"單筆 ETH：{self.config.real_amount_eth}\n"
                f"鏈上信心：≥{self.config.real_min_confidence}\n"
            )

        lines = [
            "🤖 自動交易引擎",
            f"狀態：{'🟢 啟用' if self.is_enabled else '🔴 停用'}",
            f"今日模擬：{self._state['trades_today']}/{self.config.max_trades_per_day}",
            f"上次掃描：{self._state.get('last_scan', '從未')}",
            "",
        ]
        if real_status:
            lines.append(f"⛓️ 鏈上真實交易模式\n{real_status}")
        lines.extend([
            "⚙️ 設定 (環境變數)",
            f"買入門檻：{self.config.buy_threshold}",
            f"賣出門檻：{self.config.sell_threshold}",
            f"最低信心：{self.config.min_confidence}",
            f"掃描間隔：{self.config.interval_minutes} 分鐘",
            "",
            "📜 最近動作：",
        ])
        history = self._state.get("history", [])
        if history:
            for entry in history[-3:]:
                for a in entry.get("actions", []):
                    lines.append(
                        f"  {a['action']} {a['symbol']} @ {a.get('price','?')}"
                    )
        else:
            lines.append("  （尚無自動交易記錄）")

        lines.append("")
        lines.append("/autotrade on — 啟用")
        lines.append("/autotrade off — 停用")
        lines.append("/autotrade run — 立即執行一次掃描")
        lines.append("/autotrade real on — 啟用鏈上真實交易")
        lines.append("/autotrade real off — 停用鏈上真實交易")
        lines.append("/tokenmap — 管理代幣映射")
        return "\n".join(lines)
