#!/usr/bin/env python3
"""Full pipeline: compile, deploy, and verify a test token on Sepolia.

This script performs the complete workflow:
1. Compile the TestToken contract
2. Deploy to Sepolia testnet
3. Query on-chain state to verify deployment
4. Mint additional tokens if requested
5. Print a summary of results

Usage:
    export SEPOLIA_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/YOUR_KEY
    export PRIVATE_KEY=0x...
    python scripts/deploy_and_verify.py
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
from scripts.deploy_token import get_web3, get_account, deploy_token

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def verify_deployment(w3: Web3, token_address: str, abi: list, deployer: str) -> dict:
    """Verify the deployed token by querying on-chain state.

    Args:
        w3: Web3 instance
        token_address: Deployed token contract address
        abi: Contract ABI
        deployer: Deployer address for balance check

    Returns:
        Dict with on-chain state values
    """
    contract = w3.eth.contract(address=token_address, abi=abi)

    try:
        name = contract.functions.name().call()
        symbol = contract.functions.symbol().call()
        decimals = contract.functions.decimals().call()
        total_supply = contract.functions.totalSupply().call()
        deployer_balance = contract.functions.balanceOf(deployer).call()

        return {
            'name': name,
            'symbol': symbol,
            'decimals': decimals,
            'total_supply': total_supply,
            'total_supply_formatted': total_supply / (10 ** decimals),
            'deployer_balance': deployer_balance,
            'deployer_balance_formatted': deployer_balance / (10 ** decimals),
            'verified': True,
        }

    except Exception as e:
        logger.error(f"Verification failed: {e}")
        return {
            'verified': False,
            'error': str(e),
        }


def mint_tokens(w3: Web3, account, token_address: str, abi: list,
                to_address: str, amount: int) -> str:
    """Mint additional tokens.

    Args:
        w3: Web3 instance
        account: Signing account
        token_address: Token contract address
        abi: Contract ABI
        to_address: Recipient of minted tokens
        amount: Amount in wei (smallest unit)

    Returns:
        Transaction hash
    """
    contract = w3.eth.contract(address=token_address, abi=abi)

    nonce = w3.eth.get_transaction_count(account.address)
    tx = contract.functions.mint(to_address, amount).build_transaction({
        'from': account.address,
        'nonce': nonce,
        'gas': 100000,
        'gasPrice': w3.eth.gas_price,
        'chainId': 11155111,
    })

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

    if receipt['status'] != 1:
        raise RuntimeError(f"Mint transaction failed")

    return tx_hash.hex()


def print_verification_summary(result: dict):
    """Print a formatted verification summary."""
    print("\n" + "=" * 60)
    print("VERIFICATION RESULT")
    print("=" * 60)

    if not result.get('verified'):
        print(f"  ✗ Verification failed: {result.get('error', 'Unknown error')}")
        return

    print(f"  ✓ Contract verified on-chain")
    print(f"  Name:          {result['name']}")
    print(f"  Symbol:        {result['symbol']}")
    print(f"  Decimals:      {result['decimals']}")
    print(f"  Total Supply:  {result['total_supply_formatted']:,.2f} {result['symbol']}")
    print(f"  Deployer Bal:  {result['deployer_balance_formatted']:,.2f} {result['symbol']}")
    print("=" * 60)


def main():
    """Full pipeline entry point."""
    try:
        # Step 1: Connect
        w3 = get_web3()
        account = get_account(w3)

        # Step 2: Deploy
        artifact = deploy_token(w3, account)
        token_address = artifact['address']
        abi = artifact['abi']

        # Step 3: Verify
        logger.info("Verifying deployment...")
        verify_result = verify_deployment(w3, token_address, abi, account.address)

        if verify_result['verified']:
            logger.info("Deployment verified successfully!")
        else:
            logger.warning(f"Verification issue: {verify_result.get('error')}")

        print_verification_summary(verify_result)

        # Step 4: Offer to mint more tokens
        mint_amount_str = os.environ.get('MINT_AMOUNT', '')
        if mint_amount_str:
            try:
                mint_amount = int(mint_amount_str)
                logger.info(f"Minting {mint_amount} additional tokens...")
                tx_hash = mint_tokens(
                    w3, account, token_address, abi,
                    account.address, mint_amount
                )
                logger.info(f"Mint tx: 0x{tx_hash[:20]}...")

                # Re-verify
                verify_result = verify_deployment(
                    w3, token_address, abi, account.address
                )
                print_verification_summary(verify_result)
            except (ValueError, RuntimeError) as e:
                logger.warning(f"Mint skipped: {e}")

        # Step 5: Print configuration for bot
        print("\n" + "=" * 60)
        print("BOT CONFIGURATION")
        print("=" * 60)
        print(f"Add to your .env or export:")
        print(f"  NETWORK_MODE=testnet")
        print(f"  TEST_TOKEN_ADDRESS={token_address}")
        print()

    except (ValueError, ConnectionError, RuntimeError) as e:
        logger.error(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Cancelled")
        sys.exit(1)


if __name__ == '__main__':
    main()
