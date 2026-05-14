"""Copy trading on Polymarket — follows leader wallets and mirrors positions.

Detects new positions by polling Polygonscan for ERC1155 transfers of
Polymarket outcome tokens. Resolves token IDs to market data via the
Gamma API, then mirrors trades via the CLOB at a configurable ratio.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from bot.polymarket_clob import PolymarketCLOB, MarketData
from bot.polygonscan_client import PolygonscanClient

logger = logging.getLogger(__name__)

# Contracts on Polygon mainnet
CTF_EXCHANGE = "0x4D97DCd97eC945f5cf4732E76B5Cce92f41C1b3b"
NEG_RISK_ADAPTER = "0xC5d563A36AE78145C45a50134d48A1215220f80a"


class CopyTraderConfig:
    """Read-only configuration from environment variables."""

    @property
    def enabled(self) -> bool:
        return os.environ.get("POLYCOPY_ENABLED", "false").lower() == "true"

    @property
    def leaders(self) -> list[str]:
        raw = os.environ.get("POLYCOPY_LEADERS", "")
        return [a.strip() for a in raw.split(",") if a.strip()]

    @property
    def copy_ratio(self) -> float:
        return float(os.environ.get("POLYCOPY_RATIO", "0.1"))

    @property
    def max_per_trade_usdc(self) -> float:
        return float(os.environ.get("POLYCOPY_MAX_PER_TRADE", "10.0"))

    @property
    def max_daily_trades(self) -> int:
        return int(os.environ.get("POLYCOPY_MAX_DAILY_TRADES", "10"))

    @property
    def scan_interval_minutes(self) -> int:
        return int(os.environ.get("POLYCOPY_SCAN_INTERVAL", "15"))

    @property
    def start_block(self) -> int:
        return int(os.environ.get("POLYCOPY_START_BLOCK", "0"))

    @property
    def dry_run(self) -> bool:
        return os.environ.get("POLYCOPY_DRY_RUN", "false").lower() == "true"


class CopyTrader:
    """Scans leader wallets for new Polymarket positions and mirrors them.

    State persists to ``data/copy_trader_state.json``, tracking
    ``last_block`` per leader to avoid re-processing transfers.
    """

    def __init__(self, clob: Optional[PolymarketCLOB] = None,
                 polygonscan: Optional[PolygonscanClient] = None):
        self.config = CopyTraderConfig()
        self.clob = clob or PolymarketCLOB()
        self.polygonscan = polygonscan or PolygonscanClient(
            api_key=os.environ.get("POLYGONSCAN_API_KEY", "")
        )
        self._state_file = Path(__file__).parent.parent / "data" / "copy_trader_state.json"
        self._state = self._load_state()

    # ── State ───────────────────────────────────

    def _load_state(self) -> dict:
        try:
            if self._state_file.exists():
                return json.loads(self._state_file.read_text())
        except Exception:
            logger.exception("Failed to load copy_trader state")
        return self._default_state()

    def _default_state(self) -> dict:
        return {
            "enabled": self.config.enabled,
            "date": str(date.today()),
            "trades_today": 0,
            "leaders": {},
        }

    def _save_state(self) -> None:
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(json.dumps(self._state, indent=2))
        except Exception:
            logger.exception("Failed to save copy_trader state")

    def _check_reset(self) -> None:
        today = str(date.today())
        if self._state.get("date") != today:
            self._state["trades_today"] = 0
            self._state["date"] = today

    # ── Enable / Disable ────────────────────────

    def enable(self) -> None:
        self._state["enabled"] = True
        self._save_state()
        logger.info("Copy trader enabled")

    def disable(self) -> None:
        self._state["enabled"] = False
        self._save_state()
        logger.info("Copy trader disabled")

    @property
    def is_enabled(self) -> bool:
        return self._state.get("enabled", False)

    # ── Core cycle ──────────────────────────────

    def run_cycle(self) -> list[dict]:
        """Scan all leader wallets and mirror new positions.

        Returns list of executed trade dicts.
        """
        self._check_reset()
        if not self.is_enabled:
            return []

        leaders = self.config.leaders
        if not leaders:
            logger.warning("Copy trader enabled but no POLYCOPY_LEADERS configured")
            return []

        if self._state["trades_today"] >= self.config.max_daily_trades:
            logger.info("Copy trader: daily trade limit reached")
            return []

        # Pre-fetch active markets for token ID resolution (cache)
        all_markets = PolymarketCLOB.fetch_active_markets(limit=200)
        token_to_market: dict[str, tuple[MarketData, int]] = {}
        for m in all_markets:
            for i, tid in enumerate(m.token_ids):
                token_to_market[tid] = (m, i)

        all_trades: list[dict] = []

        for leader_addr in leaders:
            trades = self._scan_leader(leader_addr, token_to_market)
            all_trades.extend(trades)

            # Be nice to Polygonscan API
            time.sleep(1)

        # Deduplicate by tx hash
        seen_tx = set()
        unique_trades = []
        for t in all_trades:
            if t.get("tx_hash") and t["tx_hash"] not in seen_tx:
                seen_tx.add(t["tx_hash"])
                unique_trades.append(t)

        # Execute
        executed = []
        for trade in unique_trades:
            if self._state["trades_today"] >= self.config.max_daily_trades:
                break
            result = self._execute_trade(trade)
            if result:
                executed.append(result)
                self._state["trades_today"] += 1

        if executed:
            self._save_state()

        return executed

    def _scan_leader(self, address: str,
                     token_to_market: dict[str, tuple[MarketData, int]]) -> list[dict]:
        """Scan one leader wallet for new transfers.

        Returns list of detected trade dicts.
        """
        leader_state = self._state["leaders"].get(address, {})
        last_block = leader_state.get("last_block", self.config.start_block)
        copied_tx = set(leader_state.get("copied_tx_hashes", []))

        # Fetch ERC1155 transfers from CTF exchange
        transfers = self.polygonscan.get_erc1155_transfers(
            address=address,
            contract_address=CTF_EXCHANGE,
            start_block=last_block,
        )

        if not transfers:
            return []

        trades = []
        max_block = last_block

        for tx in transfers:
            tx_hash = tx.get("hash", "")
            if tx_hash in copied_tx:
                continue

            from_addr = tx.get("from", "").lower()
            to_addr = tx.get("to", "").lower()
            token_id = tx.get("tokenID", "")
            token_value = int(tx.get("tokenValue", "0"))
            tx_block = int(tx.get("blockNumber", 0))

            if tx_block > max_block:
                max_block = tx_block

            if not token_id or token_value == 0:
                continue

            # Determine direction
            addr_lower = address.lower()
            if to_addr == addr_lower:
                side = "BUY"
            elif from_addr == addr_lower:
                side = "SELL"
            else:
                continue  # unrelated transfer

            # Resolve market
            market_info = token_to_market.get(token_id)
            if not market_info:
                # Try to resolve via Gamma fallback
                market_info = self._resolve_token_fallback(token_id, token_to_market)
                if market_info:
                    m, idx = market_info
                    token_to_market[token_id] = market_info

            if not market_info:
                logger.debug("Could not resolve token %s for leader %s",
                             token_id[:16], address[:10])
                continue

            market, outcome_idx = market_info
            outcome = market.outcomes[outcome_idx] if outcome_idx < len(market.outcomes) else "?"
            price = market.outcome_prices[outcome_idx] if outcome_idx < len(market.outcome_prices) else 0.5

            # Calculate mirror size
            mirror_value = max(1, int(token_value * self.config.copy_ratio))
            max_by_budget = int(self.config.max_per_trade_usdc / price) if price > 0 else 10
            mirror_size = min(mirror_value, max_by_budget)

            trades.append({
                "leader": address,
                "tx_hash": tx_hash,
                "side": side,
                "outcome": outcome,
                "token_id": token_id,
                "size": mirror_size,
                "price": price,
                "slug": market.slug,
                "question": market.question,
                "block_number": tx_block,
            })

            copied_tx.add(tx_hash)

        # Update leader state
        leader_state["last_block"] = max(last_block, max_block)
        leader_state["copied_tx_hashes"] = list(copied_tx)
        self._state["leaders"][address] = leader_state

        return trades

    def _resolve_token_fallback(
        self, token_id: str,
        cache: dict[str, tuple[MarketData, int]],
    ) -> Optional[tuple[MarketData, int]]:
        """Fallback: try to resolve a token ID by scanning fresh Gamma data.

        Also attempts to parse condition_id from the token_id
        (high 128 bits of the 256-bit token ID).
        """
        # Try extracting condition_id (first 32 hex chars = high 128 bits)
        if len(token_id) >= 32:
            condition_id = "0x" + token_id[:32]
            try:
                market = self.clob.resolve_condition(condition_id)
                if market:
                    for i, tid in enumerate(market.token_ids):
                        if tid == token_id:
                            cache[token_id] = (market, i)
                            return cache[token_id]
                    # Token ID not in resolved market; use index 0
                    cache[token_id] = (market, 0)
                    return cache[token_id]
            except Exception:
                pass

        return None

    def _execute_trade(self, trade: dict) -> Optional[dict]:
        """Execute a mirrored trade via CLOB.

        Respects dry_run config.
        """
        if self.config.dry_run:
            logger.info(
                "[DRY-RUN Copy] %s %s x%d @ $%.4f (%s)",
                trade["side"], trade["outcome"], trade["size"],
                trade["price"], trade["slug"][:30],
            )
            trade["status"] = "dry_run"
            trade["dry_run"] = True
            return trade

        receipt = self.clob.place_order(
            token_id=trade["token_id"],
            side=trade["side"],
            price=trade["price"],
            size=trade["size"],
        )
        if receipt:
            trade["status"] = "executed"
            trade["receipt"] = receipt
            logger.info(
                "Copy %s %s %s x%d @ $%.4f (leader: %s)",
                trade["side"], trade["outcome"], trade["slug"][:30],
                trade["size"], trade["price"], trade["leader"][:10],
            )
            return trade

        logger.warning("Copy trade execution failed: %s", trade.get("slug", "?")[:30])
        return None

    # ── Reporting ──────────────────────────────

    def status_text(self) -> str:
        self._check_reset()
        leaders = self.config.leaders

        lines = [
            "👤 Polymarket 複製交易",
            "狀態：🟢 啟用" if self.is_enabled else "狀態：🔴 停用",
            f"模式：{'🧪 模擬' if self.config.dry_run else '⚡ 真實'}",
            f"今日複製：{self._state['trades_today']}/{self.config.max_daily_trades}",
            f"複製比例：{self.config.copy_ratio:.0%}",
            f"單筆上限：${self.config.max_per_trade_usdc:.2f}",
            "",
        ]

        if leaders:
            lines.append("👤 跟隨錢包：")
            for addr in leaders:
                ls = self._state["leaders"].get(addr, {})
                n = len(ls.get("copied_tx_hashes", []))
                lines.append(f"  {addr[:10]}...{addr[-4:]} ({n} 筆已處理)")
        else:
            lines.append("尚未設定跟隨錢包（POLYCOPY_LEADERS）")

        lines.extend([
            "",
            "/copy on — 啟用複製",
            "/copy off — 停用",
            "/copy leaders — 跟隨錢包列表",
        ])
        return "\n".join(lines)
