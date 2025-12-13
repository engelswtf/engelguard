"""
Tests for the Gambling mini-games cog.

These tests verify:
- Slot machine mechanics
- Gamble (coin flip) mechanics
- Roulette mechanics
- Duel system
- Bet validation
- Points management
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestGamblingDatabase:
    """Tests for gambling database operations."""

    @pytest.fixture
    def db(self):
        """Create a temporary database for testing."""
        from bot.utils.database import DatabaseManager

        # Create temp file for database
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        db = DatabaseManager(db_path)
        yield db

        # Cleanup
        try:
            os.unlink(db_path)
        except OSError:
            pass

    def test_get_points_no_user(self, db) -> None:
        """Test getting points for non-existent user returns 0."""
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT points FROM user_loyalty WHERE user_id = ? AND channel = ?",
                ("nonexistent", "testchannel")
            )
            row = cursor.fetchone()
            assert row is None

    def test_create_user_with_points(self, db) -> None:
        """Test creating a user with points."""
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_loyalty (user_id, username, channel, points)
                VALUES (?, ?, ?, ?)
            """, ("user123", "testuser", "testchannel", 1000))

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT points FROM user_loyalty WHERE user_id = ? AND channel = ?",
                ("user123", "testchannel")
            )
            row = cursor.fetchone()
            assert row is not None
            assert row["points"] == 1000

    def test_update_points_add(self, db) -> None:
        """Test adding points to a user."""
        # Create user first
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_loyalty (user_id, username, channel, points)
                VALUES (?, ?, ?, ?)
            """, ("user123", "testuser", "testchannel", 1000))

        # Update points
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_loyalty 
                SET points = MAX(0, points + ?)
                WHERE user_id = ? AND channel = ?
            """, (500, "user123", "testchannel"))

            cursor.execute(
                "SELECT points FROM user_loyalty WHERE user_id = ? AND channel = ?",
                ("user123", "testchannel")
            )
            row = cursor.fetchone()
            assert row["points"] == 1500

    def test_update_points_subtract(self, db) -> None:
        """Test subtracting points from a user."""
        # Create user first
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_loyalty (user_id, username, channel, points)
                VALUES (?, ?, ?, ?)
            """, ("user123", "testuser", "testchannel", 1000))

        # Subtract points
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_loyalty 
                SET points = MAX(0, points + ?)
                WHERE user_id = ? AND channel = ?
            """, (-300, "user123", "testchannel"))

            cursor.execute(
                "SELECT points FROM user_loyalty WHERE user_id = ? AND channel = ?",
                ("user123", "testchannel")
            )
            row = cursor.fetchone()
            assert row["points"] == 700

    def test_points_cannot_go_negative(self, db) -> None:
        """Test that points cannot go below 0."""
        # Create user first
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_loyalty (user_id, username, channel, points)
                VALUES (?, ?, ?, ?)
            """, ("user123", "testuser", "testchannel", 100))

        # Try to subtract more than available
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_loyalty 
                SET points = MAX(0, points + ?)
                WHERE user_id = ? AND channel = ?
            """, (-500, "user123", "testchannel"))

            cursor.execute(
                "SELECT points FROM user_loyalty WHERE user_id = ? AND channel = ?",
                ("user123", "testchannel")
            )
            row = cursor.fetchone()
            assert row["points"] == 0


