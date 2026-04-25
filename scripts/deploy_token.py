#!/usr/bin/env python3
"""Deploy a test ERC20 token to Sepolia testnet.

Usage:
    export SEPOLIA_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/YOUR_KEY
    export PRIVATE_KEY=0x...
    python scripts/deploy_token.py

Optional env vars:
    TEST_TOKEN_NAME    (default: "ClaudeBot Test Token")
    TEST_TOKEN_SYMBOL  (default: "CTST")
    TEST_TOKEN_DECIMALS (default: 18)
"""

import os
import sys
import json
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from web3 import Web3
from web3.middleware import geth_poa_middleware

from scripts.config import get_or_compile, CONTRACTS_DIR

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_web3() -> Web3:
    """Create Web3 instance connected to Sepolia."""
    rpc_url = os.environ.get('SEPOLIA_RPC_URL')
    if not rpc_url:
        raise ValueError(
            "SEPOLIA_RPC_URL environment variable is required.\n"
            "Get a free endpoint at https://alchemy.com or https://infura.io"
        )

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    if not w3.is_connected():
        raise ConnectionError(f"Cannot connect to Sepolia at {rpc_url[:50]}...")

    chain_id = w3.eth.chain_id
    if chain_id != 11155111:
        logger.warning(f"Connected to chain {chain_id}, expected Sepolia (11155111)")

    logger.info(f"Connected to Sepolia (block: {w3.eth.block_number})")
    return w3


def get_account(w3: Web3):
    """Get account from private key."""
    private_key = os.environ.get('PRIVATE_KEY')
    if not private_key:
        raise ValueError(
            "PRIVATE_KEY environment variable is required.\n"
            "Use a testnet wallet private key (NEVER use mainnet key here!)"
        )

    account = w3.eth.account.from_key(private_key)
    balance = w3.eth.get_balance(account.address)
    balance_eth = float(w3.from_wei(balance, 'ether'))

    logger.info(f"Deployer: {account.address}")
    logger.info(f"Balance: {balance_eth:.4f} ETH")

    if balance_eth < 0.01:
        logger.warning(
            "Low balance! Get Sepolia ETH from a faucet:\n"
            "  https://sepoliafaucet.com\n"
            "  https://faucet.quicknode.com/ethereum/sepolia"
        )

    return account


def deploy_token(w3: Web3, account):
    """Compile and deploy the test token contract.

    Args:
        w3: Web3 instance connected to Sepolia
        account: LocalAccount for signing

    Returns:
        Deployment artifact dict
    """
    token_name = os.environ.get('TEST_TOKEN_NAME', 'ClaudeBot Test Token')
    token_symbol = os.environ.get('TEST_TOKEN_SYMBOL', 'CTST')
    token_decimals = int(os.environ.get('TEST_TOKEN_DECIMALS', '18'))

    # Compile the contract
    logger.info(f"Compiling TestToken.sol...")
    compiled = get_or_compile('TestToken')
    if not compiled:
        raise RuntimeError("Failed to compile TestToken.sol")

    abi = compiled['abi']
    bytecode = compiled['bytecode']

    # Create contract factory
    Contract = w3.eth.contract(abi=abi, bytecode=bytecode)

    # Build deployment transaction
    nonce = w3.eth.get_transaction_count(account.address)

    # Estimate gas
    try:
        gas_estimate = Contract.constructor(
            token_name, token_symbol, token_decimals
        ).estimate_gas({'from': account.address})
    except Exception:
        gas_estimate = 2000000  # Conservative fallback

    tx = Contract.constructor(token_name, token_symbol, token_decimals).build_transaction({
        'from': account.address,
        'nonce': nonce,
        'gas': int(gas_estimate * 1.2),  # 20% buffer
        'gasPrice': w3.eth.gas_price,
        'chainId': 11155111,
    })

    # Sign and send
    logger.info(f"Deploying {token_name} ({token_symbol})...")
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    logger.info(f"Transaction sent: 0x{tx_hash.hex()[:20]}...")

    # Wait for confirmation
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    gas_used = receipt['gasUsed']

    if receipt['status'] == 1:
        contract_address = receipt['contractAddress']
        gas_cost_eth = float(w3.from_wei(gas_used * tx['gasPrice'], 'ether'))

        logger.info(f"✓ Deployed at: {contract_address}")
        logger.info(f"  Gas used: {gas_used}")
        logger.info(f"  Cost: {gas_cost_eth:.8f} ETH")

        # Save artifact
        artifact = {
            'contract': 'TestToken',
            'address': contract_address,
            'name': token_name,
            'symbol': token_symbol,
            'decimals': token_decimals,
            'deployer': account.address,
            'tx_hash': tx_hash.hex(),
            'block_number': receipt['blockNumber'],
            'gas_used': gas_used,
            'gas_cost_eth': gas_cost_eth,
            'network': 'sepolia',
            'chain_id': 11155111,
            'abi': abi,
        }

        artifact_path = CONTRACTS_DIR / 'compiled' / 'TestToken-deployment.json'
        with open(artifact_path, 'w') as f:
            json.dump(artifact, f, indent=2)
        logger.info(f"Artifact saved to {artifact_path}")

        return artifact
    else:
        raise RuntimeError(f"Deployment failed (status: {receipt['status']})")


def main():
    """Main deployment entry point."""
    try:
        w3 = get_web3()
        account = get_account(w3)
        artifact = deploy_token(w3, account)

        print("\n" + "=" * 60)
        print("DEPLOYMENT SUCCESSFUL")
        print("=" * 60)
        print(f"  Contract: TestToken")
        print(f"  Token:    {artifact['name']} ({artifact['symbol']})")
        print(f"  Address:  {artifact['address']}")
        print(f"  Network:  Sepolia (chain ID: {artifact['chain_id']})")
        print(f"  Tx:       0x{artifact['tx_hash'][:20]}...")
        print("=" * 60)
        print("\nTo verify:")
        print(f"  python scripts/verify_onchain.py --address {artifact['address']}")
        print()

    except (ValueError, ConnectionError, RuntimeError) as e:
        logger.error(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Deployment cancelled")
        sys.exit(1)


if __name__ == '__main__':
    main()
