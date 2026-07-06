"""Copy trading on Polymarket — follows leader wallets and mirrors positions.

Polls the Polymarket Data API (``/trades?maker={address}``) for each leader
wallet to detect new trades with full market metadata (title, slug, price,
side, outcome).  Mirrors trades via the CLOB at a configurable ratio.

This avoids the complex on-chain token ID → market resolution problem
since the Data API returns market data directly.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from bot.polymarket_clob import PolymarketCLOB
from manager.poly_whale_watcher import WhaleWatcher

logger = logging.getLogger(__name__)

DATA_API = "https://data-api.polymarket.com"


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
    def dry_run(self) -> bool:
        return os.environ.get("POLYCOPY_DRY_RUN", "false").lower() == "true"


class CopyTrader:
    """Follows leader wallets via the Polymarket Data API and mirrors trades.

    State persists to ``data/copy_trader_state.json``, tracking
    ``last_tx`` per leader to avoid re-processing trades.
    """

    def __init__(self, clob: Optional[PolymarketCLOB] = None):
        self.config = CopyTraderConfig()
        self.clob = clob or PolymarketCLOB()
        self._state_file = Path(__file__).parent.parent / "data" / "copy_trader_state.json"
        self._slug_token_cache: dict[str, list[str]] = {}  # slug -> CLOB token IDs
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
            "leaders": {},  # {address: {"processed_tx": [...], "last_seen_ts": int, "pnl": float, "trades_copied": int}}
            "blacklist": {},  # {address: {"reason": str, "since": str}}
        }

    # ── Leader quality tracking constants ──────────

    MIN_COPIED_TRADES_FOR_EVAL = 5  # Evaluate leader P&L after this many copied trades
    MAX_LEADER_LOSS_USDC = -5.0      # Blacklist a leader if total copied P&L drops below this

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
        """Poll Data API for each leader and mirror new trades.

        Returns list of executed trade dicts.
        """
        self._check_reset()
        if not self.is_enabled:
            return []

        # Combine manually configured leaders + auto-discovered whales
        leaders = list(self.config.leaders)
        try:
            whale_watcher = WhaleWatcher()
            auto_leaders = whale_watcher.auto_leaders
            for addr in auto_leaders:
                if addr not in leaders:
                    leaders.append(addr)
        except Exception:
            logger.debug("Copy trader: could not load auto leaders", exc_info=True)

        # Filter out blacklisted leaders
        blacklist = self._state.get("blacklist", {})
        leaders = [l for l in leaders if l not in blacklist]
        if blacklist:
            logger.info("Copy trader: %d leader(s) blacklisted, %d remaining",
                        len(blacklist), len(leaders))

        if not leaders:
            logger.warning("Copy trader enabled but no leaders configured or discovered")
            return []

        if self._state["trades_today"] >= self.config.max_daily_trades:
            logger.info("Copy trader: daily trade limit reached")
            return []

        all_trades: list[dict] = []
        for leader_addr in leaders:
            trades = self._scan_leader(leader_addr)
            all_trades.extend(trades)

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

    def _scan_leader(self, address: str) -> list[dict]:
        """Scan one leader wallet for new trades via the Data API.

        Returns list of detected trade dicts with full market metadata.
        """
        import httpx

        leader_state = self._state["leaders"].get(address, {})
        processed_tx = set(leader_state.get("processed_tx", []))

        try:
            resp = httpx.get(
                f"{DATA_API}/trades",
                params={"maker": address, "limit": 50},
                timeout=15, verify=False,
            )
            if resp.status_code != 200:
                logger.warning("Data API returned %d for leader %s",
                               resp.status_code, address[:10])
                return []
            trades_data = resp.json()
        except Exception as e:
            logger.error("Data API fetch failed for leader %s: %s", address[:10], e)
            return []

        if not trades_data or not isinstance(trades_data, list):
            return []

        new_trades = []
        for t in trades_data:
            tx_hash = (t.get("transactionHash") or "").lower()
            if not tx_hash or tx_hash in processed_tx:
                continue

            side = (t.get("side") or "").upper()
            if side not in ("BUY", "SELL"):
                continue

            outcome_index = t.get("outcomeIndex")
            if outcome_index not in (0, 1):
                continue

            raw_price = t.get("price", 0)
            try:
                price = float(raw_price) if raw_price else 0.0
            except (ValueError, TypeError):
                price = 0.0

            raw_size = t.get("size", 0)
            try:
                trade_size = float(raw_size) if raw_size else 0.0
            except (ValueError, TypeError):
                trade_size = 0.0

            if price <= 0 or trade_size <= 0:
                continue

            slug = t.get("slug", "")
            question = t.get("title", "")
            outcome = t.get("outcome", "?")
            timestamp = t.get("timestamp", 0)

            # Resolve CLOB token ID from slug + outcomeIndex
            token_id = self._get_token_for_slug(slug, outcome_index)
            if not token_id:
                logger.debug("Could not resolve token_id for slug=%s", slug[:30])
                continue

            mirror_value = max(1.0, trade_size * self.config.copy_ratio)
            max_by_budget = self.config.max_per_trade_usdc / price if price > 0 else 10.0
            mirror_size = min(mirror_value, max_by_budget)

            new_trades.append({
                "leader": address,
                "tx_hash": tx_hash,
                "side": side,
                "outcome": outcome,
                "token_id": token_id,
                "size": round(mirror_size, 2),
                "price": round(price, 6),
                "slug": slug,
                "question": question,
                "timestamp": timestamp,
            })
            processed_tx.add(tx_hash)

        logger.info("Leader %s: %d new trades", address[:10], len(new_trades))

        # Update leader state
        leader_state["processed_tx"] = list(processed_tx)
        leader_state["leader_lookups"] = leader_state.get("leader_lookups", 0) + 1
        self._state["leaders"][address] = leader_state

        return new_trades

    def _get_token_for_slug(self, slug: str, outcome_index: int) -> Optional[str]:
        """Resolve CLOB token ID from a market slug + outcome index.

        Results are cached in-memory to avoid redundant Gamma API calls.
        """
        if slug not in self._slug_token_cache:
            md = self.clob.resolve_market(slug)
            if md and len(md.token_ids) >= 2:
                self._slug_token_cache[slug] = md.token_ids
            else:
                self._slug_token_cache[slug] = []
        tokens = self._slug_token_cache.get(slug, [])
        if outcome_index < len(tokens):
            return tokens[outcome_index]
        return None

    def _execute_trade(self, trade: dict) -> Optional[dict]:
        """Execute a mirrored trade via CLOB.

        Respects dry_run config. Tracks cost per leader for P&L evaluation.
        """
        leader = trade.get("leader", "")
        trade_cost = trade.get("size", 0) * trade.get("price", 0)

        if self.config.dry_run:
            logger.info(
                "[DRY-RUN Copy] %s %s x%d @ $%.4f (%s)",
                trade["side"], trade["outcome"], trade["size"],
                trade["price"], trade["slug"][:30],
            )
            trade["status"] = "dry_run"
            trade["dry_run"] = True
            self._track_leader_cost(leader, trade_cost)
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
            self._track_leader_cost(leader, trade_cost)
            logger.info(
                "Copy %s %s %s x%d @ $%.4f (leader: %s)",
                trade["side"], trade["outcome"], trade["slug"][:30],
                trade["size"], trade["price"], trade["leader"][:10],
            )
            return trade

        logger.warning("Copy trade execution failed: %s", trade.get("slug", "?")[:30])
        return None

    def _track_leader_cost(self, leader: str, cost: float) -> None:
        """Track cumulative cost per leader and blacklist chronic losers."""
        if not leader:
            return
        ls = self._state["leaders"].setdefault(leader, {})
        ls["pnl"] = ls.get("pnl", 0.0) - cost
        ls["trades_copied"] = ls.get("trades_copied", 0) + 1

        trades_copied = ls["trades_copied"]
        total_pnl = ls["pnl"]
        if trades_copied >= MIN_COPIED_TRADES_FOR_EVAL and total_pnl < MAX_LEADER_LOSS_USDC:
            blacklist = self._state.setdefault("blacklist", {})
            if leader not in blacklist:
                blacklist[leader] = {
                    "reason": f"net loss ${total_pnl:.2f} after {trades_copied} copied trades",
                    "since": datetime.now().isoformat(),
                }
                logger.warning(
                    "Copy trader: BLACKLISTED leader %s — %s",
                    leader[:10], blacklist[leader]["reason"],
                )

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
                n = len(ls.get("processed_tx", []))
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
