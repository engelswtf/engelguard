"""
Chat alerts cog for Twitch bot.

Announces events in chat:
- Follow alerts
- Sub alerts (new, resub, gift)
- Raid alerts
- Bits/Cheer alerts

Features:
- Configurable messages with variables
- Enable/disable per event type
- Cooldown to prevent spam
- Per-channel settings stored in database
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from twitchio.ext import commands

from bot.utils.database import get_database, DatabaseManager
from bot.utils.logging import get_logger
from bot.utils.permissions import is_moderator

if TYPE_CHECKING:
    from bot.bot import TwitchBot

logger = get_logger(__name__)


# Default alert messages
DEFAULT_FOLLOW_MESSAGE = "Welcome @$(user) to the community! 🎉"
DEFAULT_SUB_MESSAGE = "Thanks @$(user) for subscribing! 💜"
DEFAULT_RESUB_MESSAGE = "Thanks @$(user) for $(months) months! 💜"
DEFAULT_GIFTSUB_MESSAGE = "@$(user) gifted a sub to @$(recipient)! 🎁"
DEFAULT_RAID_MESSAGE = "Welcome $(count) raiders from @$(user)! 🎊"
DEFAULT_BITS_MESSAGE = "Thanks @$(user) for $(bits) bits! 💎"


class AlertSettings:
    """Container for channel alert settings."""
    
    def __init__(
        self,
        channel: str,
        follow_enabled: bool = True,
        follow_message: str = DEFAULT_FOLLOW_MESSAGE,
        sub_enabled: bool = True,
        sub_message: str = DEFAULT_SUB_MESSAGE,
        resub_message: str = DEFAULT_RESUB_MESSAGE,
        giftsub_message: str = DEFAULT_GIFTSUB_MESSAGE,
        raid_enabled: bool = True,
        raid_message: str = DEFAULT_RAID_MESSAGE,
        bits_enabled: bool = True,
        bits_message: str = DEFAULT_BITS_MESSAGE,
        bits_minimum: int = 1,
    ) -> None:
        self.channel = channel
        self.follow_enabled = follow_enabled
        self.follow_message = follow_message
        self.sub_enabled = sub_enabled
        self.sub_message = sub_message
        self.resub_message = resub_message
        self.giftsub_message = giftsub_message
        self.raid_enabled = raid_enabled
        self.raid_message = raid_message
        self.bits_enabled = bits_enabled
        self.bits_message = bits_message
        self.bits_minimum = bits_minimum


class ChatAlerts(commands.Cog):
    """
    Chat alerts cog for event announcements.
    
    Listens for Twitch events and sends configurable
    alert messages to chat.
    """
    
    def __init__(self, bot: TwitchBot) -> None:
        """Initialize the chat alerts cog."""
        self.bot = bot
        self.db: DatabaseManager = get_database()
        
        # Cache for settings: {channel: AlertSettings}
        self._settings_cache: dict[str, AlertSettings] = {}
        
        # Cooldown tracking: {channel: {event_type: last_trigger_time}}
        self._cooldowns: dict[str, dict[str, float]] = {}
        
        # Cooldown duration in seconds per event type
        self._cooldown_durations = {
            "follow": 5.0,    # 5 seconds between follow alerts
            "sub": 3.0,       # 3 seconds between sub alerts
            "raid": 30.0,     # 30 seconds between raid alerts
            "bits": 3.0,      # 3 seconds between bits alerts
        }
        
        # Initialize database table
        self._init_database()
        
        logger.info("ChatAlerts cog initialized")
    
    def _init_database(self) -> None:
        """Initialize the alert_settings database table."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alert_settings (
                    channel TEXT PRIMARY KEY,
                    follow_enabled BOOLEAN DEFAULT TRUE,
                    follow_message TEXT DEFAULT 'Welcome @$(user) to the community! 🎉',
                    sub_enabled BOOLEAN DEFAULT TRUE,
                    sub_message TEXT DEFAULT 'Thanks @$(user) for subscribing! 💜',
                    resub_message TEXT DEFAULT 'Thanks @$(user) for $(months) months! 💜',
                    giftsub_message TEXT DEFAULT '@$(user) gifted a sub to @$(recipient)! 🎁',
                    raid_enabled BOOLEAN DEFAULT TRUE,
                    raid_message TEXT DEFAULT 'Welcome $(count) raiders from @$(user)! 🎊',
                    bits_enabled BOOLEAN DEFAULT TRUE,
                    bits_message TEXT DEFAULT 'Thanks @$(user) for $(bits) bits! 💎',
                    bits_minimum INTEGER DEFAULT 1
                )
            """)
            logger.debug("Alert settings table initialized")
    
    def _get_settings(self, channel: str) -> AlertSettings:
        """
        Get alert settings for a channel.
        
        Args:
            channel: Channel name
            
        Returns:
            AlertSettings for the channel
        """
        channel = channel.lower()
        
        # Check cache first
        if channel in self._settings_cache:
            return self._settings_cache[channel]
        
        # Load from database
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM alert_settings WHERE channel = ?",
                (channel,)
            )
            row = cursor.fetchone()
            
            if row:
                settings = AlertSettings(
                    channel=row["channel"],
                    follow_enabled=bool(row["follow_enabled"]),
                    follow_message=row["follow_message"],
                    sub_enabled=bool(row["sub_enabled"]),
                    sub_message=row["sub_message"],
                    resub_message=row["resub_message"],
                    giftsub_message=row["giftsub_message"],
                    raid_enabled=bool(row["raid_enabled"]),
                    raid_message=row["raid_message"],
                    bits_enabled=bool(row["bits_enabled"]),
                    bits_message=row["bits_message"],
                    bits_minimum=row["bits_minimum"],
                )
            else:
                # Create default settings
                settings = AlertSettings(channel=channel)
                self._save_settings(settings)
        
        self._settings_cache[channel] = settings
        return settings
    
    def _save_settings(self, settings: AlertSettings) -> None:
        """
        Save alert settings to database.
        
        Args:
            settings: AlertSettings to save
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO alert_settings (
                    channel, follow_enabled, follow_message,
                    sub_enabled, sub_message, resub_message, giftsub_message,
                    raid_enabled, raid_message,
                    bits_enabled, bits_message, bits_minimum
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                settings.channel,
                settings.follow_enabled,
                settings.follow_message,
                settings.sub_enabled,
                settings.sub_message,
                settings.resub_message,
                settings.giftsub_message,
                settings.raid_enabled,
                settings.raid_message,
                settings.bits_enabled,
                settings.bits_message,
                settings.bits_minimum,
            ))
        
        # Update cache
        self._settings_cache[settings.channel] = settings
        logger.debug("Saved alert settings for %s", settings.channel)
    
    def _check_cooldown(self, channel: str, event_type: str) -> bool:
        """
        Check if an event is on cooldown.
        
        Args:
            channel: Channel name
            event_type: Type of event (follow, sub, raid, bits)
            
        Returns:
            True if NOT on cooldown (can send), False if on cooldown
        """
        channel = channel.lower()
        now = time.time()
        
        if channel not in self._cooldowns:
            self._cooldowns[channel] = {}
        
        last_trigger = self._cooldowns[channel].get(event_type, 0)
        cooldown_duration = self._cooldown_durations.get(event_type, 5.0)
        
        if now - last_trigger < cooldown_duration:
            return False
        
        self._cooldowns[channel][event_type] = now
        return True
    
    def _parse_variables(
        self,
        template: str,
        user: str = "",
        months: int = 0,
        bits: int = 0,
        count: int = 0,
        recipient: str = "",
    ) -> str:
        """
        Parse variables in alert message template.
        
        Supported variables:
        - $(user) - Username
        - $(months) - Sub months
        - $(bits) - Bits amount
        - $(count) / $(raiders) - Raid viewer count
        - $(recipient) - Gift sub recipient
        
        Args:
            template: Message template
            user: Username
            months: Subscription months
            bits: Bits amount
            count: Raider count
            recipient: Gift sub recipient
            
        Returns:
            Parsed message string
        """
        result = template
        
        # Replace variables (case-insensitive)
        replacements = {
            r"\$\(user\)": user,
            r"\$\(months\)": str(months),
            r"\$\(bits\)": str(bits),
            r"\$\(count\)": str(count),
            r"\$\(raiders\)": str(count),  # Alias for count
            r"\$\(recipient\)": recipient,
        }
        
        for pattern, value in replacements.items():
            result = re.sub(pattern, value, result, flags=re.IGNORECASE)
        
        return result
    
    async def _send_alert(
        self,
        channel_name: str,
        message: str,
        event_type: str,
    ) -> None:
        """
        Send an alert message to a channel.
        
        Args:
            channel_name: Channel to send to
            message: Alert message
            event_type: Type of event for logging
        """
        channel = self.bot.get_channel(channel_name)
        if not channel:
            logger.warning("Could not find channel %s for %s alert", channel_name, event_type)
            return
        
        try:
            await channel.send(message)
            logger.info("Sent %s alert to %s: %s", event_type, channel_name, message[:50])
        except Exception as e:
            logger.error("Failed to send %s alert to %s: %s", event_type, channel_name, e)
    
    # ==================== Event Handlers ====================
    
    @commands.Cog.event()
    async def event_raw_data(self, data: str) -> None:
        """
        Handle raw IRC data to detect events.
        
        TwitchIO may not have direct events for all notification types,
        so we parse USERNOTICE messages directly.
        """
        if "USERNOTICE" not in data:
            return
        
        try:
            # Parse tags from raw data
            parts = data.split(" ")
            tags_str = parts[0] if parts[0].startswith("@") else ""
            
            tags = {}
            for tag in tags_str.lstrip("@").split(";"):
                if "=" in tag:
                    k, v = tag.split("=", 1)
                    tags[k] = v
            
            # Find channel from data
            channel = None
            for part in parts:
                if part.startswith("#"):
                    channel = part.lstrip("#").lower()
                    break
            
            if not channel:
                return
            
            msg_id = tags.get("msg-id", "")
            
            # Handle different event types
            if msg_id == "sub":
                await self._handle_subscription(channel, tags, is_resub=False)
            elif msg_id == "resub":
                await self._handle_subscription(channel, tags, is_resub=True)
            elif msg_id == "subgift":
                await self._handle_gift_sub(channel, tags)
            elif msg_id == "raid":
                await self._handle_raid(channel, tags)
            elif msg_id == "bitsbadgetier":
                # Bits badge tier upgrade - not the same as cheer
                pass
                
        except Exception as e:
            logger.error("Error processing raw event data: %s", e)
    
    async def _handle_subscription(
        self,
        channel: str,
        tags: dict[str, str],
        is_resub: bool,
    ) -> None:
        """Handle subscription events."""
        settings = self._get_settings(channel)
        
        if not settings.sub_enabled:
            return
        
        if not self._check_cooldown(channel, "sub"):
            logger.debug("Sub alert on cooldown for %s", channel)
            return
        
        user = tags.get("display-name", tags.get("login", "Someone"))
        months = int(tags.get("msg-param-cumulative-months", "1"))
        
        if is_resub:
            message = self._parse_variables(
                settings.resub_message,
                user=user,
                months=months,
            )
        else:
            message = self._parse_variables(
                settings.sub_message,
                user=user,
            )
        
        await self._send_alert(channel, message, "subscription")
    
    async def _handle_gift_sub(self, channel: str, tags: dict[str, str]) -> None:
        """Handle gift subscription events."""
        settings = self._get_settings(channel)
        
        if not settings.sub_enabled:
            return
        
        if not self._check_cooldown(channel, "sub"):
            logger.debug("Gift sub alert on cooldown for %s", channel)
            return
        
        gifter = tags.get("display-name", tags.get("login", "Someone"))
        recipient = tags.get("msg-param-recipient-display-name", 
                            tags.get("msg-param-recipient-user-name", "someone"))
        
        message = self._parse_variables(
            settings.giftsub_message,
            user=gifter,
            recipient=recipient,
        )
        
        await self._send_alert(channel, message, "gift_sub")
    
    async def _handle_raid(self, channel: str, tags: dict[str, str]) -> None:
        """Handle raid events."""
        settings = self._get_settings(channel)
        
        if not settings.raid_enabled:
            return
        
        if not self._check_cooldown(channel, "raid"):
            logger.debug("Raid alert on cooldown for %s", channel)
            return
        
        raider = tags.get("msg-param-displayName", 
                         tags.get("display-name", 
                         tags.get("login", "Someone")))
        viewer_count = int(tags.get("msg-param-viewerCount", "0"))
        
        message = self._parse_variables(
            settings.raid_message,
            user=raider,
            count=viewer_count,
        )
        
        await self._send_alert(channel, message, "raid")
    
    @commands.Cog.event()
    async def event_raw_usernotice(self, channel, tags: dict) -> None:
        """
        Alternative event handler for user notices.
        
        This may be called by TwitchIO for some events.
        """
        # This is a backup handler - main logic is in event_raw_data
        pass
    
    # Cheer/bits events come through regular messages with bits tag
    @commands.Cog.event()
    async def event_message(self, message) -> None:
        """Handle messages to detect cheer/bits events."""
        if message.echo:
            return
        
        # Check if message has bits
        bits = 0
        if hasattr(message, "tags") and message.tags:
            bits_str = message.tags.get("bits", "0")
            try:
                bits = int(bits_str)
            except (ValueError, TypeError):
                bits = 0
        
        if bits <= 0:
            return
        
        channel = message.channel.name.lower() if message.channel else None
        if not channel:
            return
        
        settings = self._get_settings(channel)
        
        if not settings.bits_enabled:
            return
        
        if bits < settings.bits_minimum:
            logger.debug("Bits %d below minimum %d for %s", bits, settings.bits_minimum, channel)
            return
        
        if not self._check_cooldown(channel, "bits"):
            logger.debug("Bits alert on cooldown for %s", channel)
            return
        
        user = message.author.display_name if message.author else "Someone"
        
        alert_message = self._parse_variables(
            settings.bits_message,
            user=user,
            bits=bits,
        )
        
        await self._send_alert(channel, alert_message, "bits")
    
    # ==================== Commands ====================
    
    @commands.command(name="alerts")
    @is_moderator()
    async def alerts_cmd(self, ctx, action: str = "status", *args) -> None:
        """
        Manage chat alerts.
        
        Usage:
            !alerts status - Show current settings
            !alerts <type> on/off - Toggle alert type
            !alerts <type> message <text> - Set custom message
            !alerts bits minimum <amount> - Set minimum bits for alert
        
        Types: follow, sub, resub, giftsub, raid, bits
        """
        channel = ctx.channel.name.lower()
        settings = self._get_settings(channel)
        action = action.lower()
        
        # Handle status command
        if action == "status":
            await self._show_status(ctx, settings)
            return
        
        # Handle type-specific commands
        alert_types = ["follow", "sub", "resub", "giftsub", "raid", "bits"]
        
        if action in alert_types:
            if not args:
                await ctx.send(f"@{ctx.author.name} Usage: !alerts {action} <on/off/message>")
                return
            
            sub_action = args[0].lower()
            
            if sub_action in ("on", "off"):
                await self._toggle_alert(ctx, settings, action, sub_action == "on")
            elif sub_action == "message":
                if len(args) < 2:
                    await ctx.send(f"@{ctx.author.name} Usage: !alerts {action} message <text>")
                    return
                message_text = " ".join(args[1:])
                await self._set_message(ctx, settings, action, message_text)
            elif sub_action == "minimum" and action == "bits":
                if len(args) < 2 or not args[1].isdigit():
                    await ctx.send(f"@{ctx.author.name} Usage: !alerts bits minimum <amount>")
                    return
                await self._set_bits_minimum(ctx, settings, int(args[1]))
            else:
                await ctx.send(f"@{ctx.author.name} Unknown action. Use: on, off, or message")
        else:
            await ctx.send(
                f"@{ctx.author.name} Usage: !alerts <status|follow|sub|resub|giftsub|raid|bits> "
                "[on/off/message]"
            )
    
    async def _show_status(self, ctx, settings: AlertSettings) -> None:
        """Show current alert settings."""
        status_parts = []
        
        if settings.follow_enabled:
            status_parts.append("Follow: ✅")
        else:
            status_parts.append("Follow: ❌")
        
        if settings.sub_enabled:
            status_parts.append("Sub: ✅")
        else:
            status_parts.append("Sub: ❌")
        
        if settings.raid_enabled:
            status_parts.append("Raid: ✅")
        else:
            status_parts.append("Raid: ❌")
        
        if settings.bits_enabled:
            status_parts.append(f"Bits: ✅ (min: {settings.bits_minimum})")
        else:
            status_parts.append("Bits: ❌")
        
        await ctx.send(f"@{ctx.author.name} Alert Status: {' | '.join(status_parts)}")
    
    async def _toggle_alert(
        self,
        ctx,
        settings: AlertSettings,
        alert_type: str,
        enabled: bool,
    ) -> None:
        """Toggle an alert type on or off."""
        # Map alert types to settings attributes
        type_map = {
            "follow": "follow_enabled",
            "sub": "sub_enabled",
            "resub": "sub_enabled",  # Resub uses same toggle as sub
            "giftsub": "sub_enabled",  # Gift sub uses same toggle as sub
            "raid": "raid_enabled",
            "bits": "bits_enabled",
        }
        
        attr = type_map.get(alert_type)
        if not attr:
            await ctx.send(f"@{ctx.author.name} Unknown alert type: {alert_type}")
            return
        
        setattr(settings, attr, enabled)
        self._save_settings(settings)
        
        status = "enabled" if enabled else "disabled"
        await ctx.send(f"@{ctx.author.name} {alert_type.capitalize()} alerts {status}! ✅")
        logger.info("Alert %s %s for channel %s by %s", 
                   alert_type, status, settings.channel, ctx.author.name)
    
    async def _set_message(
        self,
        ctx,
        settings: AlertSettings,
        alert_type: str,
        message: str,
    ) -> None:
        """Set a custom alert message."""
        # Map alert types to message attributes
        type_map = {
            "follow": "follow_message",
            "sub": "sub_message",
            "resub": "resub_message",
            "giftsub": "giftsub_message",
            "raid": "raid_message",
            "bits": "bits_message",
        }
        
        attr = type_map.get(alert_type)
        if not attr:
            await ctx.send(f"@{ctx.author.name} Unknown alert type: {alert_type}")
            return
        
        # Validate message length
        if len(message) > 400:
            await ctx.send(f"@{ctx.author.name} Message too long! Max 400 characters.")
            return
        
        if len(message) < 1:
            await ctx.send(f"@{ctx.author.name} Message cannot be empty!")
            return
        
        setattr(settings, attr, message)
        self._save_settings(settings)
        
        # Show available variables for this type
        variables = {
            "follow": "$(user)",
            "sub": "$(user)",
            "resub": "$(user), $(months)",
            "giftsub": "$(user), $(recipient)",
            "raid": "$(user), $(count), $(raiders)",
            "bits": "$(user), $(bits)",
        }
        
        await ctx.send(
            f"@{ctx.author.name} {alert_type.capitalize()} message updated! "
            f"Variables: {variables.get(alert_type, '')}"
        )
        logger.info("Alert message for %s updated in %s by %s", 
                   alert_type, settings.channel, ctx.author.name)
    
    async def _set_bits_minimum(
        self,
        ctx,
        settings: AlertSettings,
        minimum: int,
    ) -> None:
        """Set minimum bits for alert."""
        if minimum < 0:
            await ctx.send(f"@{ctx.author.name} Minimum must be 0 or greater!")
            return
        
        if minimum > 1000000:
            await ctx.send(f"@{ctx.author.name} Minimum too high! Max 1,000,000.")
            return
        
        settings.bits_minimum = minimum
        self._save_settings(settings)
        
        await ctx.send(f"@{ctx.author.name} Bits minimum set to {minimum}! ✅")
        logger.info("Bits minimum set to %d in %s by %s", 
                   minimum, settings.channel, ctx.author.name)
    
    @commands.command(name="testalert")
    @is_moderator()
    async def test_alert_cmd(self, ctx, alert_type: str = "sub") -> None:
        """
        Test an alert message.
        
        Usage: !testalert <follow|sub|resub|giftsub|raid|bits>
        """
        channel = ctx.channel.name.lower()
        settings = self._get_settings(channel)
        alert_type = alert_type.lower()
        
        test_user = ctx.author.display_name
        
        if alert_type == "follow":
            message = self._parse_variables(settings.follow_message, user=test_user)
        elif alert_type == "sub":
            message = self._parse_variables(settings.sub_message, user=test_user)
        elif alert_type == "resub":
            message = self._parse_variables(settings.resub_message, user=test_user, months=12)
        elif alert_type == "giftsub":
            message = self._parse_variables(
                settings.giftsub_message, user=test_user, recipient="TestRecipient"
            )
        elif alert_type == "raid":
            message = self._parse_variables(settings.raid_message, user=test_user, count=42)
        elif alert_type == "bits":
            message = self._parse_variables(settings.bits_message, user=test_user, bits=100)
        else:
            await ctx.send(
                f"@{ctx.author.name} Unknown type. Use: follow, sub, resub, giftsub, raid, bits"
            )
            return
        
        await ctx.send(f"[TEST] {message}")


def prepare(bot: TwitchBot) -> None:
    """Prepare the cog for loading."""
    bot.add_cog(ChatAlerts(bot))
