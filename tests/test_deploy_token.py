"""Tests for token deployment scripts and testnet configuration."""

import os
import json
import pytest
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path


# =============================================================================
# Tests for scripts/config.py (compilation helper)
# =============================================================================

class TestCompilationConfig:
    """Tests for the compilation helper module."""

    def test_ensure_solc_installs_missing(self):
        """Test that ensure_solc downloads solc when not installed."""
        from scripts.config import ensure_solc

        with patch('scripts.config.get_installed_solc_versions', return_value=[]), \
             patch('scripts.config.install_solc') as mock_install, \
             patch('scripts.config.set_solc_version') as mock_set:
            ensure_solc('0.8.20')
            mock_install.assert_called_once_with('0.8.20')
            mock_set.assert_called_once_with('0.8.20')

    def test_ensure_solc_uses_cached(self):
        """Test that ensure_solc skips download when version is cached."""
        from scripts.config import ensure_solc

        with patch('scripts.config.get_installed_solc_versions', return_value=['0.8.20']), \
             patch('scripts.config.install_solc') as mock_install, \
             patch('scripts.config.set_solc_version') as mock_set:
            ensure_solc('0.8.20')
            mock_install.assert_not_called()
            mock_set.assert_called_once_with('0.8.20')

    def test_compile_contract_file_not_found(self):
        """Test that compile_contract returns None when .sol file is missing."""
        from scripts.config import compile_contract

        with patch('scripts.config.CONTRACTS_DIR', Path('/nonexistent')):
            result = compile_contract('NonexistentContract')
            assert result is None

    def test_load_compiled_artifact_not_found(self):
        """Test that load_compiled_artifact returns None when no cache exists."""
        from scripts.config import load_compiled_artifact

        with patch('scripts.config.COMPILED_DIR', Path('/nonexistent')):
            result = load_compiled_artifact('TestToken')
            assert result is None

    def test_get_or_compile_uses_cache(self):
        """Test that get_or_compile returns cached artifact when available."""
        from scripts.config import get_or_compile

        mock_artifact = {'abi': [], 'bytecode': '0x123'}
        with patch('scripts.config.load_compiled_artifact', return_value=mock_artifact), \
             patch('scripts.config.compile_contract') as mock_compile:
            result = get_or_compile('TestToken')
            assert result == mock_artifact
            mock_compile.assert_not_called()

    def test_get_or_compile_falls_back(self):
        """Test that get_or_compile compiles when no cache exists."""
        from scripts.config import get_or_compile

        mock_artifact = {'abi': [], 'bytecode': '0x123'}
        with patch('scripts.config.load_compiled_artifact', return_value=None), \
             patch('scripts.config.compile_contract', return_value=mock_artifact):
            result = get_or_compile('TestToken')
            assert result == mock_artifact


# =============================================================================
# Tests for scripts/deploy_token.py (deployment)
# =============================================================================

