"""
Main Twitch bot class.

This module contains the TwitchBot class which handles:
- Connection to Twitch IRC
- Loading and managing cogs
- Event handling
- Graceful shutdown
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from twitchio.ext import commands

from bot.config import Config
from bot.utils.logging import get_logger

if TYPE_CHECKING:
    from twitchio import Channel, Message

logger = get_logger(__name__)


class TwitchBot(commands.Bot):
    """
    Production-ready Twitch chat bot.

    Features:
    - Modular cog system for commands
    - Permission system for mods/owners
    - Configurable command prefix
    - Graceful shutdown handling
    - Auto-moderation system
    - Custom commands
    - Timers
    - Loyalty points
    - Strike system
    - Nuke command

    Attributes:
        config: Bot configuration
        start_time: Bot start timestamp for uptime tracking
    """

    def __init__(self, config: Config) -> None:
        """
        Initialize the Twitch bot.

        Args:
            config: Bot configuration object
        """
        self.config = config
        self.start_time = datetime.now(timezone.utc)
        self._ready = asyncio.Event()

        # Initialize the bot with TwitchIO
        super().__init__(
            token=config.oauth_token,
            client_id=config.client_id,
            nick=config.bot_nick,
            prefix=config.prefix,
            initial_channels=config.channels,
        )

        logger.info(
            "Bot initialized for channels: %s",
            ", ".join(config.channels),
        )

        # Load cogs immediately (TwitchIO 2.x style)
        self._load_cogs()

    def _load_cogs(self) -> None:
        """Load all enabled cogs based on configuration."""
        cogs_to_load: list[tuple[str, bool]] = [
            ("bot.cogs.admin", self.config.enable_admin_commands),
            ("bot.cogs.fun", self.config.enable_fun_commands),
            ("bot.cogs.moderation", self.config.enable_moderation),
            ("bot.cogs.info", self.config.enable_info_commands),
            ("bot.cogs.clips", True),
            ("bot.cogs.automod", True),  # AutoMod always enabled
            ("bot.cogs.customcmds", True),  # Custom commands always enabled
            ("bot.cogs.timers", True),  # Timers always enabled
            ("bot.cogs.loyalty", True),  # Loyalty always enabled (but toggleable per channel)
            ("bot.cogs.nuke", True),  # Nuke command always enabled
        ]

        for cog_path, enabled in cogs_to_load:
            if enabled:
                try:
                    self.load_module(cog_path)
                    logger.info("Loaded cog: %s", cog_path)
                except Exception as e:
                    logger.error("Failed to load cog %s: %s", cog_path, e)

    async def event_ready(self) -> None:
        """Called when the bot is ready and connected."""
        logger.info("Bot is ready!")
        logger.info("Logged in as: %s", self.nick)
        logger.info("Connected to channels: %s", ", ".join(c.name for c in self.connected_channels))
        self._ready.set()

    async def event_channel_joined(self, channel: Channel) -> None:
        """
        Called when the bot joins a channel.

        Args:
            channel: The channel that was joined
        """
        logger.info("Joined channel: %s", channel.name)

    async def event_message(self, message: Message) -> None:
        """
        Called when a message is received.

        Args:
            message: The received message
        """
        # Ignore messages from the bot itself
        if message.echo:
            return

        # Log message for debugging (content might be sensitive)
        logger.debug(
            "[%s] %s: %s",
            message.channel.name if message.channel else "DM",
            message.author.name if message.author else "Unknown",
            message.content[:50] + "..." if len(message.content) > 50 else message.content,
        )

        # Process commands
        await self.handle_commands(message)

    async def event_command_error(
        self,
        context: commands.Context,
        error: Exception,
    ) -> None:
        """
        Called when a command raises an error.

        Args:
            context: Command context
            error: The exception that was raised
        """
        if isinstance(error, commands.CommandNotFound):
            # Silently ignore unknown commands
            return

        if isinstance(error, commands.MissingRequiredArgument):
            await context.send(
                f"@{context.author.name} Missing required argument. "
                f"Use {self.config.prefix}help {context.command.name} for usage."
            )
            return

        if isinstance(error, commands.CheckFailure):
            # Permission check failed - already handled by decorators
            return

        # Log unexpected errors
        logger.exception(
            "Error in command %s: %s",
            context.command.name if context.command else "unknown",
            error,
        )
        await context.send(
            f"@{context.author.name} An error occurred while processing your command."
        )

    async def reload_cog(self, cog_name: str) -> bool:
        """
        Reload a cog by name.

        Args:
            cog_name: Name of the cog to reload (e.g., "fun", "admin")

        Returns:
            bool: True if reload was successful
        """
        full_path = f"bot.cogs.{cog_name}"
        try:
            self.unload_module(full_path)
            self.load_module(full_path)
            logger.info("Reloaded cog: %s", full_path)
            return True
        except Exception as e:
            logger.error("Failed to reload cog %s: %s", cog_name, e)
            return False

    async def wait_until_ready(self) -> None:
        """Wait until the bot is fully ready."""
        await self._ready.wait()

    @property
    def uptime(self) -> float:
        """Get bot uptime in seconds."""
        return (datetime.now(timezone.utc) - self.start_time).total_seconds()

    @property
    def uptime_str(self) -> str:
        """Get bot uptime as a formatted string."""
        seconds = int(self.uptime)
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)

        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        parts.append(f"{seconds}s")

        return " ".join(parts)
