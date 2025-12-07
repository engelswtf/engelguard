"""
Permission decorators and utilities for Twitch bot commands.

Provides decorators for:
- Owner-only commands
- Moderator-only commands
- Subscriber-only commands
- Cooldown management
- Cog enabled checks
"""

from __future__ import annotations

import time
from collections import defaultdict
from enum import Enum
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, TypeVar

from twitchio.ext.commands import Context

from bot.utils.logging import get_logger

logger = get_logger(__name__)

# Type variable for decorated functions
F = TypeVar("F", bound=Callable[..., Any])


class CooldownBucket(Enum):
    """Cooldown bucket types for rate limiting."""

    USER = "user"  # Per-user cooldown
    CHANNEL = "channel"  # Per-channel cooldown
    GLOBAL = "global"  # Global cooldown


class CooldownManager:
    """
    Manages command cooldowns.

    Tracks when commands were last used and enforces cooldown periods.
    """

    def __init__(self) -> None:
        """Initialize the cooldown manager."""
        # Structure: {command_name: {bucket_key: last_used_timestamp}}
        self._cooldowns: dict[str, dict[str, float]] = defaultdict(dict)

    def get_bucket_key(
        self, ctx: Context, bucket: CooldownBucket
    ) -> str:
        """
        Get the bucket key for a context and bucket type.

        Args:
            ctx: Command context
            bucket: Cooldown bucket type

        Returns:
            str: Bucket key for tracking cooldown
        """
        if bucket == CooldownBucket.USER:
            return f"{ctx.channel.name}:{ctx.author.name}"
        elif bucket == CooldownBucket.CHANNEL:
            return ctx.channel.name
        else:  # GLOBAL
            return "global"

    def check_cooldown(
        self,
        command_name: str,
        ctx: Context,
        rate: float,
        bucket: CooldownBucket,
    ) -> tuple[bool, float]:
        """
        Check if a command is on cooldown.

        Args:
            command_name: Name of the command
            ctx: Command context
            rate: Cooldown duration in seconds
            bucket: Cooldown bucket type

        Returns:
            tuple[bool, float]: (is_on_cooldown, remaining_time)
        """
        bucket_key = self.get_bucket_key(ctx, bucket)
        last_used = self._cooldowns[command_name].get(bucket_key, 0)
        now = time.time()
        elapsed = now - last_used

        if elapsed < rate:
            return True, rate - elapsed
        return False, 0

    def update_cooldown(
        self,
        command_name: str,
        ctx: Context,
        bucket: CooldownBucket,
    ) -> None:
        """
        Update the cooldown timestamp for a command.

        Args:
            command_name: Name of the command
            ctx: Command context
            bucket: Cooldown bucket type
        """
        bucket_key = self.get_bucket_key(ctx, bucket)
        self._cooldowns[command_name][bucket_key] = time.time()

    def reset_cooldown(
        self,
        command_name: str,
        ctx: Context,
        bucket: CooldownBucket,
    ) -> None:
        """
        Reset the cooldown for a command.

        Args:
            command_name: Name of the command
            ctx: Command context
            bucket: Cooldown bucket type
        """
        bucket_key = self.get_bucket_key(ctx, bucket)
        if command_name in self._cooldowns:
            self._cooldowns[command_name].pop(bucket_key, None)


# Global cooldown manager
_cooldown_manager = CooldownManager()


def is_owner() -> Callable[[F], F]:
    """
    Decorator that restricts a command to the bot owner only.

    Usage:
        @commands.command()
        @is_owner()
        async def shutdown(self, ctx):
            ...
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(self: Any, ctx: Context, *args: Any, **kwargs: Any) -> Any:
            # Get owner from bot config
            owner = getattr(self.bot, "config", None)
            if owner:
                owner = owner.owner.lower()
            else:
                # Fallback: try to get from cog's bot
                owner = getattr(getattr(self, "bot", None), "config", {})
                owner = getattr(owner, "owner", "").lower()

            if ctx.author.name.lower() != owner:
                logger.warning(
                    "Unauthorized owner command attempt by %s in %s",
                    ctx.author.name,
                    ctx.channel.name,
                )
                await ctx.send(f"@{ctx.author.name} This command is owner-only.")
                return None

            return await func(self, ctx, *args, **kwargs)

        # Mark as owner-only for help system
        wrapper._is_owner_only = True  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator


def is_moderator() -> Callable[[F], F]:
    """
    Decorator that restricts a command to moderators and above.

    Allows: Broadcaster, Moderators, Bot Owner

    Usage:
        @commands.command()
        @is_moderator()
        async def timeout(self, ctx, user: str):
            ...
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(self: Any, ctx: Context, *args: Any, **kwargs: Any) -> Any:
            # Check if user is mod, broadcaster, or owner
            is_mod = ctx.author.is_mod
            is_broadcaster = ctx.author.is_broadcaster

            # Check if bot owner
            owner = ""
            config = getattr(self.bot, "config", None)
            if config:
                owner = config.owner.lower()

            is_owner_user = ctx.author.name.lower() == owner

            if not (is_mod or is_broadcaster or is_owner_user):
                logger.warning(
                    "Unauthorized mod command attempt by %s in %s",
                    ctx.author.name,
                    ctx.channel.name,
                )
                await ctx.send(f"@{ctx.author.name} This command is for moderators only.")
                return None

            return await func(self, ctx, *args, **kwargs)

        wrapper._is_mod_only = True  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator


