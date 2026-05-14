"""Polygonscan API client for tracking wallet on-chain activity.

Used by CopyTrader to detect Polymarket ERC1155 transfers
from tracked leader wallets.

API: https://docs.polygonscan.com/
Free tier: 5 calls/sec, 100k calls/day.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.polygonscan.com/api"


class PolygonscanClient:
    """Thin wrapper around the Polygonscan API.

    Only implements the endpoints needed for copy trading:
    ERC1155 token transfers and current block number.
    """

    def __init__(self, api_key: str, http_client: Optional[httpx.Client] = None):
        self.api_key = api_key
        self._http = http_client or httpx.Client(timeout=15)

    def get_erc1155_transfers(
        self,
        address: str,
        contract_address: str = "",
        start_block: int = 0,
        end_block: int = 99_999_999,
    ) -> list[dict]:
        """Fetch ERC1155 token transfers for a wallet.

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
                    "Polygonscan ERC1155 API returned non-OK for %s: %s",
                    address[:10], data.get("message", "?"),
                )
                return []
            return data.get("result", [])
        except Exception as e:
            logger.warning("Polygonscan ERC1155 query failed for %s: %s",
                           address[:10], e)
            return []

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
        """Get the latest Polygon block number via the proxy API."""
        try:
            resp = self._http.get(BASE_URL, params={
                "module": "proxy",
                "action": "eth_blockNumber",
                "apikey": self.api_key,
            })
            resp.raise_for_status()
            data = resp.json()
            if data.get("result"):
                return int(data["result"], 16)
        except Exception as e:
            logger.warning("Polygonscan block number query failed: %s", e)
        return None
