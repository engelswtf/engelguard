"""
Tests for the Quotes cog.

Tests:
- Quote parsing (text and author extraction)
- Database operations (add, get, delete, search)
- Quote formatting
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestQuoteParsing(unittest.TestCase):
    """Test quote input parsing."""
    
    def setUp(self) -> None:
        """Set up test fixtures."""
        # Create a mock Quotes cog for testing parsing
        from bot.cogs.quotes import Quotes
        
        self.mock_bot = MagicMock()
        self.quotes_cog = Quotes(self.mock_bot)
    
    def test_parse_quoted_with_author(self) -> None:
        """Test parsing quoted text with author."""
        text, author = self.quotes_cog._parse_quote_input('"I can\'t believe that worked!" -Streamer')
        self.assertEqual(text, "I can't believe that worked!")
        self.assertEqual(author, "Streamer")
    
    def test_parse_quoted_with_author_space(self) -> None:
        """Test parsing quoted text with author and space before dash."""
        text, author = self.quotes_cog._parse_quote_input('"Hello world" - TestUser')
        self.assertEqual(text, "Hello world")
        self.assertEqual(author, "TestUser")
    
    def test_parse_quoted_no_author(self) -> None:
        """Test parsing quoted text without author."""
        text, author = self.quotes_cog._parse_quote_input('"Just a quote"')
        self.assertEqual(text, "Just a quote")
        self.assertIsNone(author)
    
    def test_parse_unquoted_with_author(self) -> None:
        """Test parsing unquoted text with author."""
        text, author = self.quotes_cog._parse_quote_input('This is a quote - Author')
        self.assertEqual(text, "This is a quote")
        self.assertEqual(author, "Author")
    
    def test_parse_plain_text(self) -> None:
        """Test parsing plain text without quotes or author."""
        text, author = self.quotes_cog._parse_quote_input('Just some plain text')
        self.assertEqual(text, "Just some plain text")
        self.assertIsNone(author)
    
    def test_parse_empty_string(self) -> None:
        """Test parsing empty string."""
        text, author = self.quotes_cog._parse_quote_input('')
        self.assertEqual(text, "")
        self.assertIsNone(author)
    
    def test_parse_whitespace(self) -> None:
        """Test parsing whitespace is trimmed."""
        text, author = self.quotes_cog._parse_quote_input('  "Quote with spaces"  -  Author  ')
        self.assertEqual(text, "Quote with spaces")
        self.assertEqual(author, "Author")


class TestQuoteFormatting(unittest.TestCase):
    """Test quote formatting."""
    
    def setUp(self) -> None:
        """Set up test fixtures."""
        from bot.cogs.quotes import Quotes
        
        self.mock_bot = MagicMock()
        self.quotes_cog = Quotes(self.mock_bot)
    
    def test_format_quote_with_all_fields(self) -> None:
        """Test formatting quote with all fields."""
        quote = {
            "id": 42,
            "quote_text": "I can't believe that worked!",
            "author": "Streamer",
            "game": "Minecraft"
        }
        formatted = self.quotes_cog._format_quote(quote)
        self.assertEqual(
            formatted,
            'Quote #42: "I can\'t believe that worked!" - Streamer (Minecraft)'
        )
    
    def test_format_quote_no_game(self) -> None:
        """Test formatting quote without game."""
        quote = {
            "id": 1,
            "quote_text": "Hello world",
            "author": "TestUser",
            "game": None
        }
        formatted = self.quotes_cog._format_quote(quote)
        self.assertEqual(formatted, 'Quote #1: "Hello world" - TestUser')
    
    def test_format_quote_no_author(self) -> None:
        """Test formatting quote without author (defaults to Unknown)."""
        quote = {
            "id": 5,
            "quote_text": "Anonymous quote",
            "author": None,
            "game": "Just Chatting"
        }
        formatted = self.quotes_cog._format_quote(quote)
        self.assertEqual(formatted, 'Quote #5: "Anonymous quote" - Unknown (Just Chatting)')
    
    def test_format_quote_minimal(self) -> None:
        """Test formatting quote with minimal fields."""
        quote = {
            "id": 10,
            "quote_text": "Minimal quote",
            "author": None,
            "game": None
        }
        formatted = self.quotes_cog._format_quote(quote)
        self.assertEqual(formatted, 'Quote #10: "Minimal quote" - Unknown')


class TestQuoteDatabaseOperations(unittest.TestCase):
    """Test quote database operations."""
    
    def setUp(self) -> None:
        """Set up test fixtures with temporary database."""
        # Create temporary database
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
        
        # Patch the database path
        from bot.utils.database import DatabaseManager
        self.db = DatabaseManager(db_path=self.temp_db.name)
    
    def tearDown(self) -> None:
        """Clean up temporary database."""
        os.unlink(self.temp_db.name)
    
    def test_add_quote(self) -> None:
        """Test adding a quote."""
        quote_id = self.db.add_quote(
            channel="testchannel",
            quote_text="Test quote",
            author="TestAuthor",
            added_by="TestMod",
            game="TestGame"
        )
        
        self.assertIsInstance(quote_id, int)
        self.assertGreater(quote_id, 0)
    
    def test_get_quote(self) -> None:
        """Test getting a specific quote."""
        quote_id = self.db.add_quote(
            channel="testchannel",
            quote_text="Specific quote",
            author="Author",
            added_by="Mod",
            game="Game"
        )
        
        quote = self.db.get_quote("testchannel", quote_id)
        
        self.assertIsNotNone(quote)
        self.assertEqual(quote["quote_text"], "Specific quote")
        self.assertEqual(quote["author"], "Author")
        self.assertEqual(quote["game"], "Game")
    
    def test_get_quote_not_found(self) -> None:
        """Test getting a non-existent quote."""
        quote = self.db.get_quote("testchannel", 99999)
        self.assertIsNone(quote)
    
    def test_get_quote_wrong_channel(self) -> None:
        """Test getting a quote from wrong channel."""
        quote_id = self.db.add_quote(
            channel="channel1",
            quote_text="Channel 1 quote",
            author="Author",
            added_by="Mod"
        )
        
        # Try to get from different channel
        quote = self.db.get_quote("channel2", quote_id)
        self.assertIsNone(quote)
    
    def test_get_random_quote(self) -> None:
        """Test getting a random quote."""
        # Add some quotes
        for i in range(5):
            self.db.add_quote(
                channel="testchannel",
                quote_text=f"Quote {i}",
                author=f"Author{i}",
                added_by="Mod"
            )
        
        quote = self.db.get_random_quote("testchannel")
        
        self.assertIsNotNone(quote)
        self.assertIn("quote_text", quote)
    
    def test_get_random_quote_empty(self) -> None:
        """Test getting random quote when none exist."""
        quote = self.db.get_random_quote("emptychannel")
        self.assertIsNone(quote)
    
    def test_delete_quote(self) -> None:
        """Test deleting a quote."""
        quote_id = self.db.add_quote(
            channel="testchannel",
            quote_text="To be deleted",
            author="Author",
            added_by="Mod"
        )
        
        # Verify it exists
        quote = self.db.get_quote("testchannel", quote_id)
        self.assertIsNotNone(quote)
        
        # Delete it
        success = self.db.delete_quote("testchannel", quote_id)
        self.assertTrue(success)
        
        # Verify it's gone
        quote = self.db.get_quote("testchannel", quote_id)
        self.assertIsNone(quote)
    
    def test_delete_quote_not_found(self) -> None:
        """Test deleting non-existent quote."""
        success = self.db.delete_quote("testchannel", 99999)
        self.assertFalse(success)
    
    def test_get_quote_count(self) -> None:
        """Test getting quote count."""
        # Initially empty
        count = self.db.get_quote_count("testchannel")
        self.assertEqual(count, 0)
        
        # Add quotes
        for i in range(3):
            self.db.add_quote(
                channel="testchannel",
                quote_text=f"Quote {i}",
                author="Author",
                added_by="Mod"
            )
        
        count = self.db.get_quote_count("testchannel")
        self.assertEqual(count, 3)
    
    def test_search_quotes(self) -> None:
        """Test searching quotes."""
        self.db.add_quote(
            channel="testchannel",
            quote_text="The quick brown fox",
            author="Author1",
            added_by="Mod"
        )
        self.db.add_quote(
            channel="testchannel",
            quote_text="Lazy dog sleeps",
            author="Author2",
            added_by="Mod"
        )
        self.db.add_quote(
            channel="testchannel",
            quote_text="Another fox quote",
            author="FoxLover",
            added_by="Mod"
        )
        
        # Search for "fox"
        results = self.db.search_quotes("testchannel", "fox")
        self.assertEqual(len(results), 2)
        
        # Search for "dog"
        results = self.db.search_quotes("testchannel", "dog")
        self.assertEqual(len(results), 1)
        
        # Search for author
        results = self.db.search_quotes("testchannel", "FoxLover")
        self.assertEqual(len(results), 1)
    
    def test_search_quotes_no_results(self) -> None:
        """Test searching with no results."""
        self.db.add_quote(
            channel="testchannel",
            quote_text="Hello world",
            author="Author",
            added_by="Mod"
        )
        
        results = self.db.search_quotes("testchannel", "nonexistent")
        self.assertEqual(len(results), 0)
    
    def test_get_all_quotes(self) -> None:
        """Test getting all quotes."""
        for i in range(5):
            self.db.add_quote(
                channel="testchannel",
                quote_text=f"Quote {i}",
                author=f"Author{i}",
                added_by="Mod"
            )
        
        quotes = self.db.get_all_quotes("testchannel")
        self.assertEqual(len(quotes), 5)
    
    def test_channel_isolation(self) -> None:
        """Test that quotes are isolated by channel."""
        self.db.add_quote(
            channel="channel1",
            quote_text="Channel 1 quote",
            author="Author",
            added_by="Mod"
        )
        self.db.add_quote(
            channel="channel2",
            quote_text="Channel 2 quote",
            author="Author",
            added_by="Mod"
        )
        
        channel1_quotes = self.db.get_all_quotes("channel1")
        channel2_quotes = self.db.get_all_quotes("channel2")
        
        self.assertEqual(len(channel1_quotes), 1)
        self.assertEqual(len(channel2_quotes), 1)
        self.assertEqual(channel1_quotes[0]["quote_text"], "Channel 1 quote")
        self.assertEqual(channel2_quotes[0]["quote_text"], "Channel 2 quote")


if __name__ == "__main__":
    unittest.main()