class TestGamblingCogUnit:
    """Unit tests for Gambling cog methods."""

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot."""
        bot = MagicMock()
        bot.config = MagicMock()
        bot.config.owner = "testowner"
        return bot

    @pytest.fixture
    def db(self):
        """Create a temporary database for testing."""
        from bot.utils.database import DatabaseManager

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        db = DatabaseManager(db_path)
        yield db

        try:
            os.unlink(db_path)
        except OSError:
            pass

    @pytest.fixture
    def gambling_cog(self, mock_bot, db):
        """Create a Gambling cog with mocked dependencies."""
        with patch('bot.cogs.gambling.get_database', return_value=db):
            from bot.cogs.gambling import Gambling
            cog = Gambling(mock_bot)
            return cog

    def test_validate_bet_invalid_amount(self, gambling_cog) -> None:
        """Test bet validation with invalid amount."""
        valid, amount, error = gambling_cog._validate_bet("abc", "user123", "testchannel")
        assert valid is False
        assert amount == 0
        assert "Invalid amount" in error

    def test_validate_bet_below_minimum(self, gambling_cog) -> None:
        """Test bet validation below minimum."""
        valid, amount, error = gambling_cog._validate_bet("5", "user123", "testchannel")
        assert valid is False
        assert amount == 0
        assert "Minimum bet" in error

    def test_validate_bet_above_maximum(self, gambling_cog) -> None:
        """Test bet validation above maximum."""
        valid, amount, error = gambling_cog._validate_bet("50000", "user123", "testchannel")
        assert valid is False
        assert amount == 0
        assert "Maximum bet" in error

    def test_validate_bet_insufficient_points(self, gambling_cog) -> None:
        """Test bet validation with insufficient points."""
        valid, amount, error = gambling_cog._validate_bet("100", "user123", "testchannel")
        assert valid is False
        assert amount == 0
        assert "only have" in error

    def test_validate_bet_valid(self, gambling_cog, db) -> None:
        """Test valid bet validation."""
        # Give user some points
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_loyalty (user_id, username, channel, points)
                VALUES (?, ?, ?, ?)
            """, ("user123", "testuser", "testchannel", 1000))

        valid, amount, error = gambling_cog._validate_bet("100", "user123", "testchannel")
        assert valid is True
        assert amount == 100
        assert error == ""

    def test_get_points_existing_user(self, gambling_cog, db) -> None:
        """Test getting points for existing user."""
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_loyalty (user_id, username, channel, points)
                VALUES (?, ?, ?, ?)
            """, ("user123", "testuser", "testchannel", 500))

        points = gambling_cog._get_points("user123", "testchannel")
        assert points == 500

    def test_get_points_nonexistent_user(self, gambling_cog) -> None:
        """Test getting points for non-existent user."""
        points = gambling_cog._get_points("nonexistent", "testchannel")
        assert points == 0

    def test_update_points_new_user(self, gambling_cog) -> None:
        """Test updating points creates user if not exists."""
        new_balance = gambling_cog._update_points("newuser", "NewUser", "testchannel", 100)
        assert new_balance == 100

    def test_update_points_existing_user(self, gambling_cog, db) -> None:
        """Test updating points for existing user."""
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_loyalty (user_id, username, channel, points)
                VALUES (?, ?, ?, ?)
            """, ("user123", "testuser", "testchannel", 500))

        new_balance = gambling_cog._update_points("user123", "testuser", "testchannel", 200)
        assert new_balance == 700


class TestSlotMachine:
    """Tests for slot machine mechanics."""

    def test_slot_symbols_exist(self) -> None:
        """Test that slot symbols are defined."""
        from bot.cogs.gambling import SLOT_SYMBOLS
        assert len(SLOT_SYMBOLS) >= 5

    def test_slot_payouts_exist(self) -> None:
        """Test that slot payouts are defined."""
        from bot.cogs.gambling import SLOT_PAYOUTS
        assert len(SLOT_PAYOUTS) >= 5

    def test_jackpot_highest_payout(self) -> None:
        """Test that 777 has the highest payout."""
        from bot.cogs.gambling import SLOT_PAYOUTS
        jackpot = SLOT_PAYOUTS.get("7️⃣7️⃣7️⃣", 0)
        assert jackpot >= max(v for k, v in SLOT_PAYOUTS.items() if k != "7️⃣7️⃣7️⃣")