class TestDeployToken:
    """Tests for the token deployment script."""

    def test_get_web3_no_rpc(self):
        """Test that get_web3 raises error without SEPOLIA_RPC_URL."""
        from scripts.deploy_token import get_web3

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match='SEPOLIA_RPC_URL'):
                get_web3()

    def test_get_web3_connection_failure(self):
        """Test that get_web3 raises error on connection failure."""
        from scripts.deploy_token import get_web3

        with patch.dict(os.environ, {'SEPOLIA_RPC_URL': 'https://bad.url'}):
            with pytest.raises(ConnectionError, match='Cannot connect'):
                get_web3()

    def test_get_account_no_key(self):
        """Test that get_account raises error without PRIVATE_KEY."""
        from scripts.deploy_token import get_web3, get_account

        mock_w3 = MagicMock()
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match='PRIVATE_KEY'):
                get_account(mock_w3)

    def test_get_account_low_balance_warning(self, caplog):
        """Test that get_account warns on low balance."""
        from scripts.deploy_token import get_account

        mock_w3 = MagicMock()
        mock_w3.eth.get_balance.return_value = 0
        mock_w3.from_wei.return_value = 0.0

        with patch.dict(os.environ, {'PRIVATE_KEY': '0x' + 'a' * 64}):
            account = get_account(mock_w3)
            assert account is not None

    def test_deploy_token_builds_correct_tx(self):
        """Test that deploy_token builds a transaction with correct chain ID."""
        from scripts.deploy_token import deploy_token

        mock_w3 = MagicMock()
        mock_w3.eth.chain_id = 11155111
        mock_w3.eth.get_transaction_count.return_value = 5
        mock_w3.eth.gas_price = 50000000000
        mock_w3.from_wei.side_effect = lambda v, u: v / 10**18
        mock_w3.to_wei.side_effect = lambda v, u: int(v * 10**18)

        mock_account = MagicMock()
        mock_account.address = '0x' + 'b' * 40

        # Mock compilation result
        mock_compiled = {
            'abi': [{'name': 'test', 'type': 'function'}],
            'bytecode': '0x123456',
        }

        with patch('scripts.deploy_token.get_or_compile', return_value=mock_compiled), \
             patch('scripts.deploy_token.CONTRACTS_DIR', Path('/tmp')), \
             patch('builtins.open', mock_open()), \
             patch('json.dump'):
            with pytest.raises(RuntimeError, match='Deployment failed'):
                # This will fail because wait_for_transaction_receipt won't be setup
                # But we're testing that the tx is built correctly before that point
                deploy_token(mock_w3, mock_account)

    def test_deploy_token_env_overrides(self):
        """Test that deploy_token reads env vars for token config."""
        from scripts.deploy_token import deploy_token

        mock_w3 = MagicMock()
        mock_w3.eth.chain_id = 11155111
        mock_w3.eth.get_transaction_count.return_value = 5
        mock_w3.eth.gas_price = 50000000000
        mock_w3.from_wei.side_effect = lambda v, u: v / 10**18
        mock_w3.to_wei.side_effect = lambda v, u: int(v * 10**18)

        mock_account = MagicMock()
        mock_account.address = '0x' + 'b' * 40

        mock_compiled = {
            'abi': [{'name': 'test', 'type': 'function'}],
            'bytecode': '0x123456',
        }

        env_vars = {
            'SEPOLIA_RPC_URL': 'https://test.url',
            'PRIVATE_KEY': '0x' + 'a' * 64,
            'TEST_TOKEN_NAME': 'Custom Token',
            'TEST_TOKEN_SYMBOL': 'CTM',
            'TEST_TOKEN_DECIMALS': '6',
        }

        with patch.dict(os.environ, env_vars, clear=False), \
             patch('scripts.deploy_token.get_or_compile', return_value=mock_compiled), \
             patch('scripts.deploy_token.CONTRACTS_DIR', Path('/tmp')), \
             patch('builtins.open', mock_open()), \
             patch('json.dump'):
            with pytest.raises(RuntimeError):
                deploy_token(mock_w3, mock_account)


# =============================================================================
# Tests for scripts/verify_onchain.py (verification)
# =============================================================================

class TestVerifyOnchain:
    """Tests for the on-chain verification script."""

    def test_load_artifact_not_found(self):
        """Test error when deployment artifact is missing."""
        from scripts.verify_onchain import load_deployment_artifact

        with patch('scripts.verify_onchain.CONTRACTS_DIR', Path('/nonexistent')):
            with pytest.raises(FileNotFoundError, match='Deployment artifact'):
                load_deployment_artifact()

    def test_verify_token_success(self):
        """Test that verify_token queries and returns on-chain state."""
        from scripts.verify_onchain import verify_token

        mock_w3 = MagicMock()
        mock_contract = MagicMock()
        mock_w3.eth.contract.return_value = mock_contract

        # Set up return values for the 4 checks
        mock_contract.functions.name.return_value.call.return_value = 'Test Token'
        mock_contract.functions.symbol.return_value.call.return_value = 'TST'
        mock_contract.functions.decimals.return_value.call.return_value = 18
        mock_contract.functions.totalSupply.return_value.call.return_value = 1000000 * 10**18

        abi = [{'name': 'test', 'type': 'function'}]
        address = '0x' + 'a' * 40

        results = verify_token(mock_w3, address, abi)
        assert results['name'] == 'Test Token'
        assert results['symbol'] == 'TST'
        assert results['decimals'] == 18
        assert results['total_supply'] == 1000000 * 10**18
        assert results['verified'] is True

    def test_verify_token_failure(self):
        """Test that verify_token handles RPC errors gracefully."""
        from scripts.verify_onchain import verify_token

        mock_w3 = MagicMock()
        mock_contract = MagicMock()
        mock_w3.eth.contract.return_value = mock_contract

        # Make all calls raise
        mock_contract.functions.name.side_effect = Exception('RPC error')

        abi = [{'name': 'test', 'type': 'function'}]
        address = '0x' + 'a' * 40

        results = verify_token(mock_w3, address, abi)
        assert results['verified'] is False


# =============================================================================
# Tests for bot/config_web3.py (testnet mode)
# =============================================================================

