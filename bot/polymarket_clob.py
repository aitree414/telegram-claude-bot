"""Polymarket CLOB API client — orderbook, signing, and execution.

Supports L1 (EIP-712 ClobAuthDomain) and L2 (HMAC-SHA256) auth,
EIP-712 typed order signing, and gasless order relay.

Environment variables
--------------------
POLYMARKET_PRIVATE_KEY    — Polygon wallet PK (falls back to PRIVATE_KEY)
POLYMARKET_API_KEY        — Pre-generated API key (skip auth if set)
POLYMARKET_API_SECRET     — Pre-generated API secret (skip auth if set)
POLYMARKET_PASSPHRASE     — Pre-generated API passphrase (skip auth if set)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from eth_account.messages import encode_defunct, encode_typed_data
from web3 import Web3

logger = logging.getLogger(__name__)

# ── DNS bypass for Taiwan ISP poisoning ──────────────────────────
# `clob.polymarket.com` and `gamma-api.polymarket.com` are DNS-
# blocked in Taiwan by court order.  We pre-resolve via Cloudflare
# DNS (1.1.1.1) and monkey-patch socket.getaddrinfo so that all
# httpx / requests calls use the real IP instead of the ISP's
# redirect (182.173.0.181).

_DNS_OVERRIDE: dict[str, str] = {}


def _patch_dns() -> None:
    for domain in ("clob.polymarket.com", "gamma-api.polymarket.com"):
        try:
            out = subprocess.check_output(
                ["nslookup", domain, "1.1.1.1"],
                stderr=subprocess.STDOUT, text=True, timeout=5,
            )
            ips = re.findall(r"Address: (\d+\.\d+\.\d+\.\d+)", out)
            if ips:
                _DNS_OVERRIDE[domain] = ips[0]
        except Exception:
            pass

    if not _DNS_OVERRIDE:
        return  # fall through to system DNS

    import socket as _socket
    _orig = _socket.getaddrinfo

    def _patched(host, port, family=0, type=0, proto=0, flags=0):
        ip = _DNS_OVERRIDE.get(host)
        if ip is not None:
            host = ip
        return _orig(host, port, family, type, proto, flags)

    _socket.getaddrinfo = _patched
    logger.info(f"DNS patched: {', '.join(f'{d} -> {_DNS_OVERRIDE[d]}' for d in _DNS_OVERRIDE)}")


_patch_dns()

# ─────────────────────────────────────────────────────────────────

CLOB_API = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"
POLYGON_RPC = os.environ.get("POLYGON_RPC_URL") or "https://polygon-rpc.com"
CHAIN_ID = 137

# ──────────────────────────────────────────────
# Data types
# ──────────────────────────────────────────────


@dataclass
class MarketData:
    """Parsed Polymarket market with resolved outcome tokens."""
    question: str
    slug: str
    condition_id: str
    outcomes: list[str]
    token_ids: list[str]           # one per outcome
    outcome_prices: list[float]    # approximate price from Gamma
    volume: float
    end_date: str
    active: bool = True


@dataclass
class OrderbookLevel:
    price: float
    size: float


@dataclass
class Orderbook:
    token_id: str
    bids: list[OrderbookLevel] = field(default_factory=list)
    asks: list[OrderbookLevel] = field(default_factory=list)

    @property
    def mid_price(self) -> Optional[float]:
        if self.bids and self.asks:
            return (self.bids[0].price + self.asks[0].price) / 2
        return None

    @property
    def spread(self) -> Optional[float]:
        if self.bids and self.asks:
            return self.asks[0].price - self.bids[0].price
        return None


@dataclass
class Position:
    token_id: str
    side: str            # BUY / SELL
    size: float
    avg_price: float


# ──────────────────────────────────────────────
# Client
# ──────────────────────────────────────────────


class PolymarketCLOB:
    """Low-level CLOB API client.

    Usage
    -----
    >>> clob = PolymarketCLOB()
    >>> book = clob.get_orderbook(token_id)
    >>> receipt = clob.place_order(token_id=..., side="BUY",
    ...                            price=0.65, size=100)
    """

    def __init__(self, private_key: Optional[str] = None,
                 api_key: Optional[str] = None):
        # macOS LibreSSL can't verify Polymarket's cert chain — skip verify
        # event_hooks are populated by _set_auth_headers() once credentials exist
        # Proxy support: POLYMARKET_PROXY env var (e.g. http://127.0.0.1:7890)
        proxy = (os.environ.get("POLYMARKET_PROXY")
                 or os.environ.get("HTTPS_PROXY")
                 or os.environ.get("HTTP_PROXY")
                 or "")
        self._http = httpx.Client(
            base_url=CLOB_API, timeout=15, verify=False,
            event_hooks={"request": []},
            proxy=proxy or None,
        )
        self._w3 = Web3(Web3.HTTPProvider(POLYGON_RPC, request_kwargs={"timeout": 10}))

        # Wallet
        pk = private_key or os.environ.get("POLYMARKET_PRIVATE_KEY") or os.environ.get("PRIVATE_KEY")
        if pk:
            self._account = self._w3.eth.account.from_key(pk)
            self.wallet_address = self._account.address
        else:
            self._account = None
            self.wallet_address = None

        # API credentials (L2 auth)
        self._api_key = api_key or os.environ.get("POLYMARKET_API_KEY") or ""
        self._api_secret = os.environ.get("POLYMARKET_API_SECRET") or ""
        self._api_passphrase = os.environ.get("POLYMARKET_PASSPHRASE") or ""
        self._api_key_ts: int = 0  # timestamp used when deriving key

        if self._api_key and self._api_secret and self._api_passphrase:
            self._set_auth_headers()
        elif self._api_key:
            self._set_auth_headers()
        elif self._account:
            self._derive_api_key()

    # ── Auth ──────────────────────────────────

    @staticmethod
    def _l2_signature(secret: str, method: str, path: str, timestamp: str) -> str:
        """HMAC-SHA256 signature for L2 authenticated requests.

        The secret is URL-safe base64.  The signature output is also
        URL-safe base64 (``+`` → ``-``, ``/`` → ``_``).
        """
        message = timestamp + method + path
        raw_secret = base64.urlsafe_b64decode(secret)
        sig = hmac.new(raw_secret, message.encode(), hashlib.sha256).digest()
        return base64.b64encode(sig).decode().replace("+", "-").replace("/", "_")

    def _set_auth_headers(self) -> None:
        """Attach L2 auth headers to the httpx client via event hook.

        Each request gets POLY_ADDRESS, POLY_SIGNATURE (per-request HMAC),
        POLY_TIMESTAMP, POLY_API_KEY, and POLY_PASSPHRASE.
        """
        if not self._api_key:
            return

        # Remove any previous request hook to avoid duplicates
        self._http._event_hooks["request"] = []

        def _l2_auth_hook(request: httpx.Request) -> None:
            ts = str(int(time.time()))  # seconds (JS: Math.floor(Date.now()/1000))
            path = request.url.path
            method = request.method.upper()
            sig = self._l2_signature(self._api_secret, method, path, ts)
            request.headers["POLY_ADDRESS"] = self.wallet_address or ""
            request.headers["POLY_SIGNATURE"] = sig
            request.headers["POLY_TIMESTAMP"] = ts
            request.headers["POLY_API_KEY"] = self._api_key
            request.headers["POLY_PASSPHRASE"] = self._api_passphrase or ""

        self._http._event_hooks["request"].append(_l2_auth_hook)

    def _derive_api_key(self) -> None:
        """EIP-712 ClobAuthDomain signature → exchange for API key.

        Current Polymarket L1 auth flow (as of 2025/2026):
          - EIP-712 typed data with domain ``ClobAuthDomain``
          - Sent as HTTP headers (``POLY_ADDRESS``, ``POLY_SIGNATURE``,
            ``POLY_TIMESTAMP``, ``POLY_NONCE``)
        """
        if not self._account:
            logger.warning("No wallet private key, running in read-only mode")
            return

        ts = str(int(time.time()))
        nonce = 0

        domain = {"name": "ClobAuthDomain", "version": "1", "chainId": CHAIN_ID}
        types = {
            "ClobAuth": [
                {"name": "address", "type": "address"},
                {"name": "timestamp", "type": "string"},
                {"name": "nonce", "type": "uint256"},
                {"name": "message", "type": "string"},
            ]
        }
        values = {
            "address": self.wallet_address,
            "timestamp": ts,
            "nonce": nonce,
            "message": "This message attests that I control the given wallet",
        }

        try:
            signable = encode_typed_data(domain, types, values)
            signed = self._account.sign_message(signable)
            sig_hex = signed.signature.hex()
        except Exception as e:
            logger.error(f"L1 EIP-712 signing failed: {e}")
            return

        self._api_key_ts = int(ts)

        headers = {
            "POLY_ADDRESS": self.wallet_address,
            "POLY_SIGNATURE": sig_hex,  # already includes 0x prefix
            "POLY_TIMESTAMP": ts,
            "POLY_NONCE": str(nonce),
        }

        # Try derive first (credentials already exist), fall back to create
        # NOTE: use self._http (not standalone httpx) so the DNS patch applies
        for endpoint, method in [
            ("/auth/derive-api-key", "GET"),
            ("/auth/api-key", "POST"),
        ]:
            try:
                if method == "GET":
                    resp = self._http.get(endpoint, headers=headers)
                else:
                    resp = self._http.post(endpoint, headers=headers)

                if resp.status_code == 200:
                    data = resp.json()
                    self._api_key = data.get("apiKey", data.get("api_key", ""))
                    self._api_secret = data.get("secret", "")
                    self._api_passphrase = data.get("passphrase", "")
                    self._set_auth_headers()
                    logger.info(
                        f"Polymarket CLOB authenticated as "
                        f"{self.wallet_address[:10]}..."
                    )
                    return

                if resp.status_code == 404:
                    continue  # try next endpoint

                # For HTTP errors on the last attempt, log but don't retry
                if endpoint == "/auth/api-key":
                    logger.warning(
                        f"CLOB auth failed ({resp.status_code}), "
                        f"running read-only"
                    )

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    continue
                if endpoint == "/auth/api-key":
                    logger.warning(
                        f"CLOB auth failed ({e.response.status_code}), "
                        f"running read-only"
                    )
            except Exception as e:
                if endpoint == "/auth/api-key":
                    logger.warning(f"CLOB auth error: {e}, running read-only")

    def _ensure_auth(self) -> None:
        if not self._api_key and self._account:
            self._derive_api_key()

    # ── Market resolution ─────────────────────

    def resolve_market(self, slug: str) -> Optional[MarketData]:
        """Resolve a human-readable slug to token IDs via Gamma + CLOB."""
        try:
            resp = httpx.get(
                f"{GAMMA_API}/markets",
                params={"slug": slug},
                timeout=10,
                verify=False,
            )
            resp.raise_for_status()
            markets = resp.json()
            if not markets:
                return None
            m = markets[0]
        except Exception as e:
            logger.error(f"Gamma lookup for '{slug}' failed: {e}")
            return None

        outcomes = m.get("outcomes", "[]")
        if isinstance(outcomes, str):
            try:
                outcomes = json.loads(outcomes)
            except Exception:
                return None

        clob_ids = m.get("clobTokenIds", "[]")
        if isinstance(clob_ids, str):
            try:
                clob_ids = json.loads(clob_ids)
            except Exception:
                clob_ids = []

        prices = m.get("outcomePrices", "[]")
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except Exception:
                prices = []

        price_floats = []
        for p in prices:
            try:
                price_floats.append(float(p))
            except (ValueError, TypeError):
                price_floats.append(0.5)

        return MarketData(
            question=m.get("question", ""),
            slug=slug,
            condition_id=m.get("conditionId", ""),
            outcomes=outcomes,
            token_ids=[str(t) for t in clob_ids],
            outcome_prices=price_floats,
            volume=float(m.get("volume", 0)),
            end_date=(m.get("endDate") or "")[:10],
        )

    def resolve_condition(self, condition_id: str) -> Optional[MarketData]:
        """Resolve a condition ID to a market."""
        try:
            resp = httpx.get(
                f"{GAMMA_API}/markets",
                params={"condition_id": condition_id},
                timeout=10,
                verify=False,
            )
            resp.raise_for_status()
            markets = resp.json()
            if not markets:
                return None
            m = markets[0]
        except Exception as e:
            logger.error(f"Gamma lookup for condition '{condition_id[:16]}...' failed: {e}")
            return None

        slug = m.get("slug", "")
        return self.resolve_market(slug)

    # ── Orderbook ─────────────────────────────

    def get_orderbook(self, token_id: str) -> Orderbook:
        """Fetch orderbook for a token."""
        try:
            resp = self._http.get("/book", params={"token_id": token_id})
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"Orderbook fetch failed for {token_id}: {e}")
            return Orderbook(token_id=token_id)

        bids = []
        for b in data.get("bids", []):
            try:
                bids.append(OrderbookLevel(price=float(b.get("price", 0)), size=float(b.get("size", 0))))
            except (ValueError, TypeError):
                continue

        asks = []
        for a in data.get("asks", []):
            try:
                asks.append(OrderbookLevel(price=float(a.get("price", 0)), size=float(a.get("size", 0))))
            except (ValueError, TypeError):
                continue

        # Sort
        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)

        return Orderbook(token_id=token_id, bids=bids, asks=asks)

    # ── Order placement ───────────────────────

    def _build_order_payload(self, token_id: str, side: str,
                             price: float, size: float,
                             expiration_sec: int = 300) -> Optional[dict]:
        """Build and EIP-712 sign a CLOB limit order.

        Polymarket uses a specific typed-data schema:

        Domain:
          name: "Polymarket CLOB"
          version: "1"
          chainId: 137

        Types.Order:
          salt (uint256)
          maker (address)
          signer (address)
          taker (address) — zero address for non-filled
          tokenId (uint256)
          makerAmount (uint256)
          takerAmount (uint256)
          expiration (uint64)
          nonce (uint256)
          feeRateBps (uint16)
          side (bool) — false=BUY, true=SELL
          signatureType (uint8) — 0=EIP712
        """
        if not self._account:
            logger.error("Cannot place order: no wallet configured")
            return None
        self._ensure_auth()

        nonce = int(time.time() * 1000)
        expiration = nonce + (expiration_sec * 1000)
        salt = nonce

        # Maker = the party placing the order
        # For BUY: maker pays takerAmount USDC, receives makerAmount tokens
        # For SELL: maker sends makerAmount tokens, receives takerAmount USDC
        is_sell = side.upper() == "SELL"
        decimals = 10 ** 6  # USDC has 6 decimals, outcome tokens have 6

        if is_sell:
            maker_amount = int(size * decimals)
            taker_amount = int(size * price * decimals)
        else:
            maker_amount = int(size * price * decimals)
            taker_amount = int(size * decimals)

        domain = {
            "name": "Polymarket CLOB",
            "version": "1",
            "chainId": CHAIN_ID,
        }

        types = {
            "Order": [
                {"name": "salt", "type": "uint256"},
                {"name": "maker", "type": "address"},
                {"name": "signer", "type": "address"},
                {"name": "taker", "type": "address"},
                {"name": "tokenId", "type": "uint256"},
                {"name": "makerAmount", "type": "uint256"},
                {"name": "takerAmount", "type": "uint256"},
                {"name": "expiration", "type": "uint64"},
                {"name": "nonce", "type": "uint256"},
                {"name": "feeRateBps", "type": "uint16"},
                {"name": "side", "type": "bool"},
                {"name": "signatureType", "type": "uint8"},
            ]
        }

        values = {
            "salt": salt,
            "maker": self.wallet_address,
            "signer": self.wallet_address,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": int(token_id),
            "makerAmount": maker_amount,
            "takerAmount": taker_amount,
            "expiration": expiration,
            "nonce": nonce,
            "feeRateBps": 0,
            "side": is_sell,
            "signatureType": 0,
        }

        try:
            signable = encode_typed_data(domain, types, values)
            signed = self._account.sign_message(signable)
            signature = signed.signature.hex()
        except Exception as e:
            logger.error(f"EIP-712 signing failed: {e}")
            return None

        return {
            "tokenID": str(token_id),
            "price": str(price),
            "size": str(size),
            "side": side.upper(),
            "signature": signature,  # already includes 0x prefix
            "salt": str(salt),
            "maker": self.wallet_address,
            "signer": self.wallet_address,
            "taker": "0x0000000000000000000000000000000000000000",
            "expiration": str(expiration),
            "nonce": str(nonce),
            "feeRateBps": "0",
            "signatureType": "0",
        }

    def place_order(self, token_id: str, side: str,
                    price: float, size: float,
                    gasless: bool = True) -> Optional[dict]:
        """Place a limit order on the CLOB.

        Parameters
        ----------
        token_id : str    — Polymarket outcome token ID
        side : str        — "BUY" or "SELL"
        price : float     — limit price in USDC (0.00 – 1.00)
        size : float      — number of outcome tokens
        gasless : bool    — use the gasless relay (no gas cost for taker)

        Returns
        -------
        dict with order status, or None on failure.
        """
        payload = self._build_order_payload(token_id, side, price, size)
        if not payload:
            return None

        endpoint = "/order/gasless" if gasless else "/order"
        try:
            resp = self._http.post(endpoint, json=payload)
            resp.raise_for_status()
            result = resp.json()
            logger.info(
                f"Order placed: {side} {size} × {token_id[:10]}... @ ${price:.4f} "
                f"({result.get('status', 'ok')})"
            )
            return result
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                detail = f": {e.response.json()}"
            except Exception:
                detail = f" (status {e.response.status_code})"
            logger.error(f"Order failed{detail}")
            return None
        except Exception as e:
            logger.error(f"Order error: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        try:
            resp = self._http.delete("/order", params={"order_id": order_id})
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Cancel failed for {order_id}: {e}")
            return False

    def cancel_all(self) -> list[str]:
        """Cancel all open orders. Returns list of cancelled IDs."""
        cancelled = []
        orders = self.get_orders()
        for o in orders:
            oid = o.get("id", "")
            if self.cancel_order(oid):
                cancelled.append(oid)
        return cancelled

    # ── Positions & Orders ────────────────────

    def get_positions(self) -> list[Position]:
        """Fetch current positions via Gamma API (data endpoint)."""
        self._ensure_auth()
        if not self.wallet_address:
            return []
        try:
            resp = httpx.get(
                f"{GAMMA_API}/positions",
                params={"user": self.wallet_address, "limit": 100},
                timeout=10,
                verify=False,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"Positions fetch failed: {e}")
            return []

        positions = []
        for p in data if isinstance(data, list) else data.get("data", []):
            try:
                positions.append(Position(
                    token_id=str(p.get("tokenId", p.get("token_id", ""))),
                    side=p.get("side", "BUY"),
                    size=float(p.get("size", 0)),
                    avg_price=float(p.get("avgPrice", p.get("avg_price", 0))),
                ))
            except (ValueError, TypeError):
                continue
        return positions

    def get_orders(self) -> list[dict]:
        """Fetch open orders (L2-authenticated)."""
        self._ensure_auth()
        try:
            resp = self._http.get("/data/orders")
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("data", [])
        except Exception as e:
            logger.warning(f"Orders fetch failed: {e}")
            return []

    # ── Gamma market scan ─────────────────────

    @staticmethod
    def fetch_active_markets(limit: int = 100) -> list[MarketData]:
        """Fetch active binary markets sorted by volume."""
        try:
            resp = httpx.get(
                f"{GAMMA_API}/markets",
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": limit,
                    "order": "volume",
                    "ascending": "false",
                },
                timeout=15,
                verify=False,
            )
            resp.raise_for_status()
            raw = resp.json()
        except Exception as e:
            logger.error(f"Gamma market fetch failed: {e}")
            return []

        result = []
        for m in raw:
            outcomes = m.get("outcomes", "[]")
            prices = m.get("outcomePrices", "[]")
            if isinstance(outcomes, str):
                try:
                    outcomes = json.loads(outcomes)
                    prices = json.loads(prices)
                except Exception:
                    continue
            if len(outcomes) != 2:
                continue  # skip non-binary markets

            clob_ids = m.get("clobTokenIds", "[]")
            if isinstance(clob_ids, str):
                try:
                    clob_ids = json.loads(clob_ids)
                except Exception:
                    clob_ids = []

            price_floats = [float(p) if p else 0.5 for p in prices]

            result.append(MarketData(
                question=m.get("question", ""),
                slug=m.get("slug", ""),
                condition_id=m.get("conditionId", ""),
                outcomes=outcomes,
                token_ids=[str(t) for t in clob_ids],
                outcome_prices=price_floats,
                volume=float(m.get("volume", 0)),
                end_date=(m.get("endDate") or "")[:10],
            ))
        return result
