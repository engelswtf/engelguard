"""
EngelGuard Dashboard - Flask Web Application

A modern web dashboard for managing the EngelGuard Twitch bot.
"""

from __future__ import annotations

import os
import sys
import json
import sqlite3
import hashlib
import secrets
import subprocess
from datetime import datetime, timedelta
from collections import defaultdict

from functools import wraps
from pathlib import Path
from typing import Any, Optional

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
)
from dotenv import load_dotenv, set_key

try:
    from flask_wtf.csrf import CSRFProtect
    CSRF_AVAILABLE = True
except ImportError:
    CSRF_AVAILABLE = False

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables
ENV_FILE = Path(__file__).parent.parent / ".env"
load_dotenv(ENV_FILE)

app = Flask(__name__)

# Custom Jinja2 filters
@app.template_filter('split')
def split_filter(s, sep=','):
    """Split a string by separator."""
    return s.split(sep) if s else []

app.secret_key = os.getenv("DASHBOARD_SECRET_KEY", secrets.token_hex(32))
app.permanent_session_lifetime = timedelta(hours=1)

# Login rate limiting
_login_attempts: dict[str, list[datetime]] = defaultdict(list)
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 15


# Security Fix: Add CSRF protection
if CSRF_AVAILABLE:
    csrf = CSRFProtect(app)
    app.config["WTF_CSRF_TIME_LIMIT"] = 3600  # 1 hour

# Database path
DB_PATH = Path(__file__).parent.parent / "data" / "automod.db"

# Variable documentation
VARIABLE_DOCS = {
    "$(user)": "Username of command caller",
    "$(user.id)": "User ID of command caller",
    "$(target)": "Mentioned user or command caller",
    "$(channel)": "Channel name",
    "$(count)": "Command use count",
    "$(args)": "All arguments after command",
    "$(args.1)": "First argument",
    "$(random)": "Random number 1-100",
    "$(random.1-100)": "Random number in range",
    "$(random.pick a,b,c)": "Random choice from list",
    "$(time)": "Current time",
    "$(date)": "Current date",
    "$(uptime)": "Stream uptime",
    "$(urlfetch URL)": "Fetch text from URL",
}


def get_db_connection() -> sqlite3.Connection:
    """Get a database connection."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str) -> str:
    """Hash a password using SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()


def login_required(f):
    """Decorator to require login for routes.
    
    Security Fix: Added session token and IP hash validation to prevent
    session hijacking and detect IP address changes.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            flash("Please log in first", "error")
            return redirect(url_for("login"))
        
        # Validate session token exists
        if not session.get("session_token"):
            session.clear()
            flash("Invalid session. Please log in again.", "error")
            return redirect(url_for("login"))
        
        # Validate IP hasn't changed (prevents session hijacking)
        current_ip_hash = hashlib.sha256(request.remote_addr.encode()).hexdigest()
        if session.get("ip_hash") and session.get("ip_hash") != current_ip_hash:
            session.clear()
            flash("Session invalid - IP address changed. Please log in again.", "error")
            return redirect(url_for("login"))
        
        return f(*args, **kwargs)
    return decorated_function


def get_env_value(key: str, default: str = "") -> str:
    """Get a value from the .env file."""
    load_dotenv(ENV_FILE, override=True)
    return os.getenv(key, default)


def set_env_value(key: str, value: str) -> None:
    """Set a value in the .env file."""
    set_key(str(ENV_FILE), key, value)


def mask_secret(value: str, show_chars: int = 4) -> str:
    """Mask a secret value, showing only last few characters."""
    if not value or len(value) <= show_chars:
        return "*" * 8
    return "*" * (len(value) - show_chars) + value[-show_chars:]


def safe_int(value: any, default: int = 0, min_val: int = None, max_val: int = None) -> int:
    """Safely convert value to int with bounds checking.
    
    Args:
        value: Value to convert to integer
        default: Default value if conversion fails
        min_val: Optional minimum bound
        max_val: Optional maximum bound
        
    Returns:
        int: Converted and bounded integer value
    """
    try:
        result = int(value) if value is not None else default
        if min_val is not None:
            result = max(min_val, result)
        if max_val is not None:
            result = min(max_val, result)
        return result
    except (ValueError, TypeError):
        return default


# Dashboard-to-bot message queue
DASHBOARD_QUEUE_FILE = "/opt/twitch-bot/data/dashboard_queue.json"


def sanitize_chat_message(message: str, max_length: int = 500) -> str:
    """Sanitize a message before sending to chat."""
    if not message:
        return ""
    import re as re_module
    # Remove control characters
    message = ''.join(c for c in message if ord(c) >= 32 or c == '\n')
    # Replace newlines with space
    message = re_module.sub(r'\n+', ' ', message)
    # Remove excessive whitespace
    message = ' '.join(message.split())
    # Truncate
    if len(message) > max_length:
        message = message[:max_length-3] + "..."
    return message.strip()

def queue_chat_message(channel: str, message: str) -> bool:
    """Queue a message to be sent to Twitch chat by the bot."""
    from pathlib import Path
    
    queue_file = Path(DASHBOARD_QUEUE_FILE)
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        if queue_file.exists():
            with open(queue_file, "r") as f:
                file_content = f.read().strip()
                messages = json.loads(file_content) if file_content else []
        else:
            messages = []
        
        messages.append({"channel": channel.lower(), "message": sanitize_chat_message(message)})
        
        with open(queue_file, "w") as f:
            json.dump(messages, f)
        
        return True
    except Exception as e:
        print(f"Error queuing chat message: {e}")
        return False



def get_bot_status() -> dict[str, Any]:
    """Get current bot status."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "twitch-bot"],
            capture_output=True,
            text=True,
            timeout=5
        )
        is_running = result.stdout.strip() == "active"
    except Exception as e:
        is_running = False
    
    uptime = "Unknown"
    if is_running:
        try:
            result = subprocess.run(
                ["systemctl", "show", "twitch-bot", "--property=ActiveEnterTimestamp"],
                capture_output=True,
                text=True,
                timeout=5
            )
            timestamp_str = result.stdout.strip().split("=")[1]
            if timestamp_str:
                start_time = datetime.strptime(timestamp_str.replace(" UTC", "").split(".")[0], "%a %Y-%m-%d %H:%M:%S")
                delta = datetime.now() - start_time
                hours, remainder = divmod(int(delta.total_seconds()), 3600)
                minutes, seconds = divmod(remainder, 60)
                if hours > 24:
                    days = hours // 24
                    hours = hours % 24
                    uptime = f"{days}d {hours}h {minutes}m"
                else:
                    uptime = f"{hours}h {minutes}m {seconds}s"
        except Exception:
            uptime = "Unknown"
    
    return {
        "is_running": is_running,
        "status": "Online" if is_running else "Offline",
        "uptime": uptime
    }


def get_dashboard_stats() -> dict[str, Any]:
    """Get dashboard statistics."""
    stats = {
        "messages_today": 0,
        "actions_today": 0,
        "users_tracked": 0,
        "actions_by_type": {}
    }
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT COUNT(*) as count FROM mod_actions 
            WHERE date(timestamp) = date('now')
        """)
        row = cursor.fetchone()
        stats["actions_today"] = row["count"] if row else 0
        
        cursor.execute("SELECT COUNT(*) as count FROM users")
        row = cursor.fetchone()
        stats["users_tracked"] = row["count"] if row else 0
        
        cursor.execute("""
            SELECT action, COUNT(*) as count 
            FROM mod_actions 
            WHERE timestamp > datetime('now', '-24 hours')
            GROUP BY action
        """)
        stats["actions_by_type"] = {row["action"]: row["count"] for row in cursor.fetchall()}
        
        conn.close()
    except Exception as e:
        app.logger.error(f"Error getting stats: {e}")
    
    return stats


def get_recent_actions(limit: int = 10) -> list[dict]:
    """Get recent moderation actions."""
    actions = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM mod_actions 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (limit,))
        actions = [dict(row) for row in cursor.fetchall()]
        conn.close()
    except Exception as e:
        app.logger.error(f"Error getting recent actions: {e}")
    return actions


def get_all_cog_settings(channel: str) -> dict[str, dict]:
    """
    Get all cog settings for a channel with display info.
    
    Returns a dictionary with cog info including enabled status and display name.
    """
    # Define all available cogs with their display names and descriptions
    cog_info = {
        "admin": {"name": "Admin Commands", "description": "Bot administration commands (!reload, !shutdown)"},
        "fun": {"name": "Fun Commands", "description": "Entertainment commands (!dice, !8ball, !hug)"},
        "moderation": {"name": "Moderation Commands", "description": "Mod tools (!timeout, !ban, !permit)"},
        "info": {"name": "Info Commands", "description": "Information commands (!uptime, !followage)"},
        "clips": {"name": "Stream Commands", "description": "Stream-related commands (!clip, !title)"},
        "automod": {"name": "Auto-Moderation", "description": "Automatic spam detection and filtering"},
        "customcmds": {"name": "Custom Commands", "description": "User-defined custom commands"},
        "timers": {"name": "Timers", "description": "Automated timed messages"},
        "loyalty": {"name": "Loyalty Points", "description": "Channel points and rewards system"},
        "nuke": {"name": "Nuke Command", "description": "Mass moderation tool for raids"},
        "quotes": {"name": "Quotes", "description": "Quote storage and retrieval system"},
        "giveaways": {"name": "Giveaways", "description": "Giveaway and raffle system"},
        "songrequests": {"name": "Song Requests", "description": "Music request system"},
    }
    
    # Get enabled status from database
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT cog_name, enabled FROM cog_settings WHERE channel = ?",
            (channel.lower(),)
        )
        db_settings = {row["cog_name"].lower(): bool(row["enabled"]) for row in cursor.fetchall()}
        conn.close()
    except Exception as e:
        app.logger.error(f"Error getting cog settings: {e}")
        db_settings = {}
    
    # Merge with cog info (default to enabled if not in database)
    result = {}
    for cog_name, info in cog_info.items():
        result[cog_name] = {
            "name": info["name"],
            "description": info["description"],
            "enabled": db_settings.get(cog_name, True)  # Default to enabled
        }
    
    return result


def set_cog_enabled(channel: str, cog_name: str, enabled: bool) -> bool:
    """Set whether a cog is enabled for a channel."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO cog_settings (channel, cog_name, enabled)
            VALUES (?, ?, ?)
            ON CONFLICT(channel, cog_name) DO UPDATE SET
                enabled = excluded.enabled
            """,
            (channel.lower(), cog_name.lower(), enabled)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        app.logger.error(f"Error setting cog enabled: {e}")
        return False


# ==================== Routes ====================

@app.route("/")
def index():
    """Redirect to dashboard or login."""
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    """Login page with rate limiting."""
    if request.method == "POST":
        client_ip = request.remote_addr
        now = datetime.now()
        
        # Clean old attempts (older than lockout period)
        _login_attempts[client_ip] = [
            t for t in _login_attempts[client_ip] 
            if now - t < timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
        ]
        
        # Check if locked out
        if len(_login_attempts[client_ip]) >= MAX_LOGIN_ATTEMPTS:
            remaining = LOGIN_LOCKOUT_MINUTES - int((now - _login_attempts[client_ip][0]).total_seconds() / 60)
            flash(f"Too many login attempts. Try again in {remaining} minutes.", "error")
            return render_template("login.html")
        
        password = request.form.get("password", "")
        stored_password = get_env_value("DASHBOARD_PASSWORD", "changeme123")
        
        if password == stored_password:
            # Clear attempts on successful login
            _login_attempts[client_ip] = []
            # Security Fix: Regenerate session to prevent session fixation
            session.clear()
            session.permanent = True
            session["logged_in"] = True
            # Security Fix: Add session token and IP hash for session hardening
            session["session_token"] = secrets.token_hex(32)
            session["login_time"] = datetime.now().isoformat()
            session["ip_hash"] = hashlib.sha256(request.remote_addr.encode()).hexdigest()
            flash("Successfully logged in!", "success")
            return redirect(url_for("dashboard"))
        else:
            # Record failed attempt
            _login_attempts[client_ip].append(now)
            attempts_left = MAX_LOGIN_ATTEMPTS - len(_login_attempts[client_ip])
            if attempts_left > 0:
                flash(f"Invalid password. {attempts_left} attempts remaining.", "error")
            else:
                flash(f"Too many login attempts. Try again in {LOGIN_LOCKOUT_MINUTES} minutes.", "error")
    
    return render_template("login.html")


@app.route("/logout")
def logout():
    """Logout and clear session."""
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    """Main dashboard page."""
    bot_status = get_bot_status()
    stats = get_dashboard_stats()
    recent_actions = get_recent_actions(10)
    
    return render_template(
        "dashboard.html",
        bot_status=bot_status,
        stats=stats,
        recent_actions=recent_actions
    )


@app.route("/commands", methods=["GET", "POST"])
@login_required
def commands_page():
    """Custom commands page."""
    if request.method == "POST":
        action = request.form.get("action")
        name = request.form.get("name", "").lower().strip()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if action == "add":
            try:
                aliases = request.form.get("aliases", "").split()
                cursor.execute("""
                    INSERT INTO custom_commands 
                    (name, response, created_by, cooldown_user, cooldown_global, permission_level, enabled, aliases)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    name,
                    request.form.get("response"),
                    "dashboard",
                    safe_int(request.form.get("cooldown_user"), default=5, min_val=0, max_val=3600),
                    safe_int(request.form.get("cooldown_global"), default=0, min_val=0, max_val=3600),
                    request.form.get("permission_level", "everyone"),
                    request.form.get("enabled") == "on",
                    json.dumps(aliases) if aliases else None
                ))
                conn.commit()
                flash(f"Command !{name} created!", "success")
            except Exception as e:
                flash(f"Error creating command: {e}", "error")
        
        elif action == "edit":
            original_name = request.form.get("original_name", "").lower()
            aliases = request.form.get("aliases", "").split()
            cursor.execute("""
                UPDATE custom_commands SET
                    name = ?, response = ?, cooldown_user = ?, cooldown_global = ?,
                    permission_level = ?, enabled = ?, aliases = ?, updated_at = CURRENT_TIMESTAMP
                WHERE name = ?
            """, (
                name,
                request.form.get("response"),
                safe_int(request.form.get("cooldown_user"), default=5, min_val=0, max_val=3600),
                safe_int(request.form.get("cooldown_global"), default=0, min_val=0, max_val=3600),
                request.form.get("permission_level", "everyone"),
                request.form.get("enabled") == "on",
                json.dumps(aliases) if aliases else None,
                original_name
            ))
            conn.commit()
            flash(f"Command !{name} updated!", "success")
        
        conn.close()
        return redirect(url_for("commands_page"))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM custom_commands ORDER BY name")
    commands = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return render_template("commands.html", commands=commands, variables=VARIABLE_DOCS)