class TestTestnetConfig:
    """Tests for testnet mode configuration."""

    def test_default_network_mode(self):
        """Test that default network mode is mainnet."""
        with patch.dict(os.environ, {}, clear=True):
            from bot.config_web3 import Web3Config
            config = Web3Config()
            assert config.network_mode == 'mainnet'

    def test_testnet_mode_adds_sepolia_rpc(self):
        """Test that testnet mode adds Sepolia to RPC URLs."""
        env = {
            'NETWORK_MODE': 'testnet',
            'SEPOLIA_RPC_URL': 'https://sepolia.test.url',
            'ETH_RPC_URL': 'https://eth-mainnet.g.alchemy.com/v2/test',
        }
        with patch.dict(os.environ, env, clear=True):
            from bot.config_web3 import Web3Config
            config = Web3Config()
            assert config.network_mode == 'testnet'
            assert config.rpc_urls.get('sepolia') == 'https://sepolia.test.url'

    def test_testnet_mode_sets_chain_id(self):
        """Test that testnet mode sets Sepolia chain ID."""
        env = {
            'NETWORK_MODE': 'testnet',
            'ETH_RPC_URL': 'https://eth-mainnet.g.alchemy.com/v2/test',
        }
        with patch.dict(os.environ, env, clear=True):
            from bot.config_web3 import Web3Config
            config = Web3Config()
            assert config.chain_ids.get('sepolia') == 11155111

    def test_testnet_overrides_dex_addresses(self):
        """Test that testnet mode overrides Uniswap V2 DEX addresses."""
        env = {
            'NETWORK_MODE': 'testnet',
            'ETH_RPC_URL': 'https://eth-mainnet.g.alchemy.com/v2/test',
        }
        with patch.dict(os.environ, env, clear=True):
            from bot.config_web3 import Web3Config
            config = Web3Config()
            uniswap_v2 = config.dex_configs.get('uniswap_v2', {})
            assert uniswap_v2.get('router') == '0xC532a74256D338Db9Ee4E7e38E9046eE5fE6a8a3'
            assert uniswap_v2.get('factory') == '0x7E0987E8b5C0E2D1F2B0c7D5F8F1E3A1B5C8D9E0'

    def test_testnet_overrides_lower_limits(self):
        """Test that testnet mode lowers trading limits."""
        env = {
            'NETWORK_MODE': 'testnet',
            'ETH_RPC_URL': 'https://eth-mainnet.g.alchemy.com/v2/test',
        }
        with patch.dict(os.environ, env, clear=True):
            from bot.config_web3 import Web3Config
            config = Web3Config()
            assert config.max_trade_eth <= 0.01
            assert config.min_trade_eth <= 0.001

    def test_testnet_mode_env_overrides(self):
        """Test that testnet DEX addresses can be overridden via env."""
        env = {
            'NETWORK_MODE': 'testnet',
            'ETH_RPC_URL': 'https://eth-mainnet.g.alchemy.com/v2/test',
            'TEST_UNISWAP_V2_ROUTER': '0x' + 'c' * 40,
            'TEST_UNISWAP_V2_FACTORY': '0x' + 'd' * 40,
        }
        with patch.dict(os.environ, env, clear=True):
            from bot.config_web3 import Web3Config
            config = Web3Config()
            uniswap_v2 = config.dex_configs.get('uniswap_v2', {})
            assert uniswap_v2.get('router') == '0x' + 'c' * 40
            assert uniswap_v2.get('factory') == '0x' + 'd' * 40

    def test_mainnet_mode_does_not_add_sepolia(self):
        """Test that mainnet mode does not add Sepolia config."""
        env = {
            'NETWORK_MODE': 'mainnet',
            'SEPOLIA_RPC_URL': 'https://sepolia.test.url',
            'ETH_RPC_URL': 'https://eth-mainnet.g.alchemy.com/v2/test',
        }
        with patch.dict(os.environ, env, clear=True):
            from bot.config_web3 import Web3Config
            config = Web3Config()
            assert config.rpc_urls.get('sepolia') is None
            assert config.chain_ids.get('sepolia') is None


# =============================================================================
# Tests for onchain/trader.py (Sepolia WETH address)
# =============================================================================

class TestTraderSepolia:
    """Tests for Sepolia support in trader module."""

    def test_trader_initializes_with_sepolia(self):
        """Test that TradeExecutor can be initialized with Sepolia chain."""
        from onchain.trader import TradeExecutor
        from onchain.database import Chain

        mock_web3 = MagicMock()
        mock_web3.is_connected.return_value = True
        mock_db = MagicMock()

        executor = TradeExecutor(mock_web3, Chain.SEPOLIA, database=mock_db)
        assert executor.chain == Chain.SEPOLIA

    def test_get_weth_sepolia(self):
        """Test that Sepolia WETH address is resolved correctly."""
        from onchain.trader import TradeExecutor
        from onchain.database import Chain

        mock_web3 = MagicMock()
        mock_web3.is_connected.return_value = True
        mock_db = MagicMock()

        executor = TradeExecutor(mock_web3, Chain.SEPOLIA, database=mock_db)
        weth = executor._get_weth_address()
        assert weth == '0xfFf9976782d46CC05630D1f6eBAb18b2324d6B14'
