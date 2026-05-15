"""CommitteeTrader — executes trades based on AI Investment Committee signals.

Reads the daily committee analysis (daily_signals.json) and maps
strong_buy/buy → BUY, strong_sell/sell → SELL via the sim portfolio.

Supports Taiwan stocks (.TW/.TWO), US stocks, and margin leverage.
"""

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from bot.stock import resolve_stock_symbol, get_current_price
from manager.portfolio_risk import PortfolioRiskManager

logger = logging.getLogger(__name__)

COMMITTEE_JSON = Path(__file__).parent.parent / "data" / "committee" / "daily_signals.json"
STATE_FILE = Path(__file__).parent.parent / "data" / "committee_trader_state.json"

# Market categories in the committee JSON
STOCK_SECTIONS = {
    "stocks": "TW",
    "us_stocks": "US",
}


class CommitteeTraderConfig:
    @property
    def max_trades_per_day(self) -> int:
        return int(os.environ.get("COMMITTEE_MAX_PER_DAY", "5"))

    @property
    def max_position_pct(self) -> float:
        return float(os.environ.get("COMMITTEE_MAX_POSITION_PCT", "15"))

    @property
    def min_confidence(self) -> float:
        return float(os.environ.get("COMMITTEE_MIN_CONFIDENCE", "0.5"))

    @property
    def enabled(self) -> bool:
        return os.environ.get("COMMITTEE_TRADER_ENABLED", "true").lower() == "true"

    @property
    def use_margin(self) -> bool:
        return os.environ.get("COMMITTEE_USE_MARGIN", "true").lower() == "true"


def _is_us_stock(code: str) -> bool:
    """Detect if a stock code is a US stock (non-numeric, no TW/TWO suffix)."""
    raw = code.replace(".TW", "").replace(".TWO", "").strip().upper()
    return not raw.isdigit()


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
        total = 0.0
        for h in self.sim_portfolio.list_holdings():
            price = get_current_price(h["symbol"]) or h["avg_cost"]
            total += price * h["net_shares"]
        return max(total, 10000.0)

    def _get_available_buying_power(self) -> float:
        """回傳可用買入力（含槓桿）。"""
        if not self.sim_portfolio:
            return 400000.0
        if self.config.use_margin:
            return self.sim_portfolio.get_buying_power()
        return self.sim_portfolio.get_cash()

    def _get_current_price(self, code: str) -> Optional[float]:
        """Get latest price for any stock (TW or US)."""
        symbol = resolve_stock_symbol(code)
        price = get_current_price(symbol)
        if price:
            return price
        return get_current_price(code)

    def _collect_signals(self, data: dict) -> list[tuple]:
        """Collect actionable signals from all stock sections in committee JSON.

        Returns list of (stock_dict, action, confidence, market) tuples.
        """
        signals = []
        for section_key, market in STOCK_SECTIONS.items():
            stocks = data.get(section_key, [])
            for s in stocks:
                if s.get("status") != "ok":
                    continue
                sig = s.get("signals", [{}])[0]
                action = sig.get("action", "hold")
                confidence = sig.get("confidence", 0)
                if action in ("strong_sell", "sell", "strong_buy", "buy"):
                    signals.append((s, action, confidence, market))
        return signals

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

        signals = self._collect_signals(data)
        if not signals:
            return []

        # Priority order: strong_sell > sell > strong_buy > buy
        order = {"strong_sell": 0, "sell": 1, "strong_buy": 2, "buy": 3}
        signals.sort(key=lambda x: (order.get(x[1], 9), -x[2]))

        actions = []

        for s, action, confidence, market in signals:
            if self._state["trades_today"] >= self.config.max_trades_per_day:
                break

            code = s["code"]
            name = s["name"]
            symbol = resolve_stock_symbol(code)
            price = self._get_current_price(code)
            if not price or price <= 0:
                logger.warning("No price for %s (%s), skipping", code, name)
                continue

            is_buy = action in ("buy", "strong_buy")
            is_sell = action in ("sell", "strong_sell")

            if is_buy:
                if confidence < self.config.min_confidence:
                    logger.info("Skipping BUY %s: confidence %.2f < threshold %.2f",
                                code, confidence, self.config.min_confidence)
                    continue

                current_value = self._estimate_portfolio_value()
                position_value = current_value * (self.config.max_position_pct / 100)
                available_bp = self._get_available_buying_power()
                position_value = min(position_value, available_bp)
                if position_value < price:
                    logger.info("BUY %s skipped: position_value %.0f < price %.2f (bp %.0f)",
                                code, position_value, price, available_bp)
                    continue
                shares = max(1, int(position_value / price))

                if self.sim_portfolio:
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

                    note = f"committee: {action} conf {confidence:.0%} ({market})"
                    tid = self.sim_portfolio.buy(symbol, shares, price, note)
                    self._state["trades_today"] += 1
                    self.risk_manager.record_trade(is_stock=True)
                    logger.info("📊 Committee BUY %s (%s) x%d @ %.2f  (trade #%d, %s)",
                                code, name, shares, price, tid, market)
                    actions.append({
                        "symbol": symbol, "name": name, "action": "BUY",
                        "shares": shares, "price": price,
                        "confidence": confidence, "trade_id": tid,
                        "reason": f"{action} signal ({market})",
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
                        "reason": f"{action} signal ({market})",
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