@app.route("/timers", methods=["GET", "POST"])
@login_required
def timers_page():
    """Timers page."""
    if request.method == "POST":
        action = request.form.get("action")
        name = request.form.get("name", "").lower().strip()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if action == "add":
            try:
                cursor.execute("""
                    INSERT INTO timers 
                    (name, message, interval_minutes, chat_lines_required, online_only, enabled, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    name,
                    request.form.get("message"),
                    safe_int(request.form.get("interval_minutes"), default=15, min_val=5, max_val=120),
                    safe_int(request.form.get("chat_lines_required"), default=5, min_val=0, max_val=100),
                    request.form.get("online_only") == "on",
                    request.form.get("enabled") == "on",
                    "dashboard"
                ))
                conn.commit()
                flash(f"Timer '{name}' created!", "success")
            except Exception as e:
                flash(f"Error creating timer: {e}", "error")
        
        elif action == "edit":
            original_name = request.form.get("original_name", "").lower()
            cursor.execute("""
                UPDATE timers SET
                    name = ?, message = ?, interval_minutes = ?, chat_lines_required = ?,
                    online_only = ?, enabled = ?
                WHERE name = ?
            """, (
                name,
                request.form.get("message"),
                safe_int(request.form.get("interval_minutes"), default=15, min_val=5, max_val=120),
                safe_int(request.form.get("chat_lines_required"), default=5, min_val=0, max_val=100),
                request.form.get("online_only") == "on",
                request.form.get("enabled") == "on",
                original_name
            ))
            conn.commit()
            flash(f"Timer '{name}' updated!", "success")
        
        conn.close()
        return redirect(url_for("timers_page"))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM timers ORDER BY name")
    timers = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return render_template("timers.html", timers=timers)


@app.route("/strikes")
@login_required
def strikes_page():
    """Strikes page."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get users with strikes
    cursor.execute("SELECT * FROM user_strikes WHERE strike_count > 0 ORDER BY strike_count DESC")
    users_with_strikes = [dict(row) for row in cursor.fetchall()]
    
    # Get total strikes
    total_strikes = sum(u["strike_count"] for u in users_with_strikes)
    
    # Get recent strike history
    cursor.execute("SELECT * FROM strike_history ORDER BY timestamp DESC LIMIT 50")
    strike_history = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    expire_days = int(get_env_value("STRIKE_EXPIRE_DAYS", "30"))
    max_strikes = int(get_env_value("STRIKE_MAX_BEFORE_BAN", "5"))
    
    return render_template(
        "strikes.html",
        users_with_strikes=users_with_strikes,
        total_strikes=total_strikes,
        strike_history=strike_history,
        expire_days=expire_days,
        max_strikes=max_strikes
    )


@app.route("/loyalty", methods=["GET", "POST"])
@login_required
def loyalty_page():
    """Loyalty points page."""
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
    
    if request.method == "POST":
        action = request.form.get("action")
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if action == "settings":
            cursor.execute("""
                INSERT INTO loyalty_settings 
                (channel, enabled, points_name, points_per_minute, points_per_message, bonus_sub_multiplier, bonus_vip_multiplier)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel) DO UPDATE SET
                    enabled = excluded.enabled,
                    points_name = excluded.points_name,
                    points_per_minute = excluded.points_per_minute,
                    points_per_message = excluded.points_per_message,
                    bonus_sub_multiplier = excluded.bonus_sub_multiplier,
                    bonus_vip_multiplier = excluded.bonus_vip_multiplier
            """, (
                channel,
                request.form.get("enabled") == "on",
                request.form.get("points_name", "points"),
                float(request.form.get("points_per_minute", 1)),
                float(request.form.get("points_per_message", 0.5)),
                float(request.form.get("bonus_sub_multiplier", 2)),
                float(request.form.get("bonus_vip_multiplier", 1.5))
            ))
            conn.commit()
            flash("Loyalty settings saved!", "success")
        
        elif action == "adjust":
            user_id = request.form.get("user_id")
            amount = int(request.form.get("amount", 0))
            cursor.execute("""
                UPDATE user_loyalty SET points = points + ? WHERE user_id = ? AND channel = ?
            """, (amount, user_id, channel))
            conn.commit()
            flash(f"Points adjusted by {amount}", "success")
        
        conn.close()
        return redirect(url_for("loyalty_page"))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get settings
    cursor.execute("SELECT * FROM loyalty_settings WHERE channel = ?", (channel,))
    row = cursor.fetchone()
    settings = dict(row) if row else {
        "enabled": False,
        "points_name": "points",
        "points_per_minute": 1.0,
        "points_per_message": 0.5,
        "bonus_sub_multiplier": 2.0,
        "bonus_vip_multiplier": 1.5
    }
    
    # Get leaderboard
    cursor.execute("""
        SELECT * FROM user_loyalty WHERE channel = ? ORDER BY points DESC LIMIT 25
    """, (channel,))
    leaderboard = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return render_template("loyalty.html", settings=settings, leaderboard=leaderboard)


@app.route("/filters", methods=["GET", "POST"])
@login_required
def filters_page():
    """Filters page with per-filter actions, durations, and link lists."""
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
    
    if request.method == "POST":
        action = request.form.get("action", "save_filters")
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if action == "save_filters":
            # Save all filter settings including actions and durations
            cursor.execute("""
                INSERT INTO filter_settings 
                (channel, global_sensitivity,
                 caps_enabled, caps_min_length, caps_max_percent, caps_action, caps_duration,
                 emote_enabled, emote_max_count, emote_action, emote_duration,
                 symbol_enabled, symbol_max_percent, symbol_action, symbol_duration,
                 link_enabled, link_action, link_duration,
                 length_enabled, length_max_chars, length_action, length_duration,
                 repetition_enabled, repetition_max_words, repetition_action, repetition_duration,
                 zalgo_enabled, zalgo_action, zalgo_duration,
                 lookalike_enabled, lookalike_action, lookalike_duration)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel) DO UPDATE SET
                    global_sensitivity = excluded.global_sensitivity,
                    caps_enabled = excluded.caps_enabled,
                    caps_min_length = excluded.caps_min_length,
                    caps_max_percent = excluded.caps_max_percent,
                    caps_action = excluded.caps_action,
                    caps_duration = excluded.caps_duration,
                    emote_enabled = excluded.emote_enabled,
                    emote_max_count = excluded.emote_max_count,
                    emote_action = excluded.emote_action,
                    emote_duration = excluded.emote_duration,
                    symbol_enabled = excluded.symbol_enabled,
                    symbol_max_percent = excluded.symbol_max_percent,
                    symbol_action = excluded.symbol_action,
                    symbol_duration = excluded.symbol_duration,
                    link_enabled = excluded.link_enabled,
                    link_action = excluded.link_action,
                    link_duration = excluded.link_duration,
                    length_enabled = excluded.length_enabled,
                    length_max_chars = excluded.length_max_chars,
                    length_action = excluded.length_action,
                    length_duration = excluded.length_duration,
                    repetition_enabled = excluded.repetition_enabled,
                    repetition_max_words = excluded.repetition_max_words,
                    repetition_action = excluded.repetition_action,
                    repetition_duration = excluded.repetition_duration,
                    zalgo_enabled = excluded.zalgo_enabled,
                    zalgo_action = excluded.zalgo_action,
                    zalgo_duration = excluded.zalgo_duration,
                    lookalike_enabled = excluded.lookalike_enabled,
                    lookalike_action = excluded.lookalike_action,
                    lookalike_duration = excluded.lookalike_duration
            """, (
                channel,
                request.form.get("global_sensitivity", "medium"),
                # Caps filter
                request.form.get("caps_enabled") == "on",
                safe_int(request.form.get("caps_min_length"), default=10, min_val=1, max_val=500),
                safe_int(request.form.get("caps_max_percent"), default=70, min_val=1, max_val=100),
                request.form.get("caps_action", "timeout"),
                safe_int(request.form.get("caps_duration"), default=60, min_val=1, max_val=86400),
                # Emote filter
                request.form.get("emote_enabled") == "on",
                safe_int(request.form.get("emote_max_count"), default=15, min_val=1, max_val=100),
                request.form.get("emote_action", "timeout"),
                safe_int(request.form.get("emote_duration"), default=60, min_val=1, max_val=86400),
                # Symbol filter
                request.form.get("symbol_enabled") == "on",
                safe_int(request.form.get("symbol_max_percent"), default=50, min_val=1, max_val=100),
                request.form.get("symbol_action", "timeout"),
                safe_int(request.form.get("symbol_duration"), default=60, min_val=1, max_val=86400),
                # Link filter
                request.form.get("link_enabled") == "on",
                request.form.get("link_action", "delete"),
                safe_int(request.form.get("link_duration"), default=60, min_val=1, max_val=86400),
                # Length filter
                request.form.get("length_enabled") == "on",
                safe_int(request.form.get("length_max_chars"), default=500, min_val=50, max_val=2000),
                request.form.get("length_action", "delete"),
                safe_int(request.form.get("length_duration"), default=60, min_val=1, max_val=86400),
                # Repetition filter
                request.form.get("repetition_enabled") == "on",
                safe_int(request.form.get("repetition_max_words"), default=10, min_val=2, max_val=50),
                request.form.get("repetition_action", "timeout"),
                safe_int(request.form.get("repetition_duration"), default=60, min_val=1, max_val=86400),
                # Zalgo filter
                request.form.get("zalgo_enabled") == "on",
                request.form.get("zalgo_action", "delete"),
                safe_int(request.form.get("zalgo_duration"), default=60, min_val=1, max_val=86400),
                # Lookalike filter
                request.form.get("lookalike_enabled") == "on",
                request.form.get("lookalike_action", "delete"),
                safe_int(request.form.get("lookalike_duration"), default=60, min_val=1, max_val=86400)
            ))
            conn.commit()
            flash("Filter settings saved!", "success")
        
        elif action == "add_link":
            domain = request.form.get("domain", "").strip().lower()
            list_type = request.form.get("list_type", "whitelist")
            if domain:
                # Remove protocol and path if present
                domain = domain.replace("https://", "").replace("http://", "").split("/")[0]
                try:
                    cursor.execute("""
                        INSERT INTO link_lists (channel, domain, list_type, added_by)
                        VALUES (?, ?, ?, ?)
                    """, (channel.lower(), domain, list_type, "dashboard"))
                    conn.commit()
                    flash(f"Added {domain} to {list_type}!", "success")
                except Exception as e:
                    flash(f"Domain already exists in {list_type}!", "error")
        
        elif action == "remove_link":
            link_id = request.form.get("link_id")
            if link_id:
                cursor.execute("DELETE FROM link_lists WHERE id = ? AND channel = ?", (link_id, channel.lower()))
                conn.commit()
                flash("Domain removed!", "success")
        
        conn.close()
        return redirect(url_for("filters_page"))
    
    # GET request - load settings and link lists
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get filter settings
    cursor.execute("SELECT * FROM filter_settings WHERE channel = ?", (channel,))
    row = cursor.fetchone()
    settings = dict(row) if row else {
        "global_sensitivity": "medium",
        "caps_enabled": True, "caps_min_length": 10, "caps_max_percent": 70, "caps_action": "timeout", "caps_duration": 60,
        "emote_enabled": True, "emote_max_count": 15, "emote_action": "timeout", "emote_duration": 60,
        "symbol_enabled": True, "symbol_max_percent": 50, "symbol_action": "timeout", "symbol_duration": 60,
        "link_enabled": True, "link_action": "delete", "link_duration": 60,
        "length_enabled": True, "length_max_chars": 500, "length_action": "delete", "length_duration": 60,
        "repetition_enabled": True, "repetition_max_words": 10, "repetition_action": "timeout", "repetition_duration": 60,
        "zalgo_enabled": True, "zalgo_action": "delete", "zalgo_duration": 60,
        "lookalike_enabled": True, "lookalike_action": "delete", "lookalike_duration": 60
    }
    
    # Get link whitelist
    cursor.execute("SELECT * FROM link_lists WHERE channel = ? AND list_type = 'whitelist' ORDER BY domain", (channel.lower(),))
    whitelist = [dict(row) for row in cursor.fetchall()]
    
    # Get link blacklist
    cursor.execute("SELECT * FROM link_lists WHERE channel = ? AND list_type = 'blacklist' ORDER BY domain", (channel.lower(),))
    blacklist = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return render_template("filters.html", settings=settings, whitelist=whitelist, blacklist=blacklist)

@app.route("/filters/banned-words", methods=["GET", "POST"])
@login_required
def banned_words_page():
    """Banned words management page."""
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "add":
            word = request.form.get("word", "").strip()
            if word:
                conn = get_db_connection()
                cursor = conn.cursor()
                try:
                    cursor.execute("""
                        INSERT INTO banned_words (channel, word, is_regex, action, duration, added_by)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        channel.lower(),
                        word,
                        request.form.get("is_regex") == "on",
                        request.form.get("ban_action", "delete"),
                        int(request.form.get("duration", 600)),
                        "dashboard"
                    ))
                    conn.commit()
                    flash(f"Added banned word: {word[:30]}", "success")
                except sqlite3.IntegrityError:
                    flash("Word already exists!", "error")
                conn.close()
        
        elif action == "delete":
            word_id = request.form.get("word_id")
            if word_id:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM banned_words WHERE id = ? AND channel = ?", (word_id, channel.lower()))
                conn.commit()
                conn.close()
                flash("Banned word deleted.", "success")
        
        elif action == "toggle":
            word_id = request.form.get("word_id")
            if word_id:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("UPDATE banned_words SET enabled = NOT enabled WHERE id = ? AND channel = ?", (word_id, channel.lower()))
                conn.commit()
                conn.close()
                flash("Banned word toggled.", "success")
        
        elif action == "import":
            file = request.files.get("import_file")
            if file:
                try:
                    content = file.read().decode("utf-8")
                    if file.filename.endswith(".json"):
                        import json
                        words = json.loads(content)
                    else:
                        words = [{"word": w.strip()} for w in content.split("\n") if w.strip()]
                    
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    added = 0
                    for w in words:
                        try:
                            cursor.execute("""
                                INSERT INTO banned_words (channel, word, is_regex, action, duration, added_by)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (
                                channel.lower(),
                                w.get("word", w) if isinstance(w, dict) else w,
                                w.get("is_regex", False) if isinstance(w, dict) else False,
                                w.get("action", "delete") if isinstance(w, dict) else "delete",
                                w.get("duration", 600) if isinstance(w, dict) else 600,
                                "import"
                            ))
                            added += 1
                        except sqlite3.IntegrityError:
                            pass
                    conn.commit()
                    conn.close()
                    flash(f"Imported {added} words.", "success")
                except Exception as e:
                    flash(f"Import error: {str(e)}", "error")
        
        return redirect(url_for("banned_words_page"))
    
    # GET request
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM banned_words WHERE channel = ? ORDER BY added_at DESC", (channel.lower(),))
    words = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return render_template("banned_words.html", words=words)


@app.route("/filters/banned-words/export")
@login_required
def banned_words_export():
    """Export banned words as JSON."""
    import json
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT word, is_regex, action, duration FROM banned_words WHERE channel = ?", (channel.lower(),))
    words = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    response = app.response_class(
        response=json.dumps(words, indent=2),
        status=200,
        mimetype='application/json'
    )
    response.headers["Content-Disposition"] = "attachment; filename=banned_words.json"
    return response




@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    """Bot settings page."""
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
    
    if request.method == "POST":
        prefix = request.form.get("prefix", "!")
        set_env_value("BOT_PREFIX", prefix)
        
        sensitivity = request.form.get("automod_sensitivity", "medium")
        set_env_value("AUTOMOD_SENSITIVITY", sensitivity)
        
        flash("Settings saved! Restart the bot for changes to take effect.", "success")
        return redirect(url_for("settings"))
    
    current_settings = {
        "prefix": get_env_value("BOT_PREFIX", "!"),
        "automod_sensitivity": get_env_value("AUTOMOD_SENSITIVITY", "medium"),
    }
    
    # Get cog settings from database
    cog_settings = get_all_cog_settings(channel)
    
    whitelisted_users = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM users WHERE is_whitelisted = 1")
        whitelisted_users = [row["username"] for row in cursor.fetchall()]
        conn.close()
    except Exception:
        pass
    
    return render_template(
        "settings.html", 
        settings=current_settings, 
        whitelisted_users=whitelisted_users,
        cog_settings=cog_settings,
        channel=channel
    )


@app.route("/credentials", methods=["GET", "POST"])
@login_required
def credentials():
    """Credentials management page."""
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "save":
            fields = [
                "TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", 
                "TWITCH_OAUTH_TOKEN", "TWITCH_BOT_NICK",
                "TWITCH_CHANNELS", "BOT_OWNER"
            ]
            
            for field in fields:
                value = request.form.get(field.lower(), "")
                if value and not value.startswith("*"):
                    set_env_value(field, value)
            
            flash("Credentials saved! Restart the bot for changes to take effect.", "success")
        
        elif action == "restart":
            try:
                subprocess.run(["systemctl", "restart", "twitch-bot"], check=True, timeout=30)
                flash("Bot restarted successfully!", "success")
            except subprocess.CalledProcessError:
                flash("Failed to restart bot. Check system logs.", "error")
            except subprocess.TimeoutExpired:
                flash("Restart command timed out.", "warning")
        
        return redirect(url_for("credentials"))
    
    current_creds = {
        "client_id": mask_secret(get_env_value("TWITCH_CLIENT_ID")),
        "client_secret": mask_secret(get_env_value("TWITCH_CLIENT_SECRET")),
        "oauth_token": mask_secret(get_env_value("TWITCH_OAUTH_TOKEN")),
        "bot_nick": get_env_value("TWITCH_BOT_NICK"),
        "channels": get_env_value("TWITCH_CHANNELS"),
        "owner": get_env_value("BOT_OWNER"),
    }

    # SECURITY: Never send real credentials to browser
    return render_template("credentials.html", credentials=current_creds)


@app.route("/modlog")
@login_required
def modlog():
    """Moderation log page."""
    action_filter = request.args.get("action", "")
    username_filter = request.args.get("username", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    page = int(request.args.get("page", 1))
    per_page = 25
    
    actions = []
    total_count = 0
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM mod_actions WHERE 1=1"
        count_query = "SELECT COUNT(*) as count FROM mod_actions WHERE 1=1"
        params = []
        
        if action_filter:
            query += " AND action = ?"
            count_query += " AND action = ?"
            params.append(action_filter)
        
        if username_filter:
            query += " AND username LIKE ?"
            count_query += " AND username LIKE ?"
            params.append(f"%{username_filter}%")
        
        if date_from:
            query += " AND date(timestamp) >= ?"
            count_query += " AND date(timestamp) >= ?"
            params.append(date_from)
        
        if date_to:
            query += " AND date(timestamp) <= ?"
            count_query += " AND date(timestamp) <= ?"
            params.append(date_to)
        
        cursor.execute(count_query, params)
        total_count = cursor.fetchone()["count"]
        
        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([per_page, (page - 1) * per_page])
        
        cursor.execute(query, params)
        actions = [dict(row) for row in cursor.fetchall()]
        conn.close()
    except Exception as e:
        app.logger.error(f"Error getting mod log: {e}")
    
    total_pages = (total_count + per_page - 1) // per_page
    
    return render_template(
        "modlog.html",
        actions=actions,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        filters={
            "action": action_filter,
            "username": username_filter,
            "date_from": date_from,
            "date_to": date_to
        }
    )


@app.route("/users")
@login_required
def users():
    """Users management page."""
    search = request.args.get("search", "")
    filter_type = request.args.get("filter", "")
    sort_by = request.args.get("sort", "recent")
    page = int(request.args.get("page", 1))
    per_page = 25
    
    users_list = []
    total_count = 0
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM users WHERE 1=1"
        count_query = "SELECT COUNT(*) as count FROM users WHERE 1=1"
        params = []
        
        if search:
            query += " AND username LIKE ?"
            count_query += " AND username LIKE ?"
            params.append(f"%{search}%")
        
        if filter_type == "whitelisted":
            query += " AND is_whitelisted = 1"
            count_query += " AND is_whitelisted = 1"
        elif filter_type == "warned":
            query += " AND warnings_count > 0"
            count_query += " AND warnings_count > 0"
        elif filter_type == "low_trust":
            query += " AND trust_score < 30"
            count_query += " AND trust_score < 30"
        elif filter_type == "high_trust":
            query += " AND trust_score > 70"
            count_query += " AND trust_score > 70"
        elif filter_type == "active":
            query += " AND message_count >= 100"
            count_query += " AND message_count >= 100"
        elif filter_type == "new":
            query += " AND message_count < 10"
            count_query += " AND message_count < 10"
        
        cursor.execute(count_query, params)
        total_count = cursor.fetchone()["count"]
        
        # Apply sorting
        if sort_by == "messages":
            query += " ORDER BY message_count DESC"
        elif sort_by == "trust_high":
            query += " ORDER BY trust_score DESC"
        elif sort_by == "trust_low":
            query += " ORDER BY trust_score ASC"
        elif sort_by == "warnings":
            query += " ORDER BY warnings_count DESC"
        else:  # recent (default)
            query += " ORDER BY last_message DESC NULLS LAST"
        
        query += " LIMIT ? OFFSET ?"
        params.extend([per_page, (page - 1) * per_page])
        
        cursor.execute(query, params)
        users_list = [dict(row) for row in cursor.fetchall()]
        conn.close()
    except Exception as e:
        app.logger.error(f"Error getting users: {e}")
    
    total_pages = (total_count + per_page - 1) // per_page
    
    return render_template(
        "users.html",
        users=users_list,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        search=search,
        filter_type=filter_type,
        sort_by=sort_by
    )




# ==================== API Routes ====================

@app.route("/api/command/<name>")
@login_required
def get_command(name: str):
    """Get command details."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM custom_commands WHERE name = ?", (name.lower(),))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            cmd = dict(row)
            cmd["aliases"] = " ".join(json.loads(cmd["aliases"])) if cmd.get("aliases") else ""
            return jsonify({"success": True, "command": cmd})
        return jsonify({"success": False, "error": "Not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/command/<name>/delete", methods=["POST"])
@login_required
def delete_command(name: str):
    """Delete a command."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM custom_commands WHERE name = ?", (name.lower(),))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/timer/<name>")
@login_required
def get_timer(name: str):
    """Get timer details."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM timers WHERE name = ?", (name.lower(),))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return jsonify({"success": True, "timer": dict(row)})
        return jsonify({"success": False, "error": "Not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/timer/<name>/delete", methods=["POST"])
@login_required
def delete_timer(name: str):
    """Delete a timer."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM timers WHERE name = ?", (name.lower(),))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/timer/<name>/toggle", methods=["POST"])
