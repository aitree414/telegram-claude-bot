"""Trade orchestrator for onchain sniper functionality.

This module coordinates the complete trade execution workflow:
signal validation -> trade execution -> status tracking.

It integrates the risk manager, trade executor, and database
into a unified trade processing pipeline.
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Any, List, Callable
from datetime import datetime
from dataclasses import dataclass

from web3 import Web3

from bot.config_web3 import get_web3_config
from .database import (
    Signal, SignalType, Trade, TradeStatus, Chain,
    get_onchain_database, OnchainDatabase
)
from .monitor import BlockchainMonitor, MultiChainMonitor
from .signal_generator import OnchainSignalGenerator
from .risk_manager import RiskManager
from .trader import TradeExecutor, TradeExecutionError
from .wallet_manager import WalletManager

logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    """Result of processing a single signal."""
    signal_id: int
    signal_type: SignalType
    success: bool
    trade_id: Optional[int] = None
    error: Optional[str] = None
    duration_ms: float = 0


@dataclass
class OrchestratorConfig:
    """Configuration for the trade orchestrator."""
    poll_interval: int = 30  # Seconds between signal polls
    max_signals_per_cycle: int = 10
    max_retries: int = 3
    retry_delay_base: int = 10  # Base retry delay in seconds
    enable_auto_trading: bool = True
    enable_simulation: bool = True
    default_gas_strategy: str = 'balanced'
    default_dex: str = 'uniswap_v2'


class TradeOrchestrator:
    """Coordinates the complete trade execution pipeline.

    The orchestrator manages the full lifecycle of trade processing:
    1. Poll for pending signals from the database
    2. Validate signals through risk management
    3. Execute trades through the executor
    4. Track and update trade status
    5. Handle errors and retries
    """

    def __init__(self, config=None, database=None):
        """Initialize trade orchestrator.

        Args:
            config: Web3Config instance
            database: OnchainDatabase instance
        """
        self.config = config or get_web3_config()
        self.database = database or get_onchain_database()
        self.orchestrator_config = OrchestratorConfig()

        # Web3 instances per chain
        self._web3_instances: Dict[Chain, Web3] = {}
        self._executors: Dict[Chain, TradeExecutor] = {}
        self._monitors: Dict[Chain, BlockchainMonitor] = {}

        # Central components
        self.risk_manager = RiskManager(self.config, self.database)
        self.signal_generator = OnchainSignalGenerator(self.config)
        self.wallet = WalletManager(self.config)

        # Runtime state
        self.is_running = False
        self._stop_event = asyncio.Event()
        self._processing_stats = {
            'total_signals_processed': 0,
            'successful_trades': 0,
            'failed_trades': 0,
            'last_cycle_duration': 0,
        }

        logger.info("Trade orchestrator initialized")

    # ==================== Web3 Management ====================

    def _get_web3_for_chain(self, chain: Chain) -> Optional[Web3]:
        """Get or create Web3 instance for a chain.

        Args:
            chain: Target chain

        Returns:
            Web3 instance or None if chain not configured
        """
        if chain in self._web3_instances:
            return self._web3_instances[chain]

        rpc_url = self.config.get_rpc_url(chain.value if isinstance(chain, Chain) else chain)
        if not rpc_url:
            logger.error(f"No RPC URL configured for {chain}")
            return None

        try:
            from web3 import Web3
            from web3.middleware import geth_poa_middleware

            web3 = Web3(Web3.HTTPProvider(rpc_url))

            # Add POA middleware for non-ETH chains (not needed in web3.py v7+)
            if chain in [Chain.BSC, Chain.POLYGON, Chain.AVALANCHE]:
                try:
                    web3.middleware_onion.inject(geth_poa_middleware, layer=0)
                except TypeError:
                    pass  # web3.py v7+ auto-detects PoA chains

            if not web3.is_connected():
                logger.error(f"Failed to connect to {chain} RPC")
                return None

            self._web3_instances[chain] = web3
            logger.info(f"Connected to {chain} at block {web3.eth.block_number}")

            return web3

        except Exception as e:
            logger.error(f"Failed to create Web3 instance for {chain}: {e}")
            return None

    def _get_executor(self, chain: Chain) -> Optional[TradeExecutor]:
        """Get or create trade executor for a chain."""
        if chain in self._executors:
            return self._executors[chain]

        web3 = self._get_web3_for_chain(chain)
        if not web3:
            return None

        executor = TradeExecutor(
            web3=web3,
            chain=chain,
            config=self.config,
            database=self.database,
        )

        self._executors[chain] = executor
        return executor

    # ==================== Signal Processing ====================

    async def process_pending_signals(self) -> List[ProcessingResult]:
        """Process all pending trading signals.

        Main processing pipeline:
        1. Fetch pending signals from database
        2. Validate each signal
        3. Execute validated trades
        4. Update signal status

        Returns:
            List of processing results
        """
        if not self.wallet.is_wallet_available():
            logger.warning("Wallet not available, skipping signal processing")
            return []

        # Fetch pending signals
        signals = self.database.get_pending_signals(
            self.orchestrator_config.max_signals_per_cycle
        )

        if not signals:
            logger.debug("No pending signals to process")
            return []

        logger.info(f"Processing {len(signals)} pending signals")
        results = []

        for signal in signals:
            start_time = time.time()
            result = await self._process_single_signal(signal)
            result.duration_ms = (time.time() - start_time) * 1000
            results.append(result)

        # Update stats
        self._processing_stats['total_signals_processed'] += len(results)
        self._processing_stats['successful_trades'] += sum(1 for r in results if r.success)
        self._processing_stats['failed_trades'] += sum(1 for r in results if not r.success)

        logger.info(
            f"Processed {len(results)} signals: "
            f"{self._processing_stats['successful_trades']} successful, "
            f"{self._processing_stats['failed_trades']} failed"
        )

        return results

    async def _process_single_signal(self, signal: Signal) -> ProcessingResult:
        """Process a single trading signal.

        Args:
            signal: Signal to process

        Returns:
            Processing result
        """
        signal_id = signal.id
        signal_type = signal.signal_type

        logger.debug(f"Processing signal {signal_id}: {signal_type}")

        # 1. Validate signal
        is_valid, reason = self.risk_manager.validate_trade(signal)

        if not is_valid:
            logger.info(f"Signal {signal_id} rejected: {reason}")
            # Mark as processed to avoid infinite retry
            signal.processed = True
            return ProcessingResult(
                signal_id=signal_id,
                signal_type=signal_type,
                success=False,
                error=reason,
            )

        # 2. Skip HOLD signals
        if signal_type == SignalType.HOLD:
            signal.processed = True
            return ProcessingResult(
                signal_id=signal_id,
                signal_type=signal_type,
                success=True,
                error="HOLD signal, no trade needed",
            )

        # 3. Get executor for the chain
        executor = self._get_executor(signal.chain)
        if not executor:
            error_msg = f"No executor available for {signal.chain}"
            signal.processed = True
            return ProcessingResult(
                signal_id=signal_id,
                signal_type=signal_type,
                success=False,
                error=error_msg,
            )

        # 4. Execute trade
        trade = None
        try:
            if signal_type == SignalType.BUY:
                trade = await executor.execute_buy(
                    signal=signal,
                    dex_name=self.orchestrator_config.default_dex,
                    gas_strategy=self.orchestrator_config.default_gas_strategy,
                )
            elif signal_type == SignalType.SELL:
                # For sell signals, we need an existing trade
                # TODO: Implement sell execution
                logger.warning(f"Sell signal {signal_id} received but sell execution not yet implemented")
                signal.processed = True
                return ProcessingResult(
                    signal_id=signal_id,
                    signal_type=signal_type,
                    success=False,
                    error="Sell execution not implemented",
                )
            else:
                signal.processed = True
                return ProcessingResult(
                    signal_id=signal_id,
                    signal_type=signal_type,
                    success=True,
                    error=f"Unhandled signal type: {signal_type}",
                )

        except Exception as e:
            logger.error(f"Signal {signal_id} execution error: {e}")
            signal.processed = True
            return ProcessingResult(
                signal_id=signal_id,
                signal_type=signal_type,
                success=False,
                error=str(e),
            )

        # 5. Process result
        if trade:
            self._processing_stats['successful_trades'] += 1
            signal.processed = True
            if hasattr(signal, 'trade_id'):
                signal.trade_id = trade.id

            return ProcessingResult(
                signal_id=signal_id,
                signal_type=signal_type,
                success=True,
                trade_id=trade.id,
            )

        # Trade execution started but no trade record created
        signal.processed = True
        return ProcessingResult(
            signal_id=signal_id,
            signal_type=signal_type,
            success=False,
            error="Trade execution failed (no trade record)",
        )

    # ==================== Continuous Processing ====================

    async def start_continuous_processing(self) -> None:
        """Start the continuous signal processing loop.

        Polls for new signals at a configurable interval
        and processes them automatically.
        """
        if self.is_running:
            logger.warning("Orchestrator is already running")
            return

        self.is_running = True
        self._stop_event.clear()

        logger.info(
            f"Starting continuous processing "
            f"(interval: {self.orchestrator_config.poll_interval}s, "
            f"max signals: {self.orchestrator_config.max_signals_per_cycle})"
        )

        if not self.wallet.is_wallet_available():
            logger.warning("Running in read-only mode (no wallet available)")

        while self.is_running:
            cycle_start = time.time()

            try:
                # Process signals
                if self.wallet.is_wallet_available():
                    results = await self.process_pending_signals()

                    # Log results
                    if results:
                        successful = [r for r in results if r.success]
                        failed = [r for r in results if not r.success]

                        if successful:
                            logger.info(f"Successfully processed {len(successful)} signals")
                        if failed:
                            for f in failed:
                                logger.warning(
                                    f"Signal {f.signal_id} failed: {f.error}"
                                )

                # Process pending events
                if hasattr(self.signal_generator, 'process_pending_events'):
                    self.signal_generator.process_pending_events(limit=50)

            except Exception as e:
                logger.error(f"Processing cycle error: {e}")

            # Calculate sleep time
            cycle_duration = time.time() - cycle_start
            self._processing_stats['last_cycle_duration'] = cycle_duration

            sleep_time = max(
                1,
                self.orchestrator_config.poll_interval - cycle_duration
            )

            # Wait for stop event or sleep
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=sleep_time
                )
                break  # Stop event received
            except asyncio.TimeoutError:
                continue  # Normal sleep completion

    async def stop_continuous_processing(self) -> None:
        """Stop the continuous processing loop."""
        self.is_running = False
        self._stop_event.set()
        logger.info("Stopped continuous processing")

    # ==================== Position Monitoring ====================

    async def monitor_active_positions(self) -> None:
        """Monitor active positions for stop loss/take profit triggers."""
        session = self.database.get_session()
        try:
            # Get active trades
            active_trades = session.query(Trade).filter(
                Trade.status.in_([TradeStatus.PENDING, TradeStatus.EXECUTING, TradeStatus.PARTIAL])
            ).all()

            if not active_trades:
                return

            logger.debug(f"Monitoring {len(active_trades)} active positions")

            for trade in active_trades:
                try:
                    # Get current price (simplified - would use oracle or DEX price)
                    executor = self._get_executor(trade.chain)
                    if not executor:
                        continue

                    # Check for SL/TP triggers
                    triggered = self.risk_manager.check_stop_loss_take_profit(
                        trade, trade.entry_price  # Would use actual current price
                    )

                    if triggered == 'stop_loss':
                        logger.warning(f"Stop loss triggered for trade {trade.id}")
                        # Execute sell if stop loss triggered
                        if self.orchestrator_config.enable_auto_trading:
                            await executor.execute_sell(trade)

                    elif triggered == 'take_profit':
                        logger.info(f"Take profit triggered for trade {trade.id}")
                        if self.orchestrator_config.enable_auto_trading:
                            await executor.execute_sell(trade)

                except Exception as e:
                    logger.error(f"Failed to monitor trade {trade.id}: {e}")

        except Exception as e:
            logger.error(f"Position monitoring error: {e}")
        finally:
            session.close()

    # ==================== Status & Reporting ====================

    def get_status(self) -> Dict[str, Any]:
        """Get orchestrator status summary."""
        status = {
            'is_running': self.is_running,
            'wallet_available': self.wallet.is_wallet_available(),
            'wallet_address': self.wallet.wallet_address,
            'config': {
                'poll_interval': self.orchestrator_config.poll_interval,
                'max_signals_per_cycle': self.orchestrator_config.max_signals_per_cycle,
                'enable_auto_trading': self.orchestrator_config.enable_auto_trading,
                'default_gas_strategy': self.orchestrator_config.default_gas_strategy,
            },
            'stats': self._processing_stats,
            'risk_summary': self.risk_manager.get_risk_summary(),
            'executors': {},
        }

        for chain, executor in self._executors.items():
            status['executors'][chain.value] = executor.get_status()

        return status

    def get_pipeline_status(self) -> Dict[str, Any]:
        """Get the complete pipeline status including all components."""
        return {
            'orchestrator': self.get_status(),
            'database_stats': self.database.get_stats(),
            'signal_generator_stats': self.signal_generator.get_stats()
            if hasattr(self.signal_generator, 'get_stats') else {},
        }