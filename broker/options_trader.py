"""台指選擇權 (TXO) 模擬交易模組。

策略：
  從 AutoTrader 的個股分析提取整體市場情緒，
  強烈看多 → Buy Call，強烈看空 → Buy Put。

選擇權定價：簡化 Delta 模型（用於模擬）。
  真實帳戶開通後可透過 Shioaji 取得即時 TXO 報價。
"""

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# TXO 合約規格
TXO_POINT_VALUE = 50       # 1 點 = NT$50
MONTHLY_EXPIRY_DAY = 15    # 每月第三週三（簡化：每月 15 號前後）
WEEKLY_EXPIRY_DAY = 3      # 週三到期（週選）

# 定價參數（模擬用）
ATM_IV = 0.18              # 價平隱含波動率 18%
DAYS_TO_EXPIRY = 14        # 預設距離到期天數
OPTION_FEE = 30            # 每口手續費 NT$30


@dataclass
class OptionPosition:
    symbol: str
    option_type: str        # "call" / "put"
    strike: int
    contracts: int
    premium_paid: float     # 總付出權利金
    premium_per_contract: float
    entry_index: float      # 進場時指數點位
    entry_date: str
    expiry: str
    pnl: float = 0.0
    current_value: float = 0.0
    status: str = "open"    # "open" / "closed"