@login_required
def toggle_timer(name: str):
    """Toggle timer enabled state."""
    try:
        data = request.get_json()
        enabled = data.get("enabled", True)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE timers SET enabled = ? WHERE name = ?", (enabled, name.lower()))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/strikes/<user_id>/history")
@login_required
def get_strike_history(user_id: str):
    """Get strike history for a user."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM strike_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT 20
        """, (user_id,))
        history = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify({"success": True, "history": history})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/strikes/<user_id>/clear", methods=["POST"])
@login_required
def clear_strikes(user_id: str):
    """Clear strikes for a user."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE user_strikes SET strike_count = 0, expires_at = NULL WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/user/<user_id>/whitelist", methods=["POST"])
@login_required
def toggle_whitelist(user_id: str):
    """Toggle user whitelist status."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT is_whitelisted FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        
        if row:
            new_status = not bool(row["is_whitelisted"])
            cursor.execute("UPDATE users SET is_whitelisted = ? WHERE user_id = ?", (new_status, user_id))
            conn.commit()
            conn.close()
            return jsonify({"success": True, "whitelisted": new_status})
        
        conn.close()
        return jsonify({"success": False, "error": "User not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/user/<user_id>/history")
@login_required
def get_user_history(user_id: str):
    """Get user moderation history."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM mod_actions WHERE user_id = ? ORDER BY timestamp DESC LIMIT 50
        """, (user_id,))
        actions = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify({"success": True, "actions": actions})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500




