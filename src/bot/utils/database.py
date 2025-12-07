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
        """Update user's loyalty data."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                """
                INSERT INTO user_loyalty (user_id, username, channel, points, watch_time_minutes, message_count, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, channel) DO UPDATE SET
                    username = excluded.username,
                    points = user_loyalty.points + ?,
                    watch_time_minutes = user_loyalty.watch_time_minutes + ?,
                    message_count = user_loyalty.message_count + ?,
                    last_seen = CURRENT_TIMESTAMP
                """,
                (user_id, username, channel.lower(), points_delta, watch_time_delta, message_count_delta,
                 points_delta, watch_time_delta, message_count_delta)
            )
            
            return self.get_user_loyalty(user_id, channel)
    
    def set_user_points(self, user_id: str, channel: str, points: float) -> None:
        """Set user's points to a specific value."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE user_loyalty SET points = ? WHERE user_id = ? AND channel = ?",
                (points, user_id, channel.lower())
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


# Global database instance
_db: Optional[DatabaseManager] = None


def get_database() -> DatabaseManager:
    """Get the global database manager instance."""
    global _db
    if _db is None:
        _db = DatabaseManager()
    return _db
