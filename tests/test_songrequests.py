"""
Tests for the Song Request system.

These tests verify:
- YouTube URL parsing
- Queue management
- Settings management
- Blacklist functionality
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestYouTubeHelpers:
    """Tests for YouTube helper functions."""

    def test_extract_video_id_standard_url(self) -> None:
        """Test extracting video ID from standard YouTube URL."""
        from bot.cogs.songrequests import extract_video_id

        # Standard watch URL
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert extract_video_id("https://youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert extract_video_id("http://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_extract_video_id_short_url(self) -> None:
        """Test extracting video ID from youtu.be short URL."""
        from bot.cogs.songrequests import extract_video_id

        assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert extract_video_id("http://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_extract_video_id_embed_url(self) -> None:
        """Test extracting video ID from embed URL."""
        from bot.cogs.songrequests import extract_video_id

        assert extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_extract_video_id_shorts_url(self) -> None:
        """Test extracting video ID from shorts URL."""
        from bot.cogs.songrequests import extract_video_id

        assert extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_extract_video_id_with_extra_params(self) -> None:
        """Test extracting video ID from URL with extra parameters."""
        from bot.cogs.songrequests import extract_video_id

        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30") == "dQw4w9WgXcQ"
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLxyz") == "dQw4w9WgXcQ"

    def test_extract_video_id_invalid_url(self) -> None:
        """Test that invalid URLs return None."""
        from bot.cogs.songrequests import extract_video_id

        assert extract_video_id("https://google.com") is None
        assert extract_video_id("not a url") is None
        assert extract_video_id("") is None
        assert extract_video_id("https://youtube.com/") is None

    def test_format_duration(self) -> None:
        """Test duration formatting."""
        from bot.cogs.songrequests import format_duration

        assert format_duration(0) == "Unknown"
        assert format_duration(-1) == "Unknown"
        assert format_duration(30) == "0:30"
        assert format_duration(90) == "1:30"
        assert format_duration(3600) == "1:00:00"
        assert format_duration(3661) == "1:01:01"
        assert format_duration(7325) == "2:02:05"


class TestSongRequestsDatabase:
    """Tests for Song Request database operations."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        # Create temp file
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        
        # Patch the database path
        with patch("bot.utils.database.DatabaseManager.__init__") as mock_init:
            def init_with_temp_path(self, db_path=path):
                from pathlib import Path
                self.db_path = Path(db_path)
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                self._init_database()
            
            mock_init.side_effect = init_with_temp_path
            
            from bot.utils.database import DatabaseManager
            db = DatabaseManager(db_path=path)
            
            yield db
        
        # Cleanup
        try:
            os.unlink(path)
        except Exception:
            pass

    @pytest.fixture
    def sr_cog(self, temp_db):
        """Create a SongRequests cog with temp database."""
        from bot.cogs.songrequests import SongRequests
        
        # Mock bot
        mock_bot = MagicMock()
        mock_bot.config.owner = "testowner"
        
        # Patch get_database to return our temp db
        with patch("bot.cogs.songrequests.get_database", return_value=temp_db):
            cog = SongRequests(mock_bot)
            yield cog

    def test_get_sr_settings_defaults(self, sr_cog) -> None:
        """Test that default settings are returned for new channel."""
        settings = sr_cog.get_sr_settings("newchannel")
        
        assert settings["enabled"] is False
        assert settings["max_queue_size"] == 50
        assert settings["max_duration_seconds"] == 600
        assert settings["user_limit"] == 3
        assert settings["sub_limit"] == 5
        assert settings["volume"] == 50

    def test_update_sr_settings(self, sr_cog) -> None:
        """Test updating song request settings."""
        sr_cog.update_sr_settings("testchannel", enabled=True, max_queue_size=100)
        
        settings = sr_cog.get_sr_settings("testchannel")
        assert settings["enabled"] is True
        assert settings["max_queue_size"] == 100
        # Other settings should be defaults
        assert settings["user_limit"] == 3

    def test_add_to_queue(self, sr_cog) -> None:
        """Test adding a song to the queue."""
        song_id = sr_cog.add_to_queue(
            channel="testchannel",
            video_id="dQw4w9WgXcQ",
            title="Never Gonna Give You Up",
            duration=213,
            requested_by="testuser",
            requested_by_id="12345"
        )
        
        assert song_id > 0
        
        queue = sr_cog.get_queue("testchannel")
        assert len(queue) == 1
        assert queue[0]["video_id"] == "dQw4w9WgXcQ"
        assert queue[0]["title"] == "Never Gonna Give You Up"
        assert queue[0]["requested_by"] == "testuser"

    def test_get_queue_position(self, sr_cog) -> None:
        """Test getting queue position."""
        # Add multiple songs
        id1 = sr_cog.add_to_queue("testchannel", "vid1", "Song 1", 100, "user1", "1")
        id2 = sr_cog.add_to_queue("testchannel", "vid2", "Song 2", 100, "user2", "2")
        id3 = sr_cog.add_to_queue("testchannel", "vid3", "Song 3", 100, "user3", "3")
        
        assert sr_cog.get_queue_position("testchannel", id1) == 1
        assert sr_cog.get_queue_position("testchannel", id2) == 2
        assert sr_cog.get_queue_position("testchannel", id3) == 3
        assert sr_cog.get_queue_position("testchannel", 9999) == 0

    def test_get_user_queue_count(self, sr_cog) -> None:
        """Test counting user's songs in queue."""
        sr_cog.add_to_queue("testchannel", "vid1", "Song 1", 100, "user1", "1")
        sr_cog.add_to_queue("testchannel", "vid2", "Song 2", 100, "user1", "1")
        sr_cog.add_to_queue("testchannel", "vid3", "Song 3", 100, "user2", "2")
        
        assert sr_cog.get_user_queue_count("testchannel", "1") == 2
        assert sr_cog.get_user_queue_count("testchannel", "2") == 1
        assert sr_cog.get_user_queue_count("testchannel", "3") == 0

    def test_remove_from_queue(self, sr_cog) -> None:
        """Test removing a song from queue."""
        song_id = sr_cog.add_to_queue("testchannel", "vid1", "Song 1", 100, "user1", "1")
        
        assert len(sr_cog.get_queue("testchannel")) == 1
        
        result = sr_cog.remove_from_queue(song_id)
        assert result is True
        
        assert len(sr_cog.get_queue("testchannel")) == 0

    def test_clear_queue(self, sr_cog) -> None:
        """Test clearing the entire queue."""
        sr_cog.add_to_queue("testchannel", "vid1", "Song 1", 100, "user1", "1")
        sr_cog.add_to_queue("testchannel", "vid2", "Song 2", 100, "user2", "2")
        sr_cog.add_to_queue("testchannel", "vid3", "Song 3", 100, "user3", "3")
        
        count = sr_cog.clear_queue("testchannel")
        assert count == 3
        
        assert len(sr_cog.get_queue("testchannel")) == 0

    def test_mark_song_playing(self, sr_cog) -> None:
        """Test marking a song as playing."""
        song_id = sr_cog.add_to_queue("testchannel", "vid1", "Song 1", 100, "user1", "1")
        
        sr_cog.mark_song_playing(song_id)
        
        current = sr_cog.get_current_song("testchannel")
        assert current is not None
        assert current["id"] == song_id
        assert current["status"] == "playing"

    def test_skip_song(self, sr_cog) -> None:
        """Test skipping a song."""
        id1 = sr_cog.add_to_queue("testchannel", "vid1", "Song 1", 100, "user1", "1")
        id2 = sr_cog.add_to_queue("testchannel", "vid2", "Song 2", 100, "user2", "2")
        
        sr_cog.mark_song_playing(id1)
        sr_cog.skip_song(id1)
        
        # First song should be skipped (not in queue)
        current = sr_cog.get_current_song("testchannel")
        assert current is None
        
        # Second song should be next
        next_song = sr_cog.get_next_song("testchannel")
        assert next_song is not None
        assert next_song["id"] == id2

    def test_blacklist_song(self, sr_cog) -> None:
        """Test blacklisting a song."""
        assert sr_cog.is_song_blacklisted("testchannel", "vid1") is False
        
        sr_cog.add_to_blacklist("testchannel", "vid1", None, "Test reason", "mod1")
        
        assert sr_cog.is_song_blacklisted("testchannel", "vid1") is True
        assert sr_cog.is_song_blacklisted("testchannel", "vid2") is False

    def test_remove_from_blacklist(self, sr_cog) -> None:
        """Test removing a song from blacklist."""
        sr_cog.add_to_blacklist("testchannel", "vid1", None, "Test reason", "mod1")
        assert sr_cog.is_song_blacklisted("testchannel", "vid1") is True
        
        result = sr_cog.remove_from_blacklist("testchannel", "vid1")
        assert result is True
        
        assert sr_cog.is_song_blacklisted("testchannel", "vid1") is False

    def test_get_user_last_request(self, sr_cog) -> None:
        """Test getting user's last request."""
        sr_cog.add_to_queue("testchannel", "vid1", "Song 1", 100, "user1", "1")
        sr_cog.add_to_queue("testchannel", "vid2", "Song 2", 100, "user1", "1")
        
        last = sr_cog.get_user_last_request("testchannel", "1")
        assert last is not None
        assert last["video_id"] == "vid2"

    def test_queue_isolation_between_channels(self, sr_cog) -> None:
        """Test that queues are isolated between channels."""
        sr_cog.add_to_queue("channel1", "vid1", "Song 1", 100, "user1", "1")
        sr_cog.add_to_queue("channel2", "vid2", "Song 2", 100, "user2", "2")
        
        queue1 = sr_cog.get_queue("channel1")
        queue2 = sr_cog.get_queue("channel2")
        
        assert len(queue1) == 1
        assert len(queue2) == 1
        assert queue1[0]["video_id"] == "vid1"
        assert queue2[0]["video_id"] == "vid2"


class TestSongRequestsIntegration:
    """Integration tests for Song Request commands."""

    @pytest.fixture
    def mock_ctx(self):
        """Create a mock command context."""
        ctx = MagicMock()
        ctx.channel.name = "testchannel"
        ctx.author.name = "testuser"
        ctx.author.id = "12345"
        ctx.author.is_mod = False
        ctx.author.is_broadcaster = False
        ctx.author.is_subscriber = False
        return ctx

    def test_youtube_info_extraction(self) -> None:
        """Test that YouTube info extraction works with valid URL."""
        from bot.cogs.songrequests import get_youtube_info
        
        # This test requires network access, so we mock it
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"title": "Test Video", "author_name": "Test Channel"}'
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response
            
            info = get_youtube_info("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            
            assert info is not None
            assert info["video_id"] == "dQw4w9WgXcQ"
            assert info["title"] == "Test Video"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
