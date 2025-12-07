# EngelGuard Project Status

**Last Updated:** December 7, 2024  
**Version:** 1.0.0  
**Status:** Phase 1 Complete ✅

---

## Quick Links

- **GitHub:** https://github.com/engelswtf/engelguard
- **Bot Location:** LXC Container CT 101 at `/opt/twitch-bot/`
- **Dashboard:** http://10.10.10.101:5000
- **Dashboard Password:** Set in `/opt/twitch-bot/.env` as `DASHBOARD_PASSWORD`

---

## Current Architecture

### Container Details
| Property | Value |
|----------|-------|
| CT ID | 101 |
| Hostname | twitch-bot |
| IP Address | 10.10.10.101 |
| OS | Debian 12 |
| Storage | nvme1-lvm |

### Services
| Service | Port | Status |
|---------|------|--------|
| `twitch-bot.service` | N/A | Running |
| `twitch-dashboard.service` | 5000 | Running |

### File Locations
```
Container (/opt/twitch-bot/):
├── src/bot/           # Bot source code
├── dashboard/         # Flask web dashboard
├── data/              # SQLite databases
│   └── automod.db     # Main database
├── venv/              # Python virtual environment
├── .env               # Configuration (secrets)
└── run.py             # Entry point

Host (/root/twitch-bot/):
├── [Same structure]   # Git repository
└── .git/              # Git data
```

---

## Phase 1 Completed Features

### ✅ Core Bot
- TwitchIO 2.x integration
- Modular cog system
- Environment-based configuration
- Secret filtering in logs
- Graceful shutdown handling

### ✅ Cogs Loaded
1. **admin.py** - Bot management commands
2. **fun.py** - Entertainment commands (dice, 8ball, etc.)
3. **moderation.py** - Manual mod commands
4. **info.py** - Information commands
5. **clips.py** - Stream integration (clips, title, game)
6. **automod.py** - Automatic moderation with strike system
7. **customcmds.py** - Custom command system with variables
8. **timers.py** - Scheduled messages
9. **loyalty.py** - Points/watch time system (toggleable)
10. **nuke.py** - Mass moderation tool

### ✅ Auto-Moderation
- Spam detection with pattern matching
- Lookalike character detection
- Configurable filters (caps, symbols, emotes, links, length)
- Strike system (5 strikes: warn → timeout → ban)
- Subscriber/VIP protection
- Whitelist system
- Permit system for temporary link allowance

### ✅ Custom Commands
- 20+ variables supported
- Permission levels (everyone → owner)
- User and global cooldowns
- Aliases
- Dashboard management only (as requested)

### ✅ Timers
- Interval-based (5-120 minutes)
- Chat activity requirements
- Online-only mode
- Variable support

### ✅ Loyalty System
- Watch time tracking
- Points for watching/chatting
- Sub/VIP multipliers
- Leaderboards
- **Disabled by default** - toggle with `!loyalty on`

### ✅ Nuke Command
- Pattern-based mass moderation
- Safety features (preview, limits, excludes)
- Full audit logging

### ✅ Web Dashboard
- Modern dark theme
- Pages: Dashboard, Settings, Commands, Timers, Filters, Mod Log, Users, Strikes, Loyalty, Credentials
- Password protected
- Mobile responsive

---

## Database Schema

Located at `/opt/twitch-bot/data/automod.db`

### Tables
```sql
-- User tracking
users (user_id, username, trust_score, first_seen, message_count, warnings_count, is_whitelisted, last_message)

-- Moderation logs
mod_actions (id, timestamp, user_id, username, action, reason, spam_score, message_content, channel)

-- Permits
permits (user_id, granted_by, expires_at)

-- Custom commands
custom_commands (id, name, response, created_by, created_at, updated_at, use_count, cooldown_user, cooldown_global, permission_level, enabled, aliases)

-- Command aliases
command_aliases (alias, command_name)

-- Timers
timers (id, name, message, interval_minutes, chat_lines_required, online_only, enabled, last_triggered, created_by, created_at)

-- Strike system
user_strikes (id, user_id, username, strike_count, last_strike, last_reason, expires_at)
strike_history (id, user_id, username, strike_number, reason, action_taken, timestamp, moderator, channel)

-- Loyalty
loyalty_settings (channel, enabled, points_name, points_per_minute, points_per_message, bonus_sub_multiplier, bonus_vip_multiplier)
user_loyalty (id, user_id, username, channel, points, watch_time_minutes, message_count, last_seen, first_seen)

-- Nuke logs
nuke_log (id, timestamp, moderator, channel, pattern, action, duration, users_affected, options)

-- Filter settings
filter_settings (channel, caps_enabled, caps_percent, caps_min_length, emotes_enabled, emotes_max, symbols_enabled, symbols_percent, links_enabled, links_whitelist, length_enabled, length_max)

-- Recent messages (for nuke)
recent_messages (id, timestamp, channel, user_id, username, message, is_deleted)
```

