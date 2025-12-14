#!/usr/bin/env python3
"""
EngelGuard Dashboard Integration Test Suite v3

Comprehensive testing for all dashboard pages, API endpoints, form submissions,
and UI elements to ensure the dashboard is fully functional.

Usage:
    python test_dashboard_integration.py [--verbose]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from html.parser import HTMLParser

import requests

# ==================== Configuration ====================

DASHBOARD_URL = "http://10.10.10.101:5000"
DASHBOARD_PASSWORD = "newq0103Luca!?"
DB_PATH = Path("/opt/twitch-bot/data/automod.db")
TEST_PREFIX = "INTTEST_"
TWITCH_CHANNEL = "ogengels"


# ==================== Result Classes ====================

@dataclass
class TestResult:
    """Individual test result."""
    category: str
    name: str
    passed: bool
    message: str
    details: Optional[str] = None


@dataclass
class TestSuite:
    """Collection of test results."""
    results: list[TestResult] = field(default_factory=list)
    
    def add(self, category: str, name: str, passed: bool, message: str, details: str = None):
        self.results.append(TestResult(category, name, passed, message, details))
    
    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)
    
    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)
    
    @property
    def total_count(self) -> int:
        return len(self.results)
    
    def get_by_category(self, category: str) -> list[TestResult]:
        return [r for r in self.results if r.category == category]


# ==================== HTML Parser for Element Detection ====================

class FormParser(HTMLParser):
    """Parse HTML to find forms, buttons, and CSRF tokens."""
    
    def __init__(self):
        super().__init__()
        self.forms = []
        self.buttons = []
        self.csrf_tokens = []
        self.links = []
        self.inputs = []
        self.current_form = None
        self.title = ""
        self.in_title = False
        self.meta_csrf = ""
    
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        
        if tag == "title":
            self.in_title = True
        
        # Check for meta CSRF token
        if tag == "meta":
            name = attrs_dict.get("name", "")
            if "csrf" in name.lower():
                self.meta_csrf = attrs_dict.get("content", "")
        
        if tag == "form":
            self.current_form = {
                "action": attrs_dict.get("action", ""),
                "method": attrs_dict.get("method", "GET").upper(),
                "inputs": [],
                "has_csrf": False
            }
        
        elif tag == "input":
            input_info = {
                "name": attrs_dict.get("name", ""),
                "type": attrs_dict.get("type", "text"),
                "required": "required" in attrs_dict,
                "value": attrs_dict.get("value", "")
            }
            if self.current_form:
                self.current_form["inputs"].append(input_info)
                if input_info["name"] == "csrf_token":
                    self.current_form["has_csrf"] = True
                    self.csrf_tokens.append(input_info["value"])
            self.inputs.append(input_info)
        
        elif tag == "button":
            self.buttons.append({
                "type": attrs_dict.get("type", "submit"),
                "name": attrs_dict.get("name", ""),
                "class": attrs_dict.get("class", ""),
                "id": attrs_dict.get("id", "")
            })
        
        elif tag == "a":
            href = attrs_dict.get("href", "")
            if href and not href.startswith("#") and not href.startswith("javascript:"):
                self.links.append(href)
    
    def handle_endtag(self, tag):
        if tag == "form" and self.current_form:
            self.forms.append(self.current_form)
            self.current_form = None
        if tag == "title":
            self.in_title = False
    
    def handle_data(self, data):
        if self.in_title:
            self.title += data


# ==================== Dashboard Session ====================

class DashboardSession:
    """Manages authenticated session with the dashboard."""
    
    def __init__(self, base_url: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.password = password
        self.session = requests.Session()
        self._logged_in = False
        self._csrf_token = ""
    
    def _extract_csrf(self, html: str) -> str:
        """Extract CSRF token from HTML (meta tag or input)."""
        # Try meta tag first
        meta_match = re.search(r'<meta[^>]*name="csrf-token"[^>]*content="([^"]+)"', html, re.I)
        if not meta_match:
            meta_match = re.search(r'<meta[^>]*content="([^"]+)"[^>]*name="csrf-token"', html, re.I)
        if meta_match:
            return meta_match.group(1)
        
        # Try input field
        input_match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
        if not input_match:
            input_match = re.search(r'value="([^"]+)"[^>]*name="csrf_token"', html)
        if input_match:
            return input_match.group(1)
        
        return ""
    
    def login(self) -> bool:
        """Authenticate with the dashboard."""
        try:
            # Get login page for CSRF token
            login_page = self.session.get(f"{self.base_url}/login", timeout=10)
            csrf_token = self._extract_csrf(login_page.text)
            
            response = self.session.post(
                f"{self.base_url}/login",
                data={"password": self.password, "csrf_token": csrf_token},
                allow_redirects=False,
                timeout=10
            )
            
            self._logged_in = response.status_code in [302, 303]
            return self._logged_in
        except Exception as e:
            print(f"Login error: {e}")
            return False
    
    def get(self, path: str, **kwargs) -> requests.Response:
        """GET request."""
        kwargs.setdefault("timeout", 10)
        return self.session.get(f"{self.base_url}{path}", **kwargs)
    
    def post(self, path: str, data: dict = None, **kwargs) -> requests.Response:
        """POST request with CSRF token."""
        kwargs.setdefault("timeout", 10)
        if data is None:
            data = {}
        
        # Get CSRF token if needed
        if "csrf_token" not in data:
            page = self.session.get(f"{self.base_url}{path}", timeout=10)
            csrf_token = self._extract_csrf(page.text)
            if csrf_token:
                data["csrf_token"] = csrf_token
        
        return self.session.post(f"{self.base_url}{path}", data=data, **kwargs)
    
    def post_json(self, path: str, json_data: dict, **kwargs) -> requests.Response:
        """POST JSON request with CSRF token from meta tag."""
        kwargs.setdefault("timeout", 10)
        headers = kwargs.pop("headers", {})
        headers["Content-Type"] = "application/json"
        
        # Get a page to extract CSRF token from meta tag
        page = self.session.get(f"{self.base_url}/dashboard", timeout=10)
        csrf_token = self._extract_csrf(page.text)
        
        if csrf_token:
            headers["X-CSRFToken"] = csrf_token
        
        return self.session.post(
            f"{self.base_url}{path}",
            json=json_data,
            headers=headers,
            **kwargs
        )
    
    def post_api(self, path: str, data: dict = None, **kwargs) -> requests.Response:
        """POST to API endpoint with CSRF token in header."""
        kwargs.setdefault("timeout", 10)
        headers = kwargs.pop("headers", {})
        
        # Get CSRF token from a page
        page = self.session.get(f"{self.base_url}/dashboard", timeout=10)
        csrf_token = self._extract_csrf(page.text)
        
        if csrf_token:
            headers["X-CSRFToken"] = csrf_token
        
        return self.session.post(f"{self.base_url}{path}", data=data, headers=headers, **kwargs)
    
    def parse_page(self, path: str) -> tuple[requests.Response, FormParser]:
        """Get a page and parse its HTML."""
        response = self.get(path)
        parser = FormParser()
        try:
            parser.feed(response.text)
        except Exception:
            pass
        return response, parser


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
    
    tables_and_columns = [
        ("custom_commands", "name", f"{TEST_PREFIX}%"),
        ("timers", "name", f"{TEST_PREFIX}%"),
        ("quotes", "quote_text", f"{TEST_PREFIX}%"),
        ("giveaways", "prize", f"{TEST_PREFIX}%"),
        ("predictions", "question", f"{TEST_PREFIX}%"),
        ("polls", "question", f"{TEST_PREFIX}%"),
        ("banned_words", "word", f"{TEST_PREFIX}%"),
        ("shoutout_history", "target_user", f"{TEST_PREFIX}%"),
        ("user_loyalty", "user_id", f"inttest_%"),
        ("user_strikes", "user_id", f"inttest_%"),
        ("strike_history", "user_id", f"inttest_%"),
        ("users", "user_id", f"inttest_%"),
        ("link_lists", "domain", f"inttest%"),
        ("song_queue", "requested_by", f"{TEST_PREFIX}%"),
        ("viewer_queue", "username", f"{TEST_PREFIX}%"),
    ]
    
    for table, column, pattern in tables_and_columns:
        try:
            cursor.execute(f"DELETE FROM {table} WHERE {column} LIKE ?", (pattern,))
        except sqlite3.OperationalError:
            pass
    
    try:
        cursor.execute("DELETE FROM giveaway_entries WHERE giveaway_id IN (SELECT id FROM giveaways WHERE prize LIKE ?)", (f"{TEST_PREFIX}%",))
        cursor.execute("DELETE FROM giveaway_winners WHERE giveaway_id IN (SELECT id FROM giveaways WHERE prize LIKE ?)", (f"{TEST_PREFIX}%",))
        cursor.execute("DELETE FROM poll_votes WHERE poll_id IN (SELECT id FROM polls WHERE question LIKE ?)", (f"{TEST_PREFIX}%",))
        cursor.execute("DELETE FROM prediction_bets WHERE prediction_id IN (SELECT id FROM predictions WHERE question LIKE ?)", (f"{TEST_PREFIX}%",))
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    conn.close()


# ==================== Page Tests ====================

def test_all_pages(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test that all dashboard pages load correctly."""
    
    pages = [
        ("/login", "Login Page", False),
        ("/dashboard", "Dashboard", True),
        ("/commands", "Commands", True),
        ("/timers", "Timers", True),
        ("/quotes", "Quotes", True),
        ("/giveaways", "Giveaways", True),
        ("/polls", "Polls", True),
        ("/predictions", "Predictions", True),
        ("/loyalty", "Loyalty", True),
        ("/filters", "Filters", True),
        ("/filters/banned-words", "Banned Words", True),
        ("/songrequests", "Song Requests", True),
        ("/queue-management", "Queue Management", True),
        ("/settings", "Settings", True),
        ("/modlog", "Mod Log", True),
        ("/users", "Users", True),
        ("/credentials", "Credentials", True),
        ("/shoutout-settings", "Shoutout Settings", True),
        ("/alerts-settings", "Alerts Settings", True),
        ("/raid-settings", "Raid Settings", True),
        ("/strikes", "Strikes", True),
    ]
    
    for path, name, requires_login in pages:
        try:
            response, parser = session.parse_page(path)
            
            if response.status_code == 200:
                has_html = "<html" in response.text.lower()
                has_body = "<body" in response.text.lower()
                
                is_error_page = (
                    "<title>500 Internal Server Error</title>" in response.text or
                    "<title>Error</title>" in response.text or
                    "Traceback (most recent call last)" in response.text or
                    "Internal Server Error" in parser.title
                )
                
                if has_html and has_body and not is_error_page:
                    details = f"Forms: {len(parser.forms)}, Buttons: {len(parser.buttons)}, Links: {len(parser.links)}"
                    suite.add("Pages", f"{name} ({path})", True, "Loads correctly", details)
                else:
                    suite.add("Pages", f"{name} ({path})", False, 
                             "Server error page" if is_error_page else "Invalid structure")
            elif response.status_code == 302:
                suite.add("Pages", f"{name} ({path})", True, "Redirects (expected)")
            else:
                suite.add("Pages", f"{name} ({path})", False, f"HTTP {response.status_code}")
        except Exception as e:
            suite.add("Pages", f"{name} ({path})", False, f"Error: {str(e)[:50]}")


