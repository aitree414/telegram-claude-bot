"""Polygonscan API client for tracking wallet on-chain activity.

Used by CopyTrader to detect Polymarket ERC1155 transfers
from tracked leader wallets.

API: https://docs.polygonscan.com/
Free tier: 5 calls/sec, 100k calls/day.

NOTE: Polygonscan V1 API is deprecated (returns NOTOK).
This module falls back to Polygon RPC for ERC1155 transfer data.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx
from web3 import Web3
from web3.types import LogReceipt

logger = logging.getLogger(__name__)

BASE_URL = "https://api.polygonscan.com/api"

# ERC1155 event signatures (0x-prefixed)
TRANSFER_SINGLE_TOPIC = "0x" + Web3.keccak(
    text="TransferSingle(address,address,address,uint256,uint256)"
).hex()
TRANSFER_BATCH_TOPIC = "0x" + Web3.keccak(
    text="TransferBatch(address,address,address,uint256[],uint256[])"
).hex()

# Polymarket CTF_EXCHANGE on Polygon mainnet
CTF_EXCHANGE = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045"
DEFAULT_RPC_URL = "https://polygon.drpc.org"
TRANSFER_LOOKBACK_BLOCKS = 150  # ~5 min (CTF is very active, avoid RPC overload)


def _pad32(addr: str) -> str:
    """Pad a 20-byte hex address to 32 bytes (64 hex chars + 0x)."""
    clean = addr.lower().removeprefix("0x")
    return "0x" + "0" * (64 - len(clean)) + clean


def _decode_addr(topic: bytes) -> str:
    """Decode a 32-byte indexed event topic to a checksummed address."""
    return Web3.to_checksum_address(topic[-20:]).lower()


class PolygonscanClient:
    """Thin wrapper around the Polygonscan API (with RPC fallback).

    Polygonscan V1 is deprecated. ERC1155 queries transparently fall
    back to the Polygon RPC via web3.py.
    """

    def __init__(self, api_key: str = "",
                 rpc_url: str = "",
                 http_client: Optional[httpx.Client] = None):
        self.api_key = api_key
        self._http = http_client or httpx.Client(timeout=15)
        rpc = rpc_url or DEFAULT_RPC_URL
        self._w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 30}))

    def get_erc1155_transfers(
        self,
        address: str,
        contract_address: str = "",
        start_block: int = 0,
        end_block: int = 99_999_999,
    ) -> list[dict]:
        """Fetch ERC1155 token transfers for a wallet.

        First tries Polygonscan V1 API (deprecated, likely fails).
        Falls back to Polygon RPC event queries.

        Parameters
        ----------
        address : str
            Wallet address to query.
        contract_address : str
            Optional. Filter to a specific contract.
        start_block : int
            Earliest block to include.
        end_block : int
            Latest block to include (defaults to near-infinite).

        Returns
        -------
        list of transfer dicts, each with keys:
            blockNumber, timeStamp, hash, nonce, blockHash,
            from, to, tokenID, tokenValue (amount), tokenName, tokenSymbol
        """
        # Try Polygonscan V1 first (will likely fail but worth a shot)
        result = self._try_polygonscan(address, contract_address, start_block, end_block)
        if result:
            return result

        # Fall back to RPC
        return self._get_erc1155_transfers_rpc(
            address, contract_address, start_block, end_block,
        )

    def _try_polygonscan(
        self, address: str, contract_address: str,
        start_block: int, end_block: int,
    ) -> list[dict]:
        params: dict[str, Any] = {
            "module": "account",
            "action": "tokennfttx",
            "address": address,
            "startblock": start_block,
            "endblock": end_block,
            "sort": "asc",
            "apikey": self.api_key,
        }
        if contract_address:
            params["contractaddress"] = contract_address

        try:
            resp = self._http.get(BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "1":
                logger.debug(
                    "Polygonscan V1 returned non-OK for %s: %s",
                    address[:10], data.get("message", "?"),
                )
                return []
            return data.get("result", [])
        except Exception as e:
            logger.debug("Polygonscan V1 query failed for %s: %s", address[:10], e)
            return []

    def _get_erc1155_transfers_rpc(
        self, address: str, contract_address: str,
        start_block: int, end_block: int,
    ) -> list[dict]:
        """Fetch ERC1155 transfers via Polygon RPC event logs.

        Uses topic filtering (indexed from/to) so the RPC can efficiently
        find matching events without scanning all contract activity.
        """
        addr_checksummed = Web3.to_checksum_address(address)
        addr_padded = _pad32(address)

        latest = self._w3.eth.block_number
        from_block = max(start_block, latest - TRANSFER_LOOKBACK_BLOCKS)
        to_block = min(end_block, latest)

        if from_block >= to_block:
            return []

        target_contract = Web3.to_checksum_address(
            contract_address if contract_address else CTF_EXCHANGE
        )

        transfers: list[dict[str, Any]] = []
        seen_tx: set[str] = set()

        # Query 1: from=address (topics[2] == address)
        # Query 2: to=address (topics[3] == address)
        for topic_position in (2, 3):
            topics_list = [TRANSFER_SINGLE_TOPIC, None, None, None]
            if len(topics_list) > topic_position:
                topics_list[topic_position] = addr_padded

            try:
                logs: list[LogReceipt] = self._w3.eth.get_logs({
                    "address": target_contract,
                    "fromBlock": from_block,
                    "toBlock": to_block,
                    "topics": topics_list,
                })
            except Exception:
                logger.exception(
                    "RPC get_logs for %s topic[%d] failed", address[:10], topic_position,
                )
                continue

            for log_entry in logs:
                topics = log_entry.get("topics", [])
                if len(topics) < 4:
                    continue

                tx_hash = log_entry.get("transactionHash", b"").hex()
                if tx_hash in seen_tx:
                    continue
                seen_tx.add(tx_hash)

                from_addr = _decode_addr(topics[2])
                to_addr = _decode_addr(topics[3])

                # Decode tokenValue from data (last 32 bytes)
                data_bytes = log_entry.get("data", b"") or b""
                token_value = 0
                if len(data_bytes) >= 64:
                    token_value = int.from_bytes(data_bytes[32:64], "big")

                # Extract tokenId (first 32 bytes)
                token_id = ""
                if len(data_bytes) >= 32:
                    token_id = hex(int.from_bytes(data_bytes[:32], "big"))

                block_num = log_entry.get("blockNumber", 0)

                transfers.append({
                    "from": from_addr,
                    "to": to_addr,
                    "tokenID": token_id,
                    "tokenValue": str(token_value),
                    "hash": tx_hash,
                    "blockNumber": str(block_num),
                })

        return transfers

    def get_erc20_transfers(
        self,
        address: str,
        contract_address: str = "",
        start_block: int = 0,
    ) -> list[dict]:
        """Fetch ERC20 token transfers for a wallet.

        Used primarily for detecting USDC movements.
        """
        params: dict[str, Any] = {
            "module": "account",
            "action": "tokentx",
            "address": address,
            "startblock": start_block,
            "endblock": 99_999_999,
            "sort": "asc",
            "apikey": self.api_key,
        }
        if contract_address:
            params["contractaddress"] = contract_address

        try:
            resp = self._http.get(BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "1":
                return []
            return data.get("result", [])
        except Exception as e:
            logger.warning("Polygonscan ERC20 query failed for %s: %s",
                           address[:10], e)
            return []

    def get_block_number(self) -> Optional[int]:
        """Get the latest Polygon block number via the RPC."""
        try:
            return self._w3.eth.block_number
        except Exception as e:
            logger.warning("RPC block number query failed: %s", e)
        return None
