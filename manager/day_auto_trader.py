"""
DayAutoTrader — Automatic day trading engine.

Reads AI Committee signals and executes day trades via DayTraderSim,
with stop-loss, take-profit, probe positions, and force-close at market end.
Follows the same patterns as AutoTrader and CommitteeTrader.

Strategies integrated:
  - 巨人傑: 試單找方向, 小賠大賺 (風報比 1:3), 動態加碼
  - 相良文昭: 時間紀律, 強制平倉
  - Committee: 技術指標 (RSI/MACD) 動態調整 SL/TP
"""

import json
import logging
import os
from datetime import date, datetime, time as dtime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from manager.day_trader_sim import DayTraderSim
from manager.market_schedule import Market, is_market_open
from manager.portfolio_risk import PortfolioRiskManager

logger = logging.getLogger(__name__)

STATE_DIR = Path.home() / "telegram-claude-bot" / "data"
STATE_FILE = STATE_DIR / "day_auto_trader_state.json"
REVIEW_DIR = STATE_DIR / "reviews"
COMMITTEE_JSON = Path.home() / "telegram-claude-bot" / "data" / "committee" / "daily_signals.json"
USD_TWD_RATE = 33.0

# ── Fee Model: 永豐金證券 美股複委託 ──────────────────────────────────
# Commission: 0.5% of trade value, minimum USD $15 per side
# Transaction tax: 0% (US stocks have no transaction tax)
# Source: broker/sino_bridge.py lines 35-38, 557-562
FEE_RATE = 0.005      # 0.5% commission
FEE_MIN_USD = 15.0    # minimum USD $15 per trade
FEE_MIN_TWD = FEE_MIN_USD * USD_TWD_RATE  # NT$495


class DayAutoTraderConfig:
    """Env-var-backed configuration."""

    @property
    def enabled(self) -> bool:
        return os.environ.get("DAY_AUTO_TRADER_ENABLED", "true").lower() == "true"

    @property
    def interval_minutes(self) -> int:
        return int(os.environ.get("DAY_AUTO_TRADER_INTERVAL_MINUTES", "5"))

    @property
    def position_pct(self) -> float:
        """Full position size as % of cash (default 25%)."""
        return float(os.environ.get("DAY_AUTO_TRADER_POSITION_PCT", "25"))

    @property
    def probe_pct(self) -> float:
        """Initial probe position as % of cash (default 20%, min $600 USD to beat fees)."""
        return float(os.environ.get("DAY_AUTO_TRADER_PROBE_PCT", "20"))

    @property
    def probe_confirm_pct(self) -> float:
        """Price gain % needed to confirm probe and add full position (default 1%)."""
        return float(os.environ.get("DAY_AUTO_TRADER_PROBE_CONFIRM_PCT", "1"))

    @property
    def max_positions(self) -> int:
        return int(os.environ.get("DAY_AUTO_TRADER_MAX_POSITIONS", "3"))

    @property
    def min_confidence(self) -> float:
        return float(os.environ.get("DAY_AUTO_TRADER_MIN_CONFIDENCE", "0.6"))

    @property
    def stop_loss_pct(self) -> float:
        """Base stop-loss % (default 2%). 巨人傑: 小賠大賺, SL < TP."""
        return float(os.environ.get("DAY_AUTO_TRADER_STOP_LOSS_PCT", "2"))

    @property
    def take_profit_pct(self) -> float:
        """Base take-profit % (default 6%). 風報比 1:3."""
        return float(os.environ.get("DAY_AUTO_TRADER_TAKE_PROFIT_PCT", "6"))

    @property
    def force_close_hour(self) -> int:
        return int(os.environ.get("DAY_AUTO_TRADER_FORCE_CLOSE_HOUR", "15"))

    @property
    def force_close_minute(self) -> int:
        return int(os.environ.get("DAY_AUTO_TRADER_FORCE_CLOSE_MINUTE", "30"))

    @property
    def max_trades_per_day(self) -> int:
        return int(os.environ.get("DAY_AUTO_TRADER_MAX_TRADES_PER_DAY", "20"))

    @property
    def open_premarket(self) -> bool:
        """Allow trading during pre-market (default false)."""
        return os.environ.get("DAY_AUTO_TRADER_OPEN_PREMARKET", "false").lower() == "true"

    @property
    def strategy_filters_enabled(self) -> bool:
        """Enable VWAP/ORB/Gap multi-strategy filters (default true)."""
        return os.environ.get("DAY_AUTO_TRADER_STRATEGY_FILTERS", "true").lower() == "true"

    @property
    def min_trade_value_usd(self) -> float:
        """Minimum USD trade value to beat fees (0.5%×2 + spread). Default $500."""
        return float(os.environ.get("DAY_AUTO_TRADER_MIN_TRADE_USD", "600"))

    @property
    def fee_rate(self) -> float:
        return float(os.environ.get("DAY_AUTO_TRADER_FEE_RATE", "0.005"))

    @property
    def fee_min_usd(self) -> float:
        return float(os.environ.get("DAY_AUTO_TRADER_FEE_MIN_USD", "15"))