@app.route("/api/link-list", methods=["POST"])
@login_required
def add_link_to_list():
    """Add a domain to whitelist or blacklist."""
    try:
        channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
        data = request.get_json()
        domain = data.get("domain", "").strip().lower()
        list_type = data.get("list_type", "whitelist")
        
        if not domain:
            return jsonify({"success": False, "error": "Domain is required"}), 400
        
        # Clean domain
        domain = domain.replace("https://", "").replace("http://", "").split("/")[0]
        
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO link_lists (channel, domain, list_type, added_by)
                VALUES (?, ?, ?, ?)
            """, (channel.lower(), domain, list_type, "dashboard"))
            conn.commit()
            link_id = cursor.lastrowid
            conn.close()
            return jsonify({"success": True, "id": link_id, "domain": domain, "list_type": list_type})
        except Exception as e:
            conn.close()
            return jsonify({"success": False, "error": "Domain already exists"}), 409
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/link-list/<int:link_id>", methods=["DELETE"])
@login_required
def remove_link_from_list(link_id: int):
    """Remove a domain from whitelist or blacklist."""
    try:
        channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM link_lists WHERE id = ? AND channel = ?", (link_id, channel.lower()))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/link-list")
@login_required
def get_link_lists():
    """Get all whitelisted and blacklisted domains."""
    try:
        channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM link_lists WHERE channel = ? AND list_type = 'whitelist' ORDER BY domain", (channel.lower(),))
        whitelist = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM link_lists WHERE channel = ? AND list_type = 'blacklist' ORDER BY domain", (channel.lower(),))
        blacklist = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return jsonify({"success": True, "whitelist": whitelist, "blacklist": blacklist})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/filters/sensitivity", methods=["POST"])
@login_required
def set_filter_sensitivity():
    """Apply sensitivity preset to all filters."""
    try:
        channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
        data = request.get_json()
        sensitivity = data.get("sensitivity", "medium")
        
        # Define presets
        presets = {
            "low": {
                "caps_max_percent": 90, "caps_min_length": 15,
                "emote_max_count": 25, "symbol_max_percent": 70,
                "length_max_chars": 750, "repetition_max_words": 15
            },
            "medium": {
                "caps_max_percent": 70, "caps_min_length": 10,
                "emote_max_count": 15, "symbol_max_percent": 50,
                "length_max_chars": 500, "repetition_max_words": 10
            },
            "high": {
                "caps_max_percent": 50, "caps_min_length": 8,
                "emote_max_count": 8, "symbol_max_percent": 30,
                "length_max_chars": 300, "repetition_max_words": 5
            }
        }
        
        if sensitivity not in presets:
            return jsonify({"success": False, "error": "Invalid sensitivity level"}), 400
        
        preset = presets[sensitivity]
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE filter_settings SET
                global_sensitivity = ?,
                caps_max_percent = ?, caps_min_length = ?,
                emote_max_count = ?, symbol_max_percent = ?,
                length_max_chars = ?, repetition_max_words = ?
            WHERE channel = ?
        """, (
            sensitivity,
            preset["caps_max_percent"], preset["caps_min_length"],
            preset["emote_max_count"], preset["symbol_max_percent"],
            preset["length_max_chars"], preset["repetition_max_words"],
            channel
        ))
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "preset": preset, "sensitivity": sensitivity})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/test-filter", methods=["POST"])
@login_required
def test_filter():
    """Test a message against filters."""
    try:
        data = request.get_json()
        message = data.get("message", "")
        
        # Simple test - in production would use actual spam detector
        score = 0
        reasons = []
        
        # Check caps
        if len(message) > 10:
            alpha = [c for c in message if c.isalpha()]
            if alpha:
                caps_pct = sum(1 for c in alpha if c.isupper()) / len(alpha) * 100
                if caps_pct > 70:
                    score += 20
                    reasons.append(f"Excessive caps ({caps_pct:.0f}%)")
        
        # Check length
        if len(message) > 500:
            score += 10
            reasons.append(f"Too long ({len(message)} chars)")
        
        # Check repeated chars
        import re
        if re.search(r'(.)\1{4,}', message):
            score += 15
            reasons.append("Repeated characters")
        
        action = "allow"
        if score >= 50:
            action = "timeout"
        elif score >= 30:
            action = "delete"
        elif score >= 20:
            action = "flag"
        
        return jsonify({
            "success": True,
            "score": score,
            "action": action,
            "reasons": reasons
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/bot/restart", methods=["POST"])
@login_required
def restart_bot():
    """Restart the bot service."""
    try:
        subprocess.run(["sudo", "systemctl", "restart", "twitch-bot"], check=True, timeout=30)
        return jsonify({"success": True, "message": "Bot restarted successfully"})
    except subprocess.CalledProcessError as e:
        return jsonify({"success": False, "error": f"Failed to restart: {e}"}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Restart timed out"}), 500


@app.route("/api/bot/status")
@login_required
def api_bot_status():
    """Get bot status via API."""
    return jsonify(get_bot_status())


@app.route("/api/cog/<cog_name>/toggle", methods=["POST"])
@login_required
def toggle_cog(cog_name: str):
    """Toggle cog enabled status for the channel."""
    try:
        channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
        
        if not channel:
            return jsonify({"success": False, "error": "No channel configured"}), 400
        
        # Accept both JSON and form data
        if request.is_json:
            data = request.get_json() or {}
        else:
            data = request.form.to_dict()
        
        enabled_val = data.get("enabled")
        if enabled_val is not None:
            enabled = enabled_val in [True, "true", "1", 1, "on"]
        else:
            enabled = None
        
        # If enabled not specified, toggle current state
        if enabled is None:
            cog_settings = get_all_cog_settings(channel)
            if cog_name not in cog_settings:
                return jsonify({"success": False, "error": f"Unknown cog: {cog_name}"}), 404
            enabled = not cog_settings[cog_name]["enabled"]
        
        if set_cog_enabled(channel, cog_name, enabled):
            return jsonify({
                "success": True,
                "cog_name": cog_name,
                "enabled": enabled,
                "message": f"Cog '{cog_name}' {'enabled' if enabled else 'disabled'}"
            })
        else:
            return jsonify({"success": False, "error": "Failed to update cog setting"}), 500
            
    except Exception as e:
        app.logger.error(f"Error toggling cog: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/cog/settings")
@login_required
def get_cog_settings_api():
    """Get all cog settings for the channel."""
    try:
        channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
        
        if not channel:
            return jsonify({"success": False, "error": "No channel configured"}), 400
        
        cog_settings = get_all_cog_settings(channel)
        return jsonify({
            "success": True,
            "channel": channel,
            "cogs": cog_settings
        })
    except Exception as e:
        app.logger.error(f"Error getting cog settings: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== Quotes Routes ====================

@app.route("/quotes", methods=["GET", "POST"])
@login_required
def quotes_page():
    """Quotes management page."""
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
    
    if request.method == "POST":
        action = request.form.get("action")
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if action == "add":
            cursor.execute("""
                INSERT INTO quotes (channel, quote_text, author, added_by, game)
                VALUES (?, ?, ?, ?, ?)
            """, (
                channel,
                request.form.get("quote_text"),
                request.form.get("author") or "Unknown",
                "dashboard",
                request.form.get("game")
            ))
            conn.commit()
            flash("Quote added!", "success")
        
        elif action == "edit":
            quote_id = request.form.get("quote_id")
            cursor.execute("""
                UPDATE quotes SET quote_text = ?, author = ?, game = ?
                WHERE id = ? AND channel = ?
            """, (
                request.form.get("quote_text"),
                request.form.get("author") or "Unknown",
                request.form.get("game"),
                quote_id,
                channel
            ))
            conn.commit()
            flash("Quote updated!", "success")
        
        conn.close()
        return redirect(url_for("quotes_page"))
    
    # Get all quotes
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM quotes WHERE channel = ? AND enabled = 1 ORDER BY id DESC
    """, (channel,))
    quotes = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return render_template("quotes.html", quotes=quotes)


@app.route("/api/quote/<int:quote_id>")
@login_required
def get_quote(quote_id: int):
    """Get quote details."""
    try:
        channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM quotes WHERE id = ? AND channel = ?", (quote_id, channel))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return jsonify({"success": True, "quote": dict(row)})
        return jsonify({"success": False, "error": "Not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/quote/<int:quote_id>/delete", methods=["POST"])
@login_required
def delete_quote(quote_id: int):
    """Delete a quote (soft delete)."""
    try:
        channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE quotes SET enabled = 0 WHERE id = ? AND channel = ?", (quote_id, channel))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== Giveaways Routes ====================

@app.route("/giveaways", methods=["GET", "POST"])
@login_required
def giveaways_page():
    """Giveaways management page."""
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
    
    if request.method == "POST":
        action = request.form.get("action")
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if action == "start":
            # Check for active giveaway
            cursor.execute("SELECT id FROM giveaways WHERE channel = ? AND status = 'active'", (channel,))
            if cursor.fetchone():
                flash("A giveaway is already active!", "error")
            else:
                duration = request.form.get("duration")
                ends_at = None
                if duration and int(duration) > 0:
                    from datetime import datetime, timedelta
                
                cursor.execute("""
                    INSERT INTO giveaways (channel, keyword, prize, started_by, ends_at, winner_count, sub_luck_multiplier, sub_only, min_points)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    channel,
                    request.form.get("keyword", "!enter"),
                    request.form.get("prize"),
                    "dashboard",
                    ends_at,
                    int(request.form.get("winner_count", 1)),
                    float(request.form.get("sub_luck", 2)),
                    request.form.get("sub_only") == "on",
                    int(request.form.get("min_points", 0))
                ))
                conn.commit()
                flash("Giveaway started!", "success")
        
        conn.close()
        return redirect(url_for("giveaways_page"))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get active giveaway
    cursor.execute("SELECT * FROM giveaways WHERE channel = ? AND status = 'active'", (channel,))
    active_row = cursor.fetchone()
    active_giveaway = dict(active_row) if active_row else None
    
    entry_count = 0
    if active_giveaway:
        cursor.execute("SELECT COUNT(*) as count FROM giveaway_entries WHERE giveaway_id = ?", (active_giveaway["id"],))
        entry_count = cursor.fetchone()["count"]
    
    # Get history
    cursor.execute("""
        SELECT g.*, 
               (SELECT COUNT(*) FROM giveaway_entries WHERE giveaway_id = g.id) as entry_count
        FROM giveaways g 
        WHERE g.channel = ? AND g.status != 'active'
        ORDER BY g.started_at DESC LIMIT 50
    """, (channel,))
    history = []
    for row in cursor.fetchall():
        giveaway = dict(row)
        # Get winners
        cursor.execute("SELECT username FROM giveaway_winners WHERE giveaway_id = ?", (giveaway["id"],))
        giveaway["winners"] = [w["username"] for w in cursor.fetchall()]
        history.append(giveaway)
    
    # Get totals
    cursor.execute("SELECT COUNT(*) as count FROM giveaway_entries WHERE giveaway_id IN (SELECT id FROM giveaways WHERE channel = ?)", (channel,))
    total_entries = cursor.fetchone()["count"]
    
    cursor.execute("SELECT COUNT(*) as count FROM giveaway_winners WHERE giveaway_id IN (SELECT id FROM giveaways WHERE channel = ?)", (channel,))
    total_winners = cursor.fetchone()["count"]
    
    conn.close()
    
    return render_template("giveaways.html", 
                          active_giveaway=active_giveaway,
                          entry_count=entry_count,
                          history=history,
                          total_entries=total_entries,
                          total_winners=total_winners)


@app.route("/api/giveaway/end", methods=["POST"])
@login_required
def end_giveaway():
    """End giveaway and pick winner(s)."""
    try:
        import random
        channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM giveaways WHERE channel = ? AND status = 'active'", (channel,))
        giveaway = cursor.fetchone()
        
        if not giveaway:
            return jsonify({"success": False, "error": "No active giveaway"}), 404
        
        giveaway = dict(giveaway)
        
        # Get entries with tickets
        cursor.execute("SELECT * FROM giveaway_entries WHERE giveaway_id = ?", (giveaway["id"],))
        entries = [dict(row) for row in cursor.fetchall()]
        
        if not entries:
            cursor.execute("UPDATE giveaways SET status = 'ended' WHERE id = ?", (giveaway["id"],))
            conn.commit()
            conn.close()
            return jsonify({"success": True, "winners": [], "message": "No entries"})
        
        # Build weighted pool
        pool = []
        for entry in entries:
            pool.extend([entry] * entry.get("tickets", 1))
        
        # Pick winners
        winners = []
        winner_count = giveaway.get("winner_count", 1)
        picked_ids = set()
        
        for _ in range(min(winner_count, len(entries))):
            available = [e for e in pool if e["user_id"] not in picked_ids]
            if not available:
                break
            winner = random.choice(available)
            winners.append(winner["username"])
            picked_ids.add(winner["user_id"])
            
            cursor.execute("""
                INSERT INTO giveaway_winners (giveaway_id, user_id, username)
                VALUES (?, ?, ?)
            """, (giveaway["id"], winner["user_id"], winner["username"]))
        
        cursor.execute("UPDATE giveaways SET status = 'ended' WHERE id = ?", (giveaway["id"],))
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "winners": winners})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/giveaway/cancel", methods=["POST"])
@login_required
def cancel_giveaway():
    """Cancel active giveaway."""
    try:
        channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE giveaways SET status = 'cancelled' WHERE channel = ? AND status = 'active'", (channel,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/giveaway/entries")
