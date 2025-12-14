#!/usr/bin/env python3
"""Test urlfetch rate limiting."""
import sys
sys.path.insert(0, '/opt/twitch-bot/src')

import asyncio

async def test_urlfetch_limiting():
    print("=" * 60)
    print("URLFETCH RATE LIMITING TEST")
    print("=" * 60)
    
    from bot.utils.variables import VariableParser
    
    parser = VariableParser()
    
    # Test 1: Single urlfetch should work
    print("\n[TEST 1] Single urlfetch call...")
    template1 = "Result: $(urlfetch https://httpbin.org/get)"
    result1 = await parser.parse(template1)
    if "Error" not in result1 and "Rate limited" not in result1:
        print(f"  ✅ Single urlfetch works")
    else:
        print(f"  ⚠️ Single urlfetch result: {result1[:100]}")
    
    # Test 2: Multiple urlfetch calls should be limited
    print("\n[TEST 2] Multiple urlfetch calls (should limit to 3)...")
    template2 = """
    $(urlfetch https://httpbin.org/get?n=1)
    $(urlfetch https://httpbin.org/get?n=2)
    $(urlfetch https://httpbin.org/get?n=3)
    $(urlfetch https://httpbin.org/get?n=4)
    $(urlfetch https://httpbin.org/get?n=5)
    """
    
    # Reset counter for new parse
    parser._urlfetch_count = 0
    result2 = await parser.parse(template2)
    
    # Count how many actually fetched vs limited
    limit_count = result2.count("Max urlfetch limit") + result2.count("limit reached")
    
    if limit_count >= 2:  # At least 2 should be blocked (5 calls, max 3)
        print(f"  ✅ Rate limiting working: {limit_count} calls blocked")
    else:
        print(f"  ⚠️ Expected 2+ blocked calls, got {limit_count}")
        print(f"  Result preview: {result2[:200]}")
    
    # Test 3: Same URL cooldown
    print("\n[TEST 3] Same URL cooldown (10 second limit)...")
    parser._urlfetch_count = 0
    url = "https://httpbin.org/uuid"
    template3 = f"$(urlfetch {url})"
    
    result3a = await parser.parse(template3)
    parser._urlfetch_count = 0  # Reset for second call
    result3b = await parser.parse(template3)
    
    if "Rate limited" in result3b or "wait" in result3b.lower():
        print(f"  ✅ Same URL cooldown working")
    else:
        print(f"  ⚠️ Same URL was not rate limited")
        print(f"  First: {result3a[:50]}")
        print(f"  Second: {result3b[:50]}")
    
    print("\n" + "=" * 60)
    print("URLFETCH RATE LIMITING TESTS COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_urlfetch_limiting())