class OptionsTrader:
    """Simulated TXO options trading with 100k dedicated capital.

    In simulation mode, prices are estimated using a Delta-based model.
    In production mode (future), prices come from Shioaji real-time quotes.
    """

    def __init__(self, initial_capital: float = 100_000):
        self.initial_capital = initial_capital
        self._cash = initial_capital
        self._positions: list[OptionPosition] = []
        self._closed_positions: list[OptionPosition] = []
        self._total_pnl = 0.0
        self._state_file = (
            Path.home() / "telegram-claude-bot" / "data" / "options_state.json"
        )
        self._last_index = 0.0
        self._load_state()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def account_value(self) -> float:
        pos_value = sum(p.current_value for p in self._positions if p.status == "open")
        return self._cash + pos_value

    @property
    def open_positions(self) -> list[OptionPosition]:
        return [p for p in self._positions if p.status == "open"]

    # ------------------------------------------------------------------
    # Signal evaluation
    # ------------------------------------------------------------------

    def evaluate_and_trade(self, auto_trader_actions: list[dict],
                           current_index: float) -> list[str]:
        """Evaluate AutoTrader results and decide options trades.

        Simple logic:
          - Count BUY vs SELL signals from the last scan
          - If strongly bullish (BUYs >> SELLs) → buy a Call
          - If strongly bearish (SELLs >> BUYs) → buy a Put
          - Otherwise → no trade (or close existing positions)
        """
        if not auto_trader_actions:
            return []

        self._last_index = current_index
        self._mark_to_market(current_index)
        messages = []

        buys = sum(1 for a in auto_trader_actions if a.get("action") == "BUY")
        sells = sum(1 for a in auto_trader_actions if a.get("action") == "SELL")
        total = buys + sells
        if total == 0:
            return []

        # Calculate net sentiment: +1 (all buy) to -1 (all sell)
        net_sentiment = (buys - sells) / total

        # Check if we already have a position in this direction
        has_call = any(p.option_type == "call" and p.status == "open" for p in self._positions)
        has_put = any(p.option_type == "put" and p.status == "open" for p in self._positions)

        # Strongly bullish: net > 0.5 (e.g. 8 buys, 2 sells)
        if net_sentiment >= 0.5 and not has_call:
            # Close any put position
            self._close_all("put")
            # Open a Call
            strike = self._choose_strike(current_index, "call")
            if self._cash >= 5000:  # Min premium needed
                contracts = min(2, max(1, int(self._cash * 0.3 / 5000)))
                msg = self._buy_call(strike, contracts, current_index)
                messages.append(msg)

        # Strongly bearish: net < -0.5
        elif net_sentiment <= -0.5 and not has_put:
            self._close_all("call")
            strike = self._choose_strike(current_index, "put")
            if self._cash >= 5000:
                contracts = min(2, max(1, int(self._cash * 0.3 / 5000)))
                msg = self._buy_put(strike, contracts, current_index)
                messages.append(msg)

        # Neutral or weak signal: close positions that are losing
        elif -0.3 < net_sentiment < 0.3:
            for pos in self.open_positions:
                if pos.pnl < -pos.premium_paid * 0.5:  # Lost >50% → cut loss
                    msg = self._close_position(pos, current_index)
                    messages.append(msg)

        return messages

    # ------------------------------------------------------------------
    # Trade execution (simulated)
    # ------------------------------------------------------------------

    def _buy_call(self, strike: int, contracts: int,
                  current_index: float) -> str:
        """Simulate buying a Call option."""
        premium = self._estimate_premium(current_index, strike, "call")
        total_cost = premium * contracts + OPTION_FEE * contracts

        if total_cost > self._cash:
            return f"⚠️ 期權資金不足: 需 NT${total_cost:,.0f}, 可用 NT${self._cash:,.0f}"

        expiry = self._next_expiry()
        position = OptionPosition(
            symbol=f"TXO {expiry} Call {strike}",
            option_type="call",
            strike=strike,
            contracts=contracts,
            premium_paid=total_cost,
            premium_per_contract=premium,
            entry_index=current_index,
            entry_date=str(date.today()),
            expiry=expiry,
            current_value=total_cost,
        )
        self._cash -= total_cost
        self._positions.append(position)
        self._save_state()

        logger.info(f"📈 Buy TXO Call {strike} x{contracts} @ NT${premium:,.0f} = NT${total_cost:,.0f}")
        return f"📈 買 Call {strike} x{contracts} 權利金 NT${total_cost:,.0f}"

    def _buy_put(self, strike: int, contracts: int,
                 current_index: float) -> str:
        """Simulate buying a Put option."""
        premium = self._estimate_premium(current_index, strike, "put")
        total_cost = premium * contracts + OPTION_FEE * contracts

        if total_cost > self._cash:
            return f"⚠️ 期權資金不足: 需 NT${total_cost:,.0f}, 可用 NT${self._cash:,.0f}"

        expiry = self._next_expiry()
        position = OptionPosition(
            symbol=f"TXO {expiry} Put {strike}",
            option_type="put",
            strike=strike,
            contracts=contracts,
            premium_paid=total_cost,
            premium_per_contract=premium,
            entry_index=current_index,
            entry_date=str(date.today()),
            expiry=expiry,
            current_value=total_cost,
        )
        self._cash -= total_cost
        self._positions.append(position)
        self._save_state()

        logger.info(f"📉 Buy TXO Put {strike} x{contracts} @ NT${premium:,.0f} = NT${total_cost:,.0f}")
        return f"📉 買 Put {strike} x{contracts} 權利金 NT${total_cost:,.0f}"

    def close_all_positions(self, current_index: float) -> list[str]:
        """Close all open positions (e.g. at end of day / expiry)."""
        messages = []
        for pos in list(self.open_positions):
            msg = self._close_position(pos, current_index)
            messages.append(msg)
        return messages

    def _close_position(self, position: OptionPosition,
                        current_index: float) -> str:
        """Close an option position and realize P&L."""
        self._mark_to_market(current_index)
        pnl = position.current_value - position.premium_paid
        self._cash += position.current_value - OPTION_FEE * position.contracts
        position.pnl = pnl
        position.status = "closed"
        self._total_pnl += pnl
        self._closed_positions.append(position)

        direction = "Call" if position.option_type == "call" else "Put"
        pnl_str = f"+NT${pnl:,.0f}" if pnl >= 0 else f"-NT${abs(pnl):,.0f}"
        logger.info(f"🔚 Close {direction} {position.strike}: {pnl_str}")
        self._save_state()
        return f"🔚 平倉 {direction} {position.strike}: {pnl_str}"

    def _close_all(self, option_type: str) -> None:
        """Close all positions of a given type."""
        for pos in list(self.open_positions):
            if pos.option_type == option_type:
                self._close_position(pos, self._last_index or pos.entry_index)

    # ------------------------------------------------------------------
    # Pricing (simplified Delta model for simulation)
    # ------------------------------------------------------------------

    def _estimate_premium(self, current_index: float, strike: int,
                          option_type: str) -> float:
        """Estimate option premium using a simplified model.

        Uses: intrinsic value + time value (proportional to ATM IV).
        This is a rough approximation — real prices come from the market.
        """
        days = DAYS_TO_EXPIRY
        time_value = current_index * ATM_IV * math.sqrt(days / 365)
        moneyness = (current_index - strike) / current_index

        if option_type == "call":
            intrinsic = max(current_index - strike, 0)
            # OTM discount: further OTM = cheaper
            otm_factor = max(0.1, math.exp(-abs(moneyness) * 10))
            premium = intrinsic + time_value * otm_factor
        else:
            intrinsic = max(strike - current_index, 0)
            otm_factor = max(0.1, math.exp(-abs(moneyness) * 10))
            premium = intrinsic + time_value * otm_factor

        # Round to nearest 50 (TXO ticks in 0.5 points = NT$25)
        premium = round(premium / 50) * 50
        return max(premium, 50)  # Min NT$50

    def _mark_to_market(self, current_index: float) -> None:
        """Revalue all open positions based on current index level."""
        for pos in self.open_positions:
            if pos.option_type == "call":
                intrinsic = max(current_index - pos.strike, 0)
            else:
                intrinsic = max(pos.strike - current_index, 0)
            # Remaining time value decays
            elapsed_days = (date.today() - date.fromisoformat(pos.entry_date)).days
            remaining_days = max(1, DAYS_TO_EXPIRY - elapsed_days)
            time_value = (pos.entry_index * ATM_IV
                          * math.sqrt(remaining_days / 365))

            pos.current_value = (intrinsic + time_value) * pos.contracts
            pos.pnl = pos.current_value - pos.premium_paid

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _choose_strike(self, index: float, option_type: str) -> int:
        """Choose a strike price: 1-2 strikes OTM for leverage."""
        base = int(index / 100) * 100  # Round to nearest 100
        if option_type == "call":
            return base + 200  # 200 points OTM (higher leverage)
        else:
            return base - 200  # 200 points OTM

    def _next_expiry(self) -> str:
        """Estimate next monthly expiry (3rd Wed, simplified)."""
        today = date.today()
        d = today
        for _ in range(35):
            if d.weekday() == 2 and 15 <= d.day <= 21:
                return d.isoformat()
            d += timedelta(days=1)
        # Fallback: ~2 weeks from now
        return (today + timedelta(days=14)).isoformat()

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def summary(self) -> str:
        self._mark_to_market(self._last_index or 0)
        lines = [
            "📊 期權模擬帳戶",
            f"現金: NT${self._cash:,.0f}",
            f"未平倉價值: NT${sum(p.current_value for p in self.open_positions):,.0f}",
            f"總權益: NT${self.account_value:,.0f}",
            f"總損益: {self._total_pnl:+,.0f}",
            "",
        ]
        if self.open_positions:
            lines.append("未平倉:")
            for p in self.open_positions:
                pnl_s = f"{p.pnl:+,.0f}" if p.pnl != 0 else "0"
                lines.append(
                    f"  {p.symbol:30s} x{p.contracts} 成本NT${p.premium_paid:>,.0f} "
                    f"現值NT${p.current_value:>,.0f} ({pnl_s})"
                )
        if self._closed_positions:
            lines.append(f"\n已平倉: {len(self._closed_positions)} 筆")
            for p in self._closed_positions[-3:]:
                pnl_s = f"+{p.pnl:,.0f}" if p.pnl >= 0 else f"{p.pnl:,.0f}"
                lines.append(f"  {p.symbol:30s} {pnl_s}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        if self._state_file.exists():
            try:
                data = json.loads(self._state_file.read_text())
                self._cash = data.get("cash", self.initial_capital)
                self._total_pnl = data.get("total_pnl", 0.0)
                self._last_index = data.get("last_index", 0.0)
                for p_data in data.get("positions", []):
                    self._positions.append(OptionPosition(**p_data))
                for p_data in data.get("closed_positions", []):
                    self._closed_positions.append(OptionPosition(**p_data))
            except Exception:
                logger.exception("Failed to load options state")

    def _save_state(self) -> None:
        try:
            data = {
                "cash": self._cash,
                "total_pnl": self._total_pnl,
                "last_index": self._last_index,
                "positions": [
                    {"symbol": p.symbol, "option_type": p.option_type,
                     "strike": p.strike, "contracts": p.contracts,
                     "premium_paid": p.premium_paid,
                     "premium_per_contract": p.premium_per_contract,
                     "entry_index": p.entry_index, "entry_date": p.entry_date,
                     "expiry": p.expiry, "pnl": p.pnl,
                     "current_value": p.current_value, "status": p.status}
                    for p in self._positions
                ],
                "closed_positions": [
                    {"symbol": p.symbol, "option_type": p.option_type,
                     "strike": p.strike, "contracts": p.contracts,
                     "premium_paid": p.premium_paid,
                     "premium_per_contract": p.premium_per_contract,
                     "entry_index": p.entry_index, "entry_date": p.entry_date,
                     "expiry": p.expiry, "pnl": p.pnl,
                     "current_value": p.current_value, "status": p.status}
                    for p in self._closed_positions
                ],
            }
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception:
            logger.exception("Failed to save options state")
