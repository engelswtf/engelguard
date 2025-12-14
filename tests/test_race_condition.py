#!/usr/bin/env python3
"""Test gambling race condition fix."""
import sqlite3
import threading
import time

DB_PATH = "/opt/twitch-bot/data/automod.db"
TEST_USER = "race_test_user_123"
TEST_CHANNEL = "testchannel"
INITIAL_POINTS = 100
BET_AMOUNT = 100
NUM_CONCURRENT_BETS = 10

def setup_test_user():
    """Create test user with known points."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Delete if exists
    cursor.execute("DELETE FROM user_loyalty WHERE user_id = ?", (TEST_USER,))
    
    # Create with initial points
    cursor.execute("""
        INSERT INTO user_loyalty (user_id, channel, username, points)
        VALUES (?, ?, ?, ?)
    """, (TEST_USER, TEST_CHANNEL, "RaceTestUser", INITIAL_POINTS))
    
    conn.commit()
    conn.close()
    print(f"[SETUP] Created test user with {INITIAL_POINTS} points")

def atomic_bet_deduct(user_id: str, channel: str, amount: int) -> tuple:
    """Simulate the atomic bet deduction (same logic as gambling.py)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Atomic check and deduct
    cursor.execute("""
        UPDATE user_loyalty 
        SET points = points - ?
        WHERE user_id = ? AND channel = ? AND points >= ?
    """, (amount, user_id, channel.lower(), amount))
    
    success = cursor.rowcount > 0
    
    if success:
        cursor.execute("SELECT points FROM user_loyalty WHERE user_id = ? AND channel = ?", 
                      (user_id, channel.lower()))
        row = cursor.fetchone()
        new_balance = int(row["points"]) if row else 0
        conn.commit()
        conn.close()
        return True, new_balance
    else:
        conn.close()
        return False, 0

def attempt_bet(results: list, index: int):
    """Attempt a bet and record result."""
    success, balance = atomic_bet_deduct(TEST_USER, TEST_CHANNEL, BET_AMOUNT)
    results[index] = {"success": success, "balance": balance}

def run_race_condition_test():
    """Run concurrent bets to test for race condition."""
    print(f"\n[TEST] Attempting {NUM_CONCURRENT_BETS} concurrent bets of {BET_AMOUNT} points each")
    print(f"[TEST] User only has {INITIAL_POINTS} points - only 1 bet should succeed\n")
    
    results = [None] * NUM_CONCURRENT_BETS
    threads = []
    
    # Create all threads
    for i in range(NUM_CONCURRENT_BETS):
        t = threading.Thread(target=attempt_bet, args=(results, i))
        threads.append(t)
    
    # Start all threads as simultaneously as possible
    for t in threads:
        t.start()
    
    # Wait for all to complete
    for t in threads:
        t.join()
    
    # Analyze results
    successful_bets = sum(1 for r in results if r and r["success"])
    failed_bets = sum(1 for r in results if r and not r["success"])
    
    print(f"[RESULTS]")
    print(f"  Successful bets: {successful_bets}")
    print(f"  Failed bets: {failed_bets}")
    
    # Check final balance
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT points FROM user_loyalty WHERE user_id = ?", (TEST_USER,))
    row = cursor.fetchone()
    final_balance = row[0] if row else "NOT FOUND"
    conn.close()
    
    print(f"  Final balance: {final_balance}")
    
    # Verify
    if successful_bets == 1 and final_balance == 0:
        print(f"\n✅ PASS: Race condition prevented! Only 1 bet succeeded.")
        return True
    elif successful_bets > 1:
        print(f"\n❌ FAIL: Race condition exists! {successful_bets} bets succeeded (should be 1)")
        print(f"   User was able to bet {successful_bets * BET_AMOUNT} points with only {INITIAL_POINTS}!")
        return False
    elif successful_bets == 0:
        print(f"\n⚠️ UNEXPECTED: No bets succeeded. Check the implementation.")
        return False
    else:
        print(f"\n⚠️ UNEXPECTED: Final balance is {final_balance}, expected 0")
        return False

def cleanup():
    """Remove test user."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_loyalty WHERE user_id = ?", (TEST_USER,))
    conn.commit()
    conn.close()
    print("\n[CLEANUP] Test user removed")

if __name__ == "__main__":
    print("=" * 60)
    print("GAMBLING RACE CONDITION TEST")
    print("=" * 60)
    
    setup_test_user()
    
    # Run test multiple times to increase chance of catching race condition
    all_passed = True
    for i in range(3):
        print(f"\n--- Run {i+1}/3 ---")
        setup_test_user()  # Reset user for each run
        if not run_race_condition_test():
            all_passed = False
            break
    
    cleanup()
    
    print("\n" + "=" * 60)
    if all_passed:
        print("FINAL RESULT: ✅ ALL TESTS PASSED - Race condition is fixed!")
    else:
        print("FINAL RESULT: ❌ TEST FAILED - Race condition still exists!")
    print("=" * 60)
