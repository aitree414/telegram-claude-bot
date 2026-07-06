import json
import logging
import os
import threading
from datetime import date
from pathlib import Path
from typing import Any

from bot.portfolio_managers import (
    StopLossManager,
    DividendManager,
    RebalanceManager,
    PerformanceTracker,
)

logger = logging.getLogger(__name__)

PORTFOLIO_FILE = Path.home() / "telegram-claude-bot" / "portfolio.json"
SIM_PORTFOLIO_FILE = Path.home() / "telegram-claude-bot" / "portfolio_sim.json"
DEFAULT_SIM_CAPITAL = 400000  # 預設模擬本金 40 萬 TWD
DEFAULT_MAX_LEVERAGE = float(os.environ.get("SIM_MAX_LEVERAGE", "2.0"))


class PortfolioManager:
    def __init__(self, simulation: bool = False) -> None:
        self._trades: list[dict[str, Any]] = []
        self._futures: list[dict[str, Any]] = []
        self._next_id = 1
        self._futures_next_id = 1
        self._initial_capital = 0.0
        self._realized_pnl = 0.0
        self._futures_realized_pnl = 0.0
        self._max_leverage = 1.0
        self._max_leverage_tw = 2.0
        self._max_leverage_us = 2.0
        self._max_leverage_futures = 3.0
        self._lock = threading.RLock()
        self._simulation = simulation
        self._load()
        # Sub-managers for advanced features
        self._sl_manager = StopLossManager(simulation)
        self._div_manager = DividendManager(simulation)
        self._rebal_manager = RebalanceManager(simulation)
        self._perf_tracker = PerformanceTracker(simulation)

    def _file_path(self) -> Path:
        return SIM_PORTFOLIO_FILE if self._simulation else PORTFOLIO_FILE

    def _load(self) -> None:
        with self._lock:
            fp = self._file_path()
            if fp.exists():
                try:
                    data = json.loads(fp.read_text())
                    self._trades = data.get("trades", [])
                    self._futures = data.get("futures", [])
                    self._next_id = data.get("next_id", 1)
                    self._futures_next_id = data.get("futures_next_id", 1)
                    self._initial_capital = data.get("initial_capital", 0.0)
                    self._realized_pnl = data.get("realized_pnl", 0.0)
                    self._futures_realized_pnl = data.get("futures_realized_pnl", 0.0)
                    self._max_leverage = data.get("max_leverage", DEFAULT_MAX_LEVERAGE)
                    self._max_leverage_tw = data.get("max_leverage_tw", 2.0)
                    self._max_leverage_us = data.get("max_leverage_us", 2.0)
                    self._max_leverage_futures = data.get("max_leverage_futures", 3.0)
                except Exception:
                    logger.exception("載入 portfolio 失敗")

    def _save(self) -> None:
        with self._lock:
            try:
                fp = self._file_path()
                fp.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "trades": self._trades,
                    "futures": self._futures,
                    "next_id": self._next_id,
                    "futures_next_id": self._futures_next_id,
                    "initial_capital": self._initial_capital,
                    "realized_pnl": self._realized_pnl,
                    "futures_realized_pnl": self._futures_realized_pnl,
                    "max_leverage": self._max_leverage,
                    "max_leverage_tw": self._max_leverage_tw,
                    "max_leverage_us": self._max_leverage_us,
                    "max_leverage_futures": self._max_leverage_futures,
                }
                fp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
            except Exception:
                logger.exception("儲存 portfolio 失敗")

    def get_initial_capital(self) -> float:
        with self._lock:
            return self._initial_capital

    def set_initial_capital(self, amount: float) -> None:
        """設定模擬交易初始本金（僅 sim 模式有效）。"""
        with self._lock:
            self._initial_capital = amount
            self._save()

    def set_max_leverage(self, leverage: float) -> None:
        """設定全域最大槓桿倍數（僅 sim 模式有效）。"""
        with self._lock:
            self._max_leverage = max(1.0, leverage)
            self._save()

    def set_leverage_tw(self, leverage: float) -> None:
        """設定台股槓桿倍數。"""
        with self._lock:
            self._max_leverage_tw = max(1.0, leverage)
            self._save()

    def set_leverage_us(self, leverage: float) -> None:
        """設定美股槓桿倍數。"""
        with self._lock:
            self._max_leverage_us = max(1.0, leverage)
            self._save()

    def set_leverage_futures(self, leverage: float) -> None:
        """設定期貨槓桿倍數。"""
        with self._lock:
            self._max_leverage_futures = max(1.0, leverage)
            self._save()

    def get_equity(self) -> float:
        """Return book equity = cash + holdings at cost basis.

        This represents the portfolio's accounting net worth using cost basis.
        For market-value equity, use get_cash() + current market value of holdings.
        """
        with self._lock:
            return self.get_cash() + self._get_holdings_cost()

    def _get_holdings_cost(self) -> float:
        """Total cost basis of all current holdings."""
        holdings = self._aggregate()
        return sum(h["net_shares"] * h["avg_cost"] for h in holdings)

    def get_portfolio_value(self, price_fn=None) -> float:
        """Return cash + market value of holdings.

        If price_fn(symbol) -> float is provided, uses current market prices.
        Otherwise falls back to cost basis.
        """
        cash = self.get_cash()
        holdings = self._aggregate()
        if price_fn:
            holdings_value = sum(
                h["net_shares"] * max(0, (price_fn(h["symbol"]) or h["avg_cost"]))
                for h in holdings
            )
        else:
            holdings_value = sum(h["net_shares"] * h["avg_cost"] for h in holdings)
        return cash + holdings_value

    def get_cash(self) -> float:
        """計算可用現金 = initial_capital - 買入成本 - 手續費 + 賣出收入 - 手續費

        Buy and sell both store raw price with fee recorded separately.
        """
        with self._lock:
            cash = self._initial_capital
            for t in self._trades:
                if t["action"] == "buy":
                    cash -= t["shares"] * t["price"] + t.get("fee", 0)
                else:
                    cash += t["shares"] * t["price"] - t.get("fee", 0)
            return cash

    def get_buying_power(self) -> float:
        """Total buying power including margin leverage.

        buying_power = cash_on_hand + equity * (max_leverage - 1)
        With max_leverage=2.0 and 400k equity: buying_power = cash + 400k
        """
        with self._lock:
            cash = self.get_cash()
            if self._max_leverage <= 1.0:
                return cash
            equity = self.get_equity()
            margin_available = max(0, equity * (self._max_leverage - 1))
            return max(0, cash) + margin_available

    def get_margin_summary(self) -> dict[str, Any]:
        """回傳保證金帳戶摘要資訊。"""
        with self._lock:
            cash = self.get_cash()
            equity = self.get_equity()
            bp = max(0, cash) + max(0, equity * (self._max_leverage - 1))
            holdings = self._aggregate()
            holdings_cost = sum(h["net_shares"] * h["avg_cost"] for h in holdings)
            margin_used = max(0, holdings_cost - max(0, cash))
            margin_ratio = (margin_used / equity * 100) if equity > 0 else 0
            if margin_ratio > 80:
                risk = "danger"
            elif margin_ratio > 60:
                risk = "warning"
            else:
                risk = "safe"
            return {
                "max_leverage": self._max_leverage,
                "max_leverage_tw": self._max_leverage_tw,
                "max_leverage_us": self._max_leverage_us,
                "max_leverage_futures": self._max_leverage_futures,
                "buying_power": round(bp, 2),
                "equity": round(equity, 2),
                "margin_used": round(margin_used, 2),
                "margin_ratio": round(margin_ratio, 2),
                "maintenance_risk": risk,
            }

    def buy(self, symbol: str, shares: float, price: float, note: str = "",
            auto_sl_pct: float | None = None,
            auto_tp_pct: float | None = None,
            fee_rate: float = 0.001425) -> int:
        """Record a buy trade. Returns trade ID (0 if insufficient cash).

        Checks available cash before recording. In simulation mode, rejects
        trades that exceed available cash to prevent cost-basis inflation.
        If auto_sl_pct is set (e.g. 15), creates a stop-loss at price*(1-pct/100).
        If auto_tp_pct is set (e.g. 30), creates a take-profit at price*(1+pct/100).

        Deducts transaction fee (default 0.1425% = TW broker fee) from cash.
        price is the raw execution price (TWD). Fee is recorded separately.
        """
        with self._lock:
            trade_value = shares * price
            fee = max(1, trade_value * fee_rate)  # Minimum $1 fee floor
            total_cost = trade_value + fee

            bp = self.get_buying_power()
            if self._simulation and total_cost > bp + 1:  # $1 tolerance
                logger.warning(
                    f"Buy {symbol} x{shares} @ {price} = {total_cost:.0f} "
                    f"(incl. fee {fee:.0f}) failed: buying_power {bp:.0f} insufficient"
                )
                return 0

            trade_id = self._next_id
            self._trades = [
                *self._trades,
                {
                    "id": trade_id,
                    "symbol": symbol,
                    "action": "buy",
                    "shares": shares,
                    "price": price,       # raw execution price (TWD)
                    "date": str(date.today()),
                    "note": note,
                    "fee": fee,
                },
            ]
            self._next_id += 1

            # Post-trade cash sanity check: warn if cash goes deeply negative
            if self._simulation:
                cash_after = self.get_cash()
                equity = self.get_equity()
                if cash_after < 0 and abs(cash_after) > equity * 0.3:
                    logger.warning(
                        f"⚠️ Cash deeply negative ({cash_after:,.0f}) after buy {symbol} "
                        f"x{shares} @ {price} (equity {equity:,.0f}) — margin risk elevated"
                    )

            if auto_sl_pct and auto_sl_pct > 0:
                sl_price = round(price * (1 - auto_sl_pct / 100), 2)
                self._sl_manager.add(
                    symbol=symbol, sl_type="sl",
                    trigger_price=sl_price, shares=shares,
                    note=f"auto SL ({auto_sl_pct}%)",
                )
            if auto_tp_pct and auto_tp_pct > 0:
                tp_price = round(price * (1 + auto_tp_pct / 100), 2)
                self._sl_manager.add(
                    symbol=symbol, sl_type="tp",
                    trigger_price=tp_price, shares=shares,
                    note=f"auto TP ({auto_tp_pct}%)",
                )

            self._save()
            return trade_id

    def sell(self, symbol: str, shares: float, price: float,
             fee_rate: float = 0.004425) -> dict[str, Any]:
        """Record a sell trade. Returns realized P&L info.

        Deducts transaction fees from realized P&L.
        Default fee_rate 0.4425% = TW broker fee (0.1425%) + stamp duty (0.3%).
        """
        with self._lock:
            holdings = self._aggregate()
            holding = next((h for h in holdings if h["symbol"] == symbol), None)

            if not holding or holding["net_shares"] < shares:
                available = holding["net_shares"] if holding else 0
                return {"ok": False, "error": f"持股不足（現有 {available} 股）"}

            avg_cost = holding["avg_cost"]
            trade_value = shares * price
            fee = max(1, trade_value * fee_rate)  # Minimum $1 fee floor
            gross_pnl = (price - avg_cost) * shares
            realized_pnl = gross_pnl - fee
            realized_pnl_pct = (price - avg_cost) / avg_cost * 100 if avg_cost else 0

            trade_id = self._next_id
            self._trades = [
                *self._trades,
                {
                    "id": trade_id,
                    "symbol": symbol,
                    "action": "sell",
                    "shares": shares,
                    "price": price,
                    "date": str(date.today()),
                    "note": f"fee {fee:.0f}",
                    "fee": fee,
                },
            ]
            self._next_id += 1
            self._realized_pnl += realized_pnl
            self._save()

            return {
                "ok": True,
                "trade_id": trade_id,
                "symbol": symbol,
                "shares": shares,
                "sell_price": price,
                "avg_cost": avg_cost,
                "realized_pnl": realized_pnl,
                "realized_pnl_pct": realized_pnl_pct,
            }

    def _aggregate(self) -> list[dict[str, Any]]:
        """Aggregate trades by symbol: net_shares and weighted avg_cost.

        Buy cost basis = shares * raw_price + fee (true total cost).
        """
        with self._lock:
            by_symbol: dict[str, dict] = {}
            for t in self._trades:
                sym = t["symbol"]
                if sym not in by_symbol:
                    by_symbol[sym] = {"total_cost": 0.0, "buy_shares": 0.0, "sell_shares": 0.0}
                if t["action"] == "buy":
                    # Include fee in cost basis for accurate P&L
                    by_symbol[sym]["total_cost"] += t["shares"] * t["price"] + t.get("fee", 0)
                    by_symbol[sym]["buy_shares"] += t["shares"]
                else:
                    by_symbol[sym]["sell_shares"] += t["shares"]

            result = []
            for sym, agg in by_symbol.items():
                net = agg["buy_shares"] - agg["sell_shares"]
                if net <= 0:
                    continue
                avg_cost = agg["total_cost"] / agg["buy_shares"] if agg["buy_shares"] else 0
                result.append({"symbol": sym, "net_shares": net, "avg_cost": avg_cost})
            return result

    def list_holdings(self) -> list[dict[str, Any]]:
        """Return aggregated holdings (net_shares > 0)."""
        with self._lock:
            return self._aggregate()

    # ── Sub-manager accessors ──────────────────────────────────────────────

    @property
    def stop_loss_manager(self) -> StopLossManager:
        return self._sl_manager

    @property
    def dividend_manager(self) -> DividendManager:
        return self._div_manager

    @property
    def rebalance_manager(self) -> RebalanceManager:
        return self._rebal_manager

    @property
    def performance_tracker(self) -> PerformanceTracker:
        return self._perf_tracker

    # ── Futures trading ────────────────────────────────────────────────────

    def open_futures(self, symbol: str, direction: str, contracts: float,
                     entry_price: float, leverage: float, note: str = "") -> int:
        """Open a futures position. Returns position ID."""
        with self._lock:
            pos_id = self._futures_next_id
            margin = (contracts * entry_price) / leverage
            self._futures = [
                *self._futures,
                {
                    "id": pos_id,
                    "symbol": symbol,
                    "direction": direction,  # "long" or "short"
                    "contracts": contracts,
                    "entry_price": entry_price,
                    "current_price": entry_price,
                    "leverage": max(1.0, leverage),
                    "margin": round(margin, 2),
                    "date": str(date.today()),
                    "note": note,
                },
            ]
            self._futures_next_id += 1
            self._save()
            return pos_id

    def close_futures(self, position_id: int, exit_price: float) -> dict[str, Any]:
        """Close a futures position. Returns realized P&L."""
        with self._lock:
            idx = next((i for i, p in enumerate(self._futures) if p["id"] == position_id), None)
            if idx is None:
                return {"ok": False, "error": f"期貨倉位 #{position_id} 不存在"}

            pos = self._futures[idx]
            if pos["direction"] == "long":
                pnl = (exit_price - pos["entry_price"]) * pos["contracts"]
            else:
                pnl = (pos["entry_price"] - exit_price) * pos["contracts"]

            pnl_pct = (pnl / pos["margin"] * 100) if pos["margin"] > 0 else 0
            self._futures_realized_pnl += pnl
            self._futures.pop(idx)
            self._save()

            return {
                "ok": True,
                "position_id": position_id,
                "symbol": pos["symbol"],
                "direction": pos["direction"],
                "contracts": pos["contracts"],
                "entry_price": pos["entry_price"],
                "exit_price": exit_price,
                "realized_pnl": round(pnl, 2),
                "realized_pnl_pct": round(pnl_pct, 2),
            }

    def update_futures_price(self, position_id: int, price: float) -> None:
        """Update current price for a futures position (mark-to-market)."""
        with self._lock:
            for p in self._futures:
                if p["id"] == position_id:
                    p["current_price"] = price
                    self._save()
                    return

    def list_futures(self) -> list[dict[str, Any]]:
        """Return open futures positions with unrealized P&L."""
        with self._lock:
            result = []
            for p in self._futures:
                if p["direction"] == "long":
                    upnl = (p["current_price"] - p["entry_price"]) * p["contracts"]
                else:
                    upnl = (p["entry_price"] - p["current_price"]) * p["contracts"]
                upnl_pct = (upnl / p["margin"] * 100) if p["margin"] > 0 else 0
                result.append({
                    **p,
                    "unrealized_pnl": round(upnl, 2),
                    "unrealized_pnl_pct": round(upnl_pct, 2),
                })
            return result

    # ── Integrity checks ────────────────────────────────────────────────

    def verify_integrity(self) -> dict[str, Any]:
        """Check portfolio internal consistency.

        Verifies that cash, holdings, and realized P&L are self-consistent.
        Returns a dict with status, issues list, and key metrics.
        """
        with self._lock:
            issues = []
            cash = self._initial_capital
            total_buy_cost = 0.0
            total_sell_proceeds = 0.0
            realized_from_trades = 0.0
            bought_shares: dict[str, float] = {}
            bought_cost: dict[str, float] = {}

            for t in self._trades:
                if t["action"] == "buy":
                    cash -= t["shares"] * t["price"]
                    total_buy_cost += t["shares"] * t["price"]
                    bought_shares[t["symbol"]] = bought_shares.get(t["symbol"], 0) + t["shares"]
                    bought_cost[t["symbol"]] = bought_cost.get(t["symbol"], 0) + t["shares"] * t["price"]
                else:
                    cash += t["shares"] * t["price"]
                    total_sell_proceeds += t["shares"] * t["price"]
                    sym = t["symbol"]
                    if sym in bought_shares and bought_shares[sym] > 0:
                        avg_cost = bought_cost[sym] / bought_shares[sym]
                        realized_from_trades += t["shares"] * (t["price"] - avg_cost)
                        sell_shares = min(t["shares"], bought_shares[sym])
                        bought_shares[sym] -= sell_shares
                        bought_cost[sym] = avg_cost * bought_shares[sym] if bought_shares[sym] > 0 else 0

            computed_cash = cash
            stored_cash = self._initial_capital + self._realized_pnl - total_buy_cost + total_sell_proceeds
            actual_cash = self.get_cash()
            equity = self.get_equity()

            if abs(computed_cash - actual_cash) > 1.0:
                issues.append(f"Cash mismatch: computed={computed_cash:.2f} get_cash={actual_cash:.2f}")

            if equity < 0:
                issues.append(f"Negative equity: {equity:.2f}")

            if self._simulation and actual_cash < -self._initial_capital * 0.5:
                issues.append(f"Cash dangerously negative: {actual_cash:.2f} (>{self._initial_capital * -0.5:.0f})")

            holdings = self._aggregate()
            total_holdings_cost = sum(h["net_shares"] * h["avg_cost"] for h in holdings)
            implied_pnl = self._realized_pnl
            expected_pnl = realized_from_trades
            if abs(implied_pnl - expected_pnl) > 1.0:
                issues.append(f"Realized PnL mismatch: stored={implied_pnl:.2f} computed={expected_pnl:.2f}")

            holdings_pct = {}
            for h in holdings:
                pct = (h["net_shares"] * h["avg_cost"] / equity * 100) if equity > 0 else 0
                holdings_pct[h["symbol"]] = round(pct, 1)

            return {
                "ok": len(issues) == 0,
                "issues": issues,
                "equity": round(equity, 2),
                "cash": round(actual_cash, 2),
                "holdings_count": len(holdings),
                "holdings_value": round(total_holdings_cost, 2),
                "holdings_concentration": holdings_pct,
                "realized_pnl": round(implied_pnl, 2),
                "total_trades": len(self._trades),
            }
