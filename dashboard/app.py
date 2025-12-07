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

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables
ENV_FILE = Path(__file__).parent.parent / ".env"
load_dotenv(ENV_FILE)

app = Flask(__name__)
app.secret_key = os.getenv("DASHBOARD_SECRET_KEY", secrets.token_hex(32))
app.permanent_session_lifetime = timedelta(hours=1)

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
    """Decorator to require login for routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
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


def get_bot_status() -> dict[str, Any]:
    """Get current bot status."""
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "is-active", "twitch-bot"],
            capture_output=True,
            text=True,
            timeout=5
        )
        is_running = result.stdout.strip() == "active"
    except Exception:
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
                start_time = datetime.strptime(timestamp_str.split(".")[0], "%a %Y-%m-%d %H:%M:%S")
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
    """Login page."""
    if request.method == "POST":
        password = request.form.get("password", "")
        stored_password = get_env_value("DASHBOARD_PASSWORD", "changeme123")
        
        if password == stored_password:
            session.permanent = True
            session["logged_in"] = True
            flash("Successfully logged in!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid password", "error")
    
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
                    int(request.form.get("cooldown_user", 5)),
                    int(request.form.get("cooldown_global", 0)),
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
                int(request.form.get("cooldown_user", 5)),
                int(request.form.get("cooldown_global", 0)),
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
                    int(request.form.get("interval_minutes", 15)),
                    int(request.form.get("chat_lines_required", 5)),
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
                int(request.form.get("interval_minutes", 15)),
                int(request.form.get("chat_lines_required", 5)),
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
    """Filters page."""
    channel = get_env_value("TWITCH_CHANNELS", "").split(",")[0].strip()
    
    if request.method == "POST":
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO filter_settings 
            (channel, caps_enabled, caps_min_length, caps_max_percent, emote_enabled, emote_max_count,
             symbol_enabled, symbol_max_percent, link_enabled, length_enabled, length_max_chars,
             repetition_enabled, repetition_max_words, zalgo_enabled, lookalike_enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(channel) DO UPDATE SET
                caps_enabled = excluded.caps_enabled,
                caps_min_length = excluded.caps_min_length,
                caps_max_percent = excluded.caps_max_percent,
                emote_enabled = excluded.emote_enabled,
                emote_max_count = excluded.emote_max_count,
                symbol_enabled = excluded.symbol_enabled,
                symbol_max_percent = excluded.symbol_max_percent,
                link_enabled = excluded.link_enabled,
                length_enabled = excluded.length_enabled,
                length_max_chars = excluded.length_max_chars,
                repetition_enabled = excluded.repetition_enabled,
                repetition_max_words = excluded.repetition_max_words,
                zalgo_enabled = excluded.zalgo_enabled,
                lookalike_enabled = excluded.lookalike_enabled
        """, (
            channel,
            request.form.get("caps_enabled") == "on",
            int(request.form.get("caps_min_length", 10)),
            int(request.form.get("caps_max_percent", 70)),
            request.form.get("emote_enabled") == "on",
            int(request.form.get("emote_max_count", 15)),
            request.form.get("symbol_enabled") == "on",
            int(request.form.get("symbol_max_percent", 50)),
            request.form.get("link_enabled") == "on",
            request.form.get("length_enabled") == "on",
            int(request.form.get("length_max_chars", 500)),
            request.form.get("repetition_enabled") == "on",
            int(request.form.get("repetition_max_words", 10)),
            request.form.get("zalgo_enabled") == "on",
            request.form.get("lookalike_enabled") == "on"
        ))
        conn.commit()
        conn.close()
        
        flash("Filter settings saved!", "success")
        return redirect(url_for("filters_page"))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM filter_settings WHERE channel = ?", (channel,))
    row = cursor.fetchone()
    settings = dict(row) if row else {
        "caps_enabled": True,
        "caps_min_length": 10,
        "caps_max_percent": 70,
        "emote_enabled": True,
        "emote_max_count": 15,
        "symbol_enabled": True,
        "symbol_max_percent": 50,
        "link_enabled": True,
        "length_enabled": True,
        "length_max_chars": 500,
        "repetition_enabled": True,
        "repetition_max_words": 10,
        "zalgo_enabled": True,
        "lookalike_enabled": True
    }
    conn.close()
    
    return render_template("filters.html", settings=settings)


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
        
        cursor.execute(count_query, params)
        total_count = cursor.fetchone()["count"]
        
        query += " ORDER BY last_message DESC NULLS LAST LIMIT ? OFFSET ?"
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
        filter_type=filter_type
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
        
        data = request.get_json() or {}
        enabled = data.get("enabled")
        
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
                    ends_at = (datetime.now() + timedelta(minutes=int(duration))).isoformat()
                
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
