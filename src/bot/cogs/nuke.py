"""
Nuke command cog for Twitch bot.

Provides mass moderation capabilities with safety features:
- Pattern matching on recent messages
- Preview before execution
- Excludes mods/VIPs/subs by default
- Full audit logging
- Cooldown protection
"""

from __future__ import annotations

import os
import re
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


# Maximum regex pattern length to prevent complexity attacks
MAX_REGEX_LENGTH = 100
REGEX_TIMEOUT = 1.0


def is_safe_regex(pattern: str) -> tuple[bool, str]:
    """Validate regex pattern for potential ReDoS vulnerabilities."""
    if len(pattern) > MAX_REGEX_LENGTH:
        return False, f"Pattern too long (max {MAX_REGEX_LENGTH} characters)"
    
    # Check for nested quantifiers - common ReDoS pattern
    nested_patterns = [
        r'\([^)]*[+*][^)]*\)[+*]',
        r'\([^)]*\|[^)]*[+*][^)]*\)[+*]',
    ]
    
    for dangerous in nested_patterns:
        if re.search(dangerous, pattern):
            return False, "Pattern contains potentially dangerous nested quantifiers"
    
    quantifier_count = len(re.findall(r'[+*?]', pattern))
    if quantifier_count > 10:
        return False, "Pattern contains too many quantifiers"
    
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
        compiled.search("test" * 10)
    except re.error as e:
        return False, f"Invalid regex pattern: {e}"
    
    return True, ""


def safe_regex_search(pattern: str, text: str, timeout: float = REGEX_TIMEOUT):
    """Perform regex search with safety limits."""
    try:
        import regex as regex_module
        try:
            compiled = regex_module.compile(pattern, regex_module.IGNORECASE, timeout=timeout)
            return compiled.search(text)
        except regex_module.TimeoutError:
            return None
    except ImportError:
        max_text_length = 1000
        truncated_text = text[:max_text_length]
        compiled = re.compile(pattern, re.IGNORECASE)
        return compiled.search(truncated_text)



class NukeManager:
    """Manages the nuke command functionality."""
    
    def __init__(self, db: DatabaseManager) -> None:
        """Initialize the nuke manager."""
        self.db = db
        self.max_users = int(os.getenv("NUKE_MAX_USERS", "50"))
        self.max_lookback = int(os.getenv("NUKE_MAX_LOOKBACK", "120"))
        self.cooldown_seconds = int(os.getenv("NUKE_COOLDOWN", "30"))
        self._last_nuke: dict[str, datetime] = {}
    
    def is_on_cooldown(self, channel: str) -> tuple[bool, int]:
        """Check if nuke is on cooldown for a channel."""
        if channel not in self._last_nuke:
            return False, 0
        
        elapsed = (datetime.now(timezone.utc) - self._last_nuke[channel]).total_seconds()
        if elapsed < self.cooldown_seconds:
            return True, int(self.cooldown_seconds - elapsed)
        return False, 0
    
    def update_cooldown(self, channel: str) -> None:
        """Update the cooldown timestamp for a channel."""
        self._last_nuke[channel] = datetime.now(timezone.utc)
    
    def find_matches(
        self,
        channel: str,
        pattern: str,
        lookback: int,
        is_regex: bool,
        include_subs: bool,
        include_vips: bool
    ) -> tuple[list[dict[str, Any]], Optional[str]]:
        """Find users matching pattern in recent messages."""
        # Get recent messages
        messages = self.db.get_recent_messages(
            channel=channel,
            lookback_seconds=min(lookback, self.max_lookback),
            include_subs=include_subs,
            include_vips=include_vips
        )
        
        matches: dict[str, dict[str, Any]] = {}  # {user_id: {username, message}}
        
        if is_regex:
            # Validate regex pattern for safety (ReDoS protection)
            is_safe, error = is_safe_regex(pattern)
            if not is_safe:
                return [], error
            
            for msg in messages:
                result = safe_regex_search(pattern, msg["message"])
                if result:
                    user_id = msg["user_id"]
                    if user_id not in matches:
                        matches[user_id] = {
                            "user_id": user_id,
                            "username": msg["username"],
                            "message": msg["message"][:100]
                        }
        else:
            pattern_lower = pattern.lower()
            for msg in messages:
                if pattern_lower in msg["message"].lower():
                    user_id = msg["user_id"]
                    if user_id not in matches:
                        matches[user_id] = {
                            "user_id": user_id,
                            "username": msg["username"],
                            "message": msg["message"][:100]
                        }
        
        # Limit to max users
        result = list(matches.values())[:self.max_users]
        return result, None


