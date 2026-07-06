import json
import logging
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BASE_DIR = Path.home() / "telegram-claude-bot"
STOP_LOSS_FILE = BASE_DIR / "stop_losses.json"
DIVIDENDS_FILE = BASE_DIR / "dividends.json"
REBALANCE_FILE = BASE_DIR / "rebalance_plans.json"
PERFORMANCE_FILE = BASE_DIR / "performance_history.json"


class StopLossManager:
    """Manage stop-loss and take-profit conditions.

    Each condition monitors a symbol; when trigger_price is crossed the
    condition fires and can be used to auto-sell.
    """

    def __init__(self, simulation: bool = False) -> None:
        self._items: list[dict[str, Any]] = []
        self._next_id = 1
        self._lock = threading.RLock()
        self._simulation = simulation
        self._load()

    def _file_path(self) -> Path:
        return STOP_LOSS_FILE

    def _load(self) -> None:
        with self._lock:
            fp = self._file_path()
            if fp.exists():
                try:
                    data = json.loads(fp.read_text())
                    self._items = data.get("items", [])
                    self._next_id = data.get("next_id", 1)
                except Exception:
                    logger.exception("載入停損/停利設定失敗")

    def _save(self) -> None:
        with self._lock:
            try:
                fp = self._file_path()
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(json.dumps(
                    {"items": self._items, "next_id": self._next_id},
                    ensure_ascii=False, indent=2,
                ))
            except Exception:
                logger.exception("儲存停損/停利設定失敗")

    def add(self, symbol: str, sl_type: str, trigger_price: float,
            shares: float, note: str = "") -> int:
        """Add a stop-loss or take-profit condition.

        sl_type: "sl" (stop-loss) or "tp" (take-profit)
        """
        with self._lock:
            item_id = self._next_id
            self._items.append({
                "id": item_id,
                "symbol": symbol,
                "type": sl_type,
                "trigger_price": trigger_price,
                "shares": shares,
                "status": "active",
                "created_at": str(date.today()),
                "note": note,
            })
            self._next_id += 1
            self._save()
            return item_id

    def remove(self, item_id: int) -> bool:
        with self._lock:
            before = len(self._items)
            self._items = [i for i in self._items if i["id"] != item_id]
            if len(self._items) < before:
                self._save()
                return True
            return False

    def list_active(self) -> list[dict[str, Any]]:
        with self._lock:
            return [i for i in self._items if i["status"] == "active"]

    def list_all(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._items)

    def mark_triggered(self, item_id: int) -> None:
        with self._lock:
            for i in self._items:
                if i["id"] == item_id:
                    i["status"] = "triggered"
                    self._save()
                    return

    def check(self, current_prices: dict[str, float]) -> list[dict[str, Any]]:
        """Check all active conditions against current prices.

        Returns list of triggered items, each with current_price injected.
        For SL: triggered when price <= trigger_price.
        For TP: triggered when price >= trigger_price.
        """
        triggered = []
        with self._lock:
            for item in self._items:
                if item["status"] != "active":
                    continue
                price = current_prices.get(item["symbol"])
                if price is None:
                    continue
                if item["type"] == "sl" and price <= item["trigger_price"]:
                    item["status"] = "triggered"
                    item["_triggered_price"] = price
                    triggered.append(dict(item))
                elif item["type"] == "tp" and price >= item["trigger_price"]:
                    item["status"] = "triggered"
                    item["_triggered_price"] = price
                    triggered.append(dict(item))
            if triggered:
                self._save()
        return triggered


