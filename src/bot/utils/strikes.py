"""
Strike/Warning system for Twitch chat moderation.

Provides escalating punishment system:
- Strike 1: Warning
- Strike 2: 1 minute timeout
- Strike 3: 10 minute timeout
- Strike 4: 1 hour timeout
- Strike 5: Ban (unless subscriber)

Strikes expire after configurable days (default 30).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Optional, Any

from bot.utils.database import get_database, DatabaseManager
from bot.utils.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class StrikeAction(Enum):
    """Actions that can be taken for strikes."""
    WARN = "warn"
    TIMEOUT = "timeout"
    BAN = "ban"


@dataclass
class StrikeResult:
    """Result of adding a strike."""
    strike_number: int
    action: StrikeAction
    duration: int  # seconds, 0 for warn/ban
    message: str
    should_ban: bool = False


class StrikeManager:
    """
    Manages the strike/warning system for users.
    
    Features:
    - Escalating punishments
    - Configurable expiration
    - Subscriber protection (no auto-ban)
    - Full audit trail
    """
    
    # Default escalation configuration
    DEFAULT_ESCALATION = {
        1: {"action": StrikeAction.WARN, "duration": 0, "message": "@{user} Warning: {reason}"},
        2: {"action": StrikeAction.TIMEOUT, "duration": 60, "message": "@{user} Strike 2: 1 minute timeout"},
        3: {"action": StrikeAction.TIMEOUT, "duration": 600, "message": "@{user} Strike 3: 10 minute timeout"},
        4: {"action": StrikeAction.TIMEOUT, "duration": 3600, "message": "@{user} Strike 4: 1 hour timeout"},
        5: {"action": StrikeAction.BAN, "duration": 0, "message": "@{user} Strike 5: Banned"},
    }
    
    def __init__(
        self,
        expire_days: int = 30,
        max_strikes_before_ban: int = 5,
        subscriber_max_strike: int = 4
    ) -> None:
        """
        Initialize the strike manager.
        
        Args:
            expire_days: Days until strikes expire
            max_strikes_before_ban: Maximum strikes before ban
            subscriber_max_strike: Maximum strike level for subscribers (no auto-ban)
        """
        self.db: DatabaseManager = get_database()
        self.expire_days = int(os.getenv("STRIKE_EXPIRE_DAYS", expire_days))
        self.max_strikes = int(os.getenv("STRIKE_MAX_BEFORE_BAN", max_strikes_before_ban))
        self.subscriber_max = subscriber_max_strike
        self.escalation = self.DEFAULT_ESCALATION.copy()
        
        logger.info(
            "StrikeManager initialized: expire=%d days, max=%d strikes",
            self.expire_days, self.max_strikes
        )
    
    def get_strikes(self, user_id: str) -> dict[str, Any]:
        """
        Get current strike information for a user.
        
        Args:
            user_id: Twitch user ID
            
        Returns:
            dict: Strike information
        """
        return self.db.get_user_strikes(user_id)
    
    def add_strike(
        self,
        user_id: str,
        username: str,
        reason: str,
        moderator: str,
        channel: str,
        is_subscriber: bool = False
    ) -> StrikeResult:
        """
        Add a strike to a user and determine action.
        
        Args:
            user_id: Twitch user ID
            username: Twitch username
            reason: Reason for the strike
            moderator: Moderator who issued the strike
            channel: Channel where strike occurred
            is_subscriber: Whether user is a subscriber
            
        Returns:
            StrikeResult: The result including action to take
        """
        # Get escalation for this strike level
        current = self.db.get_user_strikes(user_id)
        new_count = current["strike_count"] + 1
        
        # Cap at max strikes
        effective_strike = min(new_count, self.max_strikes)
        
        # Get action for this strike level
        escalation = self.escalation.get(effective_strike, self.escalation[self.max_strikes])
        action = escalation["action"]
        duration = escalation["duration"]
        message_template = escalation["message"]
        
        # Subscriber protection - cap at timeout, no auto-ban
        should_ban = False
        if action == StrikeAction.BAN:
            if is_subscriber:
                # Downgrade to max timeout for subscribers
                action = StrikeAction.TIMEOUT
                duration = 3600  # 1 hour
                message_template = "@{user} Strike {strike}: 1 hour timeout (subscriber protection)"
            else:
                should_ban = True
        
        # Format message
        message = message_template.format(
            user=username,
            reason=reason,
            strike=new_count
        )
        
        # Record the strike
        action_str = f"{action.value}:{duration}" if duration else action.value
        self.db.add_strike(
            user_id=user_id,
            username=username,
            reason=reason,
            action_taken=action_str,
            moderator=moderator,
            channel=channel,
            expire_days=self.expire_days
        )
        
        logger.info(
            "Strike added: user=%s, strike=%d, action=%s, reason=%s",
            username, new_count, action.value, reason
        )
        
        return StrikeResult(
            strike_number=new_count,
            action=action,
            duration=duration,
            message=message,
            should_ban=should_ban
        )
    
    def clear_strikes(self, user_id: str, moderator: str = "system") -> bool:
        """
        Clear all strikes for a user.
        
        Args:
            user_id: Twitch user ID
            moderator: Who cleared the strikes
            
        Returns:
            bool: True if strikes were cleared
        """
        result = self.db.clear_strikes(user_id)
        if result:
            logger.info("Strikes cleared for user %s by %s", user_id, moderator)
        return result
    
    def get_history(self, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """
        Get strike history for a user.
        
        Args:
            user_id: Twitch user ID
            limit: Maximum records to return
            
        Returns:
            list: Strike history records
        """
        return self.db.get_strike_history(user_id, limit)
    
    def format_strikes_info(self, user_id: str, username: str) -> str:
        """
        Format strike information for display.
        
        Args:
            user_id: Twitch user ID
            username: Twitch username
            
        Returns:
            str: Formatted strike information
        """
        strikes = self.get_strikes(user_id)
        count = strikes.get("strike_count", 0)
        
        if count == 0:
            return f"@{username} has no strikes."
        
        last_strike = strikes.get("last_strike", "Unknown")
        last_reason = strikes.get("last_reason", "No reason recorded")
        expires = strikes.get("expires_at", "")
        
        # Calculate days until expiration
        expire_str = ""
        if expires:
            try:
                if isinstance(expires, str):
                    expires_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                else:
                    expires_dt = expires
                days_left = (expires_dt.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days
                if days_left > 0:
                    expire_str = f" (expires in {days_left} days)"
            except (ValueError, AttributeError):
                pass
        
        return (
            f"@{username}: {count}/{self.max_strikes} strikes{expire_str}. "
            f"Last: {last_reason[:50]}"
        )


# Global strike manager instance
_strike_manager: Optional[StrikeManager] = None


def get_strike_manager() -> StrikeManager:
    """Get the global strike manager instance."""
    global _strike_manager
    if _strike_manager is None:
        _strike_manager = StrikeManager()
    return _strike_manager
