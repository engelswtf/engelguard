"""
Configuration management for the Twitch bot.

Loads configuration from environment variables and .env files,
validates required fields, and provides type-safe access.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class Config:
    """
    Immutable configuration for the Twitch bot.

    All configuration values are loaded from environment variables
    or a .env file. Required fields will raise ValueError if missing.

    Attributes:
        client_id: Twitch application client ID
        client_secret: Twitch application client secret
        oauth_token: Bot OAuth token for chat access
        refresh_token: OAuth refresh token for token renewal
        bot_nick: Bot's Twitch username
        channels: List of channels to join
        prefix: Command prefix (default: !)
        owner: Bot owner's Twitch username
        log_level: Logging level (default: INFO)
        log_file: Optional log file path
        database_url: Database connection URL
        enable_moderation: Enable moderation commands
        enable_fun_commands: Enable fun commands
        enable_info_commands: Enable info commands
        enable_admin_commands: Enable admin commands
        default_cooldown: Default command cooldown in seconds
        api_timeout: API request timeout in seconds
    """

    # Required fields
    client_id: str
    client_secret: str
    oauth_token: str
    bot_nick: str
    channels: list[str]
    owner: str

    # Optional fields with defaults
    refresh_token: str = ""
    prefix: str = "!"
    log_level: str = "INFO"
    log_file: str | None = None
    database_url: str = "sqlite:///data/bot.db"
    enable_moderation: bool = True
    enable_fun_commands: bool = True
    enable_info_commands: bool = True
    enable_admin_commands: bool = True
    default_cooldown: int = 3
    api_timeout: int = 10

    # Computed/derived fields
    _secrets: list[str] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        """Initialize secrets list for log filtering."""
        # Use object.__setattr__ because dataclass is frozen
        secrets = [
            self.client_id,
            self.client_secret,
            self.oauth_token,
            self.refresh_token,
        ]
        # Filter out empty strings
        object.__setattr__(self, "_secrets", [s for s in secrets if s])

    @property
    def secrets(self) -> list[str]:
        """Get list of secret values that should be filtered from logs."""
        return self._secrets

    def get_oauth_token_clean(self) -> str:
        """Get OAuth token without 'oauth:' prefix if present."""
        token = self.oauth_token
        if token.startswith("oauth:"):
            return token[6:]
        return token


def _parse_bool(value: str | None, default: bool = False) -> bool:
    """Parse a boolean from environment variable string."""
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes", "on")


def _parse_int(value: str | None, default: int) -> int:
    """Parse an integer from environment variable string."""
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _parse_channels(value: str | None) -> list[str]:
    """Parse comma-separated channel list."""
    if not value:
        return []
    # Split by comma, strip whitespace, remove empty strings, remove # prefix
    channels = [ch.strip().lstrip("#") for ch in value.split(",")]
    return [ch for ch in channels if ch]


def load_config(env_file: str | Path | None = None) -> Config:
    """
    Load configuration from environment variables and .env file.

    Args:
        env_file: Optional path to .env file. If not provided,
                  looks for .env in current directory and parent directories.

    Returns:
        Config: Validated configuration object

    Raises:
        ValueError: If required configuration is missing or invalid
    """
    # Load .env file if it exists
    if env_file:
        load_dotenv(env_file)
    else:
        # Try to find .env in current or parent directories
        load_dotenv()

    # Collect validation errors
    errors: list[str] = []

    # Required fields
    client_id = os.getenv("TWITCH_CLIENT_ID", "")
    if not client_id or client_id == "your_client_id_here":
        errors.append("TWITCH_CLIENT_ID is required")

    client_secret = os.getenv("TWITCH_CLIENT_SECRET", "")
    if not client_secret or client_secret == "your_client_secret_here":
        errors.append("TWITCH_CLIENT_SECRET is required")

    oauth_token = os.getenv("TWITCH_OAUTH_TOKEN", "")
    if not oauth_token or oauth_token == "oauth:your_token_here":
        errors.append("TWITCH_OAUTH_TOKEN is required")

    bot_nick = os.getenv("TWITCH_BOT_NICK", "")
    if not bot_nick or bot_nick == "your_bot_username":
        errors.append("TWITCH_BOT_NICK is required")

    channels = _parse_channels(os.getenv("TWITCH_CHANNELS"))
    if not channels:
        errors.append("TWITCH_CHANNELS is required (comma-separated list)")

    owner = os.getenv("BOT_OWNER", "")
    if not owner or owner == "your_twitch_username":
        errors.append("BOT_OWNER is required")

    # Raise all errors at once
    if errors:
        error_msg = "Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ValueError(error_msg)

    # Optional fields
    refresh_token = os.getenv("TWITCH_REFRESH_TOKEN", "")
    if refresh_token == "your_refresh_token_here":
        refresh_token = ""

    prefix = os.getenv("BOT_PREFIX", "!")
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_file = os.getenv("LOG_FILE") or None
    database_url = os.getenv("DATABASE_URL", "sqlite:///data/bot.db")

    # Feature flags
    enable_moderation = _parse_bool(os.getenv("ENABLE_MODERATION"), True)
    enable_fun_commands = _parse_bool(os.getenv("ENABLE_FUN_COMMANDS"), True)
    enable_info_commands = _parse_bool(os.getenv("ENABLE_INFO_COMMANDS"), True)
    enable_admin_commands = _parse_bool(os.getenv("ENABLE_ADMIN_COMMANDS"), True)

    # Rate limiting
    default_cooldown = _parse_int(os.getenv("DEFAULT_COOLDOWN"), 3)
    api_timeout = _parse_int(os.getenv("API_TIMEOUT"), 10)

    # Validate log level
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if log_level not in valid_levels:
        log_level = "INFO"

    return Config(
        client_id=client_id,
        client_secret=client_secret,
        oauth_token=oauth_token,
        refresh_token=refresh_token,
        bot_nick=bot_nick,
        channels=channels,
        prefix=prefix,
        owner=owner,
        log_level=log_level,
        log_file=log_file,
        database_url=database_url,
        enable_moderation=enable_moderation,
        enable_fun_commands=enable_fun_commands,
        enable_info_commands=enable_info_commands,
        enable_admin_commands=enable_admin_commands,
        default_cooldown=default_cooldown,
        api_timeout=api_timeout,
    )
