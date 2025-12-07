"""
EngelGuard - A production-ready Twitch chat bot built with TwitchIO.

This package provides a modular, extensible Twitch bot with:
- Cog-based command organization
- Permission system for moderators and owners
- Configurable logging with secret filtering
- Fun, moderation, info, and admin commands
"""

from bot.bot import TwitchBot
from bot.config import Config, load_config

__version__ = "1.0.0"
__author__ = "ogengels"
__all__ = ["TwitchBot", "Config", "load_config", "main"]


def main() -> None:
    """Entry point for the Twitch bot."""
    import asyncio
    import signal
    import sys

    from bot.utils.logging import setup_logging, get_logger

    # Load configuration
    try:
        config = load_config()
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    # Setup logging
    setup_logging(config)
    logger = get_logger(__name__)

    logger.info("Starting EngelGuard v%s", __version__)

    # Create bot instance
    bot = TwitchBot(config)

    # Handle graceful shutdown
    def signal_handler(sig: int, frame: object) -> None:
        logger.info("Received shutdown signal, stopping bot...")
        asyncio.create_task(bot.close())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run the bot
    try:
        bot.run()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception("Bot crashed with error: %s", e)
        sys.exit(1)
    finally:
        logger.info("Bot shutdown complete")
