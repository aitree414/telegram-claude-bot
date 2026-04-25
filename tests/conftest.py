"""Shared pytest fixtures for onchain tests."""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set test environment variables
os.environ.setdefault('ETH_RPC_URL', 'https://eth-mainnet.g.alchemy.com/v2/test')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test_token')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test_key')

from bot.config_web3 import get_web3_config


@pytest.fixture
def web3_config():
    """Get Web3 config instance."""
    return get_web3_config()


@pytest.fixture
def mock_web3():
    """Create a mock Web3 instance."""
    mock = MagicMock()

    # Mock eth properties
    mock.eth.block_number = 20000000
    mock.eth.gas_price = 50000000000  # 50 Gwei
    mock.eth.chain_id = 1

    # Mock is_connected
    mock.is_connected.return_value = True

    # Mock get_block
    mock.eth.get_block.return_value = {
        'number': 20000000,
        'timestamp': 1700000000,
        'baseFeePerGas': 25000000000,  # 25 Gwei
    }

    # Mock get_transaction_count
    mock.eth.get_transaction_count.return_value = 100

    # Mock fee_history for EIP-1559
    mock.eth.fee_history.return_value = {
        'oldestBlock': 19999995,
        'baseFeePerGas': [25000000000] * 6,
        'reward': [[1000000000, 2000000000, 3000000000]] * 5,
        'gasUsedRatio': [0.5] * 5,
    }

    # Mock estimate_gas
    mock.eth.estimate_gas.return_value = 200000

    # Mock wei conversion
    mock.from_wei = MagicMock(side_effect=lambda v, unit: v / 10**18 if unit == 'ether' else v / 10**9 if unit == 'gwei' else v)
    mock.to_wei = MagicMock(side_effect=lambda v, unit: int(v * 10**18) if unit == 'ether' else int(v * 10**9) if unit == 'gwei' else int(v))

    # Mock keccak
    mock.keccak = MagicMock(return_value=b'\x00' * 32)
    mock.keccak.text = MagicMock(return_value=b'\x00' * 32)

    return mock


@pytest.fixture
def mock_db():
    """Create a mock database."""
    mock = MagicMock()

    # Mock get_session
    mock_session = MagicMock()
    mock.get_session.return_value = mock_session

    # Mock query methods
    mock.is_blacklisted.return_value = False
    mock.add_trade.return_value = MagicMock(id=1)
    mock.get_pending_signals.return_value = []
    mock.add_execution_log.return_value = MagicMock(id=1)
    mock.get_stats.return_value = {}

    return mock


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary SQLite database for testing."""
    db_path = tmp_path / "test_onchain.db"
    from onchain.database import OnchainDatabase
    db = OnchainDatabase(str(db_path))
    yield db
    # Cleanup
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def sample_signal():
    """Create a sample signal for testing."""
    from onchain.database import Signal, SignalType, Chain
    from datetime import datetime, timedelta

    signal = MagicMock(spec=Signal)
    signal.id = 1
    signal.signal_type = SignalType.BUY
    signal.chain = Chain.ETHEREUM
    signal.token_address = '0x' + 'a' * 40
    signal.token_symbol = 'TEST'
    signal.token_name = 'Test Token'
    signal.base_token = '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
    signal.confidence_score = 0.75
    signal.risk_score = 0.3
    signal.expected_return = 15.0
    signal.suggested_amount_eth = 0.05
    signal.suggested_price = 0.001
    signal.stop_loss = 0.10
    signal.take_profit = 0.30
    signal.generated_at = datetime.utcnow()
    signal.expires_at = datetime.utcnow() + timedelta(hours=1)
    signal.processed = False
    signal.trade_id = None
    signal.signal_data = {'event_id': 1}

    return signal


@pytest.fixture
def sample_trade():
    """Create a sample trade for testing."""
    from onchain.database import Trade, TradeStatus, SignalType, Chain
    from datetime import datetime

    trade = MagicMock(spec=Trade)
    trade.id = 1
    trade.chain = Chain.ETHEREUM
    trade.token_address = '0x' + 'a' * 40
    trade.token_symbol = 'TEST'
    trade.token_name = 'Test Token'
    trade.trade_type = SignalType.BUY
    trade.amount_eth = 0.05
    trade.amount_token = 50000.0
    trade.entry_price = 0.000001
    trade.current_price = 0.0000012
    trade.stop_loss = 0.10
    trade.take_profit = 0.30
    trade.transaction_hash = '0x' + 'b' * 64
    trade.status = TradeStatus.EXECUTING
    trade.executed_at = datetime.utcnow()
    trade.pnl_eth = 0.0
    trade.pnl_percent = 0.0

    return trade


@pytest.fixture
def mock_wallet_config():
    """Create mock config with private key."""
    config = MagicMock()
    config.private_key = '0x' + 'a' * 64  # Valid hex key
    config.encrypted_private_key = None
    config.wallet_address = None
    return config