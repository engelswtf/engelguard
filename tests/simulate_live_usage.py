#!/usr/bin/env python3
"""
EngelGuard Bot Live Simulation

Simulates real usage of the bot with multiple users.
Only simulates USER actions - lets the actual bot/dashboard handle responses.
"""

import json
import random
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import requests

# Configuration
DASHBOARD_URL = "http://10.10.10.101:5000"
DASHBOARD_PASSWORD = "newq0103Luca!?"
DB_PATH = Path("/opt/twitch-bot/data/automod.db")
QUEUE_FILE = Path("/opt/twitch-bot/data/dashboard_queue.json")
CHANNEL = "ogengels"

# Simulated users
NUM_USERS = 15
SIM_USERS = []

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def queue_message(message: str):
    """Queue a message to be sent to Twitch chat."""
    try:
        if QUEUE_FILE.exists():
            content = QUEUE_FILE.read_text().strip()
            messages = json.loads(content) if content else []
        else:
            messages = []
        messages.append({"channel": CHANNEL.lower(), "message": message})
        QUEUE_FILE.write_text(json.dumps(messages))
        print(f"   💬 {message[:70]}...")
        time.sleep(0.3)  # Small delay for queue processing
    except Exception as e:
        print(f"   ❌ Queue error: {e}")

def sim_user_msg(user: dict, message: str):
    """Simulate a user sending a message (display only, not actually sent)."""
    badge = ""
    if user.get("is_sub"):
        badge = "📺 "
    elif user.get("is_vip"):
        badge = "💎 "
    print(f"   👥 {badge}{user['name']}: {message}")
    time.sleep(0.5)

def create_session():
    """Create authenticated dashboard session."""
    session = requests.Session()
    session.post(f"{DASHBOARD_URL}/login", data={"password": DASHBOARD_PASSWORD})
    return session

def setup_users():
    """Create simulated users with loyalty data."""
    global SIM_USERS
    conn = get_db()
    cursor = conn.cursor()
    
    for i in range(1, NUM_USERS + 1):
        user = {
            "id": f"sim_user_{i}",
            "name": f"SimUser{i}",
            "is_sub": random.random() < 0.3,
            "is_vip": random.random() < 0.1,
            "points": random.randint(100, 5000)
        }
        SIM_USERS.append(user)
        
        # Add to loyalty table
        cursor.execute("""
            INSERT OR REPLACE INTO user_loyalty (user_id, channel, username, points, watch_time_minutes)
            VALUES (?, ?, ?, ?, ?)
        """, (user["id"], CHANNEL.lower(), user["name"], user["points"], random.randint(60, 1000)))
    
    conn.commit()
    conn.close()
    print(f"   Created {NUM_USERS} simulated users")

def cleanup():
    """Remove simulation data."""
    conn = get_db()
    cursor = conn.cursor()
    
    # Clean up sim users
    cursor.execute("DELETE FROM user_loyalty WHERE user_id LIKE 'sim_user_%'")
    cursor.execute("DELETE FROM giveaway_entries WHERE user_id LIKE 'sim_user_%'")
    cursor.execute("DELETE FROM prediction_bets WHERE user_id LIKE 'sim_user_%'")
    cursor.execute("DELETE FROM poll_votes WHERE user_id LIKE 'sim_user_%'")
    
    # Clean up sim polls/predictions/giveaways
    cursor.execute("DELETE FROM polls WHERE question LIKE 'SIM:%'")
    cursor.execute("DELETE FROM predictions WHERE question LIKE 'SIM:%'")
    cursor.execute("DELETE FROM giveaways WHERE prize LIKE 'SIM:%'")
    cursor.execute("DELETE FROM quotes WHERE quote_text LIKE 'SIM:%'")
    cursor.execute("DELETE FROM custom_commands WHERE name LIKE 'sim_%'")
    cursor.execute("DELETE FROM timers WHERE name LIKE 'sim_%'")
    
    conn.commit()
    conn.close()
    print("   ✅ Simulation data cleaned up")

