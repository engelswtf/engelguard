"""
Logging utilities with secret filtering.

Provides a logging setup that:
- Filters sensitive information from logs
- Supports both console and file output
- Configurable log levels
- Includes timestamps and module names
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.config import Config


class SecretFilter(logging.Filter):
    """
    Logging filter that redacts sensitive information.

    Replaces any occurrence of registered secrets with [REDACTED].
    """

    def __init__(self, secrets: list[str] | None = None) -> None:
        """
        Initialize the secret filter.

        Args:
            secrets: List of secret strings to redact from logs
        """
        super().__init__()
        self._secrets: list[str] = []
        self._pattern: re.Pattern[str] | None = None
        if secrets:
            self.set_secrets(secrets)

    def set_secrets(self, secrets: list[str]) -> None:
        """
        Set the list of secrets to filter.

        Args:
            secrets: List of secret strings to redact
        """
        # Filter out empty strings and very short strings
        self._secrets = [s for s in secrets if s and len(s) > 3]
        if self._secrets:
            # Escape regex special characters and join with |
            escaped = [re.escape(s) for s in self._secrets]
            self._pattern = re.compile("|".join(escaped), re.IGNORECASE)
        else:
            self._pattern = None

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter a log record, redacting any secrets.

        Args:
            record: The log record to filter

        Returns:
            bool: Always True (we modify, not filter out)
        """
        if self._pattern and record.msg:
            # Handle string messages
            if isinstance(record.msg, str):
                record.msg = self._pattern.sub("[REDACTED]", record.msg)

            # Handle arguments that might contain secrets
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        k: self._pattern.sub("[REDACTED]", str(v)) if isinstance(v, str) else v
                        for k, v in record.args.items()
                    }
                elif isinstance(record.args, tuple):
                    record.args = tuple(
                        self._pattern.sub("[REDACTED]", str(arg)) if isinstance(arg, str) else arg
                        for arg in record.args
                    )

        return True


class ColoredFormatter(logging.Formatter):
    """
    Logging formatter with colored output for console.

    Colors:
    - DEBUG: Cyan
    - INFO: Green
    - WARNING: Yellow
    - ERROR: Red
    - CRITICAL: Red on white background
    """

    COLORS = {
        logging.DEBUG: "\033[36m",  # Cyan
        logging.INFO: "\033[32m",  # Green
        logging.WARNING: "\033[33m",  # Yellow
        logging.ERROR: "\033[31m",  # Red
        logging.CRITICAL: "\033[41m",  # Red background
    }
    RESET = "\033[0m"

    def __init__(self, fmt: str | None = None, use_colors: bool = True) -> None:
        """
        Initialize the colored formatter.

        Args:
            fmt: Log format string
            use_colors: Whether to use colors (disable for non-TTY)
        """
        super().__init__(fmt)
        self.use_colors = use_colors and sys.stderr.isatty()

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record with colors."""
        message = super().format(record)
        if self.use_colors:
            color = self.COLORS.get(record.levelno, "")
            if color:
                message = f"{color}{message}{self.RESET}"
        return message


# Global secret filter instance
_secret_filter: SecretFilter | None = None


def setup_logging(config: Config) -> None:
    """
    Set up logging for the bot.

    Configures:
    - Console handler with colored output
    - Optional file handler
    - Secret filtering on all handlers

    Args:
        config: Bot configuration with log settings
    """
    global _secret_filter

    # Create root logger for our bot
    logger = logging.getLogger("bot")
    logger.setLevel(getattr(logging, config.log_level, logging.INFO))

    # Remove existing handlers
    logger.handlers.clear()

    # Create secret filter
    _secret_filter = SecretFilter(config.secrets)

    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.DEBUG)
    console_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    console_handler.setFormatter(ColoredFormatter(console_format))
    console_handler.addFilter(_secret_filter)
    logger.addHandler(console_handler)

    # File handler if configured
    if config.log_file:
        log_path = Path(config.log_file)
        # Create parent directories if needed
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        file_handler.setFormatter(logging.Formatter(file_format))
        file_handler.addFilter(_secret_filter)
        logger.addHandler(file_handler)

    # Also configure twitchio logger
    twitchio_logger = logging.getLogger("twitchio")
    twitchio_logger.setLevel(logging.WARNING)
    for handler in logger.handlers:
        twitchio_logger.addHandler(handler)

    logger.debug("Logging initialized with level %s", config.log_level)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a module.

    Args:
        name: Module name (usually __name__)

    Returns:
        logging.Logger: Configured logger instance
    """
    # Ensure it's under our bot namespace
    if not name.startswith("bot"):
        name = f"bot.{name}"
    return logging.getLogger(name)


def add_secret(secret: str) -> None:
    """
    Add a secret to the filter at runtime.

    Useful for dynamically loaded credentials.

    Args:
        secret: Secret string to filter
    """
    global _secret_filter
    if _secret_filter and secret:
        secrets = _secret_filter._secrets.copy()
        if secret not in secrets:
            secrets.append(secret)
            _secret_filter.set_secrets(secrets)
