"""
Polls system cog for Twitch bot.

Provides both native Twitch Polls API integration and chat-based polling:
- Native Twitch Polls (requires channel:manage:polls scope)
- Chat-based polls as fallback
- Vote tracking with duplicate prevention
- Poll history and results storage
- Dashboard integration
"""

from __future__ import annotations

import asyncio
import json
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


class Polls(commands.Cog):
    """
    Polls system cog for viewer engagement.
    
    Features:
    - Native Twitch Polls API integration
    - Chat-based polls as fallback
    - Configurable duration
    - Duplicate vote prevention
    - Vote percentages display
    - Poll history tracking
    - Dashboard integration
    """
    
    def __init__(self, bot: TwitchBot) -> None:
        """Initialize the polls cog."""
        self.bot = bot
        self.db: DatabaseManager = get_database()
        
        # Track active chat polls per channel for fast lookup
        self._active_polls: dict[str, int] = {}  # {channel: poll_id}
        
        # Background task for auto-ending polls
        self._check_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Initialize database tables
        self._init_tables()
        
        logger.info("Polls cog initialized")
    
    def _init_tables(self) -> None:
        """Initialize polls database tables."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Polls table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS polls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    question TEXT NOT NULL,
                    options TEXT NOT NULL,
                    started_by TEXT NOT NULL,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ended_at TIMESTAMP,
                    duration_seconds INTEGER DEFAULT 60,
                    status TEXT DEFAULT 'active',
                    poll_type TEXT DEFAULT 'chat',
                    twitch_poll_id TEXT
                )
            """)
            
            # Poll votes table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS poll_votes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    poll_id INTEGER NOT NULL,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    option_index INTEGER NOT NULL,
                    voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(poll_id, user_id),
                    FOREIGN KEY (poll_id) REFERENCES polls(id)
                )
            """)
            
            # Poll settings table for dashboard integration
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS poll_settings (
                    channel TEXT PRIMARY KEY,
                    default_duration INTEGER DEFAULT 60,
                    allow_change_vote BOOLEAN DEFAULT FALSE,
                    show_results_during BOOLEAN DEFAULT TRUE,
                    announce_winner BOOLEAN DEFAULT TRUE,
                    min_votes_to_end INTEGER DEFAULT 1
                )
            """)
            
            # Create indexes for better query performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_polls_channel_status 
                ON polls(channel, status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_poll_votes_poll_id 
                ON poll_votes(poll_id)
            """)
            
            conn.commit()
            logger.info("Polls database tables initialized")
    
    async def cog_load(self) -> None:
        """Called when cog is loaded."""
        self._running = True
        self._check_task = asyncio.create_task(self._check_expired_polls())
        
        # Load active polls from database
        await self._load_active_polls()
        
        logger.info("Polls cog loaded, expiration checker started")
    
    async def cog_unload(self) -> None:
        """Called when cog is unloaded."""
        self._running = False
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
        logger.info("Polls cog unloaded")
    
    async def _load_active_polls(self) -> None:
        """Load active polls from database."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, channel FROM polls 
                WHERE status = 'active' AND poll_type = 'chat'
            """)
            for row in cursor.fetchall():
                self._active_polls[row["channel"].lower()] = row["id"]
    
    async def _check_expired_polls(self) -> None:
        """Background task to check for and end expired polls."""
        await self.bot.wait_until_ready()
        
        while self._running:
            try:
                expired_polls = self._get_expired_polls()
                
                for poll in expired_polls:
                    channel_name = poll["channel"]
                    poll_id = poll["id"]
                    
                    # Find the channel
                    channel = None
                    for ch in self.bot.connected_channels:
                        if ch.name.lower() == channel_name.lower():
                            channel = ch
                            break
                    
                    if channel:
                        # Auto-end the poll
                        await self._end_poll_and_announce(channel, poll_id)
                        logger.info(
                            "Auto-ended expired poll %d in %s",
                            poll_id,
                            channel_name
                        )
                    else:
                        # Just mark as ended if channel not found
                        self._mark_poll_ended(poll_id)
                        
            except Exception as e:
                logger.error("Error checking expired polls: %s", e)
            
            # Check every 5 seconds for more responsive poll endings
            await asyncio.sleep(5)
    
    def _get_expired_polls(self) -> list[dict]:
        """Get all expired but still active polls."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, channel, question, options, duration_seconds, started_at
                FROM polls 
                WHERE status = 'active' 
                AND poll_type = 'chat'
                AND datetime(started_at, '+' || duration_seconds || ' seconds') <= datetime('now')
            """)
            return [dict(row) for row in cursor.fetchall()]
    
    def _mark_poll_ended(self, poll_id: int) -> None:
        """Mark a poll as ended in the database."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE polls 
                SET status = 'ended', ended_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (poll_id,))
            conn.commit()
    
    async def _end_poll_and_announce(self, channel, poll_id: int) -> dict:
        """End a poll and announce results."""
        # Get poll details
        poll = self._get_poll_by_id(poll_id)
        if not poll:
            return {}
        
        # Get results
        results = self._get_poll_results(poll_id)
        
        # Mark poll as ended
        self._mark_poll_ended(poll_id)
        
        # Remove from active polls
        channel_name = channel.name.lower()
        if channel_name in self._active_polls:
            del self._active_polls[channel_name]
        
        # Build results message
        options = json.loads(poll["options"])
        total_votes = sum(r["votes"] for r in results)
        
        if total_votes == 0:
            await channel.send(
                f"Poll ended: \"{poll['question']}\" - No votes received! BibleThump"
            )
        else:
            # Find winner(s)
            max_votes = max(r["votes"] for r in results)
            winners = [r for r in results if r["votes"] == max_votes]
            
            if len(winners) == 1:
                winner = winners[0]
                percentage = (winner["votes"] / total_votes) * 100
                await channel.send(
                    f"Poll ended! Winner: \"{options[winner['option_index']]}\" "
                    f"with {winner['votes']} votes ({percentage:.1f}%) PogChamp"
                )
            else:
                # Tie
                winner_names = ", ".join(f"\"{options[w['option_index']]}\"" for w in winners)
                await channel.send(
                    f"Poll ended! It's a tie between {winner_names} "
                    f"with {max_votes} votes each!"
                )
        
        return {"poll": poll, "results": results, "total_votes": total_votes}
    
    def _get_poll_by_id(self, poll_id: int) -> Optional[dict]:
        """Get a poll by its ID."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM polls WHERE id = ?", (poll_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def _get_active_poll(self, channel: str) -> Optional[dict]:
        """Get the active poll for a channel."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM polls 
                WHERE channel = ? AND status = 'active'
                ORDER BY started_at DESC LIMIT 1
            """, (channel.lower(),))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def _create_poll(
        self,
        channel: str,
        question: str,
        options: list[str],
        started_by: str,
        duration_seconds: int = 60,
        poll_type: str = "chat",
        twitch_poll_id: Optional[str] = None
    ) -> int:
        """Create a new poll in the database."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO polls (channel, question, options, started_by, 
                                   duration_seconds, poll_type, twitch_poll_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                channel.lower(),
                question,
                json.dumps(options),
                started_by,
                duration_seconds,
                poll_type,
                twitch_poll_id
            ))
            conn.commit()
            return cursor.lastrowid
    
    def _add_vote(
        self,
        poll_id: int,
        user_id: str,
        username: str,
        option_index: int
    ) -> bool:
        """
        Add a vote to a poll.
        
        Returns True if vote was added, False if user already voted.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO poll_votes (poll_id, user_id, username, option_index)
                    VALUES (?, ?, ?, ?)
                """, (poll_id, user_id, username, option_index))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                # User already voted (UNIQUE constraint violation)
                return False
    
    def _get_poll_results(self, poll_id: int) -> list[dict]:
        """Get vote counts for each option in a poll."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get poll options first
            cursor.execute("SELECT options FROM polls WHERE id = ?", (poll_id,))
            row = cursor.fetchone()
            if not row:
                return []
            
            options = json.loads(row["options"])
            
            # Get vote counts per option
            cursor.execute("""
                SELECT option_index, COUNT(*) as votes
                FROM poll_votes
                WHERE poll_id = ?
                GROUP BY option_index
            """, (poll_id,))
            
            vote_counts = {row["option_index"]: row["votes"] for row in cursor.fetchall()}
            
            # Build results list with all options
            results = []
            for i, option in enumerate(options):
                results.append({
                    "option_index": i,
                    "option_text": option,
                    "votes": vote_counts.get(i, 0)
                })
            
            return results
    
    def _get_total_votes(self, poll_id: int) -> int:
        """Get total number of votes for a poll."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) as total FROM poll_votes WHERE poll_id = ?",
                (poll_id,)
            )
            return cursor.fetchone()["total"]
    
    def _get_poll_settings(self, channel: str) -> dict:
        """Get poll settings for a channel."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM poll_settings WHERE channel = ?",
                (channel.lower(),)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            # Return defaults
            return {
                "channel": channel.lower(),
                "default_duration": 60,
                "allow_change_vote": False,
                "show_results_during": True,
                "announce_winner": True,
                "min_votes_to_end": 1
            }
    
    def _get_poll_history(self, channel: str, limit: int = 10) -> list[dict]:
        """Get poll history for a channel."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM polls 
                WHERE channel = ?
                ORDER BY started_at DESC
                LIMIT ?
            """, (channel.lower(), limit))
            return [dict(row) for row in cursor.fetchall()]
    
    def _has_user_voted(self, poll_id: int, user_id: str) -> bool:
        """Check if a user has already voted in a poll."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 1 FROM poll_votes 
                WHERE poll_id = ? AND user_id = ?
            """, (poll_id, user_id))
            return cursor.fetchone() is not None
    
    # ==================== Poll Commands ====================
    
    @commands.command(name="poll")
    async def poll_command(self, ctx: Context, action: str = "", *args: str) -> None:
        """
        Poll management command.
        
        Usage:
        - !poll start "Question" "Option1" "Option2" ... [duration] - Start a poll (mod)
        - !poll end - End poll and show results (mod)
        - !poll cancel - Cancel poll without results (mod)
        - !poll results - Show current poll results
        - !poll info - Show poll information
        """
        action = action.lower()
        
        if action == "start":
            await self._poll_start(ctx, *args)
        elif action == "end":
            await self._poll_end(ctx)
        elif action == "cancel":
            await self._poll_cancel(ctx)
        elif action == "results":
            await self._poll_results(ctx)
        elif action == "info":
            await self._poll_info(ctx)
        else:
            await ctx.send(
                f"@{ctx.author.name} Poll commands: !poll start \"Question\" \"Opt1\" \"Opt2\" [duration] | "
                f"!poll end | !poll cancel | !poll results"
            )
    
    async def _poll_start(self, ctx: Context, *args: str) -> None:
        """Start a new chat-based poll."""
        # Check permissions
        if not (ctx.author.is_mod or ctx.author.is_broadcaster):
            await ctx.send(f"@{ctx.author.name} You don't have permission to start polls.")
            return
        
        channel_name = ctx.channel.name
        
        # Check for existing active poll
        existing = self._get_active_poll(channel_name)
        if existing:
            await ctx.send(
                f"@{ctx.author.name} There's already an active poll! "
                f"Use !poll end or !poll cancel first."
            )
            return
        
        # Parse arguments - expecting quoted strings
        # Reconstruct the full argument string
        full_args = " ".join(args)
        
        # Parse quoted strings
        parsed = self._parse_quoted_args(full_args)
        
        if len(parsed) < 3:
            await ctx.send(
                f"@{ctx.author.name} Usage: !poll start \"Question\" \"Option1\" \"Option2\" [duration_seconds]"
            )
            return
        
        # Check if last argument is a duration (number)
        duration = 60  # Default duration
        if parsed[-1].isdigit():
            duration = int(parsed[-1])
            parsed = parsed[:-1]
        
        # Validate duration (10 seconds to 10 minutes)
        duration = max(10, min(600, duration))
        
        question = parsed[0]
        options = parsed[1:]
        
        if len(options) < 2:
            await ctx.send(
                f"@{ctx.author.name} A poll needs at least 2 options!"
            )
            return
        
        if len(options) > 10:
            await ctx.send(
                f"@{ctx.author.name} Maximum 10 options allowed!"
            )
            return
        
        # Create the poll
        poll_id = self._create_poll(
            channel=channel_name,
            question=question,
            options=options,
            started_by=ctx.author.name,
            duration_seconds=duration,
            poll_type="chat"
        )
        
        # Track active poll
        self._active_polls[channel_name.lower()] = poll_id
        
        # Build announcement
        options_text = " | ".join(f"{i+1}. {opt}" for i, opt in enumerate(options))
        await ctx.send(
            f"Poll started: {question} | {options_text} | "
            f"Vote with !vote <number> | Ends in {duration}s"
        )
        
        logger.info(
            "Poll %d started in %s by %s: %s",
            poll_id,
            channel_name,
            ctx.author.name,
            question
        )
    
    def _parse_quoted_args(self, text: str) -> list[str]:
        """Parse quoted arguments from a string."""
        result = []
        current = ""
        in_quotes = False
        quote_char = None
        
        for char in text:
            if char in ('"', "'") and not in_quotes:
                in_quotes = True
                quote_char = char
            elif char == quote_char and in_quotes:
                in_quotes = False
                if current.strip():
                    result.append(current.strip())
                current = ""
                quote_char = None
            elif in_quotes:
                current += char
            elif char == " " and not in_quotes:
                if current.strip():
                    result.append(current.strip())
                current = ""
            else:
                current += char
        
        # Add any remaining content
        if current.strip():
            result.append(current.strip())
        
        return result
    
    async def _poll_end(self, ctx: Context) -> None:
        """End the current poll and show results."""
        # Check permissions
        if not (ctx.author.is_mod or ctx.author.is_broadcaster):
            await ctx.send(f"@{ctx.author.name} You don't have permission to end polls.")
            return
        
        channel_name = ctx.channel.name
        
        poll = self._get_active_poll(channel_name)
        if not poll:
            await ctx.send(f"@{ctx.author.name} No active poll to end.")
            return
        
        await self._end_poll_and_announce(ctx.channel, poll["id"])
        
        logger.info(
            "Poll %d ended in %s by %s",
            poll["id"],
            channel_name,
            ctx.author.name
        )
    
    async def _poll_cancel(self, ctx: Context) -> None:
        """Cancel the current poll without showing results."""
        # Check permissions
        if not (ctx.author.is_mod or ctx.author.is_broadcaster):
            await ctx.send(f"@{ctx.author.name} You don't have permission to cancel polls.")
            return
        
        channel_name = ctx.channel.name
        
        poll = self._get_active_poll(channel_name)
        if not poll:
            await ctx.send(f"@{ctx.author.name} No active poll to cancel.")
            return
        
        # Mark as cancelled
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE polls 
                SET status = 'cancelled', ended_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (poll["id"],))
            conn.commit()
        
        # Remove from active polls
        if channel_name.lower() in self._active_polls:
            del self._active_polls[channel_name.lower()]
        
        await ctx.send(f"@{ctx.author.name} Poll cancelled.")
        
        logger.info(
            "Poll %d cancelled in %s by %s",
            poll["id"],
            channel_name,
            ctx.author.name
        )
    
    async def _poll_results(self, ctx: Context) -> None:
        """Show current poll results."""
        channel_name = ctx.channel.name
        
        poll = self._get_active_poll(channel_name)
        if not poll:
            # Check for most recent ended poll
            history = self._get_poll_history(channel_name, limit=1)
            if history:
                poll = history[0]
            else:
                await ctx.send(f"@{ctx.author.name} No poll found.")
                return
        
        results = self._get_poll_results(poll["id"])
        total_votes = sum(r["votes"] for r in results)
        options = json.loads(poll["options"])
        
        if total_votes == 0:
            await ctx.send(
                f"Poll: \"{poll['question']}\" - No votes yet!"
            )
            return
        
        # Build results string
        results_parts = []
        for r in results:
            percentage = (r["votes"] / total_votes) * 100
            results_parts.append(
                f"{r['option_index']+1}. {options[r['option_index']]}: "
                f"{r['votes']} ({percentage:.1f}%)"
            )
        
        status = "Active" if poll["status"] == "active" else "Ended"
        await ctx.send(
            f"[{status}] {poll['question']} | {' | '.join(results_parts)} | "
            f"Total: {total_votes} votes"
        )
    
    async def _poll_info(self, ctx: Context) -> None:
        """Show information about the current poll."""
        channel_name = ctx.channel.name
        
        poll = self._get_active_poll(channel_name)
        if not poll:
            await ctx.send(f"@{ctx.author.name} No active poll.")
            return
        
        options = json.loads(poll["options"])
        total_votes = self._get_total_votes(poll["id"])
        
        # Calculate remaining time
        started_at = datetime.fromisoformat(poll["started_at"])
        duration = poll["duration_seconds"]
        elapsed = (datetime.now() - started_at).total_seconds()
        remaining = max(0, duration - elapsed)
        
        options_text = " | ".join(f"{i+1}. {opt}" for i, opt in enumerate(options))
        await ctx.send(
            f"Poll: {poll['question']} | {options_text} | "
            f"{total_votes} votes | {int(remaining)}s remaining | "
            f"Vote with !vote <number>"
        )
    
    # ==================== Vote Command ====================
    
    @commands.command(name="vote")
    async def vote_command(self, ctx: Context, option: str = "") -> None:
        """
        Vote in the current poll.
        
        Usage: !vote <number>
        """
        channel_name = ctx.channel.name
        
        poll = self._get_active_poll(channel_name)
        if not poll:
            await ctx.send(f"@{ctx.author.name} No active poll to vote in.")
            return
        
        # Validate option
        if not option.isdigit():
            await ctx.send(f"@{ctx.author.name} Usage: !vote <number>")
            return
        
        option_num = int(option)
        options = json.loads(poll["options"])
        
        if option_num < 1 or option_num > len(options):
            await ctx.send(
                f"@{ctx.author.name} Invalid option! Choose 1-{len(options)}"
            )
            return
        
        # Try to add vote (0-indexed)
        user_id = str(ctx.author.id)
        username = ctx.author.name
        option_index = option_num - 1
        
        success = self._add_vote(poll["id"], user_id, username, option_index)
        
        if success:
            total_votes = self._get_total_votes(poll["id"])
            await ctx.send(
                f"@{username} Voted for \"{options[option_index]}\"! "
                f"({total_votes} total votes)"
            )
        else:
            await ctx.send(
                f"@{username} You've already voted in this poll!"
            )
    
    # ==================== Twitch Native Polls ====================
    
    @commands.command(name="twitchpoll")
    async def twitch_poll_command(self, ctx: Context, action: str = "", *args: str) -> None:
        """
        Native Twitch Poll management (requires channel:manage:polls scope).
        
        Usage:
        - !twitchpoll start "Question" "Option1" "Option2" [duration] - Start native poll
        - !twitchpoll end - End native poll
        """
        action = action.lower()
        
        if action == "start":
            await self._twitch_poll_start(ctx, *args)
        elif action == "end":
            await self._twitch_poll_end(ctx)
        else:
            await ctx.send(
                f"@{ctx.author.name} Twitch Poll: !twitchpoll start \"Question\" \"Opt1\" \"Opt2\" [duration] | "
                f"!twitchpoll end"
            )
    
    async def _twitch_poll_start(self, ctx: Context, *args: str) -> None:
        """Start a native Twitch poll using the API."""
        # Check permissions
        if not (ctx.author.is_mod or ctx.author.is_broadcaster):
            await ctx.send(f"@{ctx.author.name} You don't have permission to start polls.")
            return
        
        # Parse arguments
        full_args = " ".join(args)
        parsed = self._parse_quoted_args(full_args)
        
        if len(parsed) < 3:
            await ctx.send(
                f"@{ctx.author.name} Usage: !twitchpoll start \"Question\" \"Option1\" \"Option2\" [duration_seconds]"
            )
            return
        
        # Check if last argument is a duration
        duration = 60
        if parsed[-1].isdigit():
            duration = int(parsed[-1])
            parsed = parsed[:-1]
        
        # Twitch polls: 15 seconds to 30 minutes
        duration = max(15, min(1800, duration))
        
        question = parsed[0]
        options = parsed[1:]
        
        if len(options) < 2 or len(options) > 5:
            await ctx.send(
                f"@{ctx.author.name} Twitch polls need 2-5 options!"
            )
            return
        
        # Validate question length (1-60 characters for Twitch)
        if len(question) > 60:
            await ctx.send(
                f"@{ctx.author.name} Question must be 60 characters or less for Twitch polls!"
            )
            return
        
        # Validate option lengths (1-25 characters for Twitch)
        for opt in options:
            if len(opt) > 25:
                await ctx.send(
                    f"@{ctx.author.name} Each option must be 25 characters or less!"
                )
                return
        
        try:
            # Get broadcaster ID
            broadcaster = await self.bot.fetch_users(names=[ctx.channel.name])
            if not broadcaster:
                await ctx.send(f"@{ctx.author.name} Could not find broadcaster info.")
                return
            
            broadcaster_id = broadcaster[0].id
            
            # Create poll via Twitch API
            # Note: This requires the bot to have channel:manage:polls scope
            # and appropriate token
            poll_data = {
                "broadcaster_id": str(broadcaster_id),
                "title": question,
                "choices": [{"title": opt} for opt in options],
                "duration": duration
            }
            
            # Make API request
            token = self.bot._http.token  # Access token
            headers = {
                "Authorization": f"Bearer {token}",
                "Client-Id": self.bot._http.client_id,
                "Content-Type": "application/json"
            }
            
            async with self.bot._http._session.post(
                "https://api.twitch.tv/helix/polls",
                headers=headers,
                json=poll_data
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    twitch_poll_id = data["data"][0]["id"]
                    
                    # Store in database for tracking
                    poll_id = self._create_poll(
                        channel=ctx.channel.name,
                        question=question,
                        options=options,
                        started_by=ctx.author.name,
                        duration_seconds=duration,
                        poll_type="twitch",
                        twitch_poll_id=twitch_poll_id
                    )
                    
                    await ctx.send(
                        f"@{ctx.author.name} Twitch Poll started! "
                        f"Vote in the poll widget. Ends in {duration}s."
                    )
                    
                    logger.info(
                        "Twitch poll %s started in %s by %s",
                        twitch_poll_id,
                        ctx.channel.name,
                        ctx.author.name
                    )
                elif resp.status == 401:
                    await ctx.send(
                        f"@{ctx.author.name} Bot doesn't have permission to create polls. "
                        f"Use !poll start for chat-based polls instead."
                    )
                elif resp.status == 400:
                    error_data = await resp.json()
                    error_msg = error_data.get("message", "Invalid request")
                    await ctx.send(f"@{ctx.author.name} Error: {error_msg}")
                else:
                    await ctx.send(
                        f"@{ctx.author.name} Failed to create Twitch poll. "
                        f"Use !poll start for chat-based polls."
                    )
                    
        except Exception as e:
            logger.error("Error creating Twitch poll: %s", e)
            await ctx.send(
                f"@{ctx.author.name} Error creating poll. "
                f"Use !poll start for chat-based polls instead."
            )
    
    async def _twitch_poll_end(self, ctx: Context) -> None:
        """End a native Twitch poll."""
        # Check permissions
        if not (ctx.author.is_mod or ctx.author.is_broadcaster):
            await ctx.send(f"@{ctx.author.name} You don't have permission to end polls.")
            return
        
        # Find active Twitch poll
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM polls 
                WHERE channel = ? AND status = 'active' AND poll_type = 'twitch'
                ORDER BY started_at DESC LIMIT 1
            """, (ctx.channel.name.lower(),))
            poll = cursor.fetchone()
        
        if not poll:
            await ctx.send(f"@{ctx.author.name} No active Twitch poll to end.")
            return
        
        poll = dict(poll)
        twitch_poll_id = poll["twitch_poll_id"]
        
        try:
            # Get broadcaster ID
            broadcaster = await self.bot.fetch_users(names=[ctx.channel.name])
            if not broadcaster:
                await ctx.send(f"@{ctx.author.name} Could not find broadcaster info.")
                return
            
            broadcaster_id = broadcaster[0].id
            
            # End poll via Twitch API
            token = self.bot._http.token
            headers = {
                "Authorization": f"Bearer {token}",
                "Client-Id": self.bot._http.client_id,
                "Content-Type": "application/json"
            }
            
            end_data = {
                "broadcaster_id": str(broadcaster_id),
                "id": twitch_poll_id,
                "status": "TERMINATED"  # or "ARCHIVED" to show results
            }
            
            async with self.bot._http._session.patch(
                "https://api.twitch.tv/helix/polls",
                headers=headers,
                json=end_data
            ) as resp:
                if resp.status == 200:
                    # Mark as ended in database
                    self._mark_poll_ended(poll["id"])
                    await ctx.send(f"@{ctx.author.name} Twitch Poll ended!")
                    
                    logger.info(
                        "Twitch poll %s ended in %s by %s",
                        twitch_poll_id,
                        ctx.channel.name,
                        ctx.author.name
                    )
                else:
                    await ctx.send(f"@{ctx.author.name} Failed to end Twitch poll.")
                    
        except Exception as e:
            logger.error("Error ending Twitch poll: %s", e)
            await ctx.send(f"@{ctx.author.name} Error ending poll.")


# Import sqlite3 for IntegrityError
import sqlite3


def prepare(bot: TwitchBot) -> None:
    """Prepare the cog for loading."""
    bot.add_cog(Polls(bot))
