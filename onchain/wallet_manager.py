"""Wallet management for onchain sniper functionality.

This module provides secure private key management, transaction signing,
and wallet operations for the onchain trading system.
"""

import os
import logging
from typing import Optional, Dict, Any
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3

from bot.config_web3 import get_web3_config

logger = logging.getLogger(__name__)


class WalletManager:
    """Secure wallet manager for private key handling and transaction signing."""

    def __init__(self, web3_config=None):
        """Initialize wallet manager.

        Args:
            web3_config: Web3Config instance, defaults to global config
        """
        self.config = web3_config or get_web3_config()
        self.account: Optional[LocalAccount] = None
        self.wallet_address: Optional[str] = None
        self._initialize_wallet()

    def _initialize_wallet(self) -> None:
        """Initialize wallet from configuration."""
        try:
            # Try to load private key
            private_key = self._load_private_key()

            if not private_key:
                logger.warning("No private key available. Read-only mode enabled.")
                return

            # Create account from private key
            self.account = Account.from_key(private_key)
            self.wallet_address = self.account.address

            logger.info(f"Wallet initialized: {self.wallet_address[:10]}...")

            # Verify wallet address matches config if provided
            if self.config.wallet_address and self.config.wallet_address.lower() != self.wallet_address.lower():
                logger.warning(
                    f"Configured wallet address {self.config.wallet_address} "
                    f"does not match derived address {self.wallet_address}"
                )

        except Exception as e:
            logger.error(f"Failed to initialize wallet: {e}")
            raise

    def _load_private_key(self) -> Optional[str]:
        """Load private key from configuration.

        Returns:
            Decrypted private key string or None if not available
        """
        # Try plaintext private key first
        if self.config.private_key:
            private_key = self.config.private_key.strip()

            # Remove '0x' prefix if present
            if private_key.startswith('0x'):
                private_key = private_key[2:]

            # Validate private key length (64 hex chars = 32 bytes)
            if len(private_key) == 64 and all(c in '0123456789abcdefABCDEF' for c in private_key):
                logger.info("Loaded plaintext private key")
                return private_key
            else:
                logger.error("Invalid private key format")
                return None

        # Try encrypted private key
        if self.config.encrypted_private_key:
            logger.warning("Encrypted private key support not yet implemented")
            # TODO: Implement encrypted private key decryption
            # Requires PRIVATE_KEY_PASSWORD environment variable
            return None

        return None

    def is_wallet_available(self) -> bool:
        """Check if wallet is available for signing transactions."""
        return self.account is not None

    def get_balance(self, web3: Web3, token_address: Optional[str] = None) -> float:
        """Get wallet balance.

        Args:
            web3: Web3 instance
            token_address: Optional token contract address for ERC20 balance

        Returns:
            Balance in ETH (or token units)
        """
        if not self.wallet_address:
            return 0.0

        try:
            if token_address:
                # ERC20 token balance
                # Minimal ERC20 ABI for balanceOf
                erc20_abi = [
                    {
                        "constant": True,
                        "inputs": [{"name": "_owner", "type": "address"}],
                        "name": "balanceOf",
                        "outputs": [{"name": "balance", "type": "uint256"}],
                        "type": "function"
                    }
                ]

                contract = web3.eth.contract(address=token_address, abi=erc20_abi)
                balance = contract.functions.balanceOf(self.wallet_address).call()
                # TODO: Get decimals for proper formatting
                return float(balance)
            else:
                # Native token balance (ETH, BNB, etc.)
                balance = web3.eth.get_balance(self.wallet_address)
                return float(Web3.from_wei(balance, 'ether'))

        except Exception as e:
            logger.error(f"Failed to get balance for {token_address or 'native'}: {e}")
            return 0.0

    def sign_transaction(self, transaction_dict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Sign a transaction.

        Args:
            transaction_dict: Transaction parameters

        Returns:
            Signed transaction dictionary or None if signing failed
        """
        if not self.is_wallet_available():
            logger.error("Cannot sign transaction: no wallet available")
            return None

        try:
            # Ensure from address matches wallet
            if 'from' in transaction_dict:
                if transaction_dict['from'].lower() != self.wallet_address.lower():
                    logger.warning(
                        f"Transaction 'from' address {transaction_dict['from']} "
                        f"does not match wallet address {self.wallet_address}"
                    )
            else:
                transaction_dict['from'] = self.wallet_address

            # Sign the transaction
            signed_tx = self.account.sign_transaction(transaction_dict)

            logger.debug(f"Transaction signed: {signed_tx.hash.hex()}")

            return {
                'rawTransaction': signed_tx.rawTransaction.hex(),
                'hash': signed_tx.hash.hex(),
                'r': hex(signed_tx.r),
                's': hex(signed_tx.s),
                'v': signed_tx.v,
            }

        except Exception as e:
            logger.error(f"Failed to sign transaction: {e}")
            return None

    def verify_signature(self, message_hash: str, signature: Dict[str, Any]) -> bool:
        """Verify a signature.

        Args:
            message_hash: Hash of the message that was signed
            signature: Signature dictionary with v, r, s

        Returns:
            True if signature is valid for this wallet
        """
        if not self.is_wallet_available():
            return False

        try:
            # Recover address from signature
            recovered_address = Account.recover_hash(
                message_hash=Web3.to_bytes(hexstr=message_hash),
                vrs=(signature['v'], signature['r'], signature['s'])
            )

            return recovered_address.lower() == self.wallet_address.lower()

        except Exception as e:
            logger.error(f"Failed to verify signature: {e}")
            return False

    def get_account_info(self) -> Dict[str, Any]:
        """Get wallet account information (excluding sensitive data)."""
        return {
            'wallet_address': self.wallet_address,
            'is_available': self.is_wallet_available(),
            'has_private_key': self.account is not None,
            'config_wallet_address': self.config.wallet_address,
        }