# ==================== API Endpoint Tests ====================

def test_api_endpoints(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test all API endpoints respond correctly."""
    
    get_endpoints = [
        ("/api/bot/status", "Bot Status"),
        ("/api/cog/settings", "Cog Settings"),
        ("/api/link-list", "Link List"),
        ("/api/giveaway/entries", "Giveaway Entries"),
        ("/api/polls/active", "Active Poll"),
        ("/api/predictions/active", "Active Prediction"),
        ("/api/predictions/history", "Prediction History"),
        ("/api/shoutout/history", "Shoutout History"),
        ("/queue-management/data", "Queue Data"),
    ]
    
    for path, name in get_endpoints:
        try:
            response = session.get(path)
            if response.status_code == 200:
                try:
                    data = response.json()
                    suite.add("API GET", f"{name} ({path})", True, 
                             f"Returns JSON: {list(data.keys())[:3]}...")
                except json.JSONDecodeError:
                    suite.add("API GET", f"{name} ({path})", False, "Invalid JSON response")
            else:
                suite.add("API GET", f"{name} ({path})", False, f"HTTP {response.status_code}")
        except Exception as e:
            suite.add("API GET", f"{name} ({path})", False, f"Error: {str(e)[:50]}")
    
    dynamic_get_endpoints = [
        ("/api/command/test", "Get Command"),
        ("/api/timer/test", "Get Timer"),
        ("/api/quote/1", "Get Quote"),
        ("/api/strikes/12345/history", "Strike History"),
        ("/api/user/12345/history", "User History"),
    ]
    
    for path, name in dynamic_get_endpoints:
        try:
            response = session.get(path)
            if response.status_code in [200, 404]:
                suite.add("API GET Dynamic", f"{name} ({path})", True, 
                         f"HTTP {response.status_code} (endpoint exists)")
            else:
                suite.add("API GET Dynamic", f"{name} ({path})", False, f"HTTP {response.status_code}")
        except Exception as e:
            suite.add("API GET Dynamic", f"{name} ({path})", False, f"Error: {str(e)[:50]}")


# ==================== Form Submission Tests ====================

def test_form_submissions(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test form submissions for CRUD operations."""
    
    # Test command creation
    try:
        response = session.post("/commands", data={
            "action": "add",
            "name": f"{TEST_PREFIX}testcmd",
            "response": "Test response",
            "cooldown": "5",
            "user_level": "everyone"
        }, allow_redirects=False)
        
        if response.status_code in [200, 302, 303]:
            suite.add("Forms", "Create Command", True, "Command created")
            
            # Test command deletion via API
            del_response = session.post_api(f"/api/command/{TEST_PREFIX}testcmd/delete")
            suite.add("Forms", "Delete Command API", 
                     del_response.status_code == 200,
                     f"HTTP {del_response.status_code}")
        else:
            suite.add("Forms", "Create Command", False, f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("Forms", "Create Command", False, f"Error: {str(e)[:50]}")
    
    # Test timer creation
    try:
        response = session.post("/timers", data={
            "action": "add",
            "name": f"{TEST_PREFIX}testtimer",
            "message": "Test timer message",
            "interval": "300",
            "min_messages": "5"
        }, allow_redirects=False)
        
        if response.status_code in [200, 302, 303]:
            suite.add("Forms", "Create Timer", True, "Timer created")
            
            # Test timer toggle
            toggle_response = session.post_api(f"/api/timer/{TEST_PREFIX}testtimer/toggle")
            suite.add("Forms", "Toggle Timer API",
                     toggle_response.status_code == 200,
                     f"HTTP {toggle_response.status_code}")
            
            # Test timer deletion
            del_response = session.post_api(f"/api/timer/{TEST_PREFIX}testtimer/delete")
            suite.add("Forms", "Delete Timer API",
                     del_response.status_code == 200,
                     f"HTTP {del_response.status_code}")
        else:
            suite.add("Forms", "Create Timer", False, f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("Forms", "Create Timer", False, f"Error: {str(e)[:50]}")
    
    # Test quote creation
    try:
        response = session.post("/quotes", data={
            "action": "add",
            "quote_text": f"{TEST_PREFIX}Test quote text",
            "author": "TestAuthor",
            "game": "TestGame"
        }, allow_redirects=False)
        
        if response.status_code in [200, 302, 303]:
            suite.add("Forms", "Create Quote", True, "Quote created")
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM quotes WHERE quote_text LIKE ? ORDER BY id DESC LIMIT 1", 
                          (f"{TEST_PREFIX}%",))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                del_response = session.post_api(f"/api/quote/{row['id']}/delete")
                suite.add("Forms", "Delete Quote API",
                         del_response.status_code == 200,
                         f"HTTP {del_response.status_code}")
        else:
            suite.add("Forms", "Create Quote", False, f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("Forms", "Create Quote", False, f"Error: {str(e)[:50]}")
    
    # Test giveaway creation
    try:
        response = session.post("/giveaways", data={
            "action": "start",
            "keyword": "!inttest",
            "prize": f"{TEST_PREFIX}Test Prize",
            "duration": "0",
            "winner_count": "1",
            "sub_luck": "1",
            "min_points": "0"
        }, allow_redirects=False)
        
        if response.status_code in [200, 302, 303]:
            suite.add("Forms", "Create Giveaway", True, "Giveaway started")
            
            cancel_response = session.post_api("/api/giveaway/cancel")
            suite.add("Forms", "Cancel Giveaway API", 
                     cancel_response.status_code == 200,
                     f"HTTP {cancel_response.status_code}")
        else:
            suite.add("Forms", "Create Giveaway", False, f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("Forms", "Create Giveaway", False, f"Error: {str(e)[:50]}")
    
    # Test poll creation via JSON API
    try:
        response = session.post_json("/api/polls/create", {
            "question": f"{TEST_PREFIX}Test Poll Question?",
            "options": ["Option A", "Option B", "Option C"],
            "duration": 300
        })
        
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                poll_id = data.get("poll_id")
                suite.add("Forms", "Create Poll API", True, f"Poll ID: {poll_id}")
                
                cancel_response = session.post_api(f"/api/polls/{poll_id}/cancel")
                suite.add("Forms", "Cancel Poll API", 
                         cancel_response.status_code == 200,
                         f"HTTP {cancel_response.status_code}")
            else:
                suite.add("Forms", "Create Poll API", False, f"API error: {data.get('error', 'unknown')}")
        else:
            suite.add("Forms", "Create Poll API", False, f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("Forms", "Create Poll API", False, f"Error: {str(e)[:50]}")
    
    # Test prediction creation via JSON API
    try:
        response = session.post_json("/api/predictions/create", {
            "question": f"{TEST_PREFIX}Test Prediction?",
            "outcomes": ["Outcome 1", "Outcome 2"],
            "duration": 300
        })
        
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                pred_id = data.get("prediction_id")
                suite.add("Forms", "Create Prediction API", True, f"Prediction ID: {pred_id}")
                
                cancel_response = session.post_api(f"/api/predictions/{pred_id}/cancel")
                suite.add("Forms", "Cancel Prediction API",
                         cancel_response.status_code == 200,
                         f"HTTP {cancel_response.status_code}")
            else:
                suite.add("Forms", "Create Prediction API", False, f"API error: {data.get('error', 'unknown')}")
        else:
            suite.add("Forms", "Create Prediction API", False, f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("Forms", "Create Prediction API", False, f"Error: {str(e)[:50]}")
    
    # Test settings update
    try:
        response = session.post("/settings", data={
            "bot_prefix": "!",
            "response_delay": "1"
        }, allow_redirects=False)
        suite.add("Forms", "Update Settings", response.status_code in [200, 302, 303],
                 f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("Forms", "Update Settings", False, f"Error: {str(e)[:50]}")


# ==================== POST API Endpoint Tests ====================

def test_post_api_endpoints(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test POST API endpoints."""
    
    # Test filter sensitivity
    try:
        response = session.post_json("/api/filters/sensitivity", {
            "caps_threshold": 70,
            "spam_threshold": 5,
            "emote_threshold": 10
        })
        suite.add("API POST", "Filter Sensitivity", 
                 response.status_code == 200,
                 f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("API POST", "Filter Sensitivity", False, f"Error: {str(e)[:50]}")
    
    # Test filter testing endpoint
    try:
        response = session.post_json("/api/test-filter", {
            "message": "This is a test message"
        })
        suite.add("API POST", "Test Filter", 
                 response.status_code == 200,
                 f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("API POST", "Test Filter", False, f"Error: {str(e)[:50]}")
    
    # Test cog toggle
    try:
        response = session.post_api("/api/cog/quotes/toggle")
        if response.status_code == 200:
            session.post_api("/api/cog/quotes/toggle")  # Toggle back
        suite.add("API POST", "Cog Toggle", 
                 response.status_code == 200,
                 f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("API POST", "Cog Toggle", False, f"Error: {str(e)[:50]}")
    
    # Test shoutout settings
    try:
        response = session.post_json("/api/shoutout/settings", {
            "enabled": True,
            "auto_shoutout": False,
            "cooldown": 300
        })
        suite.add("API POST", "Shoutout Settings",
                 response.status_code == 200,
                 f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("API POST", "Shoutout Settings", False, f"Error: {str(e)[:50]}")
    
    # Test prediction settings
    try:
        response = session.post_json("/api/predictions/settings", {
            "prediction_window": 120,
            "min_bet": 10,
            "max_bet": 5000,
            "enabled": True
        })
        suite.add("API POST", "Prediction Settings",
                 response.status_code == 200,
                 f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("API POST", "Prediction Settings", False, f"Error: {str(e)[:50]}")
    
    # Test poll settings
    try:
        response = session.post_json("/api/polls/settings", {
            "default_duration": 60,
            "allow_change_vote": False,
            "show_results_during": True,
            "announce_winner": True
        })
        suite.add("API POST", "Poll Settings",
                 response.status_code == 200,
                 f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("API POST", "Poll Settings", False, f"Error: {str(e)[:50]}")
    
    # Test link list add
    try:
        response = session.post_json("/api/link-list", {
            "domain": f"inttest{int(time.time())}.com",
            "list_type": "whitelist"
        })
        suite.add("API POST", "Add Link to List",
                 response.status_code == 200,
                 f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("API POST", "Add Link to List", False, f"Error: {str(e)[:50]}")
    
    # Test song request toggle
    try:
        response = session.post_api("/api/songrequests/toggle")
        suite.add("API POST", "Song Request Toggle",
                 response.status_code == 200,
                 f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("API POST", "Song Request Toggle", False, f"Error: {str(e)[:50]}")


# ==================== Element Detection Tests ====================

def test_page_elements(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Check for required elements on each page."""
    
    pages_to_check = [
        ("/commands", "Commands", ["add", "delete"], True),
        ("/timers", "Timers", ["add", "delete"], True),
        ("/quotes", "Quotes", ["add"], True),
        ("/giveaways", "Giveaways", ["start"], True),
        ("/filters", "Filters", ["save"], True),
        ("/settings", "Settings", ["save"], True),
        ("/credentials", "Credentials", ["save"], True),
        ("/loyalty", "Loyalty", ["save"], True),
        ("/songrequests", "Song Requests", ["save"], True),
        ("/shoutout-settings", "Shoutout Settings", ["save"], True),
        ("/alerts-settings", "Alerts Settings", ["save"], True),
        ("/polls", "Polls", ["create"], False),
        ("/predictions", "Predictions", ["create"], False),
    ]
    
    for path, name, expected_actions, check_csrf in pages_to_check:
        try:
            response, parser = session.parse_page(path)
            
            if response.status_code != 200:
                suite.add("Elements", f"{name} - Page Load", False, f"HTTP {response.status_code}")
                continue
            
            has_forms = len(parser.forms) > 0
            forms_with_csrf = sum(1 for f in parser.forms if f["has_csrf"])
            
            # Also check for meta CSRF token
            has_meta_csrf = bool(parser.meta_csrf)
            csrf_ok = not check_csrf or forms_with_csrf == len(parser.forms) or len(parser.forms) == 0 or has_meta_csrf
            
            has_buttons = len(parser.buttons) > 0
            
            action_buttons_found = []
            for action in expected_actions:
                if action.lower() in response.text.lower():
                    action_buttons_found.append(action)
            
            all_actions_found = len(action_buttons_found) == len(expected_actions)
            
            details = f"Forms: {len(parser.forms)}, CSRF: {forms_with_csrf}/{len(parser.forms)}, Meta CSRF: {has_meta_csrf}, Buttons: {len(parser.buttons)}"
            
            if has_forms or has_buttons:
                suite.add("Elements", f"{name} - Has Forms/Buttons", True, details)
            else:
                suite.add("Elements", f"{name} - Has Forms/Buttons", False, "No forms or buttons found")
            
            if csrf_ok:
                suite.add("Elements", f"{name} - CSRF Protection", True, 
                         f"{forms_with_csrf} forms + meta: {has_meta_csrf}")
            else:
                suite.add("Elements", f"{name} - CSRF Protection", False, 
                         f"Missing CSRF: {len(parser.forms) - forms_with_csrf} forms")
            
            if all_actions_found:
                suite.add("Elements", f"{name} - Action Buttons", True, f"Found: {action_buttons_found}")
            else:
                missing = set(expected_actions) - set(action_buttons_found)
                suite.add("Elements", f"{name} - Action Buttons", False, f"Missing: {missing}")
                
        except Exception as e:
            suite.add("Elements", f"{name}", False, f"Error: {str(e)[:50]}")


# ==================== Navigation Tests ====================

def test_navigation(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test that navigation links work correctly."""
    
    try:
        response, parser = session.parse_page("/dashboard")
        
        if response.status_code != 200:
            suite.add("Navigation", "Dashboard Nav", False, f"HTTP {response.status_code}")
            return
        
        expected_links = [
            "/dashboard", "/commands", "/timers", "/quotes", "/giveaways",
            "/polls", "/predictions", "/loyalty", "/filters", "/songrequests",
            "/settings", "/modlog", "/users"
        ]
        
        found_links = []
        for link in parser.links:
            for expected in expected_links:
                if expected in link:
                    found_links.append(expected)
                    break
        
        found_links = list(set(found_links))
        missing_links = [l for l in expected_links if l not in found_links]
        
        if len(missing_links) == 0:
            suite.add("Navigation", "All Nav Links Present", True, f"Found {len(found_links)} links")
        else:
            suite.add("Navigation", "All Nav Links Present", False, f"Missing: {missing_links[:5]}")
        
        accessible_count = 0
        for link in expected_links[:5]:
            try:
                resp = session.get(link)
                if resp.status_code == 200:
                    accessible_count += 1
            except:
                pass
        
        suite.add("Navigation", "Nav Links Accessible", accessible_count >= 4, 
                 f"{accessible_count}/5 tested links accessible")
        
    except Exception as e:
        suite.add("Navigation", "Navigation Test", False, f"Error: {str(e)[:50]}")


# ==================== Error Handling Tests ====================

def test_error_handling(session: DashboardSession, suite: TestSuite, verbose: bool = False):
    """Test error handling for invalid requests."""
    
    try:
        response = session.get("/nonexistent-page-12345")
        suite.add("Errors", "404 Handling", response.status_code in [404, 302], 
                 f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("Errors", "404 Handling", False, f"Error: {str(e)[:50]}")
    
    try:
        response = session.get("/api/command/nonexistent_cmd_12345")
        suite.add("Errors", "Invalid API Request", response.status_code in [200, 404],
                 f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("Errors", "Invalid API Request", False, f"Error: {str(e)[:50]}")
    
    try:
        response = session.session.post(
            f"{session.base_url}/api/polls/create",
            data="invalid json",
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        suite.add("Errors", "Invalid JSON Handling", response.status_code in [400, 415, 500],
                 f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("Errors", "Invalid JSON Handling", False, f"Error: {str(e)[:50]}")
    
    try:
        response = session.post_json("/api/polls/create", {
            "question": "Test?"
        })
        suite.add("Errors", "Missing Fields Handling", response.status_code in [200, 400],
                 f"HTTP {response.status_code}")
    except Exception as e:
        suite.add("Errors", "Missing Fields Handling", False, f"Error: {str(e)[:50]}")


# ==================== Main ====================

def print_header():
    """Print test suite header."""
    print("\n" + "=" * 70)
    print("        EngelGuard Dashboard Integration Test Suite v3")
    print("=" * 70)
    print(f"Dashboard URL: {DASHBOARD_URL}")
    print(f"Database:      {DB_PATH}")
    print(f"Test Prefix:   {TEST_PREFIX}")
    print("=" * 70 + "\n")


def print_category_results(suite: TestSuite, category: str):
    """Print results for a specific category."""
    results = suite.get_by_category(category)
    if not results:
        return
    
    print(f"\n--- {category} ---")
    for result in results:
        status = "✓" if result.passed else "✗"
        color = "\033[92m" if result.passed else "\033[91m"
        reset = "\033[0m"
        print(f"  {color}{status}{reset} {result.name}: {result.message}")
        if result.details:
            print(f"      └─ {result.details}")


def print_summary(suite: TestSuite):
    """Print test summary."""
    print("\n" + "=" * 70)
    print("                         SUMMARY")
    print("=" * 70)
    
    categories = {}
    for result in suite.results:
        if result.category not in categories:
            categories[result.category] = {"passed": 0, "failed": 0}
        if result.passed:
            categories[result.category]["passed"] += 1
        else:
            categories[result.category]["failed"] += 1
    
    print(f"\n{'Category':<25} {'Passed':<10} {'Failed':<10} {'Total':<10}")
    print("-" * 55)
    
    for cat, counts in categories.items():
        total = counts["passed"] + counts["failed"]
        color = "\033[92m" if counts["failed"] == 0 else "\033[93m" if counts["passed"] > counts["failed"] else "\033[91m"
        reset = "\033[0m"
        print(f"{cat:<25} {color}{counts['passed']:<10}{reset} {counts['failed']:<10} {total:<10}")
    
    print("-" * 55)
    total_passed = suite.passed_count
    total_failed = suite.failed_count
    total = suite.total_count
    pct = 100 * total_passed // total if total > 0 else 0
    
    color = "\033[92m" if total_failed == 0 else "\033[93m" if total_passed > total_failed else "\033[91m"
    reset = "\033[0m"
    print(f"{'TOTAL':<25} {color}{total_passed:<10}{reset} {total_failed:<10} {total:<10}")
    print(f"\n{color}Overall: {total_passed}/{total} passed ({pct}%){reset}")
    print("=" * 70 + "\n")
    
    failed = [r for r in suite.results if not r.passed]
    if failed:
        print("\n--- FAILED TESTS ---")
        for result in failed:
            print(f"  ✗ [{result.category}] {result.name}: {result.message}")
        print()


def main():
    """Main test runner."""
    parser = argparse.ArgumentParser(description="EngelGuard Dashboard Integration Tests v3")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    parser.add_argument("--no-cleanup", action="store_true", help="Don't clean up test data")
    args = parser.parse_args()
    
    print_header()
    
    suite = TestSuite()
    session = DashboardSession(DASHBOARD_URL, DASHBOARD_PASSWORD)
    
    print("Cleaning up previous test data...")
    cleanup_test_data()
    
    print("Logging into dashboard...")
    if not session.login():
        print("\033[91mFailed to login to dashboard!\033[0m")
        print("Check that the dashboard is running and password is correct.")
        sys.exit(1)
    print("Login successful!\n")
    
    print("Running tests...")
    
    print("\n[1/7] Testing all pages load correctly...")
    test_all_pages(session, suite, args.verbose)
    
    print("[2/7] Testing API GET endpoints...")
    test_api_endpoints(session, suite, args.verbose)
    
    print("[3/7] Testing form submissions (CRUD)...")
    test_form_submissions(session, suite, args.verbose)
    
    print("[4/7] Testing API POST endpoints...")
    test_post_api_endpoints(session, suite, args.verbose)
    
    print("[5/7] Checking page elements (forms, buttons, CSRF)...")
    test_page_elements(session, suite, args.verbose)
    
    print("[6/7] Testing navigation...")
    test_navigation(session, suite, args.verbose)
    
    print("[7/7] Testing error handling...")
    test_error_handling(session, suite, args.verbose)
    
    for category in ["Pages", "API GET", "API GET Dynamic", "Forms", "API POST", "Elements", "Navigation", "Errors"]:
        print_category_results(suite, category)
    
    print_summary(suite)
    
    if not args.no_cleanup:
        print("Cleaning up test data...")
        cleanup_test_data()
        print("Done!\n")
    
    sys.exit(0 if suite.failed_count == 0 else 1)


if __name__ == "__main__":
    main()
