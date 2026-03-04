"""Shared constants for the Telegram Claude Bot.

This module centralizes configuration constants to ensure consistency
across different parts of the application.
"""

# DeepSeek API configuration
DEEPSEEK_MODEL = "deepseek-chat"

# Token limits
API_MAX_TOKENS = 4096  # Maximum tokens to generate in API responses
MAX_CONTEXT_WINDOW = 50000  # Maximum context window size for DeepSeek
POLYMARKET_MAX_TOKENS = 1500  # Specific limit for Polymarket analysis

# Tool execution limits
MAX_TOOL_ITERATIONS = 8
TOOL_RESULT_MAX_LEN = 2000

# Session management
DEFAULT_MAX_HISTORY_MESSAGES = 15
MAX_RETRIES_CONTEXT_EXCEEDED = 3
ARCHIVE_DAYS = 30
GENERAL_SESSION_TIMEOUT = 1800  # 30 minutes in seconds

# API retry configuration
MAX_API_RETRIES = 3
INITIAL_RETRY_DELAY = 1.0  # seconds
MAX_RETRY_DELAY = 10.0  # seconds
RETRY_BACKOFF_FACTOR = 2.0

# File paths
SESSIONS_DIR_NAME = "data/sessions"
ARCHIVE_DIR_NAME = "archive"

# Supported media types
SUPPORTED_IMAGE_TYPES = frozenset({
    "image/jpeg", "image/png", "image/gif", "image/webp"
})

# Task tracker configuration
TASKS_FILE_NAME = "data/tasks.json"
WEB_TASKS_FILE_NAME = "web-apps/data/tasks.json"
MAX_RETRIES = 3
RETRY_DELAY = 0.1  # seconds
MAX_BACKUPS = 5