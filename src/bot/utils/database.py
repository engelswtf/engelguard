"""
SQLite database manager for automod system.

Handles:
- User trust tracking
- Moderation action logging
- Temporary permit system
- Custom commands
- Timers
- Strikes/warnings
- Loyalty points
- Quotes system
- Giveaways
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Generator, Optional, Any

from bot.utils.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class DatabaseManager:
    """
    SQLite database manager for automod system.
    
    Provides thread-safe database operations for:
    - User trust tracking
    - Moderation action logging
    - Temporary link permits
    - Custom commands
    - Timers
    - Strike system
    - Loyalty points
    - Quotes system
    - Giveaways
    """
    
    def __init__(self, db_path: str = "/opt/twitch-bot/data/automod.db") -> None:
        """
        Initialize the database manager.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
        logger.info("Database initialized at %s", self.db_path)
    
    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Get a database connection with automatic cleanup.
        
        Yields:
            sqlite3.Connection: Database connection
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error("Database error: %s", e)
            raise
        finally:
            conn.close()
    
    def _init_database(self) -> None:
        """Initialize database tables."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # User trust tracking table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT,
                    trust_score INTEGER DEFAULT 50,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    message_count INTEGER DEFAULT 0,
                    warnings_count INTEGER DEFAULT 0,
                    is_whitelisted BOOLEAN DEFAULT FALSE,
                    last_message TIMESTAMP
                )
            """)
            
            # Moderation action log table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mod_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_id TEXT,
                    username TEXT,
                    action TEXT,
                    reason TEXT,
                    spam_score INTEGER,
                    message_content TEXT,
                    channel TEXT
                )
            """)
            
            # Permit system table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS permits (
                    user_id TEXT PRIMARY KEY,
                    granted_by TEXT,
                    expires_at TIMESTAMP
                )
            """)
            
            # ==================== NEW TABLES ====================
            
            # Custom commands table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS custom_commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    response TEXT NOT NULL,
                    created_by TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP,
                    use_count INTEGER DEFAULT 0,
                    cooldown_user INTEGER DEFAULT 5,
                    cooldown_global INTEGER DEFAULT 0,
                    permission_level TEXT DEFAULT 'everyone',
                    enabled BOOLEAN DEFAULT TRUE,
                    aliases TEXT
                )
            """)
            
            # Command aliases table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS command_aliases (
                    alias TEXT PRIMARY KEY,
                    command_name TEXT NOT NULL,
                    FOREIGN KEY (command_name) REFERENCES custom_commands(name) ON DELETE CASCADE
                )
            """)
            
            # Timers table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS timers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    message TEXT NOT NULL,
                    interval_minutes INTEGER DEFAULT 15,
                    chat_lines_required INTEGER DEFAULT 5,
                    online_only BOOLEAN DEFAULT TRUE,
                    enabled BOOLEAN DEFAULT TRUE,
                    last_triggered TIMESTAMP,
                    created_by TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # User strikes table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_strikes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    username TEXT,
                    strike_count INTEGER DEFAULT 0,
                    last_strike TIMESTAMP,
                    last_reason TEXT,
                    expires_at TIMESTAMP,
                    UNIQUE(user_id)
                )
            """)
            
            # Strike history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS strike_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    username TEXT,
                    strike_number INTEGER,
                    reason TEXT,
                    action_taken TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    moderator TEXT,
                    channel TEXT
                )
            """)
            
            # Loyalty settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS loyalty_settings (
                    channel TEXT PRIMARY KEY,
                    enabled BOOLEAN DEFAULT FALSE,
                    points_name TEXT DEFAULT 'points',
                    points_per_minute REAL DEFAULT 1.0,
                    points_per_message REAL DEFAULT 0.5,
                    bonus_sub_multiplier REAL DEFAULT 2.0,
                    bonus_vip_multiplier REAL DEFAULT 1.5
                )
            """)
            
            # User loyalty table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_loyalty (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    username TEXT,
                    channel TEXT NOT NULL,
                    points REAL DEFAULT 0,
                    watch_time_minutes INTEGER DEFAULT 0,
                    message_count INTEGER DEFAULT 0,
                    last_seen TIMESTAMP,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, channel)
                )
            """)
            
            # Nuke log table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS nuke_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    moderator TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    pattern TEXT NOT NULL,
                    action TEXT NOT NULL,
                    duration INTEGER,
                    users_affected INTEGER,
                    users_list TEXT
                )
            """)
            
            # Filter settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS filter_settings (
                    channel TEXT PRIMARY KEY,
                    caps_enabled BOOLEAN DEFAULT TRUE,
                    caps_min_length INTEGER DEFAULT 10,
                    caps_max_percent INTEGER DEFAULT 70,
                    emote_enabled BOOLEAN DEFAULT TRUE,
                    emote_max_count INTEGER DEFAULT 15,
                    symbol_enabled BOOLEAN DEFAULT TRUE,
                    symbol_max_percent INTEGER DEFAULT 50,
                    link_enabled BOOLEAN DEFAULT TRUE,
                    length_enabled BOOLEAN DEFAULT TRUE,
                    length_max_chars INTEGER DEFAULT 500,
                    repetition_enabled BOOLEAN DEFAULT TRUE,
                    repetition_max_words INTEGER DEFAULT 10,
                    zalgo_enabled BOOLEAN DEFAULT TRUE,
                    lookalike_enabled BOOLEAN DEFAULT TRUE
                )
            """)
            
            # Recent chatters table (for nuke command)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recent_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    channel TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    message TEXT NOT NULL,
                    is_subscriber BOOLEAN DEFAULT FALSE,
                    is_vip BOOLEAN DEFAULT FALSE,
                    is_mod BOOLEAN DEFAULT FALSE
                )
            """)
            
            # Cog settings table (for global feature toggles)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cog_settings (
                    channel TEXT NOT NULL,
                    cog_name TEXT NOT NULL,
                    enabled BOOLEAN DEFAULT TRUE,
                    PRIMARY KEY (channel, cog_name)
                )
            """)
            
            # Quotes table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS quotes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    quote_text TEXT NOT NULL,
                    author TEXT,
                    added_by TEXT NOT NULL,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    game TEXT,
                    enabled BOOLEAN DEFAULT TRUE
                )
            """)
            
            # Giveaways table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS giveaways (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    keyword TEXT NOT NULL,
                    prize TEXT,
                    started_by TEXT NOT NULL,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ends_at TIMESTAMP,
                    status TEXT DEFAULT 'active',
                    winner_count INTEGER DEFAULT 1,
                    sub_luck_multiplier REAL DEFAULT 1.0,
                    follower_only BOOLEAN DEFAULT FALSE,
                    sub_only BOOLEAN DEFAULT FALSE,
                    min_points INTEGER DEFAULT 0
                )
            """)
            
            # Giveaway entries table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS giveaway_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    giveaway_id INTEGER NOT NULL,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    is_subscriber BOOLEAN DEFAULT FALSE,
                    is_vip BOOLEAN DEFAULT FALSE,
                    entered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    tickets INTEGER DEFAULT 1,
                    UNIQUE(giveaway_id, user_id),
                    FOREIGN KEY (giveaway_id) REFERENCES giveaways(id) ON DELETE CASCADE
                )
            """)
            
            # Giveaway winners table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS giveaway_winners (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    giveaway_id INTEGER NOT NULL,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    won_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (giveaway_id) REFERENCES giveaways(id) ON DELETE CASCADE
                )
            """)
            
            # Banned words table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS banned_words (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    word TEXT NOT NULL,
                    is_regex BOOLEAN DEFAULT FALSE,
                    action TEXT DEFAULT 'delete',
                    duration INTEGER DEFAULT 600,
                    added_by TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    enabled BOOLEAN DEFAULT TRUE,
                    UNIQUE(channel, word)
                )
            """)
            
            # Create indexes for performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_mod_actions_timestamp 
                ON mod_actions(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_mod_actions_user 
                ON mod_actions(user_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_users_username 
                ON users(username)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_custom_commands_name
                ON custom_commands(name)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_strikes_user_id
                ON user_strikes(user_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_loyalty_user_channel
                ON user_loyalty(user_id, channel)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_recent_messages_timestamp
                ON recent_messages(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_recent_messages_channel
                ON recent_messages(channel)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_cog_settings_channel
                ON cog_settings(channel)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_quotes_channel
                ON quotes(channel)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_quotes_channel_enabled
                ON quotes(channel, enabled)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_giveaways_channel_status
                ON giveaways(channel, status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_giveaway_entries_giveaway_id
                ON giveaway_entries(giveaway_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_giveaway_winners_giveaway_id
                ON giveaway_winners(giveaway_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_banned_words_channel
                ON banned_words(channel)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_banned_words_channel_enabled
                ON banned_words(channel, enabled)
            """)
            
            logger.info("Database tables initialized")
    
    # ==================== User Methods ====================
    
    def get_or_create_user(self, user_id: str, username: str) -> dict[str, Any]:
        """Get or create a user record."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            
            if row:
                if row["username"] != username:
                    cursor.execute(
                        "UPDATE users SET username = ? WHERE user_id = ?",
                        (username, user_id)
                    )
                return dict(row)
            
            cursor.execute(
                """
                INSERT INTO users (user_id, username, trust_score, first_seen, message_count)
                VALUES (?, ?, 50, CURRENT_TIMESTAMP, 0)
                """,
                (user_id, username)
            )
            
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            return dict(cursor.fetchone())
    
    def update_user_message(self, user_id: str) -> None:
        """Update user's last message time and increment message count."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE users 
                SET message_count = message_count + 1,
                    last_message = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (user_id,)
            )
    
    def update_trust_score(self, user_id: str, delta: int) -> int:
        """Update user's trust score."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE users 
                SET trust_score = MAX(0, MIN(100, trust_score + ?))
                WHERE user_id = ?
                """,
                (delta, user_id)
            )
            cursor.execute(
                "SELECT trust_score FROM users WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            return row["trust_score"] if row else 50
    
    def increment_warnings(self, user_id: str) -> int:
        """Increment user's warning count."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET warnings_count = warnings_count + 1 WHERE user_id = ?",
                (user_id,)
            )
            cursor.execute(
                "SELECT warnings_count FROM users WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            return row["warnings_count"] if row else 0
    
    def set_whitelisted(self, user_id: str, username: str, whitelisted: bool) -> None:
        """Set user's whitelist status."""
        self.get_or_create_user(user_id, username)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET is_whitelisted = ? WHERE user_id = ?",
                (whitelisted, user_id)
            )
    
    def is_whitelisted(self, user_id: str) -> bool:
        """Check if user is whitelisted."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT is_whitelisted FROM users WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            return bool(row["is_whitelisted"]) if row else False
    
    def get_user_stats(self, user_id: str) -> Optional[dict[str, Any]]:
        """Get user statistics."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    # ==================== Moderation Log Methods ====================
    
    def log_action(
        self,
        user_id: str,
        username: str,
        action: str,
        reason: str,
        spam_score: int,
        message_content: str,
        channel: str
    ) -> int:
        """Log a moderation action."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO mod_actions 
                (user_id, username, action, reason, spam_score, message_content, channel)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, username, action, reason, spam_score, message_content, channel)
            )
            return cursor.lastrowid or 0
    
    def get_recent_actions(self, limit: int = 10, channel: Optional[str] = None) -> list[dict[str, Any]]:
        """Get recent moderation actions."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if channel:
                cursor.execute(
                    """
                    SELECT * FROM mod_actions 
                    WHERE channel = ?
                    ORDER BY timestamp DESC 
                    LIMIT ?
                    """,
                    (channel, limit)
                )
            else:
                cursor.execute(
                    """
                    SELECT * FROM mod_actions 
                    ORDER BY timestamp DESC 
                    LIMIT ?
                    """,
                    (limit,)
                )
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_user_actions(self, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get moderation actions for a specific user."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM mod_actions 
                WHERE user_id = ?
                ORDER BY timestamp DESC 
                LIMIT ?
                """,
                (user_id, limit)
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def get_action_stats(self, hours: int = 24) -> dict[str, int]:
        """Get action statistics for the past N hours."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            
            cursor.execute(
                """
                SELECT action, COUNT(*) as count 
                FROM mod_actions 
                WHERE timestamp > ?
                GROUP BY action
                """,
                (cutoff.isoformat(),)
            )
            
            return {row["action"]: row["count"] for row in cursor.fetchall()}
    
    # ==================== Permit Methods ====================
    
    def grant_permit(self, user_id: str, granted_by: str, duration_seconds: int = 60) -> None:
        """Grant a temporary link permit to a user."""
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO permits (user_id, granted_by, expires_at)
                VALUES (?, ?, ?)
                """,
                (user_id, granted_by, expires_at.isoformat())
            )
    
    def has_valid_permit(self, user_id: str) -> bool:
        """Check if user has a valid (non-expired) permit."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            
            cursor.execute(
                """
                SELECT 1 FROM permits 
                WHERE user_id = ? AND expires_at > ?
                """,
                (user_id, now)
            )
            
            return cursor.fetchone() is not None
    
    def revoke_permit(self, user_id: str) -> bool:
        """Revoke a user's permit."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM permits WHERE user_id = ?", (user_id,))
            return cursor.rowcount > 0
    
    def cleanup_expired_permits(self) -> int:
        """Remove expired permits from database."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute("DELETE FROM permits WHERE expires_at <= ?", (now,))
            return cursor.rowcount
    
    # ==================== Custom Commands Methods ====================
    
    def create_command(
        self,
        name: str,
        response: str,
        created_by: str,
        cooldown_user: int = 5,
        cooldown_global: int = 0,
        permission_level: str = "everyone",
        aliases: list[str] | None = None
    ) -> int:
        """Create a new custom command."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            aliases_json = json.dumps(aliases) if aliases else None
            
            cursor.execute(
                """
                INSERT INTO custom_commands 
                (name, response, created_by, cooldown_user, cooldown_global, permission_level, aliases)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (name.lower(), response, created_by, cooldown_user, cooldown_global, permission_level, aliases_json)
            )
            
            # Add aliases to aliases table
            if aliases:
                for alias in aliases:
                    cursor.execute(
                        "INSERT OR IGNORE INTO command_aliases (alias, command_name) VALUES (?, ?)",
                        (alias.lower(), name.lower())
                    )
            
            return cursor.lastrowid or 0
    
    def get_command(self, name: str) -> Optional[dict[str, Any]]:
        """Get a custom command by name or alias."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # First check direct name
            cursor.execute(
                "SELECT * FROM custom_commands WHERE name = ? AND enabled = TRUE",
                (name.lower(),)
            )
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            
            # Check aliases
            cursor.execute(
                "SELECT command_name FROM command_aliases WHERE alias = ?",
                (name.lower(),)
            )
            alias_row = cursor.fetchone()
            
            if alias_row:
                cursor.execute(
                    "SELECT * FROM custom_commands WHERE name = ? AND enabled = TRUE",
                    (alias_row["command_name"],)
                )
                row = cursor.fetchone()
                if row:
                    return dict(row)
            
            return None
    
    def update_command(
        self,
        name: str,
        response: str | None = None,
        cooldown_user: int | None = None,
        cooldown_global: int | None = None,
        permission_level: str | None = None,
        enabled: bool | None = None,
        aliases: list[str] | None = None
    ) -> bool:
        """Update an existing custom command."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            updates = []
            params = []
            
            if response is not None:
                updates.append("response = ?")
                params.append(response)
            if cooldown_user is not None:
                updates.append("cooldown_user = ?")
                params.append(cooldown_user)
            if cooldown_global is not None:
                updates.append("cooldown_global = ?")
                params.append(cooldown_global)
            if permission_level is not None:
                updates.append("permission_level = ?")
                params.append(permission_level)
            if enabled is not None:
                updates.append("enabled = ?")
                params.append(enabled)
            if aliases is not None:
                updates.append("aliases = ?")
                params.append(json.dumps(aliases))
                
                # Update aliases table
                cursor.execute("DELETE FROM command_aliases WHERE command_name = ?", (name.lower(),))
                for alias in aliases:
                    cursor.execute(
                        "INSERT OR IGNORE INTO command_aliases (alias, command_name) VALUES (?, ?)",
                        (alias.lower(), name.lower())
                    )
            
            if not updates:
                return False
            
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(name.lower())
            
            cursor.execute(
                f"UPDATE custom_commands SET {', '.join(updates)} WHERE name = ?",
                params
            )
            
            return cursor.rowcount > 0
    
    def delete_command(self, name: str) -> bool:
        """Delete a custom command."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM command_aliases WHERE command_name = ?", (name.lower(),))
            cursor.execute("DELETE FROM custom_commands WHERE name = ?", (name.lower(),))
            return cursor.rowcount > 0
    
    def get_all_commands(self) -> list[dict[str, Any]]:
        """Get all custom commands."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM custom_commands ORDER BY name")
            return [dict(row) for row in cursor.fetchall()]
    
    def increment_command_usage(self, name: str) -> None:
        """Increment command usage count."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE custom_commands SET use_count = use_count + 1 WHERE name = ?",
                (name.lower(),)
            )
    
    # ==================== Timers Methods ====================
    
    def create_timer(
        self,
        name: str,
        message: str,
        interval_minutes: int = 15,
        chat_lines_required: int = 5,
        online_only: bool = True,
        created_by: str = ""
    ) -> int:
        """Create a new timer."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO timers 
                (name, message, interval_minutes, chat_lines_required, online_only, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name.lower(), message, interval_minutes, chat_lines_required, online_only, created_by)
            )
            return cursor.lastrowid or 0
    
    def get_timer(self, name: str) -> Optional[dict[str, Any]]:
        """Get a timer by name."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM timers WHERE name = ?", (name.lower(),))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def update_timer(
        self,
        name: str,
        message: str | None = None,
        interval_minutes: int | None = None,
        chat_lines_required: int | None = None,
        online_only: bool | None = None,
        enabled: bool | None = None
    ) -> bool:
        """Update an existing timer."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            updates = []
            params = []
            
            if message is not None:
                updates.append("message = ?")
                params.append(message)
            if interval_minutes is not None:
                updates.append("interval_minutes = ?")
                params.append(interval_minutes)
            if chat_lines_required is not None:
                updates.append("chat_lines_required = ?")
                params.append(chat_lines_required)
            if online_only is not None:
                updates.append("online_only = ?")
                params.append(online_only)
            if enabled is not None:
                updates.append("enabled = ?")
                params.append(enabled)
            
            if not updates:
                return False
            
            params.append(name.lower())
            
            cursor.execute(
                f"UPDATE timers SET {', '.join(updates)} WHERE name = ?",
                params
            )
            
            return cursor.rowcount > 0
    
    def delete_timer(self, name: str) -> bool:
        """Delete a timer."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM timers WHERE name = ?", (name.lower(),))
            return cursor.rowcount > 0
    
    def get_all_timers(self) -> list[dict[str, Any]]:
        """Get all timers."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM timers ORDER BY name")
            return [dict(row) for row in cursor.fetchall()]
    
    def get_enabled_timers(self) -> list[dict[str, Any]]:
        """Get all enabled timers."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM timers WHERE enabled = TRUE ORDER BY name")
            return [dict(row) for row in cursor.fetchall()]
    
    def update_timer_triggered(self, name: str) -> None:
        """Update timer's last triggered time."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE timers SET last_triggered = CURRENT_TIMESTAMP WHERE name = ?",
                (name.lower(),)
            )
    
    # ==================== Strike Methods ====================
    
    def get_user_strikes(self, user_id: str) -> dict[str, Any]:
        """Get user's strike information."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_strikes WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            
            if row:
                # Check if strikes have expired
                expires_at = row["expires_at"]
                if expires_at:
                    try:
                        if isinstance(expires_at, str):
                            expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                        else:
                            expires_dt = expires_at
                        
                        if datetime.now(timezone.utc) > expires_dt.replace(tzinfo=timezone.utc):
                            # Strikes have expired, reset
                            cursor.execute(
                                "UPDATE user_strikes SET strike_count = 0, expires_at = NULL WHERE user_id = ?",
                                (user_id,)
                            )
                            return {"user_id": user_id, "strike_count": 0, "last_strike": None, "last_reason": None}
                    except (ValueError, AttributeError):
                        pass
                
                return dict(row)
            
            return {"user_id": user_id, "strike_count": 0, "last_strike": None, "last_reason": None}
    
    def add_strike(
        self,
        user_id: str,
        username: str,
        reason: str,
        action_taken: str,
        moderator: str,
        channel: str,
        expire_days: int = 30
    ) -> int:
        """Add a strike to a user and return new strike count."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get current strikes
            current = self.get_user_strikes(user_id)
            new_count = current["strike_count"] + 1
            
            expires_at = datetime.now(timezone.utc) + timedelta(days=expire_days)
            
            # Update or insert strike record
            cursor.execute(
                """
                INSERT INTO user_strikes (user_id, username, strike_count, last_strike, last_reason, expires_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    strike_count = excluded.strike_count,
                    last_strike = CURRENT_TIMESTAMP,
                    last_reason = excluded.last_reason,
                    expires_at = excluded.expires_at
                """,
                (user_id, username, new_count, reason, expires_at.isoformat())
            )
            
            # Log to strike history
            cursor.execute(
                """
                INSERT INTO strike_history 
                (user_id, username, strike_number, reason, action_taken, moderator, channel)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, username, new_count, reason, action_taken, moderator, channel)
            )
            
            return new_count
    
    def clear_strikes(self, user_id: str) -> bool:
        """Clear all strikes for a user."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE user_strikes SET strike_count = 0, expires_at = NULL WHERE user_id = ?",
                (user_id,)
            )
            return cursor.rowcount > 0
    
    def get_strike_history(self, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get strike history for a user."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM strike_history 
                WHERE user_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
                """,
                (user_id, limit)
            )
            return [dict(row) for row in cursor.fetchall()]
    
    # ==================== Loyalty Methods ====================
    
    def get_loyalty_settings(self, channel: str) -> dict[str, Any]:
        """Get loyalty settings for a channel."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM loyalty_settings WHERE channel = ?", (channel.lower(),))
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            
            # Return defaults
            return {
                "channel": channel.lower(),
                "enabled": False,
                "points_name": "points",
                "points_per_minute": 1.0,
                "points_per_message": 0.5,
                "bonus_sub_multiplier": 2.0,
                "bonus_vip_multiplier": 1.5
            }
    
    def update_loyalty_settings(
        self,
        channel: str,
        enabled: bool | None = None,
        points_name: str | None = None,
        points_per_minute: float | None = None,
        points_per_message: float | None = None,
        bonus_sub_multiplier: float | None = None,
        bonus_vip_multiplier: float | None = None
    ) -> None:
        """Update loyalty settings for a channel."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get current settings
            current = self.get_loyalty_settings(channel)
            
            new_enabled = enabled if enabled is not None else current["enabled"]
            new_points_name = points_name if points_name is not None else current["points_name"]
            new_ppm = points_per_minute if points_per_minute is not None else current["points_per_minute"]
            new_ppmsg = points_per_message if points_per_message is not None else current["points_per_message"]
            new_sub_mult = bonus_sub_multiplier if bonus_sub_multiplier is not None else current["bonus_sub_multiplier"]
            new_vip_mult = bonus_vip_multiplier if bonus_vip_multiplier is not None else current["bonus_vip_multiplier"]
            
            cursor.execute(
                """
                INSERT INTO loyalty_settings 
                (channel, enabled, points_name, points_per_minute, points_per_message, bonus_sub_multiplier, bonus_vip_multiplier)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel) DO UPDATE SET
                    enabled = excluded.enabled,
                    points_name = excluded.points_name,
                    points_per_minute = excluded.points_per_minute,
                    points_per_message = excluded.points_per_message,
                    bonus_sub_multiplier = excluded.bonus_sub_multiplier,
                    bonus_vip_multiplier = excluded.bonus_vip_multiplier
                """,
                (channel.lower(), new_enabled, new_points_name, new_ppm, new_ppmsg, new_sub_mult, new_vip_mult)
            )
    
    def get_user_loyalty(self, user_id: str, channel: str) -> dict[str, Any]:
        """Get user's loyalty data for a channel."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM user_loyalty WHERE user_id = ? AND channel = ?",
                (user_id, channel.lower())
            )
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            
            return {
                "user_id": user_id,
                "channel": channel.lower(),
                "points": 0,
                "watch_time_minutes": 0,
                "message_count": 0
            }
    
    def update_user_loyalty(
        self,
        user_id: str,
        username: str,
        channel: str,
        points_delta: float = 0,
        watch_time_delta: int = 0,
        message_count_delta: int = 0
    ) -> dict[str, Any]:
        """Update user's loyalty data (points floor at 0)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Use MAX to prevent negative balance when deducting points
            cursor.execute(
                """
                INSERT INTO user_loyalty (user_id, username, channel, points, watch_time_minutes, message_count, last_seen)
                VALUES (?, ?, ?, MAX(0, ?), ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, channel) DO UPDATE SET
                    username = excluded.username,
                    points = MAX(0, user_loyalty.points + ?),
                    watch_time_minutes = user_loyalty.watch_time_minutes + ?,
                    message_count = user_loyalty.message_count + ?,
                    last_seen = CURRENT_TIMESTAMP
                """,
                (user_id, username, channel.lower(), points_delta, watch_time_delta, message_count_delta,
                 points_delta, watch_time_delta, message_count_delta)
            )
            
            return self.get_user_loyalty(user_id, channel)
    
    def set_user_points(self, user_id: str, channel: str, points: float) -> None:
        """Set user's loyalty points (enforces non-negative)."""
        # Prevent negative points
        if points < 0:
            logger.warning("Attempted to set negative points for user %s: %f, clamping to 0", user_id, points)
            points = 0
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO user_loyalty (user_id, channel, points)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, channel) DO UPDATE SET points = ?
                """,
                (user_id, channel.lower(), points, points)
            )
    
    def get_loyalty_leaderboard(self, channel: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get loyalty leaderboard for a channel."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM user_loyalty 
                WHERE channel = ? 
                ORDER BY points DESC 
                LIMIT ?
                """,
                (channel.lower(), limit)
            )
            return [dict(row) for row in cursor.fetchall()]
    
    # ==================== Recent Messages Methods (for Nuke) ====================
    
    def add_recent_message(
        self,
        channel: str,
        user_id: str,
        username: str,
        message: str,
        is_subscriber: bool = False,
        is_vip: bool = False,
        is_mod: bool = False
    ) -> None:
        """Add a message to recent messages cache."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO recent_messages 
                (channel, user_id, username, message, is_subscriber, is_vip, is_mod)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (channel.lower(), user_id, username, message, is_subscriber, is_vip, is_mod)
            )
            
            # Cleanup old messages (older than 2 minutes)
            cursor.execute(
                "DELETE FROM recent_messages WHERE timestamp < datetime('now', '-2 minutes')"
            )
    
    def get_recent_messages(
        self,
        channel: str,
        lookback_seconds: int = 60,
        include_subs: bool = False,
        include_vips: bool = False
    ) -> list[dict[str, Any]]:
        """Get recent messages for nuke command."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            query = """
                SELECT * FROM recent_messages 
                WHERE channel = ? 
                AND timestamp > datetime('now', '-' || ? || ' seconds')
                AND is_mod = FALSE
            """
            params = [channel.lower(), lookback_seconds]
            
            if not include_subs:
                query += " AND is_subscriber = FALSE"
            if not include_vips:
                query += " AND is_vip = FALSE"
            
            query += " ORDER BY timestamp DESC"
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def log_nuke(
        self,
        moderator: str,
        channel: str,
        pattern: str,
        action: str,
        duration: int | None,
        users_affected: int,
        users_list: list[str]
    ) -> int:
        """Log a nuke action."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO nuke_log 
                (moderator, channel, pattern, action, duration, users_affected, users_list)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (moderator, channel.lower(), pattern, action, duration, users_affected, json.dumps(users_list))
            )
            return cursor.lastrowid or 0
    
    # ==================== Filter Settings Methods ====================
    
    def get_filter_settings(self, channel: str) -> dict[str, Any]:
        """Get filter settings for a channel."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM filter_settings WHERE channel = ?", (channel.lower(),))
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            
            # Return defaults
            return {
                "channel": channel.lower(),
                "caps_enabled": True,
                "caps_min_length": 10,
                "caps_max_percent": 70,
                "emote_enabled": True,
                "emote_max_count": 15,
                "symbol_enabled": True,
                "symbol_max_percent": 50,
                "link_enabled": True,
                "length_enabled": True,
                "length_max_chars": 500,
                "repetition_enabled": True,
                "repetition_max_words": 10,
                "zalgo_enabled": True,
                "lookalike_enabled": True
            }
    
    def update_filter_settings(self, channel: str, **kwargs) -> None:
        """Update filter settings for a channel."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            current = self.get_filter_settings(channel)
            
            # Merge with current settings
            for key, value in kwargs.items():
                if key in current and value is not None:
                    current[key] = value
            
            cursor.execute(
                """
                INSERT INTO filter_settings 
                (channel, caps_enabled, caps_min_length, caps_max_percent, emote_enabled, emote_max_count,
                 symbol_enabled, symbol_max_percent, link_enabled, length_enabled, length_max_chars,
                 repetition_enabled, repetition_max_words, zalgo_enabled, lookalike_enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel) DO UPDATE SET
                    caps_enabled = excluded.caps_enabled,
                    caps_min_length = excluded.caps_min_length,
                    caps_max_percent = excluded.caps_max_percent,
                    emote_enabled = excluded.emote_enabled,
                    emote_max_count = excluded.emote_max_count,
                    symbol_enabled = excluded.symbol_enabled,
                    symbol_max_percent = excluded.symbol_max_percent,
                    link_enabled = excluded.link_enabled,
                    length_enabled = excluded.length_enabled,
                    length_max_chars = excluded.length_max_chars,
                    repetition_enabled = excluded.repetition_enabled,
                    repetition_max_words = excluded.repetition_max_words,
                    zalgo_enabled = excluded.zalgo_enabled,
                    lookalike_enabled = excluded.lookalike_enabled
                """,
                (current["channel"], current["caps_enabled"], current["caps_min_length"],
                 current["caps_max_percent"], current["emote_enabled"], current["emote_max_count"],
                 current["symbol_enabled"], current["symbol_max_percent"], current["link_enabled"],
                 current["length_enabled"], current["length_max_chars"], current["repetition_enabled"],
                 current["repetition_max_words"], current["zalgo_enabled"], current["lookalike_enabled"])
            )
    
    # ==================== Quotes Methods ====================
    
    def add_quote(
        self,
        channel: str,
        quote_text: str,
        author: str | None,
        added_by: str,
        game: str | None = None
    ) -> int:
        """
        Add a new quote to the database.
        
        Args:
            channel: Channel the quote belongs to
            quote_text: The quote text
            author: Who said the quote (optional)
            added_by: Username of who added the quote
            game: Game being played when quote was added (optional)
            
        Returns:
            int: The ID of the newly created quote
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO quotes (channel, quote_text, author, added_by, game)
                VALUES (?, ?, ?, ?, ?)
                """,
                (channel.lower(), quote_text, author, added_by, game)
            )
            return cursor.lastrowid or 0
    
    def get_quote(self, channel: str, quote_id: int) -> Optional[dict[str, Any]]:
        """
        Get a specific quote by ID.
        
        Args:
            channel: Channel to search in
            quote_id: The quote ID to retrieve
            
        Returns:
            dict | None: Quote data or None if not found
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM quotes 
                WHERE channel = ? AND id = ? AND enabled = TRUE
                """,
                (channel.lower(), quote_id)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_random_quote(self, channel: str) -> Optional[dict[str, Any]]:
        """
        Get a random quote from the channel.
        
        Args:
            channel: Channel to get quote from
            
        Returns:
            dict | None: Random quote data or None if no quotes exist
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM quotes 
                WHERE channel = ? AND enabled = TRUE
                ORDER BY RANDOM()
                LIMIT 1
                """,
                (channel.lower(),)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def delete_quote(self, channel: str, quote_id: int) -> bool:
        """
        Delete a quote by ID (soft delete - sets enabled to FALSE).
        
        Args:
            channel: Channel the quote belongs to
            quote_id: The quote ID to delete
            
        Returns:
            bool: True if quote was deleted, False if not found
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE quotes SET enabled = FALSE
                WHERE channel = ? AND id = ?
                """,
                (channel.lower(), quote_id)
            )
            return cursor.rowcount > 0
    
    def get_all_quotes(self, channel: str) -> list[dict[str, Any]]:
        """
        Get all enabled quotes for a channel.
        
        Args:
            channel: Channel to get quotes from
            
        Returns:
            list[dict]: List of all quotes
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM quotes 
                WHERE channel = ? AND enabled = TRUE
                ORDER BY id ASC
                """,
                (channel.lower(),)
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def get_quote_count(self, channel: str) -> int:
        """
        Get the total number of enabled quotes for a channel.
        
        Args:
            channel: Channel to count quotes for
            
        Returns:
            int: Number of quotes
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) as count FROM quotes 
                WHERE channel = ? AND enabled = TRUE
                """,
                (channel.lower(),)
            )
            row = cursor.fetchone()
            return row["count"] if row else 0
    
    def search_quotes(self, channel: str, search_term: str) -> list[dict[str, Any]]:
        """
        Search quotes by text content.
        
        Args:
            channel: Channel to search in
            search_term: Term to search for in quote text
            
        Returns:
            list[dict]: List of matching quotes
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM quotes 
                WHERE channel = ? AND enabled = TRUE
                AND (quote_text LIKE ? OR author LIKE ?)
                ORDER BY id ASC
                LIMIT 10
                """,
                (channel.lower(), f"%{search_term.replace(chr(37), chr(92)+chr(37)).replace(chr(95), chr(92)+chr(95))}%", f"%{search_term.replace(chr(37), chr(92)+chr(37)).replace(chr(95), chr(92)+chr(95))}%")
            )
            return [dict(row) for row in cursor.fetchall()]
    
    # ==================== Cog Settings Methods ====================
    
    def get_cog_enabled(self, channel: str, cog_name: str) -> bool:
        """
        Check if a cog is enabled for a channel.
        
        Args:
            channel: Channel name
            cog_name: Name of the cog
            
        Returns:
            bool: True if enabled (defaults to True if not set)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT enabled FROM cog_settings WHERE channel = ? AND cog_name = ?",
                (channel.lower(), cog_name.lower())
            )
            row = cursor.fetchone()
            
            # Default to enabled if no setting exists
            if row is None:
                return True
            
            return bool(row["enabled"])
    
    def set_cog_enabled(self, channel: str, cog_name: str, enabled: bool) -> None:
        """
        Set whether a cog is enabled for a channel.
        
        Args:
            channel: Channel name
            cog_name: Name of the cog
            enabled: Whether the cog should be enabled
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO cog_settings (channel, cog_name, enabled)
                VALUES (?, ?, ?)
                ON CONFLICT(channel, cog_name) DO UPDATE SET
                    enabled = excluded.enabled
                """,
                (channel.lower(), cog_name.lower(), enabled)
            )
            logger.info(
                "Cog '%s' %s for channel '%s'",
                cog_name,
                "enabled" if enabled else "disabled",
                channel
            )
    
    def get_all_cog_settings(self, channel: str) -> dict[str, bool]:
        """
        Get all cog settings for a channel.
        
        Args:
            channel: Channel name
            
        Returns:
            dict[str, bool]: Dictionary mapping cog names to enabled status
        """
        # Define all available cogs with their default enabled state
        all_cogs = {
            "admin": True,
            "fun": True,
            "moderation": True,
            "info": True,
            "clips": True,
            "automod": True,
            "customcmds": True,
            "timers": True,
            "loyalty": True,
            "nuke": True,
            "quotes": True,
            "giveaways": True,
            "songrequests": True,
        }
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT cog_name, enabled FROM cog_settings WHERE channel = ?",
                (channel.lower(),)
            )
            
            # Update defaults with stored settings
            for row in cursor.fetchall():
                cog_name = row["cog_name"].lower()
                if cog_name in all_cogs:
                    all_cogs[cog_name] = bool(row["enabled"])
        
        return all_cogs
    
    # ==================== Giveaway Methods ====================
    
    def create_giveaway(
        self,
        channel: str,
        keyword: str,
        prize: str | None,
        started_by: str,
        duration_minutes: int | None = None,
        winner_count: int = 1,
        sub_luck: float = 1.0,
        follower_only: bool = False,
        sub_only: bool = False,
        min_points: int = 0
    ) -> int:
        """
        Create a new giveaway.
        
        Args:
            channel: Channel name
            keyword: Entry keyword (e.g., "!enter")
            prize: Prize description
            started_by: Username who started the giveaway
            duration_minutes: Auto-end duration (None for manual end)
            winner_count: Number of winners to pick
            sub_luck: Subscriber luck multiplier (extra tickets)
            follower_only: Require follower status
            sub_only: Require subscriber status
            min_points: Minimum loyalty points required
            
        Returns:
            int: Giveaway ID
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            ends_at = None
            if duration_minutes:
                ends_at = (datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)).isoformat()
            
            cursor.execute(
                """
                INSERT INTO giveaways 
                (channel, keyword, prize, started_by, ends_at, winner_count, 
                 sub_luck_multiplier, follower_only, sub_only, min_points)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (channel.lower(), keyword.lower(), prize, started_by, ends_at, 
                 winner_count, sub_luck, follower_only, sub_only, min_points)
            )
            
            return cursor.lastrowid or 0
    
    def get_active_giveaway(self, channel: str) -> Optional[dict[str, Any]]:
        """
        Get the active giveaway for a channel.
        
        Args:
            channel: Channel name
            
        Returns:
            dict: Giveaway data or None if no active giveaway
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM giveaways 
                WHERE channel = ? AND status = 'active'
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (channel.lower(),)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_giveaway_by_id(self, giveaway_id: int) -> Optional[dict[str, Any]]:
        """Get a giveaway by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM giveaways WHERE id = ?", (giveaway_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def add_giveaway_entry(
        self,
        giveaway_id: int,
        user_id: str,
        username: str,
        is_sub: bool = False,
        is_vip: bool = False,
        tickets: int = 1
    ) -> bool:
        """
        Add an entry to a giveaway.
        
        Args:
            giveaway_id: Giveaway ID
            user_id: User's Twitch ID
            username: User's display name
            is_sub: Whether user is a subscriber
            is_vip: Whether user is a VIP
            tickets: Number of tickets (for weighted selection)
            
        Returns:
            bool: True if entry was added, False if already entered
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                cursor.execute(
                    """
                    INSERT INTO giveaway_entries 
                    (giveaway_id, user_id, username, is_subscriber, is_vip, tickets)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (giveaway_id, user_id, username, is_sub, is_vip, tickets)
                )
                return True
            except sqlite3.IntegrityError:
                # User already entered
                return False
    
    def get_giveaway_entries(self, giveaway_id: int) -> list[dict[str, Any]]:
        """
        Get all entries for a giveaway.
        
        Args:
            giveaway_id: Giveaway ID
            
        Returns:
            list: List of entry dicts
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM giveaway_entries 
                WHERE giveaway_id = ?
                ORDER BY entered_at
                """,
                (giveaway_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def get_entry_count(self, giveaway_id: int) -> int:
        """
        Get the number of entries for a giveaway.
        
        Args:
            giveaway_id: Giveaway ID
            
        Returns:
            int: Number of entries
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) as count FROM giveaway_entries WHERE giveaway_id = ?",
                (giveaway_id,)
            )
            row = cursor.fetchone()
            return row["count"] if row else 0
    
    def pick_winner(
        self,
        giveaway_id: int,
        exclude_user_ids: list[str] | None = None
    ) -> Optional[dict[str, Any]]:
        """
        Pick a random winner from giveaway entries (weighted by tickets).
        
        Args:
            giveaway_id: Giveaway ID
            exclude_user_ids: List of user IDs to exclude (previous winners)
            
        Returns:
            dict: Winner entry data or None if no eligible entries
        """
        import random
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get all entries
            query = "SELECT * FROM giveaway_entries WHERE giveaway_id = ?"
            params: list[Any] = [giveaway_id]
            
            if exclude_user_ids:
                placeholders = ",".join("?" * len(exclude_user_ids))
                query += f" AND user_id NOT IN ({placeholders})"
                params.extend(exclude_user_ids)
            
            cursor.execute(query, params)
            entries = [dict(row) for row in cursor.fetchall()]
            
            if not entries:
                return None
            
            # Build weighted list
            weighted_entries: list[dict[str, Any]] = []
            for entry in entries:
                tickets = entry.get("tickets", 1)
                for _ in range(tickets):
                    weighted_entries.append(entry)
            
            # Pick random winner
            return random.choice(weighted_entries)
    
    def add_giveaway_winner(
        self,
        giveaway_id: int,
        user_id: str,
        username: str
    ) -> None:
        """
        Record a giveaway winner.
        
        Args:
            giveaway_id: Giveaway ID
            user_id: Winner's user ID
            username: Winner's username
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO giveaway_winners (giveaway_id, user_id, username)
                VALUES (?, ?, ?)
                """,
                (giveaway_id, user_id, username)
            )
    
    def get_giveaway_winners(self, giveaway_id: int) -> list[dict[str, Any]]:
        """Get all winners for a giveaway."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM giveaway_winners 
                WHERE giveaway_id = ?
                ORDER BY won_at
                """,
                (giveaway_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def end_giveaway(self, giveaway_id: int) -> None:
        """
        End a giveaway (mark as ended).
        
        Args:
            giveaway_id: Giveaway ID
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE giveaways SET status = 'ended' WHERE id = ?",
                (giveaway_id,)
            )
    
    def cancel_giveaway(self, giveaway_id: int) -> None:
        """
        Cancel a giveaway without picking winners.
        
        Args:
            giveaway_id: Giveaway ID
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE giveaways SET status = 'cancelled' WHERE id = ?",
                (giveaway_id,)
            )
    
    def get_giveaway_history(
        self,
        channel: str,
        limit: int = 10
    ) -> list[dict[str, Any]]:
        """
        Get giveaway history for a channel.
        
        Args:
            channel: Channel name
            limit: Maximum number of giveaways to return
            
        Returns:
            list: List of giveaway dicts
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM giveaways 
                WHERE channel = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (channel.lower(), limit)
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def check_expired_giveaways(self) -> list[dict[str, Any]]:
        """
        Get all active giveaways that have expired.
        
        Returns:
            list: List of expired giveaway dicts
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                SELECT * FROM giveaways 
                WHERE status = 'active' 
                AND ends_at IS NOT NULL 
                AND ends_at <= ?
                """,
                (now,)
            )
            return [dict(row) for row in cursor.fetchall()]

    # ==================== Banned Words Methods ====================
    
    def add_banned_word(
        self,
        channel: str,
        word: str,
        is_regex: bool = False,
        action: str = "delete",
        duration: int = 600,
        added_by: str | None = None
    ) -> int:
        """
        Add a banned word/phrase to the database.
        
        Args:
            channel: Channel name
            word: Word or phrase to ban (or regex pattern if is_regex=True)
            is_regex: Whether the word is a regex pattern
            action: Action to take (delete, timeout, ban)
            duration: Timeout duration in seconds (for timeout action)
            added_by: Username who added the word
            
        Returns:
            int: ID of the new banned word entry, or 0 if already exists
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                cursor.execute(
                    """
                    INSERT INTO banned_words 
                    (channel, word, is_regex, action, duration, added_by)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (channel.lower(), word, is_regex, action, duration, added_by)
                )
                logger.info(
                    "Added banned word '%s' for channel %s (regex=%s, action=%s)",
                    word[:30], channel, is_regex, action
                )
                return cursor.lastrowid or 0
            except Exception as e:
                logger.warning("Failed to add banned word '%s': %s", word[:30], e)
                return 0
    
    def remove_banned_word(self, channel: str, word: str) -> bool:
        """
        Remove a banned word from the database.
        
        Args:
            channel: Channel name
            word: Word to remove
            
        Returns:
            bool: True if word was removed, False if not found
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM banned_words WHERE channel = ? AND word = ?",
                (channel.lower(), word)
            )
            removed = cursor.rowcount > 0
            if removed:
                logger.info("Removed banned word '%s' for channel %s", word[:30], channel)
            return removed
    
    def remove_banned_word_by_id(self, word_id: int) -> bool:
        """
        Remove a banned word by its ID.
        
        Args:
            word_id: ID of the banned word entry
            
        Returns:
            bool: True if word was removed
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM banned_words WHERE id = ?", (word_id,))
            return cursor.rowcount > 0
    
    def get_banned_words(self, channel: str, enabled_only: bool = True) -> list[dict[str, Any]]:
        """
        Get all banned words for a channel.
        
        Args:
            channel: Channel name
            enabled_only: Only return enabled words
            
        Returns:
            list: List of banned word dicts
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if enabled_only:
                cursor.execute(
                    """
                    SELECT * FROM banned_words 
                    WHERE channel = ? AND enabled = TRUE
                    ORDER BY word
                    """,
                    (channel.lower(),)
                )
            else:
                cursor.execute(
                    """
                    SELECT * FROM banned_words 
                    WHERE channel = ?
                    ORDER BY word
                    """,
                    (channel.lower(),)
                )
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_banned_word_by_id(self, word_id: int) -> dict[str, Any] | None:
        """
        Get a banned word by ID.
        
        Args:
            word_id: ID of the banned word
            
        Returns:
            dict | None: Banned word data or None
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM banned_words WHERE id = ?", (word_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def update_banned_word(
        self,
        channel: str,
        word: str,
        is_regex: bool | None = None,
        action: str | None = None,
        duration: int | None = None,
        enabled: bool | None = None
    ) -> bool:
        """
        Update a banned word's settings.
        
        Args:
            channel: Channel name
            word: Word to update
            is_regex: New regex setting (optional)
            action: New action (optional)
            duration: New duration (optional)
            enabled: New enabled status (optional)
            
        Returns:
            bool: True if word was updated
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            updates = []
            params = []
            
            if is_regex is not None:
                updates.append("is_regex = ?")
                params.append(is_regex)
            if action is not None:
                updates.append("action = ?")
                params.append(action)
            if duration is not None:
                updates.append("duration = ?")
                params.append(duration)
            if enabled is not None:
                updates.append("enabled = ?")
                params.append(enabled)
            
            if not updates:
                return False
            
            params.extend([channel.lower(), word])
            
            cursor.execute(
                f"UPDATE banned_words SET {', '.join(updates)} WHERE channel = ? AND word = ?",
                params
            )
            
            return cursor.rowcount > 0
    
    def update_banned_word_by_id(
        self,
        word_id: int,
        word: str | None = None,
        is_regex: bool | None = None,
        action: str | None = None,
        duration: int | None = None,
        enabled: bool | None = None
    ) -> bool:
        """
        Update a banned word by ID.
        
        Args:
            word_id: ID of the banned word
            word: New word/pattern (optional)
            is_regex: New regex setting (optional)
            action: New action (optional)
            duration: New duration (optional)
            enabled: New enabled status (optional)
            
        Returns:
            bool: True if word was updated
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            updates = []
            params = []
            
            if word is not None:
                updates.append("word = ?")
                params.append(word)
            if is_regex is not None:
                updates.append("is_regex = ?")
                params.append(is_regex)
            if action is not None:
                updates.append("action = ?")
                params.append(action)
            if duration is not None:
                updates.append("duration = ?")
                params.append(duration)
            if enabled is not None:
                updates.append("enabled = ?")
                params.append(enabled)
            
            if not updates:
                return False
            
            params.append(word_id)
            
            cursor.execute(
                f"UPDATE banned_words SET {', '.join(updates)} WHERE id = ?",
                params
            )
            
            return cursor.rowcount > 0
    
    def toggle_banned_word(self, word_id: int) -> bool | None:
        """
        Toggle a banned word's enabled status.
        
        Args:
            word_id: ID of the banned word
            
        Returns:
            bool | None: New enabled status, or None if not found
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT enabled FROM banned_words WHERE id = ?", (word_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            new_status = not bool(row["enabled"])
            cursor.execute(
                "UPDATE banned_words SET enabled = ? WHERE id = ?",
                (new_status, word_id)
            )
            
            return new_status
    
    def check_banned_words(self, channel: str, message: str) -> list[dict[str, Any]]:
        """
        Check a message against banned words for a channel.
        
        Args:
            channel: Channel name
            message: Message content to check
            
        Returns:
            list: List of matched banned word dicts with match info
        """
        import re as regex_module
        
        banned_words = self.get_banned_words(channel, enabled_only=True)
        matches = []
        message_lower = message.lower()
        
        for banned in banned_words:
            word = banned["word"]
            is_regex = banned["is_regex"]
            
            try:
                if is_regex:
                    # Regex pattern matching
                    pattern = regex_module.compile(word, regex_module.IGNORECASE)
                    match = pattern.search(message)
                    if match:
                        matches.append({
                            **banned,
                            "matched_text": match.group(),
                            "match_type": "regex"
                        })
                else:
                    # Exact word/phrase matching (case-insensitive)
                    word_lower = word.lower()
                    if word_lower in message_lower:
                        matches.append({
                            **banned,
                            "matched_text": word,
                            "match_type": "exact"
                        })
            except regex_module.error as e:
                logger.warning("Invalid regex pattern '%s': %s", word[:30], e)
                continue
        
        return matches
    
    def get_banned_words_count(self, channel: str) -> int:
        """
        Get count of banned words for a channel.
        
        Args:
            channel: Channel name
            
        Returns:
            int: Number of banned words
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) as count FROM banned_words WHERE channel = ?",
                (channel.lower(),)
            )
            row = cursor.fetchone()
            return row["count"] if row else 0
    
    def export_banned_words(self, channel: str) -> list[dict[str, Any]]:
        """
        Export banned words for backup/transfer.
        
        Args:
            channel: Channel name
            
        Returns:
            list: List of banned words with all fields
        """
        return self.get_banned_words(channel, enabled_only=False)
    
    def import_banned_words(
        self,
        channel: str,
        words: list[dict[str, Any]],
        added_by: str = "import"
    ) -> tuple[int, int]:
        """
        Import banned words from a list.
        
        Args:
            channel: Channel name
            words: List of word dicts with at least 'word' key
            added_by: Username to record as importer
            
        Returns:
            tuple: (added_count, skipped_count)
        """
        added = 0
        skipped = 0
        
        for word_data in words:
            word = word_data.get("word", "").strip()
            if not word:
                skipped += 1
                continue
            
            result = self.add_banned_word(
                channel=channel,
                word=word,
                is_regex=word_data.get("is_regex", False),
                action=word_data.get("action", "delete"),
                duration=word_data.get("duration", 600),
                added_by=added_by
            )
            
            if result > 0:
                added += 1
            else:
                skipped += 1
        
        logger.info(
            "Imported banned words for %s: %d added, %d skipped",
            channel, added, skipped
        )
        return added, skipped


# Global database instance
_db: Optional[DatabaseManager] = None


def get_database() -> DatabaseManager:
    """Get the global database manager instance."""
    global _db
    if _db is None:
        _db = DatabaseManager()
    return _db
