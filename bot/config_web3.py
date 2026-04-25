"""Web3 and blockchain configuration management for Telegram Claude Bot.

This module extends the main configuration system to support blockchain-related
settings including RPC nodes, wallet management, transaction parameters, and
monitoring rules for the onchain sniper functionality.
"""

import os
import logging
from typing import Dict, Optional, Any, List
from pathlib import Path
import json

logger = logging.getLogger(__name__)


class Web3Config:
    """Web3 and blockchain configuration manager."""

    def __init__(self):
        self._load_from_env()
        self._validate()

    def _load_from_env(self) -> None:
        """Load Web3 configuration from environment variables."""

        # Network configurations
        self.rpc_urls = {
            'ethereum': os.environ.get('ETH_RPC_URL', 'https://eth-mainnet.g.alchemy.com/v2/demo'),
            'bsc': os.environ.get('BSC_RPC_URL', 'https://bsc-dataseed.binance.org/'),
            'arbitrum': os.environ.get('ARB_RPC_URL', 'https://arb1.arbitrum.io/rpc'),
            'polygon': os.environ.get('POLYGON_RPC_URL', 'https://polygon-rpc.com'),
            'avalanche': os.environ.get('AVAX_RPC_URL', 'https://api.avax.network/ext/bc/C/rpc'),
        }

        # Chain IDs
        self.chain_ids = {
            'ethereum': 1,
            'bsc': 56,
            'arbitrum': 42161,
            'polygon': 137,
            'avalanche': 43114,
        }

        # Wallet configuration
        self.private_key = os.environ.get('PRIVATE_KEY')
        self.encrypted_private_key = os.environ.get('ENCRYPTED_PRIVATE_KEY')
        self.wallet_address = os.environ.get('WALLET_ADDRESS')

        # Transaction configuration
        self.gas_multiplier = float(os.environ.get('GAS_MULTIPLIER', '1.1'))
        self.max_gas_price_gwei = int(os.environ.get('MAX_GAS_PRICE_GWEI', '150'))
        self.max_slippage = float(os.environ.get('MAX_SLIPPAGE', '0.05'))  # 5%
        self.transaction_timeout = int(os.environ.get('TRANSACTION_TIMEOUT', '300'))  # seconds

        # Trading configuration
        self.max_trade_eth = float(os.environ.get('MAX_TRADE_ETH', '0.1'))
        self.min_trade_eth = float(os.environ.get('MIN_TRADE_ETH', '0.001'))
        self.max_position_eth = float(os.environ.get('MAX_POSITION_ETH', '1.0'))
        self.default_slippage_bps = int(os.environ.get('DEFAULT_SLIPPAGE_BPS', '500'))  # 5% in basis points

        # Monitoring configuration
        self.monitor_interval = int(os.environ.get('MONITOR_INTERVAL', '30'))  # seconds
        self.max_blocks_to_scan = int(os.environ.get('MAX_BLOCKS_TO_SCAN', '1000'))
        self.confirmation_blocks = int(os.environ.get('CONFIRMATION_BLOCKS', '3'))

        # Event monitoring thresholds
        self.min_liquidity_eth = float(os.environ.get('MIN_LIQUIDITY_ETH', '10.0'))
        self.min_holder_count = int(os.environ.get('MIN_HOLDER_COUNT', '100'))
        self.large_transfer_threshold_eth = float(os.environ.get('LARGE_TRANSFER_THRESHOLD_ETH', '50.0'))
        self.new_token_age_hours = int(os.environ.get('NEW_TOKEN_AGE_HOURS', '24'))

        # Risk management
        self.max_daily_trades = int(os.environ.get('MAX_DAILY_TRADES', '10'))
        self.max_daily_loss_eth = float(os.environ.get('MAX_DAILY_LOSS_ETH', '0.5'))
        self.stop_loss_pct = float(os.environ.get('STOP_LOSS_PCT', '0.10'))  # 10%
        self.take_profit_pct = float(os.environ.get('TAKE_PROFIT_PCT', '0.30'))  # 30%
        self.cooldown_minutes = int(os.environ.get('COOLDOWN_MINUTES', '30'))

        # DEX configurations
        self.dex_configs = {
            'uniswap_v2': {
                'router': '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D',
                'factory': '0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f',
            },
            'uniswap_v3': {
                'router': '0xE592427A0AEce92De3Edee1F18E0157C05861564',
                'factory': '0x1F98431c8aD98523631AE4a59f267346ea31F984',
            },
            'pancakeswap_v2': {
                'router': '0x10ED43C718714eb63d5aA57B78B54704E256024E',
                'factory': '0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73',
            },
            'sushiswap': {
                'router': '0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F',
                'factory': '0xC0AEe478e3658e2610c5F7A4A2E1777cE9e4f2Ac',
            }
        }

        # Blacklist configuration
        blacklist_path = os.environ.get('BLACKLIST_PATH', 'data/blacklist.json')
        self.blacklist_path = Path(blacklist_path)
        self.blacklist = self._load_blacklist()

        # Cache configuration
        self.cache_ttl_blocks = int(os.environ.get('CACHE_TTL_BLOCKS', '100'))
        self.cache_ttl_transactions = int(os.environ.get('CACHE_TTL_TRANSACTIONS', '3600'))  # 1 hour

        # Logging and debugging
        self.debug_mode = os.environ.get('DEBUG_MODE', 'false').lower() == 'true'
        self.log_all_transactions = os.environ.get('LOG_ALL_TRANSACTIONS', 'false').lower() == 'true'

        # Network mode (mainnet or testnet)
        self.network_mode = os.environ.get('NETWORK_MODE', 'mainnet').lower()

        # Apply testnet overrides if in testnet mode
        self._apply_testnet_overrides()

    def _apply_testnet_overrides(self) -> None:
        """Apply testnet-specific configuration overrides.

        When NETWORK_MODE=testnet, this method:
        - Adds Sepolia RPC URL and chain ID
        - Overrides DEX configs with Sepolia testnet addresses
        - Lowers trading limits for testnet safety
        """
        if self.network_mode != 'testnet':
            return

        logger.info("Applying testnet configuration overrides")

        # Add Sepolia RPC URL
        sepolia_rpc = os.environ.get('SEPOLIA_RPC_URL')
        if sepolia_rpc:
            self.rpc_urls['sepolia'] = sepolia_rpc

        # Add Sepolia chain ID
        self.chain_ids['sepolia'] = 11155111

        # Override DEX configs for Sepolia testnet
        self.dex_configs['uniswap_v2'] = {
            'router': os.environ.get(
                'TEST_UNISWAP_V2_ROUTER',
                '0xC532a74256D338Db9Ee4E7e38E9046eE5fE6a8a3'
            ),
            'factory': os.environ.get(
                'TEST_UNISWAP_V2_FACTORY',
                '0x7E0987E8b5C0E2D1F2B0c7D5F8F1E3A1B5C8D9E0'
            ),
        }

        # Lower trading limits for testnet safety
        self.max_trade_eth = float(os.environ.get('TEST_MAX_TRADE_ETH', '0.01'))
        self.min_trade_eth = float(os.environ.get('TEST_MIN_TRADE_ETH', '0.0001'))

    def _load_blacklist(self) -> Dict[str, Any]:
        """Load blacklist from JSON file."""
        try:
            if self.blacklist_path.exists():
                with open(self.blacklist_path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load blacklist from {self.blacklist_path}: {e}")

        # Return default empty blacklist
        return {
            "contracts": [],
            "tokens": [],
            "wallets": [],
            "patterns": []
        }

    def _validate(self) -> None:
        """Validate Web3 configuration."""
        errors = []

        # Check for at least one RPC URL
        active_rpcs = [chain for chain, url in self.rpc_urls.items() if url and url != 'demo']
        if not active_rpcs:
            errors.append("At least one RPC URL must be configured (ETH_RPC_URL, BSC_RPC_URL, etc.)")

        # Check wallet configuration
        if not self.private_key and not self.encrypted_private_key:
            logger.warning("No private key configured. Read-only mode will be enabled.")

        # Validate numeric ranges
        if self.gas_multiplier < 1.0:
            errors.append("GAS_MULTIPLIER must be >= 1.0")

        if not (0 <= self.max_slippage <= 1.0):
            errors.append("MAX_SLIPPAGE must be between 0 and 1")

        if self.monitor_interval < 5:
            errors.append("MONITOR_INTERVAL must be at least 5 seconds")

        if errors:
            error_msg = ", ".join(errors)
            logger.error(f"Web3 configuration validation failed: {error_msg}")
            if not self.debug_mode:
                raise ValueError(f"Invalid Web3 configuration: {error_msg}")

    def get_active_chains(self) -> List[str]:
        """Get list of chains with configured RPC URLs."""
        return [chain for chain, url in self.rpc_urls.items()
                if url and url != 'demo' and 'YOUR_KEY' not in url]

    def get_rpc_url(self, chain: str) -> Optional[str]:
        """Get RPC URL for a specific chain."""
        url = self.rpc_urls.get(chain)
        if not url or url == 'demo' or 'YOUR_KEY' in url:
            return None
        return url

    def get_chain_id(self, chain: str) -> Optional[int]:
        """Get chain ID for a specific chain."""
        return self.chain_ids.get(chain)

    def is_chain_enabled(self, chain: str) -> bool:
        """Check if a chain is enabled (has configured RPC)."""
        return self.get_rpc_url(chain) is not None

    def save_blacklist(self) -> bool:
        """Save blacklist to JSON file."""
        try:
            self.blacklist_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.blacklist_path, 'w') as f:
                json.dump(self.blacklist, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to save blacklist to {self.blacklist_path}: {e}")
            return False

    def add_to_blacklist(self, category: str, item: str, reason: str = "") -> bool:
        """Add an item to the blacklist."""
        if category not in self.blacklist:
            self.blacklist[category] = []

        # Check if already in blacklist
        for entry in self.blacklist[category]:
            if isinstance(entry, dict) and entry.get('address') == item:
                return False  # Already exists

        # Add to blacklist
        blacklist_entry = {
            "address": item,
            "reason": reason,
            "added_at": int(os.environ.get('CURRENT_TIMESTAMP', 0)) or 0
        }
        self.blacklist[category].append(blacklist_entry)

        # Save to file
        return self.save_blacklist()

    def is_blacklisted(self, address: str) -> bool:
        """Check if an address is in any blacklist category."""
        address_lower = address.lower()

        for category, items in self.blacklist.items():
            for item in items:
                if isinstance(item, dict):
                    item_address = item.get('address', '').lower()
                else:
                    item_address = str(item).lower()

                if item_address == address_lower:
                    return True

        return False

    def get_config_summary(self) -> Dict[str, Any]:
        """Get summary of Web3 configuration (excluding sensitive data)."""
        return {
            'active_chains': self.get_active_chains(),
            'max_trade_eth': self.max_trade_eth,
            'max_slippage': self.max_slippage,
            'monitor_interval': self.monitor_interval,
            'max_daily_trades': self.max_daily_trades,
            'risk_limits': {
                'stop_loss_pct': self.stop_loss_pct,
                'take_profit_pct': self.take_profit_pct,
                'max_daily_loss_eth': self.max_daily_loss_eth,
            },
            'blacklist_count': sum(len(items) for items in self.blacklist.values()),
            'debug_mode': self.debug_mode,
        }


# Global Web3 config instance
_web3_config_instance: Optional[Web3Config] = None

def get_web3_config() -> Web3Config:
    """Get the global Web3 configuration instance."""
    global _web3_config_instance
    if _web3_config_instance is None:
        _web3_config_instance = Web3Config()
    return _web3_config_instance

def reload_web3_config() -> Web3Config:
    """Reload Web3 configuration from environment variables."""
    global _web3_config_instance
    _web3_config_instance = Web3Config()
    return _web3_config_instance