@login_required
def get_giveaway_entries():
    """Get entry count for active giveaway."""
    try:
        channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) as count FROM giveaway_entries 
            WHERE giveaway_id = (SELECT id FROM giveaways WHERE channel = ? AND status = 'active')
        """, (channel,))
        row = cursor.fetchone()
        conn.close()
        return jsonify({"success": True, "count": row["count"] if row else 0})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== Song Requests Routes ====================

@app.route("/songrequests", methods=["GET", "POST"])
@login_required
def songrequests_page():
    """Song requests management page."""
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Ensure tables exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS songrequest_settings (
            channel TEXT PRIMARY KEY,
            enabled BOOLEAN DEFAULT FALSE,
            max_queue_size INTEGER DEFAULT 50,
            max_duration_seconds INTEGER DEFAULT 600,
            user_limit INTEGER DEFAULT 3,
            sub_limit INTEGER DEFAULT 5,
            volume INTEGER DEFAULT 50
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS song_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            video_id TEXT NOT NULL,
            title TEXT NOT NULL,
            duration_seconds INTEGER,
            requested_by TEXT NOT NULL,
            requested_by_id TEXT NOT NULL,
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'queued'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS song_blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            video_id TEXT,
            reason TEXT,
            added_by TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS song_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            video_id TEXT NOT NULL,
            title TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "settings":
            cursor.execute("""
                INSERT INTO songrequest_settings (channel, enabled, max_queue_size, max_duration_seconds, user_limit, sub_limit, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel) DO UPDATE SET
                    max_queue_size = excluded.max_queue_size,
                    max_duration_seconds = excluded.max_duration_seconds,
                    user_limit = excluded.user_limit,
                    sub_limit = excluded.sub_limit,
                    volume = excluded.volume
            """, (
                channel,
                True,  # Keep current enabled state
                int(request.form.get("max_queue_size", 50)),
                int(request.form.get("max_duration_seconds", 600)),
                int(request.form.get("user_limit", 3)),
                int(request.form.get("sub_limit", 5)),
                int(request.form.get("volume", 50))
            ))
            conn.commit()
            flash("Settings saved!", "success")
        
        elif action == "blacklist":
            video_id = request.form.get("video_id", "").strip()
            # Extract video ID from URL if needed
            import re
            match = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})', video_id)
            if match:
                video_id = match.group(1)
            
            cursor.execute("""
                INSERT INTO song_blacklist (channel, video_id, reason, added_by)
                VALUES (?, ?, ?, ?)
            """, (channel, video_id, request.form.get("reason"), "dashboard"))
            conn.commit()
            flash("Added to blacklist!", "success")
        
        conn.close()
        return redirect(url_for("songrequests_page"))
    
    # Get settings
    cursor.execute("SELECT * FROM songrequest_settings WHERE channel = ?", (channel,))
    row = cursor.fetchone()
    settings = dict(row) if row else {
        "enabled": False,
        "max_queue_size": 50,
        "max_duration_seconds": 600,
        "user_limit": 3,
        "sub_limit": 5,
        "volume": 50
    }
    
    # Get current song
    cursor.execute("SELECT * FROM song_queue WHERE channel = ? AND status = 'playing'", (channel,))
    current_row = cursor.fetchone()
    current_song = dict(current_row) if current_row else None
    
    # Get queue
    cursor.execute("SELECT * FROM song_queue WHERE channel = ? AND status = 'queued' ORDER BY id", (channel,))
    queue = [dict(row) for row in cursor.fetchall()]
    
    # Get blacklist
    cursor.execute("SELECT * FROM song_blacklist WHERE channel = ?", (channel,))
    blacklist = [dict(row) for row in cursor.fetchall()]
    
    # Get history
    cursor.execute("SELECT * FROM song_history WHERE channel = ? ORDER BY played_at DESC LIMIT 20", (channel,))
    history = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return render_template("songrequests.html",
                          settings=settings,
                          current_song=current_song,
                          queue=queue,
                          blacklist=blacklist,
                          history=history)


@app.route("/api/songrequests/toggle", methods=["POST"])
@login_required
def toggle_songrequests():
    """Toggle song requests enabled state."""
    try:
        channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
        data = request.get_json() or {}
        enabled = data.get("enabled", False)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO songrequest_settings (channel, enabled)
            VALUES (?, ?)
            ON CONFLICT(channel) DO UPDATE SET enabled = excluded.enabled
        """, (channel, enabled))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/songrequests/skip", methods=["POST"])
@login_required
def skip_song():
    """Skip current song."""
    try:
        channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Mark current as skipped
        cursor.execute("UPDATE song_queue SET status = 'skipped' WHERE channel = ? AND status = 'playing'", (channel,))
        
        # Get next song and mark as playing
        cursor.execute("SELECT id FROM song_queue WHERE channel = ? AND status = 'queued' ORDER BY id LIMIT 1", (channel,))
        next_song = cursor.fetchone()
        if next_song:
            cursor.execute("UPDATE song_queue SET status = 'playing' WHERE id = ?", (next_song["id"],))
        
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/songrequests/clear", methods=["POST"])
@login_required
def clear_song_queue():
    """Clear the song queue."""
    try:
        channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM song_queue WHERE channel = ? AND status = 'queued'", (channel,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/songrequests/<int:song_id>/remove", methods=["POST"])
