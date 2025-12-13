"""
Viewer queue system cog for Twitch bot.

Provides a complete queue system for:
- Game queues (viewers can join to play with streamer)
- Multiple named queues per channel
- Subscriber priority option
- Max queue size limits
- Mod controls for picking, clearing, opening/closing

Commands use 'v' prefix (viewer queue) to avoid conflicts with song queue:
- !vqueue, !vjoin, !vleave, !vposition, etc.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from twitchio.ext import commands
from twitchio.ext.commands import Context

from bot.utils.database import get_database, DatabaseManager
from bot.utils.logging import get_logger
from bot.utils.permissions import is_moderator, cooldown, CooldownBucket

if TYPE_CHECKING:
    from bot.bot import TwitchBot

logger = get_logger(__name__)


class Queue(commands.Cog):
    """
    Viewer queue system cog.
    
    Features:
    - Multiple named queues per channel
    - Open/close queue controls
    - Max queue size limits
    - Subscriber priority (subs go to front)
    - Prevent duplicate entries
    - Pick next, random, or specific position
    - Persistent queue storage in database
    
    All commands use 'v' prefix (viewer queue) to avoid conflicts
    with the song request queue commands.
    """
    
    def __init__(self, bot: TwitchBot) -> None:
        """Initialize the queue cog."""
        self.bot = bot
        self.db: DatabaseManager = get_database()
        
        # Initialize queue tables
        self._init_queue_tables()
        
        logger.info("Queue cog initialized")
    
    def _init_queue_tables(self) -> None:
        """Initialize queue database tables."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Viewer queue table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS viewer_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    queue_name TEXT DEFAULT 'default',
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    is_subscriber BOOLEAN DEFAULT FALSE,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    picked BOOLEAN DEFAULT FALSE,
                    picked_at TIMESTAMP,
                    UNIQUE(channel, queue_name, user_id)
                )
            """)
            
            # Queue settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS queue_settings (
                    channel TEXT NOT NULL,
                    queue_name TEXT DEFAULT 'default',
                    is_open BOOLEAN DEFAULT FALSE,
                    max_size INTEGER DEFAULT 50,
                    sub_priority BOOLEAN DEFAULT FALSE,
                    PRIMARY KEY (channel, queue_name)
                )
            """)
            
            # Create indexes for performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_viewer_queue_channel_name
                ON viewer_queue(channel, queue_name)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_viewer_queue_picked
                ON viewer_queue(channel, queue_name, picked)
            """)
            
            logger.info("Queue tables initialized")
    
    # ==================== Database Helper Methods ====================
    
    def _get_queue_settings(
        self, 
        channel: str, 
        queue_name: str = "default"
    ) -> dict:
        """Get queue settings, creating defaults if not exists."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT is_open, max_size, sub_priority
                FROM queue_settings
                WHERE channel = ? AND queue_name = ?
            """, (channel.lower(), queue_name.lower()))
            
            row = cursor.fetchone()
            if row:
                return {
                    "is_open": bool(row["is_open"]),
                    "max_size": row["max_size"],
                    "sub_priority": bool(row["sub_priority"])
                }
            
            # Create default settings
            cursor.execute("""
                INSERT INTO queue_settings (channel, queue_name, is_open, max_size, sub_priority)
                VALUES (?, ?, FALSE, 50, FALSE)
            """, (channel.lower(), queue_name.lower()))
            
            return {"is_open": False, "max_size": 50, "sub_priority": False}
    
    def _update_queue_settings(
        self,
        channel: str,
        queue_name: str = "default",
        is_open: Optional[bool] = None,
        max_size: Optional[int] = None,
        sub_priority: Optional[bool] = None
    ) -> None:
        """Update queue settings."""
        # Ensure settings exist
        self._get_queue_settings(channel, queue_name)
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            updates = []
            params = []
            
            if is_open is not None:
                updates.append("is_open = ?")
                params.append(is_open)
            if max_size is not None:
                updates.append("max_size = ?")
                params.append(max_size)
            if sub_priority is not None:
                updates.append("sub_priority = ?")
                params.append(sub_priority)
            
            if updates:
                params.extend([channel.lower(), queue_name.lower()])
                cursor.execute(f"""
                    UPDATE queue_settings
                    SET {", ".join(updates)}
                    WHERE channel = ? AND queue_name = ?
                """, params)
    
    def _get_queue_entries(
        self,
        channel: str,
        queue_name: str = "default",
        include_picked: bool = False
    ) -> list[dict]:
        """Get queue entries ordered by position."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            settings = self._get_queue_settings(channel, queue_name)
            
            # Build ORDER BY based on sub priority
            if settings["sub_priority"]:
                order_by = "is_subscriber DESC, joined_at ASC"
            else:
                order_by = "joined_at ASC"
            
            if include_picked:
                cursor.execute(f"""
                    SELECT id, user_id, username, is_subscriber, joined_at, picked, picked_at
                    FROM viewer_queue
                    WHERE channel = ? AND queue_name = ?
                    ORDER BY picked ASC, {order_by}
                """, (channel.lower(), queue_name.lower()))
            else:
                cursor.execute(f"""
                    SELECT id, user_id, username, is_subscriber, joined_at, picked, picked_at
                    FROM viewer_queue
                    WHERE channel = ? AND queue_name = ? AND picked = FALSE
                    ORDER BY {order_by}
                """, (channel.lower(), queue_name.lower()))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def _get_queue_count(
        self,
        channel: str,
        queue_name: str = "default",
        include_picked: bool = False
    ) -> int:
        """Get count of entries in queue."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            if include_picked:
                cursor.execute("""
                    SELECT COUNT(*) as count
                    FROM viewer_queue
                    WHERE channel = ? AND queue_name = ?
                """, (channel.lower(), queue_name.lower()))
            else:
                cursor.execute("""
                    SELECT COUNT(*) as count
                    FROM viewer_queue
                    WHERE channel = ? AND queue_name = ? AND picked = FALSE
                """, (channel.lower(), queue_name.lower()))
            
            return cursor.fetchone()["count"]
    
    def _add_to_queue(
        self,
        channel: str,
        queue_name: str,
        user_id: str,
        username: str,
        is_subscriber: bool
    ) -> tuple[bool, str, int]:
        """
        Add user to queue.
        
        Returns:
            tuple: (success, message, position)
        """
        settings = self._get_queue_settings(channel, queue_name)
        
        if not settings["is_open"]:
            return False, "Queue is closed.", 0
        
        # Check if already in queue
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, picked FROM viewer_queue
                WHERE channel = ? AND queue_name = ? AND user_id = ?
            """, (channel.lower(), queue_name.lower(), user_id))
            
            existing = cursor.fetchone()
            if existing:
                if existing["picked"]:
                    return False, "You were already picked!", 0
                return False, "You're already in the queue!", 0
            
            # Check max size
            current_count = self._get_queue_count(channel, queue_name)
            if current_count >= settings["max_size"]:
                return False, "Queue is full!", 0
            
            # Add to queue
            cursor.execute("""
                INSERT INTO viewer_queue (channel, queue_name, user_id, username, is_subscriber)
                VALUES (?, ?, ?, ?, ?)
            """, (channel.lower(), queue_name.lower(), user_id, username, is_subscriber))
        
        # Calculate position
        entries = self._get_queue_entries(channel, queue_name)
        position = next(
            (i + 1 for i, e in enumerate(entries) if e["user_id"] == user_id),
            len(entries)
        )
        
        return True, "Success", position
    
    def _remove_from_queue(
        self,
        channel: str,
        queue_name: str,
        user_id: str
    ) -> tuple[bool, str]:
        """Remove user from queue."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, picked FROM viewer_queue
                WHERE channel = ? AND queue_name = ? AND user_id = ?
            """, (channel.lower(), queue_name.lower(), user_id))
            
            existing = cursor.fetchone()
            if not existing:
                return False, "You're not in the queue."
            
            if existing["picked"]:
                return False, "You were already picked and can't leave."
            
            cursor.execute("""
                DELETE FROM viewer_queue
                WHERE channel = ? AND queue_name = ? AND user_id = ?
            """, (channel.lower(), queue_name.lower(), user_id))
        
        return True, "You left the queue."
    
    def _get_user_position(
        self,
        channel: str,
        queue_name: str,
        user_id: str
    ) -> tuple[int, bool]:
        """
        Get user's position in queue.
        
        Returns:
            tuple: (position, was_picked) - position is 0 if not in queue
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, picked FROM viewer_queue
                WHERE channel = ? AND queue_name = ? AND user_id = ?
            """, (channel.lower(), queue_name.lower(), user_id))
            
            existing = cursor.fetchone()
            if not existing:
                return 0, False
            
            if existing["picked"]:
                return 0, True
        
        entries = self._get_queue_entries(channel, queue_name)
        position = next(
            (i + 1 for i, e in enumerate(entries) if e["user_id"] == user_id),
            0
        )
        
        return position, False
    
    def _pick_from_queue(
        self,
        channel: str,
        queue_name: str,
        position: Optional[int] = None,
        random_pick: bool = False
    ) -> Optional[dict]:
        """
        Pick someone from the queue.
        
        Args:
            channel: Channel name
            queue_name: Queue name
            position: Specific position to pick (1-indexed), None for next
            random_pick: If True, pick randomly from queue
        
        Returns:
            dict with user info or None if queue empty
        """
        entries = self._get_queue_entries(channel, queue_name)
        
        if not entries:
            return None
        
        if random_pick:
            entry = random.choice(entries)
        elif position is not None:
            if position < 1 or position > len(entries):
                return None
            entry = entries[position - 1]
        else:
            # Pick next (first in queue)
            entry = entries[0]
        
        # Mark as picked
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE viewer_queue
                SET picked = TRUE, picked_at = ?
                WHERE id = ?
            """, (datetime.now(timezone.utc).isoformat(), entry["id"]))
        
        return entry
    
    def _clear_queue(
        self,
        channel: str,
        queue_name: str,
        picked_only: bool = False
    ) -> int:
        """
        Clear the queue.
        
        Args:
            channel: Channel name
            queue_name: Queue name
            picked_only: If True, only clear picked entries
        
        Returns:
            Number of entries cleared
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            if picked_only:
                cursor.execute("""
                    DELETE FROM viewer_queue
                    WHERE channel = ? AND queue_name = ? AND picked = TRUE
                """, (channel.lower(), queue_name.lower()))
            else:
                cursor.execute("""
                    DELETE FROM viewer_queue
                    WHERE channel = ? AND queue_name = ?
                """, (channel.lower(), queue_name.lower()))
            
            return cursor.rowcount
    
    # ==================== Commands ====================
    
    @commands.command(name="vqueue", aliases=["vq", "viewerqueue"])
    @cooldown(rate=3.0, bucket=CooldownBucket.USER)
    async def queue_status(self, ctx: Context, queue_name: str = "default") -> None:
        """
        Show current viewer queue status.
        
        Usage: !vqueue [queue_name]
        Aliases: !vq, !viewerqueue
        """
        channel = ctx.channel.name
        settings = self._get_queue_settings(channel, queue_name)
        entries = self._get_queue_entries(channel, queue_name)
        
        status = "OPEN" if settings["is_open"] else "CLOSED"
        count = len(entries)
        max_size = settings["max_size"]
        
        if count == 0:
            await ctx.send(
                f"Viewer Queue [{queue_name}] is {status} ({count}/{max_size}). "
                f"{'Type !vjoin to enter!' if settings['is_open'] else ''}"
            )
            return
        
        # Show first few entries
        display_count = min(5, count)
        names = [f"{i+1}. {e['username']}" for i, e in enumerate(entries[:display_count])]
        names_str = ", ".join(names)
        
        more = f" (+{count - display_count} more)" if count > display_count else ""
        
        await ctx.send(
            f"Viewer Queue [{queue_name}] {status} ({count}/{max_size}): {names_str}{more} | "
            f"{'!vjoin to enter' if settings['is_open'] else ''}"
        )
    
    @commands.command(name="vjoin", aliases=["vj"])
    @cooldown(rate=2.0, bucket=CooldownBucket.USER)
    async def join_queue(self, ctx: Context, queue_name: str = "default") -> None:
        """
        Join the viewer queue.
        
        Usage: !vjoin [queue_name]
        Alias: !vj
        """
        channel = ctx.channel.name
        user_id = str(ctx.author.id)
        username = ctx.author.name
        is_sub = getattr(ctx.author, "is_subscriber", False)
        
        success, message, position = self._add_to_queue(
            channel, queue_name, user_id, username, is_sub
        )
        
        if success:
            await ctx.send(f"@{username} You joined the viewer queue! Position: #{position}")
        else:
            await ctx.send(f"@{username} {message}")
    
    @commands.command(name="vleave", aliases=["vl"])
    @cooldown(rate=2.0, bucket=CooldownBucket.USER)
    async def leave_queue(self, ctx: Context, queue_name: str = "default") -> None:
        """
        Leave the viewer queue.
        
        Usage: !vleave [queue_name]
        Alias: !vl
        """
        channel = ctx.channel.name
        user_id = str(ctx.author.id)
        username = ctx.author.name
        
        success, message = self._remove_from_queue(channel, queue_name, user_id)
        await ctx.send(f"@{username} {message}")
    
    @commands.command(name="vposition", aliases=["vpos"])
    @cooldown(rate=3.0, bucket=CooldownBucket.USER)
    async def check_position(self, ctx: Context, queue_name: str = "default") -> None:
        """
        Check your position in the viewer queue.
        
        Usage: !vposition [queue_name]
        Alias: !vpos
        """
        channel = ctx.channel.name
        user_id = str(ctx.author.id)
        username = ctx.author.name
        
        position, was_picked = self._get_user_position(channel, queue_name, user_id)
        
        if was_picked:
            await ctx.send(f"@{username} You were already picked!")
        elif position > 0:
            await ctx.send(f"@{username} You are #{position} in the viewer queue.")
        else:
            await ctx.send(f"@{username} You're not in the queue. Type !vjoin to enter!")
    
    @commands.command(name="vnext")
    @is_moderator()
    async def pick_next(self, ctx: Context, queue_name: str = "default") -> None:
        """
        Pick the next person from the viewer queue.
        
        Usage: !vnext [queue_name]
        Mod only.
        """
        channel = ctx.channel.name
        entry = self._pick_from_queue(channel, queue_name)
        
        if entry:
            await ctx.send(f"@{entry['username']} - You're up! 🎮")
        else:
            await ctx.send("Viewer queue is empty!")
    
    @commands.command(name="vpick")
    @is_moderator()
    async def pick_position(self, ctx: Context, position: int, queue_name: str = "default") -> None:
        """
        Pick a specific position from the viewer queue.
        
        Usage: !vpick <position> [queue_name]
        Mod only.
        """
        channel = ctx.channel.name
        entry = self._pick_from_queue(channel, queue_name, position=position)
        
        if entry:
            await ctx.send(f"@{entry['username']} - You're up! 🎮 (picked from #{position})")
        else:
            count = self._get_queue_count(channel, queue_name)
            if count == 0:
                await ctx.send("Viewer queue is empty!")
            else:
                await ctx.send(f"Invalid position! Queue has {count} entries (1-{count}).")
    
    @commands.command(name="vrandom", aliases=["vrand"])
    @is_moderator()
    async def pick_random(self, ctx: Context, queue_name: str = "default") -> None:
        """
        Pick a random person from the viewer queue.
        
        Usage: !vrandom [queue_name]
        Alias: !vrand
        Mod only.
        """
        channel = ctx.channel.name
        entry = self._pick_from_queue(channel, queue_name, random_pick=True)
        
        if entry:
            await ctx.send(f"@{entry['username']} - You're up! 🎲 (randomly selected)")
        else:
            await ctx.send("Viewer queue is empty!")
    
    @commands.command(name="vclear", aliases=["vqclear"])
    @is_moderator()
    async def clear_queue(self, ctx: Context, queue_name: str = "default") -> None:
        """
        Clear the viewer queue.
        
        Usage: !vclear [queue_name]
        Alias: !vqclear
        Mod only.
        """
        channel = ctx.channel.name
        cleared = self._clear_queue(channel, queue_name)
        await ctx.send(f"Viewer Queue [{queue_name}] cleared! ({cleared} entries removed)")
    
    @commands.command(name="vqopen", aliases=["vopenqueue"])
    @is_moderator()
    async def open_queue(self, ctx: Context, queue_name: str = "default") -> None:
        """
        Open the viewer queue for entries.
        
        Usage: !vqopen [queue_name]
        Alias: !vopenqueue
        Mod only.
        """
        channel = ctx.channel.name
        self._update_queue_settings(channel, queue_name, is_open=True)
        await ctx.send(f"Viewer Queue [{queue_name}] is now OPEN! Type !vjoin to enter. 🎮")
    
    @commands.command(name="vqclose", aliases=["vclosequeue"])
    @is_moderator()
    async def close_queue(self, ctx: Context, queue_name: str = "default") -> None:
        """
        Close the viewer queue to new entries.
        
        Usage: !vqclose [queue_name]
        Alias: !vclosequeue
        Mod only.
        """
        channel = ctx.channel.name
        self._update_queue_settings(channel, queue_name, is_open=False)
        count = self._get_queue_count(channel, queue_name)
        await ctx.send(f"Viewer Queue [{queue_name}] is now CLOSED. ({count} in queue)")
    
    @commands.command(name="vqsize", aliases=["vsetqueuesize"])
    @is_moderator()
    async def set_queue_size(self, ctx: Context, size: int, queue_name: str = "default") -> None:
        """
        Set the maximum viewer queue size.
        
        Usage: !vqsize <size> [queue_name]
        Mod only.
        """
        if size < 1 or size > 1000:
            await ctx.send(f"@{ctx.author.name} Queue size must be between 1 and 1000.")
            return
        
        channel = ctx.channel.name
        self._update_queue_settings(channel, queue_name, max_size=size)
        await ctx.send(f"Viewer Queue [{queue_name}] max size set to {size}.")
    
    @commands.command(name="vsubpriority")
    @is_moderator()
    async def toggle_sub_priority(self, ctx: Context, enabled: str = "", queue_name: str = "default") -> None:
        """
        Toggle subscriber priority (subs go to front of viewer queue).
        
        Usage: !vsubpriority [on/off] [queue_name]
        Mod only.
        """
        channel = ctx.channel.name
        settings = self._get_queue_settings(channel, queue_name)
        
        if enabled.lower() in ("on", "true", "yes", "1"):
            new_value = True
        elif enabled.lower() in ("off", "false", "no", "0"):
            new_value = False
        else:
            # Toggle current value
            new_value = not settings["sub_priority"]
        
        self._update_queue_settings(channel, queue_name, sub_priority=new_value)
        status = "ENABLED" if new_value else "DISABLED"
        await ctx.send(f"Subscriber priority {status} for viewer queue [{queue_name}].")
    
    @commands.command(name="vqlist", aliases=["vql"])
    @is_moderator()
    async def queue_list(self, ctx: Context, queue_name: str = "default") -> None:
        """
        Show full viewer queue list (mod only, shows more detail).
        
        Usage: !vqlist [queue_name]
        Alias: !vql
        Mod only.
        """
        channel = ctx.channel.name
        settings = self._get_queue_settings(channel, queue_name)
        entries = self._get_queue_entries(channel, queue_name, include_picked=True)
        
        waiting = [e for e in entries if not e["picked"]]
        picked = [e for e in entries if e["picked"]]
        
        status = "OPEN" if settings["is_open"] else "CLOSED"
        sub_priority = "ON" if settings["sub_priority"] else "OFF"
        
        msg = f"Viewer Queue [{queue_name}] {status} | Max: {settings['max_size']} | Sub Priority: {sub_priority}"
        
        if waiting:
            names = [f"{i+1}. {e['username']}{'*' if e['is_subscriber'] else ''}" 
                     for i, e in enumerate(waiting[:10])]
            msg += f" | Waiting ({len(waiting)}): {', '.join(names)}"
            if len(waiting) > 10:
                msg += f" +{len(waiting) - 10} more"
        else:
            msg += " | Queue empty"
        
        if picked:
            msg += f" | Picked: {len(picked)}"
        
        await ctx.send(msg)
    
    @commands.command(name="vqremove", aliases=["vremove"])
    @is_moderator()
    async def remove_user(self, ctx: Context, username: str, queue_name: str = "default") -> None:
        """
        Remove a specific user from the viewer queue.
        
        Usage: !vqremove <username> [queue_name]
        Alias: !vremove
        Mod only.
        """
        channel = ctx.channel.name
        username_clean = username.lstrip("@").lower()
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM viewer_queue
                WHERE channel = ? AND queue_name = ? AND LOWER(username) = ?
            """, (channel.lower(), queue_name.lower(), username_clean))
            
            if cursor.rowcount > 0:
                await ctx.send(f"@{username_clean} removed from viewer queue [{queue_name}].")
            else:
                await ctx.send(f"@{username_clean} is not in the viewer queue.")
    
    @commands.command(name="vqclearpicked", aliases=["vclearpicked"])
    @is_moderator()
    async def clear_picked(self, ctx: Context, queue_name: str = "default") -> None:
        """
        Clear only the picked entries from the viewer queue.
        
        Usage: !vqclearpicked [queue_name]
        Alias: !vclearpicked
        Mod only.
        """
        channel = ctx.channel.name
        cleared = self._clear_queue(channel, queue_name, picked_only=True)
        await ctx.send(f"Cleared {cleared} picked entries from viewer queue [{queue_name}].")


def prepare(bot: TwitchBot) -> None:
    """Prepare the cog for loading."""
    bot.add_cog(Queue(bot))
