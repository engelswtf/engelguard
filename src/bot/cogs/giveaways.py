"""
Giveaway system cog for Twitch bot.

Provides a complete giveaway system with:
- Keyword-based entry
- Optional timed duration (auto-end)
- Subscriber luck multiplier
- Eligibility requirements (follower-only, sub-only, min points)
- Multiple winners support
- Reroll capability
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from twitchio.ext import commands
from twitchio.ext.commands import Context

from bot.utils.database import get_database, DatabaseManager
from bot.utils.logging import get_logger
from bot.utils.permissions import is_moderator

if TYPE_CHECKING:
    from twitchio import Message
    from bot.bot import TwitchBot

logger = get_logger(__name__)


class Giveaways(commands.Cog):
    """
    Giveaway system cog for viewer engagement.
    
    Features:
    - Start giveaways with custom keywords
    - Optional auto-end timer
    - Subscriber luck multiplier (more tickets)
    - Eligibility requirements
    - Multiple winners
    - Reroll capability
    - History tracking
    """
    
    def __init__(self, bot: TwitchBot) -> None:
        """Initialize the giveaways cog."""
        self.bot = bot
        self.db: DatabaseManager = get_database()
        
        # Track active giveaway keywords per channel for fast lookup
        self._active_keywords: dict[str, str] = {}  # {channel: keyword}
        
        # Background task for auto-ending giveaways
        self._check_task: Optional[asyncio.Task] = None
        self._running = False
        
        logger.info("Giveaways cog initialized")
    
    async def cog_load(self) -> None:
        """Called when cog is loaded."""
        self._running = True
        self._check_task = asyncio.create_task(self._check_expired_giveaways())
        
        # Load active giveaway keywords
        await self._load_active_keywords()
        
        logger.info("Giveaways cog loaded, expiration checker started")
    
    async def cog_unload(self) -> None:
        """Called when cog is unloaded."""
        self._running = False
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
        logger.info("Giveaways cog unloaded")
    
    async def _load_active_keywords(self) -> None:
        """Load active giveaway keywords from database."""
        for channel in self.bot.connected_channels:
            giveaway = self.db.get_active_giveaway(channel.name)
            if giveaway:
                self._active_keywords[channel.name.lower()] = giveaway["keyword"]
    
    async def _check_expired_giveaways(self) -> None:
        """Background task to check for and end expired giveaways."""
        await self.bot.wait_until_ready()
        
        while self._running:
            try:
                expired = self.db.check_expired_giveaways()
                
                for giveaway in expired:
                    channel_name = giveaway["channel"]
                    giveaway_id = giveaway["id"]
                    
                    # Find the channel
                    channel = None
                    for ch in self.bot.connected_channels:
                        if ch.name.lower() == channel_name.lower():
                            channel = ch
                            break
                    
                    if channel:
                        # Auto-end the giveaway
                        await self._end_giveaway_and_announce(
                            channel, 
                            giveaway_id, 
                            giveaway["winner_count"]
                        )
                        logger.info(
                            "Auto-ended expired giveaway %d in %s",
                            giveaway_id,
                            channel_name
                        )
                    else:
                        # Just mark as ended if channel not found
                        self.db.end_giveaway(giveaway_id)
                        
            except Exception as e:
                logger.error("Error checking expired giveaways: %s", e)
            
            # Check every 10 seconds
            await asyncio.sleep(10)
    
    async def _end_giveaway_and_announce(
        self,
        channel,
        giveaway_id: int,
        winner_count: int
    ) -> list[dict]:
        """End a giveaway and announce winner(s)."""
        winners = []
        exclude_ids: list[str] = []
        
        for i in range(winner_count):
            winner = self.db.pick_winner(giveaway_id, exclude_ids)
            if winner:
                self.db.add_giveaway_winner(
                    giveaway_id,
                    winner["user_id"],
                    winner["username"]
                )
                winners.append(winner)
                exclude_ids.append(winner["user_id"])
            else:
                break
        
        # Mark giveaway as ended
        self.db.end_giveaway(giveaway_id)
        
        # Remove from active keywords
        channel_name = channel.name.lower()
        if channel_name in self._active_keywords:
            del self._active_keywords[channel_name]
        
        # Announce winners
        if winners:
            if len(winners) == 1:
                await channel.send(
                    f"Giveaway ended! Winner: @{winners[0]['username']} - "
                    f"Congratulations! PogChamp"
                )
            else:
                winner_names = ", ".join(f"@{w['username']}" for w in winners)
                await channel.send(
                    f"Giveaway ended! Winners: {winner_names} - "
                    f"Congratulations! PogChamp"
                )
        else:
            await channel.send("Giveaway ended! No eligible entries. BibleThump")
        
        return winners
    
    @commands.Cog.event()
    async def event_message(self, message: Message) -> None:
        """Listen for giveaway keyword entries."""
        if message.echo or not message.author or not message.channel:
            return
        
        channel_name = message.channel.name.lower()
        content = message.content.strip().lower()
        
        # Check if there's an active giveaway with this keyword
        if channel_name not in self._active_keywords:
            return
        
        keyword = self._active_keywords[channel_name]
        
        # Check if message matches the keyword
        if content != keyword:
            return
        
        # Get the active giveaway
        giveaway = self.db.get_active_giveaway(channel_name)
        if not giveaway:
            return
        
        user_id = str(message.author.id)
        username = message.author.name
        is_sub = getattr(message.author, "is_subscriber", False)
        is_vip = getattr(message.author, "is_vip", False)
        
        # Check eligibility requirements
        if giveaway["sub_only"] and not is_sub:
            return  # Silently ignore non-subs for sub-only giveaways
        
        # Check minimum points requirement
        if giveaway["min_points"] > 0:
            loyalty = self.db.get_user_loyalty(user_id, channel_name)
            if loyalty.get("points", 0) < giveaway["min_points"]:
                return  # Silently ignore users without enough points
        
        # Calculate tickets (sub luck multiplier)
        tickets = 1
        if is_sub and giveaway["sub_luck_multiplier"] > 1.0:
            tickets = int(giveaway["sub_luck_multiplier"])
        
        # Try to add entry
        success = self.db.add_giveaway_entry(
            giveaway["id"],
            user_id,
            username,
            is_sub,
            is_vip,
            tickets
        )
        
        if success:
            entry_count = self.db.get_entry_count(giveaway["id"])
            await message.channel.send(
                f"@{username} You have entered the giveaway! ({entry_count} entries)"
            )
    
    # ==================== Giveaway Commands ====================
    # Using a single command with subcommand parsing since TwitchIO 2.x doesn't support command groups
    
    @commands.command(name="giveaway", aliases=["ga"])
    async def giveaway_command(self, ctx: Context, action: str = "", *args: str) -> None:
        """
        Giveaway management command.
        
        Usage:
        - !giveaway start <keyword> [duration] [prize] - Start a giveaway (mod)
        - !giveaway end - End and pick winner (mod)
        - !giveaway reroll - Pick new winner (mod)
        - !giveaway cancel - Cancel without winner (mod)
        - !giveaway info - Show current giveaway info
        - !giveaway entries - Show entry count
        """
        action = action.lower()
        
        if action == "start":
            await self._giveaway_start(ctx, *args)
        elif action == "end":
            await self._giveaway_end(ctx)
        elif action == "reroll":
            await self._giveaway_reroll(ctx)
        elif action == "cancel":
            await self._giveaway_cancel(ctx)
        elif action == "info":
            await self._giveaway_info(ctx)
        elif action == "entries":
            await self._giveaway_entries(ctx)
        else:
            await ctx.send(
                f"@{ctx.author.name} Giveaway commands: !giveaway start <keyword> [duration] [prize] | "
                f"!giveaway end | !giveaway reroll | !giveaway cancel | !giveaway info | !giveaway entries"
            )
    
    async def _giveaway_start(self, ctx: Context, *args: str) -> None:
        """Start a new giveaway."""
        # Check permissions
        if not (ctx.author.is_mod or ctx.author.name.lower() == ctx.channel.name.lower()):
            await ctx.send(f"@{ctx.author.name} You don't have permission to start giveaways.")
            return
        
        channel_name = ctx.channel.name
        
        if not args:
            await ctx.send(
                f"@{ctx.author.name} Usage: !giveaway start <keyword> [duration_minutes] [prize]"
            )
            return
        
        keyword = args[0]
        
        # Check for existing active giveaway
        existing = self.db.get_active_giveaway(channel_name)
        if existing:
            await ctx.send(
                f"@{ctx.author.name} There's already an active giveaway! "
                f"Use !giveaway end or !giveaway cancel first."
            )
            return
        
        # Parse duration and prize
        duration_minutes: Optional[int] = None
        prize_text: Optional[str] = None
        
        if len(args) > 1:
            try:
                duration_minutes = int(args[1])
                if len(args) > 2:
                    prize_text = " ".join(args[2:])
            except ValueError:
                # Duration is actually part of the prize
                prize_text = " ".join(args[1:])
        
        # Normalize keyword (ensure it starts with ! if it doesn't)
        if not keyword.startswith("!"):
            keyword = f"!{keyword}"
        
        # Create the giveaway
        giveaway_id = self.db.create_giveaway(
            channel=channel_name,
            keyword=keyword.lower(),
            prize=prize_text,
            started_by=ctx.author.name,
            duration_minutes=duration_minutes,
            winner_count=1,
            sub_luck=2.0,  # Default: subs get 2x tickets
            follower_only=False,
            sub_only=False,
            min_points=0
        )
        
        # Track active keyword
        self._active_keywords[channel_name.lower()] = keyword.lower()
        
        # Build announcement
        announcement = f"@{ctx.author.name} Giveaway started! Type {keyword} to enter."
        
        if duration_minutes:
            announcement += f" Ends in {duration_minutes} minute{'s' if duration_minutes != 1 else ''}."
        
        if prize_text:
            announcement += f" Prize: {prize_text}"
        
        await ctx.send(announcement)
        logger.info(
            "Giveaway %d started in %s by %s (keyword: %s)",
            giveaway_id,
            channel_name,
            ctx.author.name,
            keyword
        )
    
    async def _giveaway_end(self, ctx: Context) -> None:
        """End the current giveaway and pick winner(s)."""
        # Check permissions
        if not (ctx.author.is_mod or ctx.author.name.lower() == ctx.channel.name.lower()):
            await ctx.send(f"@{ctx.author.name} You don't have permission to end giveaways.")
            return
        
        channel_name = ctx.channel.name
        
        giveaway = self.db.get_active_giveaway(channel_name)
        if not giveaway:
            await ctx.send(f"@{ctx.author.name} No active giveaway to end.")
            return
        
        await self._end_giveaway_and_announce(
            ctx.channel,
            giveaway["id"],
            giveaway["winner_count"]
        )
        
        logger.info(
            "Giveaway %d ended in %s by %s",
            giveaway["id"],
            channel_name,
            ctx.author.name
        )
    
    async def _giveaway_reroll(self, ctx: Context) -> None:
        """Pick a new winner for the most recent giveaway."""
        # Check permissions
        if not (ctx.author.is_mod or ctx.author.name.lower() == ctx.channel.name.lower()):
            await ctx.send(f"@{ctx.author.name} You don't have permission to reroll giveaways.")
            return
        
        channel_name = ctx.channel.name
        
        # Get the most recent ended giveaway
        history = self.db.get_giveaway_history(channel_name, limit=1)
        if not history:
            await ctx.send(f"@{ctx.author.name} No giveaway history found.")
            return
        
        giveaway = history[0]
        
        if giveaway["status"] == "active":
            await ctx.send(
                f"@{ctx.author.name} The giveaway is still active! "
                f"Use !giveaway end first."
            )
            return
        
        if giveaway["status"] == "cancelled":
            await ctx.send(
                f"@{ctx.author.name} Cannot reroll a cancelled giveaway."
            )
            return
        
        # Get existing winners to exclude
        existing_winners = self.db.get_giveaway_winners(giveaway["id"])
        exclude_ids = [w["user_id"] for w in existing_winners]
        
        # Pick new winner
        winner = self.db.pick_winner(giveaway["id"], exclude_ids)
        
        if winner:
            self.db.add_giveaway_winner(
                giveaway["id"],
                winner["user_id"],
                winner["username"]
            )
            await ctx.send(
                f"@{ctx.author.name} New winner: @{winner['username']} - "
                f"Congratulations! PogChamp"
            )
            logger.info(
                "Giveaway %d rerolled in %s, new winner: %s",
                giveaway["id"],
                channel_name,
                winner["username"]
            )
        else:
            await ctx.send(
                f"@{ctx.author.name} No more eligible entries to pick from."
            )
    
    async def _giveaway_cancel(self, ctx: Context) -> None:
        """Cancel the current giveaway without picking a winner."""
        # Check permissions
        if not (ctx.author.is_mod or ctx.author.name.lower() == ctx.channel.name.lower()):
            await ctx.send(f"@{ctx.author.name} You don't have permission to cancel giveaways.")
            return
        
        channel_name = ctx.channel.name
        
        giveaway = self.db.get_active_giveaway(channel_name)
        if not giveaway:
            await ctx.send(f"@{ctx.author.name} No active giveaway to cancel.")
            return
        
        self.db.cancel_giveaway(giveaway["id"])
        
        # Remove from active keywords
        if channel_name.lower() in self._active_keywords:
            del self._active_keywords[channel_name.lower()]
        
        await ctx.send(f"@{ctx.author.name} Giveaway cancelled. No winner was picked.")
        logger.info(
            "Giveaway %d cancelled in %s by %s",
            giveaway["id"],
            channel_name,
            ctx.author.name
        )
    
    async def _giveaway_info(self, ctx: Context) -> None:
        """Show information about the current giveaway."""
        channel_name = ctx.channel.name
        
        giveaway = self.db.get_active_giveaway(channel_name)
        if not giveaway:
            await ctx.send(f"@{ctx.author.name} No active giveaway.")
            return
        
        entry_count = self.db.get_entry_count(giveaway["id"])
        keyword = giveaway["keyword"]
        prize = giveaway.get("prize", "Not specified")
        
        info = f"Active giveaway: Type {keyword} to enter | {entry_count} entries"
        
        if prize:
            info += f" | Prize: {prize}"
        
        # Check if timed
        if giveaway["ends_at"]:
            try:
                ends_at = datetime.fromisoformat(giveaway["ends_at"].replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                remaining = ends_at - now
                
                if remaining.total_seconds() > 0:
                    minutes = int(remaining.total_seconds() // 60)
                    seconds = int(remaining.total_seconds() % 60)
                    if minutes > 0:
                        info += f" | Ends in {minutes}m {seconds}s"
                    else:
                        info += f" | Ends in {seconds}s"
            except (ValueError, AttributeError):
                pass
        
        await ctx.send(info)
    
    async def _giveaway_entries(self, ctx: Context) -> None:
        """Show the number of entries in the current giveaway."""
        channel_name = ctx.channel.name
        
        giveaway = self.db.get_active_giveaway(channel_name)
        if not giveaway:
            await ctx.send(f"@{ctx.author.name} No active giveaway.")
            return
        
        entry_count = self.db.get_entry_count(giveaway["id"])
        await ctx.send(
            f"@{ctx.author.name} Current giveaway has {entry_count} "
            f"entr{'y' if entry_count == 1 else 'ies'}."
        )
    
    # ==================== Standalone Enter Command ====================
    
    @commands.command(name="enter")
    async def enter_giveaway(self, ctx: Context) -> None:
        """Enter the current giveaway. Usage: !enter"""
        channel_name = ctx.channel.name.lower()
        
        # Check if there's an active giveaway
        giveaway = self.db.get_active_giveaway(channel_name)
        if not giveaway:
            await ctx.send(f"@{ctx.author.name} No active giveaway to enter.")
            return
        
        user_id = str(ctx.author.id)
        username = ctx.author.name
        is_sub = getattr(ctx.author, "is_subscriber", False)
        is_vip = getattr(ctx.author, "is_vip", False)
        
        # Check eligibility requirements
        if giveaway["sub_only"] and not is_sub:
            await ctx.send(
                f"@{ctx.author.name} This giveaway is for subscribers only."
            )
            return
        
        # Check minimum points requirement
        if giveaway["min_points"] > 0:
            loyalty = self.db.get_user_loyalty(user_id, channel_name)
            if loyalty.get("points", 0) < giveaway["min_points"]:
                await ctx.send(
                    f"@{ctx.author.name} You need at least {giveaway['min_points']} "
                    f"points to enter this giveaway."
                )
                return
        
        # Calculate tickets (sub luck multiplier)
        tickets = 1
        if is_sub and giveaway["sub_luck_multiplier"] > 1.0:
            tickets = int(giveaway["sub_luck_multiplier"])
        
        # Try to add entry
        success = self.db.add_giveaway_entry(
            giveaway["id"],
            user_id,
            username,
            is_sub,
            is_vip,
            tickets
        )
        
        if success:
            entry_count = self.db.get_entry_count(giveaway["id"])
            await ctx.send(
                f"@{username} You have entered the giveaway! ({entry_count} entries)"
            )
        else:
            await ctx.send(
                f"@{username} You have already entered this giveaway!"
            )


def prepare(bot: TwitchBot) -> None:
    """Prepare the cog for loading."""
    bot.add_cog(Giveaways(bot))
