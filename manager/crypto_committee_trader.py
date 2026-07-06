"""CryptoCommitteeTrader — executes on-chain trades from AI committee crypto signals.

Reads daily_signals.json["crypto"] and maps strong_buy/buy → BUY,
strong_sell/sell → SELL via RealTradeBridge for real DEX execution.

Runs as a scheduler job after the stock committee trader (7:45 AM).
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from manager.real_trader_bridge import RealTradeBridge

logger = logging.getLogger(__name__)

COMMITTEE_JSON = Path(__file__).parent.parent / "data" / "committee" / "daily_signals.json"
STATE_FILE = Path(__file__).parent.parent / "data" / "crypto_committee_trader_state.json"

# Hard floor: on-chain trades below this confidence are NEVER executed.
# Real money needs a higher bar — this cannot be overridden by env vars.
HARD_CONFIDENCE_FLOOR = 0.60


class CryptoCommitteeTraderConfig:
    @property
    def max_trades_per_day(self) -> int:
        return int(__import__("os").environ.get("CRYPTO_COMMITTEE_MAX_PER_DAY", "3"))

    @property
    def trade_amount_eth(self) -> float:
        return float(__import__("os").environ.get("CRYPTO_COMMITTEE_TRADE_AMOUNT_ETH", "0.02"))

    @property
    def min_confidence(self) -> float:
        return float(__import__("os").environ.get("CRYPTO_COMMITTEE_MIN_CONFIDENCE", "0.5"))

    @property
    def enabled(self) -> bool:
        return __import__("os").environ.get("CRYPTO_COMMITTEE_TRADER_ENABLED", "true").lower() == "true"

    @property
    def dry_run(self) -> bool:
        """If True, log intended trades without executing on-chain."""
        return __import__("os").environ.get("CRYPTO_COMMITTEE_DRY_RUN", "true").lower() == "true"


class CryptoCommitteeTrader:
    """Reads crypto committee signals and executes on-chain trades via RealTradeBridge."""

    def __init__(self, real_trade_bridge: RealTradeBridge):
        self.config = CryptoCommitteeTraderConfig()
        self.bridge = real_trade_bridge
        self._state = self._load_state()

    def _load_state(self) -> dict:
        try:
            if STATE_FILE.exists():
                return json.loads(STATE_FILE.read_text())
        except Exception:
            logger.exception("Failed to load crypto committee trader state")
        return self._default_state()

    def _default_state(self) -> dict:
        return {
            "enabled": self.config.enabled,
            "trades_today": 0,
            "date": str(date.today()),
            "history": [],
        }

    def _save_state(self) -> None:
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(self._state, indent=2))
        except Exception:
            logger.exception("Failed to save crypto committee trader state")

    def _check_reset(self) -> None:
        today = str(date.today())
        if self._state.get("date") != today:
            self._state["trades_today"] = 0
            self._state["date"] = today

    async def run_cycle(self) -> list[dict]:
        """Read crypto committee signals and execute on-chain trades.

        Returns list of action dicts (empty if nothing traded).
        """
        self._check_reset()
        if not self._state.get("enabled", False):
            logger.debug("Crypto committee trader disabled, skipping")
            return []

        if self._state["trades_today"] >= self.config.max_trades_per_day:
            logger.info("Daily crypto trade limit reached, skipping committee cycle")
            return []

        if not COMMITTEE_JSON.exists():
            logger.warning("No committee data found at %s", COMMITTEE_JSON)
            return []

        try:
            data = json.loads(COMMITTEE_JSON.read_text())
        except Exception as e:
            logger.error("Failed to read committee JSON: %s", e)
            return []

        crypto_assets = data.get("crypto", [])
        if not crypto_assets:
            return []

        actions = []

        # Priority: strong_sell > sell > strong_buy > buy
        priority = []
        for s in crypto_assets:
            if s.get("status") != "ok":
                continue
            sig = s.get("signals", [{}])[0]
            action = sig.get("action", "hold")
            confidence = sig.get("confidence", 0)
            if action in ("strong_sell", "sell", "strong_buy", "buy"):
                priority.append((s, action, confidence))

        order = {"strong_sell": 0, "sell": 1, "strong_buy": 2, "buy": 3}
        priority.sort(key=lambda x: (order.get(x[1], 9), -x[2]))

        for s, action, confidence in priority:
            if self._state["trades_today"] >= self.config.max_trades_per_day:
                break

            symbol = s["code"]  # e.g. "BTCUSDT"
            name = s["name"]
            is_buy = action in ("buy", "strong_buy")
            is_sell = action in ("sell", "strong_sell")

            # Skip assets that are native ETH (cannot buy native ETH on a DEX)
            if is_buy and symbol in ("ETHUSDT",):
                logger.info("Skipping BUY %s (%s): native ETH — cannot buy on DEX", symbol, name)
                actions.append({
                    "symbol": symbol, "name": name, "action": "SKIP",
                    "reason": "native_ETH_asset_cannot_buy_on_DEX",
                })
                continue

            if is_buy:
                effective_min_conf = max(self.config.min_confidence, HARD_CONFIDENCE_FLOOR)
                if confidence < effective_min_conf:
                    logger.info("Skipping crypto BUY %s: confidence %.2f < threshold %.2f (hard floor %.2f)",
                                symbol, confidence, effective_min_conf, HARD_CONFIDENCE_FLOOR)
                    continue

                amount_eth = self.config.trade_amount_eth

                if self.config.dry_run:
                    logger.info("DRY-RUN crypto BUY %s (%s) %.4f ETH  conf=%.0f%%",
                                symbol, name, amount_eth, confidence * 100)
                    actions.append({
                        "symbol": symbol, "name": name, "action": "BUY",
                        "amount_eth": amount_eth, "confidence": confidence,
                        "reason": f"dry_run_{action}_signal",
                    })
                    self._state["trades_today"] += 1
                else:
                    # Check native gas balance on Polygon (need at least 0.5 POL for gas)
                    gas_bal = self.bridge.get_native_balance("polygon")
                    if gas_bal is not None and gas_bal < 0.5:
                        logger.warning("Insufficient POL gas balance (%.4f < 0.5), skipping %s",
                                       gas_bal, symbol)
                        actions.append({
                            "symbol": symbol, "name": name, "action": "BLOCKED",
                            "reason": f"insufficient_POL_gas_{gas_bal:.4f}",
                        })
                        continue

                    result = await self.bridge.execute_buy(
                        symbol=symbol,
                        amount_eth=amount_eth,
                        confidence=confidence,
                        reason=f"committee_{action}_signal",
                    )
                    if result.get("success"):
                        self._state["trades_today"] += 1
                        tx = (result.get("tx_hash") or "")[:10]
                        logger.info("On-chain BUY %s (%s) %.4f ETH  tx=%s",
                                    symbol, name, amount_eth, tx)
                        actions.append({
                            "symbol": symbol, "name": name, "action": "BUY",
                            "amount_eth": amount_eth, "confidence": confidence,
                            "tx_hash": result.get("tx_hash"),
                            "trade_id": result.get("trade_id"),
                            "reason": f"{action} signal",
                        })
                    else:
                        logger.warning("On-chain BUY %s failed: %s", symbol, result.get("error"))
                        actions.append({
                            "symbol": symbol, "name": name, "action": "FAILED",
                            "reason": result.get("error", "unknown"),
                        })

            elif is_sell:
                effective_min_conf = max(self.config.min_confidence, HARD_CONFIDENCE_FLOOR)
                if confidence < effective_min_conf:
                    logger.info("Skipping crypto SELL %s: confidence %.2f < threshold %.2f (hard floor %.2f)",
                                symbol, confidence, effective_min_conf, HARD_CONFIDENCE_FLOOR)
                    continue

                if self.config.dry_run:
                    logger.info("DRY-RUN crypto SELL %s (%s)  conf=%.0f%%",
                                symbol, name, confidence * 100)
                    actions.append({
                        "symbol": symbol, "name": name, "action": "SELL",
                        "confidence": confidence,
                        "reason": f"dry_run_{action}_signal",
                    })
                    self._state["trades_today"] += 1
                else:
                    result = await self.bridge.execute_sell(
                        symbol=symbol,
                        confidence=confidence,
                    )
                    if result.get("success"):
                        self._state["trades_today"] += 1
                        tx = (result.get("tx_hash") or "")[:10]
                        logger.info("On-chain SELL %s (%s)  tx=%s", symbol, name, tx)
                        actions.append({
                            "symbol": symbol, "name": name, "action": "SELL",
                            "tx_hash": result.get("tx_hash"),
                            "trade_id": result.get("trade_id"),
                            "confidence": confidence,
                            "reason": f"{action} signal",
                        })
                    else:
                        logger.warning("On-chain SELL %s failed: %s", symbol, result.get("error"))
                        actions.append({
                            "symbol": symbol, "name": name, "action": "FAILED",
                            "reason": result.get("error", "unknown"),
                        })

        if actions:
            self._state["history"].append({
                "time": datetime.now().isoformat(),
                "actions": actions,
            })
            self._state["history"] = self._state["history"][-50:]
        self._save_state()

        return actions
