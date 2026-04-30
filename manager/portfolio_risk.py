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
            "total_trades_today": 0,
            "daily_loss": 0.0,
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
        return int(os.environ.get("RISK_MAX_STOCK_TRADES_DAILY", "5"))

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

        # 2. Single position concentration
        position_pct = (amount / portfolio_value * 100) if portfolio_value > 0 else 0
        if position_pct > self.max_single_position_pct:
            return False, (
                f"持倉過度集中：{position_pct:.1f}% > {self.max_single_position_pct}% "
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
        if pnl < 0:
            self._state["daily_loss"] += abs(pnl)
        self._save()

    def check_drawdown(self, portfolio_value: float, peak_value: float) -> Optional[str]:
        """Return a warning message if drawdown exceeds limits."""
        if peak_value <= 0:
            return None
        dd_pct = (peak_value - portfolio_value) / peak_value * 100
        if dd_pct > self.max_daily_loss_pct * 3:
            return f"⚠️ 大幅回撤警告：{dd_pct:.1f}%（超過 {self.max_daily_loss_pct * 3:.0f}%）"
        if dd_pct > self.max_daily_loss_pct:
            return f"⚠️ 回撤警告：{dd_pct:.1f}%（超過 {self.max_daily_loss_pct:.0f}%）"
        return None

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        self._check_reset()
        return dict(self._state)

    def text_summary(self) -> str:
        self._check_reset()
        return (
            f"📊 風控日誌（{self._state['date']}）\n"
            f"今日股票交易：{self._state['stock_trades_today']}/{self.max_stock_trades_daily}\n"
            f"今日總交易：{self._state['total_trades_today']}/{self.max_total_trades_daily}\n"
            f"今日累計虧損：{self._state['daily_loss']:.2f}\n"
            f"單一資產上限：{self.max_single_position_pct}%\n"
            f"最大持倉數：{self.max_open_positions}"
        )
