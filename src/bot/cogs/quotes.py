"""
Quotes cog for Twitch bot.

Provides a quote system with:
- Adding quotes with optional author
- Random quote retrieval
- Quote search functionality
- Auto-capture of current game
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

from twitchio.ext import commands
from twitchio.ext.commands import Context

from bot.utils.database import get_database, DatabaseManager
from bot.utils.logging import get_logger
from bot.utils.permissions import is_moderator, cooldown, CooldownBucket

if TYPE_CHECKING:
    from bot.bot import TwitchBot

logger = get_logger(__name__)

# Maximum allowed quote length to prevent abuse
MAX_QUOTE_LENGTH = 500


class Quotes(commands.Cog):
    """
    Quotes cog for memorable moments.
    
    Features:
    - Add quotes with !addquote
    - Get random or specific quotes with !quote
    - Search quotes with !searchquote
    - Auto-captures current game when adding
    """
    
    def __init__(self, bot: TwitchBot) -> None:
        """Initialize the quotes cog."""
        self.bot = bot
        self.db: DatabaseManager = get_database()
        logger.info("Quotes cog initialized")
    
    def _format_quote(self, quote: dict) -> str:
        """
        Format a quote for display.
        
        Args:
            quote: Quote dictionary from database
            
        Returns:
            str: Formatted quote string
        """
        quote_id = quote.get("id", 0)
        text = quote.get("quote_text", "")
        author = quote.get("author") or "Unknown"
        game = quote.get("game")
        
        # Build the formatted string
        formatted = f'Quote #{quote_id}: "{text}" - {author}'
        
        if game:
            formatted += f" ({game})"
        
        return formatted
    
    def _parse_quote_input(self, text: str) -> tuple[str, Optional[str]]:
        """
        Parse quote input to extract quote text and optional author.
        
        Supports formats:
        - "quote text" -Author
        - "quote text" - Author
        - "quote text"
        - quote text -Author
        - quote text
        
        Args:
            text: Raw input text
            
        Returns:
            tuple[str, Optional[str]]: (quote_text, author)
        """
        text = text.strip()
        
        # Try to match quoted text with author: "text" -Author or "text" - Author
        quoted_with_author = re.match(r'^"(.+?)"\s*-\s*(.+)$', text)
        if quoted_with_author:
            return quoted_with_author.group(1).strip(), quoted_with_author.group(2).strip()
        
        # Try to match just quoted text: "text"
        quoted_only = re.match(r'^"(.+?)"$', text)
        if quoted_only:
            return quoted_only.group(1).strip(), None
        
        # Try to match unquoted text with author: text -Author
        unquoted_with_author = re.match(r'^(.+?)\s+-\s*(.+)$', text)
        if unquoted_with_author:
            return unquoted_with_author.group(1).strip(), unquoted_with_author.group(2).strip()
        
        # Just plain text, no author
        return text, None
    
    async def _get_current_game(self, channel_name: str) -> Optional[str]:
        """
        Get the current game being played on the channel.
        
        Args:
            channel_name: Name of the channel
            
        Returns:
            Optional[str]: Game name or None if not streaming/available
        """
        try:
            # Try to get channel info from Twitch API
            channels = await self.bot.fetch_channels([channel_name])
            if channels and len(channels) > 0:
                game_name = channels[0].game_name
                if game_name:
                    return game_name
        except Exception as e:
            logger.debug("Could not fetch current game for %s: %s", channel_name, e)
        
        return None
    
    @commands.command(name="addquote", aliases=["quoteadd"])
    @is_moderator()
    async def add_quote(self, ctx: Context, *, text: str = "") -> None:
        """
        Add a new quote. Usage: !addquote "quote text" -Author
        
        Moderator only. Auto-captures current game if streaming.
        Maximum quote length is 500 characters.
        """
        if not text:
            await ctx.send(f'@{ctx.author.name} Usage: !addquote "quote text" -Author')
            return
        
        channel_name = ctx.channel.name
        
        # Parse the quote text and author
        quote_text, author = self._parse_quote_input(text)
        
        if not quote_text:
            await ctx.send(f"@{ctx.author.name} Please provide a quote to add.")
            return
        
        # Check quote length
        if len(quote_text) > MAX_QUOTE_LENGTH:
            await ctx.send(f"@{ctx.author.name} Quote too long! Maximum {MAX_QUOTE_LENGTH} characters.")
            return
        
        # Try to get current game
        game = await self._get_current_game(channel_name)
        
        # Add the quote to database
        quote_id = self.db.add_quote(
            channel=channel_name,
            quote_text=quote_text,
            author=author,
            added_by=ctx.author.name,
            game=game
        )
        
        logger.info(
            "Quote #%d added by %s in %s: %s",
            quote_id, ctx.author.name, channel_name, quote_text[:50]
        )
        
        await ctx.send(f"@{ctx.author.name} Quote #{quote_id} added!")
    
    @commands.command(name="quote", aliases=["q"])
    @cooldown(rate=5.0, bucket=CooldownBucket.USER)
    async def get_quote(self, ctx: Context, quote_id: str = "") -> None:
        """
        Get a random quote or a specific quote by ID. Usage: !quote [id]
        """
        channel_name = ctx.channel.name
        
        if quote_id:
            # Try to get specific quote
            try:
                qid = int(quote_id)
            except ValueError:
                await ctx.send(f"@{ctx.author.name} Quote ID must be a number.")
                return
            
            quote = self.db.get_quote(channel_name, qid)
            
            if not quote:
                await ctx.send(f"@{ctx.author.name} Quote #{qid} not found.")
                return
        else:
            # Get random quote
            quote = self.db.get_random_quote(channel_name)
            
            if not quote:
                await ctx.send(f"@{ctx.author.name} No quotes found. Add some with !addquote")
                return
        
        formatted = self._format_quote(quote)
        await ctx.send(formatted)
    
    @commands.command(name="delquote", aliases=["deletequote", "rmquote"])
    @is_moderator()
    async def delete_quote(self, ctx: Context, quote_id: str = "") -> None:
        """
        Delete a quote by ID. Usage: !delquote <id>
        
        Moderator only.
        """
        if not quote_id:
            await ctx.send(f"@{ctx.author.name} Usage: !delquote <id>")
            return
        
        try:
            qid = int(quote_id)
        except ValueError:
            await ctx.send(f"@{ctx.author.name} Quote ID must be a number.")
            return
        
        channel_name = ctx.channel.name
        
        # Check if quote exists first
        quote = self.db.get_quote(channel_name, qid)
        if not quote:
            await ctx.send(f"@{ctx.author.name} Quote #{qid} not found.")
            return
        
        # Delete the quote
        success = self.db.delete_quote(channel_name, qid)
        
        if success:
            logger.info(
                "Quote #%d deleted by %s in %s",
                qid, ctx.author.name, channel_name
            )
            await ctx.send(f"@{ctx.author.name} Quote #{qid} deleted.")
        else:
            await ctx.send(f"@{ctx.author.name} Failed to delete quote #{qid}.")
    
    @commands.command(name="quotes", aliases=["quotecount"])
    async def quote_count(self, ctx: Context) -> None:
        """Show the total number of quotes in the database."""
        channel_name = ctx.channel.name
        count = self.db.get_quote_count(channel_name)
        
        if count == 0:
            await ctx.send(f"@{ctx.author.name} There are no quotes yet. Add some with !addquote")
        elif count == 1:
            await ctx.send(f"@{ctx.author.name} There is 1 quote in the database.")
        else:
            await ctx.send(f"@{ctx.author.name} There are {count:,} quotes in the database.")
    
    @commands.command(name="searchquote", aliases=["findquote", "quotesearch"])
    @cooldown(rate=5.0, bucket=CooldownBucket.USER)
    async def search_quote(self, ctx: Context, *, search_term: str = "") -> None:
        """
        Search quotes by text. Usage: !searchquote <term>
        """
        if not search_term:
            await ctx.send(f"@{ctx.author.name} Usage: !searchquote <term>")
            return
        
        channel_name = ctx.channel.name
        
        # Search for quotes
        results = self.db.search_quotes(channel_name, search_term)
        
        if not results:
            await ctx.send(f"@{ctx.author.name} No quotes found matching '{search_term}'")
            return
        
        # Show results (limit to first 3 to avoid spam)
        if len(results) == 1:
            formatted = self._format_quote(results[0])
            await ctx.send(formatted)
        else:
            # Show IDs of matching quotes
            quote_ids = [f"#{q['id']}" for q in results[:5]]
            remaining = len(results) - 5 if len(results) > 5 else 0
            
            msg = f"@{ctx.author.name} Found {len(results)} quotes: {', '.join(quote_ids)}"
            if remaining > 0:
                msg += f" (+{remaining} more)"
            msg += " - Use !quote <id> to view"
            
            await ctx.send(msg)
    
    @commands.command(name="lastquote", aliases=["latestquote"])
    async def last_quote(self, ctx: Context) -> None:
        """Show the most recently added quote."""
        channel_name = ctx.channel.name
        
        # Get all quotes and find the last one (highest ID)
        quotes = self.db.get_all_quotes(channel_name)
        
        if not quotes:
            await ctx.send(f"@{ctx.author.name} No quotes found. Add some with !addquote")
            return
        
        # Get the last quote (highest ID)
        last_quote = max(quotes, key=lambda q: q["id"])
        formatted = self._format_quote(last_quote)
        await ctx.send(formatted)


def prepare(bot: TwitchBot) -> None:
    """Prepare the cog for loading."""
    bot.add_cog(Quotes(bot))
