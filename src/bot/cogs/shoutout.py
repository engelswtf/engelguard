"""
Shoutout and Watchtime cog for Twitch bot.

Features:
- Manual shoutouts with !so or !shoutout (mod only)
- Auto-shoutout on raids (configurable)
- Customizable shoutout messages with variables
- Cooldown to prevent spam
- Fetch last game played from Twitch API
- Watchtime commands (!watchtime, !topwatchtime)
- First-time chatter detection and welcome messages
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

import aiohttp
from twitchio.ext import commands
from twitchio.ext.commands import Context

from bot.utils.database import get_database, DatabaseManager
from bot.utils.logging import get_logger
from bot.utils.permissions import is_moderator, is_owner, cooldown, CooldownBucket

if TYPE_CHECKING:
    from twitchio import Message
    from bot.bot import TwitchBot

logger = get_logger(__name__)


# Default messages
DEFAULT_SHOUTOUT_MESSAGE = "Go check out @$(user) at twitch.tv/$(user) - They were last playing $(game)! 💜"
DEFAULT_WELCOME_MESSAGE = "Welcome to the stream @$(user)! 👋"


class ShoutoutSettings:
    """Container for channel shoutout settings."""

    def __init__(
        self,
        channel: str,
        enabled: bool = True,
        auto_raid_shoutout: bool = True,
        message: str = DEFAULT_SHOUTOUT_MESSAGE,
        cooldown_seconds: int = 300,
    ) -> None:
        self.channel = channel
        self.enabled = enabled
        self.auto_raid_shoutout = auto_raid_shoutout
        self.message = message
        self.cooldown_seconds = cooldown_seconds


class FirstChatterSettings:
    """Container for first-time chatter settings."""

    def __init__(
        self,
        channel: str,
        enabled: bool = True,
        message: str = DEFAULT_WELCOME_MESSAGE,
    ) -> None:
        self.channel = channel
        self.enabled = enabled
        self.message = message


class ShoutoutCog(commands.Cog):
    """
    Shoutout and Watchtime cog for Twitch bot.

    Features:
    - Manual shoutouts (!so, !shoutout)
    - Auto-shoutout on raids
    - Watchtime tracking and display
    - First-time chatter detection
    """

    def __init__(self, bot: TwitchBot) -> None:
        """Initialize the shoutout cog."""
        self.bot = bot
        self.db: DatabaseManager = get_database()

        # Cache for settings
        self._shoutout_settings_cache: dict[str, ShoutoutSettings] = {}
        self._first_chatter_settings_cache: dict[str, FirstChatterSettings] = {}

        # Cooldown tracking: {channel: {username: last_shoutout_time}}
        self._shoutout_cooldowns: dict[str, dict[str, float]] = {}

        # Track known chatters per channel: {channel: set(user_ids)}
        self._known_chatters: dict[str, set[str]] = {}

        # HTTP session for API calls
        self._session: Optional[aiohttp.ClientSession] = None
        
        # API rate limiting - max 5 concurrent API calls to prevent hitting Twitch rate limits
        self._api_semaphore: asyncio.Semaphore = asyncio.Semaphore(5)

        # Initialize database tables
        self._init_database()

        logger.info("ShoutoutCog initialized")

    def _init_database(self) -> None:
        """Initialize database tables for shoutout and first-chatter features."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # Shoutout settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shoutout_settings (
                    channel TEXT PRIMARY KEY,
                    enabled BOOLEAN DEFAULT TRUE,
                    auto_raid_shoutout BOOLEAN DEFAULT TRUE,
                    message TEXT DEFAULT 'Go check out @$(user) at twitch.tv/$(user) - They were last playing $(game)! 💜',
                    cooldown_seconds INTEGER DEFAULT 300
                )
            """)

            # Shoutout history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shoutout_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    target_user TEXT NOT NULL,
                    shouted_by TEXT NOT NULL,
                    shouted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    was_raid BOOLEAN DEFAULT FALSE
                )
            """)

            # First chatter settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS first_chatter_settings (
                    channel TEXT PRIMARY KEY,
                    enabled BOOLEAN DEFAULT TRUE,
                    message TEXT DEFAULT 'Welcome to the stream @$(user)! 👋'
                )
            """)

            # Known chatters table (persistent tracking)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS known_chatters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    username TEXT,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(channel, user_id)
                )
            """)

            # Create index for faster lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_known_chatters_channel_user
                ON known_chatters(channel, user_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_shoutout_history_channel
                ON shoutout_history(channel, target_user)
            """)

            logger.debug("Shoutout database tables initialized")

    async def cog_load(self) -> None:
        """Called when cog is loaded."""
        # Load known chatters from database into memory
        await self._load_known_chatters()
        logger.info("ShoutoutCog loaded")

    async def cog_unload(self) -> None:
        """Called when cog is unloaded."""
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("ShoutoutCog unloaded")

    async def _load_known_chatters(self) -> None:
        """Load known chatters from database into memory cache."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT channel, user_id FROM known_chatters")
            rows = cursor.fetchall()

            for row in rows:
                channel = row["channel"]
                user_id = row["user_id"]
                if channel not in self._known_chatters:
                    self._known_chatters[channel] = set()
                self._known_chatters[channel].add(user_id)

        logger.debug("Loaded %d known chatter records", sum(len(v) for v in self._known_chatters.values()))

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session for API calls."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _get_app_access_token(self) -> Optional[str]:
        """Get an app access token for Twitch API calls."""
        try:
            session = await self._get_session()
            async with session.post(
                "https://id.twitch.tv/oauth2/token",
                data={
                    "client_id": self.bot.config.client_id,
                    "client_secret": self.bot.config.client_secret,
                    "grant_type": "client_credentials",
                },
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("access_token")
                logger.error("Failed to get app token: HTTP %d", resp.status)
                return None
        except Exception as e:
            logger.error("Error getting app token: %s", e)
            return None

    # ==================== Settings Management ====================

    def _get_shoutout_settings(self, channel: str) -> ShoutoutSettings:
        """Get shoutout settings for a channel."""
        channel = channel.lower()

        if channel in self._shoutout_settings_cache:
            return self._shoutout_settings_cache[channel]

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM shoutout_settings WHERE channel = ?",
                (channel,),
            )
            row = cursor.fetchone()

            if row:
                settings = ShoutoutSettings(
                    channel=channel,
                    enabled=bool(row["enabled"]),
                    auto_raid_shoutout=bool(row["auto_raid_shoutout"]),
                    message=row["message"],
                    cooldown_seconds=row["cooldown_seconds"],
                )
            else:
                settings = ShoutoutSettings(channel=channel)

            self._shoutout_settings_cache[channel] = settings
            return settings

    def _save_shoutout_settings(self, settings: ShoutoutSettings) -> None:
        """Save shoutout settings to database."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO shoutout_settings (channel, enabled, auto_raid_shoutout, message, cooldown_seconds)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(channel) DO UPDATE SET
                    enabled = excluded.enabled,
                    auto_raid_shoutout = excluded.auto_raid_shoutout,
                    message = excluded.message,
                    cooldown_seconds = excluded.cooldown_seconds
                """,
                (
                    settings.channel,
                    settings.enabled,
                    settings.auto_raid_shoutout,
                    settings.message,
                    settings.cooldown_seconds,
                ),
            )

        self._shoutout_settings_cache[settings.channel] = settings
        logger.debug("Saved shoutout settings for %s", settings.channel)

    def _get_first_chatter_settings(self, channel: str) -> FirstChatterSettings:
        """Get first-chatter settings for a channel."""
        channel = channel.lower()

        if channel in self._first_chatter_settings_cache:
            return self._first_chatter_settings_cache[channel]

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM first_chatter_settings WHERE channel = ?",
                (channel,),
            )
            row = cursor.fetchone()

            if row:
                settings = FirstChatterSettings(
                    channel=channel,
                    enabled=bool(row["enabled"]),
                    message=row["message"],
                )
            else:
                settings = FirstChatterSettings(channel=channel)

            self._first_chatter_settings_cache[channel] = settings
            return settings

    def _save_first_chatter_settings(self, settings: FirstChatterSettings) -> None:
        """Save first-chatter settings to database."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO first_chatter_settings (channel, enabled, message)
                VALUES (?, ?, ?)
                ON CONFLICT(channel) DO UPDATE SET
                    enabled = excluded.enabled,
                    message = excluded.message
                """,
                (settings.channel, settings.enabled, settings.message),
            )

        self._first_chatter_settings_cache[settings.channel] = settings
        logger.debug("Saved first-chatter settings for %s", settings.channel)

    # ==================== Cooldown Management ====================

    def _check_shoutout_cooldown(self, channel: str, target_user: str) -> tuple[bool, int]:
        """
        Check if a shoutout is on cooldown.

        Args:
            channel: Channel name
            target_user: Target username

        Returns:
            Tuple of (is_on_cooldown, remaining_seconds)
        """
        channel = channel.lower()
        target_user = target_user.lower()
        settings = self._get_shoutout_settings(channel)
        now = time.time()

        if channel not in self._shoutout_cooldowns:
            self._shoutout_cooldowns[channel] = {}

        last_shoutout = self._shoutout_cooldowns[channel].get(target_user, 0)
        elapsed = now - last_shoutout

        if elapsed < settings.cooldown_seconds:
            remaining = int(settings.cooldown_seconds - elapsed)
            return True, remaining

        return False, 0

    def _update_shoutout_cooldown(self, channel: str, target_user: str) -> None:
        """Update the cooldown timestamp for a shoutout."""
        channel = channel.lower()
        target_user = target_user.lower()

        if channel not in self._shoutout_cooldowns:
            self._shoutout_cooldowns[channel] = {}

        self._shoutout_cooldowns[channel][target_user] = time.time()

    # ==================== Twitch API Helpers ====================

    async def _get_last_game(self, username: str) -> str:
        """
        Get the last game played by a user from Twitch API.
        
        Uses semaphore to limit concurrent API calls and prevent rate limiting.

        Args:
            username: Twitch username

        Returns:
            Game name or "an awesome game" if not found
        """
        async with self._api_semaphore:
            try:
                token = await self._get_app_access_token()
                if not token:
                    return "an awesome game"

                session = await self._get_session()
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Client-Id": self.bot.config.client_id,
                }

                # First, get user ID
                users = await self.bot.fetch_users(names=[username])
                if not users:
                    return "an awesome game"

                user_id = str(users[0].id)

                # Check if they're currently live
                async with session.get(
                    "https://api.twitch.tv/helix/streams",
                    headers=headers,
                    params={"user_login": username},
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("data"):
                            return data["data"][0].get("game_name", "an awesome game")

                # If not live, get channel info for last game
                async with session.get(
                    "https://api.twitch.tv/helix/channels",
                    headers=headers,
                    params={"broadcaster_id": user_id},
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("data"):
                            return data["data"][0].get("game_name", "an awesome game")

                return "an awesome game"

            except Exception as e:
                logger.error("Error fetching last game for %s: %s", username, e)
                return "an awesome game"

    # ==================== Variable Parsing ====================

    def _parse_shoutout_variables(
        self,
        template: str,
        user: str,
        game: str,
        channel: str,
    ) -> str:
        """
        Parse variables in shoutout message template.

        Supported variables:
        - $(user) - Target username
        - $(game) - Last game played
        - $(channel) - Current channel

        Args:
            template: Message template
            user: Target username
            game: Last game played
            channel: Current channel name

        Returns:
            Parsed message string
        """
        result = template

        replacements = {
            r"\$\(user\)": user,
            r"\$\(game\)": game,
            r"\$\(channel\)": channel,
        }

        for pattern, value in replacements.items():
            result = re.sub(pattern, value, result, flags=re.IGNORECASE)

        return result

    def _parse_welcome_variables(self, template: str, user: str) -> str:
        """
        Parse variables in welcome message template.

        Supported variables:
        - $(user) - Username

        Args:
            template: Message template
            user: Username

        Returns:
            Parsed message string
        """
        result = template
        result = re.sub(r"\$\(user\)", user, result, flags=re.IGNORECASE)
        return result

    # ==================== Shoutout History ====================

    def _log_shoutout(
        self,
        channel: str,
        target_user: str,
        shouted_by: str,
        was_raid: bool = False,
    ) -> None:
        """Log a shoutout to the database."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO shoutout_history (channel, target_user, shouted_by, was_raid)
                VALUES (?, ?, ?, ?)
                """,
                (channel.lower(), target_user.lower(), shouted_by.lower(), was_raid),
            )

    # ==================== Watchtime Formatting ====================

    @staticmethod
    def _format_watchtime(minutes: int) -> str:
        """
        Format watch time in a human-readable format.

        Args:
            minutes: Total watch time in minutes

        Returns:
            Formatted string like "2h 30m" or "1d 5h 20m"
        """
        if minutes < 60:
            return f"{minutes}m"

        days, remainder = divmod(minutes, 1440)  # 1440 minutes in a day
        hours, mins = divmod(remainder, 60)

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if mins > 0 or not parts:
            parts.append(f"{mins}m")

        return " ".join(parts)

    # ==================== Shoutout Commands ====================

    @commands.command(name="so", aliases=["shoutout"])
    @is_moderator()
    async def shoutout(self, ctx: Context, username: str = "") -> None:
        """
        Give a shoutout to a user.

        Usage: !so <username> or !shoutout <username>
        """
        channel_name = ctx.channel.name
        settings = self._get_shoutout_settings(channel_name)

        if not settings.enabled:
            await ctx.send(f"@{ctx.author.name} Shoutouts are disabled.")
            return

        if not username:
            await ctx.send(f"@{ctx.author.name} Usage: !so <username>")
            return

        # Clean username
        target = username.lstrip("@").lower()

        # Check cooldown
        on_cooldown, remaining = self._check_shoutout_cooldown(channel_name, target)
        if on_cooldown:
            await ctx.send(
                f"@{ctx.author.name} Shoutout for {target} is on cooldown. "
                f"Try again in {remaining} seconds."
            )
            return

        # Fetch last game
        last_game = await self._get_last_game(target)

        # Get display name
        try:
            users = await self.bot.fetch_users(names=[target])
            if users:
                display_name = users[0].display_name or users[0].name
            else:
                display_name = target
        except Exception:
            display_name = target

        # Parse and send message
        message = self._parse_shoutout_variables(
            settings.message,
            user=display_name,
            game=last_game,
            channel=channel_name,
        )

        await ctx.send(message)

        # Update cooldown and log
        self._update_shoutout_cooldown(channel_name, target)
        self._log_shoutout(channel_name, target, ctx.author.name, was_raid=False)

        logger.info(
            "Shoutout to %s by %s in %s",
            target,
            ctx.author.name,
            channel_name,
        )

    # ==================== Shoutout Settings Commands ====================

    @commands.command(name="soset")
    @is_owner()
    async def shoutout_settings(self, ctx: Context, action: str = "", *, value: str = "") -> None:
        """
        Configure shoutout settings.

        Usage:
            !soset status - Show current settings
            !soset on/off - Enable/disable shoutouts
            !soset autoraid on/off - Enable/disable auto-shoutout on raids
            !soset message <message> - Set shoutout message
            !soset cooldown <seconds> - Set cooldown between shoutouts
        """
        channel_name = ctx.channel.name
        settings = self._get_shoutout_settings(channel_name)
        action = action.lower()

        if action in ("", "status"):
            status = "ENABLED" if settings.enabled else "DISABLED"
            autoraid = "ON" if settings.auto_raid_shoutout else "OFF"
            await ctx.send(
                f"@{ctx.author.name} Shoutouts: {status} | Auto-raid: {autoraid} | "
                f"Cooldown: {settings.cooldown_seconds}s"
            )
            return

        if action == "on":
            settings.enabled = True
            self._save_shoutout_settings(settings)
            await ctx.send(f"@{ctx.author.name} Shoutouts ENABLED!")
            return

        if action == "off":
            settings.enabled = False
            self._save_shoutout_settings(settings)
            await ctx.send(f"@{ctx.author.name} Shoutouts DISABLED.")
            return

        if action == "autoraid":
            if value.lower() == "on":
                settings.auto_raid_shoutout = True
                self._save_shoutout_settings(settings)
                await ctx.send(f"@{ctx.author.name} Auto-shoutout on raids ENABLED!")
            elif value.lower() == "off":
                settings.auto_raid_shoutout = False
                self._save_shoutout_settings(settings)
                await ctx.send(f"@{ctx.author.name} Auto-shoutout on raids DISABLED.")
            else:
                await ctx.send(f"@{ctx.author.name} Usage: !soset autoraid on/off")
            return

        if action == "message":
            if not value:
                await ctx.send(
                    f"@{ctx.author.name} Current message: {settings.message}"
                )
                return
            settings.message = value
            self._save_shoutout_settings(settings)
            await ctx.send(f"@{ctx.author.name} Shoutout message updated!")
            return

        if action == "cooldown":
            try:
                seconds = int(value)
                if seconds < 0:
                    raise ValueError("Cooldown must be positive")
                settings.cooldown_seconds = seconds
                self._save_shoutout_settings(settings)
                await ctx.send(f"@{ctx.author.name} Shoutout cooldown set to {seconds} seconds.")
            except ValueError:
                await ctx.send(f"@{ctx.author.name} Cooldown must be a positive number.")
            return

        await ctx.send(
            f"@{ctx.author.name} Usage: !soset <status/on/off/autoraid/message/cooldown>"
        )

# DISABLED - already in loyalty.py:     # ==================== Watchtime Commands ====================
# DISABLED - already in loyalty.py: 
# DISABLED - already in loyalty.py:     @commands.command(name="watchtime", aliases=["wt"])
# DISABLED - already in loyalty.py:     async def watchtime(self, ctx: Context, username: str = "") -> None:
# DISABLED - already in loyalty.py:         """
# DISABLED - already in loyalty.py:         Check your watch time or another user's watch time.
# DISABLED - already in loyalty.py: 
# DISABLED - already in loyalty.py:         Usage: !watchtime or !watchtime <username>
# DISABLED - already in loyalty.py:         """
# DISABLED - already in loyalty.py:         channel_name = ctx.channel.name
# DISABLED - already in loyalty.py: 
# DISABLED - already in loyalty.py:         # Determine target user
# DISABLED - already in loyalty.py:         if username:
# DISABLED - already in loyalty.py:             target_name = username.lstrip("@").lower()
# DISABLED - already in loyalty.py:             # Try to find user by username in loyalty table
# DISABLED - already in loyalty.py:             target_id = target_name
# DISABLED - already in loyalty.py:         else:
# DISABLED - already in loyalty.py:             target_name = ctx.author.name
# DISABLED - already in loyalty.py:             target_id = str(ctx.author.id)
# DISABLED - already in loyalty.py: 
# DISABLED - already in loyalty.py:         # Get loyalty data (which contains watch_time_minutes)
# DISABLED - already in loyalty.py:         loyalty = self.db.get_user_loyalty(target_id, channel_name)
# DISABLED - already in loyalty.py:         watch_time = loyalty.get("watch_time_minutes", 0)
# DISABLED - already in loyalty.py: 
# DISABLED - already in loyalty.py:         formatted_time = self._format_watchtime(watch_time)
# DISABLED - already in loyalty.py: 
# DISABLED - already in loyalty.py:         if username:
# DISABLED - already in loyalty.py:             await ctx.send(f"@{ctx.author.name} {target_name} has watched for {formatted_time}")
# DISABLED - already in loyalty.py:         else:
# DISABLED - already in loyalty.py:             await ctx.send(f"@{ctx.author.name} You have watched for {formatted_time}")
# DISABLED - already in loyalty.py: 
# DISABLED - already in loyalty.py:     @commands.command(name="topwatchtime", aliases=["topwt"])
# DISABLED - already in loyalty.py:     async def top_watchtime(self, ctx: Context, count: str = "5") -> None:
# DISABLED - already in loyalty.py:         """
# DISABLED - already in loyalty.py:         Show top watchers by watch time.
# DISABLED - already in loyalty.py: 
# DISABLED - already in loyalty.py:         Usage: !topwatchtime or !topwatchtime <count>
# DISABLED - already in loyalty.py:         """
# DISABLED - already in loyalty.py:         channel_name = ctx.channel.name
# DISABLED - already in loyalty.py: 
# DISABLED - already in loyalty.py:         try:
# DISABLED - already in loyalty.py:             limit = min(int(count), 10)
# DISABLED - already in loyalty.py:             if limit < 1:
# DISABLED - already in loyalty.py:                 limit = 5
# DISABLED - already in loyalty.py:         except ValueError:
# DISABLED - already in loyalty.py:             limit = 5
# DISABLED - already in loyalty.py: 
# DISABLED - already in loyalty.py:         # Query top watchers by watch time
# DISABLED - already in loyalty.py:         with self.db.get_connection() as conn:
# DISABLED - already in loyalty.py:             cursor = conn.cursor()
# DISABLED - already in loyalty.py:             cursor.execute(
# DISABLED - already in loyalty.py:                 """
# DISABLED - already in loyalty.py:                 SELECT username, watch_time_minutes
# DISABLED - already in loyalty.py:                 FROM user_loyalty
# DISABLED - already in loyalty.py:                 WHERE channel = ? AND watch_time_minutes > 0
# DISABLED - already in loyalty.py:                 ORDER BY watch_time_minutes DESC
# DISABLED - already in loyalty.py:                 LIMIT ?
# DISABLED - already in loyalty.py:                 """,
# DISABLED - already in loyalty.py:                 (channel_name, limit),
# DISABLED - already in loyalty.py:             )
# DISABLED - already in loyalty.py:             rows = cursor.fetchall()
# DISABLED - already in loyalty.py: 
# DISABLED - already in loyalty.py:         if not rows:
# DISABLED - already in loyalty.py:             await ctx.send(f"@{ctx.author.name} No watchtime data yet.")
# DISABLED - already in loyalty.py:             return
# DISABLED - already in loyalty.py: 
# DISABLED - already in loyalty.py:         entries = []
# DISABLED - already in loyalty.py:         for i, row in enumerate(rows, 1):
# DISABLED - already in loyalty.py:             username = row["username"] or "Unknown"
# DISABLED - already in loyalty.py:             watch_time = row["watch_time_minutes"]
# DISABLED - already in loyalty.py:             formatted_time = self._format_watchtime(watch_time)
# DISABLED - already in loyalty.py:             entries.append(f"{i}. {username}: {formatted_time}")
# DISABLED - already in loyalty.py: 
# DISABLED - already in loyalty.py:         await ctx.send(f"Top watchers: " + " | ".join(entries))
# DISABLED - already in loyalty.py: 
# DISABLED - already in loyalty.py:     # ==================== First-time Chatter Commands ====================

    @commands.command(name="welcomeset")
    @is_owner()
    async def welcome_settings(self, ctx: Context, action: str = "", *, value: str = "") -> None:
        """
        Configure first-time chatter welcome settings.

        Usage:
            !welcomeset status - Show current settings
            !welcomeset on/off - Enable/disable welcome messages
            !welcomeset message <message> - Set welcome message
        """
        channel_name = ctx.channel.name
        settings = self._get_first_chatter_settings(channel_name)
        action = action.lower()

        if action in ("", "status"):
            status = "ENABLED" if settings.enabled else "DISABLED"
            await ctx.send(
                f"@{ctx.author.name} Welcome messages: {status} | "
                f"Message: {settings.message}"
            )
            return

        if action == "on":
            settings.enabled = True
            self._save_first_chatter_settings(settings)
            await ctx.send(f"@{ctx.author.name} Welcome messages ENABLED!")
            return

        if action == "off":
            settings.enabled = False
            self._save_first_chatter_settings(settings)
            await ctx.send(f"@{ctx.author.name} Welcome messages DISABLED.")
            return

        if action == "message":
            if not value:
                await ctx.send(
                    f"@{ctx.author.name} Current message: {settings.message}"
                )
                return
            settings.message = value
            self._save_first_chatter_settings(settings)
            await ctx.send(f"@{ctx.author.name} Welcome message updated!")
            return

        await ctx.send(
            f"@{ctx.author.name} Usage: !welcomeset <status/on/off/message>"
        )

    # ==================== Event Handlers ====================

    @commands.Cog.event()
    async def event_message(self, message: Message) -> None:
        """Handle incoming messages for first-time chatter detection."""
        if message.echo or not message.author or not message.channel:
            return

        channel_name = message.channel.name.lower()
        user_id = str(message.author.id)
        username = message.author.name

        # Check if first-time chatter detection is enabled
        settings = self._get_first_chatter_settings(channel_name)
        if not settings.enabled:
            return

        # Check if user is already known
        if channel_name not in self._known_chatters:
            self._known_chatters[channel_name] = set()

        if user_id in self._known_chatters[channel_name]:
            return

        # New chatter detected - add to known chatters
        self._known_chatters[channel_name].add(user_id)

        # Save to database
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO known_chatters (channel, user_id, username)
                VALUES (?, ?, ?)
                """,
                (channel_name, user_id, username),
            )

        # Send welcome message
        welcome_message = self._parse_welcome_variables(settings.message, username)

        channel = self.bot.get_channel(channel_name)
        if channel:
            await channel.send(welcome_message)
            logger.info("Welcomed first-time chatter %s in %s", username, channel_name)

    @commands.Cog.event()
    async def event_raw_usernotice(self, channel, tags: dict[str, Any]) -> None:
        """Handle raw usernotice events for raid detection."""
        msg_id = tags.get("msg-id", "")

        if msg_id != "raid":
            return

        channel_name = channel.name if hasattr(channel, "name") else str(channel)
        channel_name = channel_name.lower()

        # Check if auto-shoutout on raid is enabled
        settings = self._get_shoutout_settings(channel_name)
        if not settings.enabled or not settings.auto_raid_shoutout:
            return

        # Get raider info
        raider = tags.get("msg-param-displayName", tags.get("display-name", ""))
        raider_login = tags.get("msg-param-login", tags.get("login", raider.lower()))
        viewer_count = tags.get("msg-param-viewerCount", "0")

        if not raider:
            return

        # Check cooldown
        on_cooldown, remaining = self._check_shoutout_cooldown(channel_name, raider_login)
        if on_cooldown:
            logger.debug(
                "Auto-shoutout for raider %s on cooldown (%ds remaining)",
                raider_login,
                remaining,
            )
            return

        # Fetch last game
        last_game = await self._get_last_game(raider_login)

        # Parse and send message
        message = self._parse_shoutout_variables(
            settings.message,
            user=raider,
            game=last_game,
            channel=channel_name,
        )

        # Get channel object and send
        channel_obj = self.bot.get_channel(channel_name)
        if channel_obj:
            await channel_obj.send(message)

            # Update cooldown and log
            self._update_shoutout_cooldown(channel_name, raider_login)
            self._log_shoutout(channel_name, raider_login, "AUTO_RAID", was_raid=True)

            logger.info(
                "Auto-shoutout to raider %s (%s viewers) in %s",
                raider,
                viewer_count,
                channel_name,
            )

    # ==================== Shoutout History Command ====================

    @commands.command(name="sohistory")
    @is_moderator()
    async def shoutout_history(self, ctx: Context, username: str = "") -> None:
        """
        View recent shoutout history.

        Usage: !sohistory or !sohistory <username>
        """
        channel_name = ctx.channel.name

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            if username:
                target = username.lstrip("@").lower()
                cursor.execute(
                    """
                    SELECT target_user, shouted_by, shouted_at, was_raid
                    FROM shoutout_history
                    WHERE channel = ? AND target_user = ?
                    ORDER BY shouted_at DESC
                    LIMIT 5
                    """,
                    (channel_name, target),
                )
            else:
                cursor.execute(
                    """
                    SELECT target_user, shouted_by, shouted_at, was_raid
                    FROM shoutout_history
                    WHERE channel = ?
                    ORDER BY shouted_at DESC
                    LIMIT 5
                    """,
                    (channel_name,),
                )

            rows = cursor.fetchall()

        if not rows:
            await ctx.send(f"@{ctx.author.name} No shoutout history found.")
            return

        entries = []
        for row in rows:
            target = row["target_user"]
            by = row["shouted_by"]
            was_raid = row["was_raid"]
            raid_tag = " (raid)" if was_raid else ""
            entries.append(f"{target} by {by}{raid_tag}")

        await ctx.send(f"@{ctx.author.name} Recent shoutouts: " + " | ".join(entries))


def prepare(bot: TwitchBot) -> None:
    """Prepare the cog for loading."""
    bot.add_cog(ShoutoutCog(bot))
