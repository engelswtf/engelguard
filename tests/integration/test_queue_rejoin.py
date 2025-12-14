#!/usr/bin/env python3
"""Test queue rejoin protection."""
import sqlite3
from datetime import datetime, timedelta

DB_PATH = "/opt/twitch-bot/data/automod.db"
TEST_USER = "queue_test_user_456"
TEST_CHANNEL = "testchannel"
QUEUE_NAME = "test_queue"

def setup():
    """Setup test environment."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Ensure history table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS viewer_queue_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            queue_name TEXT NOT NULL,
            user_id TEXT NOT NULL,
            username TEXT,
            joined_at TIMESTAMP,
            left_at TIMESTAMP,
            picked INTEGER DEFAULT 0
        )
    """)
    
    # Clean up any existing test data
    cursor.execute("DELETE FROM viewer_queue_history WHERE user_id = ?", (TEST_USER,))
    cursor.execute("DELETE FROM viewer_queue WHERE user_id = ?", (TEST_USER,))
    
    conn.commit()
    conn.close()
    print("[SETUP] Test environment ready")

def simulate_leave(minutes_ago: int = 0):
    """Simulate user leaving queue X minutes ago."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Calculate leave time - use SQLite-compatible format (space separator, no microseconds)
    if minutes_ago > 0:
        leave_time = datetime.now() - timedelta(minutes=minutes_ago)
    else:
        leave_time = datetime.now()
    
    # Format as SQLite datetime: YYYY-MM-DD HH:MM:SS
    leave_time_str = leave_time.strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("""
        INSERT INTO viewer_queue_history 
        (channel, queue_name, user_id, username, left_at, picked)
        VALUES (?, ?, ?, ?, ?, 0)
    """, (TEST_CHANNEL, QUEUE_NAME, TEST_USER, "QueueTestUser", leave_time_str))
    
    conn.commit()
    conn.close()
    print(f"[SIMULATE] User left queue {minutes_ago} minutes ago (at {leave_time_str})")

def check_can_rejoin() -> bool:
    """Check if user can rejoin (simulating _add_to_queue logic)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check for recent leave (within 5 minutes)
    cursor.execute("""
        SELECT left_at FROM viewer_queue_history
        WHERE channel = ? AND queue_name = ? AND user_id = ?
        AND left_at > datetime('now', '-5 minutes')
        AND picked = 0
        ORDER BY left_at DESC LIMIT 1
    """, (TEST_CHANNEL, QUEUE_NAME, TEST_USER))
    
    recent_leave = cursor.fetchone()
    conn.close()
    
    return recent_leave is None  # Can rejoin if no recent leave

def cleanup():
    """Clean up test data."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM viewer_queue_history WHERE user_id = ?", (TEST_USER,))
    cursor.execute("DELETE FROM viewer_queue WHERE user_id = ?", (TEST_USER,))
    conn.commit()
    conn.close()
    print("[CLEANUP] Test data removed")

def test_queue_rejoin_protection():
    print("=" * 60)
    print("QUEUE REJOIN PROTECTION TEST")
    print("=" * 60)
    
    all_passed = True
    
    # Test 1: User who just left cannot rejoin
    print("\n[TEST 1] User just left (0 minutes ago)...")
    setup()
    simulate_leave(minutes_ago=0)
    can_rejoin = check_can_rejoin()
    if not can_rejoin:
        print("  ✅ Correctly BLOCKED from rejoining")
    else:
        print("  ❌ Should be blocked but was allowed")
        all_passed = False
    
    # Test 2: User who left 3 minutes ago cannot rejoin
    print("\n[TEST 2] User left 3 minutes ago...")
    setup()
    simulate_leave(minutes_ago=3)
    can_rejoin = check_can_rejoin()
    if not can_rejoin:
        print("  ✅ Correctly BLOCKED from rejoining")
    else:
        print("  ❌ Should be blocked but was allowed")
        all_passed = False
    
    # Test 3: User who left 6 minutes ago CAN rejoin
    print("\n[TEST 3] User left 6 minutes ago...")
    setup()
    simulate_leave(minutes_ago=6)
    can_rejoin = check_can_rejoin()
    if can_rejoin:
        print("  ✅ Correctly ALLOWED to rejoin")
    else:
        print("  ❌ Should be allowed but was blocked")
        all_passed = False
    
    # Test 4: User with no history can join
    print("\n[TEST 4] User with no leave history...")
    setup()  # Clean slate, no leave history
    can_rejoin = check_can_rejoin()
    if can_rejoin:
        print("  ✅ Correctly ALLOWED to join")
    else:
        print("  ❌ Should be allowed but was blocked")
        all_passed = False
    
    cleanup()
    
    print("\n" + "=" * 60)
    if all_passed:
        print("RESULT: ✅ ALL QUEUE REJOIN TESTS PASSED")
    else:
        print("RESULT: ❌ SOME TESTS FAILED")
    print("=" * 60)
    
    return all_passed

if __name__ == "__main__":
    test_queue_rejoin_protection()
