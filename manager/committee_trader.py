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
from manager.market_schedule import is_market_open, detect_market
from manager.portfolio_risk import PortfolioRiskManager

logger = logging.getLogger(__name__)

COMMITTEE_JSON = Path(__file__).parent.parent / "data" / "committee" / "daily_signals.json"
STATE_FILE = Path(__file__).parent.parent / "data" / "committee_trader_state.json"

# Market categories in the committee JSON
STOCK_SECTIONS = {
    "stocks": "TW",
    "us_stocks": "US",
}

USD_TWD_RATE = 33.0  # for US stock price conversion to TWD

# Hard floor: trades below this confidence are NEVER executed,
# regardless of env-var configuration. This is a safety rail.
HARD_CONFIDENCE_FLOOR = 0.55


class CommitteeTraderConfig:
    @property
    def max_trades_per_day(self) -> int:
        return int(os.environ.get("COMMITTEE_MAX_PER_DAY", "10"))

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
    def cash_reserve_pct(self) -> float:
        return float(os.environ.get("COMMITTEE_CASH_RESERVE_PCT", "15"))

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
            "today_buys": [],
            "today_sells": [],
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
            self._state["today_buys"] = []
            self._state["today_sells"] = []
            self._state["date"] = today

    def _estimate_portfolio_value(self) -> float:
        if not self.sim_portfolio:
            return 100000.0
        total_holdings = 0.0
        for h in self.sim_portfolio.list_holdings():
            price = get_current_price(h["symbol"]) or h["avg_cost"]
            total_holdings += price * h["net_shares"]
        cash = self.sim_portfolio.get_cash()
        return max(cash + total_holdings, 10000.0)

    def _get_available_buying_power(self) -> float:
        """Return available buying power with cash reserve applied."""
        if not self.sim_portfolio:
            return 400000.0
        if self.config.use_margin:
            bp = self.sim_portfolio.get_buying_power()
        else:
            bp = self.sim_portfolio.get_cash()
        reserve = self._estimate_portfolio_value() * (self.config.cash_reserve_pct / 100)
        return max(0, bp - reserve)

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

    def _rebalance_overweight_positions(self) -> list[dict]:
        """Sell excess shares from positions exceeding max_position_pct * 1.3.

        Prevents any single holding from consuming too much of the portfolio
        due to price appreciation or initial sizing. Frees up capital for
        new opportunities.

        Skips positions that were bought today to avoid same-day conflict
        with freshly opened committee trades.
        """
        if not self.sim_portfolio:
            return []
        actions = []
        portfolio_value = self._estimate_portfolio_value()
        max_pos_value = portfolio_value * (self.config.max_position_pct / 100)
        threshold = max_pos_value * 1.3  # e.g. 19.5% trigger for 15% limit

        today_buys = set(self._state.get("today_buys", []))
        for h in self.sim_portfolio.list_holdings():
            sym = h["symbol"]
            if sym in today_buys:
                continue  # skip positions opened today — let them settle
            price = self._get_current_price(sym)
            if not price or price <= 0:
                continue
            # Use current market price, not avg_cost, to compute position value
            portfolio_price = price * USD_TWD_RATE if _is_us_stock(sym) else price
            current_value = portfolio_price * h["net_shares"]
            if current_value <= threshold:
                continue

            target_shares = max(1, int(max_pos_value / portfolio_price))
            sell_shares = int(h["net_shares"] - target_shares)
            if sell_shares <= 0:
                continue

            old_net = int(h["net_shares"])
            result = self.sim_portfolio.sell(sym, sell_shares, portfolio_price)
            if result.get("ok"):
                self._state["trades_today"] += 1
                self.risk_manager.record_trade(is_stock=True, pnl=result.get("realized_pnl", 0))
                logger.info("Rebalance: sold %d/%d of %s @ %.2f (was %.1f%% of portfolio)",
                            sell_shares, old_net, sym, price,
                            current_value / portfolio_value * 100)
                actions.append({
                    "symbol": sym, "action": "REBALANCE_SELL",
                    "shares": sell_shares, "price": price,
                    "pnl": result.get("realized_pnl", 0),
                    "reason": (f"reduce overweight "
                               f"({current_value/portfolio_value*100:.0f}% > {self.config.max_position_pct}%)"),
                })
        return actions

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

        # ── Drawdown check: halt trading if drawdown is too severe ──
        portfolio_val = self._estimate_portfolio_value()
        if self.risk_manager:
            self.risk_manager.update_peak(portfolio_val)
            should_halt, halt_reason = self.risk_manager.should_force_stop(portfolio_val)
            if should_halt:
                logger.warning("Committee trader halted: %s", halt_reason)
                return [{"symbol": "PORTFOLIO", "action": "HALTED", "reason": halt_reason}]

        if not COMMITTEE_JSON.exists():
            logger.warning("No committee data found at %s", COMMITTEE_JSON)
            return []

        try:
            data = json.loads(COMMITTEE_JSON.read_text())
        except Exception as e:
            logger.error("Failed to read committee JSON: %s", e)
            return []

        actions = []

        # Rebalance overweight positions before new trades
        rebalance_actions = self._rebalance_overweight_positions()
        if rebalance_actions:
            actions.extend(rebalance_actions)
            logger.info("Rebalanced %d overweight position(s)", len(rebalance_actions))

        signals = self._collect_signals(data)
        if not signals:
            # Return rebalance actions even without new signals
            if actions:
                self._state["history"].append({
                    "time": datetime.now().isoformat(),
                    "actions": actions,
                })
                self._state["history"] = self._state["history"][-50:]
                self._save_state()
            return actions

        # Priority order: strong_sell > sell > strong_buy > buy
        order = {"strong_sell": 0, "sell": 1, "strong_buy": 2, "buy": 3}
        signals.sort(key=lambda x: (order.get(x[1], 9), -x[2]))

        # Track cumulative spend this cycle to prevent over-concentration
        cycle_spent = 0.0

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

            # Skip if the stock's market is closed
            if not is_market_open(symbol):
                mkt = detect_market(symbol).value.upper()
                logger.info("Market %s closed for %s (%s), skipping", mkt, code, name)
                actions.append({
                    "symbol": symbol, "name": name, "action": "SKIP",
                    "reason": f"{mkt} market closed",
                })
                continue

            is_buy = action in ("buy", "strong_buy")
            is_sell = action in ("sell", "strong_sell")

            if is_buy:
                effective_min_conf = max(self.config.min_confidence, HARD_CONFIDENCE_FLOOR)
                if confidence < effective_min_conf:
                    logger.info("Skipping BUY %s: confidence %.2f < threshold %.2f (hard floor %.2f)",
                                code, confidence, effective_min_conf, HARD_CONFIDENCE_FLOOR)
                    continue

                # Intraday cooldown: skip if already bought today
                if symbol in self._state.get("today_buys", []):
                    logger.info("BUY %s (%s) skipped: already bought today", code, name)
                    continue

                current_value = self._estimate_portfolio_value()
                position_value = current_value * (self.config.max_position_pct / 100)
                available_bp = self._get_available_buying_power()
                position_value = min(position_value, available_bp)

                # Per-cycle budget: prevent over-concentration in single cycle
                remaining_budget = available_bp - cycle_spent
                position_value = min(position_value, remaining_budget)

                # Convert US stock price to TWD for position sizing (sim_portfolio stores in TWD)
                portfolio_price = price * USD_TWD_RATE if _is_us_stock(code) else price

                if position_value < portfolio_price:
                    logger.info("BUY %s skipped: position_value %.0f < portfolio_price %.2f (bp %.0f, remaining %0.f)",
                                code, position_value, portfolio_price, available_bp, remaining_budget)
                    continue
                shares = max(1, int(position_value / portfolio_price))

                if self.sim_portfolio:
                    holdings = self.sim_portfolio.list_holdings()
                    existing = next((h for h in holdings if h["symbol"] == symbol), None)
                    if existing and existing["net_shares"] > 0:
                        logger.info("Already holding %s (%s), skipping BUY", code, name)
                        continue

                    positions = []
                    for h in holdings:
                        pos_price = get_current_price(h["symbol"]) or h["avg_cost"]
                        positions.append({
                            "symbol": h["symbol"],
                            "value": pos_price * h["net_shares"],
                            "sector": "",
                        })
                    allowed, reason = self.risk_manager.validate_new_position(
                        symbol, position_value, current_value, positions
                    )
                    if not allowed:
                        logger.info("BUY %s blocked: %s", code, reason)
                        actions.append({"symbol": symbol, "name": name, "action": "BLOCKED", "reason": reason})
                        continue

                    note = f"committee: {action} conf {confidence:.0%} ({market})"
                    tid = self.sim_portfolio.buy(symbol, shares, portfolio_price, note,
                        auto_sl_pct=15, auto_tp_pct=30)
                    self._state["trades_today"] += 1
                    self._state.setdefault("today_buys", []).append(symbol)
                    cycle_spent += shares * portfolio_price
                    self.risk_manager.record_trade(is_stock=True)
                    logger.info("📊 Committee BUY %s (%s) x%d @ %.2f (price %.2f TWD) (trade #%d, %s)",
                                code, name, shares, price, portfolio_price, tid, market)
                    actions.append({
                        "symbol": symbol, "name": name, "action": "BUY",
                        "shares": shares, "price": price,
                        "confidence": confidence, "trade_id": tid,
                        "reason": f"{action} signal ({market})",
                    })

            elif is_sell:
                if not self.sim_portfolio:
                    continue

                # Intraday cooldown: skip if already sold today via committee
                if symbol in self._state.get("today_sells", []):
                    logger.info("SELL %s (%s) skipped: already sold today", code, name)
                    continue

                holdings = self.sim_portfolio.list_holdings()
                holding = next((h for h in holdings if h["symbol"] == symbol), None)
                if not holding or holding["net_shares"] <= 0:
                    logger.info("No position in %s (%s) to sell", code, name)
                    continue

                sell_shares = holding["net_shares"]
                if action == "sell":
                    sell_shares = max(1, int(sell_shares / 2))

                # Convert US stock price to TWD for sim_portfolio (stores in TWD)
                sell_price = price * USD_TWD_RATE if _is_us_stock(code) else price
                sell_result = self.sim_portfolio.sell(symbol, sell_shares, sell_price)
                if sell_result.get("ok"):
                    self._state["trades_today"] += 1
                    self._state.setdefault("today_sells", []).append(symbol)
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
