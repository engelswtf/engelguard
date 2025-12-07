"""
Utility modules for the Twitch bot.

Provides:
- logging: Logging setup with secret filtering
- permissions: Permission decorators for commands
- database: SQLite database manager for automod
- spam_detector: Spam detection system
- strikes: Strike/warning system
- variables: Variable parser for custom commands
"""

from bot.utils.logging import get_logger, setup_logging
from bot.utils.permissions import (
    is_moderator,
    is_owner,
    is_subscriber,
    cooldown,
    CooldownBucket,
)
from bot.utils.database import get_database, DatabaseManager
from bot.utils.spam_detector import get_spam_detector, SpamDetector, SpamResult, ModAction
from bot.utils.strikes import get_strike_manager, StrikeManager, StrikeResult, StrikeAction
from bot.utils.variables import get_variable_parser, VariableParser, VARIABLE_DOCS

__all__ = [
    "get_logger",
    "setup_logging",
    "is_moderator",
    "is_owner",
    "is_subscriber",
    "cooldown",
    "CooldownBucket",
    "get_database",
    "DatabaseManager",
    "get_spam_detector",
    "SpamDetector",
    "SpamResult",
    "ModAction",
    "get_strike_manager",
    "StrikeManager",
    "StrikeResult",
    "StrikeAction",
    "get_variable_parser",
    "VariableParser",
    "VARIABLE_DOCS",
]
