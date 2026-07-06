"""永豐金證券 (SinoPac) broker bridge via Shioaji API.

Two modes:
  simulation=True — local mock that follows 永豐金 trading rules
  simulation=False — real Shioaji API (requires account + API key)

When Shioaji credentials are not set, falls back to local simulation
with realistic fees, settlement rules, and position limits.
"""

import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 永豐金交易規則 constants
# ---------------------------------------------------------------------------

STOCK_FEE_RATE = Decimal("0.001425")       # 手續費 0.1425%
STOCK_TAX_RATE = Decimal("0.003")          # 證交稅 0.3% (賣出)
STOCK_DAYTRADE_TAX_RATE = Decimal("0.0015")  # 當沖證交稅 0.15%
STOCK_LOT_SIZE = 1000                      # 1 張 = 1000 股
SETTLEMENT_T_DAYS = 2                      # T+2 交割

# 美股複委託規則
US_FEE_RATE = Decimal("0.005")             # 手續費 0.5% (最低 USD $15)
US_MIN_FEE = Decimal("15")                 # 最低手續費 USD $15
US_FEE_RATE_PCT = Decimal("0.005")         # 0.5%
USD_TWD_RATE = Decimal("33")               # 簡化匯率 1 USD = 33 TWD

# 選擇權
OPTION_POINT_VALUE = 50                    # 1 點 = NT$50
OPTION_FEE = Decimal("30")                 # 每口手續費 ~NT$30

# 交易時段
MARKET_OPEN = (9, 0)
MARKET_CLOSE = (13, 30)
OPTION_OPEN = (8, 45)
OPTION_CLOSE = (13, 45)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class OrderRequest:
    symbol: str
    action: str          # "buy" / "sell"
    shares: int
    price: float
    order_type: str = "limit"   # "limit" / "market"
    order_id: str = ""

    @property
    def value(self) -> float:
        return self.shares * self.price


@dataclass
class OrderResult:
    success: bool
    order_id: str
    symbol: str
    action: str
    shares: int
    price: float
    fee: float = 0.0
    tax: float = 0.0
    message: str = ""


@dataclass
class BrokerPosition:
    symbol: str
    shares: int
    avg_price: float
    unrealized_pnl: float = 0.0
    market_price: float = 0.0


@dataclass
class TransactionRecord:
    date: str
    symbol: str
    action: str
    shares: int
    price: float
    fee: float
    tax: float
    total: float
    order_id: str


@dataclass
class PendingOrder:
    order_id: str
    symbol: str
    action: str          # "buy" / "sell"
    shares: int
    limit_price: float
    created_at: datetime
    filled: bool = False
    fill_price: float = 0.0
    result: Optional[OrderResult] = None


@dataclass
class SettlementRecord:
    """Tracks T+2 settlement for Taiwan stocks."""
    trade_date: str
    settle_date: str      # trade_date + 2 business days
    symbol: str
    amount: float          # positive = cash received, negative = cash paid


# ---------------------------------------------------------------------------
# SinoBridge
# ---------------------------------------------------------------------------

