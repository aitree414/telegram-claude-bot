"""Onchain sniper module for Telegram Claude Bot.

This module provides blockchain monitoring and automated trading functionality
for the Telegram Claude Bot. It includes modules for monitoring blockchain events,
generating trading signals, executing trades, and managing risks.
"""

__version__ = "0.1.0"
__author__ = "Telegram Claude Bot Team"

# Import key components for easy access
from .database import OnchainDatabase
from .monitor import BlockchainMonitor

# Optional imports for modules that may not exist yet
try:
    from .signal_generator import OnchainSignalGenerator
except ImportError:
    OnchainSignalGenerator = None

try:
    from .trader import OnchainTrader
except ImportError:
    OnchainTrader = None

try:
    from .risk_manager import RiskManager
except ImportError:
    RiskManager = None

try:
    from .wallet_manager import WalletManager
except ImportError:
    WalletManager = None

try:
    from .dex_client import DEXClient, UniswapV2Client, DEXClientFactory
except ImportError:
    DEXClient = None
    UniswapV2Client = None
    DEXClientFactory = None

try:
    from .gas_optimizer import GasOptimizer, GasEstimator
except ImportError:
    GasOptimizer = None
    GasEstimator = None

try:
    from .tx_simulator import TxSimulator, SimulationResult
except ImportError:
    TxSimulator = None
    SimulationResult = None

try:
    from .transaction_builder import TransactionBuilder
except ImportError:
    TransactionBuilder = None

try:
    from .orchestrator import TradeOrchestrator, OrchestratorConfig, ProcessingResult
except ImportError:
    TradeOrchestrator = None
    OrchestratorConfig = None
    ProcessingResult = None

# Define what's available when using `from onchain import *`
__all__ = [
    "OnchainDatabase",
    "BlockchainMonitor",
    "OnchainSignalGenerator",
    "OnchainTrader",
    "RiskManager",
    "WalletManager",
    "DEXClient",
    "UniswapV2Client",
    "DEXClientFactory",
    "GasOptimizer",
    "GasEstimator",
    "TxSimulator",
    "SimulationResult",
    "TransactionBuilder",
    "TradeOrchestrator",
    "OrchestratorConfig",
    "ProcessingResult",
]