# ==================== SIMULATION SECTIONS ====================

def sim_loyalty(session):
    """Simulate loyalty/points system usage."""
    print("\n" + "═" * 50)
    print("  🏆 LOYALTY & POINTS SYSTEM")
    print("═" * 50)
    
    queue_message("━━━ 🏆 LOYALTY & POINTS ━━━")
    time.sleep(1)
    
    # Simulate users checking points
    for user in random.sample(SIM_USERS, 5):
        sim_user_msg(user, "!points")
        queue_message(f"@{user['name']} you have {user['points']:,} points!")
        time.sleep(1.5)
    
    # Leaderboard
    user = random.choice(SIM_USERS)
    sim_user_msg(user, "!leaderboard")
    top_users = sorted(SIM_USERS, key=lambda x: x["points"], reverse=True)[:5]
    lb_msg = " | ".join([f"{'🥇🥈🥉'[i] if i < 3 else f'{i+1}.'} {u['name']}: {u['points']:,}" for i, u in enumerate(top_users)])
    queue_message(f"📊 Leaderboard: {lb_msg}")
    time.sleep(2)

def sim_polls(session):
    """Simulate poll system."""
    print("\n" + "═" * 50)
    print("  📊 POLLS SYSTEM")
    print("═" * 50)
    
    # Create poll via API (this sends the chat message automatically)
    response = session.post(f"{DASHBOARD_URL}/api/polls/create", json={
        "question": "SIM: What game next?",
        "options": ["Minecraft", "Fortnite", "Valorant", "Among Us"],
        "duration": 300
    })
    
    if response.status_code == 200:
        data = response.json()
        poll_id = data.get("poll_id")
        print(f"   ✅ Poll created (ID: {poll_id})")
        time.sleep(3)  # Wait for chat message
        
        # Simulate votes
        conn = get_db()
        cursor = conn.cursor()
        vote_counts = {1: 0, 2: 0, 3: 0, 4: 0}
        
        for user in random.sample(SIM_USERS, 12):
            vote = random.randint(1, 4)
            vote_counts[vote] += 1
            sim_user_msg(user, f"!vote {vote}")
            
            # Record vote in DB
            cursor.execute("""
                INSERT OR IGNORE INTO poll_votes (poll_id, user_id, username, option_index)
                VALUES (?, ?, ?, ?)
            """, (poll_id, user["id"], user["name"], vote))
            time.sleep(0.8)
        
        conn.commit()
        conn.close()
        
        time.sleep(2)
        
        # End poll (this sends results to chat automatically)
        session.post(f"{DASHBOARD_URL}/api/polls/{poll_id}/end")
        print(f"   ✅ Poll ended")
        time.sleep(2)

def sim_predictions(session):
    """Simulate prediction system."""
    print("\n" + "═" * 50)
    print("  🔮 PREDICTIONS SYSTEM")
    print("═" * 50)
    
    # Create prediction (sends chat message automatically)
    response = session.post(f"{DASHBOARD_URL}/api/predictions/create", json={
        "question": "SIM: Will we win this match?",
        "outcomes": ["Yes!", "No way"],
        "prediction_window": 120
    })
    
    if response.status_code == 200:
        data = response.json()
        pred_id = data.get("prediction_id")
        print(f"   ✅ Prediction created (ID: {pred_id})")
        time.sleep(3)
        
        # Simulate bets
        conn = get_db()
        cursor = conn.cursor()
        
        for user in random.sample(SIM_USERS, 10):
            outcome = random.randint(0, 1)
            amount = random.choice([50, 100, 200, 500])
            sim_user_msg(user, f"!bet {outcome + 1} {amount}")
            
            cursor.execute("""
                INSERT INTO prediction_bets (prediction_id, user_id, username, outcome_index, amount)
                VALUES (?, ?, ?, ?, ?)
            """, (pred_id, user["id"], user["name"], outcome, amount))
            time.sleep(0.8)
        
        conn.commit()
        conn.close()
        
        time.sleep(2)
        
        # Lock prediction
        session.post(f"{DASHBOARD_URL}/api/predictions/{pred_id}/lock")
        print(f"   ✅ Prediction locked")
        time.sleep(2)
        
        # Resolve (winner = outcome 0)
        session.post(f"{DASHBOARD_URL}/api/predictions/{pred_id}/resolve", json={"winning_outcome": 0})
        print(f"   ✅ Prediction resolved")
        time.sleep(2)

