"""Trade execution module for onchain sniper functionality.

This module executes trades based on generated signals, managing
order placement, transaction broadcasting, and trade monitoring.
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Any, Tuple, List
from datetime import datetime
from web3 import Web3
from web3.exceptions import TimeExhausted, ContractLogicError

from bot.config_web3 import get_web3_config
from .database import (
    Trade, TradeStatus, Signal, Order, OrderStatus, OrderType,
    ExecutionLog, Chain, SignalType, get_onchain_database,
    OnchainDatabase
)
from .wallet_manager import WalletManager
from .transaction_builder import TransactionBuilder
from .risk_manager import RiskManager

logger = logging.getLogger(__name__)


class TradeExecutionError(Exception):
    """Exception raised when trade execution fails."""
    def __init__(self, message: str, tx_hash: Optional[str] = None):
        self.tx_hash = tx_hash
        super().__init__(message)


class TradeExecutor:
    """Core trade execution engine.

    Handles all aspects of trade execution including:
    - Building and broadcasting swap transactions
    - Token approval management
    - Transaction monitoring and confirmation
    - Error handling and retries
    - Trade status tracking
    """

    def __init__(self, web3: Web3, chain: Chain, config=None, database=None):
        """Initialize trade executor.

        Args:
            web3: Web3 instance for the target chain
            chain: Target blockchain chain
            config: Web3Config instance
            database: OnchainDatabase instance
        """
        self.web3 = web3
        self.chain = chain
        self.config = config or get_web3_config()
        self.database = database or get_onchain_database()
        self.wallet = WalletManager(self.config)
        self.tx_builder = TransactionBuilder(web3, self.config)
        self.risk_manager = RiskManager(self.config, self.database)

        # Transaction receipt cache: tx_hash -> receipt
        self._receipt_cache: Dict[str, Dict] = {}

        # Execution stats
        self.stats = {
            'total_executed': 0,
            'successful': 0,
            'failed': 0,
            'total_gas_cost_eth': 0.0,
        }

        logger.info(f"Trade executor initialized for {chain}")

    # ==================== Main Execution ====================

    async def execute_buy(
        self,
        signal: Signal,
        dex_name: str = 'uniswap_v2',
        gas_strategy: str = 'balanced',
    ) -> Optional[Trade]:
        """Execute a buy trade based on a signal.

        Args:
            signal: Trading signal
            dex_name: DEX to use for execution
            gas_strategy: Gas price strategy

        Returns:
            Trade object if execution started, None if failed
        """
        token_address = signal.token_address
        amount_eth = signal.suggested_amount_eth or self.config.min_trade_eth

        if not token_address:
            self._log_execution(signal.id, 'execute_buy', 'failed',
                                message="No token address in signal")
            return None

        logger.info(
            f"Executing buy: {amount_eth:.4f} ETH -> "
            f"{token_address[:10]}... on {self.chain}"
        )

        # Build the swap transaction (ETH -> Token)
        weth_address = self._get_weth_address()
        if not weth_address:
            self._log_execution(signal.id, 'execute_buy', 'failed',
                                message="Failed to get WETH address")
            return None

        try:
            # Build and prepare transaction
            prepared = self.tx_builder.prepare_swap_transaction(
                token_in=weth_address,
                token_out=token_address,
                amount_in=amount_eth,
                dex_name=dex_name,
                gas_strategy=gas_strategy,
                simulate=True,
            )

            if prepared['status'] == 'simulation_failed':
                self._log_execution(signal.id, 'execute_buy', 'failed',
                                    message=f"Simulation failed: {prepared.get('simulation_error')}")
                return None

            # Broadcast transaction
            tx_hash = self._broadcast_transaction(prepared)

            if not tx_hash:
                self._log_execution(signal.id, 'execute_buy', 'failed',
                                    message="Transaction broadcast failed")
                return None

            # Wait for confirmation
            receipt = self._wait_for_confirmation(tx_hash)

            if not receipt:
                self._log_execution(signal.id, 'execute_buy', 'failed',
                                    message="Transaction confirmation timeout",
                                    tx_hash=tx_hash)
                return None

            # Process receipt and create trade record
            trade = self._process_buy_receipt(
                signal, receipt, amount_eth, prepared
            )

            if trade:
                self._log_execution(signal.id, 'execute_buy', 'success',
                                    message=f"Buy executed: tx={tx_hash[:10]}...",
                                    tx_hash=tx_hash)
                self.stats['successful'] += 1
            else:
                self._log_execution(signal.id, 'execute_buy', 'failed',
                                    message="Failed to create trade record",
                                    tx_hash=tx_hash)
                self.stats['failed'] += 1

            return trade

        except TradeExecutionError as e:
            self._log_execution(signal.id, 'execute_buy', 'failed',
                                message=str(e), tx_hash=e.tx_hash)
            self.stats['failed'] += 1
            return None

        except Exception as e:
            self._log_execution(signal.id, 'execute_buy', 'failed',
                                message=f"Unexpected error: {e}")
            logger.error(f"Buy execution error: {e}")
            self.stats['failed'] += 1
            return None

    async def execute_sell(
        self,
        trade: Trade,
        dex_name: str = 'uniswap_v2',
        gas_strategy: str = 'balanced',
    ) -> bool:
        """Execute a sell trade (close an existing position).

        Args:
            trade: Active trade to close
            dex_name: DEX to use
            gas_strategy: Gas strategy

        Returns:
            True if sell executed successfully
        """
        token_address = trade.token_address
        amount_token = trade.amount_token

        if not token_address:
            logger.error(f"Trade {trade.id} has no token address")
            return False

        if amount_token <= 0:
            logger.error(f"Trade {trade.id} has no token amount to sell")
            return False

        logger.info(
            f"Executing sell: {amount_token:.6f} tokens "
            f"{token_address[:10]}... -> ETH on {self.chain}"
        )

        weth_address = self._get_weth_address()
        if not weth_address:
            self._log_execution(None, 'execute_sell', 'failed',
                                message="Failed to get WETH address",
                                trade_id=trade.id)
            return False

        router_address = self._get_router_for_dex(dex_name)
        if not router_address:
            self._log_execution(None, 'execute_sell', 'failed',
                                message=f"No router for {dex_name}",
                                trade_id=trade.id)
            return False

        try:
            # Step 1: Ensure token is approved for DEX router
            amount_wei = int(amount_token * 10**18)
            approved = await self.ensure_approval(token_address, router_address, amount_wei)

            if not approved:
                self._log_execution(None, 'execute_sell', 'failed',
                                    message="Token approval failed",
                                    trade_id=trade.id)
                return False

            # Step 2: Build swap transaction (Token -> WETH)
            prepared = self.tx_builder.prepare_swap_transaction(
                token_in=token_address,
                token_out=weth_address,
                amount_in=amount_token,
                dex_name=dex_name,
                gas_strategy=gas_strategy,
                simulate=True,
            )

            if prepared['status'] == 'simulation_failed':
                self._log_execution(None, 'execute_sell', 'failed',
                                    message=f"Sell simulation failed: {prepared.get('simulation_error')}",
                                    trade_id=trade.id)
                return False

            # Step 3: Broadcast transaction
            tx_hash = self._broadcast_transaction(prepared)

            if not tx_hash:
                self._log_execution(None, 'execute_sell', 'failed',
                                    message="Sell broadcast failed",
                                    trade_id=trade.id)
                return False

            # Step 4: Wait for confirmation
            receipt = self._wait_for_confirmation(tx_hash)

            if not receipt:
                self._log_execution(None, 'execute_sell', 'failed',
                                    message="Sell confirmation timeout",
                                    tx_hash=tx_hash, trade_id=trade.id)
                return False

            # Step 5: Update trade status
            status_success = receipt.get('status') == 1
            new_status = TradeStatus.COMPLETED if status_success else TradeStatus.FAILED

            gas_used = receipt.get('gas_used', 0)
            tx_data = prepared.get('transaction', {})
            gas_price_wei = tx_data.get('gasPrice', 0)

            self.database.update_trade_status(
                trade.id,
                new_status,
                transaction_hash=tx_hash,
                gas_used=gas_used,
                gas_price_gwei=float(Web3.from_wei(gas_price_wei, 'gwei')) if gas_price_wei else 0,
                transaction_cost_eth=float(Web3.from_wei(gas_used * gas_price_wei, 'ether')),
            )

            self._log_execution(None, 'execute_sell',
                                'success' if status_success else 'failed',
                                message=f"Sell {'completed' if status_success else 'failed'}: tx={tx_hash[:10]}...",
                                tx_hash=tx_hash, trade_id=trade.id)

            if status_success:
                self.stats['successful'] += 1
            else:
                self.stats['failed'] += 1

            return status_success

        except Exception as e:
            self._log_execution(None, 'execute_sell', 'failed',
                                message=f"Sell error: {e}",
                                trade_id=trade.id)
            logger.error(f"Sell execution error for trade {trade.id}: {e}")
            self.stats['failed'] += 1
            return False

    # ==================== Token Approval ====================

    async def ensure_approval(
        self,
        token_address: str,
        spender: str,
        amount_wei: int,
    ) -> bool:
        """Ensure token is approved for DEX router.

        Args:
            token_address: Token contract address
            spender: Spender address (DEX router)
            amount_wei: Required approval amount

        Returns:
            True if approved (or already approved)
        """
        try:
            prepared = self.tx_builder.check_and_prepare_approval(
                token_address, spender, amount_wei
            )

            if prepared is None:
                # Already approved
                return True

            if prepared['status'] == 'simulation_failed':
                logger.warning(f"Approval simulation failed for {token_address[:10]}...")
                return False

            # Broadcast approval transaction
            tx_hash = self._broadcast_transaction(prepared)

            if not tx_hash:
                logger.error("Approval broadcast failed")
                return False

            # Wait for confirmation
            receipt = self._wait_for_confirmation(tx_hash)

            if receipt and receipt.get('status') == 1:
                logger.info(f"Token {token_address[:10]}... approved for {spender[:10]}...")
                return True

            logger.warning(f"Approval transaction failed: {tx_hash[:10]}...")
            return False

        except Exception as e:
            logger.error(f"Approval failed: {e}")
            return False

    # ==================== Transaction Broadcasting ====================

    def _broadcast_transaction(self, prepared: Dict[str, Any]) -> Optional[str]:
        """Broadcast a signed transaction to the network.

        Args:
            prepared: Prepared transaction from TransactionBuilder

        Returns:
            Transaction hash string or None on failure
        """
        transaction = prepared.get('transaction')
        if not transaction:
            logger.error("No transaction data in prepared result")
            return None

        try:
            # Sign the transaction
            signed = self.wallet.sign_transaction(transaction)

            if not signed:
                logger.error("Failed to sign transaction")
                return None

            # Broadcast raw transaction
            tx_hash = self.web3.eth.send_raw_transaction(
                signed['rawTransaction']
            )

            if isinstance(tx_hash, bytes):
                tx_hash = tx_hash.hex()

            logger.info(f"Transaction broadcast: {tx_hash[:20]}...")
            self.stats['total_executed'] += 1

            return tx_hash

        except Exception as e:
            logger.error(f"Failed to broadcast transaction: {e}")
            return None

    def _wait_for_confirmation(
        self,
        tx_hash: str,
        timeout: int = 300,
        poll_interval: int = 3
    ) -> Optional[Dict]:
        """Wait for transaction confirmation.

        Args:
            tx_hash: Transaction hash
            timeout: Max wait time in seconds
            poll_interval: Poll interval in seconds

        Returns:
            Transaction receipt or None on timeout
        """
        logger.debug(f"Waiting for confirmation: {tx_hash[:20]}...")

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                receipt = self.web3.eth.get_transaction_receipt(tx_hash)

                if receipt is not None:
                    # Check confirmation blocks
                    current_block = self.web3.eth.block_number
                    receipt_block = receipt.get('blockNumber', 0)
                    confirmations = current_block - receipt_block

                    if confirmations >= self.config.confirmation_blocks:
                        status = 'success' if receipt.get('status') == 1 else 'failed'
                        logger.info(
                            f"Transaction {tx_hash[:20]}... confirmed: "
                            f"{status} ({confirmations} confirmations)"
                        )

                        # Cache receipt
                        self._receipt_cache[tx_hash] = receipt
                        return {
                            'hash': tx_hash,
                            'block_number': receipt.get('blockNumber'),
                            'gas_used': receipt.get('gasUsed', 0),
                            'status': receipt.get('status'),
                            'confirmations': confirmations,
                            'receipt': receipt,
                        }

            except Exception:
                pass

            # Sleep before next poll
            time.sleep(poll_interval)

        logger.warning(f"Transaction confirmation timeout: {tx_hash[:20]}...")
        return None

    # ==================== Trade Record Processing ====================

    def _process_buy_receipt(
        self,
        signal: Signal,
        receipt: Dict,
        amount_eth: float,
        prepared: Dict
    ) -> Optional[Trade]:
        """Process a successful buy receipt and create trade record.

        Args:
            signal: Original trading signal
            receipt: Transaction receipt
            amount_eth: Buy amount in ETH
            prepared: Prepared transaction data

        Returns:
            Created Trade object
        """
        try:
            gas_used = receipt.get('gas_used', 0)
            tx_hash = receipt.get('hash', '')

            # Calculate gas cost
            gas_price_wei = prepared.get('transaction', {}).get('gasPrice', 0)
            gas_cost_eth = float(Web3.from_wei(gas_used * gas_price_wei, 'ether'))

            entry_price = prepared.get('gas_estimate', {}).get('total_cost_eth', 0)
            if entry_price == 0:
                entry_price = amount_eth  # Fallback to amount

            # Create trade record
            trade_data = {
                'chain': self.chain,
                'token_address': signal.token_address,
                'token_symbol': signal.token_symbol,
                'token_name': signal.token_name,
                'trade_type': SignalType.BUY,
                'amount_eth': amount_eth,
                'amount_token': 0,  # Will be updated when we know exact token amount
                'entry_price': entry_price,
                'stop_loss': signal.stop_loss or self.config.stop_loss_pct,
                'take_profit': signal.take_profit or self.config.take_profit_pct,
                'transaction_hash': tx_hash,
                'gas_used': gas_used,
                'gas_price_gwei': float(Web3.from_wei(gas_price_wei, 'gwei')) if gas_price_wei else 0,
                'transaction_cost_eth': gas_cost_eth,
                'dex': prepared.get('dex_name', 'unknown'),
                'status': TradeStatus.COMPLETED,
                'executed_at': datetime.utcnow(),
                'trade_data': {
                    'signal_id': signal.id,
                    'dex': prepared.get('dex_name'),
                    'slippage_bps': prepared.get('slippage_bps'),
                    'gas_strategy': 'balanced',
                }
            }

            trade = self.database.add_trade(trade_data)

            if trade:
                logger.info(f"Trade record created: {trade}")
                # Update signal with trade reference
                signal.trade_id = trade.id
                signal.processed = True

            return trade

        except Exception as e:
            logger.error(f"Failed to process buy receipt: {e}")
            return None

    # ==================== Utility Methods ====================

    def _get_weth_address(self) -> Optional[str]:
        """Get WETH (or equivalent wrapped native token) address for the chain."""
        weth_addresses = {
            Chain.ETHEREUM: "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            Chain.BSC: "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
            Chain.ARBITRUM: "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
            Chain.POLYGON: "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
            Chain.AVALANCHE: "0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7",
            Chain.SEPOLIA: "0xfFf9976782d46CC05630D1f6eBAb18b2324d6B14",
        }
        return weth_addresses.get(self.chain)

    def _get_router_for_dex(self, dex_name: str) -> Optional[str]:
        """Get router address for a DEX name."""
        dex_configs = self.config.dex_configs
        config = dex_configs.get(dex_name)
        if config:
            return config.get('router')
        return None

    def _log_execution(
        self,
        signal_id: Optional[int],
        action: str,
        status: str,
        message: str = '',
        tx_hash: Optional[str] = None,
        trade_id: Optional[int] = None,
    ) -> None:
        """Log an execution event to the database.

        Args:
            signal_id: Associated signal ID
            action: Action name
            status: Status (started/success/failed)
            message: Log message
            tx_hash: Transaction hash
            trade_id: Trade ID
        """
        try:
            log_data = {
                'signal_id': signal_id,
                'action': action,
                'status': status,
                'message': message,
                'tx_hash': tx_hash,
                'trade_id': trade_id,
                'chain': self.chain,
            }
            self.database.add_execution_log(log_data)
        except Exception as e:
            logger.error(f"Failed to log execution: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get executor status summary."""
        return {
            'chain': self.chain.value if isinstance(self.chain, Chain) else str(self.chain),
            'wallet_available': self.wallet.is_wallet_available(),
            'wallet_address': self.wallet.wallet_address,
            'web3_connected': self.web3.is_connected(),
            'stats': self.stats,
        }