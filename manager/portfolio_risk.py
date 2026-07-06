"""Portfolio-level risk management — extends beyond onchain trades to cover
the entire investment portfolio (stocks, crypto, etc.).

Features
--------
- Concentration limits (single asset, sector)
- Maximum open positions (absolute & per-asset)
- Combined daily trade limit (stocks + onchain)
- Portfolio-level stop-loss / drawdown alert
"""

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class PortfolioRiskManager:
    """Unified risk manager for the entire investment portfolio."""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path.home() / "telegram-claude-bot"
        self._state_file = self.data_dir / "portfolio_risk.json"
        self._state = self._load()

    # ------------------------------------------------------------------
    # Persistent state (daily counters reset each day)
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        if self._state_file.exists():
            try:
                return json.loads(self._state_file.read_text())
            except Exception:
                logger.exception("Failed to load portfolio risk state")
        return self._default_state()

    def _default_state(self) -> dict:
        return {
            "date": str(date.today()),
            "stock_trades_today": 0,
            "polymarket_trades_today": 0,
            "total_trades_today": 0,
            "daily_loss": 0.0,
            "daily_polymarket_pnl": 0.0,
            "daily_stock_pnl": 0.0,
            "total_polymarket_pnl": 0.0,
            "total_stock_pnl": 0.0,
            "peak_portfolio_value": 0.0,
        }

    def _save(self) -> None:
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(json.dumps(self._state, indent=2))
        except Exception:
            logger.exception("Failed to save portfolio risk state")

    def _check_reset(self) -> None:
        today = str(date.today())
        if self._state.get("date") != today:
            self._state = self._default_state()
            self._state["date"] = today

    # ------------------------------------------------------------------
    # Limits (configurable via env or defaults)
    # ------------------------------------------------------------------

    @property
    def max_single_position_pct(self) -> float:
        """Max % of portfolio in a single asset."""
        return float(os.environ.get("RISK_MAX_SINGLE_POSITION_PCT", "20"))

    @property
    def max_open_positions(self) -> int:
        return int(os.environ.get("RISK_MAX_OPEN_POSITIONS", "10"))

    @property
    def max_stock_trades_daily(self) -> int:
        return int(os.environ.get("RISK_MAX_STOCK_TRADES_DAILY", "10"))

    @property
    def max_total_trades_daily(self) -> int:
        """Stock + onchain combined."""
        return int(os.environ.get("RISK_MAX_TOTAL_TRADES_DAILY", "15"))

    @property
    def max_daily_loss_pct(self) -> float:
        return float(os.environ.get("RISK_MAX_DAILY_LOSS_PCT", "3"))

    @property
    def max_sector_exposure_pct(self) -> float:
        return float(os.environ.get("RISK_MAX_SECTOR_EXPOSURE_PCT", "35"))

    @property
    def max_polymarket_trades_daily(self) -> int:
        return int(os.environ.get("RISK_MAX_POLYMARKET_TRADES_DAILY", "5"))

    @property
    def max_polymarket_spend_daily(self) -> float:
        return float(os.environ.get("RISK_MAX_POLYMARKET_SPEND_DAILY", "50.0"))

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_new_position(
        self,
        symbol: str,
        amount: float,
        portfolio_value: float,
        current_positions: list[dict],
        sector: str = "",
    ) -> tuple[bool, str]:
        """Check whether a new position is allowed.

        Parameters
        ----------
        symbol : str
        amount : float
            Proposed position value (price × shares).
        portfolio_value : float
            Current total portfolio value.
        current_positions : list[dict]
            Each dict needs at least {"symbol": str, "value": float, "sector": str}.
        sector : str
            Sector of the proposed position.

        Returns
        -------
        (allowed: bool, reason: str)
        """
        self._check_reset()

        # 1. Max open positions
        existing_symbols = {p["symbol"] for p in current_positions}
        if symbol not in existing_symbols and len(current_positions) >= self.max_open_positions:
            return False, f"已達最大持倉數量限制 ({self.max_open_positions})"

        # 2. Single position concentration (TOTAL = existing + new)
        existing_value = sum(p.get("value", 0) for p in current_positions if p["symbol"] == symbol)
        total_position_value = amount + existing_value
        position_pct = (total_position_value / portfolio_value * 100) if portfolio_value > 0 else 0
        if position_pct > self.max_single_position_pct:
            return False, (
                f"持倉過度集中：新增後 {position_pct:.1f}% > {self.max_single_position_pct}% "
                f"(既有 {existing_value:,.0f} + 新增 {amount:,.0f})"
            )

        # 3. Sector exposure
        if sector:
            sector_total = amount + sum(
                p.get("value", 0) for p in current_positions
                if p.get("sector", "") == sector
            )
            sector_pct = (sector_total / portfolio_value * 100) if portfolio_value > 0 else 0
            if sector_pct > self.max_sector_exposure_pct:
                return False, (
                    f"產業曝險過高：{sector_pct:.1f}% > {self.max_sector_exposure_pct}% "
                    f"(產業：{sector})"
                )

        # 4. Daily trade limit
        if self._state["stock_trades_today"] >= self.max_stock_trades_daily:
            return False, f"今日已達股票交易次數上限 ({self.max_stock_trades_daily})"
        if self._state["total_trades_today"] >= self.max_total_trades_daily:
            return False, f"今日已達總交易次數上限 ({self.max_total_trades_daily})"

        return True, "OK"

    # ------------------------------------------------------------------
    # Trade recording & PnL tracking
    # ------------------------------------------------------------------

    def record_trade(self, is_stock: bool = True, pnl: float = 0.0) -> None:
        """Record a trade for daily limit tracking."""
        self._check_reset()
        self._state["total_trades_today"] += 1
        if is_stock:
            self._state["stock_trades_today"] += 1
            if pnl != 0:
                self._state["daily_stock_pnl"] = self._state.get("daily_stock_pnl", 0.0) + pnl
                self._state["total_stock_pnl"] = self._state.get("total_stock_pnl", 0.0) + pnl
        if pnl < 0:
            self._state["daily_loss"] = self._state.get("daily_loss", 0.0) + abs(pnl)
        self._save()

    # ── Polymarket-specific ─────────────────────

    def validate_polymarket_trade(
        self, amount: float, current_positions: int = 0,
    ) -> tuple[bool, str]:
        """Check whether a Polymarket trade is allowed by risk limits.

        Parameters
        ----------
        amount : float
            Proposed trade value in USDC.
        current_positions : int
            Number of current open Polymarket positions.

        Returns
        -------
        (allowed: bool, reason: str)
        """
        self._check_reset()

        polymarket_trades = self._state.get("polymarket_trades_today", 0)
        if polymarket_trades >= self.max_polymarket_trades_daily:
            return False, (
                f"今日 Polymarket 交易已達上限 ({polymarket_trades}/{self.max_polymarket_trades_daily})"
            )

        total_trades = self._state.get("total_trades_today", 0)
        if total_trades >= self.max_total_trades_daily:
            return False, (
                f"今日總交易次數已達上限 ({total_trades}/{self.max_total_trades_daily})"
            )

        # Track cumulative spend
        daily_pm_spend = self._state.get("daily_polymarket_spend", 0.0)
        if daily_pm_spend + amount > self.max_polymarket_spend_daily:
            return False, (
                f"Polymarket 日花費超限 (${daily_pm_spend + amount:.2f} > ${self.max_polymarket_spend_daily:.2f})"
            )

        return True, "OK"

    def record_polymarket_trade(self, amount: float = 0.0, pnl: float = 0.0) -> None:
        """Record a Polymarket trade for daily limit tracking."""
        self._check_reset()
        self._state["total_trades_today"] = self._state.get("total_trades_today", 0) + 1
        self._state["polymarket_trades_today"] = self._state.get("polymarket_trades_today", 0) + 1
        self._state["daily_polymarket_spend"] = self._state.get("daily_polymarket_spend", 0.0) + amount

        if pnl != 0:
            self._state["daily_polymarket_pnl"] = self._state.get("daily_polymarket_pnl", 0.0) + pnl
            self._state["total_polymarket_pnl"] = self._state.get("total_polymarket_pnl", 0.0) + pnl
            if pnl < 0:
                self._state["daily_loss"] = self._state.get("daily_loss", 0.0) + abs(pnl)
        self._save()

    def check_drawdown(self, portfolio_value: float, peak_value: float = 0.0) -> Optional[str]:
        """Return a warning message if drawdown exceeds limits.

        Automatically tracks peak internally — call update_peak() or pass
        a non-zero peak_value to override.
        """
        # Use tracked peak if caller didn't provide one
        if peak_value <= 0:
            peak_value = self._state.get("peak_portfolio_value", 0.0)

        # Update peak if current value is higher
        if portfolio_value > peak_value:
            self._state["peak_portfolio_value"] = portfolio_value
            self._save()
            return None

        if peak_value <= 0:
            return None  # No baseline yet

        dd_pct = (peak_value - portfolio_value) / peak_value * 100
        if dd_pct > self.max_daily_loss_pct * 3:
            return f"⚠️ 大幅回撤警告：{dd_pct:.1f}%（超過 {self.max_daily_loss_pct * 3:.0f}%）"
        if dd_pct > self.max_daily_loss_pct:
            return f"⚠️ 回撤警告：{dd_pct:.1f}%（超過 {self.max_daily_loss_pct:.0f}%）"
        return None

    def update_peak(self, portfolio_value: float) -> None:
        """Update peak portfolio value if current value is a new high."""
        current_peak = self._state.get("peak_portfolio_value", 0.0)
        if portfolio_value > current_peak:
            self._state["peak_portfolio_value"] = portfolio_value
            self._save()

    def get_drawdown_pct(self, portfolio_value: float) -> float:
        """Return current drawdown percentage from peak (0.0 = at peak)."""
        peak = self._state.get("peak_portfolio_value", 0.0)
        if peak <= 0 or portfolio_value >= peak:
            return 0.0
        return (peak - portfolio_value) / peak * 100

    def should_force_stop(self, portfolio_value: float) -> tuple[bool, str]:
        """Check if drawdown is severe enough to force-stop all trading.

        Returns (should_stop: bool, reason: str).
        """
        dd_pct = self.get_drawdown_pct(portfolio_value)
        # 3x the daily loss limit = circuit breaker
        if dd_pct > self.max_daily_loss_pct * 3:
            return True, f"CIRCUIT BREAKER: drawdown {dd_pct:.1f}% > {self.max_daily_loss_pct * 3:.0f}%"
        # 2x = force-stop new trades
        if dd_pct > self.max_daily_loss_pct * 2:
            return True, f"FORCE STOP: drawdown {dd_pct:.1f}% > {self.max_daily_loss_pct * 2:.0f}%"
        return False, ""

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        self._check_reset()
        return dict(self._state)

    def text_summary(self) -> str:
        self._check_reset()
        pm_trades = self._state.get("polymarket_trades_today", 0)
        stock_trades = self._state.get("stock_trades_today", 0)
        total_trades = self._state.get("total_trades_today", 0)
        daily_loss = self._state.get("daily_loss", 0.0)
        pm_pnl = self._state.get("daily_polymarket_pnl", 0.0)
        stock_pnl = self._state.get("daily_stock_pnl", 0.0)

        return (
            f"📊 風控日誌（{self._state['date']}）\n"
            f"今日股票交易：{stock_trades}/{self.max_stock_trades_daily}\n"
            f"今日 Polymarket：{pm_trades}/{self.max_polymarket_trades_daily}\n"
            f"今日總交易：{total_trades}/{self.max_total_trades_daily}\n"
            f"今日股票 P&L：{stock_pnl:+.2f}\n"
            f"今日 Polymarket P&L：{pm_pnl:+.2f}\n"
            f"今日累計虧損：{daily_loss:.2f}\n"
            f"單一資產上限：{self.max_single_position_pct}%\n"
            f"最大持倉數：{self.max_open_positions}"
        )
