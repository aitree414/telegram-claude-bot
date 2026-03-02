import json
import logging
import threading
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PORTFOLIO_FILE = Path.home() / "telegram-claude-bot" / "portfolio.json"


class PortfolioManager:
    def __init__(self) -> None:
        self._trades: list[dict[str, Any]] = []
        self._next_id = 1
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        with self._lock:
            if PORTFOLIO_FILE.exists():
                try:
                    data = json.loads(PORTFOLIO_FILE.read_text())
                    self._trades = data.get("trades", [])
                    self._next_id = data.get("next_id", 1)
                except Exception:
                    logger.exception("載入 portfolio 失敗")

    def _save(self) -> None:
        with self._lock:
            try:
                PORTFOLIO_FILE.parent.mkdir(parents=True, exist_ok=True)
                PORTFOLIO_FILE.write_text(
                    json.dumps(
                        {"trades": self._trades, "next_id": self._next_id},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            except Exception:
                logger.exception("儲存 portfolio 失敗")

    def buy(self, symbol: str, shares: float, price: float, note: str = "") -> int:
        """Record a buy trade. Returns trade ID."""
        with self._lock:
            trade_id = self._next_id
            self._trades = [
                *self._trades,
                {
                    "id": trade_id,
                    "symbol": symbol,
                    "action": "buy",
                    "shares": shares,
                    "price": price,
                    "date": str(date.today()),
                    "note": note,
                },
            ]
            self._next_id += 1
            self._save()
            return trade_id

    def sell(self, symbol: str, shares: float, price: float) -> dict[str, Any]:
        """Record a sell trade. Returns realized P&L info."""
        with self._lock:
            holdings = self._aggregate()
            holding = next((h for h in holdings if h["symbol"] == symbol), None)

            if not holding or holding["net_shares"] < shares:
                available = holding["net_shares"] if holding else 0
                return {"ok": False, "error": f"持股不足（現有 {available} 股）"}

            avg_cost = holding["avg_cost"]
            realized_pnl = (price - avg_cost) * shares
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
                    "note": "",
                },
            ]
            self._next_id += 1
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
        """Aggregate trades by symbol: net_shares and weighted avg_cost."""
        with self._lock:
            by_symbol: dict[str, dict] = {}
            for t in self._trades:
                sym = t["symbol"]
                if sym not in by_symbol:
                    by_symbol[sym] = {"total_cost": 0.0, "buy_shares": 0.0, "sell_shares": 0.0}
                if t["action"] == "buy":
                    by_symbol[sym]["total_cost"] += t["shares"] * t["price"]
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
