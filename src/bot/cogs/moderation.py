"""
Moderation commands cog.

Provides moderator-only commands:
- !timeout: Timeout a user
- !ban: Ban a user
- !unban: Unban a user
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from twitchio.ext import commands
from twitchio.ext.commands import Context

from bot.utils.logging import get_logger
from bot.utils.permissions import is_moderator, cooldown, CooldownBucket

if TYPE_CHECKING:
    from bot.bot import TwitchBot

logger = get_logger(__name__)


class ModerationCog(commands.Cog):
    """
    Moderation commands for channel management.

    All commands in this cog require moderator privileges.
    """

    def __init__(self, bot: TwitchBot) -> None:
        """
        Initialize the moderation cog.

        Args:
            bot: The bot instance
        """
        self.bot = bot

    @commands.command(name="timeout", aliases=["to", "mute"])
    @is_moderator()
    @cooldown(rate=1.0, bucket=CooldownBucket.CHANNEL)
    async def timeout_user(
        self,
        ctx: Context,
        user: str | None = None,
        duration: int = 600,
        *,
        reason: str = "No reason provided",
    ) -> None:
        """
        Timeout a user in the channel.

        Usage: !timeout @user [seconds] [reason]
        Examples:
            !timeout @baduser                    - 10 minute timeout
            !timeout @baduser 300                - 5 minute timeout
            !timeout @baduser 60 Being rude      - 1 minute timeout with reason

        Only moderators can use this command.
        """
        if not user:
            await ctx.send(
                f"@{ctx.author.name} Usage: {self.bot.config.prefix}timeout @user [seconds] [reason]"
            )
            return

        # Clean up username
        target = user.lstrip("@").lower()

        # Validate duration
        if duration < 1:
            await ctx.send(f"@{ctx.author.name} Duration must be at least 1 second.")
            return
        if duration > 1209600:  # 2 weeks max
            await ctx.send(f"@{ctx.author.name} Maximum timeout is 2 weeks (1209600 seconds).")
            return

        # Can't timeout the bot itself
        if target == self.bot.nick.lower():
            await ctx.send(f"@{ctx.author.name} I can't timeout myself! 😅")
            return

        # Can't timeout the broadcaster
        if target == ctx.channel.name.lower():
            await ctx.send(f"@{ctx.author.name} Can't timeout the broadcaster!")
            return

        try:
            # Use Twitch IRC timeout command
            await ctx.send(f"/timeout {target} {duration} {reason}")
            logger.info(
                "User %s timed out %s for %ds in %s: %s",
                ctx.author.name,
                target,
                duration,
                ctx.channel.name,
                reason,
            )

            # Format duration for display
            if duration >= 3600:
                duration_str = f"{duration // 3600}h {(duration % 3600) // 60}m"
            elif duration >= 60:
                duration_str = f"{duration // 60}m {duration % 60}s"
            else:
                duration_str = f"{duration}s"

            await ctx.send(f"@{ctx.author.name} Timed out {target} for {duration_str}. ⏱️")

        except Exception as e:
            logger.error("Failed to timeout %s: %s", target, e)
            await ctx.send(f"@{ctx.author.name} Failed to timeout user. Check bot permissions.")

    @commands.command(name="ban")
    @is_moderator()
    @cooldown(rate=1.0, bucket=CooldownBucket.CHANNEL)
    async def ban_user(
        self,
        ctx: Context,
        user: str | None = None,
        *,
        reason: str = "No reason provided",
    ) -> None:
        """
        Ban a user from the channel.

        Usage: !ban @user [reason]
        Examples:
            !ban @baduser
            !ban @baduser Spamming

        Only moderators can use this command.
        """
        if not user:
            await ctx.send(
                f"@{ctx.author.name} Usage: {self.bot.config.prefix}ban @user [reason]"
            )
            return

        # Clean up username
        target = user.lstrip("@").lower()

        # Can't ban the bot itself
        if target == self.bot.nick.lower():
            await ctx.send(f"@{ctx.author.name} I can't ban myself! 😅")
            return

        # Can't ban the broadcaster
        if target == ctx.channel.name.lower():
            await ctx.send(f"@{ctx.author.name} Can't ban the broadcaster!")
            return

        try:
            # Use Twitch IRC ban command
            await ctx.send(f"/ban {target} {reason}")
            logger.info(
                "User %s banned %s in %s: %s",
                ctx.author.name,
                target,
                ctx.channel.name,
                reason,
            )
            await ctx.send(f"@{ctx.author.name} Banned {target}. 🔨")

        except Exception as e:
            logger.error("Failed to ban %s: %s", target, e)
            await ctx.send(f"@{ctx.author.name} Failed to ban user. Check bot permissions.")

    @commands.command(name="unban")
    @is_moderator()
    @cooldown(rate=1.0, bucket=CooldownBucket.CHANNEL)
    async def unban_user(
        self,
        ctx: Context,
        user: str | None = None,
    ) -> None:
        """
        Unban a user from the channel.

        Usage: !unban @user
        Example: !unban @forgiven_user

        Only moderators can use this command.
        """
        if not user:
            await ctx.send(f"@{ctx.author.name} Usage: {self.bot.config.prefix}unban @user")
            return

        # Clean up username
        target = user.lstrip("@").lower()

        try:
            # Use Twitch IRC unban command
            await ctx.send(f"/unban {target}")
            logger.info(
                "User %s unbanned %s in %s",
                ctx.author.name,
                target,
                ctx.channel.name,
            )
            await ctx.send(f"@{ctx.author.name} Unbanned {target}. ✅")

        except Exception as e:
            logger.error("Failed to unban %s: %s", target, e)
            await ctx.send(f"@{ctx.author.name} Failed to unban user. Check bot permissions.")

    @commands.command(name="clear", aliases=["clearchat"])
    @is_moderator()
    @cooldown(rate=10.0, bucket=CooldownBucket.CHANNEL)
    async def clear_chat(self, ctx: Context) -> None:
        """
        Clear the chat.

        Usage: !clear

        Only moderators can use this command.
        """
        try:
            await ctx.send("/clear")
            logger.info("Chat cleared by %s in %s", ctx.author.name, ctx.channel.name)

        except Exception as e:
            logger.error("Failed to clear chat: %s", e)
            await ctx.send(f"@{ctx.author.name} Failed to clear chat. Check bot permissions.")

    @commands.command(name="slowmode", aliases=["slow"])
    @is_moderator()
    @cooldown(rate=5.0, bucket=CooldownBucket.CHANNEL)
    async def slowmode(
        self,
        ctx: Context,
        seconds: int | None = None,
    ) -> None:
        """
        Enable or disable slow mode.

        Usage: !slowmode [seconds]
        Examples:
            !slowmode 30    - Enable 30 second slow mode
            !slowmode 0     - Disable slow mode
            !slowmode       - Show current status

        Only moderators can use this command.
        """
        if seconds is None:
            await ctx.send(
                f"@{ctx.author.name} Usage: {self.bot.config.prefix}slowmode <seconds> "
                "(0 to disable)"
            )
            return

        if seconds < 0 or seconds > 120:
            await ctx.send(f"@{ctx.author.name} Slow mode must be between 0-120 seconds.")
            return

        try:
            if seconds == 0:
                await ctx.send("/slowoff")
                await ctx.send(f"@{ctx.author.name} Slow mode disabled. ✅")
            else:
                await ctx.send(f"/slow {seconds}")
                await ctx.send(f"@{ctx.author.name} Slow mode set to {seconds} seconds. 🐌")

            logger.info(
                "Slow mode set to %ds by %s in %s",
                seconds,
                ctx.author.name,
                ctx.channel.name,
            )

        except Exception as e:
            logger.error("Failed to set slow mode: %s", e)
            await ctx.send(f"@{ctx.author.name} Failed to set slow mode.")


def prepare(bot: TwitchBot) -> None:
    """
    Prepare function called by TwitchIO when loading the cog.

    Args:
        bot: The bot instance
    """
    bot.add_cog(ModerationCog(bot))
