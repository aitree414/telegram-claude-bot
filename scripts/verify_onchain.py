#!/usr/bin/env python3
"""Verify a deployed test token on Sepolia by querying on-chain state.

Usage:
    python scripts/verify_onchain.py --address 0x... [--rpc-url URL]

If --rpc-url is not provided, reads SEPOLIA_RPC_URL from environment.
If --address is not provided, reads from the deployment artifact.
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from web3 import Web3
from web3.middleware import geth_poa_middleware

from scripts.config import CONTRACTS_DIR

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def load_deployment_artifact() -> dict:
    """Load deployment artifact from compiled directory."""
    artifact_path = CONTRACTS_DIR / 'compiled' / 'TestToken-deployment.json'
    if not artifact_path.exists():
        raise FileNotFoundError(
            f"Deployment artifact not found at {artifact_path}\n"
            "Deploy the token first with: python scripts/deploy_token.py"
        )
    with open(artifact_path) as f:
        return json.load(f)


def verify_token(w3: Web3, address: str, abi: list) -> dict:
    """Query and verify the deployed token's on-chain state.

    Args:
        w3: Web3 instance
        address: Token contract address
        abi: Contract ABI

    Returns:
        Dict with on-chain state and verification status
    """
    contract = w3.eth.contract(address=address, abi=abi)

    results = {}
    checks = [
        ('name', lambda c: c.functions.name().call()),
        ('symbol', lambda c: c.functions.symbol().call()),
        ('decimals', lambda c: c.functions.decimals().call()),
        ('total_supply', lambda c: c.functions.totalSupply().call()),
    ]

    all_ok = True
    for name, query_fn in checks:
        try:
            value = query_fn(contract)
            results[name] = value
            print(f"  ✓ {name}: {value}")
        except Exception as e:
            results[name] = None
            print(f"  ✗ {name}: {e}")
            all_ok = False

    results['verified'] = all_ok

    # Try balance check with a default address
    try:
        any_address = w3.eth.accounts[0] if w3.eth.accounts else None
        if any_address:
            balance = contract.functions.balanceOf(any_address).call()
            results['sample_balance'] = balance
            print(f"  ✓ balanceOf({any_address[:10]}...): {balance}")
    except Exception:
        pass

    return results


def main():
    parser = argparse.ArgumentParser(description='Verify deployed test token on Sepolia')
    parser.add_argument('--address', '-a', help='Token contract address')
    parser.add_argument('--rpc-url', '-r', help='Sepolia RPC URL')
    args = parser.parse_args()

    # Get RPC URL
    rpc_url = args.rpc_url or os.environ.get('SEPOLIA_RPC_URL')
    if not rpc_url:
        print("Error: SEPOLIA_RPC_URL not set. Provide --rpc-url or set env var.")
        sys.exit(1)

    # Get token address
    if args.address:
        token_address = Web3.to_checksum_address(args.address)
    else:
        try:
            artifact = load_deployment_artifact()
            token_address = artifact['address']
            abi = artifact['abi']
            print(f"Using deployed artifact: {token_address}")
        except FileNotFoundError as e:
            print(f"Error: {e}")
            sys.exit(1)

    # Connect
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    if not w3.is_connected():
        print(f"Error: Cannot connect to {rpc_url[:50]}...")
        sys.exit(1)

    print(f"\nConnected to Sepolia (block: {w3.eth.block_number})")
    print(f"Token address: {token_address}")
    print()

    # If no abi from artifact, load from compilation cache
    if 'abi' not in locals() or not abi:
        compiled = CONTRACTS_DIR / 'compiled' / 'TestToken.json'
        if compiled.exists():
            with open(compiled) as f:
                abi = json.load(f)['abi']
        else:
            print("Error: No ABI available. Compile first with scripts/config.py")
            sys.exit(1)

    # Verify
    results = verify_token(w3, token_address, abi)

    print()
    if results.get('verified'):
        print("✓ Token verified successfully on-chain!")
    else:
        print("✗ Some checks failed. Review errors above.")
        sys.exit(1)


if __name__ == '__main__':
    main()
