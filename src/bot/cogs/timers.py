"""
Timers cog for Twitch bot.

Provides scheduled message system with:
- Interval-based timers
- Chat activity requirements
- Online-only option
- Variable support
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
from bot.utils.variables import get_variable_parser, VariableParser

if TYPE_CHECKING:
    from twitchio import Message, Channel
    from bot.bot import TwitchBot

logger = get_logger(__name__)


class Timers(commands.Cog):
    """
    Timers cog for scheduled messages.
    
    Features:
    - Interval-based message posting
    - Minimum chat activity requirement
    - Online-only option
    - Variable support in messages
    """
    
    def __init__(self, bot: TwitchBot) -> None:
        """Initialize the timers cog."""
        self.bot = bot
        self.db: DatabaseManager = get_database()
        self.parser: VariableParser = get_variable_parser(bot)
        
        # Track chat activity per channel per timer
        # Structure: {channel_name: {timer_name: line_count}}
        self._chat_lines: dict[str, dict[str, int]] = {}
        self._last_timer_check: dict[str, datetime] = {}
        
        # Timer task
        self._timer_task: Optional[asyncio.Task] = None
        self._running = False
        
        logger.info("Timers cog initialized")
    
    async def cog_load(self) -> None:
        """Called when cog is loaded."""
        self._running = True
        self._timer_task = asyncio.create_task(self._timer_loop())
        logger.info("Timer loop started")
    
    async def cog_unload(self) -> None:
        """Called when cog is unloaded."""
        self._running = False
        if self._timer_task:
            self._timer_task.cancel()
            try:
                await self._timer_task
            except asyncio.CancelledError:
                pass
        logger.info("Timer loop stopped")
    
    async def _timer_loop(self) -> None:
        """Main timer loop that checks and triggers timers."""
        await self.bot.wait_until_ready()
        
        while self._running:
            try:
                await self._check_timers()
            except Exception as e:
                logger.error("Error in timer loop: %s", e)
            
            # Check every 30 seconds
            await asyncio.sleep(30)
    
    async def _check_timers(self) -> None:
        """Check all timers and trigger if ready."""
        timers = self.db.get_enabled_timers()
        now = datetime.now(timezone.utc)
        
        for timer in timers:
            name = timer["name"]
            interval = timer.get("interval_minutes", 15)
            chat_required = timer.get("chat_lines_required", 5)
            online_only = timer.get("online_only", True)
            last_triggered = timer.get("last_triggered")
            
            # Parse last triggered time
            if last_triggered:
                if isinstance(last_triggered, str):
                    try:
                        last_dt = datetime.fromisoformat(last_triggered.replace("Z", "+00:00"))
                    except ValueError:
                        last_dt = now - timedelta(hours=1)
                else:
                    last_dt = last_triggered
            else:
                last_dt = now - timedelta(hours=1)
            
            # Check if enough time has passed
            elapsed_minutes = (now - last_dt.replace(tzinfo=timezone.utc)).total_seconds() / 60
            if elapsed_minutes < interval:
                continue
            
            # Check each connected channel
            for channel in self.bot.connected_channels:
                channel_name = channel.name
                
                # Check chat activity for this specific timer
                channel_timers = self._chat_lines.get(channel_name, {})
                chat_lines = channel_timers.get(name, 0)
                if chat_lines < chat_required:
                    continue
                
                # Trigger the timer
                await self._trigger_timer(timer, channel)
                
                # Reset chat counter only for this specific timer
                if channel_name in self._chat_lines:
                    self._chat_lines[channel_name][name] = 0
                
                # Update last triggered
                self.db.update_timer_triggered(name)
                
                logger.debug("Timer %s triggered in %s", name, channel_name)
    
    async def _trigger_timer(self, timer: dict, channel: Channel) -> None:
        """Trigger a timer and send its message."""
        message_template = timer.get("message", "")
        if not message_template:
            return
        
        # Parse variables
        message = await self.parser.parse(
            template=message_template,
            channel=channel,
            user="Timer",
            user_id="0"
        )
        
        try:
            await channel.send(message)
        except Exception as e:
            logger.error("Failed to send timer message: %s", e)
    
    @commands.Cog.event()
    async def event_message(self, message: Message) -> None:
        """Track chat activity for timer requirements."""
        if message.echo or not message.channel:
            return
        
        channel_name = message.channel.name
        
        # Initialize channel dict if needed
        if channel_name not in self._chat_lines:
            self._chat_lines[channel_name] = {}
        
        # Increment counter for all enabled timers
        timers = self.db.get_enabled_timers()
        for timer in timers:
            timer_name = timer["name"]
            self._chat_lines[channel_name][timer_name] = self._chat_lines[channel_name].get(timer_name, 0) + 1
    
    @commands.command(name="addtimer")
    @is_moderator()
    async def add_timer(self, ctx: Context, name: str = "", interval: str = "15", *, message: str = "") -> None:
        """Add a new timer. Usage: !addtimer <name> <interval_minutes> <message>"""
        if not name or not message:
            await ctx.send(f"@{ctx.author.name} Usage: !addtimer <name> <interval_minutes> <message>")
            return
        
        name = name.lower()
        
        try:
            interval_int = int(interval)
            if interval_int < 5 or interval_int > 120:
                await ctx.send(f"@{ctx.author.name} Interval must be between 5 and 120 minutes")
                return
        except ValueError:
            await ctx.send(f"@{ctx.author.name} Interval must be a number (minutes)")
            return
        
        existing = self.db.get_timer(name)
        if existing:
            await ctx.send(f"@{ctx.author.name} Timer already exists. Use !edittimer to modify.")
            return
        
        try:
            self.db.create_timer(name=name, message=message, interval_minutes=interval_int, created_by=ctx.author.name)
            await ctx.send(f"@{ctx.author.name} Timer created! Interval: {interval_int} minutes")
            logger.info("Timer %s created by %s", name, ctx.author.name)
        except Exception as e:
            logger.error("Failed to create timer: %s", e)
            await ctx.send(f"@{ctx.author.name} Failed to create timer.")
    
    @commands.command(name="edittimer")
    @is_moderator()
    async def edit_timer(self, ctx: Context, name: str = "", *, message: str = "") -> None:
        """Edit a timer message. Usage: !edittimer <name> <new message>"""
        if not name or not message:
            await ctx.send(f"@{ctx.author.name} Usage: !edittimer <name> <new message>")
            return
        
        name = name.lower()
        
        if self.db.update_timer(name, message=message):
            await ctx.send(f"@{ctx.author.name} Timer updated!")
            logger.info("Timer %s edited by %s", name, ctx.author.name)
        else:
            await ctx.send(f"@{ctx.author.name} Timer not found.")
    
    @commands.command(name="deltimer")
    @is_moderator()
    async def delete_timer(self, ctx: Context, name: str = "") -> None:
        """Delete a timer. Usage: !deltimer <name>"""
        if not name:
            await ctx.send(f"@{ctx.author.name} Usage: !deltimer <name>")
            return
        
        name = name.lower()
        
        if self.db.delete_timer(name):
            await ctx.send(f"@{ctx.author.name} Timer deleted.")
            logger.info("Timer %s deleted by %s", name, ctx.author.name)
        else:
            await ctx.send(f"@{ctx.author.name} Timer not found.")
    
    @commands.command(name="timerinfo")
    @is_moderator()
    async def timer_info(self, ctx: Context, name: str = "") -> None:
        """Show information about a timer. Usage: !timerinfo <name>"""
        if not name:
            await ctx.send(f"@{ctx.author.name} Usage: !timerinfo <name>")
            return
        
        name = name.lower()
        timer = self.db.get_timer(name)
        
        if not timer:
            await ctx.send(f"@{ctx.author.name} Timer not found.")
            return
        
        interval = timer.get("interval_minutes", 15)
        chat_req = timer.get("chat_lines_required", 5)
        online_only = "Yes" if timer.get("online_only", True) else "No"
        enabled = "Yes" if timer.get("enabled", True) else "No"
        
        await ctx.send(f"@{ctx.author.name} Timer: Interval: {interval}m | Chat lines: {chat_req} | Online only: {online_only} | Enabled: {enabled}")
    
    @commands.command(name="timerinterval")
    @is_moderator()
    async def set_interval(self, ctx: Context, name: str = "", interval: str = "") -> None:
        """Set timer interval. Usage: !timerinterval <name> <minutes>"""
        if not name or not interval:
            await ctx.send(f"@{ctx.author.name} Usage: !timerinterval <name> <minutes>")
            return
        
        name = name.lower()
        
        try:
            interval_int = int(interval)
            if interval_int < 5 or interval_int > 120:
                await ctx.send(f"@{ctx.author.name} Interval must be between 5 and 120 minutes")
                return
        except ValueError:
            await ctx.send(f"@{ctx.author.name} Interval must be a number")
            return
        
        if self.db.update_timer(name, interval_minutes=interval_int):
            await ctx.send(f"@{ctx.author.name} Timer interval set to {interval_int} minutes")
        else:
            await ctx.send(f"@{ctx.author.name} Timer not found.")
    
    @commands.command(name="timerchat")
    @is_moderator()
    async def set_chat_requirement(self, ctx: Context, name: str = "", lines: str = "") -> None:
        """Set minimum chat lines required. Usage: !timerchat <name> <lines>"""
        if not name or not lines:
            await ctx.send(f"@{ctx.author.name} Usage: !timerchat <name> <lines>")
            return
        
        name = name.lower()
        
        try:
            lines_int = int(lines)
            if lines_int < 0 or lines_int > 100:
                await ctx.send(f"@{ctx.author.name} Lines must be between 0 and 100")
                return
        except ValueError:
            await ctx.send(f"@{ctx.author.name} Lines must be a number")
            return
        
        if self.db.update_timer(name, chat_lines_required=lines_int):
            await ctx.send(f"@{ctx.author.name} Timer chat requirement set to {lines_int} lines")
        else:
            await ctx.send(f"@{ctx.author.name} Timer not found.")
    
    @commands.command(name="timertoggle")
    @is_moderator()
    async def toggle_timer(self, ctx: Context, name: str = "") -> None:
        """Enable or disable a timer. Usage: !timertoggle <name>"""
        if not name:
            await ctx.send(f"@{ctx.author.name} Usage: !timertoggle <name>")
            return
        
        name = name.lower()
        timer = self.db.get_timer(name)
        
        if not timer:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM timers WHERE name = ?", (name,))
                row = cursor.fetchone()
                if row:
                    timer = dict(row)
        
        if not timer:
            await ctx.send(f"@{ctx.author.name} Timer not found.")
            return
        
        new_state = not timer.get("enabled", True)
        self.db.update_timer(name, enabled=new_state)
        
        state_str = "enabled" if new_state else "disabled"
        await ctx.send(f"@{ctx.author.name} Timer is now {state_str}")
    
    @commands.command(name="timers")
    @is_moderator()
    async def list_timers(self, ctx: Context) -> None:
        """List all timers. Usage: !timers"""
        timers = self.db.get_all_timers()
        
        if not timers:
            await ctx.send(f"@{ctx.author.name} No timers configured.")
            return
        
        timer_list = []
        for t in timers:
            status = "ON" if t.get("enabled", True) else "OFF"
            timer_list.append(f"{t['name']} ({status})")
        
        await ctx.send(f"@{ctx.author.name} Timers: " + ", ".join(timer_list))


def prepare(bot: TwitchBot) -> None:
    """Prepare the cog for loading."""
    bot.add_cog(Timers(bot))
