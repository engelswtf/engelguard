"""
Tests for the Giveaway system.

These tests verify:
- Giveaway creation
- Entry management
- Winner selection
- Giveaway lifecycle
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestGiveawayDatabase:
    """Tests for giveaway database operations."""
    
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
    
    def test_create_giveaway(self, db) -> None:
        """Test creating a giveaway."""
        giveaway_id = db.create_giveaway(
            channel="testchannel",
            keyword="!enter",
            prize="Steam Key",
            started_by="testmod",
            duration_minutes=10,
            winner_count=1,
            sub_luck=2.0,
            follower_only=False,
            sub_only=False,
            min_points=0
        )
        
        assert giveaway_id > 0
        
        # Verify it was created
        giveaway = db.get_active_giveaway("testchannel")
        assert giveaway is not None
        assert giveaway["keyword"] == "!enter"
        assert giveaway["prize"] == "Steam Key"
        assert giveaway["started_by"] == "testmod"
        assert giveaway["status"] == "active"
        assert giveaway["winner_count"] == 1
        assert giveaway["sub_luck_multiplier"] == 2.0
    
    def test_create_giveaway_no_duration(self, db) -> None:
        """Test creating a giveaway without a duration."""
        giveaway_id = db.create_giveaway(
            channel="testchannel",
            keyword="!enter",
            prize="Prize",
            started_by="testmod",
            duration_minutes=None
        )
        
        giveaway = db.get_giveaway_by_id(giveaway_id)
        assert giveaway is not None
        assert giveaway["ends_at"] is None
    
    def test_get_active_giveaway_none(self, db) -> None:
        """Test getting active giveaway when none exists."""
        giveaway = db.get_active_giveaway("nonexistent")
        assert giveaway is None
    
    def test_add_giveaway_entry(self, db) -> None:
        """Test adding entries to a giveaway."""
        giveaway_id = db.create_giveaway(
            channel="testchannel",
            keyword="!enter",
            prize="Prize",
            started_by="testmod"
        )
        
        # Add first entry
        success = db.add_giveaway_entry(
            giveaway_id=giveaway_id,
            user_id="user1",
            username="User1",
            is_sub=False,
            is_vip=False,
            tickets=1
        )
        assert success is True
        
        # Try to add duplicate entry
        success = db.add_giveaway_entry(
            giveaway_id=giveaway_id,
            user_id="user1",
            username="User1",
            is_sub=False,
            is_vip=False,
            tickets=1
        )
        assert success is False
        
        # Add different user
        success = db.add_giveaway_entry(
            giveaway_id=giveaway_id,
            user_id="user2",
            username="User2",
            is_sub=True,
            is_vip=False,
            tickets=2
        )
        assert success is True
    
    def test_get_entry_count(self, db) -> None:
        """Test getting entry count."""
        giveaway_id = db.create_giveaway(
            channel="testchannel",
            keyword="!enter",
            prize="Prize",
            started_by="testmod"
        )
        
        assert db.get_entry_count(giveaway_id) == 0
        
        db.add_giveaway_entry(giveaway_id, "user1", "User1")
        assert db.get_entry_count(giveaway_id) == 1
        
        db.add_giveaway_entry(giveaway_id, "user2", "User2")
        assert db.get_entry_count(giveaway_id) == 2
    
    def test_get_giveaway_entries(self, db) -> None:
        """Test getting all entries."""
        giveaway_id = db.create_giveaway(
            channel="testchannel",
            keyword="!enter",
            prize="Prize",
            started_by="testmod"
        )
        
        db.add_giveaway_entry(giveaway_id, "user1", "User1", is_sub=True, tickets=2)
        db.add_giveaway_entry(giveaway_id, "user2", "User2", is_sub=False, tickets=1)
        
        entries = db.get_giveaway_entries(giveaway_id)
        assert len(entries) == 2
        
        # Check entry data
        user1_entry = next(e for e in entries if e["user_id"] == "user1")
        assert user1_entry["username"] == "User1"
        assert user1_entry["is_subscriber"] == 1  # SQLite stores as int
        assert user1_entry["tickets"] == 2
    
    def test_pick_winner(self, db) -> None:
        """Test picking a winner."""
        giveaway_id = db.create_giveaway(
            channel="testchannel",
            keyword="!enter",
            prize="Prize",
            started_by="testmod"
        )
        
        # No entries - should return None
        winner = db.pick_winner(giveaway_id)
        assert winner is None
        
        # Add entries
        db.add_giveaway_entry(giveaway_id, "user1", "User1", tickets=1)
        db.add_giveaway_entry(giveaway_id, "user2", "User2", tickets=1)
        
        # Pick winner
        winner = db.pick_winner(giveaway_id)
        assert winner is not None
        assert winner["user_id"] in ["user1", "user2"]
    
    def test_pick_winner_with_exclusions(self, db) -> None:
        """Test picking a winner with exclusions."""
        giveaway_id = db.create_giveaway(
            channel="testchannel",
            keyword="!enter",
            prize="Prize",
            started_by="testmod"
        )
        
        db.add_giveaway_entry(giveaway_id, "user1", "User1")
        db.add_giveaway_entry(giveaway_id, "user2", "User2")
        
        # Exclude user1
        winner = db.pick_winner(giveaway_id, exclude_user_ids=["user1"])
        assert winner is not None
        assert winner["user_id"] == "user2"
        
        # Exclude both
        winner = db.pick_winner(giveaway_id, exclude_user_ids=["user1", "user2"])
        assert winner is None
    
    def test_pick_winner_weighted(self, db) -> None:
        """Test that winner selection is weighted by tickets."""
        giveaway_id = db.create_giveaway(
            channel="testchannel",
            keyword="!enter",
            prize="Prize",
            started_by="testmod"
        )
        
        # User1 has 100 tickets, user2 has 1
        # User1 should win most of the time
        db.add_giveaway_entry(giveaway_id, "user1", "User1", tickets=100)
        db.add_giveaway_entry(giveaway_id, "user2", "User2", tickets=1)
        
        # Run multiple picks
        user1_wins = 0
        for _ in range(100):
            winner = db.pick_winner(giveaway_id)
            if winner["user_id"] == "user1":
                user1_wins += 1
        
        # User1 should win significantly more often
        assert user1_wins > 80
    
    def test_add_giveaway_winner(self, db) -> None:
        """Test recording a winner."""
        giveaway_id = db.create_giveaway(
            channel="testchannel",
            keyword="!enter",
            prize="Prize",
            started_by="testmod"
        )
        
        db.add_giveaway_winner(giveaway_id, "user1", "User1")
        
        winners = db.get_giveaway_winners(giveaway_id)
        assert len(winners) == 1
        assert winners[0]["user_id"] == "user1"
        assert winners[0]["username"] == "User1"
    
    def test_end_giveaway(self, db) -> None:
        """Test ending a giveaway."""
        giveaway_id = db.create_giveaway(
            channel="testchannel",
            keyword="!enter",
            prize="Prize",
            started_by="testmod"
        )
        
        # Should be active
        giveaway = db.get_active_giveaway("testchannel")
        assert giveaway is not None
        
        # End it
        db.end_giveaway(giveaway_id)
        
        # Should no longer be active
        giveaway = db.get_active_giveaway("testchannel")
        assert giveaway is None
        
        # But should exist with ended status
        giveaway = db.get_giveaway_by_id(giveaway_id)
        assert giveaway["status"] == "ended"
    
    def test_cancel_giveaway(self, db) -> None:
        """Test cancelling a giveaway."""
        giveaway_id = db.create_giveaway(
            channel="testchannel",
            keyword="!enter",
            prize="Prize",
            started_by="testmod"
        )
        
        db.cancel_giveaway(giveaway_id)
        
        giveaway = db.get_giveaway_by_id(giveaway_id)
        assert giveaway["status"] == "cancelled"
    
    def test_get_giveaway_history(self, db) -> None:
        """Test getting giveaway history."""
        # Create multiple giveaways
        id1 = db.create_giveaway(
            channel="testchannel",
            keyword="!enter1",
            prize="Prize1",
            started_by="mod1"
        )
        db.end_giveaway(id1)
        
        id2 = db.create_giveaway(
            channel="testchannel",
            keyword="!enter2",
            prize="Prize2",
            started_by="mod2"
        )
        
        history = db.get_giveaway_history("testchannel", limit=10)
        assert len(history) == 2
        
        # Most recent first
        assert history[0]["id"] == id2
        assert history[1]["id"] == id1
    
    def test_only_one_active_per_channel(self, db) -> None:
        """Test that only one active giveaway per channel is returned."""
        # Create first giveaway
        id1 = db.create_giveaway(
            channel="testchannel",
            keyword="!enter1",
            prize="Prize1",
            started_by="mod1"
        )
        
        # End it
        db.end_giveaway(id1)
        
        # Create second giveaway
        id2 = db.create_giveaway(
            channel="testchannel",
            keyword="!enter2",
            prize="Prize2",
            started_by="mod2"
        )
        
        # Should only get the active one
        active = db.get_active_giveaway("testchannel")
        assert active is not None
        assert active["id"] == id2


class TestGiveawayIntegration:
    """Integration tests for the giveaway system."""
    
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
    
    def test_full_giveaway_flow(self, db) -> None:
        """Test a complete giveaway flow."""
        # 1. Create giveaway
        giveaway_id = db.create_giveaway(
            channel="testchannel",
            keyword="!enter",
            prize="Steam Key",
            started_by="streamer",
            winner_count=2,
            sub_luck=2.0
        )
        
        # 2. Users enter
        db.add_giveaway_entry(giveaway_id, "user1", "User1", is_sub=False, tickets=1)
        db.add_giveaway_entry(giveaway_id, "user2", "User2", is_sub=True, tickets=2)
        db.add_giveaway_entry(giveaway_id, "user3", "User3", is_sub=False, tickets=1)
        db.add_giveaway_entry(giveaway_id, "user4", "User4", is_sub=True, tickets=2)
        
        assert db.get_entry_count(giveaway_id) == 4
        
        # 3. Pick winners
        winners = []
        exclude_ids = []
        
        for _ in range(2):
            winner = db.pick_winner(giveaway_id, exclude_ids)
            if winner:
                db.add_giveaway_winner(giveaway_id, winner["user_id"], winner["username"])
                winners.append(winner)
                exclude_ids.append(winner["user_id"])
        
        assert len(winners) == 2
        assert winners[0]["user_id"] != winners[1]["user_id"]
        
        # 4. End giveaway
        db.end_giveaway(giveaway_id)
        
        # 5. Verify final state
        giveaway = db.get_giveaway_by_id(giveaway_id)
        assert giveaway["status"] == "ended"
        
        recorded_winners = db.get_giveaway_winners(giveaway_id)
        assert len(recorded_winners) == 2
    
    def test_reroll_flow(self, db) -> None:
        """Test rerolling a winner."""
        # Create and populate giveaway
        giveaway_id = db.create_giveaway(
            channel="testchannel",
            keyword="!enter",
            prize="Prize",
            started_by="mod"
        )
        
        db.add_giveaway_entry(giveaway_id, "user1", "User1")
        db.add_giveaway_entry(giveaway_id, "user2", "User2")
        db.add_giveaway_entry(giveaway_id, "user3", "User3")
        
        # Pick first winner
        winner1 = db.pick_winner(giveaway_id)
        db.add_giveaway_winner(giveaway_id, winner1["user_id"], winner1["username"])
        
        # End giveaway
        db.end_giveaway(giveaway_id)
        
        # Reroll - exclude first winner
        existing_winners = db.get_giveaway_winners(giveaway_id)
        exclude_ids = [w["user_id"] for w in existing_winners]
        
        winner2 = db.pick_winner(giveaway_id, exclude_ids)
        assert winner2 is not None
        assert winner2["user_id"] != winner1["user_id"]
        
        db.add_giveaway_winner(giveaway_id, winner2["user_id"], winner2["username"])
        
        # Verify both winners recorded
        all_winners = db.get_giveaway_winners(giveaway_id)
        assert len(all_winners) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