class Nuke(commands.Cog):
    """
    Nuke cog for mass moderation.
    
    Features:
    - Pattern matching on recent messages
    - Preview mode
    - Safety limits
    - Excludes protected users by default
    - Full audit logging
    - Confirmation required for large nukes (>20 users)
    """
    
    # Pending nuke confirmations: {channel: {data}}
    _pending_nukes: dict[str, dict] = {}
    
    def __init__(self, bot: TwitchBot) -> None:
        """Initialize the nuke cog."""
        self.bot = bot
        self.db: DatabaseManager = get_database()
        self.manager = NukeManager(self.db)
        
        logger.info("Nuke cog initialized")
    
    @commands.Cog.event()
    async def event_message(self, message: Message) -> None:
        """Cache recent messages for nuke command."""
        if message.echo or not message.author or not message.channel:
            return
        
        # Don't cache mod messages
        if getattr(message.author, "is_mod", False):
            return
        
        self.db.add_recent_message(
            channel=message.channel.name,
            user_id=str(message.author.id),
            username=message.author.name,
            message=message.content,
            is_subscriber=getattr(message.author, "is_subscriber", False),
            is_vip=getattr(message.author, "is_vip", False),
            is_mod=getattr(message.author, "is_mod", False)
        )
    
    @commands.command(name="nuke")
    @is_moderator()
    async def nuke_cmd(self, ctx: Context, *, args: str = "") -> None:
        """
        Mass timeout/ban users matching a pattern.
        
        Usage: !nuke "pattern" [duration] [options]
        
        Examples:
            !nuke "buy followers" 600       - Timeout matching users for 10 min
            !nuke "free vbucks" ban         - Ban matching users
            !nuke "spam" preview            - Preview only, don't execute
            !nuke "test" 300 --include-subs - Include subs
            !nuke "regex.*pattern" 600 --regex - Use regex
        
        Options:
            --include-subs    Include subscribers
            --include-vips    Include VIPs
            --regex           Treat pattern as regex
            --lookback N      Only check last N seconds (default: 60, max: 120)
        """
        if not args:
            await ctx.send(f"@{ctx.author.name} Usage: !nuke \"pattern\" [duration/ban/preview] [options]")
            return
        
        channel_name = ctx.channel.name
        
        # Check cooldown
        on_cooldown, remaining = self.manager.is_on_cooldown(channel_name)
        if on_cooldown:
            await ctx.send(f"@{ctx.author.name} Nuke on cooldown ({remaining}s remaining)")
            return
        
        # Parse arguments
        pattern, action, duration, options = self._parse_args(args)
        
        if not pattern:
            await ctx.send(f"@{ctx.author.name} Please provide a pattern in quotes")
            return
        
        # Find matches
        matches, error = self.manager.find_matches(
            channel=channel_name,
            pattern=pattern,
            lookback=options.get("lookback", 60),
            is_regex=options.get("regex", False),
            include_subs=options.get("include_subs", False),
            include_vips=options.get("include_vips", False)
        )
        
        if error:
            await ctx.send(f"@{ctx.author.name} Regex error: {error}")
            return
        
        if not matches:
            await ctx.send(f"@{ctx.author.name} No users found matching pattern")
            return
        
        # Preview mode
        if action == "preview":
            usernames = [m["username"] for m in matches[:10]]
            preview = ", ".join(usernames)
            if len(matches) > 10:
                preview += f" ... and {len(matches) - 10} more"
            await ctx.send(f"@{ctx.author.name} [PREVIEW] Would affect {len(matches)} users: {preview}")
            return
        
        # Confirmation for large nukes
        if len(matches) > 20:
            channel_name_lower = channel_name.lower()
            self._pending_nukes[channel_name_lower] = {
                "matches": matches,
                "action": action,
                "duration": duration,
                "pattern": pattern,
                "mod": ctx.author.name,
                "expires": datetime.now(timezone.utc) + timedelta(seconds=30)
            }
            await ctx.send(
                f"@{ctx.author.name} ⚠️ About to {action} {len(matches)} users matching '{pattern}'. "
                f"Type !nukeconfirm within 30 seconds to proceed, or !nukecancel to abort."
            )
            return
        
        # Execute nuke
        await self._execute_nuke(ctx, matches, action, duration, pattern)
    
    def _parse_args(self, args: str) -> tuple[str, str, int, dict]:
        """Parse nuke command arguments."""
        pattern = ""
        action = "timeout"
        duration = 600  # Default 10 minutes
        options = {
            "include_subs": False,
            "include_vips": False,
            "regex": False,
            "lookback": 60
        }
        
        # Extract quoted pattern
        quote_match = re.search(r'"([^"]+)"', args)
        if quote_match:
            pattern = quote_match.group(1)
            args = args.replace(f'"{pattern}"', "").strip()
        else:
            # Try first word as pattern
            parts = args.split()
            if parts:
                pattern = parts[0]
                args = " ".join(parts[1:])
        
        # Parse remaining args
        parts = args.split()
        for i, part in enumerate(parts):
            part_lower = part.lower()
            
            if part_lower == "ban":
                action = "ban"
            elif part_lower == "preview":
                action = "preview"
            elif part_lower.isdigit():
                duration = int(part_lower)
            elif part_lower == "--include-subs":
                options["include_subs"] = True
            elif part_lower == "--include-vips":
                options["include_vips"] = True
            elif part_lower == "--regex":
                options["regex"] = True
            elif part_lower == "--lookback" and i + 1 < len(parts):
                try:
                    options["lookback"] = int(parts[i + 1])
                except ValueError:
                    pass
        
        return pattern, action, duration, options
    
    async def _execute_nuke(
        self,
        ctx: Context,
        matches: list[dict],
        action: str,
        duration: int,
        pattern: str
    ) -> None:
        """Execute the nuke command."""
        channel = ctx.channel
        moderator = ctx.author.name
        
        success_count = 0
        failed_count = 0
        affected_users = []
        
        for match in matches:
            username = match["username"]
            
            try:
                if action == "ban":
                    await channel.send(f"/ban {username} Nuke: {pattern[:50]}")
                else:
                    await channel.send(f"/timeout {username} {duration} Nuke: {pattern[:50]}")
                
                success_count += 1
                affected_users.append(username)
            except Exception as e:
                logger.warning("Failed to %s %s: %s", action, username, e)
                failed_count += 1
        
        # Log the nuke
        self.db.log_nuke(
            moderator=moderator,
            channel=channel.name,
            pattern=pattern,
            action=action,
            duration=duration if action == "timeout" else None,
            users_affected=success_count,
            users_list=affected_users
        )
        
        # Update cooldown
        self.manager.update_cooldown(channel.name)
        
        # Report results
        action_str = "banned" if action == "ban" else f"timed out ({duration}s)"
        await ctx.send(f"@{moderator} Nuke complete: {success_count} users {action_str}")
        
        if failed_count > 0:
            await ctx.send(f"@{moderator} {failed_count} actions failed")
        
        logger.info(
            "Nuke executed by %s in %s: pattern='%s', action=%s, affected=%d",
            moderator, channel.name, pattern, action, success_count
        )
    
    @commands.command(name="nukeconfirm")
    @is_moderator()
    async def nuke_confirm(self, ctx: Context) -> None:
        """Confirm a pending nuke action."""
        channel = ctx.channel.name.lower()
        
        if channel not in self._pending_nukes:
            await ctx.send(f"@{ctx.author.name} No pending nuke to confirm.")
            return
        
        pending = self._pending_nukes[channel]
        
        # Check expiry
        if datetime.now(timezone.utc) > pending["expires"]:
            del self._pending_nukes[channel]
            await ctx.send(f"@{ctx.author.name} Nuke confirmation expired. Run the command again.")
            return
        
        # Check same mod
        if pending["mod"] != ctx.author.name:
            await ctx.send(f"@{ctx.author.name} Only {pending['mod']} can confirm this nuke.")
            return
        
        # Execute the nuke
        await self._execute_nuke(
            ctx,
            pending["matches"],
            pending["action"],
            pending["duration"],
            pending["pattern"]
        )
        del self._pending_nukes[channel]
    
    @commands.command(name="nukecancel")
    @is_moderator()
    async def nuke_cancel(self, ctx: Context) -> None:
        """Cancel a pending nuke."""
        channel = ctx.channel.name.lower()
        if channel in self._pending_nukes:
            del self._pending_nukes[channel]
            await ctx.send(f"@{ctx.author.name} Nuke cancelled.")
        else:
            await ctx.send(f"@{ctx.author.name} No pending nuke to cancel.")
    
    @commands.command(name="nukelog")
    @is_moderator()
    async def nuke_log(self, ctx: Context, count: str = "5") -> None:
        """Show recent nuke actions. Usage: !nukelog [count]"""
        try:
            limit = min(int(count), 10)
        except ValueError:
            limit = 5
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM nuke_log 
                WHERE channel = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
                """,
                (ctx.channel.name, limit)
            )
            logs = [dict(row) for row in cursor.fetchall()]
        
        if not logs:
            await ctx.send(f"@{ctx.author.name} No nuke history.")
            return
        
        entries = []
        for log in logs[:3]:
            mod = log.get("moderator", "?")
            pattern = log.get("pattern", "?")[:20]
            affected = log.get("users_affected", 0)
            action = log.get("action", "timeout")
            entries.append(f"{mod}: '{pattern}' ({affected} {action}s)")
        
        await ctx.send(f"@{ctx.author.name} Recent nukes: " + " | ".join(entries))


def prepare(bot: TwitchBot) -> None:
    """Prepare the cog for loading."""
    bot.add_cog(Nuke(bot))
