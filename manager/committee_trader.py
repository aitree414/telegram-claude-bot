"""CommitteeTrader — executes trades based on AI Investment Committee signals.

Reads the daily committee analysis (daily_signals.json) and maps
strong_buy/buy → BUY, strong_sell/sell → SELL via the sim portfolio
(and optionally real broker in the future).

Integrated as a scheduler job that runs after the morning analysis.
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from manager.portfolio_risk import PortfolioRiskManager

logger = logging.getLogger(__name__)

COMMITTEE_JSON = Path(__file__).parent.parent / "data" / "committee" / "daily_signals.json"
STATE_FILE = Path(__file__).parent.parent / "data" / "committee_trader_state.json"
OTC_STOCKS = {"3529", "6180", "4506", "3680"}  # 力旺, 橘子, 崇友, 家登


class CommitteeTraderConfig:
    @property
    def max_trades_per_day(self) -> int:
        return int(__import__("os").environ.get("COMMITTEE_MAX_PER_DAY", "5"))

    @property
    def max_position_pct(self) -> float:
        return float(__import__("os").environ.get("COMMITTEE_MAX_POSITION_PCT", "15"))

    @property
    def min_confidence(self) -> float:
        return float(__import__("os").environ.get("COMMITTEE_MIN_CONFIDENCE", "0.5"))

    @property
    def enabled(self) -> bool:
        return __import__("os").environ.get("COMMITTEE_TRADER_ENABLED", "true").lower() == "true"


class CommitteeTrader:
    """Reads committee signals and executes trades via the sim portfolio."""

    def __init__(self, sim_portfolio=None, risk_manager: Optional[PortfolioRiskManager] = None):
        self.config = CommitteeTraderConfig()
        self.sim_portfolio = sim_portfolio
        self.risk_manager = risk_manager or PortfolioRiskManager()
        self._state = self._load_state()

    def _load_state(self) -> dict:
        try:
            if STATE_FILE.exists():
                return json.loads(STATE_FILE.read_text())
        except Exception:
            logger.exception("Failed to load committee trader state")
        return self._default_state()

    def _default_state(self) -> dict:
        return {
            "enabled": self.config.enabled,
            "trades_today": 0,
            "date": str(date.today()),
            "history": [],
        }

    def _save_state(self) -> None:
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(self._state, indent=2))
        except Exception:
            logger.exception("Failed to save committee trader state")

    def _check_reset(self) -> None:
        today = str(date.today())
        if self._state.get("date") != today:
            self._state["trades_today"] = 0
            self._state["date"] = today

    def _estimate_portfolio_value(self) -> float:
        if not self.sim_portfolio:
            return 100000.0
        from bot.stock import get_current_price
        total = 0.0
        for h in self.sim_portfolio.list_holdings():
            price = get_current_price(h["symbol"]) or h["avg_cost"]
            total += price * h["net_shares"]
        return max(total, 10000.0)

    @staticmethod
    def _resolve_symbol(code: str) -> str:
        """Resolve raw stock code to exchange-suffixed symbol."""
        if code in OTC_STOCKS:
            return code + ".TWO"
        return code + ".TW"

    def _get_current_price(self, code: str) -> Optional[float]:
        """Get latest price for a Taiwan stock code."""
        from bot.stock import get_current_price
        symbol = self._resolve_symbol(code)
        price = get_current_price(symbol)
        if price:
            return price
        # Fallback: try raw code or other suffixes
        return get_current_price(code)

    def run_cycle(self) -> list[dict]:
        """Read committee signals and execute trades.

        Returns list of action dicts (empty if nothing traded).
        """
        self._check_reset()
        if not self._state.get("enabled", False):
            logger.debug("Committee trader disabled, skipping")
            return []

        if self._state["trades_today"] >= self.config.max_trades_per_day:
            logger.info("Daily trade limit reached, skipping committee cycle")
            return []

        if not COMMITTEE_JSON.exists():
            logger.warning("No committee data found at %s", COMMITTEE_JSON)
            return []

        try:
            data = json.loads(COMMITTEE_JSON.read_text())
        except Exception as e:
            logger.error("Failed to read committee JSON: %s", e)
            return []

        stocks = data.get("stocks", [])
        if not stocks:
            return []

        summary = data.get("summary", {})
        actions = []

        # Priority order: strong_sell > sell > strong_buy > buy
        priority_stocks = []
        for s in stocks:
            if s.get("status") != "ok":
                continue
            sig = s.get("signals", [{}])[0]
            action = sig.get("action", "hold")
            confidence = sig.get("confidence", 0)
            if action in ("strong_sell", "sell", "strong_buy", "buy"):
                priority_stocks.append((s, action, confidence))

        # Sort: strong_sell first, then sell, then strong_buy, then buy
        order = {"strong_sell": 0, "sell": 1, "strong_buy": 2, "buy": 3}
        priority_stocks.sort(key=lambda x: (order.get(x[1], 9), -x[2]))

        for s, action, confidence in priority_stocks:
            if self._state["trades_today"] >= self.config.max_trades_per_day:
                break

            code = s["code"]
            name = s["name"]
            symbol = self._resolve_symbol(code)
            price = self._get_current_price(code)
            if not price or price <= 0:
                logger.warning("No price for %s (%s), skipping", code, name)
                continue

            is_buy = action in ("buy", "strong_buy")
            is_sell = action in ("sell", "strong_sell")

            if is_buy:
                # Check confidence threshold
                if confidence < self.config.min_confidence:
                    logger.info("Skipping BUY %s: confidence %.2f < threshold %.2f",
                                code, confidence, self.config.min_confidence)
                    continue

                # Risk check
                current_value = self._estimate_portfolio_value()
                position_value = current_value * (self.config.max_position_pct / 100)
                shares = max(1, int(position_value / price))

                if self.sim_portfolio:
                    # Check if already held (use resolved symbol)
                    holdings = self.sim_portfolio.list_holdings()
                    existing = next((h for h in holdings if h["symbol"] == symbol), None)
                    if existing and existing["net_shares"] > 0:
                        logger.info("Already holding %s (%s), skipping BUY", code, name)
                        continue

                    positions = [
                        {"symbol": h["symbol"], "value": h["avg_cost"] * h["net_shares"], "sector": ""}
                        for h in holdings
                    ]
                    allowed, reason = self.risk_manager.validate_new_position(
                        symbol, position_value, current_value, positions
                    )
                    if not allowed:
                        logger.info("BUY %s blocked: %s", code, reason)
                        actions.append({"symbol": symbol, "name": name, "action": "BLOCKED", "reason": reason})
                        continue

                    note = f"committee: {action} conf {confidence:.0%}"
                    tid = self.sim_portfolio.buy(symbol, shares, price, note)
                    self._state["trades_today"] += 1
                    self.risk_manager.record_trade(is_stock=True)
                    logger.info("📊 Committee BUY %s (%s) x%d @ %.2f  (trade #%d)",
                                code, name, shares, price, tid)
                    actions.append({
                        "symbol": symbol, "name": name, "action": "BUY",
                        "shares": shares, "price": price,
                        "confidence": confidence, "trade_id": tid,
                        "reason": f"{action} signal",
                    })

            elif is_sell:
                if not self.sim_portfolio:
                    continue

                holdings = self.sim_portfolio.list_holdings()
                holding = next((h for h in holdings if h["symbol"] == symbol), None)
                if not holding or holding["net_shares"] <= 0:
                    logger.info("No position in %s (%s) to sell", code, name)
                    continue

                sell_shares = holding["net_shares"]
                # For strong_sell, sell all. For sell, sell half.
                if action == "sell":
                    sell_shares = max(1, int(sell_shares / 2))

                sell_result = self.sim_portfolio.sell(symbol, sell_shares, price)
                if sell_result.get("ok"):
                    self._state["trades_today"] += 1
                    self.risk_manager.record_trade(is_stock=True)
                    pnl = sell_result.get("realized_pnl", 0)
                    logger.info("📊 Committee SELL %s (%s) x%d @ %.2f  pnl %.2f",
                                code, name, sell_shares, price, pnl)
                    actions.append({
                        "symbol": code, "name": name, "action": "SELL",
                        "shares": sell_shares, "price": price,
                        "pnl": pnl, "confidence": confidence,
                        "reason": f"{action} signal",
                    })
                else:
                    logger.warning("SELL %s failed: %s", code, sell_result.get("error"))

        if actions:
            self._state["history"].append({
                "time": datetime.now().isoformat(),
                "actions": actions,
            })
            self._state["history"] = self._state["history"][-50:]
        self._save_state()

        return actions
