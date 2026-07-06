"""
Day Trading Simulation (當沖模擬)

A lightweight, independent day trading simulator with 30,000 TWD capital.
Separate from the main PortfolioManager (long-term holdings).

Features:
  - Cash-limited buying (no margin)
  - Same-day round-trip enforcement
  - Per-trade P&L tracking (USD + TWD)
  - Daily and total P&L aggregation
  - AI committee signal integration for trade ideas
"""

import json
import logging
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DAYTRADE_FILE = Path.home() / "telegram-claude-bot" / "daytrade_sim.json"
COMMITTEE_FILE = Path.home() / "telegram-claude-bot" / "data" / "committee" / "daily_signals.json"
DEFAULT_CAPITAL_TWD = 100000
DEFAULT_USD_TWD_RATE = 33.0


class DayTraderSim:
    """Day trading simulation account, independent of the main portfolio."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._positions: list[dict[str, Any]] = []
        self._trade_history: list[dict[str, Any]] = []
        self._initial_capital: float = DEFAULT_CAPITAL_TWD
        self._cash: float = DEFAULT_CAPITAL_TWD
        self._total_realized_pnl: float = 0.0
        self._next_id: int = 1
        self._usd_twd_rate: float = DEFAULT_USD_TWD_RATE
        self._daily_pnl: dict[str, dict[str, Any]] = {}
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _file_path(self) -> Path:
        return DAYTRADE_FILE

    def _load(self) -> None:
        with self._lock:
            if not DAYTRADE_FILE.exists():
                logger.info("No daytrade_sim.json found, starting fresh with %d TWD", DEFAULT_CAPITAL_TWD)
                return
            try:
                data = json.loads(DAYTRADE_FILE.read_text())
                self._initial_capital = float(data.get("initial_capital", DEFAULT_CAPITAL_TWD))
                self._cash = float(data.get("cash", self._initial_capital))
                self._usd_twd_rate = float(data.get("usd_twd_rate", DEFAULT_USD_TWD_RATE))
                self._total_realized_pnl = float(data.get("total_realized_pnl", 0.0))
                self._next_id = int(data.get("next_id", 1))
                self._positions = list(data.get("positions", []))
                self._trade_history = list(data.get("trade_history", []))
                self._daily_pnl = dict(data.get("daily_pnl", {}))
                logger.info("Day trader loaded: cash=%.0f TWD, %d positions", self._cash, len(self._positions))
            except Exception:
                logger.exception("Failed to load daytrade_sim.json, using defaults")

    def _save(self) -> None:
        with self._lock:
            try:
                DAYTRADE_FILE.parent.mkdir(parents=True, exist_ok=True)
                DAYTRADE_FILE.write_text(json.dumps({
                    "initial_capital": self._initial_capital,
                    "cash": self._cash,
                    "usd_twd_rate": self._usd_twd_rate,
                    "total_realized_pnl": self._total_realized_pnl,
                    "next_id": self._next_id,
                    "positions": self._positions,
                    "trade_history": self._trade_history,
                    "daily_pnl": self._daily_pnl,
                }, ensure_ascii=False, indent=2))
            except Exception:
                logger.exception("Failed to save daytrade_sim.json")

    # ── Core Trading ─────────────────────────────────────────────────────────

    def buy(self, symbol: str, shares: float, price_usd: float, note: str = "") -> int:
        """Open a day trade position. Returns position ID (0 if rejected).

        Rejects if:
          - Insufficient cash after USD→TWD conversion
          - Already holding the same symbol intraday
        """
        with self._lock:
            symbol = symbol.upper().strip()

            # Check for existing open position in the same symbol
            if any(p["symbol"] == symbol for p in self._positions):
                logger.warning("Day trade buy %s rejected: already holding", symbol)
                return 0

            cost_twd = shares * price_usd * self._usd_twd_rate
            if cost_twd > self._cash + 1:  # $1 tolerance for floating point
                logger.warning(
                    "Day trade buy %s x%s @ $%.2f = TWD %.0f failed: cash %.0f insufficient",
                    symbol, shares, price_usd, cost_twd, self._cash,
                )
                return 0

            position_id = self._next_id
            now = datetime.now()
            self._positions.append({
                "id": position_id,
                "symbol": symbol,
                "shares": shares,
                "entry_price_usd": price_usd,
                "entry_price_twd": round(price_usd * self._usd_twd_rate, 2),
                "entry_date": str(date.today()),
                "entry_time": now.strftime("%H:%M:%S"),
                "note": note,
            })
            self._next_id += 1
            self._cash -= cost_twd
            self._save()
            logger.info("Day trade BUY #%d %s x%s @ $%.2f (TWD %.0f)", position_id, symbol, shares, price_usd, cost_twd)
            return position_id

    def add_to_position(self, position_id: int, shares: float, price_usd: float) -> dict[str, Any]:
        """Add shares to an existing open position (pyramiding).

        Returns dict with {ok, position_id, symbol, total_shares, new_avg_price}.
        Rejects if insufficient cash or position not found.
        """
        with self._lock:
            idx = next((i for i, p in enumerate(self._positions) if p["id"] == position_id), None)
            if idx is None:
                return {"ok": False, "error": f"Position #{position_id} not found"}

            position = self._positions[idx]
            if position["entry_date"] != str(date.today()):
                return {
                    "ok": False,
                    "error": f"Position #{position_id} opened on {position['entry_date']}, not today — cannot add",
                }

            cost_twd = shares * price_usd * self._usd_twd_rate
            if cost_twd > self._cash + 1:
                return {"ok": False, "error": f"Insufficient cash: need TWD {cost_twd:.0f}, have {self._cash:.0f}"}

            # Weighted average entry price
            old_shares = position["shares"]
            old_cost = position["entry_price_usd"] * old_shares
            new_cost = price_usd * shares
            total_shares = old_shares + shares
            new_avg = round((old_cost + new_cost) / total_shares, 4) if total_shares > 0 else price_usd

            position["shares"] = total_shares
            position["entry_price_usd"] = new_avg
            position["entry_price_twd"] = round(new_avg * self._usd_twd_rate, 2)
            self._cash -= cost_twd
            self._save()
            logger.info(
                "Day trade ADD #%d %s +%s @ $%.2f → total %s @ $%.4f",
                position_id, position["symbol"], shares, price_usd, total_shares, new_avg,
            )
            return {
                "ok": True,
                "position_id": position_id,
                "symbol": position["symbol"],
                "added_shares": shares,
                "total_shares": total_shares,
                "new_avg_price": new_avg,
                "add_price": price_usd,
            }

    def sell(self, position_id: int, price_usd: float) -> dict[str, Any]:
        """Close a day trade position by ID. Returns P&L info.

        Rejects if position not found or not opened today.
        """
        with self._lock:
            idx = next((i for i, p in enumerate(self._positions) if p["id"] == position_id), None)
            if idx is None:
                return {"ok": False, "error": f"Position #{position_id} not found"}

            position = self._positions[idx]
            if position["entry_date"] != str(date.today()):
                return {
                    "ok": False,
                    "error": f"Position #{position_id} {position['symbol']} opened on {position['entry_date']}, not today — not a day trade",
                }

            shares = position["shares"]
            entry_usd = position["entry_price_usd"]
            entry_twd = position["entry_price_twd"]

            pnl_usd = (price_usd - entry_usd) * shares
            pnl_twd = round(pnl_usd * self._usd_twd_rate, 2)
            pnl_pct = ((price_usd - entry_usd) / entry_usd * 100) if entry_usd else 0

            now = datetime.now()
            trade_record = {
                "id": position_id,
                "symbol": position["symbol"],
                "shares": shares,
                "entry_price_usd": entry_usd,
                "exit_price_usd": price_usd,
                "entry_price_twd": entry_twd,
                "exit_price_twd": round(price_usd * self._usd_twd_rate, 2),
                "pnl_usd": round(pnl_usd, 2),
                "pnl_twd": pnl_twd,
                "pnl_pct": round(pnl_pct, 2),
                "entry_date": position["entry_date"],
                "exit_date": str(date.today()),
                "entry_time": position["entry_time"],
                "exit_time": now.strftime("%H:%M:%S"),
                "note": position.get("note", ""),
            }

            # Credit cash
            sell_proceeds_twd = shares * price_usd * self._usd_twd_rate
            self._cash += sell_proceeds_twd
            self._total_realized_pnl += pnl_twd

            # Update daily PnL
            today = str(date.today())
            if today not in self._daily_pnl:
                self._daily_pnl[today] = {"realized_pnl_twd": 0.0, "realized_pnl_usd": 0.0, "trades_count": 0}
            self._daily_pnl[today]["realized_pnl_twd"] = round(
                self._daily_pnl[today]["realized_pnl_twd"] + pnl_twd, 2
            )
            self._daily_pnl[today]["realized_pnl_usd"] = round(
                self._daily_pnl[today]["realized_pnl_usd"] + pnl_usd, 2
            )
            self._daily_pnl[today]["trades_count"] += 1

            # Move from positions to history
            self._trade_history.append(trade_record)
            self._positions.pop(idx)
            self._save()

            logger.info(
                "Day trade SELL #%d %s: $%.2f → $%.2f | PnL %+.2f TWD (%+.2f%%)",
                position_id, position["symbol"], entry_usd, price_usd, pnl_twd, pnl_pct,
            )

            return {
                "ok": True,
                "trade_id": position_id,
                "symbol": position["symbol"],
                "shares": shares,
                "entry_price": entry_usd,
                "exit_price": price_usd,
                "pnl_usd": round(pnl_usd, 2),
                "pnl_twd": pnl_twd,
                "pnl_pct": round(pnl_pct, 2),
            }

    def sell_by_symbol(self, symbol: str, shares: Optional[float] = None, price_usd: float = 0.0) -> dict[str, Any]:
        """Close a day trade position by symbol. Uses first matching open position."""
        with self._lock:
            for p in self._positions:
                if p["symbol"] == symbol.upper().strip():
                    if shares is not None and shares != p["shares"]:
                        continue
                    return self.sell(p["id"], price_usd)
            return {"ok": False, "error": f"No open position for {symbol.upper()}"}

    def force_close(self, position_id: int, price_usd: float) -> dict[str, Any]:
        """Force close a position bypassing the same-day check. Used for stuck positions."""
        with self._lock:
            idx = next((i for i, p in enumerate(self._positions) if p["id"] == position_id), None)
            if idx is None:
                return {"ok": False, "error": f"Position #{position_id} not found"}

            position = self._positions[idx]
            shares = position["shares"]
            entry_usd = position["entry_price_usd"]
            entry_twd = position["entry_price_twd"]

            pnl_usd = (price_usd - entry_usd) * shares
            pnl_twd = round(pnl_usd * self._usd_twd_rate, 2)
            pnl_pct = ((price_usd - entry_usd) / entry_usd * 100) if entry_usd else 0

            now = datetime.now()
            trade_record = {
                "id": position_id,
                "symbol": position["symbol"],
                "shares": shares,
                "entry_price_usd": entry_usd,
                "exit_price_usd": price_usd,
                "entry_price_twd": entry_twd,
                "exit_price_twd": round(price_usd * self._usd_twd_rate, 2),
                "pnl_usd": round(pnl_usd, 2),
                "pnl_twd": pnl_twd,
                "pnl_pct": round(pnl_pct, 2),
                "entry_date": position["entry_date"],
                "exit_date": str(date.today()),
                "entry_time": position["entry_time"],
                "exit_time": now.strftime("%H:%M:%S"),
                "note": position.get("note", "") + " [force closed]",
            }

            sell_proceeds_twd = shares * price_usd * self._usd_twd_rate
            self._cash += sell_proceeds_twd
            self._total_realized_pnl += pnl_twd

            today = str(date.today())
            if today not in self._daily_pnl:
                self._daily_pnl[today] = {"realized_pnl_twd": 0.0, "realized_pnl_usd": 0.0, "trades_count": 0}
            self._daily_pnl[today]["realized_pnl_twd"] = round(
                self._daily_pnl[today]["realized_pnl_twd"] + pnl_twd, 2
            )
            self._daily_pnl[today]["realized_pnl_usd"] = round(
                self._daily_pnl[today]["realized_pnl_usd"] + pnl_usd, 2
            )
            self._daily_pnl[today]["trades_count"] += 1

            self._trade_history.append(trade_record)
            self._positions.pop(idx)
            self._save()

            logger.info(
                "FORCE CLOSE #%d %s: $%.2f → $%.2f | PnL %+.2f TWD (%+.2f%%)",
                position_id, position["symbol"], entry_usd, price_usd, pnl_twd, pnl_pct,
            )

            return {
                "ok": True,
                "trade_id": position_id,
                "symbol": position["symbol"],
                "shares": shares,
                "entry_price": entry_usd,
                "exit_price": price_usd,
                "pnl_usd": round(pnl_usd, 2),
                "pnl_twd": pnl_twd,
                "pnl_pct": round(pnl_pct, 2),
            }

    # ── Queries ──────────────────────────────────────────────────────────────

    def get_cash(self) -> float:
        with self._lock:
            return self._cash

    def get_buying_power(self) -> float:
        return self.get_cash()  # No margin for day trading

    def get_equity(self) -> float:
        with self._lock:
            positions_value = sum(
                p["shares"] * p["entry_price_usd"] * self._usd_twd_rate
                for p in self._positions
            )
            return self._cash + positions_value + max(0, self._total_realized_pnl)

    def list_positions(self) -> list[dict[str, Any]]:
        """List open positions with live prices injected."""
        with self._lock:
            positions = list(self._positions)
        # Fetch live prices for all held symbols
        symbols = list({p["symbol"] for p in positions})
        live_prices = self._fetch_prices(symbols)
        results = []
        for p in positions:
            sym = p["symbol"]
            live = live_prices.get(sym)
            entry_usd = p["entry_price_usd"]
            shares = p["shares"]
            if live is not None:
                current_price = round(live, 2)
                unrealized_usd = round((live - entry_usd) * shares, 2)
                unrealized_pct = round((live - entry_usd) / entry_usd * 100, 2) if entry_usd else 0
            else:
                current_price = entry_usd
                unrealized_usd = 0.0
                unrealized_pct = 0.0
            results.append({
                "id": p["id"],
                "symbol": sym,
                "shares": shares,
                "entry_price_usd": entry_usd,
                "current_price_usd": current_price,
                "unrealized_pnl_usd": unrealized_usd,
                "unrealized_pnl_pct": unrealized_pct,
                "entry_time": p.get("entry_time", ""),
                "note": p.get("note", ""),
            })
        return results

    def get_position(self, position_id: int) -> Optional[dict[str, Any]]:
        with self._lock:
            for p in self._positions:
                if p["id"] == position_id:
                    return dict(p)
        return None

    def get_daily_pnl(self, date_str: Optional[str] = None) -> dict[str, Any]:
        today = date_str or str(date.today())
        with self._lock:
            return dict(self._daily_pnl.get(today, {
                "realized_pnl_twd": 0.0,
                "realized_pnl_usd": 0.0,
                "trades_count": 0,
            }))

    def get_total_pnl(self) -> float:
        with self._lock:
            return self._total_realized_pnl

    def set_usd_rate(self, rate: float) -> None:
        with self._lock:
            self._usd_twd_rate = rate
            self._save()

    # ── Committee Integration ────────────────────────────────────────────────

    def get_trade_ideas(self, min_confidence: float = 0.6, max_results: int = 5) -> list[dict[str, Any]]:
        """Read committee daily_signals.json and return top US stock trade ideas."""
        if not COMMITTEE_FILE.exists():
            logger.debug("No committee signals file at %s", COMMITTEE_FILE)
            return []
        try:
            data = json.loads(COMMITTEE_FILE.read_text())
        except Exception:
            logger.exception("Failed to read committee signals")
            return []

        us_stocks = data.get("us_stocks", [])
        ideas = []
        for s in us_stocks:
            for sig in s.get("signals", []):
                action = sig.get("action", "")
                if action not in ("strong_buy", "buy"):
                    continue
                confidence = sig.get("confidence", 0)
                if confidence < min_confidence:
                    continue
                # Best effort price from technical or metrics
                price = (
                    s.get("technical", {}).get("current_price")
                    or s.get("metrics", {}).get("current_price")
                    or 0
                )
                ideas.append({
                    "symbol": s["code"],
                    "name": s.get("name", s["code"]),
                    "action": action,
                    "confidence": confidence,
                    "price": round(price, 2) if price else 0,
                    "reason": sig.get("reason", ""),
                })
                break  # one signal per stock

        ideas.sort(key=lambda x: -x["confidence"])
        return ideas[:max_results]

    # ── Summary ──────────────────────────────────────────────────────────────

    def summary_text(self) -> str:
        """Return a Telegram-formatted summary of the day trading account."""
        with self._lock:
            cash = self._cash
            total_pnl = self._total_realized_pnl
            positions_count = len(self._positions)
            equity = cash + sum(
                p["shares"] * p["entry_price_usd"] * self._usd_twd_rate
                for p in self._positions
            ) + max(0, total_pnl)
            daily = self.get_daily_pnl()
            daily_pnl_twd = daily.get("realized_pnl_twd", 0)
            daily_trades = daily.get("trades_count", 0)

        lines = [
            "📊 **當沖模擬帳戶**",
            f"資金: NT${self._initial_capital:,.0f}（獨立於主投資組合）",
            f"現金: NT${cash:,.0f} | 權益總額: NT${equity:,.0f}",
            f"USD/TWD: {self._usd_twd_rate}",
        ]

        positions = self.list_positions()
        if positions:
            lines.append(f"\n**當前持倉 ({len(positions)})：**")
            for p in positions:
                pnl = p["unrealized_pnl_usd"]
                sign = "▲" if pnl >= 0 else "▼"
                lines.append(
                    f"  #{p['id']} {p['symbol']} x{p['shares']:.0f} "
                    f"@ ${p['entry_price_usd']:.2f} → ${p['current_price_usd']:.2f} "
                    f"| 未實現 {sign} ${abs(pnl):.2f} ({p['unrealized_pnl_pct']:+.2f}%)"
                )
        else:
            lines.append("\n**當前持倉：** 無")

        pnl_sign = "▲" if daily_pnl_twd >= 0 else "▼"
        lines.append(
            f"\n**本日損益：** {pnl_sign} NT${abs(daily_pnl_twd):,.0f} "
            f"({daily_trades} 筆交易)"
        )

        total_sign = "▲" if total_pnl >= 0 else "▼"
        lines.append(f"**累計損益：** {total_sign} NT${abs(total_pnl):,.0f}")

        return "\n".join(lines)

    # ── Live Prices ──────────────────────────────────────────────────────────

    @staticmethod
    def _fetch_prices(symbols: list[str]) -> dict[str, float]:
        """Fetch current prices via yfinance. Returns {symbol: price_usd}."""
        if not symbols:
            return {}
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not available for live prices")
            return {}
        prices = {}
        for sym in symbols:
            try:
                ticker = yf.Ticker(sym)
                hist = ticker.history(period="2d")
                if hist is not None and len(hist) >= 1:
                    prices[sym] = float(hist["Close"].iloc[-1])
                else:
                    info = ticker.info or {}
                    p = info.get("currentPrice") or info.get("regularMarketPreviousClose")
                    if p:
                        prices[sym] = float(p)
            except Exception:
                logger.debug("Failed to fetch price for %s", sym)
        return prices
