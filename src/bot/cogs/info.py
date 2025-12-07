"""
Info commands cog.

Provides informational commands:
- !help: Show help for commands
- !bot: Show bot information (owner-only)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import aiohttp
from twitchio.ext import commands
from twitchio.ext.commands import Context

from bot.utils.logging import get_logger
from bot.utils.permissions import cooldown, CooldownBucket, is_owner

if TYPE_CHECKING:
    from bot.bot import TwitchBot

logger = get_logger(__name__)


class InfoCog(commands.Cog):
    """
    Informational commands for users.

    Provides help and bot information.
    """

    def __init__(self, bot: TwitchBot) -> None:
        """
        Initialize the info cog.

        Args:
            bot: The bot instance
        """
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def cog_unload(self) -> None:
        """Clean up when cog is unloaded."""
        if self._session and not self._session.closed:
            # Schedule cleanup
            import asyncio

            asyncio.create_task(self._session.close())

    @commands.command(name="help", aliases=["commands", "cmds"])
    @cooldown(rate=5.0, bucket=CooldownBucket.USER)
    async def help_command(
        self,
        ctx: Context,
        command_name: str | None = None,
    ) -> None:
        """
        Show help for commands.

        Usage: !help [command]
        Examples:
            !help           - Show all commands
            !help dice      - Show help for dice command
        """
        prefix = self.bot.config.prefix

        if command_name:
            # Show help for specific command
            cmd = self.bot.get_command(command_name.lower())
            if cmd:
                # Get docstring for help text
                doc = cmd.callback.__doc__ or "No description available."
                # Get first paragraph
                help_text = doc.strip().split("\n\n")[0].replace("\n", " ").strip()
                await ctx.send(f"@{ctx.author.name} {prefix}{cmd.name}: {help_text}")
            else:
                await ctx.send(f"@{ctx.author.name} Command '{command_name}' not found.")
            return

        # Show all commands grouped by category
        command_groups = {
            "Fun": ["hello", "dice", "8ball", "coinflip", "hug", "rps", "choose"],
            "Info": ["help", "uptime", "followage"],
            "Stream": ["clip", "title", "game", "shoutout"],
            "Mod": ["timeout", "ban", "unban", "clear", "slowmode"],
            "Admin": ["shutdown", "reload", "ping", "status", "bot"],
        }

        # Build compact command list
        available = []
        for category, cmds in command_groups.items():
            existing = [c for c in cmds if self.bot.get_command(c)]
            if existing:
                available.append(f"{category}: {', '.join(existing)}")

        response = f"Commands ({prefix}): " + " | ".join(available)
        response += f" | Use {prefix}help <command> for details."

        await ctx.send(f"@{ctx.author.name} {response}")

    @commands.command(name="bot", aliases=["botinfo", "about"])
    @is_owner()
    async def show_bot_info(self, ctx: Context) -> None:
        """
        Show information about the bot (owner-only).

        Usage: !bot
        """
        from bot import __version__

        uptime = self.bot.uptime_str
        channels = len(self.bot.connected_channels)
        prefix = self.bot.config.prefix
        cogs = len(self.bot.cogs)

        await ctx.send(
            f"@{ctx.author.name} 🤖 EngelGuard v{__version__} | "
            f"Uptime: {uptime} | "
            f"Channels: {channels} | "
            f"Cogs: {cogs} | "
            f"Prefix: {prefix} | "
            f"Use {prefix}help for commands"
        )


def prepare(bot: TwitchBot) -> None:
    """
    Prepare function called by TwitchIO when loading the cog.

    Args:
        bot: The bot instance
    """
    bot.add_cog(InfoCog(bot))
