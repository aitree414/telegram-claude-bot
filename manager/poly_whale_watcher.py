"""Auto-discovers active Polymarket whale wallets by scanning on-chain activity.

Strategy
--------
1. Query Polygon RPC for recent ERC1155 TransferSingle / TransferBatch events
   on Polymarket's CTF_EXCHANGE contract
2. Extract all unique ``from`` / ``to`` addresses
3. Rank by frequency (most active = highest score)
4. Save top 5 wallets as auto-leaders for copy trading

No manual configuration needed. The file ``data/poly_whales.json``
is shared with ``CopyTrader``.
"""

from __future__ import annotations

import json
import logging
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from web3 import Web3
from web3.types import LogReceipt

logger = logging.getLogger(__name__)

# Polymarket contracts on Polygon mainnet
CTF_EXCHANGE = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045"
NEG_RISK_ADAPTER = "0xC5d563A36AE78145C45a50134d48A1215220f80a"

# Known Polymarket contracts to exclude from ranking (they are not end-user traders)
KNOWN_CONTRACTS = {
    "0x4d97dcd97ec945f40cf65f87097ace5ea0476045",  # ConditionalTokens
    "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e",  # Exchange v1
    "0xe111180000d2663c0091e4f400237545b87b996b",  # Exchange v2
    "0xc5d563a36ae78145c45a50134d48a1215220f80a",  # NegRiskExchange / adapter
    "0xd91e80cf2e7be2e162c6513ced06f1dd0da35296",  # NegRiskAdapter (alt)
    "0x0000000000000000000000000000000000000000",  # zero address (mints/burns)
}

# ERC1155 event signatures
TRANSFER_SINGLE_TOPIC = "0x" + Web3.keccak(
    text="TransferSingle(address,address,address,uint256,uint256)"
).hex()
TRANSFER_BATCH_TOPIC = "0x" + Web3.keccak(
    text="TransferBatch(address,address,address,uint256[],uint256[])"
).hex()

WHALES_FILE = Path(__file__).parent.parent / "data" / "poly_whales.json"
TOP_WHALES_LIMIT = 5
DEFAULT_BLOCKS = 150  # ~5 minutes of Polygon blocks (CTF is very active)
MIN_TRADES_FOR_LEADER = 50  # Minimum trades required before a wallet can be a leader


def _decode_addr(topic: bytes) -> str:
    """Decode a 32-byte indexed event topic to a checksummed address."""
    return Web3.to_checksum_address(topic[-20:]).lower()


