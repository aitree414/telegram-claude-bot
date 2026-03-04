#!/usr/bin/env python3
"""Test that all major modules can be imported successfully."""

import sys
import importlib

# Add current directory to path
sys.path.insert(0, '.')

MODULES_TO_TEST = [
    # Core modules
    'bot.claude_client',
    'bot.retry',
    'bot.config',
    'bot.constants',
    'bot.handlers',
    'bot.alerts',
    'bot.watchlist',
    'bot.portfolio',
    'bot.scheduler',
    'bot.repair',
    'bot.session_manager',
    'bot.memory',
    'bot.task_tracker',
    'bot.tools',
    'bot.stock',
    'bot.poly_analyzer',
    'bot.polymarket',
    'bot.horse_race',
    'bot.project_loader',
]

def test_module_imports():
    """Test that all modules can be imported."""
    print("Testing module imports...")
    print("=" * 60)

    failed_modules = []

    for module_name in MODULES_TO_TEST:
        try:
            module = importlib.import_module(module_name)
            print(f"✅ {module_name}")
        except Exception as e:
            print(f"❌ {module_name}: {e}")
            failed_modules.append((module_name, e))

    print("\n" + "=" * 60)

    if failed_modules:
        print(f"❌ {len(failed_modules)} modules failed to import:")
        for module_name, error in failed_modules:
            print(f"  - {module_name}: {error}")
        return False
    else:
        print(f"✅ All {len(MODULES_TO_TEST)} modules imported successfully!")
        return True

if __name__ == "__main__":
    success = test_module_imports()
    sys.exit(0 if success else 1)