class DividendManager:
    """Track dividend records and upcoming ex-dividend dates."""

    def __init__(self, simulation: bool = False) -> None:
        self._items: list[dict[str, Any]] = []
        self._next_id = 1
        self._lock = threading.RLock()
        self._simulation = simulation
        self._load()

    def _file_path(self) -> Path:
        return DIVIDENDS_FILE

    def _load(self) -> None:
        with self._lock:
            fp = self._file_path()
            if fp.exists():
                try:
                    data = json.loads(fp.read_text())
                    self._items = data.get("items", [])
                    self._next_id = data.get("next_id", 1)
                except Exception:
                    logger.exception("載入股利資料失敗")

    def _save(self) -> None:
        with self._lock:
            try:
                fp = self._file_path()
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(json.dumps(
                    {"items": self._items, "next_id": self._next_id},
                    ensure_ascii=False, indent=2,
                ))
            except Exception:
                logger.exception("儲存股利資料失敗")

    def add(self, symbol: str, ex_date: str, amount_per_share: float,
            pay_date: str = "", shares_held: float = 0,
            note: str = "") -> int:
        """Add a dividend record."""
        with self._lock:
            item_id = self._next_id
            self._items.append({
                "id": item_id,
                "symbol": symbol,
                "ex_date": ex_date,
                "pay_date": pay_date or "",
                "amount_per_share": amount_per_share,
                "shares_held": shares_held,
                "status": "pending",
                "note": note,
            })
            self._next_id += 1
            self._save()
            return item_id

    def remove(self, item_id: int) -> bool:
        with self._lock:
            before = len(self._items)
            self._items = [i for i in self._items if i["id"] != item_id]
            if len(self._items) < before:
                self._save()
                return True
            return False

    def mark_paid(self, item_id: int) -> None:
        with self._lock:
            for i in self._items:
                if i["id"] == item_id:
                    i["status"] = "paid"
                    self._save()
                    return

    def list_upcoming(self, days: int = 30) -> list[dict[str, Any]]:
        """Return dividends with ex_date within the next N days."""
        with self._lock:
            today = date.today()
            cutoff = today + timedelta(days=days)
            result = []
            for i in self._items:
                if i["status"] != "pending":
                    continue
                try:
                    ex = datetime.strptime(i["ex_date"], "%Y-%m-%d").date()
                    if today <= ex <= cutoff:
                        result.append(i)
                except ValueError:
                    continue
            return result

    def list_all(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._items)

    def get_estimated_income(self, item_id: int,
                             actual_shares: float = 0) -> float:
        """Estimate dividend income for a record."""
        with self._lock:
            for i in self._items:
                if i["id"] == item_id:
                    shares = actual_shares or i["shares_held"]
                    return shares * i["amount_per_share"]
            return 0.0


