"""Centralized configuration management for Telegram Claude Bot.

This module loads configuration from environment variables, provides
default values, validates configuration, and exports a singleton config
object for use throughout the application.
"""

import os
import logging
from typing import Optional, Any
from pathlib import Path

from . import constants
from .config_web3 import get_web3_config

logger = logging.getLogger(__name__)


class Config:
    """Central configuration manager."""

    def __init__(self):
        self._load_from_env()
        self._validate()
        self.web3_config = get_web3_config()

    def _load_from_env(self) -> None:
        """Load configuration from environment variables."""
        # Telegram Bot
        self.telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")

        # DeepSeek API (using DEEPSEEK_API_KEY for compatibility)
        self.deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY")

        # User authorization
        self.authorized_user_id = int(os.environ.get("AUTHORIZED_USER_ID", "0"))

        # Daily reminders
        try:
            self.reminder_chat_id = int(os.environ.get("REMINDER_CHAT_ID", "0"))
        except ValueError:
            self.reminder_chat_id = 0
            logger.warning("REMINDER_CHAT_ID format error, daily reminders disabled")

        try:
            self.reminder_hour = int(os.environ.get("REMINDER_HOUR", "8"))
            if not (0 <= self.reminder_hour <= 23):
                logger.warning(f"REMINDER_HOUR {self.reminder_hour} out of range (0-23), using 8")
                self.reminder_hour = 8
        except ValueError:
            self.reminder_hour = 8
            logger.warning("REMINDER_HOUR format error, using default 8")

        # Paths
        self.data_dir = Path(__file__).parent.parent / "data"
        self.sessions_dir = self.data_dir / "sessions"
        self.archive_dir = self.sessions_dir / "archive"

        # Web app paths (if applicable)
        self.web_apps_data_dir = Path(__file__).parent.parent / "web-apps" / "data"

        # Onchain data paths
        self.onchain_data_dir = self.data_dir / "onchain"
        self.onchain_cache_dir = self.onchain_data_dir / "cache"
        self.onchain_logs_dir = self.onchain_data_dir / "logs"
        self.onchain_blacklist_dir = self.onchain_data_dir / "blacklist"

    def _validate(self) -> None:
        """Validate required configuration."""
        errors = []

        if not self.telegram_bot_token:
            errors.append("TELEGRAM_BOT_TOKEN is required")

        if not self.deepseek_api_key:
            errors.append("DEEPSEEK_API_KEY is required")

        if errors:
            error_msg = ", ".join(errors)
            logger.error(f"Configuration validation failed: {error_msg}")
            raise ValueError(f"Missing required configuration: {error_msg}")

    def is_daily_reminder_enabled(self) -> bool:
        """Check if daily reminders are enabled."""
        return self.reminder_chat_id > 0

    def get_required_config(self) -> dict:
        """Get required configuration for external validation."""
        web3_summary = self.web3_config.get_config_summary() if hasattr(self, 'web3_config') else {}

        return {
            "telegram_bot_token": bool(self.telegram_bot_token),
            "deepseek_api_key": bool(self.deepseek_api_key),
            "authorized_user_id": self.authorized_user_id,
            "reminder_chat_id": self.reminder_chat_id,
            "reminder_hour": self.reminder_hour,
            "daily_reminder_enabled": self.is_daily_reminder_enabled(),
            "web3_config": web3_summary,
        }

    def ensure_directories(self) -> bool:
        """Ensure required directories exist."""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            self.web_apps_data_dir.mkdir(parents=True, exist_ok=True)

            # Create onchain directories
            self.onchain_data_dir.mkdir(parents=True, exist_ok=True)
            self.onchain_cache_dir.mkdir(parents=True, exist_ok=True)
            self.onchain_logs_dir.mkdir(parents=True, exist_ok=True)
            self.onchain_blacklist_dir.mkdir(parents=True, exist_ok=True)

            return True
        except Exception as e:
            logger.error(f"Failed to create directories: {e}")
            return False


# Global config instance
_config_instance: Optional[Config] = None

def get_config() -> Config:
    """Get the global configuration instance."""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance

def reload_config() -> Config:
    """Reload configuration from environment variables."""
    global _config_instance
    _config_instance = Config()
    return _config_instance