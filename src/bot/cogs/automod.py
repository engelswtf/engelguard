"""
Auto-moderation cog for Twitch bot.

Provides comprehensive spam detection and automatic moderation:
- URL filtering (whitelist/blacklist)
- Spam pattern detection
- Subscriber protection
- Strike system integration
- Moderation logging
- Permit system
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Optional

from twitchio.ext import commands
from twitchio.ext.commands import Context

from bot.utils.database import get_database, DatabaseManager
from bot.utils.logging import get_logger
from bot.utils.permissions import is_owner, is_moderator, cooldown, CooldownBucket
from bot.utils.spam_detector import get_spam_detector, SpamDetector, ModAction
from bot.utils.strikes import get_strike_manager, StrikeManager, StrikeAction

if TYPE_CHECKING:
    from twitchio import Message, User
    from bot.bot import TwitchBot

logger = get_logger(__name__)


class AutoMod(commands.Cog):
    """
    Auto-moderation cog for spam detection and prevention.
    
    Features:
    - Automatic spam detection
    - URL filtering
    - Subscriber protection
    - Strike system for escalating punishments
    - Moderation logging
    - Permit system for temporary link allowance
    """
    
    def __init__(self, bot: TwitchBot) -> None:
        """Initialize the automod cog."""
        self.bot = bot
        self.db: DatabaseManager = get_database()
        self.detector: SpamDetector = get_spam_detector("medium")
        self.strikes: StrikeManager = get_strike_manager()
        self.enabled: bool = True
        self.use_strikes: bool = True  # Use strike system for escalation
        
        # Cooldown tracking to prevent spam timeouts on same user
        self._action_cooldowns: dict[str, datetime] = {}
        self._action_cooldown_seconds = 30
        
        logger.info("AutoMod cog initialized with strike system")
    
    def _is_on_action_cooldown(self, user_id: str) -> bool:
        """Check if we recently took action on this user."""
        if user_id not in self._action_cooldowns:
            return False
        
        last_action = self._action_cooldowns[user_id]
        elapsed = (datetime.now(timezone.utc) - last_action).total_seconds()
        return elapsed < self._action_cooldown_seconds
    
    def _update_action_cooldown(self, user_id: str) -> None:
        """Update the action cooldown for a user."""
        self._action_cooldowns[user_id] = datetime.now(timezone.utc)
        
        # Cleanup old entries
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        self._action_cooldowns = {
            uid: ts for uid, ts in self._action_cooldowns.items()
            if ts > cutoff
        }
    
    async def _get_user_context(
        self,
        author: User,
        user_id: str,
        username: str,
        channel_name: str
    ) -> dict:
        """Get user context for spam detection."""
        # Get or create user in database
        user_data = self.db.get_or_create_user(user_id, username)
        
        # Check for permit
        has_permit = self.db.has_valid_permit(user_id)
        
        # Get follow age (estimate based on first_seen)
        first_seen = user_data.get("first_seen")
        if first_seen:
            try:
                if isinstance(first_seen, str):
                    first_seen_dt = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
                else:
                    first_seen_dt = first_seen
                follow_age_days = (datetime.now(timezone.utc) - first_seen_dt.replace(tzinfo=timezone.utc)).days
            except (ValueError, AttributeError):
                follow_age_days = 0
        else:
            follow_age_days = 0
        
        # Get filter settings for channel
        filter_settings = self.db.get_filter_settings(channel_name)
        
        return {
            "is_subscriber": getattr(author, "is_subscriber", False),
            "is_vip": getattr(author, "is_vip", False),
            "is_mod": getattr(author, "is_mod", False),
            "is_broadcaster": getattr(author, "is_broadcaster", False),
            "follow_age_days": follow_age_days,
            "message_count": user_data.get("message_count", 0),
            "is_whitelisted": user_data.get("is_whitelisted", False),
            "has_permit": has_permit,
            "filter_settings": filter_settings,
        }
    
    async def _take_action(
        self,
        message: Message,
        action: ModAction,
        reason: str,
        score: int,
        is_subscriber_protected: bool,
    ) -> None:
        """Take moderation action on a message."""
        if not message.author or not message.channel:
            return
        
        user_id = str(message.author.id)
        username = message.author.name
        channel = message.channel
        is_subscriber = getattr(message.author, "is_subscriber", False)
        
        # Check action cooldown
        if self._is_on_action_cooldown(user_id):
            logger.debug("Skipping action on %s - on cooldown", username)
            return
        
        try:
            if action == ModAction.FLAG:
                # Just log, no action
                self.db.log_action(
                    user_id=user_id,
                    username=username,
                    action="flag",
                    reason=reason,
                    spam_score=score,
                    message_content=message.content[:500],
                    channel=channel.name,
                )
                logger.info("[FLAG] %s (score: %d): %s", username, score, reason)
            
            elif action == ModAction.DELETE:
                # Delete message and add strike
                try:
                    await channel.send(f"/delete {message.id}")
                except Exception as e:
                    logger.warning("Failed to delete message: %s", e)
                
                if self.use_strikes:
                    strike_result = self.strikes.add_strike(
                        user_id=user_id,
                        username=username,
                        reason=reason[:100],
                        moderator="AutoMod",
                        channel=channel.name,
                        is_subscriber=is_subscriber
                    )
                    await channel.send(strike_result.message)
                else:
                    await channel.send(f"@{username} Your message was removed. Please follow chat rules.")
                
                self.db.log_action(
                    user_id=user_id,
                    username=username,
                    action="delete",
                    reason=reason,
                    spam_score=score,
                    message_content=message.content[:500],
                    channel=channel.name,
                )
                self.db.update_trust_score(user_id, -5)
                logger.info("[DELETE] %s (score: %d): %s", username, score, reason)
            
            elif action == ModAction.TIMEOUT:
                if self.use_strikes:
                    # Use strike system for escalation
                    strike_result = self.strikes.add_strike(
                        user_id=user_id,
                        username=username,
                        reason=reason[:100],
                        moderator="AutoMod",
                        channel=channel.name,
                        is_subscriber=is_subscriber
                    )
                    
                    # Execute the strike action
                    if strike_result.action == StrikeAction.TIMEOUT:
                        try:
                            await channel.send(f"/timeout {username} {strike_result.duration} {strike_result.message[:100]}")
                        except Exception as e:
                            logger.warning("Failed to timeout user: %s", e)
                    elif strike_result.action == StrikeAction.BAN and strike_result.should_ban:
                        try:
                            await channel.send(f"/ban {username} {strike_result.message[:100]}")
                        except Exception as e:
                            logger.warning("Failed to ban user: %s", e)
                    else:
                        await channel.send(strike_result.message)
                else:
                    # Standard 10 minute timeout
                    duration = 600
                    try:
                        await channel.send(f"/timeout {username} {duration} AutoMod: {reason[:100]}")
                    except Exception as e:
                        logger.warning("Failed to timeout user: %s", e)
                    
                    if is_subscriber_protected:
                        await channel.send(f"@{username} Timed out for 10 minutes. As a subscriber, you won't be banned.")
                
                self.db.log_action(
                    user_id=user_id,
                    username=username,
                    action="timeout",
                    reason=reason,
                    spam_score=score,
                    message_content=message.content[:500],
                    channel=channel.name,
                )
                self.db.update_trust_score(user_id, -15)
                logger.info("[TIMEOUT] %s (score: %d): %s", username, score, reason)
            
            elif action == ModAction.BAN:
                if self.use_strikes:
                    # Use strike system - may not result in immediate ban
                    strike_result = self.strikes.add_strike(
                        user_id=user_id,
                        username=username,
                        reason=reason[:100],
                        moderator="AutoMod",
                        channel=channel.name,
                        is_subscriber=is_subscriber
                    )
                    
                    if strike_result.should_ban:
                        try:
                            await channel.send(f"/ban {username} {strike_result.message[:100]}")
                        except Exception as e:
                            logger.warning("Failed to ban user: %s", e)
                    elif strike_result.action == StrikeAction.TIMEOUT:
                        try:
                            await channel.send(f"/timeout {username} {strike_result.duration} {strike_result.message[:100]}")
                        except Exception as e:
                            logger.warning("Failed to timeout user: %s", e)
                    else:
                        await channel.send(strike_result.message)
                else:
                    # Direct ban
                    try:
                        await channel.send(f"/ban {username} AutoMod: {reason[:100]}")
                    except Exception as e:
                        logger.warning("Failed to ban user: %s", e)
                
                self.db.log_action(
                    user_id=user_id,
                    username=username,
                    action="ban",
                    reason=reason,
                    spam_score=score,
                    message_content=message.content[:500],
                    channel=channel.name,
                )
                logger.info("[BAN] %s (score: %d): %s", username, score, reason)
            
            self._update_action_cooldown(user_id)
            
        except Exception as e:
            logger.error("Error taking action on %s: %s", username, e)
    
    @commands.Cog.event()
    async def event_message(self, message: Message) -> None:
        """Process incoming messages for spam detection."""
        # Skip if automod is disabled
        if not self.enabled:
            return
        
        # Skip echo messages (from bot itself)
        if message.echo:
            return
        
        # Skip if no author
        if not message.author:
            return
        
        # Skip if no content
        if not message.content:
            return
        
        user_id = str(message.author.id)
        username = message.author.name
        channel_name = message.channel.name if message.channel else ""
        
        # Get user context
        context = await self._get_user_context(message.author, user_id, username, channel_name)
        
        # Skip mods and broadcaster
        if context["is_mod"] or context["is_broadcaster"]:
            self.db.update_user_message(user_id)
            return
        
        # Analyze message
        result = self.detector.analyze(
            message=message.content,
            user_id=user_id,
            username=username,
            **context,
        )
        
        # Update user message count
        self.db.update_user_message(user_id)
        
        # Take action if needed
        if result.should_act:
            reason = "; ".join(result.reasons[:3])
            if result.matched_patterns:
                reason += f" | Patterns: {', '.join(result.matched_patterns[:2])}"
            
            await self._take_action(
                message=message,
                action=result.action,
                reason=reason,
                score=result.score,
                is_subscriber_protected=result.is_subscriber_protected,
            )
    
    # ==================== Commands ====================
    
    @commands.command(name="automod")
    @is_moderator()
    async def automod_cmd(self, ctx: Context, action: str = "status", value: str = "") -> None:
        """Control automod settings. Usage: !automod <on/off/status/sensitivity/strikes>"""
        action = action.lower()
        
        if action == "on":
            owner = self.bot.config.owner.lower()
            if ctx.author.name.lower() != owner:
                await ctx.send(f"@{ctx.author.name} Only the owner can enable/disable automod.")
                return
            
            self.enabled = True
            await ctx.send(f"@{ctx.author.name} AutoMod is now ENABLED.")
            logger.info("AutoMod enabled by %s", ctx.author.name)
        
        elif action == "off":
            owner = self.bot.config.owner.lower()
            if ctx.author.name.lower() != owner:
                await ctx.send(f"@{ctx.author.name} Only the owner can enable/disable automod.")
                return
            
            self.enabled = False
            await ctx.send(f"@{ctx.author.name} AutoMod is now DISABLED.")
            logger.info("AutoMod disabled by %s", ctx.author.name)
        
        elif action == "sensitivity":
            owner = self.bot.config.owner.lower()
            if ctx.author.name.lower() != owner:
                await ctx.send(f"@{ctx.author.name} Only the owner can change sensitivity.")
                return
            
            if value.lower() not in ("low", "medium", "high"):
                await ctx.send(f"@{ctx.author.name} Valid options: low, medium, high")
                return
            
            self.detector.set_sensitivity(value.lower())
            await ctx.send(f"@{ctx.author.name} AutoMod sensitivity set to {value.upper()}.")
            logger.info("AutoMod sensitivity changed to %s by %s", value, ctx.author.name)
        
        elif action == "strikes":
            owner = self.bot.config.owner.lower()
            if ctx.author.name.lower() != owner:
                await ctx.send(f"@{ctx.author.name} Only the owner can toggle strike system.")
                return
            
            if value.lower() == "on":
                self.use_strikes = True
                await ctx.send(f"@{ctx.author.name} Strike system ENABLED.")
            elif value.lower() == "off":
                self.use_strikes = False
                await ctx.send(f"@{ctx.author.name} Strike system DISABLED.")
            else:
                status = "ON" if self.use_strikes else "OFF"
                await ctx.send(f"@{ctx.author.name} Strike system: {status}. Use !automod strikes on/off")
        
        elif action == "status":
            stats = self.db.get_action_stats(24)
            total_actions = sum(stats.values())
            
            status = "ENABLED" if self.enabled else "DISABLED"
            sensitivity = self.detector.sensitivity.upper()
            strikes_status = "ON" if self.use_strikes else "OFF"
            
            stats_str = ", ".join(f"{k}: {v}" for k, v in stats.items()) if stats else "none"
            
            await ctx.send(
                f"@{ctx.author.name} AutoMod: {status} | Sensitivity: {sensitivity} | "
                f"Strikes: {strikes_status} | 24h actions: {total_actions} ({stats_str})"
            )
        
        else:
            await ctx.send(f"@{ctx.author.name} Usage: !automod <on/off/status/sensitivity/strikes>")
    
    @commands.command(name="strikes")
    @is_moderator()
    async def strikes_cmd(self, ctx: Context, username: str = "") -> None:
        """View user's strike count. Usage: !strikes @username"""
        if not username:
            await ctx.send(f"@{ctx.author.name} Usage: !strikes @username")
            return
        
        username = username.lstrip("@").lower()
        user_id = username  # Simplified
        
        info = self.strikes.format_strikes_info(user_id, username)
        await ctx.send(f"@{ctx.author.name} {info}")
    
    @commands.command(name="clearstrikes")
    @is_moderator()
    async def clear_strikes_cmd(self, ctx: Context, username: str = "") -> None:
        """Clear user's strikes. Usage: !clearstrikes @username"""
        if not username:
            await ctx.send(f"@{ctx.author.name} Usage: !clearstrikes @username")
            return
        
        username = username.lstrip("@").lower()
        user_id = username
        
        if self.strikes.clear_strikes(user_id, ctx.author.name):
            await ctx.send(f"@{ctx.author.name} Cleared strikes for {username}")
            logger.info("Strikes cleared for %s by %s", username, ctx.author.name)
        else:
            await ctx.send(f"@{ctx.author.name} No strikes found for {username}")
    
    @commands.command(name="addstrike")
    @is_moderator()
    async def add_strike_cmd(self, ctx: Context, username: str = "", *, reason: str = "Manual strike") -> None:
        """Manually add a strike. Usage: !addstrike @username [reason]"""
        if not username:
            await ctx.send(f"@{ctx.author.name} Usage: !addstrike @username [reason]")
            return
        
        username = username.lstrip("@").lower()
        user_id = username
        
        result = self.strikes.add_strike(
            user_id=user_id,
            username=username,
            reason=reason,
            moderator=ctx.author.name,
            channel=ctx.channel.name,
            is_subscriber=False  # Can't check without user object
        )
        
        await ctx.send(f"@{ctx.author.name} {result.message}")
        logger.info("Manual strike added to %s by %s: %s", username, ctx.author.name, reason)
    
    @commands.command(name="whitelist")
    @is_moderator()
    async def whitelist_cmd(self, ctx: Context, username: str = "") -> None:
        """Add a user to the automod whitelist. Usage: !whitelist @username"""
        if not username:
            await ctx.send(f"@{ctx.author.name} Usage: !whitelist @username")
            return
        
        username = username.lstrip("@").lower()
        user_id = username
        
        self.db.set_whitelisted(user_id, username, True)
        await ctx.send(f"@{ctx.author.name} {username} has been added to the whitelist.")
        logger.info("%s whitelisted by %s", username, ctx.author.name)
    
    @commands.command(name="unwhitelist")
    @is_moderator()
    async def unwhitelist_cmd(self, ctx: Context, username: str = "") -> None:
        """Remove a user from the automod whitelist. Usage: !unwhitelist @username"""
        if not username:
            await ctx.send(f"@{ctx.author.name} Usage: !unwhitelist @username")
            return
        
        username = username.lstrip("@").lower()
        user_id = username
        
        self.db.set_whitelisted(user_id, username, False)
        await ctx.send(f"@{ctx.author.name} {username} has been removed from the whitelist.")
        logger.info("%s unwhitelisted by %s", username, ctx.author.name)
    
    @commands.command(name="permit")
    @is_moderator()
    async def permit_cmd(self, ctx: Context, username: str = "") -> None:
        """Grant temporary link permission. Usage: !permit @username"""
        if not username:
            await ctx.send(f"@{ctx.author.name} Usage: !permit @username")
            return
        
        username = username.lstrip("@").lower()
        user_id = username
        
        self.db.grant_permit(user_id, ctx.author.name, duration_seconds=60)
        await ctx.send(f"@{username} You have 60 seconds to post a link.")
        logger.info("%s granted permit by %s", username, ctx.author.name)
    
    @commands.command(name="modlog")
    @is_moderator()
    async def modlog_cmd(self, ctx: Context, count: str = "10") -> None:
        """Show recent moderation actions. Usage: !modlog [count]"""
        try:
            limit = min(int(count), 25)
        except ValueError:
            limit = 10
        
        actions = self.db.get_recent_actions(limit=limit, channel=ctx.channel.name)
        
        if not actions:
            await ctx.send(f"@{ctx.author.name} No recent moderation actions.")
            return
        
        lines = []
        for action in actions[:3]:
            timestamp = action.get("timestamp", "?")[:16]
            username = action.get("username", "?")
            act = action.get("action", "?")
            score = action.get("spam_score", 0)
            lines.append(f"{username}: {act} (score: {score})")
        
        await ctx.send(f"@{ctx.author.name} Recent actions: " + " | ".join(lines))
        
        if len(actions) > 3:
            await ctx.send(f"... and {len(actions) - 3} more. Check dashboard for full history.")
    
    @commands.command(name="checkuser")
    @is_moderator()
    async def checkuser_cmd(self, ctx: Context, username: str = "") -> None:
        """Check a user's automod stats. Usage: !checkuser @username"""
        if not username:
            await ctx.send(f"@{ctx.author.name} Usage: !checkuser @username")
            return
        
        username = username.lstrip("@").lower()
        user_id = username
        
        stats = self.db.get_user_stats(user_id)
        strikes_info = self.strikes.get_strikes(user_id)
        
        if not stats:
            await ctx.send(f"@{ctx.author.name} No data for {username}.")
            return
        
        trust = stats.get("trust_score", 50)
        messages = stats.get("message_count", 0)
        warnings = stats.get("warnings_count", 0)
        whitelisted = "Yes" if stats.get("is_whitelisted") else "No"
        strike_count = strikes_info.get("strike_count", 0)
        
        await ctx.send(
            f"@{ctx.author.name} {username}: Trust: {trust}/100 | "
            f"Messages: {messages} | Warnings: {warnings} | "
            f"Strikes: {strike_count}/5 | Whitelisted: {whitelisted}"
        )


def prepare(bot: TwitchBot) -> None:
    """Prepare the cog for loading."""
    bot.add_cog(AutoMod(bot))