class TestRoulette:
    """Tests for roulette mechanics."""

    def test_roulette_red_numbers(self) -> None:
        """Test that red numbers are correctly defined."""
        from bot.cogs.gambling import ROULETTE_RED
        # Standard roulette red numbers
        expected_red = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
        assert ROULETTE_RED == expected_red

    def test_roulette_red_count(self) -> None:
        """Test that there are 18 red numbers."""
        from bot.cogs.gambling import ROULETTE_RED
        assert len(ROULETTE_RED) == 18


class TestDuelSystem:
    """Tests for duel system mechanics."""

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot."""
        bot = MagicMock()
        bot.config = MagicMock()
        bot.config.owner = "testowner"
        return bot

    @pytest.fixture
    def db(self):
        """Create a temporary database for testing."""
        from bot.utils.database import DatabaseManager

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        db = DatabaseManager(db_path)
        yield db

        try:
            os.unlink(db_path)
        except OSError:
            pass

    @pytest.fixture
    def gambling_cog(self, mock_bot, db):
        """Create a Gambling cog with mocked dependencies."""
        with patch('bot.cogs.gambling.get_database', return_value=db):
            from bot.cogs.gambling import Gambling
            cog = Gambling(mock_bot)
            return cog

    def test_clean_expired_duels_empty(self, gambling_cog) -> None:
        """Test cleaning expired duels when none exist."""
        gambling_cog._clean_expired_duels("testchannel")
        assert "testchannel" not in gambling_cog._pending_duels

    def test_clean_expired_duels_removes_old(self, gambling_cog) -> None:
        """Test that expired duels are removed."""
        gambling_cog._pending_duels["testchannel"] = {
            "challenger1": {
                "target": "target1",
                "amount": 100,
                "challenger_id": "123",
                "expires": datetime.now(timezone.utc) - timedelta(minutes=5)
            }
        }

        gambling_cog._clean_expired_duels("testchannel")
        assert "challenger1" not in gambling_cog._pending_duels.get("testchannel", {})

    def test_clean_expired_duels_keeps_active(self, gambling_cog) -> None:
        """Test that active duels are kept."""
        gambling_cog._pending_duels["testchannel"] = {
            "challenger1": {
                "target": "target1",
                "amount": 100,
                "challenger_id": "123",
                "expires": datetime.now(timezone.utc) + timedelta(minutes=5)
            }
        }

        gambling_cog._clean_expired_duels("testchannel")
        assert "challenger1" in gambling_cog._pending_duels.get("testchannel", {})


class TestGamblingSettings:
    """Tests for gambling settings."""

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot."""
        bot = MagicMock()
        bot.config = MagicMock()
        bot.config.owner = "testowner"
        return bot

    @pytest.fixture
    def db(self):
        """Create a temporary database for testing."""
        from bot.utils.database import DatabaseManager

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        db = DatabaseManager(db_path)
        yield db

        try:
            os.unlink(db_path)
        except OSError:
            pass

    @pytest.fixture
    def gambling_cog(self, mock_bot, db):
        """Create a Gambling cog with mocked dependencies."""
        with patch('bot.cogs.gambling.get_database', return_value=db):
            from bot.cogs.gambling import Gambling
            cog = Gambling(mock_bot)
            return cog

    def test_default_min_bet(self, gambling_cog) -> None:
        """Test default minimum bet."""
        assert gambling_cog.min_bet == 10

    def test_default_max_bet(self, gambling_cog) -> None:
        """Test default maximum bet."""
        assert gambling_cog.max_bet == 10000

    def test_default_enabled(self, gambling_cog) -> None:
        """Test gambling is enabled by default."""
        assert gambling_cog.enabled is True

    def test_toggle_enabled(self, gambling_cog) -> None:
        """Test toggling enabled state."""
        gambling_cog.enabled = False
        assert gambling_cog.enabled is False
        gambling_cog.enabled = True
        assert gambling_cog.enabled is True