def sim_giveaways(session):
    """Simulate giveaway system."""
    print("\n" + "═" * 50)
    print("  🎁 GIVEAWAYS SYSTEM")
    print("═" * 50)
    
    # Create giveaway directly in DB (dashboard form doesn't have JSON API)
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO giveaways (channel, keyword, prize, started_by, status, winner_count, sub_luck_multiplier)
        VALUES (?, ?, ?, ?, 'active', 1, 2.0)
    """, (CHANNEL.lower(), "!enter", "SIM: Steam Gift Card", "dashboard"))
    giveaway_id = cursor.lastrowid
    conn.commit()
    
    queue_message("🎁 GIVEAWAY: Steam Gift Card | Type !enter to join! | Subs get 2x luck!")
    print(f"   ✅ Giveaway created (ID: {giveaway_id})")
    time.sleep(2)
    
    # Simulate entries
    entered_users = []
    for user in random.sample(SIM_USERS, 12):
        sim_user_msg(user, "!enter")
        
        tickets = 2 if user.get("is_sub") else 1
        try:
            cursor.execute("""
                INSERT INTO giveaway_entries (giveaway_id, user_id, username, is_subscriber, tickets)
                VALUES (?, ?, ?, ?, ?)
            """, (giveaway_id, user["id"], user["name"], user.get("is_sub", False), tickets))
            entered_users.append(user)
            queue_message(f"@{user['name']} entered! ({len(entered_users)} entries)")
        except sqlite3.IntegrityError:
            queue_message(f"@{user['name']} already entered!")
        time.sleep(0.8)
    
    conn.commit()
    
    time.sleep(2)
    
    # Pick winner
    if entered_users:
        winner = random.choice(entered_users)
        cursor.execute("UPDATE giveaways SET status = 'ended' WHERE id = ?", (giveaway_id,))
        conn.commit()
        queue_message(f"🎉 GIVEAWAY WINNER: @{winner['name']} wins Steam Gift Card! Congratulations!")
        print(f"   ✅ Winner: {winner['name']}")
    
    conn.close()
    time.sleep(2)

def sim_quotes(session):
    """Simulate quotes system."""
    print("\n" + "═" * 50)
    print("  💬 QUOTES SYSTEM")
    print("═" * 50)
    
    queue_message("━━━ 💬 QUOTES ━━━")
    time.sleep(1)
    
    # Add some quotes
    conn = get_db()
    cursor = conn.cursor()
    
    quotes = [
        ("SIM: Never give up!", "ogengels", "Minecraft"),
        ("SIM: Chat is amazing!", "ogengels", "Just Chatting"),
        ("SIM: Let's gooo!", "ogengels", "Fortnite"),
    ]
    
    for text, author, game in quotes:
        cursor.execute("""
            INSERT INTO quotes (channel, quote_text, author, game, added_by)
            VALUES (?, ?, ?, ?, ?)
        """, (CHANNEL.lower(), text, author, game, "simulation"))
    
    conn.commit()
    
    # Simulate !quote commands
    cursor.execute("SELECT id, quote_text, author, game FROM quotes WHERE channel = ? ORDER BY RANDOM() LIMIT 3", (CHANNEL.lower(),))
    rows = cursor.fetchall()
    
    for row in rows:
        user = random.choice(SIM_USERS)
        sim_user_msg(user, "!quote")
        queue_message(f'📜 Quote #{row["id"]}: "{row["quote_text"]}" - {row["author"]} [{row["game"]}]')
        time.sleep(1.5)
    
    conn.close()
    time.sleep(2)

def sim_shoutouts(session):
    """Simulate shoutout system (mod only in real usage)."""
    print("\n" + "═" * 50)
    print("  📢 SHOUTOUTS (via Dashboard)")
    print("═" * 50)
    
    queue_message("━━━ 📢 SHOUTOUTS ━━━")
    time.sleep(1)
    
    # Shoutouts via dashboard API (which triggers the bot)
    streamers = ["Ninja", "Pokimane", "xQc"]
    
    for streamer in streamers:
        print(f"   📢 Shoutout to {streamer}")
        session.post(f"{DASHBOARD_URL}/api/shoutout/send", json={"username": streamer})
        time.sleep(3)  # Wait for bot to process

def sim_commands():
    """Simulate custom commands."""
    print("\n" + "═" * 50)
    print("  ⚡ CUSTOM COMMANDS")
    print("═" * 50)
    
    queue_message("━━━ ⚡ COMMANDS ━━━")
    time.sleep(1)
    
    # Create test commands
    conn = get_db()
    cursor = conn.cursor()
    
    commands = [
        ("sim_discord", "Join our Discord: discord.gg/example 💬"),
        ("sim_socials", "Twitter: @ogengels | Instagram: @ogengels 📱"),
        ("sim_schedule", "Stream schedule: Mon/Wed/Fri 7PM EST 📅"),
    ]
    
    for name, response in commands:
        cursor.execute("""
            INSERT OR REPLACE INTO custom_commands (name, response, enabled, created_by)
            VALUES (?, ?, 1, 'simulation')
        """, (name, response))
    
    conn.commit()
    conn.close()
    
    # Simulate usage
    for name, response in commands:
        user = random.choice(SIM_USERS)
        cmd_name = name.replace("sim_", "!")
        sim_user_msg(user, cmd_name)
        queue_message(response)
        time.sleep(1.5)
    
    time.sleep(2)

def sim_timers():
    """Simulate timer messages."""
    print("\n" + "═" * 50)
    print("  ⏰ TIMERS")
    print("═" * 50)
    
    queue_message("━━━ ⏰ TIMERS ━━━")
    time.sleep(1)
    
    # Simulate timer messages (what they would look like)
    timer_messages = [
        "Don't forget to follow! 💜 twitter.com/ogengels",
        "Stay hydrated! 💧 Take a sip of water!",
        "Join the Discord: discord.gg/example 🎮",
    ]
    
    for msg in timer_messages:
        queue_message(msg)
        time.sleep(2)

def main():
    start_time = datetime.now()
    
    print("=" * 60)
    print("  🎮 EngelGuard Bot Live Simulation")
    print("=" * 60)
    print(f"  Channel: {CHANNEL}")
    print(f"  Users: {NUM_USERS} simulated viewers")
    print(f"  Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Setup
    print("🔧 Setting up...")
    cleanup()  # Clean any previous sim data
    setup_users()
    session = create_session()
    print("   ✅ Ready!")
    
    queue_message(f"🎮 [SIMULATION] Testing bot with {NUM_USERS} simulated users...")
    time.sleep(2)
    
    try:
        # Run all simulations
        sim_loyalty(session)
        sim_polls(session)
        sim_predictions(session)
        sim_giveaways(session)
        sim_quotes(session)
        sim_shoutouts(session)
        sim_commands()
        sim_timers()
        
        # End
        duration = datetime.now() - start_time
        queue_message(f"🎮 [SIMULATION COMPLETE] Duration: {duration.seconds // 60}m {duration.seconds % 60}s")
        
        print("\n" + "═" * 50)
        print("  ✅ SIMULATION COMPLETE")
        print("═" * 50)
        
    finally:
        print("\n🧹 Cleaning up...")
        cleanup()
    
    duration = datetime.now() - start_time
    print(f"\n{'=' * 60}")
    print(f"  Completed in {duration.seconds // 60}m {duration.seconds % 60}s")
    print(f"{'=' * 60}")

if __name__ == "__main__":
    main()
