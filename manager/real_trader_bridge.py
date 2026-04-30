"""Bridge between AutoTrader analysis signals and real on-chain DEX execution.

Maps stock-like symbols to on-chain token addresses and executes
actual swaps via the TradeExecutor pipeline.
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from onchain.database import (
    Signal, SignalType, Chain, TradeStatus, get_onchain_database, OnchainDatabase
)

logger = logging.getLogger(__name__)

TOKEN_MAP_PATH = Path(__file__).parent.parent / "data" / "token_map.json"


class TokenMapper:
    """Maps stock-like symbols (e.g. 'WETH', 'USDC') to on-chain addresses.

    Persisted to ``data/token_map.json``.
    """

    def __init__(self):
        self._map = self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        try:
            if TOKEN_MAP_PATH.exists():
                return json.loads(TOKEN_MAP_PATH.read_text())
        except Exception:
            logger.exception("Failed to load token map")
        return {}

    def _save(self) -> None:
        try:
            TOKEN_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_MAP_PATH.write_text(json.dumps(self._map, indent=2))
        except Exception:
            logger.exception("Failed to save token map")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, symbol: str) -> Optional[Dict[str, str]]:
        """Get on-chain mapping for a symbol.

        Returns dict with keys: chain, address [, decimals]
        or None if not mapped.
        """
        return self._map.get(symbol.upper())

    def set(self, symbol: str, chain: str, address: str, decimals: int = 18) -> None:
        """Add or update a token mapping."""
        self._map[symbol.upper()] = {
            "chain": chain,
            "address": address,
            "decimals": decimals,
        }
        self._save()
        logger.info(f"Token map: {symbol.upper()} -> {chain}:{address[:10]}...")

    def remove(self, symbol: str) -> bool:
        """Remove a token mapping.  Returns True if it existed."""
        result = self._map.pop(symbol.upper(), None) is not None
        if result:
            self._save()
        return result

    def list_mappings(self) -> Dict[str, Dict[str, Any]]:
        """Return all mappings (copy)."""
        return dict(self._map)

    def to_text(self) -> str:
        """Human-readable mapping summary."""
        if not self._map:
            return "⚠️ 尚未設定任何代幣映射\n\n用 /tokenmap add <代碼> <chain> <address> 新增"

        lines = ["🗺️ 代幣映射表\n"]
        for sym, info in sorted(self._map.items()):
            addr_short = f"{info['address'][:6]}...{info['address'][-4:]}"
            lines.append(f"  {sym:10s} → {info['chain']:10s} {addr_short}")
        lines.append("\n/tokenmap — 檢視")
        lines.append("/tokenmap add <代碼> <chain> <address> — 新增")
        lines.append("/tokenmap remove <代碼> — 移除")
        return "\n".join(lines)


class RealTradeBridge:
    """Executes real on-chain trades from AutoTrader analysis signals.

    Creates ``Signal`` records in the on-chain database and routes them
    through the ``TradeOrchestrator`` pipeline so that real DEX swaps
    are broadcast.
    """

    def __init__(self, orchestrator=None):
        self.orchestrator = orchestrator
        self.token_map = TokenMapper()
        self.db: OnchainDatabase = get_onchain_database()

    def set_orchestrator(self, orchestrator) -> None:
        self.orchestrator = orchestrator

    # ------------------------------------------------------------------
    # BUY
    # ------------------------------------------------------------------

    async def execute_buy(
        self,
        symbol: str,
        amount_eth: float,
        confidence: float,
        reason: str = "",
    ) -> Dict[str, Any]:
        """Execute a real on-chain BUY via the orchestrator pipeline.

        Returns
        -------
        dict with keys: success (bool), error (str | None),
        trade_id (int | None), tx_hash (str | None).
        """
        mapping = self.token_map.get(symbol)
        if not mapping:
            return {"success": False, "error": f"no_mapping:{symbol}"}

        chain = self._parse_chain(mapping["chain"])
        if chain is None:
            return {"success": False, "error": f"unknown_chain:{mapping['chain']}"}

        # Create a signal record in the database for tracking
        signal_data = {
            "signal_type": SignalType.BUY,
            "chain": chain,
            "token_address": mapping["address"],
            "token_symbol": symbol.upper(),
            "token_name": symbol.upper(),
            "base_token": None,
            "confidence_score": min(confidence, 1.0),
            "risk_score": 1.0 - min(confidence, 1.0),
            "suggested_amount_eth": amount_eth,
            "suggested_price": None,
            "stop_loss": None,
            "take_profit": None,
            "signal_data": {"source": "auto_trader_real", "reason": reason},
            "generated_at": datetime.utcnow(),
            "processed": False,
        }
        signal = self.db.add_signal(signal_data)
        if not signal:
            return {"success": False, "error": "failed_to_create_signal"}

        # Route through orchestrator
        if not self.orchestrator:
            return {"success": False, "error": "orchestrator_not_available"}

        executor = self.orchestrator._get_executor(chain)
        if not executor:
            return {"success": False, "error": f"no_executor:{chain}"}

        try:
            trade = await executor.execute_buy(signal)
            if trade:
                logger.info(
                    f"Real BUY {symbol} -> {mapping['address'][:10]}... "
                    f"tx={trade.transaction_hash[:10]}..."
                )
                return {
                    "success": True,
                    "trade_id": trade.id,
                    "tx_hash": trade.transaction_hash,
                    "signal_id": signal.id,
                }
            return {"success": False, "error": "execution_returned_no_trade"}
        except Exception as e:
            logger.exception(f"Real BUY failed for {symbol}")
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # SELL
    # ------------------------------------------------------------------

    async def execute_sell(
        self,
        symbol: str,
        confidence: float,
    ) -> Dict[str, Any]:
        """Execute a real on-chain SELL.

        Finds the most recent completed BUY trade for this token
        and sells the full position.
        """
        mapping = self.token_map.get(symbol)
        if not mapping:
            return {"success": False, "error": f"no_mapping:{symbol}"}

        chain = self._parse_chain(mapping["chain"])
        if chain is None:
            return {"success": False, "error": f"unknown_chain:{mapping['chain']}"}

        if not self.orchestrator:
            return {"success": False, "error": "orchestrator_not_available"}

        executor = self.orchestrator._get_executor(chain)
        if not executor:
            return {"success": False, "error": f"no_executor:{chain}"}

        # Find open long position in the DB
        trade = self._find_open_position(chain, mapping["address"])
        if not trade:
            return {"success": False, "error": f"no_open_position:{symbol}"}

        try:
            ok = await executor.execute_sell(trade)
            if ok:
                logger.info(f"Real SELL {symbol} trade #{trade.id}")
                return {"success": True, "trade_id": trade.id, "tx_hash": trade.transaction_hash}
            return {"success": False, "error": "sell_execution_failed"}
        except Exception as e:
            logger.exception(f"Real SELL failed for {symbol}")
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_chain(self, name: str) -> Optional[Chain]:
        try:
            return Chain(name.lower())
        except ValueError:
            return None

    def _find_open_position(self, chain: Chain, token_address: str):
        """Find the most recent COMPLETED BUY trade for a token."""
        session = self.db.get_session()
        try:
            from onchain.database import Trade
            return (
                session.query(Trade)
                .filter(
                    Trade.chain == chain,
                    Trade.token_address == token_address,
                    Trade.trade_type == SignalType.BUY,
                    Trade.status == TradeStatus.COMPLETED,
                )
                .order_by(Trade.executed_at.desc())
                .first()
            )
        except Exception:
            logger.exception("Failed to find open position")
            return None
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Balance check
    # ------------------------------------------------------------------

    def get_balance(self, symbol: str) -> Optional[float]:
        """Check native-token balance for a symbol's chain (read-only)."""
        mapping = self.token_map.get(symbol)
        if not mapping or not self.orchestrator:
            return None
        chain = self._parse_chain(mapping["chain"])
        if chain is None:
            return None
        web3 = self.orchestrator._get_web3_for_chain(chain)
        if not web3:
            return None
        wallet = self.orchestrator.wallet
        if not wallet or not wallet.wallet_address:
            return None
        try:
            from web3 import Web3
            bal = web3.eth.get_balance(wallet.wallet_address)
            return float(Web3.from_wei(bal, "ether"))
        except Exception:
            logger.exception("Failed to get balance")
            return None
