"""Transaction builder for onchain sniper functionality.

This module integrates wallet management, DEX clients, gas optimization,
and transaction simulation to build and prepare transactions for execution.
"""

import logging
import time
from typing import Dict, Optional, Any, Tuple, List
from web3 import Web3

from bot.config_web3 import get_web3_config
from .wallet_manager import WalletManager
from .gas_optimizer import GasOptimizer, GasEstimate
from .tx_simulator import TxSimulator, SimulationResult
from .dex_client import DEXClientFactory, DEXClient

logger = logging.getLogger(__name__)


class TransactionBuilder:
    """Builds and prepares transactions for execution.

    Integrates wallet, DEX, gas optimization, and simulation
    to create fully prepared transactions ready for signing.
    """

    def __init__(self, web3: Web3, config=None):
        """Initialize transaction builder.

        Args:
            web3: Web3 instance
            config: Web3Config instance, defaults to global config
        """
        self.web3 = web3
        self.config = config or get_web3_config()
        self.wallet = WalletManager(self.config)
        self.gas_optimizer = GasOptimizer(web3, self.config)
        self.simulator = TxSimulator(web3, self.config)
        self.dex_clients: Dict[str, DEXClient] = {}

    def _get_dex_client(self, dex_name: str) -> Optional[DEXClient]:
        """Get or create a DEX client.

        Args:
            dex_name: DEX name (uniswap_v2, pancakeswap_v2, etc.)

        Returns:
            DEXClient instance or None
        """
        if dex_name not in self.dex_clients:
            client = DEXClientFactory.create_client(dex_name, self.web3, self.config)
            if client:
                self.dex_clients[dex_name] = client
        return self.dex_clients.get(dex_name)

    def prepare_swap_transaction(
        self,
        token_in: str,
        token_out: str,
        amount_in: float,
        slippage_bps: Optional[int] = None,
        dex_name: str = 'uniswap_v2',
        gas_strategy: str = 'balanced',
        simulate: bool = True,
    ) -> Dict[str, Any]:
        """Prepare a fully built swap transaction ready for signing.

        Steps:
        1. Get DEX client
        2. Build swap transaction
        3. Estimate gas
        4. Simulate (optional)
        5. Return prepared transaction

        Args:
            token_in: Input token address
            token_out: Output token address
            amount_in: Input amount in ETH units
            slippage_bps: Maximum slippage in basis points (1% = 100)
            dex_name: DEX to use
            gas_strategy: Gas strategy (fast, balanced, economy)
            simulate: Whether to simulate before returning

        Returns:
            Dictionary with transaction details and status

        Raises:
            ValueError: If required components are not available
        """
        slippage = slippage_bps or self.config.default_slippage_bps

        # Validate wallet
        if not self.wallet.is_wallet_available():
            raise ValueError("Wallet not available for signing")

        wallet_address = self.wallet.wallet_address

        # Get DEX client
        dex_client = self._get_dex_client(dex_name)
        if not dex_client:
            raise ValueError(f"DEX client not available: {dex_name}")

        # Build swap transaction
        tx_data = dex_client.build_swap_transaction(
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            recipient=wallet_address,
            slippage_bps=slippage,
        )

        if not tx_data:
            raise ValueError("Failed to build swap transaction")

        # Estimate gas
        gas_estimate = self.gas_optimizer.estimate_swap_gas(tx_data, gas_strategy)
        if not gas_estimate:
            logger.warning("Gas estimation failed, using defaults")
            gas_limit = 300000
            gas_price = self.web3.eth.gas_price
            max_fee = float(Web3.from_wei(gas_price, 'gwei'))
        else:
            gas_limit = gas_estimate.gas_limit
            max_fee = gas_estimate.max_fee_per_gas

        # Build final transaction
        transaction = {
            **tx_data,
            'gas': gas_limit,
            'gasPrice': self.web3.to_wei(max_fee, 'gwei'),
            'nonce': self.web3.eth.get_transaction_count(wallet_address),
            'chainId': self.config.get_chain_id(
                dex_name.split('_')[0]  # Extract chain from DEX name (simplified)
            ) or 1,
        }

        result = {
            'transaction': transaction,
            'wallet_address': wallet_address,
            'dex_name': dex_name,
            'token_in': token_in,
            'token_out': token_out,
            'amount_in': amount_in,
            'gas_estimate': {
                'gas_limit': gas_limit,
                'max_fee_gwei': max_fee,
                'total_cost_eth': gas_estimate.total_cost_eth if gas_estimate else 0,
            } if gas_estimate else None,
            'slippage_bps': slippage,
            'simulation': None,
            'status': 'prepared',
        }

        # Simulate if requested
        if simulate and self.wallet.is_wallet_available():
            try:
                simulation = self.simulator.simulate_transaction(
                    transaction, wallet_address
                )
                result['simulation'] = {
                    'success': simulation.success,
                    'gas_used': simulation.gas_used,
                    'error': simulation.error,
                }
                if not simulation.success:
                    result['status'] = 'simulation_failed'
                    result['simulation_error'] = simulation.error
                    logger.warning(
                        f"Swap simulation failed: {simulation.error}"
                    )
            except Exception as e:
                logger.warning(f"Transaction simulation error: {e}")
                result['simulation'] = {'success': False, 'error': str(e)}

        return result

    def prepare_token_approval(
        self,
        token_address: str,
        spender: str,
        amount: int,
        gas_strategy: str = 'balanced',
        simulate: bool = True,
    ) -> Dict[str, Any]:
        """Prepare a token approval transaction.

        Args:
            token_address: Token contract address
            spender: Spender address (DEX router, etc.)
            amount: Amount to approve in wei (use max uint256 for unlimited)
            gas_strategy: Gas strategy
            simulate: Whether to simulate

        Returns:
            Prepared approval transaction
        """
        if not self.wallet.is_wallet_available():
            raise ValueError("Wallet not available for signing")

        wallet_address = self.wallet.wallet_address

        # ERC20 approve ABI
        approve_abi = [{
            "constant": False,
            "inputs": [
                {"name": "spender", "type": "address"},
                {"name": "amount", "type": "uint256"}
            ],
            "name": "approve",
            "outputs": [{"name": "", "type": "bool"}],
            "type": "function"
        }]

        contract = self.web3.eth.contract(address=token_address, abi=approve_abi)
        approve_data = contract.encodeABI(fn_name="approve", args=[spender, amount])

        tx_params = {
            'to': token_address,
            'data': approve_data,
            'value': 0,
        }

        # Estimate gas
        try:
            gas_limit = self.web3.eth.estimate_gas({
                **tx_params,
                'from': wallet_address,
            })
        except Exception:
            gas_limit = 50000  # Approve typically costs ~45k gas

        # Get gas price
        gas_estimate = self.gas_optimizer.estimate_gas(tx_params, gas_strategy)
        if gas_estimate:
            max_fee = gas_estimate.max_fee_per_gas
        else:
            max_fee = float(Web3.from_wei(self.web3.eth.gas_price, 'gwei'))

        transaction = {
            **tx_params,
            'gas': gas_limit,
            'gasPrice': self.web3.to_wei(max_fee, 'gwei'),
            'nonce': self.web3.eth.get_transaction_count(wallet_address),
            'chainId': self.config.chain_ids.get('ethereum', 1),
        }

        result = {
            'transaction': transaction,
            'wallet_address': wallet_address,
            'token_address': token_address,
            'spender': spender,
            'amount': amount,
            'gas_limit': gas_limit,
            'status': 'prepared',
            'simulation': None,
        }

        # Simulate if requested
        if simulate:
            simulation = self.simulator.simulate_approval(
                token_address, spender, amount, wallet_address
            )
            result['simulation'] = {
                'success': simulation.success,
                'error': simulation.error,
            }
            if not simulation.success:
                result['status'] = 'simulation_failed'

        return result

    def check_and_prepare_approval(
        self,
        token_address: str,
        spender: str,
        amount_in_wei: int,
    ) -> Optional[Dict[str, Any]]:
        """Check if approval is needed and prepare if so.

        Args:
            token_address: Token contract address
            spender: Spender address (router)
            amount_in_wei: Amount to approve

        Returns:
            Prepared approval transaction if needed, None if already approved
        """
        is_approved = self.simulator.check_token_approval(
            token_address,
            self.wallet.wallet_address,
            spender,
            amount_in_wei
        )

        if is_approved:
            logger.debug(f"Token {token_address[:10]}... already approved for {spender[:10]}...")
            return None

        logger.info(f"Token {token_address[:10]}... needs approval for {spender[:10]}...")
        return self.prepare_token_approval(
            token_address=token_address,
            spender=spender,
            amount=2**256 - 1,  # Max uint256
        )