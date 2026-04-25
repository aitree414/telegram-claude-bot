"""Transaction simulation for onchain sniper functionality.

This module provides transaction simulation capabilities to verify
trades will succeed before broadcasting them to the network.
"""

import logging
from typing import Dict, Optional, Any, List
from web3 import Web3
from web3.exceptions import ContractLogicError

from bot.config_web3 import get_web3_config

logger = logging.getLogger(__name__)


class SimulationResult:
    """Result of a transaction simulation."""

    def __init__(
        self,
        success: bool,
        gas_used: int = 0,
        error: Optional[str] = None,
        return_data: Optional[Any] = None
    ):
        """Initialize simulation result.

        Args:
            success: Whether simulation succeeded
            gas_used: Gas used in simulation
            error: Error message if simulation failed
            return_data: Return data from simulation
        """
        self.success = success
        self.gas_used = gas_used
        self.error = error
        self.return_data = return_data

    def __repr__(self) -> str:
        if self.success:
            return f"<SimulationResult: success (gas: {self.gas_used})>"
        return f"<SimulationResult: failed - {self.error}>"


class TxSimulator:
    """Transaction simulator for verifying trades before execution.

    Uses eth_call to simulate transactions without broadcasting them,
    catching potential errors like slippage, insufficient balance, etc.
    """

    def __init__(self, web3: Web3, config=None):
        """Initialize transaction simulator.

        Args:
            web3: Web3 instance
            config: Web3Config instance, defaults to global config
        """
        self.web3 = web3
        self.config = config or get_web3_config()

    def simulate_transaction(
        self,
        tx_params: Dict[str, Any],
        from_address: str,
        block_identifier: Optional[str] = 'latest'
    ) -> SimulationResult:
        """Simulate a transaction using eth_call.

        Args:
            tx_params: Transaction parameters
            from_address: Address to simulate from
            block_identifier: Block to simulate on

        Returns:
            SimulationResult with success/failure info
        """
        try:
            # Build call parameters
            call_params = {
                'from': from_address,
                'to': tx_params.get('to'),
                'data': tx_params.get('data', '0x'),
                'value': tx_params.get('value', 0),
            }

            # Add gas for more accurate simulation
            call_params['gas'] = tx_params.get('gas', 300000)

            # Execute eth_call
            result = self.web3.eth.call(call_params, block_identifier)

            # Estimate gas for the actual transaction
            try:
                gas_estimate = self.web3.eth.estimate_gas({
                    **call_params,
                    'from': from_address,
                })
            except Exception as e:
                gas_estimate = 0
                logger.warning(f"Gas estimation failed: {e}")

            logger.debug(f"Transaction simulation succeeded (gas: {gas_estimate})")
            return SimulationResult(
                success=True,
                gas_used=gas_estimate,
                return_data=result.hex() if isinstance(result, bytes) else result
            )

        except ContractLogicError as e:
            logger.warning(f"Transaction simulation failed (contract error): {e}")
            return SimulationResult(success=False, error=str(e))

        except Exception as e:
            error_msg = str(e)

            # Check for common errors
            if 'insufficient funds' in error_msg.lower():
                logger.warning("Simulation failed: insufficient funds")
                return SimulationResult(success=False, error="Insufficient funds for gas")

            if 'slippage' in error_msg.lower() or 'too little received' in error_msg.lower():
                logger.warning("Simulation failed: slippage too high")
                return SimulationResult(success=False, error="Slippage exceeded")

            if 'transfer' in error_msg.lower() and 'failed' in error_msg.lower():
                logger.warning("Simulation failed: transfer failed")
                return SimulationResult(success=False, error="Token transfer failed")

            if 'execution reverted' in error_msg.lower():
                # Try to extract revert reason
                reason = self._extract_revert_reason(error_msg)
                logger.warning(f"Transaction reverted: {reason}")
                return SimulationResult(success=False, error=reason or "Execution reverted")

            logger.error(f"Transaction simulation failed: {error_msg}")
            return SimulationResult(success=False, error=error_msg)

    def simulate_swap(
        self,
        token_in: str,
        token_out: str,
        amount_in: int,
        router_address: str,
        swap_data: str,
        from_address: str
    ) -> SimulationResult:
        """Simulate a swap transaction.

        Args:
            token_in: Input token address
            token_out: Output token address
            amount_in: Input amount in wei
            router_address: DEX router address
            swap_data: Encoded swap function data
            from_address: Address to simulate from

        Returns:
            SimulationResult
        """
        tx_params = {
            'to': router_address,
            'data': swap_data,
            'value': amount_in,
            'gas': 300000,
        }

        return self.simulate_transaction(tx_params, from_address)

    def check_token_approval(
        self,
        token_address: str,
        owner: str,
        spender: str,
        amount_required: int
    ) -> bool:
        """Check if token approval is sufficient.

        Args:
            token_address: Token contract address
            owner: Token owner address
            spender: Spender address (router, etc.)
            amount_required: Minimum required approval amount in wei

        Returns:
            True if current approval is sufficient
        """
        try:
            # ERC20 allowance ABI
            allowance_abi = [
                {
                    "constant": True,
                    "inputs": [
                        {"name": "_owner", "type": "address"},
                        {"name": "_spender", "type": "address"}
                    ],
                    "name": "allowance",
                    "outputs": [{"name": "", "type": "uint256"}],
                    "type": "function"
                }
            ]

            contract = self.web3.eth.contract(address=token_address, abi=allowance_abi)
            current_allowance = contract.functions.allowance(owner, spender).call()

            return current_allowance >= amount_required

        except Exception as e:
            logger.error(f"Failed to check token approval: {e}")
            return False

    def simulate_approval(
        self,
        token_address: str,
        spender: str,
        amount: int,
        from_address: str
    ) -> SimulationResult:
        """Simulate a token approval transaction.

        Args:
            token_address: Token contract address
            spender: Spender address
            amount: Amount to approve in wei
            from_address: Address to simulate from

        Returns:
            SimulationResult
        """
        # ERC20 approve ABI
        approve_abi = {
            "constant": False,
            "inputs": [
                {"name": "spender", "type": "address"},
                {"name": "amount", "type": "uint256"}
            ],
            "name": "approve",
            "outputs": [{"name": "", "type": "bool"}],
            "type": "function"
        }

        # Encode the approve function call
        contract = self.web3.eth.contract(
            address=token_address,
            abi=[approve_abi]
        )
        approve_data = contract.encodeABI(fn_name="approve", args=[spender, amount])

        tx_params = {
            'to': token_address,
            'data': approve_data,
            'value': 0,
        }

        return self.simulate_transaction(tx_params, from_address)

    def _extract_revert_reason(self, error_msg: str) -> Optional[str]:
        """Try to extract revert reason from error message."""
        import re

        # Try to find revert reason in hex
        hex_match = re.search(r'0x([0-9a-fA-F]{64,})', error_msg)
        if hex_match:
            try:
                # Decode hex string
                hex_str = hex_match.group(0)
                # Need at least 4 bytes for selector + 32 bytes for offset + 32 bytes for length + data
                if len(hex_str) >= 138:  # 0x + 4 + 32 + 32 + minimal data
                    # Skip function selector (4 bytes)
                    data_hex = hex_str[10:]
                    # Parse offset and length
                    offset = int(data_hex[:64], 16) * 2
                    length = int(data_hex[64:128], 16) * 2
                    reason_hex = data_hex[128 + offset:128 + offset + length]
                    reason = bytes.fromhex(reason_hex).decode('utf-8', errors='ignore')
                    if reason:
                        return f"Reverted: {reason}"
            except Exception:
                pass

        return error_msg[:200] if error_msg else None


class SimulationError(Exception):
    """Exception raised when transaction simulation fails."""
    pass