def is_subscriber() -> Callable[[F], F]:
    """
    Decorator that restricts a command to subscribers and above.

    Allows: Subscribers, VIPs, Moderators, Broadcaster, Bot Owner

    Usage:
        @commands.command()
        @is_subscriber()
        async def sub_command(self, ctx):
            ...
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(self: Any, ctx: Context, *args: Any, **kwargs: Any) -> Any:
            # Check various privilege levels
            is_sub = ctx.author.is_subscriber
            is_vip = getattr(ctx.author, "is_vip", False)
            is_mod = ctx.author.is_mod
            is_broadcaster = ctx.author.is_broadcaster

            # Check if bot owner
            owner = ""
            config = getattr(self.bot, "config", None)
            if config:
                owner = config.owner.lower()

            is_owner_user = ctx.author.name.lower() == owner

            if not (is_sub or is_vip or is_mod or is_broadcaster or is_owner_user):
                await ctx.send(f"@{ctx.author.name} This command is for subscribers only.")
                return None

            return await func(self, ctx, *args, **kwargs)

        wrapper._is_sub_only = True  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator


def cooldown(
    rate: float = 3.0,
    bucket: CooldownBucket = CooldownBucket.USER,
) -> Callable[[F], F]:
    """
    Decorator that adds a cooldown to a command.

    Args:
        rate: Cooldown duration in seconds
        bucket: Cooldown bucket type (USER, CHANNEL, or GLOBAL)

    Usage:
        @commands.command()
        @cooldown(rate=5.0, bucket=CooldownBucket.USER)
        async def dice(self, ctx):
            ...
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(self: Any, ctx: Context, *args: Any, **kwargs: Any) -> Any:
            command_name = func.__name__

            # Check cooldown
            on_cooldown, remaining = _cooldown_manager.check_cooldown(
                command_name, ctx, rate, bucket
            )

            if on_cooldown:
                # Silently ignore or send message based on remaining time
                if remaining > 1:
                    logger.debug(
                        "Command %s on cooldown for %s (%.1fs remaining)",
                        command_name,
                        ctx.author.name,
                        remaining,
                    )
                return None

            # Update cooldown and execute
            _cooldown_manager.update_cooldown(command_name, ctx, bucket)
            return await func(self, ctx, *args, **kwargs)

        wrapper._cooldown_rate = rate  # type: ignore[attr-defined]
        wrapper._cooldown_bucket = bucket  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator


def reset_cooldown(
    command_name: str,
    ctx: Context,
    bucket: CooldownBucket = CooldownBucket.USER,
) -> None:
    """
    Reset the cooldown for a command.

    Useful for allowing retry after errors.

    Args:
        command_name: Name of the command
        ctx: Command context
        bucket: Cooldown bucket type
    """
    _cooldown_manager.reset_cooldown(command_name, ctx, bucket)


def cog_enabled(cog_name: str) -> Callable[[F], F]:
    """
    Decorator that checks if a cog is enabled for the channel.

    Commands decorated with this will silently fail if the cog
    is disabled for the channel where the command is invoked.

    Args:
        cog_name: Name of the cog to check (e.g., "fun", "moderation")

    Usage:
        @commands.command()
        @cog_enabled("fun")
        async def dice(self, ctx):
            ...
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(self: Any, ctx: Context, *args: Any, **kwargs: Any) -> Any:
            # Import here to avoid circular imports
            from bot.utils.database import get_database

            db = get_database()
            channel_name = ctx.channel.name

            if not db.get_cog_enabled(channel_name, cog_name):
                logger.debug(
                    "Cog '%s' is disabled for channel '%s', ignoring command '%s'",
                    cog_name,
                    channel_name,
                    func.__name__,
                )
                return None  # Silently ignore if cog is disabled

            return await func(self, ctx, *args, **kwargs)

        wrapper._cog_name = cog_name  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator
