"""Gas optimization for onchain sniper functionality.

This module provides gas price estimation and optimization strategies
to minimize transaction costs while ensuring timely execution.
"""

import logging
import time
from typing import Dict, Optional, Tuple, List
from web3 import Web3
from dataclasses import dataclass

from bot.config_web3 import get_web3_config

logger = logging.getLogger(__name__)


@dataclass
class GasEstimate:
    """Gas estimation result."""
    gas_limit: int
    base_fee: int  # Gwei
    priority_fee: int  # Gwei
    max_fee_per_gas: int  # Gwei
    total_cost_eth: float
    is_acceptable: bool
    strategy_name: str


class GasOptimizer:
    """Gas price optimizer for transaction cost management."""

    def __init__(self, web3: Web3, config=None):
        """Initialize gas optimizer.

        Args:
            web3: Web3 instance
            config: Web3Config instance, defaults to global config
        """
        self.web3 = web3
        self.config = config or get_web3_config()

        # Cache for gas prices
        self._gas_price_cache: Optional[Dict] = None
        self._cache_timestamp: float = 0
        self._cache_ttl: float = 15.0  # Cache TTL in seconds

    def estimate_gas(
        self,
        transaction: Dict,
        strategy: str = 'balanced'
    ) -> Optional[GasEstimate]:
        """Estimate optimal gas for a transaction.

        Args:
            transaction: Transaction dictionary (without gas fields)
            strategy: Gas strategy ('fast', 'balanced', 'economy')

        Returns:
            GasEstimate object or None on error
        """
        try:
            # Get gas limit estimate
            gas_limit = self._estimate_gas_limit(transaction)
            if gas_limit is None:
                logger.error("Failed to estimate gas limit")
                return None

            # Get gas price based on strategy
            gas_prices = self._get_gas_prices()
            if gas_prices is None:
                logger.error("Failed to get gas prices")
                return None

            # Apply strategy
            if strategy == 'fast':
                priority_fee = int(gas_prices['fast_priority_fee'])
                base_fee = int(gas_prices['base_fee'])
            elif strategy == 'economy':
                priority_fee = int(gas_prices['economy_priority_fee'])
                base_fee = int(gas_prices['base_fee'])
            else:  # balanced (default)
                priority_fee = int(gas_prices['standard_priority_fee'])
                base_fee = int(gas_prices['base_fee'])

            # Calculate max fee (must be >= base_fee + priority_fee)
            max_fee = base_fee + priority_fee

            # Apply max gas price limit
            max_gas_price = self.config.max_gas_price_gwei
            if max_fee > max_gas_price:
                logger.warning(
                    f"Estimated max fee {max_fee} Gwei exceeds limit {max_gas_price} Gwei"
                )
                # Cap at max allowed
                max_fee = max_gas_price
                priority_fee = min(priority_fee, max_fee - base_fee)

            # Calculate total cost
            total_cost_wei = gas_limit * max_fee
            total_cost_eth = float(Web3.from_wei(total_cost_wei, 'gwei')) / 1e9

            # Check if gas cost is acceptable
            # For reference, a simple swap costs ~150-300k gas
            is_acceptable = total_cost_eth < 0.05  # Less than 0.05 ETH default

            return GasEstimate(
                gas_limit=gas_limit,
                base_fee=base_fee,
                priority_fee=priority_fee,
                max_fee_per_gas=max_fee,
                total_cost_eth=total_cost_eth,
                is_acceptable=is_acceptable,
                strategy_name=strategy
            )

        except Exception as e:
            logger.error(f"Failed to estimate gas: {e}")
            return None

    def estimate_swap_gas(
        self,
        transaction: Dict,
        strategy: str = 'balanced'
    ) -> Optional[GasEstimate]:
        """Estimate gas specifically for swap transactions.

        Swaps typically cost more gas than simple transfers.
        This method applies appropriate multipliers.

        Args:
            transaction: Transaction dictionary
            strategy: Gas strategy

        Returns:
            GasEstimate object
        """
        estimate = self.estimate_gas(transaction, strategy)
        if estimate:
            # Swap transactions typically need more gas
            # Apply multiplier based on current network conditions
            gas_prices = self._get_gas_prices()
            if gas_prices and gas_prices.get('congestion_level', 'low') == 'high':
                estimate.gas_limit = int(estimate.gas_limit * 1.5)
            else:
                estimate.gas_limit = int(estimate.gas_limit * 1.2)

            # Recalculate cost
            total_cost_wei = estimate.gas_limit * estimate.max_fee_per_gas
            estimate.total_cost_eth = float(Web3.from_wei(total_cost_wei, 'gwei')) / 1e9

            return estimate

        return None

    def _estimate_gas_limit(self, transaction: Dict) -> Optional[int]:
        """Estimate gas limit for a transaction.

        Args:
            transaction: Transaction dictionary

        Returns:
            Estimated gas limit or None
        """
        try:
            # Try eth_estimateGas
            gas_limit = self.web3.eth.estimate_gas(transaction)
            return gas_limit

        except Exception as e:
            logger.warning(f"eth_estimateGas failed: {e}")

            # Fallback to default limits based on transaction type
            if transaction.get('data') and transaction['data'] != '0x':
                return 300000  # Contract interaction
            return 21000  # Simple ETH transfer

    def _get_gas_prices(self) -> Optional[Dict]:
        """Get current gas prices from network.

        Returns:
            Dictionary with base_fee, fast/standard/economy priority fees
        """
        # Check cache
        current_time = time.time()
        if (self._gas_price_cache and
                current_time - self._cache_timestamp < self._cache_ttl):
            return self._gas_price_cache

        try:
            # Try EIP-1559 fee history
            latest_block = self.web3.eth.get_block('latest')
            base_fee = latest_block.get('baseFeePerGas', 0)

            # Convert to Gwei
            base_fee_gwei = float(Web3.from_wei(base_fee, 'gwei')) if base_fee else 0

            if base_fee_gwei == 0:
                # Legacy chain (no EIP-1559)
                gas_price = self.web3.eth.gas_price
                gas_price_gwei = float(Web3.from_wei(gas_price, 'gwei'))

                gas_prices = {
                    'base_fee': gas_price_gwei,
                    'standard_priority_fee': 0,
                    'fast_priority_fee': 0,
                    'economy_priority_fee': 0,
                    'legacy_price': gas_price_gwei,
                    'congestion_level': 'low' if gas_price_gwei < 50 else ('medium' if gas_price_gwei < 100 else 'high'),
                    'eip1559': False,
                }
            else:
                # EIP-1559: Get priority fees from recent blocks
                fee_history = self.web3.eth.fee_history(5, 'latest', [25, 50, 75])

                # Get percentile rewards
                rewards = fee_history.get('reward', [])
                if rewards and len(rewards) > 0:
                    # P25, P50, P75
                    economy_priority = max(r[0] for r in rewards)
                    standard_priority = max(r[1] for r in rewards)
                    fast_priority = max(r[2] for r in rewards)
                else:
                    economy_priority = 100000000  # 0.1 Gwei
                    standard_priority = 1000000000  # 1 Gwei
                    fast_priority = 2000000000  # 2 Gwei

                economy_priority_fee = float(Web3.from_wei(economy_priority, 'gwei'))
                standard_priority_fee = float(Web3.from_wei(standard_priority, 'gwei'))
                fast_priority_fee = float(Web3.from_wei(fast_priority, 'gwei'))

                # Determine congestion level
                if fast_priority_fee > 5 or base_fee_gwei > 100:
                    congestion = 'high'
                elif fast_priority_fee > 2 or base_fee_gwei > 50:
                    congestion = 'medium'
                else:
                    congestion = 'low'

                gas_prices = {
                    'base_fee': base_fee_gwei,
                    'standard_priority_fee': standard_priority_fee,
                    'fast_priority_fee': fast_priority_fee,
                    'economy_priority_fee': economy_priority_fee,
                    'legacy_price': base_fee_gwei + fast_priority_fee,
                    'congestion_level': congestion,
                    'eip1559': True,
                }

            # Update cache
            self._gas_price_cache = gas_prices
            self._cache_timestamp = current_time

            logger.debug(
                f"Gas prices - Base: {gas_prices['base_fee']:.2f}, "
                f"Standard: {gas_prices['standard_priority_fee']:.2f}, "
                f"Fast: {gas_prices['fast_priority_fee']:.2f} Gwei "
                f"({gas_prices.get('congestion_level', 'unknown')} congestion)"
            )

            return gas_prices

        except Exception as e:
            logger.error(f"Failed to get gas prices: {e}")
            return None

    def get_gas_price_summary(self) -> Dict:
        """Get a summary of current gas prices.

        Returns:
            Dictionary with gas price information
        """
        gas_prices = self._get_gas_prices()
        if not gas_prices:
            return {'error': 'Failed to get gas prices'}

        summary = {
            'base_fee_gwei': f"{gas_prices['base_fee']:.1f}" if gas_prices.get('base_fee') else 'N/A',
            'standard_priority_gwei': f"{gas_prices.get('standard_priority_fee', 0):.2f}",
            'fast_priority_gwei': f"{gas_prices.get('fast_priority_fee', 0):.2f}",
            'economy_priority_gwei': f"{gas_prices.get('economy_priority_fee', 0):.2f}",
            'congestion_level': gas_prices.get('congestion_level', 'unknown'),
            'is_eip1559': gas_prices.get('eip1559', False),
            'timestamp': time.time(),
        }

        # Add estimated costs
        for tx_type, gas_units in [
            ('eth_transfer', 21000),
            ('token_swap', 200000),
            ('complex_interaction', 400000),
        ]:
            if gas_prices.get('eip1559', False):
                total_gwei = (gas_prices['base_fee'] + gas_prices['standard_priority_fee']) * gas_units
            else:
                total_gwei = gas_prices['legacy_price'] * gas_units
            summary[f'cost_{tx_type}_eth'] = f"{total_gwei / 1e9:.6f}"

        return summary

    def should_wait_for_lower_gas(self, max_gas_gwei: Optional[int] = None) -> Tuple[bool, Dict]:
        """Check if we should wait for lower gas prices.

        Args:
            max_gas_gwei: Maximum acceptable gas price in Gwei

        Returns:
            Tuple of (should_wait, current_prices)
        """
        max_gas = max_gas_gwei or self.config.max_gas_price_gwei

        gas_prices = self._get_gas_prices()
        if not gas_prices:
            return False, {}

        if gas_prices.get('eip1559', False):
            current_price = gas_prices['base_fee'] + gas_prices['standard_priority_fee']
        else:
            current_price = gas_prices['legacy_price']

        should_wait = current_price > max_gas * 0.8  # Wait if > 80% of max

        return should_wait, gas_prices


class GasEstimator:
    """Simple gas estimator for read-only operations."""

    def __init__(self, web3: Web3):
        self.web3 = web3

    def estimate_gas_limit(self, transaction: Dict) -> int:
        """Estimate gas limit for a transaction.

        Args:
            transaction: Transaction dictionary

        Returns:
            Estimated gas limit
        """
        try:
            return self.web3.eth.estimate_gas(transaction)
        except Exception:
            return 21000  # Default for ETH transfer

    def get_current_gas_price(self) -> int:
        """Get current gas price in wei.

        Returns:
            Current gas price in wei
        """
        try:
            return self.web3.eth.gas_price
        except Exception as e:
            logger.error(f"Failed to get current gas price: {e}")
            return 0