@login_required
def remove_song(song_id: int):
    """Remove a song from queue."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM song_queue WHERE id = ?", (song_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/songrequests/<int:song_id>/promote", methods=["POST"])
@login_required
def promote_song(song_id: int):
    """Move a song to the front of the queue."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get the minimum ID in queue
        cursor.execute("SELECT MIN(id) as min_id FROM song_queue WHERE status = 'queued'")
        row = cursor.fetchone()
        if row and row["min_id"]:
            # Update the song's ID to be before the minimum (hacky but works)
            cursor.execute("UPDATE song_queue SET requested_at = datetime('now', '-1 hour') WHERE id = ?", (song_id,))
        
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/songrequests/blacklist/<int:item_id>/remove", methods=["POST"])
@login_required
def remove_blacklist(item_id: int):
    """Remove item from blacklist."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM song_blacklist WHERE id = ?", (item_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500




# ==================== Queue Management Routes ====================

def get_queue_settings_from_db(channel: str) -> dict:
    """Get queue settings from database."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM queue_settings WHERE channel = ? AND queue_name = 'default'
        """, (channel.lower(),))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "default_max_size": row["max_size"],
                "default_open": bool(row["is_open"]),
                "sub_priority": bool(row["sub_priority"])
            }
    except Exception as e:
        app.logger.error(f"Error getting queue settings: {e}")
    
    return {
        "default_max_size": 50,
        "default_open": False,
        "sub_priority": False
    }


def get_all_queues(channel: str) -> list[dict]:
    """Get all queues with their entries for a channel."""
    queues = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get all queue settings
        cursor.execute("""
            SELECT DISTINCT queue_name, is_open, max_size, sub_priority
            FROM queue_settings
            WHERE channel = ?
        """, (channel.lower(),))
        
        queue_settings = {row["queue_name"]: dict(row) for row in cursor.fetchall()}
        
        # Get all unique queue names from entries too
        cursor.execute("""
            SELECT DISTINCT queue_name FROM viewer_queue WHERE channel = ?
        """, (channel.lower(),))
        
        for row in cursor.fetchall():
            if row["queue_name"] not in queue_settings:
                queue_settings[row["queue_name"]] = {
                    "queue_name": row["queue_name"],
                    "is_open": False,
                    "max_size": 50,
                    "sub_priority": False
                }
        
        # Build queue data with entries
        for queue_name, settings in queue_settings.items():
            # Get entries (not picked)
            order_by = "is_subscriber DESC, joined_at ASC" if settings.get("sub_priority") else "joined_at ASC"
            cursor.execute(f"""
                SELECT user_id, username, is_subscriber, joined_at
                FROM viewer_queue
                WHERE channel = ? AND queue_name = ? AND picked = FALSE
                ORDER BY {order_by}
            """, (channel.lower(), queue_name))
            entries = [dict(row) for row in cursor.fetchall()]
            
            # Get picked count
            cursor.execute("""
                SELECT COUNT(*) as count FROM viewer_queue
                WHERE channel = ? AND queue_name = ? AND picked = TRUE
            """, (channel.lower(), queue_name))
            picked_count = cursor.fetchone()["count"]
            
            queues.append({
                "queue_name": queue_name,
                "is_open": settings.get("is_open", False),
                "max_size": settings.get("max_size", 50),
                "sub_priority": settings.get("sub_priority", False),
                "entries": entries,
                "entry_count": len(entries),
                "picked_count": picked_count
            })
        
        conn.close()
    except Exception as e:
        app.logger.error(f"Error getting queues: {e}")
    
    return sorted(queues, key=lambda x: x["queue_name"])


def get_queue_history(channel: str, limit: int = 20) -> list[dict]:
    """Get recent queue activity."""
    history = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get recently picked users
        cursor.execute("""
            SELECT queue_name, username, picked_at as timestamp, 'picked' as action, 'System' as performed_by
            FROM viewer_queue
            WHERE channel = ? AND picked = TRUE AND picked_at IS NOT NULL
            ORDER BY picked_at DESC
            LIMIT ?
        """, (channel.lower(), limit))
        
        history = [dict(row) for row in cursor.fetchall()]
        conn.close()
    except Exception as e:
        app.logger.error(f"Error getting queue history: {e}")
    
    return history


@app.route("/queue-management")
@login_required
def queue_management():
    """Queue management page."""
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
    
    settings = get_queue_settings_from_db(channel)
    queues = get_all_queues(channel)
    history = get_queue_history(channel)
    
    return render_template(
        "queue_management.html",
        settings=settings,
        queues=queues,
        history=history
    )


@app.route("/queue-management/settings", methods=["POST"])
@login_required
def queue_management_settings():
    """Save queue settings."""
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        default_max_size = int(request.form.get("default_max_size", 50))
        default_open = request.form.get("default_open") == "open"
        sub_priority = request.form.get("sub_priority") == "on"
        
        cursor.execute("""
            INSERT INTO queue_settings (channel, queue_name, is_open, max_size, sub_priority)
            VALUES (?, 'default', ?, ?, ?)
            ON CONFLICT(channel, queue_name) DO UPDATE SET
                is_open = excluded.is_open,
                max_size = excluded.max_size,
                sub_priority = excluded.sub_priority
        """, (channel.lower(), default_open, default_max_size, sub_priority))
        
        conn.commit()
        conn.close()
        flash("Queue settings saved!", "success")
    except Exception as e:
        app.logger.error(f"Error saving queue settings: {e}")
        flash(f"Error saving settings: {e}", "error")
    
    return redirect(url_for("queue_management"))


@app.route("/queue-management/action", methods=["POST"])
@login_required
def queue_management_action():
    """Handle queue actions (open, close, clear, pick)."""
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
    action = request.form.get("action")
    queue_name = request.form.get("queue_name", "default")
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if action == "create":
            max_size = int(request.form.get("max_size", 50))
            open_immediately = request.form.get("open_immediately") == "on"
            
            cursor.execute("""
                INSERT INTO queue_settings (channel, queue_name, is_open, max_size, sub_priority)
                VALUES (?, ?, ?, ?, FALSE)
                ON CONFLICT(channel, queue_name) DO UPDATE SET
                    is_open = excluded.is_open,
                    max_size = excluded.max_size
            """, (channel.lower(), queue_name.lower(), open_immediately, max_size))
            conn.commit()
            conn.close()
            flash(f"Queue '{queue_name}' created!", "success")
            return redirect(url_for("queue_management"))
        
        elif action == "open":
            cursor.execute("""
                UPDATE queue_settings SET is_open = TRUE
                WHERE channel = ? AND queue_name = ?
            """, (channel.lower(), queue_name.lower()))
            
            # Create settings if they don't exist
            if cursor.rowcount == 0:
                cursor.execute("""
                    INSERT INTO queue_settings (channel, queue_name, is_open, max_size, sub_priority)
                    VALUES (?, ?, TRUE, 50, FALSE)
                """, (channel.lower(), queue_name.lower()))
            
            conn.commit()
            conn.close()
            return jsonify({"success": True, "message": f"Queue '{queue_name}' opened"})
        
        elif action == "close":
            cursor.execute("""
                UPDATE queue_settings SET is_open = FALSE
                WHERE channel = ? AND queue_name = ?
            """, (channel.lower(), queue_name.lower()))
            conn.commit()
            conn.close()
            return jsonify({"success": True, "message": f"Queue '{queue_name}' closed"})
        
        elif action == "clear":
            cursor.execute("""
                DELETE FROM viewer_queue
                WHERE channel = ? AND queue_name = ?
            """, (channel.lower(), queue_name.lower()))
            cleared = cursor.rowcount
            conn.commit()
            conn.close()
            return jsonify({"success": True, "message": f"Cleared {cleared} entries", "cleared": cleared})
        
        elif action == "next":
            # Get queue settings for ordering
            cursor.execute("""
                SELECT sub_priority FROM queue_settings
                WHERE channel = ? AND queue_name = ?
            """, (channel.lower(), queue_name.lower()))
            row = cursor.fetchone()
            sub_priority = bool(row["sub_priority"]) if row else False
            
            order_by = "is_subscriber DESC, joined_at ASC" if sub_priority else "joined_at ASC"
            
            cursor.execute(f"""
                SELECT id, user_id, username, is_subscriber
                FROM viewer_queue
                WHERE channel = ? AND queue_name = ? AND picked = FALSE
                ORDER BY {order_by}
                LIMIT 1
            """, (channel.lower(), queue_name.lower()))
            
            entry = cursor.fetchone()
            if entry:
                cursor.execute("""
                    UPDATE viewer_queue SET picked = TRUE, picked_at = datetime('now')
                    WHERE id = ?
                """, (entry["id"],))
                conn.commit()
                conn.close()
                return jsonify({
                    "success": True,
                    "picked": {
                        "user_id": entry["user_id"],
                        "username": entry["username"],
                        "is_subscriber": bool(entry["is_subscriber"])
                    }
                })
            
            conn.close()
            return jsonify({"success": True, "picked": None, "message": "Queue is empty"})
        
        elif action == "random":
            import random
            
            cursor.execute("""
                SELECT id, user_id, username, is_subscriber
                FROM viewer_queue
                WHERE channel = ? AND queue_name = ? AND picked = FALSE
            """, (channel.lower(), queue_name.lower()))
            
            entries = cursor.fetchall()
            if entries:
                entry = random.choice(entries)
                cursor.execute("""
                    UPDATE viewer_queue SET picked = TRUE, picked_at = datetime('now')
                    WHERE id = ?
                """, (entry["id"],))
                conn.commit()
                conn.close()
                return jsonify({
                    "success": True,
                    "picked": {
                        "user_id": entry["user_id"],
                        "username": entry["username"],
                        "is_subscriber": bool(entry["is_subscriber"])
                    }
                })
            
            conn.close()
            return jsonify({"success": True, "picked": None, "message": "Queue is empty"})
        
        conn.close()
        return jsonify({"success": False, "error": "Unknown action"})
        
    except Exception as e:
        app.logger.error(f"Error performing queue action: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/queue-management/data")
@login_required
def queue_management_data():
    """Get queue data for AJAX refresh."""
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
    
    try:
        queues = get_all_queues(channel)
        return jsonify({"success": True, "queues": queues})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



# ==================== Alerts Settings Routes ====================

@app.route("/alerts-settings", methods=["GET", "POST"])
@login_required
def alerts_settings():
    """Chat alerts settings page."""
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Ensure alert_settings table has all columns we need
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alert_settings (
            channel TEXT PRIMARY KEY,
            alerts_enabled BOOLEAN DEFAULT TRUE,
            alert_cooldown INTEGER DEFAULT 5,
            follow_enabled BOOLEAN DEFAULT TRUE,
            follow_message TEXT DEFAULT 'Welcome @$(user) to the community! 🎉',
            sub_enabled BOOLEAN DEFAULT TRUE,
            sub_message TEXT DEFAULT 'Thanks @$(user) for subscribing! 💜',
            resub_enabled BOOLEAN DEFAULT TRUE,
            resub_message TEXT DEFAULT 'Thanks @$(user) for $(months) months! 💜',
            giftsub_enabled BOOLEAN DEFAULT TRUE,
            giftsub_message TEXT DEFAULT '@$(user) gifted a sub to @$(recipient)! 🎁',
            raid_enabled BOOLEAN DEFAULT TRUE,
            raid_message TEXT DEFAULT 'Welcome $(count) raiders from @$(user)! 🎊',
            bits_enabled BOOLEAN DEFAULT TRUE,
            bits_message TEXT DEFAULT 'Thanks @$(user) for $(bits) bits! 💎',
            bits_minimum INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "global_settings":
            cursor.execute("""
                INSERT INTO alert_settings (channel, alerts_enabled, alert_cooldown)
                VALUES (?, ?, ?)
                ON CONFLICT(channel) DO UPDATE SET
                    alerts_enabled = excluded.alerts_enabled,
                    alert_cooldown = excluded.alert_cooldown
            """, (
                channel,
                request.form.get("alerts_enabled") == "on",
                int(request.form.get("alert_cooldown", 5))
            ))
            conn.commit()
            flash("Global settings saved!", "success")
        
        elif action == "save_alerts":
            cursor.execute("""
                INSERT INTO alert_settings (
                    channel, follow_enabled, follow_message,
                    sub_enabled, sub_message, resub_enabled, resub_message,
                    giftsub_enabled, giftsub_message,
                    raid_enabled, raid_message,
                    bits_enabled, bits_message, bits_minimum
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel) DO UPDATE SET
                    follow_enabled = excluded.follow_enabled,
                    follow_message = excluded.follow_message,
                    sub_enabled = excluded.sub_enabled,
                    sub_message = excluded.sub_message,
                    resub_enabled = excluded.resub_enabled,
                    resub_message = excluded.resub_message,
                    giftsub_enabled = excluded.giftsub_enabled,
                    giftsub_message = excluded.giftsub_message,
                    raid_enabled = excluded.raid_enabled,
                    raid_message = excluded.raid_message,
                    bits_enabled = excluded.bits_enabled,
                    bits_message = excluded.bits_message,
                    bits_minimum = excluded.bits_minimum
            """, (
                channel,
                request.form.get("follow_enabled") == "on",
                request.form.get("follow_message", "Welcome @$(user) to the community! 🎉"),
                request.form.get("sub_enabled") == "on",
                request.form.get("sub_message", "Thanks @$(user) for subscribing! 💜"),
                request.form.get("resub_enabled") == "on",
                request.form.get("resub_message", "Thanks @$(user) for $(months) months! 💜"),
                request.form.get("giftsub_enabled") == "on",
                request.form.get("giftsub_message", "@$(user) gifted a sub to @$(recipient)! 🎁"),
                request.form.get("raid_enabled") == "on",
                request.form.get("raid_message", "Welcome $(count) raiders from @$(user)! 🎊"),
                request.form.get("bits_enabled") == "on",
                request.form.get("bits_message", "Thanks @$(user) for $(bits) bits! 💎"),
                int(request.form.get("bits_minimum", 1))
            ))
            conn.commit()
            flash("Alert settings saved!", "success")
        
        conn.close()
        return redirect(url_for("alerts_settings"))
    
    # GET request - load settings
    cursor.execute("SELECT * FROM alert_settings WHERE channel = ?", (channel,))
    row = cursor.fetchone()
    settings = dict(row) if row else {
        "alerts_enabled": True,
        "alert_cooldown": 5,
        "follow_enabled": True,
        "follow_message": "Welcome @$(user) to the community! 🎉",
        "sub_enabled": True,
        "sub_message": "Thanks @$(user) for subscribing! 💜",
        "resub_enabled": True,
        "resub_message": "Thanks @$(user) for $(months) months! 💜",
        "giftsub_enabled": True,
        "giftsub_message": "@$(user) gifted a sub to @$(recipient)! 🎁",
        "raid_enabled": True,
        "raid_message": "Welcome $(count) raiders from @$(user)! 🎊",
        "bits_enabled": True,
        "bits_message": "Thanks @$(user) for $(bits) bits! 💎",
        "bits_minimum": 1
    }
    conn.close()
    
    return render_template("alerts_settings.html", settings=settings)

# ==================== Raid Protection Settings ====================

@app.route("/raid-settings", methods=["GET", "POST"])
@login_required
def raid_settings():
    """Raid protection settings page."""
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
    
    if request.method == "POST":
        action = request.form.get("action", "save_settings")
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if action == "save_settings":
            # Ensure table exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS raid_settings (
                    channel TEXT PRIMARY KEY,
                    enabled BOOLEAN DEFAULT TRUE,
                    auto_detect_threshold INTEGER DEFAULT 5,
                    duration_minutes INTEGER DEFAULT 5,
                    follower_only BOOLEAN DEFAULT TRUE,
                    follower_age_minutes INTEGER DEFAULT 10,
                    slow_mode BOOLEAN DEFAULT TRUE,
                    slow_mode_seconds INTEGER DEFAULT 30,
                    welcome_message TEXT DEFAULT 'Welcome raiders! Chat is in protected mode for a few minutes. 🛡️'
                )
            """)
            
            # Save settings
            cursor.execute("""
                INSERT INTO raid_settings 
                (channel, enabled, auto_detect_threshold, duration_minutes, follower_only, 
                 follower_age_minutes, slow_mode, slow_mode_seconds, welcome_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel) DO UPDATE SET
                    enabled = excluded.enabled,
                    auto_detect_threshold = excluded.auto_detect_threshold,
                    duration_minutes = excluded.duration_minutes,
                    follower_only = excluded.follower_only,
                    follower_age_minutes = excluded.follower_age_minutes,
                    slow_mode = excluded.slow_mode,
                    slow_mode_seconds = excluded.slow_mode_seconds,
                    welcome_message = excluded.welcome_message
            """, (
                channel.lower(),
                request.form.get("enabled") == "on",
                int(request.form.get("auto_detect_threshold", 5)),
                int(request.form.get("duration_minutes", 5)),
                request.form.get("follower_only") == "on",
                int(request.form.get("follower_age_minutes", 10)),
                request.form.get("slow_mode") == "on",
                int(request.form.get("slow_mode_seconds", 30)),
                request.form.get("welcome_message", "").strip()
            ))
            conn.commit()
            flash("Raid protection settings saved!", "success")
        
        elif action == "enable_protection":
            # This would trigger the bot to enable protection
            # For now, just show a message
            flash("Raid protection manually enabled! (Bot integration pending)", "warning")
        
        elif action == "disable_protection":
            flash("Raid protection manually disabled! (Bot integration pending)", "info")
        
        conn.close()
        return redirect(url_for("raid_settings"))
    
    # GET request - load settings
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Ensure table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_settings (
            channel TEXT PRIMARY KEY,
            enabled BOOLEAN DEFAULT TRUE,
            auto_detect_threshold INTEGER DEFAULT 5,
            duration_minutes INTEGER DEFAULT 5,
            follower_only BOOLEAN DEFAULT TRUE,
            follower_age_minutes INTEGER DEFAULT 10,
            slow_mode BOOLEAN DEFAULT TRUE,
            slow_mode_seconds INTEGER DEFAULT 30,
            welcome_message TEXT DEFAULT 'Welcome raiders! Chat is in protected mode for a few minutes. 🛡️'
        )
    """)
    conn.commit()
    
    # Get settings
    cursor.execute("SELECT * FROM raid_settings WHERE channel = ?", (channel.lower(),))
    row = cursor.fetchone()
    settings = dict(row) if row else {
        "enabled": True,
        "auto_detect_threshold": 5,
        "duration_minutes": 5,
        "follower_only": True,
        "follower_age_minutes": 10,
        "slow_mode": True,
        "slow_mode_seconds": 30,
        "welcome_message": "Welcome raiders! Chat is in protected mode for a few minutes. 🛡️"
    }
    
    conn.close()
    
    return render_template("raid_settings.html", settings=settings)



# ==================== Shoutout Settings ====================

@app.route("/shoutout-settings", methods=["GET", "POST"])
@login_required
def shoutout_settings():
    """Shoutout settings page."""
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip().lower()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Ensure tables exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS shoutout_settings (
            channel TEXT PRIMARY KEY,
            enabled BOOLEAN DEFAULT TRUE,
            auto_raid_shoutout BOOLEAN DEFAULT TRUE,
            message TEXT DEFAULT 'Go check out @$(user) at twitch.tv/$(user) - They were last playing $(game)! 💜',
            cooldown_seconds INTEGER DEFAULT 300
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS first_chatter_settings (
            channel TEXT PRIMARY KEY,
            enabled BOOLEAN DEFAULT TRUE,
            message TEXT DEFAULT 'Welcome to the stream @$(user)! 👋'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS shoutout_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            target_user TEXT NOT NULL,
            shouted_by TEXT NOT NULL,
            shouted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            was_raid BOOLEAN DEFAULT FALSE
        )
    """)
    conn.commit()
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "save_shoutout_settings":
            cursor.execute("""
                INSERT INTO shoutout_settings (channel, enabled, auto_raid_shoutout, message, cooldown_seconds)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(channel) DO UPDATE SET
                    enabled = excluded.enabled,
                    auto_raid_shoutout = excluded.auto_raid_shoutout,
                    message = excluded.message,
                    cooldown_seconds = excluded.cooldown_seconds
            """, (
                channel,
                request.form.get("enabled") == "on",
                request.form.get("auto_raid_shoutout") == "on",
                request.form.get("message", "Go check out @$(user) at twitch.tv/$(user) - They were last playing $(game)! 💜").strip(),
                int(request.form.get("cooldown_seconds", 300))
            ))
            conn.commit()
            flash("Shoutout settings saved!", "success")
        
        elif action == "save_welcome_settings":
            cursor.execute("""
                INSERT INTO first_chatter_settings (channel, enabled, message)
                VALUES (?, ?, ?)
                ON CONFLICT(channel) DO UPDATE SET
                    enabled = excluded.enabled,
                    message = excluded.message
            """, (
                channel,
                request.form.get("welcome_enabled") == "on",
                request.form.get("welcome_message", "Welcome to the stream @$(user)! 👋").strip()
            ))
            conn.commit()
            flash("Welcome message settings saved!", "success")
        
        conn.close()
        return redirect(url_for("shoutout_settings"))
    
    # GET request - load settings
    cursor.execute("SELECT * FROM shoutout_settings WHERE channel = ?", (channel,))
    row = cursor.fetchone()
    settings = dict(row) if row else {
        "enabled": True,
        "auto_raid_shoutout": True,
        "message": "Go check out @$(user) at twitch.tv/$(user) - They were last playing $(game)! 💜",
        "cooldown_seconds": 300
    }
    
    cursor.execute("SELECT * FROM first_chatter_settings WHERE channel = ?", (channel,))
    row = cursor.fetchone()
    welcome_settings = dict(row) if row else {
        "enabled": True,
        "message": "Welcome to the stream @$(user)! 👋"
    }
    
    conn.close()
    
    return render_template("shoutout_settings.html", settings=settings, welcome_settings=welcome_settings)