class RebalanceManager:
    """Track target allocation and detect deviation."""

    def __init__(self, simulation: bool = False) -> None:
        self._plans: list[dict[str, Any]] = []
        self._next_id = 1
        self._lock = threading.RLock()
        self._simulation = simulation
        self._load()

    def _file_path(self) -> Path:
        return REBALANCE_FILE

    def _load(self) -> None:
        with self._lock:
            fp = self._file_path()
            if fp.exists():
                try:
                    data = json.loads(fp.read_text())
                    self._plans = data.get("plans", [])
                    self._next_id = data.get("next_id", 1)
                except Exception:
                    logger.exception("載入再平衡設定失敗")

    def _save(self) -> None:
        with self._lock:
            try:
                fp = self._file_path()
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(json.dumps(
                    {"plans": self._plans, "next_id": self._next_id},
                    ensure_ascii=False, indent=2,
                ))
            except Exception:
                logger.exception("儲存再平衡設定失敗")

    def set_targets(self, name: str, targets: list[dict],
                    tolerance_pct: float = 5.0) -> int:
        """Set or update a rebalance plan.

        targets: [{symbol, target_pct}, ...]
        tolerance_pct: max allowed deviation before signal fires.
        """
        with self._lock:
            existing = next((p for p in self._plans if p["name"] == name), None)
            if existing:
                existing["targets"] = targets
                existing["tolerance_pct"] = tolerance_pct
                existing["last_rebalance_date"] = str(date.today())
                plan_id = existing["id"]
            else:
                plan_id = self._next_id
                self._plans.append({
                    "id": plan_id,
                    "name": name,
                    "targets": targets,
                    "tolerance_pct": tolerance_pct,
                    "last_rebalance_date": str(date.today()),
                })
                self._next_id += 1
            self._save()
            return plan_id

    def remove(self, plan_id: int) -> bool:
        with self._lock:
            before = len(self._plans)
            self._plans = [p for p in self._plans if p["id"] != plan_id]
            if len(self._plans) < before:
                self._save()
                return True
            return False

    def list_plans(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._plans)

    def check_deviation(self, current_holdings: list[dict],
                        current_prices: dict[str, float]) -> list[dict]:
        """Check deviation for each plan.

        current_holdings: [{symbol, net_shares, avg_cost}, ...]
        current_prices: {symbol: current_price}

        Returns list of deviation results.
        """
        results = []
        with self._lock:
            total_value = sum(
                h["net_shares"] * current_prices.get(h["symbol"], 0)
                for h in current_holdings
                if current_prices.get(h["symbol"], 0) > 0
            )
            if total_value <= 0:
                return results

            for plan in self._plans:
                deviations = []
                for t in plan["targets"]:
                    sym = t["symbol"]
                    cur_price = current_prices.get(sym, 0)
                    holding = next(
                        (h for h in current_holdings if h["symbol"] == sym),
                        None
                    )
                    if holding and cur_price > 0:
                        actual_pct = (holding["net_shares"] * cur_price / total_value) * 100
                    else:
                        actual_pct = 0.0
                    target_pct = t["target_pct"]
                    deviation = actual_pct - target_pct
                    needs_action = abs(deviation) > plan["tolerance_pct"]
                    deviations.append({
                        "symbol": sym,
                        "target_pct": target_pct,
                        "actual_pct": round(actual_pct, 2),
                        "deviation": round(deviation, 2),
                        "needs_action": needs_action,
                    })
                results.append({
                    "plan_id": plan["id"],
                    "plan_name": plan["name"],
                    "tolerance_pct": plan["tolerance_pct"],
                    "total_value": round(total_value, 2),
                    "deviations": deviations,
                    "needs_rebalance": any(d["needs_action"] for d in deviations),
                })
        return results


