"""
Admin commands cog.

Provides owner-only administrative commands:
- !shutdown: Gracefully stop the bot
- !reload: Reload a cog
- !ping: Check bot latency
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from twitchio.ext import commands
from twitchio.ext.commands import Context

from bot.utils.logging import get_logger
from bot.utils.permissions import is_owner, cooldown, CooldownBucket

if TYPE_CHECKING:
    from bot.bot import TwitchBot

logger = get_logger(__name__)


class AdminCog(commands.Cog):
    """
    Administrative commands for bot management.

    All commands in this cog are restricted to the bot owner.
    """

    def __init__(self, bot: TwitchBot) -> None:
        """
        Initialize the admin cog.

        Args:
            bot: The bot instance
        """
        self.bot = bot

    @commands.command(name="shutdown", aliases=["stop", "quit"])
    @is_owner()
    async def shutdown(self, ctx: Context) -> None:
        """
        Gracefully shutdown the bot.

        Usage: !shutdown

        Only the bot owner can use this command.
        """
        logger.info("Shutdown command received from %s", ctx.author.name)
        await ctx.send("Shutting down... Goodbye! 👋")

        # Give time for the message to send
        await asyncio.sleep(1)

        # Close the bot
        await self.bot.close()

    @commands.command(name="reload")
    @is_owner()
    async def reload_cog(self, ctx: Context, cog_name: str | None = None) -> None:
        """
        Reload a cog to apply code changes.

        Usage: !reload <cog_name>
        Example: !reload fun

        Available cogs: admin, fun, moderation, info

        Only the bot owner can use this command.
        """
        if not cog_name:
            await ctx.send(
                f"@{ctx.author.name} Usage: {self.bot.config.prefix}reload <cog_name> "
                "(admin, fun, moderation, info)"
            )
            return

        cog_name = cog_name.lower()
        valid_cogs = ["admin", "fun", "moderation", "info"]

        if cog_name not in valid_cogs:
            await ctx.send(
                f"@{ctx.author.name} Invalid cog. Available: {', '.join(valid_cogs)}"
            )
            return

        logger.info("Reloading cog: %s (requested by %s)", cog_name, ctx.author.name)

        success = await self.bot.reload_cog(cog_name)
        if success:
            await ctx.send(f"@{ctx.author.name} Successfully reloaded {cog_name} cog! ✅")
        else:
            await ctx.send(f"@{ctx.author.name} Failed to reload {cog_name} cog. Check logs.")

    @commands.command(name="ping")
    @cooldown(rate=5.0, bucket=CooldownBucket.USER)
    async def ping(self, ctx: Context) -> None:
        """
        Check if the bot is responsive and show latency.

        Usage: !ping
        """
        # TwitchIO doesn't have built-in latency like Discord.py
        # We'll just respond to show the bot is alive
        await ctx.send(f"@{ctx.author.name} Pong! 🏓 Bot is online and responsive.")

    @commands.command(name="status")
    @is_owner()
    async def status(self, ctx: Context) -> None:
        """
        Show bot status information.

        Usage: !status

        Only the bot owner can use this command.
        """
        channels = len(self.bot.connected_channels)
        uptime = self.bot.uptime_str

        # Count loaded cogs
        cogs = len(self.bot.cogs)

        await ctx.send(
            f"@{ctx.author.name} Status: Online | "
            f"Uptime: {uptime} | "
            f"Channels: {channels} | "
            f"Cogs: {cogs}"
        )


def prepare(bot: TwitchBot) -> None:
    """
    Prepare function called by TwitchIO when loading the cog.

    Args:
        bot: The bot instance
    """
    bot.add_cog(AdminCog(bot))