@app.route("/api/shoutout/settings", methods=["POST"])
@login_required
def api_shoutout_settings():
    """API endpoint to update shoutout settings."""
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip().lower()
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"})
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO shoutout_settings (channel, enabled, auto_raid_shoutout, message, cooldown_seconds)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(channel) DO UPDATE SET
                enabled = excluded.enabled,
                auto_raid_shoutout = excluded.auto_raid_shoutout,
                message = excluded.message,
                cooldown_seconds = excluded.cooldown_seconds
        """, (
            channel,
            data.get("enabled", True),
            data.get("auto_raid_shoutout", True),
            data.get("message", "Go check out @$(user) at twitch.tv/$(user) - They were last playing $(game)! 💜"),
            int(data.get("cooldown_seconds", 300))
        ))
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "message": "Shoutout settings saved"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/shoutout/welcome-settings", methods=["POST"])
@login_required
def api_shoutout_welcome_settings():
    """API endpoint to update welcome message settings."""
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip().lower()
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"})
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO first_chatter_settings (channel, enabled, message)
            VALUES (?, ?, ?)
            ON CONFLICT(channel) DO UPDATE SET
                enabled = excluded.enabled,
                message = excluded.message
        """, (
            channel,
            data.get("enabled", True),
            data.get("message", "Welcome to the stream @$(user)! 👋")
        ))
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "message": "Welcome settings saved"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/shoutout/history", methods=["GET"])
@login_required
def api_shoutout_history():
    """API endpoint to get shoutout history."""
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip().lower()
    
    try:
        limit = request.args.get("limit", 100, type=int)
        raid_only = request.args.get("raid_only", "false").lower() == "true"
        manual_only = request.args.get("manual_only", "false").lower() == "true"
        user_filter = request.args.get("user", "").strip().lower()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Build query based on filters
        query = "SELECT * FROM shoutout_history WHERE channel = ?"
        params = [channel]
        
        if raid_only:
            query += " AND was_raid = TRUE"
        elif manual_only:
            query += " AND was_raid = FALSE"
        
        if user_filter:
            query += " AND (LOWER(target_user) LIKE ? OR LOWER(shouted_by) LIKE ?)"
            params.extend([f"%{user_filter}%", f"%{user_filter}%"])
        
        query += " ORDER BY shouted_at DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        history = []
        for row in rows:
            history.append({
                "id": row["id"],
                "target_user": row["target_user"],
                "shouted_by": row["shouted_by"],
                "shouted_at": row["shouted_at"],
                "was_raid": bool(row["was_raid"])
            })
        
        conn.close()
        
        return jsonify({"success": True, "history": history})
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "history": []})


@app.route("/api/shoutout/send", methods=["POST"])
@login_required
def api_shoutout_send():
    """API endpoint to trigger a manual shoutout."""
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip().lower()
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"})
        
        username = data.get("username", "").strip()
        if not username:
            return jsonify({"success": False, "error": "Username is required"})
        
        # Remove @ if present
        username = username.lstrip("@")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Record the shoutout in history
        cursor.execute("""
            INSERT INTO shoutout_history (channel, target_user, shouted_by, was_raid)
            VALUES (?, ?, ?, FALSE)
        """, (channel, username, "Dashboard"))
        conn.commit()
        
        # Try to trigger the bot to send the shoutout
        # This uses a command queue table that the bot monitors
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_command_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                command TEXT NOT NULL,
                args TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed BOOLEAN DEFAULT FALSE
            )
        """)
        
        cursor.execute("""
            INSERT INTO bot_command_queue (channel, command, args)
            VALUES (?, 'shoutout', ?)
        """, (channel, username))
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True, 
            "message": f"Shoutout queued for @{username}",
            "note": "The bot will send the shoutout message to chat."
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ==================== Predictions Routes ====================

@app.route("/predictions")
@login_required
def predictions_page():
    """Predictions management page."""
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Ensure tables exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            question TEXT NOT NULL,
            outcomes TEXT NOT NULL,
            started_by TEXT NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            locked_at TIMESTAMP,
            resolved_at TIMESTAMP,
            winning_outcome INTEGER,
            status TEXT DEFAULT 'open',
            prediction_type TEXT DEFAULT 'chat',
            twitch_prediction_id TEXT,
            auto_lock_at TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prediction_bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prediction_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            outcome_index INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            bet_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            payout INTEGER DEFAULT 0,
            UNIQUE(prediction_id, user_id),
            FOREIGN KEY (prediction_id) REFERENCES predictions(id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prediction_settings (
            channel TEXT PRIMARY KEY,
            prediction_window INTEGER DEFAULT 120,
            min_bet INTEGER DEFAULT 10,
            max_bet INTEGER DEFAULT 10000,
            enabled BOOLEAN DEFAULT TRUE
        )
    """)
    conn.commit()
    
    # Get active prediction
    cursor.execute("""
        SELECT * FROM predictions 
        WHERE channel = ? AND status IN ('open', 'locked')
        ORDER BY started_at DESC LIMIT 1
    """, (channel.lower(),))
    active_row = cursor.fetchone()
    active_prediction = dict(active_row) if active_row else None
    
    outcomes = []
    outcome_stats = {}
    odds = {}
    total_pool = 0
    total_bets = 0
    
    if active_prediction:
        outcomes = json.loads(active_prediction["outcomes"])
        
        # Get bet stats per outcome
        cursor.execute("""
            SELECT outcome_index, COUNT(*) as bet_count, SUM(amount) as total_amount
            FROM prediction_bets
            WHERE prediction_id = ?
            GROUP BY outcome_index
        """, (active_prediction["id"],))
        
        outcome_stats = {i: {"bets": 0, "amount": 0} for i in range(len(outcomes))}
        
        for row in cursor.fetchall():
            idx = row["outcome_index"]
            outcome_stats[idx] = {
                "bets": row["bet_count"],
                "amount": row["total_amount"] or 0
            }
            total_pool += row["total_amount"] or 0
            total_bets += row["bet_count"]
        
        # Calculate odds
        for i in range(len(outcomes)):
            if outcome_stats[i]["amount"] > 0:
                odds[i] = total_pool / outcome_stats[i]["amount"]
            else:
                odds[i] = 0
    
    # Get prediction history
    cursor.execute("""
        SELECT p.*,
               (SELECT SUM(amount) FROM prediction_bets WHERE prediction_id = p.id) as total_pool,
               (SELECT COUNT(*) FROM prediction_bets WHERE prediction_id = p.id) as total_bets
        FROM predictions p
        WHERE p.channel = ? AND p.status IN ('resolved', 'cancelled')
        ORDER BY p.started_at DESC LIMIT 50
    """, (channel.lower(),))
    
    history = []
    for row in cursor.fetchall():
        pred = dict(row)
        pred["outcomes"] = json.loads(pred["outcomes"])
        history.append(pred)
    
    # Get all-time stats
    cursor.execute("""
        SELECT SUM(amount) as total_wagered, COUNT(DISTINCT user_id) as unique_bettors
        FROM prediction_bets pb
        JOIN predictions p ON pb.prediction_id = p.id
        WHERE p.channel = ?
    """, (channel.lower(),))
    stats_row = cursor.fetchone()
    total_points_wagered = stats_row["total_wagered"] or 0 if stats_row else 0
    total_unique_bettors = stats_row["unique_bettors"] or 0 if stats_row else 0
    
    # Get settings
    cursor.execute("SELECT * FROM prediction_settings WHERE channel = ?", (channel.lower(),))
    settings_row = cursor.fetchone()
    settings = dict(settings_row) if settings_row else {
        "enabled": True,
        "prediction_window": 120,
        "min_bet": 10,
        "max_bet": 10000
    }
    
    conn.close()
    
    return render_template("predictions.html",
                          active_prediction=active_prediction,
                          outcomes=outcomes,
                          outcome_stats=outcome_stats,
                          odds=odds,
                          total_pool=total_pool,
                          total_bets=total_bets,
                          history=history,
                          total_points_wagered=total_points_wagered,
                          total_unique_bettors=total_unique_bettors,
                          settings=settings)


