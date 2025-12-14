"""
Song Request cog for Twitch bot.

Provides a complete song request system with:
- YouTube URL parsing and search
- Queue management
- User request limits (different for subs)
- Duration limits
- Blacklist songs/channels
- Volume control

Note: Actual audio playback is handled by dashboard/OBS.
The bot only manages the queue and settings.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import urllib.parse
from typing import TYPE_CHECKING, Optional, Any

from twitchio.ext import commands
from twitchio.ext.commands import Context

from bot.utils.database import get_database, DatabaseManager
from bot.utils.logging import get_logger
from bot.utils.permissions import is_moderator, is_owner

if TYPE_CHECKING:
    from twitchio import Message
    from bot.bot import TwitchBot

logger = get_logger(__name__)


# ==================== YouTube Helper Functions ====================

def extract_video_id(query: str) -> Optional[str]:
    """
    Extract YouTube video ID from URL.
    
    Args:
        query: URL or search query
        
    Returns:
        Video ID if found, None otherwise
    """
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
        r'youtube\.com/v/([a-zA-Z0-9_-]{11})',
        r'youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, query)
        if match:
            return match.group(1)
    
    return None


def normalize_video_id(url_or_id: str) -> Optional[str]:
    """
    Bug 5 FIX: Normalize video ID from any YouTube URL format.
    
    This ensures blacklist checks work regardless of URL format:
    - youtube.com/watch?v=XXX
    - youtu.be/XXX
    - youtube.com/embed/XXX
    - youtube.com/v/XXX
    - youtube.com/shorts/XXX
    - With or without www
    - With various query parameters
    
    Returns:
        The 11-character video ID, or None if not found
    """
    # If it looks like just an ID (11 chars, valid characters), return it
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url_or_id):
        return url_or_id
    
    # Otherwise extract from URL
    return extract_video_id(url_or_id)


def get_youtube_info(query: str) -> Optional[dict[str, Any]]:
    """
    Get YouTube video info from URL or search query.
    
    Uses oEmbed API (no API key required) for URL lookups.
    
    Args:
        query: YouTube URL or search query
        
    Returns:
        Dict with video_id, title, duration_seconds or None if not found
    """
    video_id = extract_video_id(query)
    
    if video_id:
        # Get video info using oEmbed (no API key needed)
        try:
            url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
                return {
                    "video_id": video_id,
                    "title": data.get("title", "Unknown"),
                    "author_name": data.get("author_name", "Unknown"),
                    "duration_seconds": 0,  # oEmbed doesn't provide duration
                }
        except urllib.error.HTTPError as e:
            logger.warning("YouTube oEmbed error for %s: %s", video_id, e)
            return None
        except Exception as e:
            logger.error("Error fetching YouTube info: %s", e)
            return None
    
    # Search functionality would require YouTube Data API
    # For now, return None for search queries
    logger.debug("Search queries not supported without YouTube API key")
    return None


def format_duration(seconds: int) -> str:
    """Format duration in seconds to MM:SS or HH:MM:SS."""
    if seconds <= 0:
        return "Unknown"
    
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class SongRequests(commands.Cog):
    """
    Song Request cog for viewer music requests.
    
    Features:
    - Request songs via YouTube URL
    - Queue management
    - User limits (different for subs)
    - Blacklist songs/channels
    - Mod controls (skip, clear, volume)
    """
    
    def __init__(self, bot: TwitchBot) -> None:
        """Initialize the song requests cog."""
        self.bot = bot
        self.db: DatabaseManager = get_database()
        self._init_sr_tables()
        logger.info("SongRequests cog initialized")
    
    def _init_sr_tables(self) -> None:
        """Initialize song request database tables."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Song request settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS songrequest_settings (
                    channel TEXT PRIMARY KEY,
                    enabled BOOLEAN DEFAULT FALSE,
                    max_queue_size INTEGER DEFAULT 50,
                    max_duration_seconds INTEGER DEFAULT 600,
                    user_limit INTEGER DEFAULT 3,
                    sub_limit INTEGER DEFAULT 5,
                    volume INTEGER DEFAULT 50,
                    allow_youtube BOOLEAN DEFAULT TRUE,
                    allow_soundcloud BOOLEAN DEFAULT FALSE
                )
            """)
            
            # Song queue table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS song_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    duration_seconds INTEGER DEFAULT 0,
                    requested_by TEXT NOT NULL,
                    requested_by_id TEXT NOT NULL,
                    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'queued',
                    played_at TIMESTAMP
                )
            """)
            
            # Song blacklist table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS song_blacklist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    video_id TEXT,
                    channel_id TEXT,
                    reason TEXT,
                    added_by TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Song history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS song_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_song_queue_channel_status
                ON song_queue(channel, status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_song_blacklist_channel
                ON song_blacklist(channel)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_song_history_channel
                ON song_history(channel)
            """)
            
            logger.info("Song request tables initialized")
    
    # ==================== Database Methods ====================
    
    def get_sr_settings(self, channel: str) -> dict[str, Any]:
        """Get song request settings for a channel."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM songrequest_settings WHERE channel = ?",
                (channel.lower(),)
            )
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            
            # Return defaults
            return {
                "channel": channel.lower(),
                "enabled": False,
                "max_queue_size": 50,
                "max_duration_seconds": 600,
                "user_limit": 3,
                "sub_limit": 5,
                "volume": 50,
                "allow_youtube": True,
                "allow_soundcloud": False
            }
    
    def update_sr_settings(self, channel: str, **kwargs: Any) -> None:
        """Update song request settings for a channel."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            current = self.get_sr_settings(channel)
            
            # Merge with current settings
            for key, value in kwargs.items():
                if key in current and value is not None:
                    current[key] = value
            
            cursor.execute("""
                INSERT INTO songrequest_settings 
                (channel, enabled, max_queue_size, max_duration_seconds, user_limit, sub_limit, volume, allow_youtube, allow_soundcloud)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel) DO UPDATE SET
                    enabled = excluded.enabled,
                    max_queue_size = excluded.max_queue_size,
                    max_duration_seconds = excluded.max_duration_seconds,
                    user_limit = excluded.user_limit,
                    sub_limit = excluded.sub_limit,
                    volume = excluded.volume,
                    allow_youtube = excluded.allow_youtube,
                    allow_soundcloud = excluded.allow_soundcloud
            """, (
                current["channel"], current["enabled"], current["max_queue_size"],
                current["max_duration_seconds"], current["user_limit"], current["sub_limit"],
                current["volume"], current["allow_youtube"], current["allow_soundcloud"]
            ))
    
    def add_to_queue(
        self,
        channel: str,
        video_id: str,
        title: str,
        duration: int,
        requested_by: str,
        requested_by_id: str
    ) -> int:
        """Add a song to the queue. Returns the song ID."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO song_queue (channel, video_id, title, duration_seconds, requested_by, requested_by_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (channel.lower(), video_id, title, duration, requested_by, requested_by_id))
            return cursor.lastrowid or 0
    
    def get_queue(self, channel: str) -> list[dict[str, Any]]:
        """Get all queued songs for a channel."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM song_queue 
                WHERE channel = ? AND status IN ('queued', 'playing')
                ORDER BY 
                    CASE status WHEN 'playing' THEN 0 ELSE 1 END,
                    requested_at ASC
            """, (channel.lower(),))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_queue_position(self, channel: str, song_id: int) -> int:
        """Get position of a song in the queue (1-indexed)."""
        queue = self.get_queue(channel)
        for i, song in enumerate(queue, 1):
            if song["id"] == song_id:
                return i
        return 0
    
    def get_current_song(self, channel: str) -> Optional[dict[str, Any]]:
        """Get the currently playing song."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM song_queue 
                WHERE channel = ? AND status = 'playing'
                LIMIT 1
            """, (channel.lower(),))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_next_song(self, channel: str) -> Optional[dict[str, Any]]:
        """Get the next song in queue."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM song_queue 
                WHERE channel = ? AND status = 'queued'
                ORDER BY requested_at ASC
                LIMIT 1
            """, (channel.lower(),))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def mark_song_playing(self, song_id: int) -> None:
        """Mark a song as currently playing."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE song_queue 
                SET status = 'playing', played_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (song_id,))
    
    def mark_song_played(self, song_id: int) -> None:
        """Mark a song as played and add to history."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get song info first
            cursor.execute("SELECT * FROM song_queue WHERE id = ?", (song_id,))
            song = cursor.fetchone()
            
            if song:
                # Add to history
                cursor.execute("""
                    INSERT INTO song_history (channel, video_id, title, requested_by)
                    VALUES (?, ?, ?, ?)
                """, (song["channel"], song["video_id"], song["title"], song["requested_by"]))
                
                # Update status
                cursor.execute("""
                    UPDATE song_queue SET status = 'played' WHERE id = ?
                """, (song_id,))
    
    def skip_song(self, song_id: int) -> None:
        """Skip a song (mark as skipped)."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE song_queue SET status = 'skipped' WHERE id = ?
            """, (song_id,))
    
    def remove_from_queue(self, song_id: int) -> bool:
        """Remove a song from the queue."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM song_queue WHERE id = ? AND status = 'queued'
            """, (song_id,))
            return cursor.rowcount > 0
    
    def clear_queue(self, channel: str) -> int:
        """Clear all queued songs for a channel. Returns count removed."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM song_queue WHERE channel = ? AND status = 'queued'
            """, (channel.lower(),))
            return cursor.rowcount
    
    def get_user_queue_count(self, channel: str, user_id: str) -> int:
        """Get number of songs a user has in queue."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) as count FROM song_queue 
                WHERE channel = ? AND requested_by_id = ? AND status = 'queued'
            """, (channel.lower(), user_id))
            row = cursor.fetchone()
            return row["count"] if row else 0
    
    def get_user_last_request(self, channel: str, user_id: str) -> Optional[dict[str, Any]]:
        """Get user's most recent queued song."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM song_queue 
                WHERE channel = ? AND requested_by_id = ? AND status = 'queued'
                ORDER BY requested_at DESC
                LIMIT 1
            """, (channel.lower(), user_id))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def is_song_blacklisted(self, channel: str, video_id: str) -> bool:
        """Check if a song is blacklisted.
        
        Bug 5 FIX: Normalizes video ID before checking to prevent bypass
        via different URL formats (youtu.be vs youtube.com, etc.)
        """
        # Normalize the video ID to handle different URL formats
        normalized_id = normalize_video_id(video_id) if video_id else None
        if not normalized_id:
            return False
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 1 FROM song_blacklist 
                WHERE channel = ? AND video_id = ?
            """, (channel.lower(), normalized_id))
            return cursor.fetchone() is not None
    
    def add_to_blacklist(
        self,
        channel: str,
        video_id: Optional[str],
        channel_id: Optional[str],
        reason: Optional[str],
        added_by: str
    ) -> None:
        """Add a song or channel to the blacklist."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO song_blacklist (channel, video_id, channel_id, reason, added_by)
                VALUES (?, ?, ?, ?, ?)
            """, (channel.lower(), video_id, channel_id, reason, added_by))
    
    def remove_from_blacklist(self, channel: str, video_id: str) -> bool:
        """Remove a song from the blacklist."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM song_blacklist WHERE channel = ? AND video_id = ?
            """, (channel.lower(), video_id))
            return cursor.rowcount > 0
    
    # ==================== Commands ====================
    
    @commands.command(name="sr", aliases=["songrequest", "request"])
    async def song_request(self, ctx: Context, *, query: str = "") -> None:
        """
        Request a song or toggle song requests.
        
        Usage: 
            !sr <youtube url> - Request a song
            !sr on/off - Enable/disable song requests (mod only)
        """
        channel_name = ctx.channel.name
        settings = self.get_sr_settings(channel_name)
        
        # Check for mod commands
        if query.lower() in ("on", "off"):
            # Check if user is mod
            is_mod = ctx.author.is_mod or ctx.author.is_broadcaster
            owner = getattr(self.bot.config, "owner", "").lower()
            is_owner_user = ctx.author.name.lower() == owner
            
            if not (is_mod or is_owner_user):
                await ctx.send(f"@{ctx.author.name} Only moderators can toggle song requests.")
                return
            
            enabled = query.lower() == "on"
            self.update_sr_settings(channel_name, enabled=enabled)
            status = "ENABLED" if enabled else "DISABLED"
            await ctx.send(f"@{ctx.author.name} Song requests are now {status}!")
            logger.info("Song requests %s for %s by %s", status, channel_name, ctx.author.name)
            return
        
        # Check if song requests are enabled
        if not settings.get("enabled", False):
            await ctx.send(f"@{ctx.author.name} Song requests are currently disabled.")
            return
        
        # Check if query provided
        if not query:
            await ctx.send(f"@{ctx.author.name} Usage: !sr <youtube url>")
            return
        
        # Get video info
        video_info = get_youtube_info(query)
        if not video_info:
            await ctx.send(f"@{ctx.author.name} Could not find that video. Please use a valid YouTube URL.")
            return
        
        video_id = video_info["video_id"]
        title = video_info["title"]
        duration = video_info.get("duration_seconds", 0)
        
        # Check if blacklisted
        if self.is_song_blacklisted(channel_name, video_id):
            await ctx.send(f"@{ctx.author.name} That song is blacklisted.")
            return
        
        # Check duration limit
        max_duration = settings.get("max_duration_seconds", 600)
        if duration > 0 and duration > max_duration:
            await ctx.send(
                f"@{ctx.author.name} Song is too long. Max duration: {format_duration(max_duration)}"
            )
            return
        
        # Check queue size
        queue = self.get_queue(channel_name)
        max_queue = settings.get("max_queue_size", 50)
        if len(queue) >= max_queue:
            await ctx.send(f"@{ctx.author.name} The queue is full ({max_queue} songs max).")
            return
        
        # Check user limit
        user_id = str(ctx.author.id)
        user_count = self.get_user_queue_count(channel_name, user_id)
        
        is_subscriber = getattr(ctx.author, "is_subscriber", False)
        user_limit = settings.get("sub_limit", 5) if is_subscriber else settings.get("user_limit", 3)
        
        if user_count >= user_limit:
            await ctx.send(
                f"@{ctx.author.name} You already have {user_count} song(s) in queue. "
                f"Max: {user_limit}"
            )
            return
        
        # Check if song already in queue
        for song in queue:
            if song["video_id"] == video_id:
                await ctx.send(f"@{ctx.author.name} That song is already in the queue.")
                return
        
        # Add to queue
        song_id = self.add_to_queue(
            channel=channel_name,
            video_id=video_id,
            title=title,
            duration=duration,
            requested_by=ctx.author.name,
            requested_by_id=user_id
        )
        
        position = self.get_queue_position(channel_name, song_id)
        
        # Truncate title if too long
        display_title = title[:50] + "..." if len(title) > 50 else title
        
        await ctx.send(
            f"@{ctx.author.name} Added to queue (#{position}): \"{display_title}\""
        )
        logger.info(
            "Song requested by %s in %s: %s (%s)",
            ctx.author.name, channel_name, title, video_id
        )
    
    @commands.command(name="queue", aliases=["songlist", "sl", "songs"])
    async def show_queue(self, ctx: Context) -> None:
        """Show the current song queue."""
        channel_name = ctx.channel.name
        settings = self.get_sr_settings(channel_name)
        
        if not settings.get("enabled", False):
            await ctx.send(f"@{ctx.author.name} Song requests are currently disabled.")
            return
        
        queue = self.get_queue(channel_name)
        
        if not queue:
            await ctx.send(f"@{ctx.author.name} The queue is empty.")
            return
        
        # Build queue message (show first 5)
        entries = []
        for i, song in enumerate(queue[:5], 1):
            title = song["title"][:30] + "..." if len(song["title"]) > 30 else song["title"]
            status = " [NOW]" if song["status"] == "playing" else ""
            entries.append(f"{i}. {title}{status}")
        
        total = len(queue)
        more = f" (+{total - 5} more)" if total > 5 else ""
        
        await ctx.send(f"Queue ({total}): " + " | ".join(entries) + more)
    
    @commands.command(name="currentsong", aliases=["song", "nowplaying", "np"])
    async def current_song(self, ctx: Context) -> None:
        """Show the currently playing song."""
        channel_name = ctx.channel.name
        settings = self.get_sr_settings(channel_name)
        
        if not settings.get("enabled", False):
            await ctx.send(f"@{ctx.author.name} Song requests are currently disabled.")
            return
        
        current = self.get_current_song(channel_name)
        
        if not current:
            # Check if there's anything in queue
            next_song = self.get_next_song(channel_name)
            if next_song:
                await ctx.send(f"@{ctx.author.name} No song playing. Next up: \"{next_song['title']}\"")
            else:
                await ctx.send(f"@{ctx.author.name} No song currently playing and queue is empty.")
            return
        
        title = current["title"]
        requester = current["requested_by"]
        
        await ctx.send(f"Now playing: \"{title}\" requested by @{requester}")
    
    @commands.command(name="skip", aliases=["skipsong", "nextsong"])
    @is_moderator()
    async def skip_current(self, ctx: Context) -> None:
        """Skip the current song (mod only)."""
        channel_name = ctx.channel.name
        
        current = self.get_current_song(channel_name)
        if not current:
            await ctx.send(f"@{ctx.author.name} No song is currently playing.")
            return
        
        self.skip_song(current["id"])
        
        # Get next song
        next_song = self.get_next_song(channel_name)
        if next_song:
            self.mark_song_playing(next_song["id"])
            await ctx.send(f"@{ctx.author.name} Skipped. Now playing: \"{next_song['title']}\"")
        else:
            await ctx.send(f"@{ctx.author.name} Skipped. Queue is now empty.")
        
        logger.info("Song skipped by %s in %s", ctx.author.name, channel_name)
    
    @commands.command(name="volume", aliases=["vol"])
    @is_moderator()
    async def set_volume(self, ctx: Context, level: str = "") -> None:
        """Set or check the volume level (mod only). Usage: !volume [0-100]"""
        channel_name = ctx.channel.name
        settings = self.get_sr_settings(channel_name)
        
        if not level:
            current_vol = settings.get("volume", 50)
            await ctx.send(f"@{ctx.author.name} Current volume: {current_vol}%")
            return
        
        try:
            new_vol = int(level)
            if not 0 <= new_vol <= 100:
                raise ValueError("Volume out of range")
        except ValueError:
            await ctx.send(f"@{ctx.author.name} Volume must be a number between 0 and 100.")
            return
        
        self.update_sr_settings(channel_name, volume=new_vol)
        await ctx.send(f"@{ctx.author.name} Volume set to {new_vol}%")
        logger.info("Volume set to %d by %s in %s", new_vol, ctx.author.name, channel_name)
    
    @commands.command(name="wrongsong", aliases=["removesong", "oops"])
    async def wrong_song(self, ctx: Context) -> None:
        """Remove your last song request from the queue."""
        channel_name = ctx.channel.name
        user_id = str(ctx.author.id)
        
        last_request = self.get_user_last_request(channel_name, user_id)
        
        if not last_request:
            await ctx.send(f"@{ctx.author.name} You don't have any songs in the queue.")
            return
        
        if self.remove_from_queue(last_request["id"]):
            title = last_request["title"][:40] + "..." if len(last_request["title"]) > 40 else last_request["title"]
            await ctx.send(f"@{ctx.author.name} Removed \"{title}\" from the queue.")
            logger.info("Song removed by %s in %s: %s", ctx.author.name, channel_name, last_request["title"])
        else:
            await ctx.send(f"@{ctx.author.name} Could not remove your song.")
    
    @commands.command(name="clearqueue", aliases=["clearq", "cq"])
    @is_moderator()
    async def clear_queue_cmd(self, ctx: Context) -> None:
        """Clear the entire song queue (mod only)."""
        channel_name = ctx.channel.name
        
        count = self.clear_queue(channel_name)
        
        if count > 0:
            await ctx.send(f"@{ctx.author.name} Cleared {count} song(s) from the queue.")
            logger.info("Queue cleared by %s in %s: %d songs", ctx.author.name, channel_name, count)
        else:
            await ctx.send(f"@{ctx.author.name} The queue is already empty.")
    
    @commands.command(name="blacklist", aliases=["bl", "bansong"])
    @is_moderator()
    async def blacklist_song(self, ctx: Context, *, query: str = "") -> None:
        """Blacklist a song (mod only). Usage: !blacklist <youtube url>"""
        channel_name = ctx.channel.name
        
        if not query:
            await ctx.send(f"@{ctx.author.name} Usage: !blacklist <youtube url>")
            return
        
        video_id = extract_video_id(query)
        if not video_id:
            await ctx.send(f"@{ctx.author.name} Please provide a valid YouTube URL.")
            return
        
        # Check if already blacklisted
        if self.is_song_blacklisted(channel_name, video_id):
            await ctx.send(f"@{ctx.author.name} That song is already blacklisted.")
            return
        
        # Get video info for logging
        video_info = get_youtube_info(query)
        title = video_info["title"] if video_info else "Unknown"
        
        self.add_to_blacklist(
            channel=channel_name,
            video_id=video_id,
            channel_id=None,
            reason="Blacklisted by moderator",
            added_by=ctx.author.name
        )
        
        # Remove from queue if present
        queue = self.get_queue(channel_name)
        for song in queue:
            if song["video_id"] == video_id:
                self.remove_from_queue(song["id"])
        
        await ctx.send(f"@{ctx.author.name} Blacklisted: \"{title}\"")
        logger.info("Song blacklisted by %s in %s: %s (%s)", ctx.author.name, channel_name, title, video_id)
    
    @commands.command(name="unblacklist", aliases=["ubl", "unbansong"])
    @is_moderator()
    async def unblacklist_song(self, ctx: Context, *, query: str = "") -> None:
        """Remove a song from the blacklist (mod only). Usage: !unblacklist <youtube url>"""
        channel_name = ctx.channel.name
        
        if not query:
            await ctx.send(f"@{ctx.author.name} Usage: !unblacklist <youtube url>")
            return
        
        video_id = extract_video_id(query)
        if not video_id:
            await ctx.send(f"@{ctx.author.name} Please provide a valid YouTube URL.")
            return
        
        if self.remove_from_blacklist(channel_name, video_id):
            await ctx.send(f"@{ctx.author.name} Removed from blacklist.")
            logger.info("Song unblacklisted by %s in %s: %s", ctx.author.name, channel_name, video_id)
        else:
            await ctx.send(f"@{ctx.author.name} That song is not blacklisted.")
    
    @commands.command(name="srset", aliases=["srsettings"])
    @is_owner()
    async def sr_settings(self, ctx: Context, setting: str = "", value: str = "") -> None:
        """
        Configure song request settings (owner only).
        
        Usage:
            !srset - Show current settings
            !srset maxqueue <number> - Set max queue size
            !srset maxduration <seconds> - Set max song duration
            !srset userlimit <number> - Set requests per user
            !srset sublimit <number> - Set requests per subscriber
        """
        channel_name = ctx.channel.name
        settings = self.get_sr_settings(channel_name)
        
        if not setting:
            # Show current settings
            status = "ENABLED" if settings["enabled"] else "DISABLED"
            await ctx.send(
                f"Song Requests: {status} | "
                f"Queue: {settings['max_queue_size']} max | "
                f"Duration: {format_duration(settings['max_duration_seconds'])} max | "
                f"Limits: {settings['user_limit']}/{settings['sub_limit']} (user/sub) | "
                f"Volume: {settings['volume']}%"
            )
            return
        
        setting = setting.lower()
        
        if not value:
            await ctx.send(f"@{ctx.author.name} Please provide a value. Usage: !srset {setting} <value>")
            return
        
        try:
            if setting == "maxqueue":
                val = int(value)
                if not 1 <= val <= 200:
                    raise ValueError("Out of range")
                self.update_sr_settings(channel_name, max_queue_size=val)
                await ctx.send(f"@{ctx.author.name} Max queue size set to {val}")
                
            elif setting == "maxduration":
                val = int(value)
                if not 60 <= val <= 3600:
                    raise ValueError("Out of range (60-3600)")
                self.update_sr_settings(channel_name, max_duration_seconds=val)
                await ctx.send(f"@{ctx.author.name} Max duration set to {format_duration(val)}")
                
            elif setting == "userlimit":
                val = int(value)
                if not 1 <= val <= 20:
                    raise ValueError("Out of range")
                self.update_sr_settings(channel_name, user_limit=val)
                await ctx.send(f"@{ctx.author.name} User limit set to {val}")
                
            elif setting == "sublimit":
                val = int(value)
                if not 1 <= val <= 50:
                    raise ValueError("Out of range")
                self.update_sr_settings(channel_name, sub_limit=val)
                await ctx.send(f"@{ctx.author.name} Subscriber limit set to {val}")
                
            else:
                await ctx.send(
                    f"@{ctx.author.name} Unknown setting. Options: maxqueue, maxduration, userlimit, sublimit"
                )
                
        except ValueError as e:
            await ctx.send(f"@{ctx.author.name} Invalid value: {e}")
    
    @commands.command(name="promote", aliases=["bump"])
    @is_moderator()
    async def promote_song(self, ctx: Context, position: str = "") -> None:
        """Move a song to the front of the queue (mod only). Usage: !promote <position>"""
        channel_name = ctx.channel.name
        
        if not position:
            await ctx.send(f"@{ctx.author.name} Usage: !promote <queue position>")
            return
        
        try:
            pos = int(position)
            if pos < 2:
                await ctx.send(f"@{ctx.author.name} Position must be 2 or higher.")
                return
        except ValueError:
            await ctx.send(f"@{ctx.author.name} Please provide a valid position number.")
            return
        
        queue = self.get_queue(channel_name)
        
        # Filter out currently playing
        queued_songs = [s for s in queue if s["status"] == "queued"]
        
        if pos > len(queued_songs):
            await ctx.send(f"@{ctx.author.name} Position {pos} doesn't exist. Queue has {len(queued_songs)} songs.")
            return
        
        # Get the song to promote (1-indexed)
        song = queued_songs[pos - 1]
        
        # Update its timestamp to be before all others
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE song_queue 
                SET requested_at = datetime('now', '-1 hour')
                WHERE id = ?
            """, (song["id"],))
        
        title = song["title"][:40] + "..." if len(song["title"]) > 40 else song["title"]
        await ctx.send(f"@{ctx.author.name} Promoted \"{title}\" to the front of the queue.")
        logger.info("Song promoted by %s in %s: %s", ctx.author.name, channel_name, song["title"])
    
    @commands.command(name="play")
    @is_moderator()
    async def play_next(self, ctx: Context) -> None:
        """Start playing the next song in queue (mod only)."""
        channel_name = ctx.channel.name
        
        # Mark current as played if exists
        current = self.get_current_song(channel_name)
        if current:
            self.mark_song_played(current["id"])
        
        # Get and play next
        next_song = self.get_next_song(channel_name)
        if next_song:
            self.mark_song_playing(next_song["id"])
            await ctx.send(f"Now playing: \"{next_song['title']}\" requested by @{next_song['requested_by']}")
        else:
            await ctx.send(f"@{ctx.author.name} Queue is empty.")


def prepare(bot: TwitchBot) -> None:
    """Prepare the cog for loading."""
    bot.add_cog(SongRequests(bot))
