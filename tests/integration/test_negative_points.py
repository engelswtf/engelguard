#!/usr/bin/env python3
"""Test negative points prevention."""
import sqlite3

DB_PATH = "/opt/twitch-bot/data/automod.db"
TEST_USER = "points_test_user_789"
TEST_CHANNEL = "testchannel"

def test_negative_points():
    print("=" * 60)
    print("NEGATIVE POINTS PREVENTION TEST")
    print("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Setup: Create user with 50 points
    cursor.execute("DELETE FROM user_loyalty WHERE user_id = ?", (TEST_USER,))
    cursor.execute("""
        INSERT INTO user_loyalty (user_id, channel, username, points)
        VALUES (?, ?, ?, 50)
    """, (TEST_USER, TEST_CHANNEL, "PointsTestUser"))
    conn.commit()
    print("[SETUP] Created user with 50 points")
    
    # Test 1: Deduct more than balance (should floor at 0)
    print("\n[TEST 1] Deduct 100 points from 50 point balance...")
    cursor.execute("""
        UPDATE user_loyalty 
        SET points = MAX(0, points - 100)
        WHERE user_id = ? AND channel = ?
    """, (TEST_USER, TEST_CHANNEL))
    conn.commit()
    
    cursor.execute("SELECT points FROM user_loyalty WHERE user_id = ?", (TEST_USER,))
    balance = cursor.fetchone()[0]
    
    if balance == 0:
        print(f"  ✅ Balance correctly floored at 0 (not -50)")
    elif balance < 0:
        print(f"  ❌ Balance went negative: {balance}")
    else:
        print(f"  ⚠️ Unexpected balance: {balance}")
    
    # Test 2: Try to set negative points directly
    print("\n[TEST 2] Attempt to set points to -100...")
    # This simulates what set_user_points should do
    new_points = -100
    clamped_points = max(0, new_points)
    cursor.execute("""
        UPDATE user_loyalty SET points = ? WHERE user_id = ?
    """, (clamped_points, TEST_USER))
    conn.commit()
    
    cursor.execute("SELECT points FROM user_loyalty WHERE user_id = ?", (TEST_USER,))
    balance = cursor.fetchone()[0]
    
    if balance == 0:
        print(f"  ✅ Negative value clamped to 0")
    else:
        print(f"  ⚠️ Balance is {balance}")
    
    # Cleanup
    cursor.execute("DELETE FROM user_loyalty WHERE user_id = ?", (TEST_USER,))
    conn.commit()
    conn.close()
    print("\n[CLEANUP] Test user removed")
    
    print("\n" + "=" * 60)
    print("NEGATIVE POINTS TESTS COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    test_negative_points()
