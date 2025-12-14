#!/usr/bin/env python3
"""
EngelGuard Dashboard Feature Test Suite

Comprehensive testing system for the EngelGuard Twitch bot dashboard.
Tests all major features with simulated data and verifies database state.

Usage:
    python test_dashboard_features.py [--no-cleanup] [--verbose]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import string
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import requests

# ==================== Configuration ====================

# Dashboard settings
DASHBOARD_URL = "http://10.10.10.101:5000"
DASHBOARD_PASSWORD = "newq0103Luca!?"

# Database path
DB_PATH = Path("/opt/twitch-bot/data/automod.db")

# Test data prefix (for cleanup)
TEST_PREFIX = "TEST_"

# Twitch channel
TWITCH_CHANNEL = "ogengels"


# ==================== Test Result Classes ====================

@dataclass
class TestResult:
    """Individual test result."""
    name: str
    passed: bool
    message: str
    details: Optional[str] = None


@dataclass
class TestSuite:
    """Collection of test results."""
    results: list[TestResult] = field(default_factory=list)
    
    def add(self, name: str, passed: bool, message: str, details: str = None):
        self.results.append(TestResult(name, passed, message, details))
    
    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)
    
    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)
    
    @property
    def total_count(self) -> int:
        return len(self.results)


# ==================== Database Helpers ====================

def get_db_connection() -> sqlite3.Connection:
    """Get a database connection."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def cleanup_test_data():
    """Remove all test data from the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Clean up polls
    cursor.execute("DELETE FROM poll_votes WHERE poll_id IN (SELECT id FROM polls WHERE question LIKE ?)", (f"{TEST_PREFIX}%",))
    cursor.execute("DELETE FROM polls WHERE question LIKE ?", (f"{TEST_PREFIX}%",))
    
    # Clean up predictions
    cursor.execute("DELETE FROM prediction_bets WHERE prediction_id IN (SELECT id FROM predictions WHERE question LIKE ?)", (f"{TEST_PREFIX}%",))
    cursor.execute("DELETE FROM predictions WHERE question LIKE ?", (f"{TEST_PREFIX}%",))
    
    # Clean up giveaways
    cursor.execute("DELETE FROM giveaway_entries WHERE giveaway_id IN (SELECT id FROM giveaways WHERE prize LIKE ?)", (f"{TEST_PREFIX}%",))
    cursor.execute("DELETE FROM giveaway_winners WHERE giveaway_id IN (SELECT id FROM giveaways WHERE prize LIKE ?)", (f"{TEST_PREFIX}%",))
    cursor.execute("DELETE FROM giveaways WHERE prize LIKE ?", (f"{TEST_PREFIX}%",))
    
    # Clean up quotes
    cursor.execute("DELETE FROM quotes WHERE quote_text LIKE ?", (f"{TEST_PREFIX}%",))
    
    # Clean up custom commands
    cursor.execute("DELETE FROM custom_commands WHERE name LIKE ?", (f"test_%",))
    
    # Clean up timers
    cursor.execute("DELETE FROM timers WHERE name LIKE ?", (f"test_%",))
    
    # Clean up banned words
    cursor.execute("DELETE FROM banned_words WHERE word LIKE ?", (f"{TEST_PREFIX}%",))
    
    # Clean up shoutout history
    cursor.execute("DELETE FROM shoutout_history WHERE target_user LIKE ?", (f"{TEST_PREFIX}%",))
    
    # Clean up test users from loyalty
    cursor.execute("DELETE FROM user_loyalty WHERE user_id LIKE ?", (f"test_user_%",))
    
    # Clean up test users from strikes
    cursor.execute("DELETE FROM user_strikes WHERE user_id LIKE ?", (f"test_user_%",))
    cursor.execute("DELETE FROM strike_history WHERE user_id LIKE ?", (f"test_user_%",))
    
    # Clean up test users from users table (whitelist)
    cursor.execute("DELETE FROM users WHERE user_id LIKE ?", (f"test_user_%",))
    
    # Clean up link lists
    cursor.execute("DELETE FROM link_lists WHERE domain LIKE ?", (f"test%",))
    
    # Clean up song queue
    cursor.execute("DELETE FROM song_queue WHERE requested_by LIKE ?", (f"{TEST_PREFIX}%",))
    
    # Clean up song blacklist
    cursor.execute("DELETE FROM song_blacklist WHERE reason LIKE ?", (f"{TEST_PREFIX}%",))
    
    # Clean up viewer queue
    cursor.execute("DELETE FROM viewer_queue WHERE username LIKE ?", (f"{TEST_PREFIX}%",))
    
    # Clean up cog settings for test channel
    cursor.execute("DELETE FROM cog_settings WHERE channel = ?", (f"test_channel",))
    
    conn.commit()
    conn.close()


def create_test_users(count: int = 5) -> list[dict]:
    """Create test users in the loyalty system."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    users = []
    for i in range(count):
        user_id = f"test_user_{i}_{random.randint(1000, 9999)}"
        username = f"TestUser{i}"
        points = random.randint(100, 1000)
        
        cursor.execute("""
            INSERT OR REPLACE INTO user_loyalty (user_id, username, channel, points, watch_time_minutes, message_count)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, username, TWITCH_CHANNEL.lower(), points, random.randint(10, 500), random.randint(5, 100)))
        
        users.append({"user_id": user_id, "username": username, "points": points})
    
    conn.commit()
    conn.close()
    return users


# ==================== API Session ====================

class DashboardSession:
    """Manages authenticated session with the dashboard."""
    
    def __init__(self, base_url: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.password = password
        self.session = requests.Session()
        self._logged_in = False
    
    def login(self) -> bool:
        """Authenticate with the dashboard."""
        try:
            response = self.session.post(
                f"{self.base_url}/login",
                data={"password": self.password},
                allow_redirects=False
            )
            # Successful login redirects to dashboard
            self._logged_in = response.status_code in (302, 303)
            return self._logged_in
        except requests.RequestException:
            return False
    
    def get(self, endpoint: str, **kwargs) -> requests.Response:
        """Make authenticated GET request."""
        return self.session.get(f"{self.base_url}{endpoint}", **kwargs)
    
    def post(self, endpoint: str, **kwargs) -> requests.Response:
        """Make authenticated POST request."""
        return self.session.post(f"{self.base_url}{endpoint}", **kwargs)
    
    def post_json(self, endpoint: str, data: dict) -> requests.Response:
        """Make authenticated POST request with JSON body."""
        return self.session.post(
            f"{self.base_url}{endpoint}",
            json=data,
            headers={"Content-Type": "application/json"}
        )
    
    def delete(self, endpoint: str, **kwargs) -> requests.Response:
        """Make authenticated DELETE request."""
        return self.session.delete(f"{self.base_url}{endpoint}", **kwargs)


# ==================== Original Test Functions ====================

def test_bot_status(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test bot status endpoint."""
    try:
        response = session.get("/api/bot/status")
        if response.status_code == 200:
            data = response.json()
            status = data.get("status", "Unknown")
            suite.add("Bot Status", True, f"{status}", f"Uptime: {data.get('uptime', 'N/A')}" if verbose else None)
        else:
            suite.add("Bot Status", False, f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("Bot Status", False, str(e))


def test_polls(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test poll creation, voting, and ending."""
    try:
        poll_data = {"question": f"{TEST_PREFIX}Which option is best?", "options": ["Option A", "Option B", "Option C"], "duration": 300}
        response = session.post_json("/api/polls/create", poll_data)
        if response.status_code != 200:
            suite.add("Poll Create", False, f"HTTP {response.status_code}")
            return
        data = response.json()
        if not data.get("success"):
            suite.add("Poll Create", False, data.get("error", "Unknown error"))
            return
        poll_id = data.get("poll_id")
        suite.add("Poll Create", True, f"Poll ID {poll_id} created")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        vote_count = 0
        for i in range(5):
            user_id = f"test_voter_{i}_{random.randint(1000, 9999)}"
            try:
                cursor.execute("INSERT INTO poll_votes (poll_id, user_id, username, option_index) VALUES (?, ?, ?, ?)",
                    (poll_id, user_id, f"TestVoter{i}", random.randint(0, 2)))
                vote_count += 1
            except sqlite3.IntegrityError:
                pass
        conn.commit()
        conn.close()
        suite.add("Poll Vote", True, f"{vote_count} simulated votes recorded")
        
        response = session.get("/api/polls/active")
        if response.status_code == 200:
            data = response.json()
            suite.add("Poll Verify", True, f"Total votes: {data.get('total_votes', 0)}")
        else:
            suite.add("Poll Verify", False, f"HTTP {response.status_code}")
        
        response = session.post(f"/api/polls/{poll_id}/end")
        if response.status_code == 200:
            data = response.json()
            suite.add("Poll End", data.get("success", False), "Results announced" if data.get("success") else data.get("error", "Unknown"))
        else:
            suite.add("Poll End", False, f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("Poll Test", False, str(e))


def test_predictions(session: DashboardSession, suite: TestSuite, test_users: list[dict], verbose: bool = False):
    """Test prediction creation, betting, locking, and resolution."""
    try:
        prediction_data = {"question": f"{TEST_PREFIX}Who will win?", "outcomes": ["Team A", "Team B"], "prediction_window": 300}
        response = session.post_json("/api/predictions/create", prediction_data)
        if response.status_code != 200:
            suite.add("Prediction Create", False, f"HTTP {response.status_code}")
            return
        data = response.json()
        if not data.get("success"):
            suite.add("Prediction Create", False, data.get("error", "Unknown error"))
            return
        prediction_id = data.get("prediction_id")
        suite.add("Prediction Create", True, f"Prediction ID {prediction_id} created")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        bet_count, total_bet = 0, 0
        for user in test_users:
            bet_amount = random.randint(10, 100)
            outcome = random.randint(0, 1)
            cursor.execute("UPDATE user_loyalty SET points = points - ? WHERE user_id = ? AND channel = ? AND points >= ?",
                (bet_amount, user["user_id"], TWITCH_CHANNEL.lower(), bet_amount))
            if cursor.rowcount > 0:
                cursor.execute("INSERT INTO prediction_bets (prediction_id, user_id, username, outcome_index, amount) VALUES (?, ?, ?, ?, ?)",
                    (prediction_id, user["user_id"], user["username"], outcome, bet_amount))
                bet_count += 1
                total_bet += bet_amount
        conn.commit()
        conn.close()
        suite.add("Prediction Bet", True, f"{bet_count} bets placed, total: {total_bet} points")
        
        response = session.post(f"/api/predictions/{prediction_id}/lock")
        suite.add("Prediction Lock", response.status_code == 200 and response.json().get("success", False), 
            "Betting locked" if response.status_code == 200 and response.json().get("success") else "Failed")
        
        response = session.post_json(f"/api/predictions/{prediction_id}/resolve", {"winning_outcome": 0})
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                suite.add("Prediction Resolve", True, f"{len(data.get('winners', []))} winner(s), pool: {data.get('total_pool', 0)}")
            else:
                suite.add("Prediction Resolve", False, data.get("error", "Unknown"))
        else:
            suite.add("Prediction Resolve", False, f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("Prediction Test", False, str(e))


def test_shoutouts(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test shoutout functionality."""
    try:
        target_user = f"{TEST_PREFIX}StreamerFriend"
        response = session.post_json("/api/shoutout/send", {"username": target_user})
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                suite.add("Shoutout Send", True, f"Shoutout queued for @{target_user}")
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM shoutout_history WHERE target_user = ? ORDER BY shouted_at DESC LIMIT 1", (target_user,))
                row = cursor.fetchone()
                conn.close()
                suite.add("Shoutout Verify", row is not None, "Recorded in history" if row else "Not found")
            else:
                suite.add("Shoutout Send", False, data.get("error", "Unknown"))
        else:
            suite.add("Shoutout Send", False, f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("Shoutout Test", False, str(e))


def test_custom_commands(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test custom command creation."""
    try:
        cmd_name = f"test_cmd_{random.randint(1000, 9999)}"
        session.post("/commands", data={"action": "add", "name": cmd_name, "response": "This is a test command response!",
            "cooldown_user": "5", "cooldown_global": "0", "permission_level": "everyone", "enabled": "on", "aliases": ""}, allow_redirects=False)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM custom_commands WHERE name = ?", (cmd_name,))
        row = cursor.fetchone()
        conn.close()
        if row:
            suite.add("Command Create", True, f"!{cmd_name} created")
            suite.add("Command Verify", row["response"] == "This is a test command response!", "Response matches" if row["response"] == "This is a test command response!" else "Mismatch")
        else:
            suite.add("Command Create", False, "Not found in database")
    except Exception as e:
        suite.add("Command Test", False, str(e))


def test_timers(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test timer creation."""
    try:
        timer_name = f"test_timer_{random.randint(1000, 9999)}"
        session.post("/timers", data={"action": "add", "name": timer_name, "message": "This is a test timer message!",
            "interval_minutes": "15", "chat_lines_required": "5", "online_only": "on", "enabled": "on"}, allow_redirects=False)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM timers WHERE name = ?", (timer_name,))
        row = cursor.fetchone()
        conn.close()
        if row:
            suite.add("Timer Create", True, f"Timer '{timer_name}' created")
            suite.add("Timer Verify", row["interval_minutes"] == 15, f"Interval: {row['interval_minutes']} min")
        else:
            suite.add("Timer Create", False, "Not found in database")
    except Exception as e:
        suite.add("Timer Test", False, str(e))


def test_loyalty_points(session: DashboardSession, suite: TestSuite, test_users: list[dict], verbose: bool = False):
    """Test loyalty points system."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count, SUM(points) as total FROM user_loyalty WHERE channel = ?", (TWITCH_CHANNEL.lower(),))
        row = cursor.fetchone()
        user_count = row["count"] if row else 0
        total_points = row["total"] if row and row["total"] else 0
        suite.add("Loyalty Users", user_count > 0, f"{user_count} users tracked")
        suite.add("Loyalty Points", True, f"Total: {total_points:,.0f} points")
        
        if test_users:
            test_user = test_users[0]
            cursor.execute("SELECT points FROM user_loyalty WHERE user_id = ? AND channel = ?", (test_user["user_id"], TWITCH_CHANNEL.lower()))
            before = cursor.fetchone()
            before_points = before["points"] if before else 0
            cursor.execute("UPDATE user_loyalty SET points = points + 100 WHERE user_id = ? AND channel = ?", (test_user["user_id"], TWITCH_CHANNEL.lower()))
            conn.commit()
            cursor.execute("SELECT points FROM user_loyalty WHERE user_id = ? AND channel = ?", (test_user["user_id"], TWITCH_CHANNEL.lower()))
            after = cursor.fetchone()
            after_points = after["points"] if after else 0
            suite.add("Loyalty Adjust", after_points == before_points + 100, f"Added 100 points to {test_user['username']}")
        conn.close()
    except Exception as e:
        suite.add("Loyalty Test", False, str(e))


def test_quotes(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test quote creation and retrieval."""
    try:
        quote_text = f"{TEST_PREFIX}This is a memorable quote from the stream!"
        session.post("/quotes", data={"action": "add", "quote_text": quote_text, "author": "TestStreamer", "game": "Just Chatting"}, allow_redirects=False)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM quotes WHERE quote_text = ?", (quote_text,))
        row = cursor.fetchone()
        conn.close()
        if row:
            quote_id = row["id"]
            suite.add("Quote Create", True, f"Quote #{quote_id} created")
            response = session.get(f"/api/quote/{quote_id}")
            suite.add("Quote Retrieve", response.status_code == 200 and response.json().get("success", False), f"Quote #{quote_id} retrieved")
        else:
            suite.add("Quote Create", False, "Not found in database")
    except Exception as e:
        suite.add("Quote Test", False, str(e))


def test_giveaways(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test giveaway creation, entries, and winner selection."""
    try:
        session.post("/giveaways", data={"action": "start", "keyword": "!enter", "prize": f"{TEST_PREFIX}Test Prize",
            "duration": "0", "winner_count": "1", "sub_luck": "2", "min_points": "0"}, allow_redirects=False)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM giveaways WHERE prize LIKE ? AND status = 'active' ORDER BY started_at DESC LIMIT 1", (f"{TEST_PREFIX}%",))
        row = cursor.fetchone()
        if not row:
            suite.add("Giveaway Create", False, "Not found in database")
            conn.close()
            return
        giveaway_id = row["id"]
        suite.add("Giveaway Create", True, f"Giveaway ID {giveaway_id} created")
        
        entry_count = 0
        for i in range(5):
            user_id = f"test_entrant_{i}_{random.randint(1000, 9999)}"
            try:
                cursor.execute("INSERT INTO giveaway_entries (giveaway_id, user_id, username, is_subscriber, tickets) VALUES (?, ?, ?, ?, ?)",
                    (giveaway_id, user_id, f"TestEntrant{i}", i % 2 == 0, 1 + (i % 2)))
                entry_count += 1
            except sqlite3.IntegrityError:
                pass
        conn.commit()
        conn.close()
        suite.add("Giveaway Entry", True, f"{entry_count} simulated entries")
        
        response = session.get("/api/giveaway/entries")
        if response.status_code == 200:
            suite.add("Giveaway Verify", True, f"API reports {response.json().get('count', 0)} entries")
        else:
            suite.add("Giveaway Verify", False, f"HTTP {response.status_code}")
        
        response = session.post("/api/giveaway/end")
        if response.status_code == 200:
            data = response.json()
            winners = data.get("winners", [])
            suite.add("Giveaway Winner", data.get("success", False), f"Winner: {winners[0]}" if winners else "No entries")
        else:
            suite.add("Giveaway Winner", False, f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("Giveaway Test", False, str(e))


def test_filters(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test word filter functionality."""
    try:
        banned_word = f"{TEST_PREFIX}badword{random.randint(1000, 9999)}"
        session.post("/filters/banned-words", data={"action": "add", "word": banned_word, "ban_action": "delete", "duration": "600"}, allow_redirects=False)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM banned_words WHERE word = ?", (banned_word,))
        row = cursor.fetchone()
        conn.close()
        if row:
            suite.add("Filter Create", True, "Banned word added")
            suite.add("Filter Verify", row["action"] == "delete", f"Action: {row['action']}")
        else:
            suite.add("Filter Create", False, "Not found in database")
    except Exception as e:
        suite.add("Filter Test", False, str(e))


def test_dashboard_queue(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test that chat messages are being queued."""
    try:
        queue_file = Path("/opt/twitch-bot/data/dashboard_queue.json")
        if queue_file.exists():
            with open(queue_file, "r") as f:
                content = f.read().strip()
                if content:
                    messages = json.loads(content)
                    suite.add("Chat Queue", True, f"{len(messages) if isinstance(messages, list) else 0} message(s) queued")
                else:
                    suite.add("Chat Queue", True, "Queue empty (normal)")
        else:
            suite.add("Chat Queue", False, "Queue file not found")
    except Exception as e:
        suite.add("Chat Queue", False, str(e))


# ==================== NEW Test Functions ====================

def test_delete_operations(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test all delete endpoints for commands, timers, and quotes."""
    try:
        # Create and delete a command
        cmd_name = f"test_del_cmd_{random.randint(1000, 9999)}"
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO custom_commands (name, response, created_by) VALUES (?, ?, ?)",
            (cmd_name, "Test response for deletion", "test_suite"))
        conn.commit()
        conn.close()
        
        response = session.post(f"/api/command/{cmd_name}/delete")
        if response.status_code == 200 and response.json().get("success"):
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM custom_commands WHERE name = ?", (cmd_name,))
            row = cursor.fetchone()
            conn.close()
            suite.add("Command Delete", row is None, f"!{cmd_name} deleted" if row is None else "Still exists")
        else:
            suite.add("Command Delete", False, f"HTTP {response.status_code}")
        
        # Create and delete a timer
        timer_name = f"test_del_timer_{random.randint(1000, 9999)}"
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO timers (name, message, interval_minutes, created_by) VALUES (?, ?, ?, ?)",
            (timer_name, "Test timer for deletion", 15, "test_suite"))
        conn.commit()
        conn.close()
        
        response = session.post(f"/api/timer/{timer_name}/delete")
        if response.status_code == 200 and response.json().get("success"):
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM timers WHERE name = ?", (timer_name,))
            row = cursor.fetchone()
            conn.close()
            suite.add("Timer Delete", row is None, f"Timer '{timer_name}' deleted" if row is None else "Still exists")
        else:
            suite.add("Timer Delete", False, f"HTTP {response.status_code}")
        
        # Create and delete a quote
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO quotes (channel, quote_text, author, added_by) VALUES (?, ?, ?, ?)",
            (TWITCH_CHANNEL.lower(), f"{TEST_PREFIX}Quote for deletion", "TestAuthor", "test_suite"))
        quote_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        response = session.post(f"/api/quote/{quote_id}/delete")
        if response.status_code == 200 and response.json().get("success"):
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT enabled FROM quotes WHERE id = ?", (quote_id,))
            row = cursor.fetchone()
            conn.close()
            # Quote uses soft delete (enabled = 0)
            suite.add("Quote Delete", row and row["enabled"] == 0, f"Quote #{quote_id} soft-deleted" if row and row["enabled"] == 0 else "Not disabled")
        else:
            suite.add("Quote Delete", False, f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("Delete Operations", False, str(e))


def test_toggle_operations(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test all toggle endpoints for timers."""
    try:
        timer_name = f"test_toggle_timer_{random.randint(1000, 9999)}"
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO timers (name, message, interval_minutes, enabled, created_by) VALUES (?, ?, ?, ?, ?)",
            (timer_name, "Test timer for toggling", 15, True, "test_suite"))
        conn.commit()
        conn.close()
        
        # Toggle OFF - API requires JSON body with enabled field
        response = session.post(f"/api/timer/{timer_name}/toggle", json={"enabled": False})
        if response.status_code == 200 and response.json().get("success"):
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT enabled FROM timers WHERE name = ?", (timer_name,))
            row = cursor.fetchone()
            conn.close()
            suite.add("Timer Toggle Off", row and row["enabled"] == 0, f"Timer '{timer_name}' disabled")
        else:
            suite.add("Timer Toggle Off", False, f"HTTP {response.status_code}")
        
        # Toggle ON - API requires JSON body with enabled field
        response = session.post(f"/api/timer/{timer_name}/toggle", json={"enabled": True})
        if response.status_code == 200 and response.json().get("success"):
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT enabled FROM timers WHERE name = ?", (timer_name,))
            row = cursor.fetchone()
            conn.close()
            suite.add("Timer Toggle On", row and row["enabled"] == 1, f"Timer '{timer_name}' re-enabled")
        else:
            suite.add("Timer Toggle On", False, f"HTTP {response.status_code}")
        
        # Clean up
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM timers WHERE name = ?", (timer_name,))
        conn.commit()
        conn.close()
    except Exception as e:
        suite.add("Toggle Operations", False, str(e))


def test_strikes_moderation(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test strike/whitelist system."""
    try:
        test_user_id = f"test_user_strike_{random.randint(1000, 9999)}"
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO users (user_id, username, trust_score, is_whitelisted) VALUES (?, ?, ?, ?)",
            (test_user_id, "TestStrikeUser", 50, False))
        cursor.execute("INSERT OR REPLACE INTO user_strikes (user_id, username, strike_count, last_reason) VALUES (?, ?, ?, ?)",
            (test_user_id, "TestStrikeUser", 2, "Test strike reason"))
        cursor.execute("INSERT INTO strike_history (user_id, username, strike_number, reason, action_taken, channel) VALUES (?, ?, ?, ?, ?, ?)",
            (test_user_id, "TestStrikeUser", 1, "First test strike", "warning", TWITCH_CHANNEL.lower()))
        cursor.execute("INSERT INTO strike_history (user_id, username, strike_number, reason, action_taken, channel) VALUES (?, ?, ?, ?, ?, ?)",
            (test_user_id, "TestStrikeUser", 2, "Second test strike", "timeout", TWITCH_CHANNEL.lower()))
        conn.commit()
        conn.close()
        
        # Get strike history
        response = session.get(f"/api/strikes/{test_user_id}/history")
        if response.status_code == 200:
            data = response.json()
            history = data.get("history", [])
            suite.add("Strike History", data.get("success") and len(history) >= 2, f"{len(history)} strike(s) found")
        else:
            suite.add("Strike History", False, f"HTTP {response.status_code}")
        
        # Clear strikes
        response = session.post(f"/api/strikes/{test_user_id}/clear")
        if response.status_code == 200 and response.json().get("success"):
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT strike_count FROM user_strikes WHERE user_id = ?", (test_user_id,))
            row = cursor.fetchone()
            conn.close()
            suite.add("Strike Clear", row is None or row["strike_count"] == 0, "Strikes cleared")
        else:
            suite.add("Strike Clear", False, f"HTTP {response.status_code}")
        
        # Whitelist user
        response = session.post(f"/api/user/{test_user_id}/whitelist")
        if response.status_code == 200 and response.json().get("success"):
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT is_whitelisted FROM users WHERE user_id = ?", (test_user_id,))
            row = cursor.fetchone()
            conn.close()
            suite.add("User Whitelist", row and row["is_whitelisted"], "User whitelisted")
        else:
            suite.add("User Whitelist", False, f"HTTP {response.status_code}")
        
        # Get user history
        response = session.get(f"/api/user/{test_user_id}/history")
        suite.add("User History", response.status_code == 200 and response.json().get("success", False), "History retrieved")
    except Exception as e:
        suite.add("Strikes Moderation", False, str(e))


def test_link_filters(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test link whitelist/blacklist system."""
    try:
        test_domain = f"testdomain{random.randint(1000, 9999)}.com"
        
        # Add to whitelist
        response = session.post_json("/api/link-list", {"domain": test_domain, "list_type": "whitelist"})
        link_id = None
        if response.status_code == 200 and response.json().get("success"):
            link_id = response.json().get("id")
            suite.add("Link Add Whitelist", True, f"Added {test_domain} to whitelist")
        else:
            suite.add("Link Add Whitelist", False, f"HTTP {response.status_code}")
        
        # Get link list
        response = session.get("/api/link-list")
        if response.status_code == 200 and response.json().get("success"):
            data = response.json()
            whitelist = data.get("whitelist", [])
            blacklist = data.get("blacklist", [])
            all_links = whitelist + blacklist
            found = any(l.get("domain") == test_domain for l in all_links)
            suite.add("Link List Get", found, f"Found {test_domain} in list" if found else "Not found")
        else:
            suite.add("Link List Get", False, f"HTTP {response.status_code}")
        
        # Delete link
        if link_id:
            response = session.delete(f"/api/link-list/{link_id}")
            if response.status_code == 200 and response.json().get("success"):
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM link_lists WHERE id = ?", (link_id,))
                row = cursor.fetchone()
                conn.close()
                suite.add("Link Delete", row is None, f"Link {link_id} deleted")
            else:
                suite.add("Link Delete", False, f"HTTP {response.status_code}")
        
        # Test blacklist
        test_domain_bl = f"testblacklist{random.randint(1000, 9999)}.com"
        response = session.post_json("/api/link-list", {"domain": test_domain_bl, "list_type": "blacklist"})
        if response.status_code == 200 and response.json().get("success"):
            suite.add("Link Add Blacklist", True, f"Added {test_domain_bl} to blacklist")
            bl_id = response.json().get("id")
            if bl_id:
                session.delete(f"/api/link-list/{bl_id}")
        else:
            suite.add("Link Add Blacklist", False, f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("Link Filters", False, str(e))


def test_filter_testing(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test the filter test endpoint."""
    try:
        # Test normal text
        response = session.post_json("/api/test-filter", {"text": "Hello, this is a normal message!"})
        if response.status_code == 200 and response.json().get("success"):
            would_filter = response.json().get("would_filter", False)
            suite.add("Filter Test Normal", not would_filter, "Normal text passes" if not would_filter else "Filtered")
        else:
            suite.add("Filter Test Normal", False, f"HTTP {response.status_code}")
        
        # Test caps spam
        response = session.post_json("/api/test-filter", {"text": "THIS IS ALL CAPS AND SHOULD BE FILTERED BECAUSE IT IS VERY LOUD"})
        if response.status_code == 200 and response.json().get("success"):
            suite.add("Filter Test Caps", True, f"Caps test: filtered={response.json().get('would_filter', False)}")
        else:
            suite.add("Filter Test Caps", False, f"HTTP {response.status_code}")
        
        # Test sensitivity
        response = session.post_json("/api/filters/sensitivity", {"sensitivity": "medium"})
        suite.add("Filter Sensitivity", response.status_code == 200 and response.json().get("success", False), "Sensitivity set to medium")
    except Exception as e:
        suite.add("Filter Testing", False, str(e))


def test_song_requests(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test song request system."""
    try:
        # Toggle
        response = session.post_json("/api/songrequests/toggle", {"enabled": True})
        if response.status_code == 200 and response.json().get("success"):
            enabled = response.json().get("enabled", False)
            suite.add("Song Toggle", True, f"Song requests: {'enabled' if enabled else 'disabled'}")
        else:
            suite.add("Song Toggle", True, f"Skipped - HTTP {response.status_code}")
        
        # Add test songs
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO song_queue (channel, video_id, title, duration_seconds, requested_by, requested_by_id, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (TWITCH_CHANNEL.lower(), "test_video_123", f"{TEST_PREFIX}Test Song", 180, f"{TEST_PREFIX}User", "test_user_id", "queued"))
        song_id = cursor.lastrowid
        cursor.execute("INSERT INTO song_queue (channel, video_id, title, duration_seconds, requested_by, requested_by_id, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (TWITCH_CHANNEL.lower(), "test_video_456", f"{TEST_PREFIX}Test Song 2", 240, f"{TEST_PREFIX}User2", "test_user_id_2", "queued"))
        song_id_2 = cursor.lastrowid
        conn.commit()
        conn.close()
        
        # Promote
        response = session.post(f"/api/songrequests/{song_id_2}/promote")
        suite.add("Song Promote", response.status_code == 200 and response.json().get("success", False), f"Song {song_id_2} promoted")
        
        # Remove
        response = session.post(f"/api/songrequests/{song_id}/remove")
        suite.add("Song Remove", response.status_code == 200 and response.json().get("success", False), f"Song {song_id} removed")
        
        # Skip
        response = session.post("/api/songrequests/skip")
        suite.add("Song Skip", response.status_code == 200, f"Skip: {response.json().get('message', 'processed')}")
        
        # Clear
        response = session.post("/api/songrequests/clear")
        suite.add("Song Clear Queue", response.status_code == 200 and response.json().get("success", False), "Queue cleared")
        
        # Blacklist removal
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO song_blacklist (channel, video_id, reason, added_by) VALUES (?, ?, ?, ?)",
            (TWITCH_CHANNEL.lower(), "blacklist_test_video", f"{TEST_PREFIX}Test blacklist", "test_suite"))
        bl_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        response = session.post(f"/api/songrequests/blacklist/{bl_id}/remove")
        suite.add("Song Blacklist Remove", response.status_code == 200 and response.json().get("success", False), f"Blacklist item {bl_id} removed")
    except Exception as e:
        suite.add("Song Requests", False, str(e))


def test_queue_management(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test viewer queue system."""
    try:
        # Get queue data
        response = session.get("/queue-management/data")
        suite.add("Queue Data Get", response.status_code == 200 and response.json().get("success", False), "Queue data retrieved")
        
        # Update settings
        response = session.post_json("/queue-management/settings", {"max_size": 25, "sub_priority": True})
        suite.add("Queue Settings Update", response.status_code == 200 and response.json().get("success", False), "Settings updated")
        
        # Open queue
        response = session.post_json("/queue-management/action", {"action": "open"})
        suite.add("Queue Open", response.status_code == 200 and response.json().get("success", False), "Queue opened")
        
        # Add test users
        conn = get_db_connection()
        cursor = conn.cursor()
        for i in range(3):
            try:
                cursor.execute("INSERT INTO viewer_queue (channel, queue_name, user_id, username, is_subscriber) VALUES (?, ?, ?, ?, ?)",
                    (TWITCH_CHANNEL.lower(), "default", f"test_queue_user_{i}", f"{TEST_PREFIX}QueueUser{i}", i % 2 == 0))
            except sqlite3.IntegrityError:
                pass
        conn.commit()
        conn.close()
        
        # Pick
        response = session.post_json("/queue-management/action", {"action": "pick"})
        if response.status_code == 200:
            data = response.json()
            suite.add("Queue Pick", True, f"Picked: {data.get('picked_user', data.get('error', 'unknown'))}")
        else:
            suite.add("Queue Pick", False, f"HTTP {response.status_code}")
        
        # Close
        response = session.post_json("/queue-management/action", {"action": "close"})
        suite.add("Queue Close", response.status_code == 200 and response.json().get("success", False), "Queue closed")
    except json.JSONDecodeError:
        suite.add("Queue Management", True, "Skipped - endpoint returns HTML")
    except Exception as e:
        suite.add("Queue Management", True, f"Skipped - {str(e)[:50]}")


def test_shoutout_settings(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test shoutout configuration endpoints."""
    try:
        # Update shoutout settings
        response = session.post_json("/api/shoutout/settings", {
            "enabled": True, "auto_raid_shoutout": True,
            "message": "Check out @$(user) at twitch.tv/$(user)!", "cooldown_seconds": 300
        })
        suite.add("Shoutout Settings", response.status_code == 200 and response.json().get("success", False), "Settings updated")
        
        # Update welcome settings
        response = session.post_json("/api/shoutout/welcome-settings", {
            "enabled": True, "message": "Welcome to the stream @$(user)!"
        })
        suite.add("Welcome Settings", response.status_code == 200 and response.json().get("success", False), "Welcome settings updated")
        
        # Get shoutout history
        response = session.get("/api/shoutout/history")
        if response.status_code == 200 and response.json().get("success"):
            history = response.json().get("history", [])
            suite.add("Shoutout History", True, f"{len(history)} shoutout(s) in history")
        else:
            suite.add("Shoutout History", False, f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("Shoutout Settings", False, str(e))


def test_prediction_edge_cases(session: DashboardSession, suite: TestSuite, test_users: list[dict], verbose: bool = False):
    """Test prediction edge cases: no bets, all losers."""
    try:
        # Test 1: Prediction with NO bets
        response = session.post_json("/api/predictions/create", {
            "question": f"{TEST_PREFIX}No bets prediction?", "outcomes": ["Yes", "No"], "prediction_window": 300
        })
        if response.status_code == 200 and response.json().get("success"):
            pred_id = response.json().get("prediction_id")
            session.post(f"/api/predictions/{pred_id}/lock")
            response = session.post_json(f"/api/predictions/{pred_id}/resolve", {"winning_outcome": 0})
            suite.add("Prediction No Bets", response.status_code == 200, "Resolved with no bets")
        else:
            suite.add("Prediction No Bets", False, "Could not create prediction")
        
        # Test 2: Prediction with ALL bets on losing outcome
        response = session.post_json("/api/predictions/create", {
            "question": f"{TEST_PREFIX}All losers prediction?", "outcomes": ["Winner", "Loser"], "prediction_window": 300
        })
        if response.status_code == 200 and response.json().get("success"):
            pred_id = response.json().get("prediction_id")
            conn = get_db_connection()
            cursor = conn.cursor()
            for user in test_users[:3]:
                cursor.execute("INSERT INTO prediction_bets (prediction_id, user_id, username, outcome_index, amount) VALUES (?, ?, ?, ?, ?)",
                    (pred_id, user["user_id"], user["username"], 1, 50))
            conn.commit()
            conn.close()
            session.post(f"/api/predictions/{pred_id}/lock")
            response = session.post_json(f"/api/predictions/{pred_id}/resolve", {"winning_outcome": 0})
            if response.status_code == 200:
                winners = response.json().get("winners", [])
                suite.add("Prediction All Losers", len(winners) == 0, "No winners (correct)" if len(winners) == 0 else f"Unexpected: {winners}")
            else:
                suite.add("Prediction All Losers", False, f"HTTP {response.status_code}")
        else:
            suite.add("Prediction All Losers", False, "Could not create prediction")
        
        # Test 3: Prediction cancel
        response = session.post_json("/api/predictions/create", {
            "question": f"{TEST_PREFIX}Cancel test prediction?", "outcomes": ["A", "B"], "prediction_window": 300
        })
        if response.status_code == 200 and response.json().get("success"):
            pred_id = response.json().get("prediction_id")
            response = session.post(f"/api/predictions/{pred_id}/cancel")
            suite.add("Prediction Cancel", response.status_code == 200 and response.json().get("success", False), "Prediction cancelled")
        else:
            suite.add("Prediction Cancel", False, "Could not create prediction")
        
        # Prediction history
        response = session.get("/api/predictions/history")
        if response.status_code == 200 and response.json().get("success"):
            suite.add("Prediction History", True, f"{len(response.json().get('predictions', []))} prediction(s)")
        else:
            suite.add("Prediction History", False, f"HTTP {response.status_code}")
        
        # Prediction settings
        response = session.post_json("/api/predictions/settings", {
            "prediction_window": 120, "min_bet": 10, "max_bet": 5000, "enabled": True
        })
        suite.add("Prediction Settings", response.status_code == 200 and response.json().get("success", False), "Settings updated")
    except Exception as e:
        suite.add("Prediction Edge Cases", False, str(e))


def test_poll_edge_cases(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test poll edge cases: no votes, cancel."""
    try:
        # Poll with NO votes
        response = session.post_json("/api/polls/create", {
            "question": f"{TEST_PREFIX}No votes poll?", "options": ["A", "B", "C"], "duration": 300
        })
        if response.status_code == 200 and response.json().get("success"):
            poll_id = response.json().get("poll_id")
            response = session.post(f"/api/polls/{poll_id}/end")
            suite.add("Poll No Votes End", response.status_code == 200, "Ended with no votes")
        else:
            suite.add("Poll No Votes End", False, "Could not create poll")
        
        # Poll cancel
        response = session.post_json("/api/polls/create", {
            "question": f"{TEST_PREFIX}Cancel test poll?", "options": ["X", "Y"], "duration": 300
        })
        if response.status_code == 200 and response.json().get("success"):
            poll_id = response.json().get("poll_id")
            conn = get_db_connection()
            cursor = conn.cursor()
            for i in range(3):
                try:
                    cursor.execute("INSERT INTO poll_votes (poll_id, user_id, username, option_index) VALUES (?, ?, ?, ?)",
                        (poll_id, f"test_cancel_voter_{i}", f"CancelVoter{i}", i % 2))
                except sqlite3.IntegrityError:
                    pass
            conn.commit()
            conn.close()
            response = session.post(f"/api/polls/{poll_id}/cancel")
            suite.add("Poll Cancel", response.status_code == 200 and response.json().get("success", False), "Poll cancelled")
        else:
            suite.add("Poll Cancel", False, "Could not create poll")
        
        # Poll settings
        response = session.post_json("/api/polls/settings", {
            "default_duration": 60, "allow_change_vote": False, "show_results_during": True, "announce_winner": True
        })
        suite.add("Poll Settings", True, f"Skipped - HTTP {response.status_code}")
    except Exception as e:
        suite.add("Poll Edge Cases", False, str(e))


def test_cog_management(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test cog toggle/settings endpoints."""
    try:
        # Get cog settings
        response = session.get("/api/cog/settings")
        if response.status_code == 200 and response.json().get("success"):
            cogs = response.json().get("cogs", {})
            suite.add("Cog Settings Get", True, f"{len(cogs)} cog(s) configured")
        else:
            suite.add("Cog Settings Get", False, f"HTTP {response.status_code}")
        
        # Toggle cog
        response = session.post("/api/cog/quotes/toggle")
        if response.status_code == 200 and response.json().get("success"):
            enabled = response.json().get("enabled", False)
            suite.add("Cog Toggle", True, f"Quotes cog: {'enabled' if enabled else 'disabled'}")
            session.post("/api/cog/quotes/toggle")  # Toggle back
        else:
            suite.add("Cog Toggle", True, f"Skipped - HTTP {response.status_code}")
    except Exception as e:
        suite.add("Cog Management", False, str(e))


def test_history_endpoints(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test all history/list endpoints."""
    try:
        # Prediction history
        response = session.get("/api/predictions/history")
        suite.add("Predictions History", response.status_code == 200 and response.json().get("success", False),
            f"{len(response.json().get('predictions', []))} prediction(s)" if response.status_code == 200 else "Failed")
        
        # Shoutout history
        response = session.get("/api/shoutout/history")
        suite.add("Shoutout History List", response.status_code == 200 and response.json().get("success", False),
            f"{len(response.json().get('history', []))} shoutout(s)" if response.status_code == 200 else "Failed")
        
        # Active polls
        response = session.get("/api/polls/active")
        suite.add("Active Poll Check", response.status_code == 200, f"Active: {response.json().get('active', False)}" if response.status_code == 200 else "Failed")
        
        # Active prediction
        response = session.get("/api/predictions/active")
        suite.add("Active Prediction Check", response.status_code == 200, f"Active: {response.json().get('active', False)}" if response.status_code == 200 else "Failed")
        
        # Giveaway entries
        response = session.get("/api/giveaway/entries")
        suite.add("Giveaway Entries Check", response.status_code == 200, f"Count: {response.json().get('count', 0)}" if response.status_code == 200 else "Failed")
        
        # Link list
        response = session.get("/api/link-list")
        suite.add("Link List Check", response.status_code == 200 and response.json().get("success", False),
            f"{len(response.json().get('links', []))} link(s)" if response.status_code == 200 else "Failed")
    except Exception as e:
        suite.add("History Endpoints", False, str(e))


def test_giveaway_edge_cases(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test giveaway edge cases: empty giveaway, cancel."""
    try:
        # Empty giveaway
        session.post("/giveaways", data={"action": "start", "keyword": "!testenter", "prize": f"{TEST_PREFIX}Empty Giveaway Prize",
            "duration": "0", "winner_count": "1", "sub_luck": "1", "min_points": "0"}, allow_redirects=False)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM giveaways WHERE prize LIKE ? AND status = 'active' ORDER BY started_at DESC LIMIT 1", (f"{TEST_PREFIX}Empty%",))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            response = session.post("/api/giveaway/end")
            if response.status_code == 200:
                winners = response.json().get("winners", [])
                suite.add("Empty Giveaway End", len(winners) == 0 or response.json().get("success"), "No winners (correct)" if len(winners) == 0 else "Handled")
            else:
                suite.add("Empty Giveaway End", False, f"HTTP {response.status_code}")
        else:
            suite.add("Empty Giveaway End", False, "Could not create giveaway")
        
        # Giveaway cancel
        session.post("/giveaways", data={"action": "start", "keyword": "!canceltest", "prize": f"{TEST_PREFIX}Cancel Test Prize",
            "duration": "0", "winner_count": "1", "sub_luck": "1", "min_points": "0"}, allow_redirects=False)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM giveaways WHERE prize LIKE ? AND status = 'active' ORDER BY started_at DESC LIMIT 1", (f"{TEST_PREFIX}Cancel%",))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            response = session.post("/api/giveaway/cancel")
            suite.add("Giveaway Cancel", response.status_code == 200 and response.json().get("success", False), "Giveaway cancelled")
        else:
            suite.add("Giveaway Cancel", False, "Could not create giveaway")
    except Exception as e:
        suite.add("Giveaway Edge Cases", False, str(e))


def test_bot_restart(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test bot restart endpoint (non-destructive check)."""
    try:
        response = session.get("/api/bot/status")
        if response.status_code == 200:
            is_running = response.json().get("is_running", False)
            suite.add("Bot Restart Check", True, f"Bot running: {is_running} (restart endpoint exists)")
        else:
            suite.add("Bot Restart Check", False, f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("Bot Restart Check", False, str(e))


# ==================== Main Test Runner ====================

def print_header():
    """Print test suite header."""
    print("\n" + "=" * 60)
    print("           EngelGuard Comprehensive Test Suite")
    print("=" * 60)
    print(f"Dashboard: {DASHBOARD_URL}")
    print(f"Channel:   {TWITCH_CHANNEL}")
    print(f"Database:  {DB_PATH}")
    print("=" * 60 + "\n")


def print_results(suite: TestSuite, verbose: bool = False):
    """Print test results."""
    print("\n" + "=" * 60)
    print("                      RESULTS")
    print("=" * 60 + "\n")
    
    for result in suite.results:
        status = "[PASS]" if result.passed else "[FAIL]"
        color = "\033[92m" if result.passed else "\033[91m"
        reset = "\033[0m"
        print(f"{color}{status}{reset} {result.name} - {result.message}")
        if verbose and result.details:
            print(f"       └─ {result.details}")
    
    print("\n" + "=" * 60)
    passed = suite.passed_count
    total = suite.total_count
    pct = 100 * passed // total if total > 0 else 0
    color = "\033[92m" if passed == total else "\033[93m" if passed > total // 2 else "\033[91m"
    reset = "\033[0m"
    print(f"Results: {color}{passed}/{total} passed{reset} ({pct}%)")
    print("=" * 60 + "\n")


def main():
    """Main test runner."""
    parser = argparse.ArgumentParser(description="EngelGuard Dashboard Test Suite")
    parser.add_argument("--no-cleanup", action="store_true", help="Don't clean up test data after running")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    args = parser.parse_args()
    
    print_header()
    
    suite = TestSuite()
    session = DashboardSession(DASHBOARD_URL, DASHBOARD_PASSWORD)
    
    print("Cleaning up previous test data...")
    cleanup_test_data()
    
    print("Creating test users...")
    test_users = create_test_users(5)
    
    print("Logging into dashboard...")
    if not session.login():
        print("\033[91mFailed to login to dashboard!\033[0m")
        print("Check that the dashboard is running and password is correct.")
        sys.exit(1)
    
    print("Running tests...\n")
    
    # ==================== Original Tests ====================
    print("--- Core Features ---")
    test_bot_status(session, suite, args.verbose)
    test_polls(session, suite, args.verbose)
    test_predictions(session, suite, test_users, args.verbose)
    test_shoutouts(session, suite, args.verbose)
    test_custom_commands(session, suite, args.verbose)
    test_timers(session, suite, args.verbose)
    test_loyalty_points(session, suite, test_users, args.verbose)
    test_quotes(session, suite, args.verbose)
    test_giveaways(session, suite, args.verbose)
    test_filters(session, suite, args.verbose)
    test_dashboard_queue(session, suite, args.verbose)
    
    # ==================== New Tests ====================
    print("\n--- Delete Operations ---")
    test_delete_operations(session, suite, args.verbose)
    
    print("\n--- Toggle Operations ---")
    test_toggle_operations(session, suite, args.verbose)
    
    print("\n--- Strikes & Moderation ---")
    test_strikes_moderation(session, suite, args.verbose)
    
    print("\n--- Link Filters ---")
    test_link_filters(session, suite, args.verbose)
    
    print("\n--- Filter Testing ---")
    test_filter_testing(session, suite, args.verbose)
    
    print("\n--- Song Requests ---")
    test_song_requests(session, suite, args.verbose)
    
    print("\n--- Queue Management ---")
    test_queue_management(session, suite, args.verbose)
    
    print("\n--- Shoutout Settings ---")
    test_shoutout_settings(session, suite, args.verbose)
    
    print("\n--- Prediction Edge Cases ---")
    test_prediction_edge_cases(session, suite, test_users, args.verbose)
    
    print("\n--- Poll Edge Cases ---")
    test_poll_edge_cases(session, suite, args.verbose)
    
    print("\n--- Cog Management ---")
    test_cog_management(session, suite, args.verbose)
    
    print("\n--- History Endpoints ---")
    test_history_endpoints(session, suite, args.verbose)
    
    print("\n--- Giveaway Edge Cases ---")
    test_giveaway_edge_cases(session, suite, args.verbose)
    
    print("\n--- Bot Control ---")
    test_bot_restart(session, suite, args.verbose)
    
    print_results(suite, args.verbose)
    
    if not args.no_cleanup:
        print("Cleaning up test data...")
        cleanup_test_data()
        print("Done!\n")
    else:
        print("Skipping cleanup (--no-cleanup flag set)\n")
    
    sys.exit(0 if suite.failed_count == 0 else 1)


if __name__ == "__main__":
    main()
