#!/usr/bin/env python3
"""Deploy MonaLisaNFT contract to Sepolia testnet.

Usage:
    export SEPOLIA_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/YOUR_KEY
    export PRIVATE_KEY=0x...
    python scripts/deploy_nft.py

Strategy: deploy with metadata (small tx), then upload SVG data
in batches of ~8 SVGs per tx to stay within block gas limit.
"""

import os
import sys
import json
import time
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from web3 import Web3

from scripts.config import get_or_compile, CONTRACTS_DIR

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BATCH_SIZE = 4  # SVGs per tx (each ~3.5M gas => ~14M per batch, under 15M)


def load_env():
    """Load .env file if env vars not already set."""
    if os.environ.get('SEPOLIA_RPC_URL'):
        return
    env_path = PROJECT_ROOT / '.env'
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    os.environ.setdefault(key.strip(), val.strip())


def get_web3() -> Web3:
    load_env()
    rpc_url = os.environ.get('SEPOLIA_RPC_URL')
    if not rpc_url:
        raise ValueError("SEPOLIA_RPC_URL environment variable required")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise ConnectionError("Cannot connect to Sepolia")
    logger.info(f"Connected to Sepolia (block: {w3.eth.block_number})")
    return w3


def get_account(w3: Web3):
    pk = os.environ.get('PRIVATE_KEY')
    if not pk:
        raise ValueError("PRIVATE_KEY env var required")
    acct = w3.eth.account.from_key(pk)
    bal = float(w3.from_wei(w3.eth.get_balance(acct.address), 'ether'))
    logger.info(f"Account: {acct.address} ({bal:.4f} ETH)")
    return acct


def send_tx(w3, tx, account):
    """Sign, send, and wait for a tx. Returns receipt."""
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    logger.info(f"  Tx: 0x{tx_hash.hex()[:16]}...")
    return w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)


def deploy_contract(w3, account, nft_data):
    """Deploy with metadata only (small tx)."""
    compiled = get_or_compile('MonaLisaNFT')
    abi, bytecode = compiled['abi'], compiled['bytecode']

    Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    meta = [(t['name'], t['character'], t['charType'], t['rarity'], int(t['price']))
            for t in nft_data['tokens']]

    try:
        gas_est = Contract.constructor(nft_data['name'], nft_data['symbol'], meta).estimate_gas(
            {'from': account.address})
    except Exception:
        gas_est = 800000

    tx = Contract.constructor(nft_data['name'], nft_data['symbol'], meta).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': int(gas_est * 1.5),
        'gasPrice': w3.eth.gas_price,
        'chainId': 11155111,
    })

    logger.info(f"Deploying... (gas est: {gas_est}, data: {len(tx.get('data', ''))} bytes)")
    receipt = send_tx(w3, tx, account)
    if receipt['status'] != 1:
        raise RuntimeError("Deployment failed")

    addr = receipt['contractAddress']
    contract = w3.eth.contract(address=addr, abi=abi)
    cost = float(w3.from_wei(receipt['gasUsed'] * tx['gasPrice'], 'ether'))
    logger.info(f"✅ Contract at {addr} (gas: {receipt['gasUsed']}, cost: {cost:.8f} ETH)")
    return contract, receipt


def upload_batch(w3, account, contract, start, end, svgs):
    """Upload a batch of SVGs. IDs = [start..end)."""
    ids = list(range(start, end))
    batch = svgs[start:end]
    total_bytes = sum(len(s) for s in batch)

    try:
        gas_est = contract.functions.batchSetSVGs(ids, batch).estimate_gas(
            {'from': account.address})
        gas_est = min(gas_est, 14_000_000)
    except Exception as e:
        logger.warning(f"  gas est failed: {e}")
        gas_est = min(3_000_000 * len(batch), 14_000_000)

    tx = contract.functions.batchSetSVGs(ids, batch).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': min(int(gas_est * 1.2), 15_000_000),
        'gasPrice': w3.eth.gas_price,
        'chainId': 11155111,
    })

    if tx['gas'] > 15_000_000:
        logger.warning(f"  Gas {tx['gas']} exceeds 15M! Reducing...")
        tx['gas'] = 15_000_000

    logger.info(f"  Batch {start}-{end-1}: {len(batch)} SVGs, {total_bytes}B, gas={tx['gas']}")
    receipt = send_tx(w3, tx, account)

    ok = receipt['status'] == 1
    cost = float(w3.from_wei(receipt['gasUsed'] * tx['gasPrice'], 'ether'))
    logger.info(f"  {'✅' if ok else '❌'} gas={receipt['gasUsed']} cost={cost:.8f} ETH")
    return ok, receipt


def save_artifact(nft_data, abi, contract_address, deploy_receipt):
    artifact = {
        'contract': 'MonaLisaNFT',
        'address': contract_address,
        'name': nft_data['name'],
        'symbol': nft_data['symbol'],
        'tokens': len(nft_data['tokens']),
        'deployer': deploy_receipt.get('from'),
        'network': 'sepolia',
        'chain_id': 11155111,
        'abi': abi,
    }
    path = CONTRACTS_DIR / 'compiled' / 'MonaLisaNFT-deployment.json'
    with open(path, 'w') as f:
        json.dump(artifact, f, indent=2)
    logger.info(f"Artifact saved to {path}")
    return artifact


def main():
    try:
        data_path = CONTRACTS_DIR / 'compiled' / 'nft_data.json'
        if not data_path.exists():
            raise FileNotFoundError("Run 'node scripts/generate_nft_data.js' first")
        with open(data_path) as f:
            nft_data = json.load(f)

        logger.info(f"Loaded {len(nft_data['tokens'])} tokens")

        w3 = get_web3()
        account = get_account(w3)

        # Step 1: Deploy with metadata
        contract, deploy_receipt = deploy_contract(w3, account, nft_data)

        # Step 2: Upload SVGs in batches
        svgs = [t['svg'] for t in nft_data['tokens']]
        total = len(svgs)
        all_ok = True

        for batch_start in range(0, total, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, total)
            ok, _ = upload_batch(w3, account, contract, batch_start, batch_end, svgs)
            if not ok:
                all_ok = False
                logger.error(f"Batch {batch_start}-{batch_end-1} FAILED")
                break

        # Save
        save_artifact(nft_data, contract.abi, contract.address, deploy_receipt)

        print("\n" + "=" * 60)
        print("MONA LISA NFT DEPLOYMENT")
        print("=" * 60)
        print(f"  Address:  {contract.address}")
        print(f"  Tokens:   {total}")
        print(f"  SVGs:     {'✅ all uploaded' if all_ok else '❌ some failed'}")
        print(f"  View:     https://sepolia.etherscan.io/address/{contract.address}")
        print("=" * 60)

    except Exception as e:
        logger.error(str(e))
        sys.exit(1)


if __name__ == '__main__':
    main()