---

## Phase 2 TODO

### 📝 Quotes System
- `!addquote <text>` - Add a quote (mod)
- `!quote [id]` - Get random or specific quote
- `!delquote <id>` - Delete quote (mod)
- `!quotes` - List quotes or count
- Store: quote text, author, added_by, timestamp, game

### 🎉 Giveaway System
- `!giveaway start <keyword> [duration]` - Start giveaway
- `!giveaway end` - End and pick winner
- `!giveaway reroll` - Pick new winner
- `!giveaway cancel` - Cancel giveaway
- Features:
  - Keyword entry
  - Eligibility (follower, sub, points minimum)
  - Sub luck multiplier
  - Multiple winners option
  - Announce winner
  - Dashboard management

### 🎵 Song Requests
- `!sr <youtube url or search>` - Request a song
- `!queue` - View queue
- `!skip` - Skip current (mod)
- `!volume <0-100>` - Set volume (mod)
- `!currentsong` - Show now playing
- `!wrongsong` - Remove your last request
- Features:
  - YouTube integration
  - Queue management
  - User request limits
  - Duration limits
  - Blacklist songs/channels
  - Dashboard player

---

## Commands Reference

### Access Commands
```bash
# SSH to Proxmox host, then:
pct exec 101 -- <command>

# Or enter container:
pct enter 101
```

### Service Management
```bash
# Bot
pct exec 101 -- systemctl status twitch-bot
pct exec 101 -- systemctl restart twitch-bot
pct exec 101 -- journalctl -u twitch-bot -f

# Dashboard
pct exec 101 -- systemctl status twitch-dashboard
pct exec 101 -- systemctl restart twitch-dashboard
```

### Git (from host)
```bash
cd /root/twitch-bot
git add -A
git commit -m "message"
git push
```

### Sync Code to Container
```bash
# From host to container
pct exec 101 -- bash -c "cat > /opt/twitch-bot/path/file.py" < /root/twitch-bot/path/file.py

# Or use tar for multiple files
tar -czf - -C /root/twitch-bot src | pct exec 101 -- tar -xzf - -C /opt/twitch-bot/
```

---

## Configuration

### Environment Variables (.env)
```env
# Required
TWITCH_CLIENT_ID=xxx
TWITCH_CLIENT_SECRET=xxx
TWITCH_OAUTH_TOKEN=oauth:xxx
TWITCH_BOT_NICK=engelguard
TWITCH_CHANNELS=ogengels
BOT_OWNER=ogengels

# Dashboard
DASHBOARD_PASSWORD=xxx

# Optional
BOT_PREFIX=!
LOG_LEVEL=INFO
LOYALTY_ENABLED=false
STRIKE_EXPIRE_DAYS=30
STRIKE_MAX_BEFORE_BAN=5
```

---

## Known Issues / Notes

1. **Bot shutdown timeout** - Graceful shutdown can take up to 90s; systemd will SIGKILL after timeout
2. **Dashboard uses Flask dev server** - Consider gunicorn for production
3. **No HTTPS on dashboard** - Add reverse proxy with SSL for security
4. **Loyalty system disabled by default** - Enable with `!loyalty on`

---

## Tech Stack

- **Python 3.11+**
- **TwitchIO 2.x** - Twitch IRC/API
- **Flask 3.x** - Web dashboard
- **SQLite** - Database
- **Systemd** - Service management

---

## Contact

- **GitHub:** https://github.com/engelswtf
- **Repository:** https://github.com/engelswtf/engelguard

---

*This document should be updated after each development session.*
