"""Blockchain monitoring framework for onchain sniper functionality.

This module provides real-time monitoring of blockchain events including:
- New token creation (ERC20/ERC721 contracts)
- Large transfers (above threshold)
- Liquidity additions/removals on DEXes
- Contract interactions and function calls
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum

from web3 import Web3
from web3.providers import HTTPProvider, WebsocketProvider
from web3.middleware import geth_poa_middleware

from .database import OnchainEvent, EventType, Chain, get_onchain_database
from bot.config_web3 import get_web3_config

logger = logging.getLogger(__name__)


@dataclass
class MonitorConfig:
    """Configuration for blockchain monitoring."""
    chain: Chain
    rpc_url: str
    use_websocket: bool = False
    poll_interval: int = 30  # seconds
    max_blocks_per_poll: int = 1000
    confirmation_blocks: int = 3


class EventDetector:
    """Base class for blockchain event detectors."""

    def __init__(self, web3: Web3, config: MonitorConfig):
        self.web3 = web3
        self.config = config
        self.last_block = 0

    async def detect_events(self, from_block: int, to_block: int) -> List[Dict[str, Any]]:
        """Detect events in the given block range.

        Args:
            from_block: Starting block number
            to_block: Ending block number

        Returns:
            List of detected events
        """
        raise NotImplementedError

    def should_process_block(self, block_number: int) -> bool:
        """Check if a block should be processed (based on confirmations)."""
        current_block = self.web3.eth.block_number
        return current_block - block_number >= self.config.confirmation_blocks


class TokenCreationDetector(EventDetector):
    """Detect new token creation events."""

    async def detect_events(self, from_block: int, to_block: int) -> List[Dict[str, Any]]:
        """Detect new token creation events."""
        events = []

        try:
            # Get all contract creations in block range
            for block_num in range(from_block, to_block + 1):
                block = self.web3.eth.get_block(block_num, full_transactions=True)

                for tx in block.transactions:
                    if tx.to is None:  # Contract creation transaction
                        # Check if it's likely a token contract
                        receipt = self.web3.eth.get_transaction_receipt(tx.hash)

                        if receipt.contractAddress:
                            # Try to detect token standard
                            token_type = self._detect_token_type(receipt.contractAddress)

                            event = {
                                'event_type': EventType.TOKEN_CREATED,
                                'chain': self.config.chain,
                                'block_number': block_num,
                                'block_timestamp': block.timestamp,
                                'transaction_hash': tx.hash.hex(),
                                'contract_address': receipt.contractAddress,
                                'from_address': tx['from'],
                                'to_address': None,
                                'token_address': receipt.contractAddress,
                                'amount': float(self.web3.from_wei(tx.value, 'ether')),
                                'event_data': {
                                    'creator': tx['from'],
                                    'gas_used': receipt.gasUsed,
                                    'gas_price': float(self.web3.from_wei(tx.gasPrice, 'gwei')),
                                    'token_type': token_type,
                                }
                            }
                            events.append(event)

        except Exception as e:
            logger.error(f"Error detecting token creation events: {e}")

        return events

    def _detect_token_type(self, contract_address: str) -> str:
        """Detect the type of token contract."""
        try:
            # ERC20 detection
            erc20_abi = [
                {"constant": True, "inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "type": "function"},
                {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
                {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
                {"constant": True, "inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
            ]

            contract = self.web3.eth.contract(address=contract_address, abi=erc20_abi)

            # Try to call ERC20 functions
            try:
                name = contract.functions.name().call()
                symbol = contract.functions.symbol().call()
                decimals = contract.functions.decimals().call()
                return "ERC20"
            except:
                pass

            # Could add ERC721 detection here
            return "UNKNOWN"

        except Exception as e:
            logger.debug(f"Failed to detect token type for {contract_address}: {e}")
            return "UNKNOWN"


class LargeTransferDetector(EventDetector):
    """Detect large token transfers."""

    def __init__(self, web3: Web3, config: MonitorConfig, threshold_eth: float = 50.0):
        super().__init__(web3, config)
        self.threshold_eth = threshold_eth

    async def detect_events(self, from_block: int, to_block: int) -> List[Dict[str, Any]]:
        """Detect large transfers."""
        events = []

        try:
            # ERC20 Transfer event signature
            transfer_event_signature = self.web3.keccak(text="Transfer(address,address,uint256)").hex()

            for block_num in range(from_block, to_block + 1):
                block = self.web3.eth.get_block(block_num)

                # Get logs for transfer events
                logs = self.web3.eth.get_logs({
                    'fromBlock': block_num,
                    'toBlock': block_num,
                    'topics': [transfer_event_signature]
                })

                for log in logs:
                    # Parse transfer event
                    # This is simplified - actual implementation would decode the log data
                    # and check token value against USD value

                    # For now, we'll just record all transfer events
                    # In production, you'd add filtering logic here
                    pass

        except Exception as e:
            logger.error(f"Error detecting large transfers: {e}")

        return events


class BlockchainMonitor:
    """Main blockchain monitoring class."""

    def __init__(self, config: MonitorConfig):
        self.config = config
        self.web3 = self._create_web3_instance()
        self.database = get_onchain_database()
        self.detectors: List[EventDetector] = []
        self.is_running = False
        self.last_processed_block = 0

        # Initialize detectors
        self._initialize_detectors()

        logger.info(f"Initialized blockchain monitor for {config.chain}")

    def _create_web3_instance(self) -> Web3:
        """Create Web3 instance based on configuration."""
        if self.config.use_websocket:
            provider = WebsocketProvider(self.config.rpc_url)
        else:
            provider = HTTPProvider(self.config.rpc_url)

        web3 = Web3(provider)

        # Add POA middleware for chains like BSC, Polygon
        if self.config.chain in [Chain.BSC, Chain.POLYGON, Chain.AVALANCHE]:
            web3.middleware_onion.inject(geth_poa_middleware, layer=0)

        # Test connection
        if not web3.is_connected():
            raise ConnectionError(f"Failed to connect to {self.config.chain} RPC")

        logger.info(f"Connected to {self.config.chain} at block {web3.eth.block_number}")
        return web3

    def _initialize_detectors(self) -> None:
        """Initialize event detectors."""
        web3_config = get_web3_config()

        # Token creation detector
        self.detectors.append(TokenCreationDetector(self.web3, self.config))

        # Large transfer detector
        threshold = web3_config.large_transfer_threshold_eth
        self.detectors.append(LargeTransferDetector(self.web3, self.config, threshold))

        logger.info(f"Initialized {len(self.detectors)} event detectors")

    async def start(self) -> None:
        """Start the monitoring loop."""
        if self.is_running:
            logger.warning("Monitor is already running")
            return

        self.is_running = True

        # Get starting block
        self.last_processed_block = self.web3.eth.block_number - self.config.confirmation_blocks
        logger.info(f"Starting monitoring from block {self.last_processed_block}")

        # Start monitoring loop
        await self._monitor_loop()

    async def stop(self) -> None:
        """Stop the monitoring loop."""
        self.is_running = False
        logger.info("Stopping blockchain monitor")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self.is_running:
            try:
                await self._process_new_blocks()
                await asyncio.sleep(self.config.poll_interval)
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(5)  # Short sleep on error

    async def _process_new_blocks(self) -> None:
        """Process new blocks since last check."""
        current_block = self.web3.eth.block_number
        confirmed_block = current_block - self.config.confirmation_blocks

        if confirmed_block <= self.last_processed_block:
            return  # No new confirmed blocks

        # Limit the number of blocks to process
        from_block = self.last_processed_block + 1
        to_block = min(confirmed_block, from_block + self.config.max_blocks_per_poll - 1)

        logger.info(f"Processing blocks {from_block} to {to_block} on {self.config.chain}")

        # Process blocks with each detector
        total_events = 0
        for detector in self.detectors:
            try:
                events = await detector.detect_events(from_block, to_block)

                # Save events to database
                for event_data in events:
                    self.database.add_event(event_data)

                total_events += len(events)

                if events:
                    logger.info(f"Detector {detector.__class__.__name__} found {len(events)} events")

            except Exception as e:
                logger.error(f"Error in detector {detector.__class__.__name__}: {e}")

        # Update last processed block
        self.last_processed_block = to_block

        if total_events > 0:
            logger.info(f"Total events detected: {total_events}")

    def get_status(self) -> Dict[str, Any]:
        """Get current monitor status."""
        return {
            'chain': self.config.chain,
            'is_running': self.is_running,
            'last_processed_block': self.last_processed_block,
            'current_block': self.web3.eth.block_number,
            'detectors': [d.__class__.__name__ for d in self.detectors],
            'web3_connected': self.web3.is_connected(),
        }


class MultiChainMonitor:
    """Monitor multiple blockchain chains simultaneously."""

    def __init__(self):
        self.web3_config = get_web3_config()
        self.monitors: Dict[Chain, BlockchainMonitor] = {}
        self.is_running = False

    async def start(self) -> None:
        """Start monitoring all configured chains."""
        if self.is_running:
            return

        self.is_running = True

        # Create monitors for each active chain
        active_chains = self.web3_config.get_active_chains()

        for chain_name in active_chains:
            try:
                chain = Chain(chain_name)
                rpc_url = self.web3_config.get_rpc_url(chain_name)

                if not rpc_url:
                    logger.warning(f"No RPC URL configured for {chain_name}")
                    continue

                config = MonitorConfig(
                    chain=chain,
                    rpc_url=rpc_url,
                    poll_interval=self.web3_config.monitor_interval,
                    confirmation_blocks=self.web3_config.confirmation_blocks,
                )

                monitor = BlockchainMonitor(config)
                self.monitors[chain] = monitor

                # Start monitor in background
                asyncio.create_task(self._start_monitor_safe(monitor))

                logger.info(f"Started monitor for {chain_name}")

            except Exception as e:
                logger.error(f"Failed to start monitor for {chain_name}: {e}")

    async def _start_monitor_safe(self, monitor: BlockchainMonitor) -> None:
        """Start a monitor with error handling."""
        try:
            await monitor.start()
        except Exception as e:
            logger.error(f"Monitor for {monitor.config.chain} failed: {e}")

    async def stop(self) -> None:
        """Stop all monitors."""
        self.is_running = False

        for monitor in self.monitors.values():
            try:
                await monitor.stop()
            except Exception as e:
                logger.error(f"Error stopping monitor for {monitor.config.chain}: {e}")

        logger.info("Stopped all blockchain monitors")

    def get_status(self) -> Dict[str, Any]:
        """Get status of all monitors."""
        status = {
            'is_running': self.is_running,
            'total_monitors': len(self.monitors),
            'monitors': {},
        }

        for chain, monitor in self.monitors.items():
            status['monitors'][chain.value] = monitor.get_status()

        return status