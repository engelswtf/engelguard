"""
Tests for the Twitch bot.

These tests verify:
- Configuration loading
- Bot instantiation
- Utility functions
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestConfig:
    """Tests for configuration loading."""

    def test_config_missing_required_fields(self) -> None:
        """Test that missing required fields raise ValueError."""
        from bot.config import load_config

        # Clear any existing env vars
        env_vars = [
            "TWITCH_CLIENT_ID",
            "TWITCH_CLIENT_SECRET",
            "TWITCH_OAUTH_TOKEN",
            "TWITCH_BOT_NICK",
            "TWITCH_CHANNELS",
            "BOT_OWNER",
        ]

        with patch.dict(os.environ, {k: "" for k in env_vars}, clear=False):
            # Remove the vars
            for var in env_vars:
                os.environ.pop(var, None)

            with pytest.raises(ValueError) as exc_info:
                load_config()

            assert "Configuration errors" in str(exc_info.value)

    def test_config_loads_with_valid_env(self) -> None:
        """Test that config loads successfully with valid environment."""
        from bot.config import load_config

        env_vars = {
            "TWITCH_CLIENT_ID": "test_client_id_12345",
            "TWITCH_CLIENT_SECRET": "test_client_secret_12345",
            "TWITCH_OAUTH_TOKEN": "oauth:test_token_12345",
            "TWITCH_BOT_NICK": "testbot",
            "TWITCH_CHANNELS": "channel1,channel2",
            "BOT_OWNER": "testowner",
            "BOT_PREFIX": "!",
            "LOG_LEVEL": "DEBUG",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            config = load_config()

            assert config.client_id == "test_client_id_12345"
            assert config.client_secret == "test_client_secret_12345"
            assert config.oauth_token == "oauth:test_token_12345"
            assert config.bot_nick == "testbot"
            assert config.channels == ["channel1", "channel2"]
            assert config.owner == "testowner"
            assert config.prefix == "!"
            assert config.log_level == "DEBUG"

    def test_config_parses_channels_correctly(self) -> None:
        """Test that channel parsing handles various formats."""
        from bot.config import _parse_channels

        # Basic comma-separated
        assert _parse_channels("a,b,c") == ["a", "b", "c"]

        # With spaces
        assert _parse_channels("a, b, c") == ["a", "b", "c"]

        # With # prefix
        assert _parse_channels("#a,#b,#c") == ["a", "b", "c"]

        # Empty string
        assert _parse_channels("") == []

        # None
        assert _parse_channels(None) == []

    def test_config_parses_bool_correctly(self) -> None:
        """Test boolean parsing from environment variables."""
        from bot.config import _parse_bool

        assert _parse_bool("true") is True
        assert _parse_bool("True") is True
        assert _parse_bool("TRUE") is True
        assert _parse_bool("1") is True
        assert _parse_bool("yes") is True
        assert _parse_bool("on") is True

        assert _parse_bool("false") is False
        assert _parse_bool("0") is False
        assert _parse_bool("no") is False
        assert _parse_bool("") is False
        assert _parse_bool(None) is False

        # Default value
        assert _parse_bool(None, default=True) is True

    def test_config_oauth_token_clean(self) -> None:
        """Test OAuth token prefix stripping."""
        from bot.config import load_config

        env_vars = {
            "TWITCH_CLIENT_ID": "test_client_id_12345",
            "TWITCH_CLIENT_SECRET": "test_client_secret_12345",
            "TWITCH_OAUTH_TOKEN": "oauth:mytoken123",
            "TWITCH_BOT_NICK": "testbot",
            "TWITCH_CHANNELS": "channel1",
            "BOT_OWNER": "testowner",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            config = load_config()
            assert config.get_oauth_token_clean() == "mytoken123"

    def test_config_secrets_filtering(self) -> None:
        """Test that secrets are properly tracked for filtering."""
        from bot.config import load_config

        env_vars = {
            "TWITCH_CLIENT_ID": "secret_client_id",
            "TWITCH_CLIENT_SECRET": "secret_client_secret",
            "TWITCH_OAUTH_TOKEN": "oauth:secret_token",
            "TWITCH_BOT_NICK": "testbot",
            "TWITCH_CHANNELS": "channel1",
            "BOT_OWNER": "testowner",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            config = load_config()
            secrets = config.secrets

            assert "secret_client_id" in secrets
            assert "secret_client_secret" in secrets
            assert "oauth:secret_token" in secrets


class TestLogging:
    """Tests for logging utilities."""

    def test_secret_filter_redacts_secrets(self) -> None:
        """Test that SecretFilter properly redacts secrets."""
        from bot.utils.logging import SecretFilter
        import logging

        filter_instance = SecretFilter(["mysecret123", "anotherSecret"])

        # Create a log record
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Token is mysecret123 and key is anotherSecret",
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)

        assert "mysecret123" not in record.msg
        assert "anotherSecret" not in record.msg
        assert "[REDACTED]" in record.msg

    def test_secret_filter_handles_empty_secrets(self) -> None:
        """Test that SecretFilter handles empty/short secrets."""
        from bot.utils.logging import SecretFilter
        import logging

        # Short secrets should be ignored
        filter_instance = SecretFilter(["ab", ""])

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Short ab should not be filtered",
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)

        # Should not be redacted (too short)
        assert "ab" in record.msg


class TestPermissions:
    """Tests for permission utilities."""

    def test_cooldown_bucket_enum(self) -> None:
        """Test CooldownBucket enum values."""
        from bot.utils.permissions import CooldownBucket

        assert CooldownBucket.USER.value == "user"
        assert CooldownBucket.CHANNEL.value == "channel"
        assert CooldownBucket.GLOBAL.value == "global"

    def test_cooldown_manager_tracks_cooldowns(self) -> None:
        """Test that CooldownManager properly tracks cooldowns."""
        from bot.utils.permissions import CooldownManager, CooldownBucket

        manager = CooldownManager()

        # Mock context
        mock_ctx = MagicMock()
        mock_ctx.channel.name = "testchannel"
        mock_ctx.author.name = "testuser"

        # First call should not be on cooldown
        on_cooldown, remaining = manager.check_cooldown(
            "testcmd", mock_ctx, 5.0, CooldownBucket.USER
        )
        assert on_cooldown is False
        assert remaining == 0

        # Update cooldown
        manager.update_cooldown("testcmd", mock_ctx, CooldownBucket.USER)

        # Now should be on cooldown
        on_cooldown, remaining = manager.check_cooldown(
            "testcmd", mock_ctx, 5.0, CooldownBucket.USER
        )
        assert on_cooldown is True
        assert remaining > 0

        # Reset cooldown
        manager.reset_cooldown("testcmd", mock_ctx, CooldownBucket.USER)

        # Should not be on cooldown anymore
        on_cooldown, remaining = manager.check_cooldown(
            "testcmd", mock_ctx, 5.0, CooldownBucket.USER
        )
        assert on_cooldown is False


class TestBotInstantiation:
    """Tests for bot instantiation."""

    def test_bot_can_be_created_with_config(self) -> None:
        """Test that TwitchBot can be instantiated with valid config."""
        from bot.config import Config
        from bot.bot import TwitchBot

        config = Config(
            client_id="test_client_id_12345",
            client_secret="test_client_secret_12345",
            oauth_token="oauth:test_token_12345",
            bot_nick="testbot",
            channels=["testchannel"],
            owner="testowner",
        )

        # This should not raise
        bot = TwitchBot(config)

        assert bot.config == config
        assert bot.nick == "testbot"

    def test_bot_uptime_calculation(self) -> None:
        """Test bot uptime calculation."""
        from bot.config import Config
        from bot.bot import TwitchBot
        import time

        config = Config(
            client_id="test_client_id_12345",
            client_secret="test_client_secret_12345",
            oauth_token="oauth:test_token_12345",
            bot_nick="testbot",
            channels=["testchannel"],
            owner="testowner",
        )

        bot = TwitchBot(config)

        # Wait a tiny bit
        time.sleep(0.1)

        # Uptime should be > 0
        assert bot.uptime > 0
        assert isinstance(bot.uptime_str, str)


class TestFunCommands:
    """Tests for fun command logic."""

    def test_eight_ball_responses_exist(self) -> None:
        """Test that 8-ball responses are defined."""
        from bot.cogs.fun import EIGHT_BALL_RESPONSES

        assert len(EIGHT_BALL_RESPONSES) == 20
        assert all(isinstance(r, str) for r in EIGHT_BALL_RESPONSES)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
