"""DEX client for onchain sniper functionality.

This module provides interfaces to various decentralized exchanges (DEXes)
for price queries, trade routing, and transaction building.
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from decimal import Decimal
from web3 import Web3
from web3.contract import Contract

from bot.config_web3 import get_web3_config

logger = logging.getLogger(__name__)


class DEXClient:
    """Base class for DEX clients."""

    def __init__(self, web3: Web3, config=None):
        """Initialize DEX client.

        Args:
            web3: Web3 instance
            config: Web3Config instance, defaults to global config
        """
        self.web3 = web3
        self.config = config or get_web3_config()
        self.router: Optional[Contract] = None
        self.factory: Optional[Contract] = None

    def get_price(
        self,
        token_in: str,
        token_out: str,
        amount_in: float
    ) -> Tuple[Optional[float], Optional[float]]:
        """Get expected output amount for a swap.

        Args:
            token_in: Input token address
            token_out: Output token address
            amount_in: Input amount in token units

        Returns:
            Tuple of (expected_output, price_impact_percent) or (None, None) on error
        """
        raise NotImplementedError

    def build_swap_transaction(
        self,
        token_in: str,
        token_out: str,
        amount_in: float,
        recipient: str,
        slippage_bps: int = 500,  # 5% in basis points
        deadline_minutes: int = 30
    ) -> Optional[Dict[str, Any]]:
        """Build a swap transaction.

        Args:
            token_in: Input token address
            token_out: Output token address
            amount_in: Input amount in token units
            recipient: Recipient address
            slippage_bps: Maximum slippage in basis points (1% = 100)
            deadline_minutes: Transaction deadline in minutes

        Returns:
            Transaction dictionary or None on error
        """
        raise NotImplementedError

    def get_liquidity(self, token_a: str, token_b: str) -> Optional[float]:
        """Get liquidity for a token pair.

        Args:
            token_a: First token address
            token_b: Second token address

        Returns:
            Total liquidity in ETH or None on error
        """
        raise NotImplementedError

    def get_pair_address(self, token_a: str, token_b: str) -> Optional[str]:
        """Get pair contract address for two tokens.

        Args:
            token_a: First token address
            token_b: Second token address

        Returns:
            Pair contract address or None if not found
        """
        raise NotImplementedError


class UniswapV2Client(DEXClient):
    """Client for Uniswap V2 and compatible DEXes."""

    def __init__(self, web3: Web3, config=None):
        """Initialize Uniswap V2 client."""
        super().__init__(web3, config)

        # Get router and factory addresses from config
        dex_config = self.config.dex_configs.get('uniswap_v2', {})
        router_address = dex_config.get('router')
        factory_address = dex_config.get('factory')

        if not router_address or not factory_address:
            logger.warning("Uniswap V2 addresses not configured")
            return

        # Load contracts
        self.router = self._load_router_contract(router_address)
        self.factory = self._load_factory_contract(factory_address)

    def _load_router_contract(self, address: str) -> Optional[Contract]:
        """Load Uniswap V2 router contract."""
        # Minimal Uniswap V2 router ABI
        router_abi = [
            {
                "inputs": [
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint256[]", "name": "path", "type": "uint256[]"}
                ],
                "name": "getAmountsOut",
                "outputs": [
                    {"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}
                ],
                "stateMutability": "view",
                "type": "function"
            },
            {
                "inputs": [
                    {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
                    {"internalType": "uint256[]", "name": "path", "type": "uint256[]"}
                ],
                "name": "getAmountsIn",
                "outputs": [
                    {"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}
                ],
                "stateMutability": "view",
                "type": "function"
            },
            {
                "inputs": [
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
                    {"internalType": "address[]", "name": "path", "type": "address[]"},
                    {"internalType": "address", "name": "to", "type": "address"},
                    {"internalType": "uint256", "name": "deadline", "type": "uint256"}
                ],
                "name": "swapExactTokensForTokens",
                "outputs": [
                    {"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}
                ],
                "stateMutability": "nonpayable",
                "type": "function"
            },
            {
                "inputs": [
                    {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountInMax", "type": "uint256"},
                    {"internalType": "address[]", "name": "path", "type": "address[]"},
                    {"internalType": "address", "name": "to", "type": "address"},
                    {"internalType": "uint256", "name": "deadline", "type": "uint256"}
                ],
                "name": "swapTokensForExactTokens",
                "outputs": [
                    {"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}
                ],
                "stateMutability": "nonpayable",
                "type": "function"
            },
            {
                "inputs": [],
                "name": "WETH",
                "outputs": [{"internalType": "address", "name": "", "type": "address"}],
                "stateMutability": "view",
                "type": "function"
            }
        ]

        try:
            contract = self.web3.eth.contract(address=address, abi=router_abi)
            logger.info(f"Loaded Uniswap V2 router at {address}")
            return contract
        except Exception as e:
            logger.error(f"Failed to load Uniswap V2 router: {e}")
            return None

    def _load_factory_contract(self, address: str) -> Optional[Contract]:
        """Load Uniswap V2 factory contract."""
        # Minimal factory ABI
        factory_abi = [
            {
                "inputs": [
                    {"internalType": "address", "name": "", "type": "address"},
                    {"internalType": "address", "name": "", "type": "address"}
                ],
                "name": "getPair",
                "outputs": [{"internalType": "address", "name": "", "type": "address"}],
                "stateMutability": "view",
                "type": "function"
            }
        ]

        try:
            contract = self.web3.eth.contract(address=address, abi=factory_abi)
            logger.info(f"Loaded Uniswap V2 factory at {address}")
            return contract
        except Exception as e:
            logger.error(f"Failed to load Uniswap V2 factory: {e}")
            return None

    def get_price(
        self,
        token_in: str,
        token_out: str,
        amount_in: float
    ) -> Tuple[Optional[float], Optional[float]]:
        """Get expected output amount for a swap on Uniswap V2."""
        if not self.router:
            logger.error("Router contract not loaded")
            return None, None

        try:
            # Convert amount to wei (assuming 18 decimals for now)
            # TODO: Handle different token decimals
            amount_in_wei = self.web3.to_wei(amount_in, 'ether')

            # Build path
            path = [token_in, token_out]

            # Get amounts out
            amounts = self.router.functions.getAmountsOut(amount_in_wei, path).call()

            if len(amounts) < 2:
                logger.error("Invalid amounts returned")
                return None, None

            expected_output = float(self.web3.from_wei(amounts[-1], 'ether'))

            # Calculate price impact (simplified)
            # TODO: Implement proper price impact calculation
            price_impact = 0.0  # Placeholder

            logger.debug(
                f"Price quote: {amount_in} {token_in[:10]}... -> "
                f"{expected_output:.6f} {token_out[:10]}... (impact: {price_impact:.2f}%)"
            )

            return expected_output, price_impact

        except Exception as e:
            logger.error(f"Failed to get price: {e}")
            return None, None

    def build_swap_transaction(
        self,
        token_in: str,
        token_out: str,
        amount_in: float,
        recipient: str,
        slippage_bps: int = 500,
        deadline_minutes: int = 30
    ) -> Optional[Dict[str, Any]]:
        """Build a swap transaction for Uniswap V2."""
        if not self.router:
            logger.error("Router contract not loaded")
            return None

        try:
            # Get expected output
            expected_output, price_impact = self.get_price(token_in, token_out, amount_in)
            if expected_output is None:
                logger.error("Failed to get price quote")
                return None

            # Calculate minimum output with slippage
            slippage_multiplier = 1.0 - (slippage_bps / 10000.0)
            amount_out_min = int(expected_output * slippage_multiplier * 10**18)  # Convert to wei

            # Convert amount to wei
            amount_in_wei = self.web3.to_wei(amount_in, 'ether')

            # Build path
            path = [token_in, token_out]

            # Calculate deadline
            deadline = self.web3.eth.get_block('latest')['timestamp'] + (deadline_minutes * 60)

            # Build transaction data
            transaction_data = self.router.functions.swapExactTokensForTokens(
                amount_in_wei,
                amount_out_min,
                path,
                recipient,
                deadline
            ).build_transaction({
                'from': recipient,  # Will be overwritten by signer
                'gas': 300000,  # Conservative estimate
                'gasPrice': self.web3.eth.gas_price,
            })

            # Remove 'from' as it will be set by wallet
            if 'from' in transaction_data:
                del transaction_data['from']

            logger.info(
                f"Built swap: {amount_in} {token_in[:10]}... -> "
                f"min {amount_out_min/10**18:.6f} {token_out[:10]}... "
                f"(slippage: {slippage_bps/100}%)"
            )

            return transaction_data

        except Exception as e:
            logger.error(f"Failed to build swap transaction: {e}")
            return None

    def get_pair_address(self, token_a: str, token_b: str) -> Optional[str]:
        """Get pair contract address for two tokens."""
        if not self.factory:
            logger.error("Factory contract not loaded")
            return None

        try:
            # Sort tokens for consistent pair address
            token_a_lower = token_a.lower()
            token_b_lower = token_b.lower()

            if token_a_lower > token_b_lower:
                token_a_lower, token_b_lower = token_b_lower, token_a_lower

            pair_address = self.factory.functions.getPair(token_a_lower, token_b_lower).call()

            if pair_address == '0x' + '0' * 40:  # Zero address means no pair
                return None

            return pair_address

        except Exception as e:
            logger.error(f"Failed to get pair address: {e}")
            return None

    def get_liquidity(self, token_a: str, token_b: str) -> Optional[float]:
        """Get liquidity for a token pair."""
        pair_address = self.get_pair_address(token_a, token_b)
        if not pair_address:
            return None

        try:
            # Minimal pair ABI for reserves
            pair_abi = [
                {
                    "inputs": [],
                    "name": "getReserves",
                    "outputs": [
                        {"internalType": "uint112", "name": "reserve0", "type": "uint112"},
                        {"internalType": "uint112", "name": "reserve1", "type": "uint112"},
                        {"internalType": "uint32", "name": "blockTimestampLast", "type": "uint32"}
                    ],
                    "stateMutability": "view",
                    "type": "function"
                },
                {
                    "inputs": [],
                    "name": "token0",
                    "outputs": [{"internalType": "address", "name": "", "type": "address"}],
                    "stateMutability": "view",
                    "type": "function"
                },
                {
                    "inputs": [],
                    "name": "token1",
                    "outputs": [{"internalType": "address", "name": "", "type": "address"}],
                    "stateMutability": "view",
                    "type": "function"
                }
            ]

            pair_contract = self.web3.eth.contract(address=pair_address, abi=pair_abi)

            # Get reserves
            reserves = pair_contract.functions.getReserves().call()
            token0 = pair_contract.functions.token0().call()

            # Determine which reserve corresponds to which token
            # This is simplified - in practice you'd need to check prices
            # For now, return the larger reserve in ETH terms
            reserve0_eth = float(self.web3.from_wei(reserves[0], 'ether'))
            reserve1_eth = float(self.web3.from_wei(reserves[1], 'ether'))

            total_liquidity = reserve0_eth + reserve1_eth

            logger.debug(f"Pair {token_a[:10]}.../{token_b[:10]}... liquidity: {total_liquidity:.2f} ETH")

            return total_liquidity

        except Exception as e:
            logger.error(f"Failed to get liquidity: {e}")
            return None


class DEXClientFactory:
    """Factory for creating DEX clients."""

    @staticmethod
    def create_client(
        dex_name: str,
        web3: Web3,
        config=None
    ) -> Optional[DEXClient]:
        """Create a DEX client by name.

        Args:
            dex_name: Name of DEX (uniswap_v2, pancakeswap_v2, etc.)
            web3: Web3 instance
            config: Web3Config instance

        Returns:
            DEXClient instance or None if not supported
        """
        clients = {
            'uniswap_v2': UniswapV2Client,
            'pancakeswap_v2': UniswapV2Client,  # Same interface
            'sushiswap': UniswapV2Client,  # Same interface
        }

        client_class = clients.get(dex_name)
        if not client_class:
            logger.error(f"Unsupported DEX: {dex_name}")
            return None

        try:
            return client_class(web3, config)
        except Exception as e:
            logger.error(f"Failed to create {dex_name} client: {e}")
            return None

    @staticmethod
    def get_supported_dexes() -> List[str]:
        """Get list of supported DEXes."""
        return ['uniswap_v2', 'pancakeswap_v2', 'sushiswap']