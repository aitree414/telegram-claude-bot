"""Compilation helper for Solidity contracts.

This module provides contract compilation using py-solc-x,
handling solc installation and artifact management.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from solcx import compile_files, install_solc, get_installed_solc_versions, set_solc_version

logger = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
CONTRACTS_DIR = PROJECT_ROOT / 'contracts'
COMPILED_DIR = CONTRACTS_DIR / 'compiled'

# Default Solidity version
DEFAULT_SOLC_VERSION = '0.8.20'


def ensure_solc(version: str = DEFAULT_SOLC_VERSION) -> None:
    """Ensure the specified solc version is installed.

    Downloads the solc binary if not already cached.

    Args:
        version: Solidity compiler version (e.g. '0.8.20')
    """
    installed = get_installed_solc_versions()

    if version not in installed:
        logger.info(f"Downloading solc {version}...")
        install_solc(version)
        logger.info(f"solc {version} installed")

    set_solc_version(version)


def compile_contract(contract_name: str) -> Optional[Dict[str, Any]]:
    """Compile a Solidity contract and return its ABI and bytecode.

    Args:
        contract_name: Name of the .sol file (without extension)

    Returns:
        Dict with 'abi' and 'bin' keys, or None if compilation fails
    """
    sol_path = CONTRACTS_DIR / f'{contract_name}.sol'

    if not sol_path.exists():
        logger.error(f"Contract file not found: {sol_path}")
        return None

    # Ensure compiled directory exists
    COMPILED_DIR.mkdir(parents=True, exist_ok=True)

    # Ensure solc is installed
    try:
        ensure_solc(DEFAULT_SOLC_VERSION)
    except Exception as e:
        logger.error(f"Failed to install solc: {e}")
        return None

    # Compile
    try:
        output = compile_files(
            [str(sol_path)],
            output_values=['abi', 'bin'],
            solc_version=DEFAULT_SOLC_VERSION,
        )

        # Find the contract in output
        contract_key = f'{sol_path}:{contract_name}'
        if contract_key not in output:
            # Try to find any contract in the output
            for key in output:
                if contract_name in key:
                    contract_key = key
                    break
            else:
                logger.error(f"Contract '{contract_name}' not found in compilation output")
                return None

        contract_data = output[contract_key]

        result = {
            'abi': contract_data['abi'],
            'bytecode': contract_data['bin'],
            'source': str(sol_path),
            'contract_name': contract_name,
            'compiler_version': DEFAULT_SOLC_VERSION,
        }

        # Cache to file
        artifact_path = COMPILED_DIR / f'{contract_name}.json'
        with open(artifact_path, 'w') as f:
            json.dump(result, f, indent=2)

        logger.info(f"Compiled {contract_name} (bytecode: {len(result['bytecode']) // 2} bytes)")
        return result

    except Exception as e:
        logger.error(f"Compilation failed: {e}")
        return None


def load_compiled_artifact(contract_name: str) -> Optional[Dict[str, Any]]:
    """Load a previously compiled artifact from cache.

    Args:
        contract_name: Name of the contract

    Returns:
        Cached artifact dict or None if not found
    """
    artifact_path = COMPILED_DIR / f'{contract_name}.json'
    if artifact_path.exists():
        with open(artifact_path) as f:
            return json.load(f)
    return None


def get_or_compile(contract_name: str) -> Optional[Dict[str, Any]]:
    """Get compiled artifact from cache, or compile if not cached.

    Args:
        contract_name: Name of the contract

    Returns:
        Compiled artifact dict
    """
    artifact = load_compiled_artifact(contract_name)
    if artifact:
        logger.info(f"Using cached artifact for {contract_name}")
        return artifact
    return compile_contract(contract_name)