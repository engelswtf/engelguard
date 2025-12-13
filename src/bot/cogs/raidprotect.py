"""
Raid protection cog for Twitch bot.

Provides automatic raid protection:
- Detects incoming raids
- Enables follower-only mode
- Enables slow mode
- Auto-disables after duration
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Optional

from twitchio.ext import commands

from bot.utils.logging import get_logger

if TYPE_CHECKING:
    from bot.bot import TwitchBot

logger = get_logger(__name__)


class RaidProtect(commands.Cog):
    """Raid protection cog."""
    
    def __init__(self, bot: TwitchBot) -> None:
        self.bot = bot
        self._active_raids: dict[str, datetime] = {}
        self._protection_tasks: dict[str, asyncio.Task] = {}
        
        # Default settings (can be overridden per channel)
        self.settings = {
            "enabled": True,
            "follower_only": True,
            "follower_age_minutes": 10,
            "slow_mode": True,
            "slow_mode_seconds": 30,
            "duration_minutes": 5,
            "welcome_message": "Welcome raiders! Chat is in protected mode for a few minutes. 🛡️"
        }
        
        logger.info("RaidProtect cog initialized")
    
    def _is_protected(self, channel: str) -> bool:
        """Check if channel is currently in raid protection mode."""
        return channel.lower() in self._active_raids
    
    async def _enable_protection(self, channel_name: str, raider: str = None, raider_count: int = 0) -> None:
        """Enable raid protection for a channel."""
        channel = self.bot.get_channel(channel_name)
        if not channel:
            return
        
        self._active_raids[channel_name.lower()] = datetime.now(timezone.utc)
        
        try:
            # Enable follower-only mode
            if self.settings["follower_only"]:
                age = self.settings["follower_age_minutes"]
                await channel.send(f"/followers {age}m")
                logger.info("Enabled follower-only mode (%dm) for %s", age, channel_name)
            
            # Enable slow mode
            if self.settings["slow_mode"]:
                seconds = self.settings["slow_mode_seconds"]
                await channel.send(f"/slow {seconds}")
                logger.info("Enabled slow mode (%ds) for %s", seconds, channel_name)
            
            # Send welcome message
            if self.settings["welcome_message"]:
                msg = self.settings["welcome_message"]
                if raider:
                    msg = f"Incoming raid from {raider}! " + msg
                await channel.send(msg)
            
            logger.info("Raid protection enabled for %s (raider: %s, count: %d)", 
                       channel_name, raider, raider_count)
            
        except Exception as e:
            logger.error("Error enabling raid protection: %s", e)
    
    async def _disable_protection(self, channel_name: str) -> None:
        """Disable raid protection for a channel."""
        channel = self.bot.get_channel(channel_name)
        if not channel:
            return
        
        try:
            # Disable follower-only mode
            if self.settings["follower_only"]:
                await channel.send("/followersoff")
            
            # Disable slow mode
            if self.settings["slow_mode"]:
                await channel.send("/slowoff")
            
            await channel.send("Raid protection disabled. Welcome everyone! 👋")
            
            logger.info("Raid protection disabled for %s", channel_name)
            
        except Exception as e:
            logger.error("Error disabling raid protection: %s", e)
        finally:
            self._active_raids.pop(channel_name.lower(), None)
    
    async def _protection_timer(self, channel_name: str) -> None:
        """Timer to auto-disable protection."""
        duration = self.settings["duration_minutes"] * 60
        await asyncio.sleep(duration)
        
        if channel_name.lower() in self._active_raids:
            await self._disable_protection(channel_name)
    
    @commands.Cog.event()
    async def event_raw_data(self, data: str) -> None:
        """Handle raw IRC data to detect raids."""
        # TwitchIO raid detection via USERNOTICE
        if "USERNOTICE" in data and "msg-id=raid" in data:
            try:
                # Parse raid info from tags
                parts = data.split(" ")
                tags_str = parts[0] if parts[0].startswith("@") else ""
                
                tags = {}
                for tag in tags_str.lstrip("@").split(";"):
                    if "=" in tag:
                        k, v = tag.split("=", 1)
                        tags[k] = v
                
                raider = tags.get("msg-param-displayName", tags.get("display-name", "Unknown"))
                raider_count = int(tags.get("msg-param-viewerCount", 0))
                
                # Find channel from data
                channel = None
                for part in parts:
                    if part.startswith("#"):
                        channel = part.lstrip("#")
                        break
                
                if channel and self.settings["enabled"]:
                    logger.info("Raid detected: %s raiding %s with %d viewers", 
                               raider, channel, raider_count)
                    
                    # Cancel existing timer if any
                    if channel.lower() in self._protection_tasks:
                        self._protection_tasks[channel.lower()].cancel()
                    
                    # Enable protection
                    await self._enable_protection(channel, raider, raider_count)
                    
                    # Start auto-disable timer
                    task = asyncio.create_task(self._protection_timer(channel))
                    self._protection_tasks[channel.lower()] = task
                    
            except Exception as e:
                logger.error("Error processing raid event: %s", e)
    
    @commands.command(name="raidmode")
    async def raidmode_cmd(self, ctx, action: str = "status", value: str = "") -> None:
        """Control raid protection. Usage: !raidmode <on/off/status>"""
        # Check if user is mod or broadcaster
        if not (ctx.author.is_mod or ctx.author.name.lower() == ctx.channel.name.lower()):
            return
        
        channel = ctx.channel.name.lower()
        action = action.lower()
        
        if action == "on":
            if self._is_protected(channel):
                await ctx.send(f"@{ctx.author.name} Raid protection is already active!")
            else:
                await self._enable_protection(ctx.channel.name)
                task = asyncio.create_task(self._protection_timer(ctx.channel.name))
                self._protection_tasks[channel] = task
                await ctx.send(f"@{ctx.author.name} Raid protection enabled for {self.settings['duration_minutes']} minutes.")
        
        elif action == "off":
            if self._is_protected(channel):
                if channel in self._protection_tasks:
                    self._protection_tasks[channel].cancel()
                await self._disable_protection(ctx.channel.name)
                await ctx.send(f"@{ctx.author.name} Raid protection disabled.")
            else:
                await ctx.send(f"@{ctx.author.name} Raid protection is not active.")
        
        elif action == "status":
            if self._is_protected(channel):
                started = self._active_raids[channel]
                elapsed = (datetime.now(timezone.utc) - started).seconds // 60
                remaining = self.settings["duration_minutes"] - elapsed
                await ctx.send(f"@{ctx.author.name} Raid protection: ACTIVE ({remaining} min remaining)")
            else:
                status = "ENABLED" if self.settings["enabled"] else "DISABLED"
                await ctx.send(f"@{ctx.author.name} Raid protection: {status} (not currently active)")
        
        elif action == "duration":
            if value.isdigit():
                self.settings["duration_minutes"] = int(value)
                await ctx.send(f"@{ctx.author.name} Raid protection duration set to {value} minutes.")
            else:
                await ctx.send(f"@{ctx.author.name} Current duration: {self.settings['duration_minutes']} minutes. Use !raidmode duration <minutes>")
        
        elif action == "toggle":
            self.settings["enabled"] = not self.settings["enabled"]
            status = "ENABLED" if self.settings["enabled"] else "DISABLED"
            await ctx.send(f"@{ctx.author.name} Auto raid protection: {status}")
        
        else:
            await ctx.send(f"@{ctx.author.name} Usage: !raidmode <on/off/status/duration/toggle>")


def prepare(bot) -> None:
    """Prepare the cog for loading."""
    bot.add_cog(RaidProtect(bot))
