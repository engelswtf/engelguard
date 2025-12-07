"""
Loyalty points cog for Twitch bot.

Provides a toggleable points system with:
- Points for watching
- Points for chatting
- Subscriber/VIP multipliers
- Leaderboards
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Optional, Any

from twitchio.ext import commands
from twitchio.ext.commands import Context

from bot.utils.database import get_database, DatabaseManager
from bot.utils.logging import get_logger
from bot.utils.permissions import is_owner, is_moderator

if TYPE_CHECKING:
    from twitchio import Message
    from bot.bot import TwitchBot

logger = get_logger(__name__)


class Loyalty(commands.Cog):
    """
    Loyalty points cog for viewer engagement.
    
    Features:
    - Earn points for watching (per minute)
    - Earn points for chatting
    - Subscriber/VIP multipliers
    - Customizable points name
    - Leaderboard
    """
    
    def __init__(self, bot: TwitchBot) -> None:
        """Initialize the loyalty cog."""
        self.bot = bot
        self.db: DatabaseManager = get_database()
        
        # Track active chatters for watch time points
        self._active_chatters: dict[str, set[str]] = {}  # {channel: {user_id, ...}}
        self._last_point_award: datetime = datetime.now(timezone.utc)
        
        # Points task
        self._points_task: Optional[asyncio.Task] = None
        self._running = False
        
        logger.info("Loyalty cog initialized")
    
    async def cog_load(self) -> None:
        """Called when cog is loaded."""
        self._running = True
        self._points_task = asyncio.create_task(self._points_loop())
        logger.info("Loyalty points loop started")
    
    async def cog_unload(self) -> None:
        """Called when cog is unloaded."""
        self._running = False
        if self._points_task:
            self._points_task.cancel()
            try:
                await self._points_task
            except asyncio.CancelledError:
                pass
        logger.info("Loyalty points loop stopped")
    
    async def _points_loop(self) -> None:
        """Award watch time points every minute."""
        await self.bot.wait_until_ready()
        
        while self._running:
            try:
                await self._award_watch_points()
            except Exception as e:
                logger.error("Error in points loop: %s", e)
            
            # Award points every minute
            await asyncio.sleep(60)
    
    async def _award_watch_points(self) -> None:
        """Award watch time points to active chatters."""
        for channel in self.bot.connected_channels:
            channel_name = channel.name
            
            # Check if loyalty is enabled for this channel
            settings = self.db.get_loyalty_settings(channel_name)
            if not settings.get("enabled", False):
                continue
            
            points_per_minute = settings.get("points_per_minute", 1.0)
            
            # Get active chatters for this channel
            active = self._active_chatters.get(channel_name, set())
            
            for user_id in active:
                # Award points (we don't have sub/vip info here, so base rate)
                self.db.update_user_loyalty(
                    user_id=user_id,
                    username="",  # Will be updated on next message
                    channel=channel_name,
                    points_delta=points_per_minute,
                    watch_time_delta=1
                )
            
            # Clear active chatters for next minute
            self._active_chatters[channel_name] = set()
    
    @commands.Cog.event()
    async def event_message(self, message: Message) -> None:
        """Track chat activity and award message points."""
        if message.echo or not message.author or not message.channel:
            return
        
        channel_name = message.channel.name
        user_id = str(message.author.id)
        username = message.author.name
        
        # Check if loyalty is enabled
        settings = self.db.get_loyalty_settings(channel_name)
        if not settings.get("enabled", False):
            return
        
        # Mark user as active for watch time
        if channel_name not in self._active_chatters:
            self._active_chatters[channel_name] = set()
        self._active_chatters[channel_name].add(user_id)
        
        # Award message points
        points_per_message = settings.get("points_per_message", 0.5)
        
        # Apply multipliers
        is_subscriber = getattr(message.author, "is_subscriber", False)
        is_vip = getattr(message.author, "is_vip", False)
        
        multiplier = 1.0
        if is_subscriber:
            multiplier = settings.get("bonus_sub_multiplier", 2.0)
        elif is_vip:
            multiplier = settings.get("bonus_vip_multiplier", 1.5)
        
        points = points_per_message * multiplier
        
        self.db.update_user_loyalty(
            user_id=user_id,
            username=username,
            channel=channel_name,
            points_delta=points,
            message_count_delta=1
        )
    
    def _get_points_name(self, channel: str) -> str:
        """Get the custom points name for a channel."""
        settings = self.db.get_loyalty_settings(channel)
        return settings.get("points_name", "points")
    
    @commands.command(name="points", aliases=["balance", "coins"])
    async def check_points(self, ctx: Context, username: str = "") -> None:
        """Check your points or another user's points. Usage: !points [@user]"""
        channel_name = ctx.channel.name
        
        # Check if loyalty is enabled
        settings = self.db.get_loyalty_settings(channel_name)
        if not settings.get("enabled", False):
            await ctx.send(f"@{ctx.author.name} Loyalty points are not enabled.")
            return
        
        points_name = settings.get("points_name", "points")
        
        # Check target user
        if username:
            target_name = username.lstrip("@").lower()
            # We need to find user_id from username - simplified approach
            target_id = target_name
        else:
            target_name = ctx.author.name
            target_id = str(ctx.author.id)
        
        loyalty = self.db.get_user_loyalty(target_id, channel_name)
        points = int(loyalty.get("points", 0))
        watch_time = loyalty.get("watch_time_minutes", 0)
        
        # Format watch time
        hours = watch_time // 60
        minutes = watch_time % 60
        if hours > 0:
            time_str = f"{hours}h {minutes}m"
        else:
            time_str = f"{minutes}m"
        
        await ctx.send(f"@{target_name} has {points:,} {points_name} | Watch time: {time_str}")
    
    @commands.command(name="watchtime", aliases=["wt"])
    async def check_watchtime(self, ctx: Context, username: str = "") -> None:
        """Check your watch time. Usage: !watchtime [@user]"""
        channel_name = ctx.channel.name
        
        settings = self.db.get_loyalty_settings(channel_name)
        if not settings.get("enabled", False):
            await ctx.send(f"@{ctx.author.name} Loyalty system is not enabled.")
            return
        
        if username:
            target_name = username.lstrip("@").lower()
            target_id = target_name
        else:
            target_name = ctx.author.name
            target_id = str(ctx.author.id)
        
        loyalty = self.db.get_user_loyalty(target_id, channel_name)
        watch_time = loyalty.get("watch_time_minutes", 0)
        
        hours = watch_time // 60
        minutes = watch_time % 60
        
        if hours > 0:
            time_str = f"{hours} hours and {minutes} minutes"
        else:
            time_str = f"{minutes} minutes"
        
        await ctx.send(f"@{target_name} has watched for {time_str}")
    
    @commands.command(name="top", aliases=["leaderboard", "lb"])
    async def leaderboard(self, ctx: Context, count: str = "5") -> None:
        """Show the points leaderboard. Usage: !top [count]"""
        channel_name = ctx.channel.name
        
        settings = self.db.get_loyalty_settings(channel_name)
        if not settings.get("enabled", False):
            await ctx.send(f"@{ctx.author.name} Loyalty points are not enabled.")
            return
        
        try:
            limit = min(int(count), 10)
        except ValueError:
            limit = 5
        
        points_name = settings.get("points_name", "points")
        leaders = self.db.get_loyalty_leaderboard(channel_name, limit)
        
        if not leaders:
            await ctx.send(f"@{ctx.author.name} No leaderboard data yet.")
            return
        
        entries = []
        for i, user in enumerate(leaders, 1):
            username = user.get("username", "Unknown")
            points = int(user.get("points", 0))
            entries.append(f"{i}. {username}: {points:,}")
        
        await ctx.send(f"Top {points_name}: " + " | ".join(entries))
    
    # ==================== Admin Commands ====================
    
    @commands.command(name="loyalty")
    @is_owner()
    async def loyalty_toggle(self, ctx: Context, action: str = "status") -> None:
        """Enable/disable loyalty system. Usage: !loyalty <on/off/status>"""
        channel_name = ctx.channel.name
        action = action.lower()
        
        if action == "on":
            self.db.update_loyalty_settings(channel_name, enabled=True)
            await ctx.send(f"@{ctx.author.name} Loyalty points system ENABLED!")
            logger.info("Loyalty enabled for %s by %s", channel_name, ctx.author.name)
        elif action == "off":
            self.db.update_loyalty_settings(channel_name, enabled=False)
            await ctx.send(f"@{ctx.author.name} Loyalty points system DISABLED.")
            logger.info("Loyalty disabled for %s by %s", channel_name, ctx.author.name)
        else:
            settings = self.db.get_loyalty_settings(channel_name)
            status = "ENABLED" if settings.get("enabled", False) else "DISABLED"
            points_name = settings.get("points_name", "points")
            ppm = settings.get("points_per_minute", 1.0)
            ppmsg = settings.get("points_per_message", 0.5)
            await ctx.send(f"@{ctx.author.name} Loyalty: {status} | Name: {points_name} | {ppm}/min, {ppmsg}/msg")
    
    @commands.command(name="setpointsname")
    @is_owner()
    async def set_points_name(self, ctx: Context, name: str = "") -> None:
        """Set custom name for points. Usage: !setpointsname <name>"""
        if not name:
            await ctx.send(f"@{ctx.author.name} Usage: !setpointsname <name>")
            return
        
        channel_name = ctx.channel.name
        self.db.update_loyalty_settings(channel_name, points_name=name)
        await ctx.send(f"@{ctx.author.name} Points are now called '{name}'")
    
    @commands.command(name="setpointsrate")
    @is_owner()
    async def set_points_rate(self, ctx: Context, per_minute: str = "", per_message: str = "") -> None:
        """Set points earning rates. Usage: !setpointsrate <per_minute> <per_message>"""
        if not per_minute:
            await ctx.send(f"@{ctx.author.name} Usage: !setpointsrate <per_minute> <per_message>")
            return
        
        try:
            ppm = float(per_minute)
            ppmsg = float(per_message) if per_message else 0.5
        except ValueError:
            await ctx.send(f"@{ctx.author.name} Rates must be numbers")
            return
        
        channel_name = ctx.channel.name
        self.db.update_loyalty_settings(channel_name, points_per_minute=ppm, points_per_message=ppmsg)
        await ctx.send(f"@{ctx.author.name} Points rate: {ppm}/min, {ppmsg}/msg")
    
    @commands.command(name="givepoints")
    @is_moderator()
    async def give_points(self, ctx: Context, username: str = "", amount: str = "") -> None:
        """Give points to a user. Usage: !givepoints <user> <amount>"""
        if not username or not amount:
            await ctx.send(f"@{ctx.author.name} Usage: !givepoints <user> <amount>")
            return
        
        channel_name = ctx.channel.name
        settings = self.db.get_loyalty_settings(channel_name)
        if not settings.get("enabled", False):
            await ctx.send(f"@{ctx.author.name} Loyalty points are not enabled.")
            return
        
        try:
            points = int(amount)
        except ValueError:
            await ctx.send(f"@{ctx.author.name} Amount must be a number")
            return
        
        target_name = username.lstrip("@").lower()
        target_id = target_name  # Simplified
        
        self.db.update_user_loyalty(
            user_id=target_id,
            username=target_name,
            channel=channel_name,
            points_delta=points
        )
        
        points_name = settings.get("points_name", "points")
        await ctx.send(f"@{ctx.author.name} Gave {points:,} {points_name} to {target_name}")
        logger.info("%s gave %d points to %s", ctx.author.name, points, target_name)
    
    @commands.command(name="removepoints")
    @is_moderator()
    async def remove_points(self, ctx: Context, username: str = "", amount: str = "") -> None:
        """Remove points from a user. Usage: !removepoints <user> <amount>"""
        if not username or not amount:
            await ctx.send(f"@{ctx.author.name} Usage: !removepoints <user> <amount>")
            return
        
        channel_name = ctx.channel.name
        settings = self.db.get_loyalty_settings(channel_name)
        if not settings.get("enabled", False):
            await ctx.send(f"@{ctx.author.name} Loyalty points are not enabled.")
            return
        
        try:
            points = int(amount)
        except ValueError:
            await ctx.send(f"@{ctx.author.name} Amount must be a number")
            return
        
        target_name = username.lstrip("@").lower()
        target_id = target_name
        
        self.db.update_user_loyalty(
            user_id=target_id,
            username=target_name,
            channel=channel_name,
            points_delta=-points
        )
        
        points_name = settings.get("points_name", "points")
        await ctx.send(f"@{ctx.author.name} Removed {points:,} {points_name} from {target_name}")
        logger.info("%s removed %d points from %s", ctx.author.name, points, target_name)
    
    @commands.command(name="resetpoints")
    @is_owner()
    async def reset_points(self, ctx: Context, username: str = "") -> None:
        """Reset a user's points to 0. Usage: !resetpoints <user>"""
        if not username:
            await ctx.send(f"@{ctx.author.name} Usage: !resetpoints <user>")
            return
        
        channel_name = ctx.channel.name
        target_name = username.lstrip("@").lower()
        target_id = target_name
        
        self.db.set_user_points(target_id, channel_name, 0)
        
        await ctx.send(f"@{ctx.author.name} Reset points for {target_name}")
        logger.info("%s reset points for %s", ctx.author.name, target_name)


def prepare(bot: TwitchBot) -> None:
    """Prepare the cog for loading."""
    bot.add_cog(Loyalty(bot))