class WhaleWatcher:
    """Discovers active Polymarket wallets by scanning on-chain transfers.

    Usage
    -----
    >>> watcher = WhaleWatcher()
    >>> whales = watcher.discover_sync()
    >>> print(whales)
    """

    def __init__(self, rpc_url: Optional[str] = None):
        url = rpc_url or os.environ.get("POLYGON_RPC_URL", "https://polygon.drpc.org")
        self.w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 30}))
        self._state_file = WHALES_FILE

    # ── Public API ───────────────────────────────

    def discover_sync(self) -> list[dict]:
        """Run one full discovery cycle (synchronous).

        Returns the updated list of whale wallet dicts.
        """
        logger.info("WhaleWatcher: starting discovery cycle")

        try:
            transfers = self._fetch_transfers()
            if not transfers:
                logger.warning("WhaleWatcher: no transfers fetched")
                return self._load_whales()

            logger.info("WhaleWatcher: fetched %d transfers", len(transfers))

            # Extract and count wallet addresses
            address_counter: Counter = Counter()
            address_volumes: dict[str, float] = defaultdict(float)

            for tx in transfers:
                from_addr = tx.get("from", "").lower()
                to_addr = tx.get("to", "").lower()

                if from_addr and from_addr != "0x0000000000000000000000000000000000000000":
                    address_counter[from_addr] += 1

                if to_addr and to_addr != "0x0000000000000000000000000000000000000000":
                    address_counter[to_addr] += 1

                try:
                    val = int(tx.get("tokenValue", "0"))
                    if from_addr in address_counter:
                        address_volumes[from_addr] += val / 1e6
                    if to_addr in address_counter:
                        address_volumes[to_addr] += val / 1e6
                except (ValueError, TypeError):
                    pass

            if not address_counter:
                logger.warning("WhaleWatcher: no valid addresses found")
                return self._load_whales()

            ranked = self._rank_wallets(address_counter, address_volumes)
            top_whales = ranked[:TOP_WHALES_LIMIT]

            self._save_whales(top_whales)
            logger.info(
                "WhaleWatcher: found %d unique wallets, saved top %d",
                len(ranked), len(top_whales),
            )
            return top_whales

        except Exception as e:
            logger.exception("WhaleWatcher: discovery failed: %s", e)
            return self._load_whales()

    async def discover(self) -> list[dict]:
        """Async wrapper — runs discovery in a thread pool."""
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.discover_sync)

    @property
    def auto_leaders(self) -> list[str]:
        """Return the list of auto-discovered leader wallet addresses."""
        whales = self._load_whales()
        return [w["address"] for w in whales if w.get("address")]

    # ── RPC event fetching ───────────────────────

    def _fetch_transfers(self) -> list[dict]:
        """Query Polygon RPC for recent ERC1155 Transfer events.

        Returns a list of dicts with keys matching the Polygonscan format
        (from, to, tokenID, tokenValue) so the caller doesn't need to change.
        """
        latest = self.w3.eth.block_number
        from_block = max(0, latest - DEFAULT_BLOCKS)

        # Query TransferSingle and TransferBatch events
        logs: list[LogReceipt] = []
        for event_topic in (TRANSFER_SINGLE_TOPIC, TRANSFER_BATCH_TOPIC):
            try:
                batch = self.w3.eth.get_logs({
                    "address": Web3.to_checksum_address(CTF_EXCHANGE),
                    "fromBlock": from_block,
                    "toBlock": latest,
                    "topics": [event_topic],
                })
                logs.extend(batch)
            except Exception:
                logger.exception(
                    "WhaleWatcher: RPC get_logs failed for %s",
                    event_topic[:20],
                )

        if not logs:
            return []

        # Parse events into transfer dicts
        transfers: list[dict[str, Any]] = []
        for log_entry in logs:
            topics = log_entry.get("topics", [])
            if len(topics) < 4:
                continue

            from_addr = _decode_addr(topics[2])
            to_addr = _decode_addr(topics[3])

            # Decode tokenValue from data
            # TransferSingle data = abi.encode(tokenId, tokenValue) = 64 bytes
            # TransferBatch data = abi.encode(ids[], values[]) — variable length
            data_bytes = log_entry.get("data", b"") or b""
            token_value = 0
            if len(data_bytes) >= 64:
                # Last 32 bytes = tokenValue (for TransferSingle)
                token_value = int.from_bytes(data_bytes[32:64], "big")
            elif len(data_bytes) >= 32:
                token_value = int.from_bytes(data_bytes[:32], "big")

            # For TransferSingle, tokenID is also in data (first 32 bytes)
            # For simplicity, use a placeholder tokenID
            tx_hash = log_entry.get("transactionHash", b"").hex()

            transfers.append({
                "from": from_addr,
                "to": to_addr,
                "tokenValue": str(token_value),
                "hash": tx_hash,
            })

        return transfers

    # ── Ranking ──────────────────────────────────

    def _rank_wallets(
        self,
        address_counter: Counter,
        address_volumes: dict[str, float],
    ) -> list[dict]:
        """Score and rank wallets by trading activity.

        Scoring:
          score = log(trades) * 0.5 + log(volume + 1) * 0.5
        """
        ranked = []
        for addr, count in address_counter.most_common(200):
            # Skip known contracts
            addr_lower = addr.lower()
            if addr_lower in KNOWN_CONTRACTS:
                continue
            volume = address_volumes.get(addr, 0)
            trades_score = math.log(count + 1) * 0.5
            vol_score = math.log(volume + 1) * 0.5
            score = trades_score + vol_score

            ranked.append({
                "address": addr,
                "score": round(score, 2),
                "trades": count,
                "total_volume": round(volume, 2),
                "discovered_at": datetime.now(timezone.utc).isoformat(),
            })

        ranked.sort(key=lambda w: w["score"], reverse=True)
        # Filter: only promote wallets with enough trade history
        return [w for w in ranked if w["trades"] >= MIN_TRADES_FOR_LEADER]

    # ── Persistence ──────────────────────────────

    def _load_whales(self) -> list[dict]:
        try:
            if self._state_file.exists():
                return json.loads(self._state_file.read_text())
        except Exception:
            logger.exception("WhaleWatcher: failed to load whales")
        return []

    def _save_whales(self, whales: list[dict]) -> None:
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(
                json.dumps(whales, indent=2, default=str)
            )
        except Exception:
            logger.exception("WhaleWatcher: failed to save whales")