class SinoBridge:
    """Bridge to 永豐金證券 via Shioaji API.

    Args:
        simulation: If True, use local mock with realistic rules.
                    If False, connect to real Shioaji API.
    """

    def __init__(self, simulation: bool = True):
        self.simulation = simulation
        self._connected = False
        self._api: Any = None
        self._positions: dict[str, BrokerPosition] = {}
        self._orders: list[OrderResult] = []
        self._transactions: list[TransactionRecord] = []
        self._pending_orders: list[PendingOrder] = []
        self._settlements: list[SettlementRecord] = []
        self._initial_capital = float(os.environ.get("SIM_INITIAL_CAPITAL", "400000"))
        self._cash = self._initial_capital
        self._usd_initial = float(os.environ.get("SIM_USD_INITIAL", "5000"))
        self._usd_cash = self._usd_initial
        self._fee_discount = Decimal(os.environ.get("SHIOAJI_FEE_DISCOUNT", "0.6"))

        self._state_file = (
            Path.home() / "telegram-claude-bot" / "data" / "sino_bridge_state.json"
        )
        self._load_state()

        # Try real Shioaji if credentials are set
        if not simulation:
            self._try_shioaji_connect()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def usd_cash(self) -> float:
        return self._usd_cash

    @property
    def portfolio_value(self) -> float:
        tw_value = sum(
            p.shares * p.avg_price for p in self._positions.values()
            if not self._is_us_stock(p.symbol)
        )
        us_value = sum(
            p.shares * p.avg_price for p in self._positions.values()
            if self._is_us_stock(p.symbol)
        )
        return self._cash + tw_value + us_value * float(USD_TWD_RATE) + self._usd_cash * float(USD_TWD_RATE)

    @property
    def buying_power(self) -> float:
        """Cash minus unsettled T+2 payments for Taiwan stocks."""
        settled = self._cash
        today = date.today()
        for s in self._settlements:
            settle = date.fromisoformat(s.settle_date)
            if settle > today and s.amount < 0:
                # Payment not yet settled — subtract from available cash
                settled += s.amount  # amount is negative, so this reduces cash
        return max(settled, 0)

    def _add_settlement(self, symbol: str, amount: float) -> None:
        """Create a T+2 settlement record for Taiwan stock trades."""
        if self._is_us_stock(symbol):
            return  # US stocks settle T+1
        trade_date = date.today()
        # Add 2 business days for T+2
        d = trade_date
        business_days = 0
        while business_days < 2:
            d += timedelta(days=1)
            if d.weekday() < 5:  # Skip weekends
                business_days += 1
        self._settlements.append(SettlementRecord(
            trade_date=str(trade_date),
            settle_date=str(d),
            symbol=symbol,
            amount=round(amount, 2),
        ))

    @staticmethod
    def _apply_slippage(price: float, is_buy: bool = True) -> float:
        """Apply random ±0.5% slippage to simulate real fill prices."""
        slip = random.uniform(-0.005, 0.005)
        return round(price * (1 + slip), 2)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _try_shioaji_connect(self) -> bool:
        """Try connecting to Shioaji API (requires API keys).

        Controls:
          SHIOAJI_API_KEY / SHIOAJI_SECRET_KEY — required for any real/sandbox mode
          SHIOAJI_SIMULATION=true — connect to Shioaji sandbox (default: false = production)
          SHIOAJI_CA_PATH / SHIOAJI_CA_PASSWORD / SHIOAJI_PERSON_ID — required for production
        """
        api_key = os.environ.get("SHIOAJI_API_KEY", "")
        secret_key = os.environ.get("SHIOAJI_SECRET_KEY", "")
        if not api_key or not secret_key:
            logger.warning(
                "SHIOAJI_API_KEY not set — falling back to simulation mode"
            )
            self.simulation = True
            return False
        try:
            import shioaji as sj

            shioaji_sim = os.environ.get("SHIOAJI_SIMULATION", "false").lower() == "true"
            self._api = sj.Shioaji(simulation=shioaji_sim)
            self._api.login(api_key=api_key, secret_key=secret_key)

            ca_path = os.environ.get("SHIOAJI_CA_PATH", "")
            ca_password = os.environ.get("SHIOAJI_CA_PASSWORD", "")
            if ca_path and ca_password:
                self._api.activate_ca(
                    ca_path=ca_path,
                    ca_passwd=ca_password,
                    person_id=os.environ.get("SHIOAJI_PERSON_ID", ""),
                )
            self._connected = True
            self.simulation = False
            logger.info("✅ Shioaji real API connected")
            return True
        except Exception as e:
            logger.error(f"Shioaji connection failed: {e}")
            self.simulation = True
            return False

    # ------------------------------------------------------------------
    # Order execution
    # ------------------------------------------------------------------

    def buy(
        self, symbol: str, shares: int, price: float, note: str = ""
    ) -> OrderResult:
        """Place a buy order.

        In simulation mode, validates against 永豐金 rules and executes locally.
        In real mode, sends order via Shioaji API.
        """
        fee = self._calc_fee(shares * price, symbol)
        total_cost = (shares * price) + fee

        if self._is_us_stock(symbol):
            total_cost_usd = total_cost  # price is already in USD
            if total_cost_usd > self._usd_cash:
                return OrderResult(
                    success=False, order_id="", symbol=symbol,
                    action="buy", shares=shares, price=price,
                    message=f"USD 不足: 需 ${total_cost_usd:,.0f}, 可用 ${self._usd_cash:,.0f}",
                )
        elif total_cost > self._cash:
            return OrderResult(
                success=False, order_id="", symbol=symbol,
                action="buy", shares=shares, price=price,
                message=f"現金不足: 需 NT${total_cost:,.0f}, 可用 NT${self._cash:,.0f}",
            )

        if self.simulation:
            return self._sim_buy(symbol, shares, price, fee)
        else:
            return self._real_place_order(symbol, "buy", shares, price)

    def sell(
        self, symbol: str, shares: int, price: float
    ) -> OrderResult:
        """Place a sell order."""
        position = self._positions.get(symbol)
        if not position or position.shares < shares:
            return OrderResult(
                success=False, order_id="", symbol=symbol,
                action="sell", shares=shares, price=price,
                message=f"庫存不足: 持有 {position.shares if position else 0} 股, 欲賣 {shares}",
            )

        if self.simulation:
            return self._sim_sell(symbol, shares, price)
        else:
            return self._real_place_order(symbol, "sell", shares, price)

    def _sim_buy(self, symbol: str, shares: int, price: float,
                 fee: float) -> OrderResult:
        """Simulated buy with slippage, pending-order tracking, and T+2 settlement."""
        order_id = f"SIM-{int(time.time() * 1000)}"
        fill_price = self._apply_slippage(price, is_buy=True)
        total = (shares * fill_price) + fee

        # Deduct cash immediately (settlement tracks T+2 separately)
        if self._is_us_stock(symbol):
            self._usd_cash -= total
        else:
            self._cash -= total

        # Update position
        if symbol in self._positions:
            pos = self._positions[symbol]
            total_cost = (pos.shares * pos.avg_price) + (shares * fill_price)
            pos.shares += shares
            pos.avg_price = total_cost / pos.shares
        else:
            self._positions[symbol] = BrokerPosition(
                symbol=symbol, shares=shares, avg_price=fill_price,
            )

        # T+2 settlement tracking
        self._add_settlement(symbol, -total)

        # Pending order record
        self._pending_orders.append(PendingOrder(
            order_id=order_id, symbol=symbol, action="buy",
            shares=shares, limit_price=price,
            created_at=datetime.now(),
            filled=True, fill_price=fill_price,
        ))

        result = OrderResult(
            success=True, order_id=order_id, symbol=symbol,
            action="buy", shares=shares, price=fill_price, fee=fee, tax=0.0,
            message=f"模擬買入 {symbol} x{shares} @ {fill_price} (限價 {price}, 滑價 {fill_price-price:+.2f})",
        )

        self._orders.append(result)
        self._record_transaction(symbol, "buy", shares, fill_price, fee, 0.0, total, order_id)
        self._save_state()
        return result

    def _sim_sell(self, symbol: str, shares: int, price: float) -> OrderResult:
        """Simulated sell with slippage, pending-order tracking, and T+2 settlement."""
        position = self._positions[symbol]
        order_id = f"SIM-{int(time.time() * 1000)}"
        fill_price = self._apply_slippage(price, is_buy=False)
        fee = self._calc_fee(shares * fill_price, symbol)
        tax = self._calc_tax(shares * fill_price, symbol)
        total = (shares * fill_price) - fee - tax

        if self._is_us_stock(symbol):
            self._usd_cash += total
        else:
            self._cash += total

        # Update position
        if shares >= position.shares:
            del self._positions[symbol]
        else:
            position.shares -= shares

        # T+2 settlement tracking
        self._add_settlement(symbol, total)

        # Pending order record
        self._pending_orders.append(PendingOrder(
            order_id=order_id, symbol=symbol, action="sell",
            shares=shares, limit_price=price,
            created_at=datetime.now(),
            filled=True, fill_price=fill_price,
        ))

        result = OrderResult(
            success=True, order_id=order_id, symbol=symbol,
            action="sell", shares=shares, price=fill_price, fee=fee, tax=tax,
            message=f"模擬賣出 {symbol} x{shares} @ {fill_price} (限價 {price}, 滑價 {fill_price-price:+.2f})",
        )

        self._orders.append(result)
        self._record_transaction(symbol, "sell", shares, fill_price, fee, tax, total, order_id)
        self._save_state()
        return result

    def _real_place_order(self, symbol: str, action: str, shares: int,
                          price: float) -> OrderResult:
        """Place order via real Shioaji API."""
        if not self._connected:
            return OrderResult(
                success=False, order_id="", symbol=symbol,
                action=action, shares=shares, price=price,
                message="Shioaji 未連線",
            )
        try:
            import shioaji as sj

            # Resolve stock contract
            contract = self._api.Contracts.Stocks[symbol]
            if not contract:
                return OrderResult(
                    success=False, order_id="", symbol=symbol,
                    action=action, shares=shares, price=price,
                    message=f"找不到 {symbol} 的合約",
                )

            order = sj.Order(
                price=price,
                quantity=shares // STOCK_LOT_SIZE,
                action=sj.Action.Buy if action == "buy" else sj.Action.Sell,
                price_type=sj.StockPriceType.Limit,
                order_type=sj.OrderType.ROD,
                order_lot=sj.StockOrderLot.Common,
            )
            trade = self._api.place_order(contract, order)
            order_id = str(trade)

            result = OrderResult(
                success=True, order_id=order_id, symbol=symbol,
                action=action, shares=shares, price=price,
                message=f"Shioaji 下單成功 [{action} {symbol} x{shares} @ {price}]",
            )
            self._orders.append(result)
            return result

        except Exception as e:
            logger.exception(f"Shioaji order failed")
            return OrderResult(
                success=False, order_id="", symbol=symbol,
                action=action, shares=shares, price=price,
                message=f"下單失敗: {e}",
            )

    def process_pending_orders(self) -> list[OrderResult]:
        """Fill pending orders older than 30 seconds with slippage.

        Call this periodically (e.g., every 30s via scheduler) to simulate
        realistic order execution delay.
        """
        filled: list[OrderResult] = []
        now = datetime.now()
        cutoff = timedelta(seconds=30)

        for po in self._pending_orders:
            if po.filled:
                continue
            if now - po.created_at < cutoff:
                continue

            fill_price = self._apply_slippage(po.limit_price, po.action == "buy")

            if po.action == "buy":
                fee = self._calc_fee(po.shares * fill_price, po.symbol)
                total = (po.shares * fill_price) + fee
                if self._is_us_stock(po.symbol):
                    self._usd_cash -= total
                else:
                    self._cash -= total

                if po.symbol in self._positions:
                    pos = self._positions[po.symbol]
                    total_cost = (pos.shares * pos.avg_price) + (po.shares * fill_price)
                    pos.shares += po.shares
                    pos.avg_price = total_cost / pos.shares
                else:
                    self._positions[po.symbol] = BrokerPosition(
                        symbol=po.symbol, shares=po.shares, avg_price=fill_price,
                    )

                self._add_settlement(po.symbol, -total)
                result = OrderResult(
                    success=True, order_id=po.order_id, symbol=po.symbol,
                    action="buy", shares=po.shares, price=fill_price, fee=fee, tax=0.0,
                    message=f"已成交 {po.symbol} 買入 x{po.shares} @ {fill_price} (限價 {po.limit_price})",
                )
            else:
                fee = self._calc_fee(po.shares * fill_price, po.symbol)
                tax = self._calc_tax(po.shares * fill_price, po.symbol)
                total = (po.shares * fill_price) - fee - tax

                if self._is_us_stock(po.symbol):
                    self._usd_cash += total
                else:
                    self._cash += total

                position = self._positions.get(po.symbol)
                if position:
                    if po.shares >= position.shares:
                        del self._positions[po.symbol]
                    else:
                        position.shares -= po.shares

                self._add_settlement(po.symbol, total)
                result = OrderResult(
                    success=True, order_id=po.order_id, symbol=po.symbol,
                    action="sell", shares=po.shares, price=fill_price, fee=fee, tax=tax,
                    message=f"已成交 {po.symbol} 賣出 x{po.shares} @ {fill_price} (限價 {po.limit_price})",
                )

            po.filled = True
            po.fill_price = fill_price
            po.result = result
            self._orders.append(result)
            self._record_transaction(
                po.symbol, po.action, po.shares, fill_price,
                result.fee, result.tax, total, po.order_id,
            )
            filled.append(result)
            logger.info(f"Pending order filled: {result.message}")

        if filled:
            self._save_state()

        return filled

    # ------------------------------------------------------------------
    # Fee & tax calculations
    # ------------------------------------------------------------------

    @staticmethod
    def _is_us_stock(symbol: str) -> bool:
        """Detect if symbol is a US stock (non-numeric, no .TW/.TWO suffix)."""
        clean = symbol.strip().upper()
        if clean.endswith(".TW") or clean.endswith(".TWO"):
            return False
        # All Taiwan stocks are numeric codes; anything else is US
        raw = clean.replace(".TW", "").replace(".TWO", "")
        return not raw.isdigit()

    def _calc_fee(self, value: float, symbol: str = "") -> float:
        """Calculate commission based on market."""
        if self._is_us_stock(symbol):
            # 複委託美股: 0.5%, 最低 USD $15 (convert to TWD)
            d = Decimal(str(value))
            fee = d * US_FEE_RATE_PCT
            min_fee_twd = US_MIN_FEE * USD_TWD_RATE
            return float(max(fee, min_fee_twd).quantize(Decimal("0.01")))

        # 台股: 0.1425% × 折扣
        d = Decimal(str(value))
        fee = d * STOCK_FEE_RATE * self._fee_discount
        return float(fee.quantize(Decimal("0.01")))

    def _calc_tax(self, value: float, symbol: str = "") -> float:
        """證交稅 = 成交金額 × 0.3%（賣出），美股無證交稅"""
        if self._is_us_stock(symbol):
            return 0.0
        d = Decimal(str(value))
        tax = d * STOCK_TAX_RATE
        return float(tax.quantize(Decimal("0.01")))

    # ------------------------------------------------------------------
    # Position & account queries
    # ------------------------------------------------------------------

    def get_positions(self) -> list[BrokerPosition]:
        return list(self._positions.values())

    def get_position(self, symbol: str) -> Optional[BrokerPosition]:
        return self._positions.get(symbol)

    def get_balance(self) -> dict[str, float]:
        tw_holdings = sum(
            p.shares * p.avg_price for p in self._positions.values()
            if not self._is_us_stock(p.symbol)
        )
        us_holdings = sum(
            p.shares * p.avg_price for p in self._positions.values()
            if self._is_us_stock(p.symbol)
        )
        total_twd = self._cash + tw_holdings + us_holdings * float(USD_TWD_RATE)
        return {
            "cash": self._cash,
            "usd_cash": self._usd_cash,
            "holdings_value": total_twd - self._cash,
            "total": total_twd,
            "buying_power": self.buying_power,
        }

    def list_transactions(self, limit: int = 20) -> list[TransactionRecord]:
        return self._transactions[-limit:]

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        if self._state_file.exists():
            try:
                data = json.loads(self._state_file.read_text())
                self._cash = data.get("cash", self._initial_capital)
                self._usd_cash = data.get("usd_cash", self._usd_initial)
                self._positions = {
                    k: BrokerPosition(**v) for k, v in data.get("positions", {}).items()
                }
                self._transactions = [TransactionRecord(**t) for t in data.get("transactions", [])]
                self._settlements = [SettlementRecord(**s) for s in data.get("settlements", [])]
                self._pending_orders = [
                    PendingOrder(
                        order_id=po["order_id"], symbol=po["symbol"],
                        action=po["action"], shares=po["shares"],
                        limit_price=po["limit_price"],
                        created_at=datetime.fromisoformat(po["created_at"]),
                        filled=po.get("filled", True),
                        fill_price=po.get("fill_price", po["limit_price"]),
                    )
                    for po in data.get("pending_orders", [])
                ]
            except Exception:
                logger.exception("Failed to load SinoBridge state")
                self._reset_state()
        else:
            self._reset_state()

    def _reset_state(self) -> None:
        self._cash = self._initial_capital
        self._usd_cash = self._usd_initial
        self._positions = {}
        self._transactions = []
        self._pending_orders = []
        self._settlements = []

    def _save_state(self) -> None:
        try:
            data = {
                "cash": self._cash,
                "usd_cash": self._usd_cash,
                "positions": {
                    k: {"symbol": v.symbol, "shares": v.shares,
                        "avg_price": v.avg_price, "unrealized_pnl": v.unrealized_pnl,
                        "market_price": v.market_price}
                    for k, v in self._positions.items()
                },
                "transactions": [
                    {"date": t.date, "symbol": t.symbol, "action": t.action,
                     "shares": t.shares, "price": t.price, "fee": t.fee,
                     "tax": t.tax, "total": t.total, "order_id": t.order_id}
                    for t in self._transactions
                ],
                "settlements": [
                    {"trade_date": s.trade_date, "settle_date": s.settle_date,
                     "symbol": s.symbol, "amount": s.amount}
                    for s in self._settlements
                ],
                "pending_orders": [
                    {"order_id": po.order_id, "symbol": po.symbol,
                     "action": po.action, "shares": po.shares,
                     "limit_price": po.limit_price,
                     "created_at": po.created_at.isoformat(),
                     "filled": po.filled, "fill_price": po.fill_price}
                    for po in self._pending_orders
                ],
            }
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception:
            logger.exception("Failed to save SinoBridge state")

    def _record_transaction(self, symbol: str, action: str, shares: int,
                            price: float, fee: float, tax: float,
                            total: float, order_id: str) -> None:
        self._transactions.append(TransactionRecord(
            date=str(date.today()),
            symbol=symbol, action=action, shares=shares, price=price,
            fee=fee, tax=tax, total=total, order_id=order_id,
        ))

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> str:
        bal = self.get_balance()
        us_holdings = sum(
            p.shares * p.avg_price for p in self._positions.values()
            if self._is_us_stock(p.symbol)
        )
        tw_holdings = sum(
            p.shares * p.avg_price for p in self._positions.values()
            if not self._is_us_stock(p.symbol)
        )
        lines = [
            "🏦 永豐金證券模擬帳戶",
            f"台幣現金: NT${self._cash:,.2f}",
            f"美元現金: ${self._usd_cash:,.2f}",
            f"台股價值: NT${tw_holdings:,.2f}",
            f"美股價值: ${us_holdings:,.2f}",
            f"總資產(TWD): NT${bal['total']:,.2f}",
            "",
        ]
        if self._positions:
            lines.append("持倉:")
            for p in self._positions.values():
                lines.append(
                    f"  {p.symbol:10s} x{p.shares:>4} @ {p.avg_price:>8.1f} = "
                    f"NT${p.shares * p.avg_price:>10,.0f}"
                )
        return "\n".join(lines)