@app.route("/api/predictions/create", methods=["POST"])
@login_required
def create_prediction():
    """Create a new prediction."""
    try:
        channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
        data = request.get_json()
        
        question = data.get("question", "").strip()
        outcomes = data.get("outcomes", [])
        prediction_window = int(data.get("prediction_window", 120))
        
        if not question:
            return jsonify({"success": False, "error": "Question is required"}), 400
        
        if len(outcomes) < 2:
            return jsonify({"success": False, "error": "At least 2 outcomes required"}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check for existing active prediction
        cursor.execute("""
            SELECT id FROM predictions 
            WHERE channel = ? AND status IN ('open', 'locked')
        """, (channel.lower(),))
        
        if cursor.fetchone():
            conn.close()
            return jsonify({"success": False, "error": "A prediction is already active"}), 400
        
        # Calculate auto-lock time
        auto_lock_at = None
        if prediction_window > 0:
            auto_lock_at = (datetime.now() + timedelta(seconds=prediction_window)).isoformat()
        
        # Create prediction
        cursor.execute("""
            INSERT INTO predictions 
            (channel, question, outcomes, started_by, auto_lock_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            channel.lower(),
            question,
            json.dumps(outcomes),
            "dashboard",
            auto_lock_at
        ))
        
        prediction_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        # Announce in chat
        outcome_list = " | ".join(f"[{i+1}] {o}" for i, o in enumerate(outcomes))
        time_msg = ""
        if prediction_window > 0:
            mins = prediction_window // 60
            secs = prediction_window % 60
            time_msg = f" Betting closes in {mins}m {secs}s!" if mins else f" Betting closes in {secs}s!"
        chat_msg = f"🔮 PREDICTION: {question} | {outcome_list} | Use !bet <#> <amount> to bet!{time_msg}"
        queue_chat_message(channel, chat_msg)
        
        return jsonify({
            "success": True, 
            "prediction_id": prediction_id,
            "message": "Prediction created successfully"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/predictions/<int:prediction_id>/lock", methods=["POST"])
@login_required
def lock_prediction(prediction_id):
    """Lock betting on a prediction."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE predictions 
            SET status = 'locked', locked_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'open'
        """, (prediction_id,))
        
        if cursor.rowcount == 0:
            conn.close()
            return jsonify({"success": False, "error": "Prediction not found or already locked"}), 404
        
        # Get channel for chat message
        cursor.execute("SELECT channel FROM predictions WHERE id = ?", (prediction_id,))
        row = cursor.fetchone()
        channel = row["channel"] if row else ""
        
        conn.commit()
        conn.close()
        
        # Announce in chat
        if channel:
            queue_chat_message(channel, "🔒 Prediction LOCKED! No more bets accepted.")
        
        return jsonify({"success": True, "message": "Prediction locked"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/predictions/<int:prediction_id>/resolve", methods=["POST"])
@login_required
def resolve_prediction(prediction_id):
    """Resolve a prediction with a winning outcome."""
    try:
        data = request.get_json()
        winning_outcome = data.get("winning_outcome")
        
        if winning_outcome is None:
            return jsonify({"success": False, "error": "Winning outcome required"}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get prediction
        cursor.execute("SELECT * FROM predictions WHERE id = ?", (prediction_id,))
        prediction = cursor.fetchone()
        
        if not prediction:
            conn.close()
            return jsonify({"success": False, "error": "Prediction not found"}), 404
        
        prediction = dict(prediction)
        outcomes = json.loads(prediction["outcomes"])
        
        if winning_outcome < 0 or winning_outcome >= len(outcomes):
            conn.close()
            return jsonify({"success": False, "error": "Invalid outcome index"}), 400
        
        # Lock if still open
        if prediction["status"] == "open":
            cursor.execute("""
                UPDATE predictions 
                SET status = 'locked', locked_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (prediction_id,))
        
        # Get all bets
        cursor.execute("""
            SELECT * FROM prediction_bets WHERE prediction_id = ?
        """, (prediction_id,))
        all_bets = [dict(row) for row in cursor.fetchall()]
        
        # Calculate payouts
        total_pool = sum(bet["amount"] for bet in all_bets)
        winner_pool = sum(bet["amount"] for bet in all_bets if bet["outcome_index"] == winning_outcome)
        
        winners = []
        if winner_pool > 0:
            payout_ratio = total_pool / winner_pool
            
            for bet in all_bets:
                if bet["outcome_index"] == winning_outcome:
                    payout = int(bet["amount"] * payout_ratio)
                    
                    # Update bet record
                    cursor.execute("""
                        UPDATE prediction_bets SET payout = ? WHERE id = ?
                    """, (payout, bet["id"]))
                    
                    # Award points to winner
                    cursor.execute("""
                        UPDATE user_loyalty 
                        SET points = points + ?
                        WHERE user_id = ? AND channel = ?
                    """, (payout, bet["user_id"], prediction["channel"]))
                    
                    winners.append({
                        "username": bet["username"],
                        "bet": bet["amount"],
                        "payout": payout
                    })
        
        # Mark prediction as resolved
        cursor.execute("""
            UPDATE predictions 
            SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP, winning_outcome = ?
            WHERE id = ?
        """, (winning_outcome, prediction_id))
        
        conn.commit()
        conn.close()
        
        # Announce in chat
        winning_text = outcomes[winning_outcome]
        if winners:
            total_payout = sum(w["payout"] for w in winners)
            top_winners = sorted(winners, key=lambda x: x["payout"], reverse=True)[:3]
            winner_names = ", ".join(f"@{w['username']} (+{w['payout']:,})" for w in top_winners)
            chat_msg = f"🎉 PREDICTION RESOLVED! Winner: [{winning_outcome+1}] {winning_text} | Total payout: {total_payout:,} points | Top winners: {winner_names}"
        else:
            chat_msg = f"🎉 PREDICTION RESOLVED! Winner: [{winning_outcome+1}] {winning_text} | No winning bets."
        queue_chat_message(prediction["channel"], chat_msg)
        
        return jsonify({
            "success": True,
            "message": f"Prediction resolved. {len(winners)} winner(s).",
            "winners": winners,
            "total_pool": total_pool
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/predictions/<int:prediction_id>/cancel", methods=["POST"])
@login_required
def cancel_prediction(prediction_id):
    """Cancel a prediction and refund all bets."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get prediction
        cursor.execute("SELECT channel FROM predictions WHERE id = ?", (prediction_id,))
        prediction = cursor.fetchone()
        
        if not prediction:
            conn.close()
            return jsonify({"success": False, "error": "Prediction not found"}), 404
        
        channel = prediction["channel"]
        
        # Get all bets for refund
        cursor.execute("""
            SELECT * FROM prediction_bets WHERE prediction_id = ?
        """, (prediction_id,))
        bets = cursor.fetchall()
        
        # Refund each bet
        refund_count = 0
        for bet in bets:
            cursor.execute("""
                UPDATE user_loyalty 
                SET points = points + ?
                WHERE user_id = ? AND channel = ?
            """, (bet["amount"], bet["user_id"], channel))
            refund_count += 1
        
        # Mark prediction as cancelled
        cursor.execute("""
            UPDATE predictions 
            SET status = 'cancelled', resolved_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (prediction_id,))
        
        conn.commit()
        conn.close()
        
        # Announce in chat
        queue_chat_message(channel, f"❌ Prediction CANCELLED! {refund_count} bet(s) have been refunded.")
        
        return jsonify({
            "success": True,
            "message": f"Prediction cancelled. {refund_count} bet(s) refunded.",
            "refunds": refund_count
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/predictions/active")
@login_required
def get_active_prediction():
    """Get the active prediction with stats (for real-time updates)."""
    try:
        channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM predictions 
            WHERE channel = ? AND status IN ('open', 'locked')
            ORDER BY started_at DESC LIMIT 1
        """, (channel.lower(),))
        
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return jsonify({"success": True, "prediction": None})
        
        prediction = dict(row)
        outcomes = json.loads(prediction["outcomes"])
        
        # Get bet stats
        cursor.execute("""
            SELECT outcome_index, COUNT(*) as bet_count, SUM(amount) as total_amount
            FROM prediction_bets
            WHERE prediction_id = ?
            GROUP BY outcome_index
        """, (prediction["id"],))
        
        outcome_stats = {i: {"bets": 0, "amount": 0} for i in range(len(outcomes))}
        total_pool = 0
        total_bets = 0
        
        for stat_row in cursor.fetchall():
            idx = stat_row["outcome_index"]
            outcome_stats[idx] = {
                "bets": stat_row["bet_count"],
                "amount": stat_row["total_amount"] or 0
            }
            total_pool += stat_row["total_amount"] or 0
            total_bets += stat_row["bet_count"]
        
        # Calculate odds
        odds = {}
        for i in range(len(outcomes)):
            if outcome_stats[i]["amount"] > 0:
                odds[i] = total_pool / outcome_stats[i]["amount"]
            else:
                odds[i] = 0
        
        conn.close()
        
        return jsonify({
            "success": True,
            "prediction": prediction,
            "stats": {
                "outcome_stats": outcome_stats,
                "odds": odds,
                "total_pool": total_pool,
                "total_bets": total_bets
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/predictions/history")
@login_required
def get_prediction_history():
    """Get prediction history."""
    try:
        channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
        limit = request.args.get("limit", 50, type=int)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT p.*,
                   (SELECT SUM(amount) FROM prediction_bets WHERE prediction_id = p.id) as total_pool,
                   (SELECT COUNT(*) FROM prediction_bets WHERE prediction_id = p.id) as total_bets
            FROM predictions p
            WHERE p.channel = ? AND p.status IN ('resolved', 'cancelled')
            ORDER BY p.started_at DESC LIMIT ?
        """, (channel.lower(), limit))
        
        history = []
        for row in cursor.fetchall():
            pred = dict(row)
            pred["outcomes"] = json.loads(pred["outcomes"])
            history.append(pred)
        
        conn.close()
        
        return jsonify({"success": True, "history": history})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/predictions/settings", methods=["POST"])
@login_required
def update_prediction_settings():
    """Update prediction settings."""
    try:
        channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
        data = request.get_json()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Ensure table exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS prediction_settings (
                channel TEXT PRIMARY KEY,
                prediction_window INTEGER DEFAULT 120,
                min_bet INTEGER DEFAULT 10,
                max_bet INTEGER DEFAULT 10000,
                enabled BOOLEAN DEFAULT TRUE
            )
        """)
        
        # Update settings
        cursor.execute("""
            INSERT INTO prediction_settings 
            (channel, enabled, prediction_window, min_bet, max_bet)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(channel) DO UPDATE SET
                enabled = excluded.enabled,
                prediction_window = excluded.prediction_window,
                min_bet = excluded.min_bet,
                max_bet = excluded.max_bet
        """, (
            channel.lower(),
            data.get("enabled", True),
            safe_int(data.get("prediction_window"), default=120, min_val=30, max_val=600),
            safe_int(data.get("min_bet"), default=10, min_val=1, max_val=10000),
            safe_int(data.get("max_bet"), default=10000, min_val=10, max_val=1000000)
        ))
        
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "message": "Settings saved"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500




# ==================== POLLS ROUTES ====================

@app.route("/polls")
@login_required
def polls_page():
    """Polls management page."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip().lower()
    
    # Ensure tables exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS polls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            question TEXT NOT NULL,
            options TEXT NOT NULL,
            started_by TEXT NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP,
            duration_seconds INTEGER DEFAULT 60,
            status TEXT DEFAULT 'active'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS poll_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            poll_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            option_index INTEGER NOT NULL,
            voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(poll_id, user_id),
            FOREIGN KEY (poll_id) REFERENCES polls(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS poll_settings (
            channel TEXT PRIMARY KEY,
            enabled BOOLEAN DEFAULT TRUE,
            default_duration INTEGER DEFAULT 60
        )
    """)
    conn.commit()
    
    # Get active poll
    cursor.execute("""
        SELECT * FROM polls 
        WHERE channel = ? AND status = 'active'
        ORDER BY started_at DESC LIMIT 1
    """, (channel,))
    active_poll = cursor.fetchone()
    
    # Get poll history
    cursor.execute("""
        SELECT * FROM polls 
        WHERE channel = ?
        ORDER BY started_at DESC LIMIT 20
    """, (channel,))
    poll_history = cursor.fetchall()
    
    # Get vote counts for active poll
    votes_by_option = {}
    if active_poll:
        cursor.execute("""
            SELECT option_index, COUNT(*) as count
            FROM poll_votes WHERE poll_id = ?
            GROUP BY option_index
        """, (active_poll["id"],))
        for row in cursor.fetchall():
            votes_by_option[row["option_index"]] = row["count"]
    
    # Get settings
    cursor.execute("SELECT * FROM poll_settings WHERE channel = ?", (channel,))
    settings = cursor.fetchone()
    
    conn.close()
    
    return render_template("polls.html",
        active_poll=active_poll,
        poll_history=poll_history,
        votes_by_option=votes_by_option,
        settings=settings,
        channel=channel
    )

@app.route("/api/polls/active")
@login_required
def api_polls_active():
    """Get active poll data."""
    conn = get_db_connection()
    cursor = conn.cursor()
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip().lower()
    
    cursor.execute("""
        SELECT * FROM polls 
        WHERE channel = ? AND status = 'active'
        ORDER BY started_at DESC LIMIT 1
    """, (channel,))
    poll = cursor.fetchone()
    
    if not poll:
        conn.close()
        return jsonify({"active": False})
    
    cursor.execute("""
        SELECT option_index, COUNT(*) as count
        FROM poll_votes WHERE poll_id = ?
        GROUP BY option_index
    """, (poll["id"],))
    votes = {row["option_index"]: row["count"] for row in cursor.fetchall()}
    
    conn.close()
    
    options = json.loads(poll["options"]) if poll["options"] else []
    
    return jsonify({
        "active": True,
        "id": poll["id"],
        "question": poll["question"],
        "options": options,
        "votes": votes,
        "total_votes": sum(votes.values()),
        "started_at": poll["started_at"],
        "duration": poll["duration_seconds"],
        "status": poll["status"]
    })

@app.route("/api/polls/create", methods=["POST"])
@login_required
def api_polls_create():
    """Create a new poll."""
    conn = get_db_connection()
    cursor = conn.cursor()
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip().lower()
    
    data = request.get_json()
    question = data.get("question", "").strip()
    options = data.get("options", [])
    duration = safe_int(data.get("duration"), default=60, min_val=10, max_val=600)
    
    if not question or len(options) < 2:
        return jsonify({"success": False, "error": "Invalid poll data"}), 400
    
    cursor.execute("SELECT id FROM polls WHERE channel = ? AND status = 'active'", (channel,))
    if cursor.fetchone():
        conn.close()
        return jsonify({"success": False, "error": "A poll is already active"}), 400
    
    cursor.execute("""
        INSERT INTO polls (channel, question, options, started_by, duration_seconds, status)
        VALUES (?, ?, ?, ?, ?, 'active')
    """, (channel, question, json.dumps(options), "dashboard", duration))
    
    conn.commit()
    poll_id = cursor.lastrowid
    conn.close()
    
    # Announce in chat
    option_list = " | ".join(f"[{i+1}] {o}" for i, o in enumerate(options))
    queue_chat_message(channel, f"📊 POLL: {question} | {option_list} | Vote with !vote <#>")
    
    return jsonify({"success": True, "poll_id": poll_id})

@app.route("/api/polls/<int:poll_id>/end", methods=["POST"])
@login_required
def api_polls_end(poll_id):
    """End a poll."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT channel, question FROM polls WHERE id = ?", (poll_id,))
    poll = cursor.fetchone()
    
    cursor.execute("""
        UPDATE polls SET status = 'ended', ended_at = CURRENT_TIMESTAMP
        WHERE id = ? AND status = 'active'
    """, (poll_id,))
    
    conn.commit()
    conn.close()
    
    if poll:
        queue_chat_message(poll["channel"], f"📊 Poll ended: {poll['question']}")
    
    return jsonify({"success": True})

@app.route("/api/polls/<int:poll_id>/cancel", methods=["POST"])
@login_required
def api_polls_cancel(poll_id):
    """Cancel a poll."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT channel FROM polls WHERE id = ?", (poll_id,))
    poll = cursor.fetchone()
    
    cursor.execute("""
        UPDATE polls SET status = 'cancelled', ended_at = CURRENT_TIMESTAMP
        WHERE id = ? AND status = 'active'
    """, (poll_id,))
    
    conn.commit()
    conn.close()
    
    if poll:
        queue_chat_message(poll["channel"], "📊 Poll cancelled.")
    
    return jsonify({"success": True})

@app.route("/api/polls/settings", methods=["POST"])
@login_required
def api_polls_settings():
    """Update poll settings."""
    conn = get_db_connection()
    cursor = conn.cursor()
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip().lower()
    
    data = request.get_json()
    enabled = data.get("enabled", True)
    default_duration = safe_int(data.get("default_duration"), default=60, min_val=10, max_val=600)
    
    cursor.execute("""
        INSERT INTO poll_settings (channel, enabled, default_duration)
        VALUES (?, ?, ?)
        ON CONFLICT(channel) DO UPDATE SET enabled = ?, default_duration = ?
    """, (channel, enabled, default_duration, enabled, default_duration))
    
    conn.commit()
    conn.close()
    
    return jsonify({"success": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
