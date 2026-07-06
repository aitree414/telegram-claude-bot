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
from dotenv import load_dotenv
from eth_account.messages import encode_defunct, encode_typed_data
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from py_clob_client_v2.signer import Signer
from py_clob_client_v2.order_builder.builder import OrderBuilder as V2OrderBuilder
from py_clob_client_v2.clob_types import OrderArgsV2, CreateOrderOptions
from py_clob_client_v2.order_utils.model.order_data_v2 import order_to_json_v2
from py_clob_client_v2.order_utils.model.signature_type_v2 import SignatureTypeV2

_load_env = load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

logger = logging.getLogger(__name__)

# ── DNS bypass for Taiwan ISP poisoning ──────────────────────────
# `clob.polymarket.com` and `gamma-api.polymarket.com` are DNS-
# blocked in Taiwan by court order.  We pre-resolve via Cloudflare
# DNS (1.1.1.1) and monkey-patch socket.getaddrinfo so that all
# httpx / requests calls use the real IP instead of the ISP's
# redirect (182.173.0.181).

_DNS_OVERRIDE: dict[str, str] = {}


def _patch_dns() -> None:
    for domain in ("clob.polymarket.com", "gamma-api.polymarket.com", "data-api.polymarket.com"):
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
        self._w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        # Wallet
        pk = private_key or os.environ.get("POLYMARKET_PRIVATE_KEY") or os.environ.get("PRIVATE_KEY")
        if pk:
            self._account = self._w3.eth.account.from_key(pk)
            self.wallet_address = self._account.address
            self._private_key_str = pk
            self._v2_signer = Signer(pk, CHAIN_ID)
            # Compute proxy wallet address via Exchange V2 (for reference)
            self._proxy_wallet = self._get_proxy_wallet(self.wallet_address)
            # Using EOA signature type — proxy wallet is stuck (owner=address(0))
            self._v2_builder = V2OrderBuilder(
                self._v2_signer,
                signature_type=SignatureTypeV2.EOA,
                funder=self.wallet_address,
            )
        else:
            self._account = None
            self.wallet_address = None
            self._private_key_str = None
            self._v2_signer = None
            self._v2_builder = None

        # API credentials (L2 auth)
        self._api_key = api_key or os.environ.get("POLYMARKET_API_KEY") or ""
        self._api_secret = os.environ.get("POLYMARKET_API_SECRET") or ""
        self._api_passphrase = (os.environ.get("POLYMARKET_PASSPHRASE")
                                or os.environ.get("POLYMARKET_API_PASSPHRASE")
                                or "")
        self._api_key_ts: int = 0  # timestamp used when deriving key

        if self._api_key and self._api_secret and self._api_passphrase:
            self._set_auth_headers()
        elif self._api_key:
            self._set_auth_headers()
        elif self._account:
            self._derive_api_key()

    # ── Auth ──────────────────────────────────

    @staticmethod
    def _l2_signature(secret: str, method: str, path: str, timestamp: str, body: str = "") -> str:
        """HMAC-SHA256 signature for L2 authenticated requests.

        Delegates to the V2 library's build_hmac_signature for correctness.
        The body must have single quotes replaced with double quotes to match
        the canonical API signing format (only matters when body is a string).
        """
        from py_clob_client_v2.signing.hmac import build_hmac_signature
        return build_hmac_signature(secret, timestamp, method, path, body)

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
            # Skip if caller already provided explicit auth headers
            if "POLY_SIGNATURE" in request.headers:
                return
            ts = str(int(time.time()))  # seconds (JS: Math.floor(Date.now()/1000))
            path = request.url.path
            method = request.method.upper()
            # Polymarket V2 requires body in signature for POST/PUT
            body = ""
            if request.content and method in ("POST", "PUT"):
                body_bytes = request.content
                if isinstance(body_bytes, bytes):
                    body = body_bytes.decode("utf-8", errors="replace")
                else:
                    body = str(body_bytes)
            sig = self._l2_signature(self._api_secret, method, path, ts, body)
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

        # CLOB requires 0x prefix on the signature hex
        headers = {
            "POLY_ADDRESS": self.wallet_address,
            "POLY_SIGNATURE": "0x" + sig_hex,
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

    # ── Internal helpers ──────────────────────

    def _get_proxy_wallet(self, user_address: str) -> str:
        """Compute proxy wallet address from Exchange V2."""
        try:
            ex_abi = json.loads('[{"inputs":[{"name":"_addr","type":"address"}],"name":"getProxyWalletAddress","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"}]')
            ex = self._w3.eth.contract(address=Web3.to_checksum_address("0xE111180000d2663C0091e4f400237545B87B996B"), abi=ex_abi)
            proxy = ex.functions.getProxyWalletAddress(Web3.to_checksum_address(user_address)).call()
            logger.info("Proxy wallet: %s", proxy)
            return proxy
        except Exception as e:
            logger.warning("Failed to get proxy wallet, using main wallet: %s", e)
            return user_address

    def _get_tick_size(self, token_id: str) -> str:
        """Fetch tick size via CLOB API."""
        try:
            resp = self._http.get("/tick-size", params={"token_id": token_id})
            resp.raise_for_status()
            ts = resp.json().get("minimum_tick_size", 0.01)
            return str(ts)
        except Exception:
            return "0.01"

    def _get_neg_risk(self, token_id: str) -> bool:
        """Check if token is neg-risk."""
        try:
            resp = self._http.get("/neg-risk", params={"token_id": token_id})
            resp.raise_for_status()
            return resp.json().get("neg_risk", False)
        except Exception:
            return False

    # ── Order placement ───────────────────────

    def _build_order_payload(self, token_id: str, side: str,
                             price: float, size: float) -> Optional[dict]:
        """Build and EIP-712 sign a V2 CLOB limit order via py_clob_client_v2."""
        if not self._v2_builder:
            logger.error("Cannot place order: no wallet configured")
            return None
        self._ensure_auth()

        tick_size = self._get_tick_size(token_id)
        neg_risk = self._get_neg_risk(token_id)

        order_args = OrderArgsV2(
            token_id=token_id,
            price=price,
            size=size,
            side="BUY" if side.upper() == "BUY" else "SELL",
        )
        options = CreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk)

        try:
            signed_order = self._v2_builder.build_order(
                order_args, options, version=2
            )
        except Exception as e:
            logger.error("V2 order build failed: %s", e)
            return None

        return order_to_json_v2(signed_order, self._api_key, "GTC")

    def place_order(self, token_id: str, side: str,
                    price: float, size: float) -> Optional[dict]:
        """Place a V2 limit order on the CLOB.

        Parameters
        ----------
        token_id : str    — Polymarket outcome token ID
        side : str        — "BUY" or "SELL"
        price : float     — limit price in USDC (0.00 – 1.00)
        size : float      — number of outcome tokens

        Returns
        -------
        dict with order status, or None on failure.
        """
        payload = self._build_order_payload(token_id, side, price, size)
        if not payload:
            return None

        # Pre-serialize with compact JSON for deterministic HMAC body signing
        serialized = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

        # Compute L2 auth headers directly (bypass event hook to ensure correct HMAC)
        from py_clob_client_v2.signing.hmac import build_hmac_signature
        ts = str(int(time.time()))
        sig = build_hmac_signature(self._api_secret, ts, "POST", "/order", serialized)
        auth_headers = {
            "Content-Type": "application/json",
            "POLY_ADDRESS": self.wallet_address or "",
            "POLY_SIGNATURE": sig,
            "POLY_TIMESTAMP": ts,
            "POLY_API_KEY": self._api_key,
            "POLY_PASSPHRASE": self._api_passphrase or "",
        }
        logger.debug("POST /order sig=%s body=%s", sig[:20], serialized[:100])
        try:
            sig_type = int(self._v2_builder.signature_type) if self._v2_builder else 2
            resp = self._http.post(
                f"/order?signature_type={sig_type}",
                content=serialized,
                headers=auth_headers,
            )
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

    # ── Balance ──────────────────────────────

    def get_balance(self, asset_type: str = "COLLATERAL") -> str:
        """Query CLOB balance for the proxy wallet (L2-authenticated)."""
        self._ensure_auth()
        try:
            sig_type = int(self._v2_builder.signature_type) if self._v2_builder else 2
            resp = self._http.get("/balance-allowance",
                params={"signature_type": str(sig_type), "asset_type": asset_type})
            resp.raise_for_status()
            data = resp.json()
            return data.get("balance", "0")
        except Exception as e:
            logger.warning("Balance fetch failed: %s", e)
            return "0"

    def update_balance(self, asset_type: str = "COLLATERAL") -> bool:
        """Trigger CLOB to re-scan on-chain balance (L2-authenticated)."""
        self._ensure_auth()
        try:
            sig_type = int(self._v2_builder.signature_type) if self._v2_builder else 2
            resp = self._http.get("/balance-allowance/update",
                params={"signature_type": str(sig_type), "asset_type": asset_type})
            return resp.status_code == 200
        except Exception as e:
            logger.warning("Balance update failed: %s", e)
            return False

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