class PerformanceTracker:
    """Track daily portfolio snapshots for performance reporting.

    Stores one snapshot per day with equity, cash, holdings value, P&L.
    History is append-only (no deletion) for audit trail.
    """

    def __init__(self, simulation: bool = False) -> None:
        self._snapshots: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self._simulation = simulation
        self._load()

    def _file_path(self) -> Path:
        return PERFORMANCE_FILE

    def _load(self) -> None:
        with self._lock:
            fp = self._file_path()
            if fp.exists():
                try:
                    data = json.loads(fp.read_text())
                    self._snapshots = data.get("snapshots", [])
                except Exception:
                    logger.exception("載入績效歷史失敗")

    def _save(self) -> None:
        with self._lock:
            try:
                fp = self._file_path()
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(json.dumps(
                    {"snapshots": self._snapshots},
                    ensure_ascii=False, indent=2,
                ))
            except Exception:
                logger.exception("儲存績效歷史失敗")

    def record_snapshot(self, initial_capital: float, cash: float,
                        holdings_value: float, realized_pnl: float,
                        futures_upnl: float = 0.0) -> dict[str, Any]:
        """Record a daily performance snapshot.

        Returns the snapshot dict.
        """
        with self._lock:
            # equity = cash + holdings at market value (realized_pnl is already in cash)
            equity = cash + holdings_value
            total_pnl = equity - initial_capital + futures_upnl
            pnl_pct = (total_pnl / initial_capital * 100) if initial_capital > 0 else 0.0

            snapshot = {
                "date": str(date.today()),
                "initial_capital": initial_capital,
                "equity": round(equity, 2),
                "cash": round(cash, 2),
                "holdings_value": round(holdings_value, 2),
                "realized_pnl": round(realized_pnl, 2),
                "futures_upnl": round(futures_upnl, 2),
                "total_pnl": round(total_pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
            }

            # Compute MDD from full history
            all_equities = [s["equity"] for s in self._snapshots] + [equity]
            peak = max(all_equities) if all_equities else equity
            mdd_pct = ((peak - equity) / peak * 100) if peak > 0 else 0.0
            snapshot["mdd"] = round(mdd_pct, 2)

            # Avoid duplicate same-date entries (overwrite if exists)
            existing = next(
                (s for s in self._snapshots if s["date"] == snapshot["date"]),
                None
            )
            if existing:
                existing.update(snapshot)
            else:
                self._snapshots.append(snapshot)

            self._snapshots.sort(key=lambda s: s["date"])
            self._save()
            return snapshot

    def get_snapshots(self, days: int = 0) -> list[dict[str, Any]]:
        """Return snapshots, optionally limited to last N days."""
        with self._lock:
            if days > 0 and len(self._snapshots) > days:
                return self._snapshots[-days:]
            return list(self._snapshots)

    def get_max_drawdown(self) -> dict[str, Any]:
        """Return max drawdown with start/end dates."""
        with self._lock:
            if not self._snapshots:
                return {"mdd": 0.0, "start_date": "", "end_date": ""}

            peak = 0.0
            peak_date = ""
            mdd = 0.0
            mdd_start = ""
            mdd_end = ""

            for s in self._snapshots:
                eq = s["equity"]
                if eq > peak:
                    peak = eq
                    peak_date = s["date"]
                else:
                    dd = (peak - eq) / peak * 100 if peak > 0 else 0
                    if dd > mdd:
                        mdd = dd
                        mdd_start = peak_date
                        mdd_end = s["date"]

            return {
                "mdd": round(mdd, 2),
                "start_date": mdd_start,
                "end_date": mdd_end,
            }

    def get_daily_returns(self, days: int = 30) -> list[dict[str, Any]]:
        """Calculate daily return % from consecutive snapshots."""
        with self._lock:
            snaps = self._snapshots[-days:] if days > 0 else self._snapshots
            returns = []
            for i in range(1, len(snaps)):
                prev = snaps[i - 1]["equity"]
                if prev > 0:
                    ret = (snaps[i]["equity"] - prev) / prev * 100
                else:
                    ret = 0.0
                returns.append({
                    "date": snaps[i]["date"],
                    "return_pct": round(ret, 2),
                })
            return returns

    def get_summary(self) -> dict[str, Any]:
        """Return summary metrics from snapshot history."""
        with self._lock:
            if not self._snapshots:
                return {}

            first = self._snapshots[0]
            last = self._snapshots[-1]
            total_return = last["pnl_pct"]

            # Simple annualized return
            try:
                d0 = datetime.strptime(first["date"], "%Y-%m-%d")
                d1 = datetime.strptime(last["date"], "%Y-%m-%d")
                days_elapsed = (d1 - d0).days
            except ValueError:
                days_elapsed = 0

            if days_elapsed > 0:
                annualized = ((1 + total_return / 100) ** (365 / days_elapsed) - 1) * 100
            else:
                annualized = 0.0

            # Daily returns for Sharpe
            returns = self.get_daily_returns(0)
            ret_values = [r["return_pct"] for r in returns]
            avg_ret = sum(ret_values) / len(ret_values) if ret_values else 0
            std_ret = (
                (sum((r - avg_ret) ** 2 for r in ret_values) / len(ret_values)) ** 0.5
                if len(ret_values) > 1 else 0
            )
            sharpe = (avg_ret / std_ret * (252 ** 0.5)) if std_ret > 0 else 0.0

            mdd_info = self.get_max_drawdown()

            return {
                "total_return_pct": round(total_return, 2),
                "annualized_return_pct": round(annualized, 2),
                "sharpe_ratio": round(sharpe, 2),
                "mdd": mdd_info["mdd"],
                "mdd_start": mdd_info["start_date"],
                "mdd_end": mdd_info["end_date"],
                "days_tracked": days_elapsed,
                "snapshot_count": len(self._snapshots),
                "last_snapshot": last["date"],
            }