class DayAutoTrader:
    """Automatic day trading engine that reads committee signals and manages positions."""

    def __init__(
        self,
        day_trader_sim: DayTraderSim,
        risk_manager: Optional[PortfolioRiskManager] = None,
    ) -> None:
        self.day_trader_sim = day_trader_sim
        self.risk_manager = risk_manager or PortfolioRiskManager()
        self.config = DayAutoTraderConfig()
        self._state: dict[str, Any] = self._default_state()
        self._load_state()
        self._intraday_cache: dict[str, dict] = {}  # symbol → {vwap, orb_high, orb_low, gap_pct, ...}

    # ── Config / Toggle ──────────────────────────────────────────────────────

    @property
    def is_enabled(self) -> bool:
        return self._state.get("enabled", self.config.enabled)

    def enable(self) -> None:
        self._state["enabled"] = True
        self._save_state()

    def disable(self) -> None:
        self._state["enabled"] = False
        self._save_state()

    # ── State persistence ────────────────────────────────────────────────────

    def _default_state(self) -> dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "trades_today": 0,
            "date": str(date.today()),
            "last_cycle": None,
            "total_pnl_twd": 0.0,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "history": [],
            "today_positions_opened": [],
            "today_positions_closed": [],
        }

    def _load_state(self) -> None:
        if not STATE_FILE.exists():
            return
        try:
            data = json.loads(STATE_FILE.read_text())
            self._state.update(data)
        except Exception:
            logger.exception("Failed to load day auto-trader state")

    def _save_state(self) -> None:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(self._state, indent=2, ensure_ascii=False))
        except Exception:
            logger.exception("Failed to save day auto-trader state")

    def _check_reset(self) -> None:
        today = str(date.today())
        if self._state.get("date") != today:
            self._state["trades_today"] = 0
            self._state["date"] = today
            self._state["today_positions_opened"] = []
            self._state["today_positions_closed"] = []
            self._save_state()

    # ── Market helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _now_et() -> datetime:
        return datetime.now(ZoneInfo("America/New_York"))

    @staticmethod
    def _is_premarket(now_et: Optional[datetime] = None) -> bool:
        """Return True if currently in US pre-market (4:00-9:30 ET)."""
        n = now_et or datetime.now(ZoneInfo("America/New_York"))
        t = n.time()
        return dtime(4, 0) <= t < dtime(9, 30)

    @staticmethod
    def _is_market_open_or_premarket() -> bool:
        """Return True if US market is open or in pre-market."""
        if is_market_open(Market.US):
            return True
        now_et = datetime.now(ZoneInfo("America/New_York"))
        # Also allow up to 30 min before open for analysis
        t = now_et.time()
        return dtime(4, 0) <= t < dtime(9, 30)

    # ── Committee signals ────────────────────────────────────────────────────

    def _read_committee_signals(self) -> list[dict[str, Any]]:
        if not COMMITTEE_JSON.exists():
            logger.debug("No committee signals at %s", COMMITTEE_JSON)
            return []
        try:
            data = json.loads(COMMITTEE_JSON.read_text())
        except Exception:
            logger.exception("Failed to read committee signals")
            return []

        signals = []
        for s in data.get("us_stocks", []):
            code = s.get("code", "")
            if not code:
                continue
            for sig in s.get("signals", []):
                action = sig.get("action", "hold")
                confidence = sig.get("confidence", 0)
                price = (
                    s.get("technical", {}).get("current_price")
                    or s.get("metrics", {}).get("current_price")
                    or 0
                )
                signals.append({
                    "symbol": code,
                    "name": s.get("name", code),
                    "action": action,
                    "confidence": confidence,
                    "price": round(price, 2) if price else 0,
                    "reason": sig.get("reason", ""),
                })
                break  # one signal per stock

        signals.sort(key=lambda x: -x["confidence"])
        return signals

    def _read_committee_technical(self, symbol: str) -> dict[str, Any]:
        """Read committee technical indicators for a specific symbol."""
        if not COMMITTEE_JSON.exists():
            return {}
        try:
            data = json.loads(COMMITTEE_JSON.read_text())
        except Exception:
            return {}
        for s in data.get("us_stocks", []):
            if s.get("code", "").upper() == symbol.upper():
                tech = s.get("technical", {})
                return {
                    "rsi": tech.get("rsi"),
                    "macd": tech.get("macd", {}),
                    "ma5": tech.get("ma5"),
                    "ma20": tech.get("ma20"),
                    "ma60": tech.get("ma60"),
                    "signal": tech.get("signal", "hold"),
                    "score": tech.get("score", 0),
                    "details": tech.get("details", []),
                }
        return {}

    def _dynamic_sl_tp(self, symbol: str) -> tuple[float, float]:
        """Return (sl_pct, tp_pct) dynamically adjusted via committee technicals.

        Base: SL=-2%, TP=+6% (1:3 risk/reward).
        - RSI > 80 (overbought with momentum): widen TP to +8%
        - MACD histogram negative (weakening): tighten SL to -1.5%
        - RSI < 30 (oversold, risky bounce): tighten SL to -1.5%
        """
        sl = self.config.stop_loss_pct
        tp = self.config.take_profit_pct
        tech = self._read_committee_technical(symbol)
        if not tech:
            return sl, tp

        rsi = tech.get("rsi")
        macd = tech.get("macd", {})
        histogram = macd.get("histogram", 0)

        if rsi is not None and rsi > 80:
            tp = 8.0  # momentum strong, let winners run further
        if isinstance(histogram, (int, float)) and histogram < 0:
            sl = max(1.0, sl - 0.5)  # weakening, cut loss quicker
        if rsi is not None and rsi < 30:
            sl = max(1.0, sl - 0.5)

        return sl, tp

    # ── Run cycle ────────────────────────────────────────────────────────────

    def run_cycle(self) -> list[dict[str, Any]]:
        """Execute one day auto-trading cycle.

        Returns list of action dicts describing what was done.
        """
        actions: list[dict[str, Any]] = []
        self._check_reset()
        self._intraday_cache.clear()  # Fresh intraday data each cycle

        # ── Guard: enabled ───────────────────────────────────────────────
        if not self.is_enabled:
            return []

        # ── Guard: daily trade limit ──────────────────────────────────────
        if self._state["trades_today"] >= self.config.max_trades_per_day:
            logger.info("DayAuto: daily trade limit reached, skipping")
            return []

        # ── Guard: US market hours ────────────────────────────────────────
        if not self._is_market_open_or_premarket():
            logger.debug("DayAuto: US market closed, skipping")
            return []

        now_et = self._now_et()
        is_open = is_market_open(Market.US)
        is_premarket = self._is_premarket(now_et) and self.config.open_premarket

        if not is_open and not is_premarket:
            logger.debug("DayAuto: outside trading window, skipping")
            return []

        # ── Drawdown check ───────────────────────────────────────────────
        portfolio_val = self._estimate_value()
        self.risk_manager.update_peak(portfolio_val)
        halt, reason = self.risk_manager.should_force_stop(portfolio_val)
        if halt:
            logger.warning("DayAuto: halted — %s", reason)
            return [{"symbol": "DAYTRADE", "action": "HALTED", "reason": reason}]

        # ── Get current positions & prices ───────────────────────────────
        positions = self.day_trader_sim.list_positions()
        prices: dict[str, float] = {
            p["symbol"]: p["current_price_usd"] for p in positions if p.get("current_price_usd")
        }

        # ── Step 1: Stop-loss / Take-profit ──────────────────────────────
        sl_tp_actions = self._check_sl_tp(positions, prices)
        actions.extend(sl_tp_actions)
        # Re-fetch positions after SL/TP sells
        positions = self.day_trader_sim.list_positions()
        prices = {p["symbol"]: p["current_price_usd"] for p in positions if p.get("current_price_usd")}

        # ── Step 2: Force close at end of day ────────────────────────────
        force_actions = self._force_close_positions(positions, prices)
        actions.extend(force_actions)
        if force_actions:
            # If we just force-closed everything, no new buys
            self._state["last_cycle"] = datetime.now().isoformat()
            self._save_state()
            return actions

        # ── Step 3: Open new positions ───────────────────────────────────
        if is_open:
            signals = self._read_committee_signals()
            buy_actions = self._open_new_trades(signals)
            actions.extend(buy_actions)

        # ── Save state ───────────────────────────────────────────────────
        self._state["last_cycle"] = datetime.now().isoformat()
        if actions:
            self._state["history"].append({
                "time": datetime.now().isoformat(),
                "actions": [
                    {"symbol": a.get("symbol"), "action": a.get("action"),
                     "price": a.get("price"), "shares": a.get("shares")}
                    for a in actions
                ],
            })
            self._state["history"] = self._state["history"][-50:]
        self._save_state()

        logger.info("DayAuto cycle: %d action(s)", len(actions))
        return actions

    # ── SL/TP check ──────────────────────────────────────────────────────────

    def _check_sl_tp(
        self, positions: list[dict], prices: dict[str, float],
    ) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        for pos in positions:
            sym = pos["symbol"]
            price = prices.get(sym) or pos.get("current_price_usd")
            if not price or price <= 0:
                continue
            entry = float(pos.get("entry_price_usd") or 0)
            if entry <= 0:
                continue
            pnl_pct = (price - entry) / entry * 100

            # Dynamic SL/TP based on committee technicals
            sl_pct, tp_pct = self._dynamic_sl_tp(sym)

            action_type: Optional[str] = None
            if pnl_pct <= -sl_pct:
                action_type = "SL_SELL"
            elif pnl_pct >= tp_pct:
                action_type = "TP_SELL"

            if action_type is None:
                continue

            result = self.day_trader_sim.sell_by_symbol(sym, price_usd=price)
            if result.get("ok"):
                self._state["trades_today"] += 1
                self._state["today_positions_closed"].append(sym)
                pnl_twd = result.get("pnl_twd", 0)
                self._state["total_pnl_twd"] = round(
                    self._state["total_pnl_twd"] + pnl_twd, 2
                )
                self._state["total_trades"] += 1
                if pnl_twd >= 0:
                    self._state["wins"] += 1
                else:
                    self._state["losses"] += 1
                self.risk_manager.record_trade(is_stock=True, pnl=pnl_twd)
                # Fee-adjusted net PnL
                fees_twd = self._roundtrip_fee_twd(
                    result.get("shares", 0),
                    result.get("entry_price", entry),
                    price,
                )
                net_pnl_twd = round(pnl_twd - fees_twd, 2)
                actions.append({
                    "symbol": sym,
                    "action": action_type,
                    "shares": result.get("shares"),
                    "price": price,
                    "pnl_usd": result.get("pnl_usd"),
                    "pnl_twd": pnl_twd,
                    "pnl_pct": result.get("pnl_pct"),
                    "position_id": result.get("trade_id"),
                    "reason": f"SL/TP triggered ({pnl_pct:+.2f}%)",
                    "fees_twd": fees_twd,
                    "net_pnl_twd": net_pnl_twd,
                })
                logger.info(
                    "DayAuto %s %s: %.2f%% (entry=%.2f, now=%.2f) | gross NT$%+.0f, fees NT$%.0f, net NT$%+.0f",
                    action_type, sym, pnl_pct, entry, price, pnl_twd, fees_twd, net_pnl_twd,
                )
        return actions

    # ── Force close ──────────────────────────────────────────────────────────

    def _force_close_positions(
        self, positions: list[dict], prices: dict[str, float],
    ) -> list[dict[str, Any]]:
        if not positions:
            return []
        now_et = self._now_et()
        close_time = dtime(self.config.force_close_hour, self.config.force_close_minute)
        if now_et.time() < close_time:
            return []

        actions: list[dict[str, Any]] = []
        logger.info("DayAuto: force-close time reached, closing %d position(s)", len(positions))
        for pos in positions:
            sym = pos["symbol"]
            price = prices.get(sym) or pos.get("current_price_usd") or 0
            result = self.day_trader_sim.sell_by_symbol(sym, price_usd=price)
            if result.get("ok"):
                self._state["trades_today"] += 1
                self._state["today_positions_closed"].append(sym)
                pnl_twd = result.get("pnl_twd", 0)
                self._state["total_pnl_twd"] = round(
                    self._state["total_pnl_twd"] + pnl_twd, 2
                )
                self._state["total_trades"] += 1
                if pnl_twd >= 0:
                    self._state["wins"] += 1
                else:
                    self._state["losses"] += 1
                self.risk_manager.record_trade(is_stock=True, pnl=pnl_twd)
                fees_twd = self._roundtrip_fee_twd(
                    result.get("shares", 0),
                    result.get("entry_price", 0),
                    price,
                )
                net_pnl_twd = round(pnl_twd - fees_twd, 2)
                actions.append({
                    "symbol": sym,
                    "action": "FORCE_CLOSE",
                    "shares": result.get("shares"),
                    "price": price,
                    "pnl_usd": result.get("pnl_usd"),
                    "pnl_twd": pnl_twd,
                    "pnl_pct": result.get("pnl_pct"),
                    "position_id": result.get("trade_id"),
                    "reason": "Force close at market end",
                    "fees_twd": fees_twd,
                    "net_pnl_twd": net_pnl_twd,
                })
                logger.info(
                    "DayAuto FORCE_CLOSE %s @ $%.2f | gross %+.0f fees %.0f net %+.0f TWD",
                    sym, price, pnl_twd, fees_twd, net_pnl_twd,
                )
            else:
                logger.warning("DayAuto force-close %s failed: %s", sym, result.get("error"))
        return actions

    # ── Multi-Strategy Filters (VWAP / ORB / Gap) ─────────────────────────

    def _fetch_intraday_data(self, symbol: str) -> dict[str, Any]:
        """Fetch today's intraday 5-min bars and compute VWAP, ORB range, gap.

        Returns dict with {vwap, orb_high, orb_low, orb_status, gap_pct, gap_status,
        current_price, prev_close, data_age_minutes}.
        Cached per cycle to avoid repeated yfinance calls.
        """
        if symbol in self._intraday_cache:
            data = dict(self._intraday_cache[symbol])
            # Refresh data age
            cached_at = data.pop("_cached_at", None)
            if cached_at:
                data["data_age_minutes"] = round(
                    (datetime.now() - cached_at).total_seconds() / 60, 1
                )
            return data

        try:
            import yfinance as yf
        except ImportError:
            return {}

        try:
            ticker = yf.Ticker(symbol)
            # Get today's 5-min bars (pre-post for gap calc)
            hist = ticker.history(period="1d", interval="5m", prepost=True)
            if hist is None or len(hist) < 1:
                return {}

            # Get previous close for gap calculation
            prev = ticker.history(period="5d", interval="1d")
            prev_close = float(prev["Close"].iloc[-2]) if len(prev) >= 2 else 0

            # Current price (last close)
            current_price = float(hist["Close"].iloc[-1])

            # ── VWAP calculation ──────────────────────────────────────────
            typical_prices = (hist["High"] + hist["Low"] + hist["Close"]) / 3
            volumes = hist["Volume"]
            cum_tp_vol = (typical_prices * volumes).cumsum()
            cum_vol = volumes.cumsum()
            vwap = float(cum_tp_vol.iloc[-1] / cum_vol.iloc[-1]) if cum_vol.iloc[-1] > 0 else current_price

            # ── ORB (Opening Range Breakout): first 5-min bar of regular session ──
            # Regular session bars start at 9:30 AM ET. We use the first 3 bars (15 min)
            # or the first bar (5 min) for the opening range.
            first_bars = hist.iloc[:3]  # first 3 bars (~15 min)
            orb_high = float(first_bars["High"].max())
            orb_low = float(first_bars["Low"].min())

            # ── Gap calculation ───────────────────────────────────────────
            gap_pct = ((current_price - prev_close) / prev_close * 100) if prev_close > 0 else 0

            # ── Determine status ──────────────────────────────────────────
            vwap_diff_pct = (current_price - vwap) / vwap * 100 if vwap > 0 else 0
            if abs(vwap_diff_pct) <= 0.5:
                vwap_status = "near"
            elif vwap_diff_pct > 0:
                vwap_status = "above"
            else:
                vwap_status = "below"

            if current_price > orb_high:
                orb_status = "breakout"
            elif current_price < orb_low:
                orb_status = "breakdown"
            else:
                orb_status = "inside"

            if abs(gap_pct) < 1:
                gap_status = "flat"
            elif gap_pct > 0:
                gap_status = "gap_up"
            else:
                gap_status = "gap_down"

            result = {
                "vwap": round(vwap, 2),
                "vwap_diff_pct": round(vwap_diff_pct, 2),
                "vwap_status": vwap_status,
                "orb_high": round(orb_high, 2),
                "orb_low": round(orb_low, 2),
                "orb_status": orb_status,
                "gap_pct": round(gap_pct, 2),
                "gap_status": gap_status,
                "current_price": round(current_price, 2),
                "prev_close": round(prev_close, 2),
                "data_age_minutes": 0,
            }
            result["_cached_at"] = datetime.now()
            self._intraday_cache[symbol] = result
            return result
        except Exception:
            logger.debug("Failed to fetch intraday data for %s", symbol)
            return {}

    def _strategy_score(
        self, symbol: str, signal: dict[str, Any],
    ) -> dict[str, Any]:
        """Compute multi-layer strategy score for a signal.

        Returns {pass, score, layers: {...}, reason}.
        Layers: committee_confidence × vwap_multiplier × orb_multiplier.
        """
        committee_conf = signal.get("confidence", 0)
        layers: dict[str, Any] = {
            "committee": {"name": "Committee AI", "confidence": committee_conf, "pass": True},
        }

        # If strategy filters disabled, only committee matters
        if not self.config.strategy_filters_enabled:
            return {
                "pass": True,
                "score": committee_conf,
                "layers": layers,
                "reason": "Strategy filters disabled — committee only",
            }

        intraday = self._fetch_intraday_data(symbol)
        if not intraday:
            # No intraday data → still allow trade but flag it
            return {
                "pass": True,
                "score": committee_conf,
                "layers": layers,
                "reason": "No intraday data — committee signal only",
            }

        # ── VWAP multiplier ──────────────────────────────────────────────
        vwap_status = intraday["vwap_status"]
        vwap_mult = {"above": 1.2, "near": 1.0, "below": 0.5}.get(vwap_status, 1.0)
        layers["vwap"] = {
            "name": "VWAP趨勢",
            "status": vwap_status,
            "value": intraday["vwap"],
            "diff_pct": intraday["vwap_diff_pct"],
            "multiplier": vwap_mult,
            "pass": vwap_mult >= 1.0,
        }

        # ── ORB multiplier ───────────────────────────────────────────────
        orb_status = intraday["orb_status"]
        orb_mult = {"breakout": 1.3, "inside": 0.7, "breakdown": 0.5}.get(orb_status, 1.0)
        layers["orb"] = {
            "name": "ORB突破",
            "status": orb_status,
            "high": intraday["orb_high"],
            "low": intraday["orb_low"],
            "multiplier": orb_mult,
            "pass": orb_mult >= 1.0,
        }

        # ── Gap multiplier ───────────────────────────────────────────────
        gap_status = intraday["gap_status"]
        gap_pct = intraday["gap_pct"]
        if gap_status == "gap_up" and abs(gap_pct) > 2:
            gap_mult = 1.10  # boost for strong gap catalysts
        elif gap_status == "gap_down" and abs(gap_pct) > 2:
            gap_mult = 0.7   # large gap down is bearish
        else:
            gap_mult = 1.0
        layers["gap"] = {
            "name": "Gap動能",
            "status": gap_status,
            "pct": gap_pct,
            "multiplier": gap_mult,
            "pass": gap_mult >= 0.7,
        }

        # ── Final score ──────────────────────────────────────────────────
        score = committee_conf * vwap_mult * orb_mult
        # Cap score at 1.0 but keep raw for logging
        effective_score = min(score, 1.0)

        # Pass threshold: score >= 0.3 (with all multipliers applied)
        # Means: 60% conf × 0.5(vwap below) × 0.7(orb inside) = 0.21 → FAIL
        # But:   60% conf × 1.2(vwap above) × 1.3(orb breakout) = 0.94 → PASS
        passed = score >= 0.30

        reasons: list[str] = []
        if vwap_mult < 1.0:
            reasons.append(f"VWAP {vwap_status} (×{vwap_mult})")
        if orb_mult < 1.0:
            reasons.append(f"ORB {orb_status} (×{orb_mult})")
        if not reasons:
            reasons.append("all layers passed")
        if gap_status == "gap_up" and abs(gap_pct) > 2:
            reasons.append(f"gap +{gap_pct:.1f}%")
        elif gap_status == "gap_down" and abs(gap_pct) > 2:
            reasons.append(f"gap {gap_pct:.1f}%")

        return {
            "pass": passed,
            "score": round(effective_score, 3),
            "raw_score": round(score, 3),
            "layers": layers,
            "reason": "; ".join(reasons),
            "intraday": intraday,
        }

    # ── Open new trades ───────────────────────────────────────────────────────

    def _open_new_trades(self, signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Open new positions from committee signals.

        Uses 巨人傑 probe-then-pyramid strategy:
        1. Open probe at probe_pct% of cash (default 10%)
        2. On next cycle, if price moved +1% above entry → add to full position (25%)
        3. If price moved against probe → do nothing, let SL handle it
        """
        actions: list[dict[str, Any]] = []
        current_positions = self.day_trader_sim.list_positions()
        available_slots = self.config.max_positions - len(current_positions)
        opened_today = set(self._state.get("today_positions_opened", []))

        # ── Phase A: Check existing probe positions for pyramid add-ons ────
        if available_slots <= 0:
            pass  # no room for new probes, but existing probes might mature
        else:
            for pos in current_positions:
                sym = pos["symbol"]
                price = pos.get("current_price_usd") or pos.get("entry_price_usd", 0)
                entry = float(pos.get("entry_price_usd") or 0)
                if entry <= 0 or price <= 0:
                    continue

                pnl_pct = (price - entry) / entry * 100
                if pnl_pct < self.config.probe_confirm_pct:
                    continue  # hasn't confirmed yet

                # Check if already at full size
                cash = self.day_trader_sim.get_cash()
                target_value = cash * (self.config.position_pct / 100)
                current_value = pos.get("shares", 0) * entry * USD_TWD_RATE
                if current_value >= target_value * 0.9:
                    continue  # already near full size

                # Calculate add-on shares
                add_value = target_value - current_value
                add_cost_per_share = price * USD_TWD_RATE
                if add_cost_per_share <= 0:
                    continue
                add_shares = max(1, int(add_value / add_cost_per_share))
                if add_shares < 1:
                    continue

                result = self.day_trader_sim.add_to_position(pos["id"], add_shares, price)
                if result.get("ok"):
                    self._state["trades_today"] += 1
                    self.risk_manager.record_trade(is_stock=True)
                    actions.append({
                        "symbol": sym,
                        "action": "PYRAMID_ADD",
                        "shares": add_shares,
                        "price": price,
                        "total_shares": result["total_shares"],
                        "new_avg_price": result["new_avg_price"],
                        "reason": f"Probe confirmed (+{pnl_pct:+.2f}%), adding to full position",
                    })
                    logger.info(
                        "DayAuto PYRAMID %s +%d @ $%.2f → total %s",
                        sym, add_shares, price, result["total_shares"],
                    )

        # ── Phase B: Open new probe positions ─────────────────────────────
        if available_slots <= 0:
            return actions

        for sig in signals:
            if len([a for a in actions if a["action"] == "PROBE_BUY"]) >= available_slots:
                break
            if self._state["trades_today"] >= self.config.max_trades_per_day:
                break

            action = sig["action"]
            if action not in ("strong_buy", "buy"):
                continue
            if sig["confidence"] < self.config.min_confidence:
                continue

            sym = sig["symbol"]
            price = sig["price"]
            if not price or price <= 0:
                logger.warning("DayAuto: no price for %s, skipping", sym)
                continue
            if sym in opened_today:
                logger.info("DayAuto: already bought %s today, skipping", sym)
                continue
            if any(p["symbol"] == sym for p in current_positions):
                logger.info("DayAuto: already holding %s, skipping", sym)
                continue

            # ── Multi-strategy filter (VWAP/ORB/Gap) ──────────────────
            strat = self._strategy_score(sym, sig)
            if not strat["pass"]:
                logger.info(
                    "DayAuto: strategy filter BLOCKED %s (score %.3f, %s)",
                    sym, strat["score"], strat["reason"],
                )
                continue

            cash = self.day_trader_sim.get_cash()
            # Probe: use probe_pct% instead of full position_pct%
            probe_value_twd = cash * (self.config.probe_pct / 100)
            cost_per_share_twd = price * USD_TWD_RATE
            if cost_per_share_twd <= 0 or probe_value_twd < cost_per_share_twd:
                logger.info(
                    "DayAuto: probe value %.0f < share cost %.0f for %s, skipping",
                    probe_value_twd, cost_per_share_twd, sym,
                )
                continue

            # ── Fee viability check ──────────────────────────────────────
            shares_est = max(1, int(probe_value_twd / cost_per_share_twd))
            trade_value_usd = shares_est * price
            if trade_value_usd < self.config.min_trade_value_usd:
                fee_info = self._min_profitable_trade_value(price, strat.get("layers", {}).get("vwap", {}).get("sl", 2), strat.get("layers", {}).get("vwap", {}).get("tp", 6))
                logger.info(
                    "DayAuto: trade value $%.0f < min $%.0f for %s — fee %s%% of stop loss, skipping",
                    trade_value_usd, self.config.min_trade_value_usd, sym, fee_info["fee_pct_of_sl"],
                )
                continue

            shares = max(1, int(probe_value_twd / cost_per_share_twd))
            pid = self.day_trader_sim.buy(
                sym, shares, price,
                note=f"day_probe: {action} conf {sig['confidence']:.0%}",
            )
            if pid > 0:
                self._state["trades_today"] += 1
                self._state.setdefault("today_positions_opened", []).append(sym)
                self.risk_manager.record_trade(is_stock=True)
                actions.append({
                    "symbol": sym,
                    "action": "PROBE_BUY",
                    "shares": shares,
                    "price": price,
                    "confidence": sig["confidence"],
                    "reason": sig.get("reason", ""),
                    "position_id": pid,
                    "strategy_score": strat["score"],
                    "strategy_layers": strat.get("layers", {}),
                    "est_fees_twd": self._roundtrip_fee_twd(shares, price, price),
                })
                vwap_info = ""
                if strat.get("layers", {}).get("vwap"):
                    vwap_info = f"| VWAP {strat['layers']['vwap']['status']}"
                orb_info = ""
                if strat.get("layers", {}).get("orb"):
                    orb_info = f"| ORB {strat['layers']['orb']['status']}"
                logger.info(
                    "DayAuto PROBE %s x%d @ $%.2f (probe %.0f%%%s%s, score %.3f)",
                    sym, shares, price, self.config.probe_pct, vwap_info, orb_info, strat["score"],
                )

        return actions

    # ── Fee calculation ──────────────────────────────────────────────────────

    def _roundtrip_fee_twd(self, shares: float, buy_price_usd: float, sell_price_usd: float) -> float:
        """Calculate round-trip fee in TWD for a completed day trade.

        Formula: (buy_value * 0.5% + max) + (sell_value * 0.5% or min $15)
        Minimum $15 USD per side = NT$495 per side if the value is low.
        """
        buy_value = shares * buy_price_usd
        sell_value = shares * sell_price_usd
        fee_rate = self.config.fee_rate
        fee_min = self.config.fee_min_usd

        buy_fee = max(buy_value * fee_rate, fee_min)
        sell_fee = max(sell_value * fee_rate, fee_min)
        total_usd = buy_fee + sell_fee
        return round(total_usd * USD_TWD_RATE, 2)

    def _min_profitable_trade_value(self, entry_price: float, sl_pct: float, tp_pct: float) -> dict:
        """Check if a given trade size can beat fees.

        Returns {viable, min_shares, fee_pct_of_sl, fee_pct_of_expected}.
        A trade is viable if the expected profit > round-trip fees.
        """
        fee_min = self.config.fee_min_usd
        fee_rate = self.config.fee_rate
        # Micro-trade: fees dominate at minimum
        # At $15 min per side, round-trip = $30 USD = NT$990
        # For a trade with SL=-2%: max loss per share is entry*2%
        # For fee to be < 20% of stop-loss: need enough shares
        min_value = self.config.min_trade_value_usd  # $600
        shares_for_min = int(min_value / entry_price) if entry_price > 0 else 1
        if shares_for_min < 1:
            shares_for_min = 1

        # Fee as % of expected loss (SL)
        loss_per_share = entry_price * sl_pct / 100
        fee_per_share = fee_min * 2 / shares_for_min  # both sides at min
        fee_pct_of_sl = (fee_per_share / loss_per_share * 100) if loss_per_share > 0 else 999

        # Fee as % of expected win (TP)
        win_per_share = entry_price * tp_pct / 100
        fee_pct_of_tp = (fee_per_share / win_per_share * 100) if win_per_share > 0 else 999

        viable = fee_pct_of_sl < 50  # fee should be < 50% of max acceptable loss
        return {
            "viable": viable,
            "min_shares": shares_for_min,
            "min_value_usd": min_value,
            "roundtrip_fee_twd": round(fee_min * USD_TWD_RATE * 2, 0),
            "fee_pct_of_sl": round(fee_pct_of_sl, 1),
            "fee_pct_of_tp": round(fee_pct_of_tp, 1),
        }

    # ── Value estimation ─────────────────────────────────────────────────────

    def _estimate_value(self) -> float:
        """Estimate total day trade account value (cash + ~market value)."""
        return self.day_trader_sim.get_equity()

    # ── Telegram summary ─────────────────────────────────────────────────────

    def summary_text(self) -> str:
        self._check_reset()
        cash = self.day_trader_sim.get_cash()
        positions = self.day_trader_sim.list_positions()
        daily_pnl = self.day_trader_sim.get_daily_pnl()
        total_pnl = self._state.get("total_pnl_twd", 0)
        wins = self._state.get("wins", 0)
        losses = self._state.get("losses", 0)
        total_trades = self._state.get("total_trades", 0)

        lines = [
            "⚡ 當沖自動交易引擎",
            f"狀態：{'🟢 啟用' if self.is_enabled else '🔴 停用'}",
            f"今日交易：{self._state['trades_today']}/{self.config.max_trades_per_day}",
            f"當沖現金：NT${cash:,.0f}",
            f"持倉：{len(positions)}/{self.config.max_positions}",
            f"本日 PnL：NT${daily_pnl.get('realized_pnl_twd', 0):+,.0f} ({daily_pnl.get('trades_count', 0)} 筆)",
            "",
            "⚙️ 設定",
            f"試單：{self.config.probe_pct}% | 加碼到：{self.config.position_pct}% (確認 +{self.config.probe_confirm_pct}%)",
            f"策略過濾：{'✅ VWAP/ORB/Gap' if self.config.strategy_filters_enabled else '🔓 僅 Committee'}",
            f"手續費：{self.config.fee_rate:.1%} / 最低 ${self.config.fee_min_usd}（永豐金美股複委託）",
            f"最低單筆：${self.config.min_trade_value_usd} USD（避免被手續費吃掉）",
            f"停損：-{self.config.stop_loss_pct}% | 停利：+{self.config.take_profit_pct}%（RSI/MACD 動態）",
            f"強制平倉：{self.config.force_close_hour:02d}:{self.config.force_close_minute:02d} ET",
            f"信心門檻：{self.config.min_confidence:.0%}",
            "",
            "📊 累計績效",
            f"總交易：{total_trades} 筆",
            f"勝率：{wins / total_trades:.0%}" if total_trades > 0 else "勝率：-",
            f"累計 PnL：NT${total_pnl:+,.0f}",
            "",
            "📜 最近動作：",
        ]

        history = self._state.get("history", [])
        if history:
            for entry in history[-3:]:
                for a in entry.get("actions", []):
                    lines.append(f"  {a['action']} {a['symbol']} @ ${a.get('price', '?')}")
        else:
            lines.append("  （尚無記錄）")

        lines.extend(["", "/dayautotrade — 查看狀態", "/dayautotrade on — 啟用", "/dayautotrade off — 停用", "/dayreview — 檢討報告"])
        return "\n".join(lines)

    # ── Post-market review (巨人傑: 盤後瘋狂檢討) ───────────────────────────

    def review_text(self) -> str:
        """Generate a post-market day trading review report.

        Classifies trades as:
          - 看對做對: profitable trades (good)
          - 看對做錯: signal was correct but lost money (cut loss too early or missed TP)
          - 看錯做對: signal was wrong but made money (luck, may mislead)
          - 看錯做錯: signal was wrong and lost money (correct outcome for bad signal)
          - 滑價: probe confirmed but went flat
        """
        self._check_reset()
        today = str(date.today())

        # Gather today's trades
        positions = self.day_trader_sim.list_positions()
        daily_pnl = self.day_trader_sim.get_daily_pnl(today)
        realized = daily_pnl.get("realized_pnl_twd", 0)
        trade_count = daily_pnl.get("trades_count", 0)

        # Read committee signals for comparison
        committee_view: dict[str, str] = {}  # symbol → action
        try:
            if COMMITTEE_JSON.exists():
                data = json.loads(COMMITTEE_JSON.read_text())
                for s in data.get("us_stocks", []):
                    sigs = s.get("signals", [])
                    if sigs:
                        committee_view[s["code"]] = sigs[0].get("action", "unknown")
        except Exception:
            pass

        # Classify today's closed trades from state history
        right_right: list[str] = []
        right_wrong: list[str] = []
        wrong_right: list[str] = []
        wrong_wrong: list[str] = []
        probes_added: list[str] = []
        probes_failed: list[str] = []

        history = self._state.get("history", [])
        today_actions = [h for h in history if h.get("time", "").startswith(today)]

        for entry in today_actions:
            for a in entry.get("actions", []):
                sym = a.get("symbol", "")
                act = a.get("action", "")
                pnl = a.get("pnl_pct", 0)
                signal = committee_view.get(sym, "unknown")

                if act == "PYRAMID_ADD":
                    probes_added.append(sym)
                elif act in ("SL_SELL",):
                    # Cut loss — was signal correct?
                    if signal in ("strong_buy", "buy"):
                        right_wrong.append(f"{sym} (conf={a.get('confidence', '?')})")
                    else:
                        wrong_wrong.append(f"{sym} ({a.get('pnl_pct', 0):+.1f}%)")
                elif act in ("TP_SELL",) and pnl > 0:
                    right_right.append(f"{sym} (+{pnl:.1f}%)")
                elif act == "FORCE_CLOSE":
                    if pnl > 0:
                        right_right.append(f"{sym} (+{pnl:.1f}% force)")
                    else:
                        wrong_wrong.append(f"{sym} ({pnl:+.1f}% force)")

        # Stats
        wins = self._state.get("wins", 0)
        losses = self._state.get("losses", 0)
        total_trades = self._state.get("total_trades", 0)
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

        # Average win/loss
        all_closed = [h for h in history if h.get("time", "").startswith(today)]
        avg_win = avg_loss = 0.0
        win_pnls: list[float] = []
        loss_pnls: list[float] = []
        for entry in all_closed:
            for a in entry.get("actions", []):
                p = a.get("pnl_pct", 0)
                if p > 0:
                    win_pnls.append(p)
                elif p < 0:
                    loss_pnls.append(p)
        if win_pnls:
            avg_win = sum(win_pnls) / len(win_pnls)
        if loss_pnls:
            avg_loss = sum(loss_pnls) / len(loss_pnls)

        # Risk/reward ratio
        rr_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

        # Recommendations
        recs: list[str] = []
        sl, tp = self.config.stop_loss_pct, self.config.take_profit_pct
        if rr_ratio < 2.0 and total_trades >= 5:
            recs.append(f"風報比 {rr_ratio:.1f} < 2.0，考慮收緊 SL 或拉高 TP")
        if right_wrong:
            recs.append(f"看對做錯 {len(right_wrong)} 筆：應檢討是否停損設太緊 (目前 {sl}%)")
        if win_rate < 40 and total_trades >= 10:
            recs.append(f"勝率 {win_rate:.0f}% 偏低，檢查 Committee 訊號品質")
        if len(probes_added) == 0 and len(today_actions) > 0:
            recs.append("今日無試單確認(加碼)，可能市場方向不明確")
        if not recs:
            recs.append("策略參數尚可，持續觀察累計損益趨勢。")

        lines = [
            f"📋 當沖檢討報告 — {today}",
            "─" * 25,
            "",
            "📊 本日統計",
            f"已平倉交易：{trade_count} 筆",
            f"本日損益：NT${realized:+,.0f}",
            f"未平倉：{len(positions)} 筆",
            "",
            f"累計績效",
            f"總交易：{total_trades} 筆 | 勝率：{win_rate:.0f}%",
            f"平均贏：{avg_win:+.2f}% | 平均輸：{avg_loss:+.2f}%",
            f"風報比：{rr_ratio:.1f}x",
            f"淨 PnL：NT${self._state.get('total_pnl_twd', 0):+,.0f}",
            "",
            "🎯 交易分類",
            f"看對做對 ✅：{len(right_right)} 筆 — {' '.join(right_right) if right_right else '無'}",
            f"看對做錯 ⚠️：{len(right_wrong)} 筆 — {' '.join(right_wrong) if right_wrong else '無'}",
            f"看錯做對 🔀：{len(wrong_right)} 筆 — {' '.join(wrong_right) if wrong_right else '無'}",
            f"看錯做錯 ❌：{len(wrong_wrong)} 筆 — {' '.join(wrong_wrong) if wrong_wrong else '無'}",
            "",
            f"試單加碼 🚀：{len(probes_added)} 筆 — {' '.join(probes_added) if probes_added else '無'}",
            "",
            "💡 建議",
        ] + [f"  • {r}" for r in recs] + [
            "",
            f"目前設定：試單 {self.config.probe_pct}% → 加碼 {self.config.position_pct}%",
            f"停損 {sl}% / 停利 {tp}%（RSI/MACD 動態）",
        ]
        return "\n".join(lines)

    def generate_review_file(self) -> Optional[Path]:
        """Generate a review JSON file and return path."""
        today = str(date.today())
        try:
            REVIEW_DIR.mkdir(parents=True, exist_ok=True)
            path = REVIEW_DIR / f"day_review_{today}.json"
            data = {
                "date": today,
                "generated_at": datetime.now().isoformat(),
                "report": self.review_text(),
                "state": dict(self._state),
                "positions": self.day_trader_sim.list_positions(),
                "config": {
                    "probe_pct": self.config.probe_pct,
                    "position_pct": self.config.position_pct,
                    "stop_loss_pct": self.config.stop_loss_pct,
                    "take_profit_pct": self.config.take_profit_pct,
                },
            }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            return path
        except Exception:
            logger.exception("Failed to generate review file")
            return None
