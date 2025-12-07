<div align="center">

# 🛡️ EngelGuard

### A Professional-Grade Twitch Moderation Bot

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![TwitchIO](https://img.shields.io/badge/TwitchIO-2.x-9146FF.svg)](https://github.com/TwitchIO/TwitchIO)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**EngelGuard** is a feature-rich, production-ready Twitch chat bot built with Python and TwitchIO. It rivals top bots like Nightbot, Fossabot, and StreamElements with advanced moderation, custom commands, loyalty systems, and more.

[Features](#-features) • [Installation](#-installation) • [Commands](#-commands) • [Dashboard](#-dashboard) • [Configuration](#-configuration)

</div>

---

## ✨ Features

### 🛡️ Advanced Auto-Moderation
- **Smart Spam Detection** - Catches spam with pattern matching, lookalike detection, and scoring system
- **Lookalike Detection** - Catches evasion attempts like "fr33 f0ll0w3rs" → "free followers"
- **Strike System** - Escalating punishments (warn → timeout → ban) with configurable thresholds
- **Nuke Command** - Mass moderation for raid attacks with safety features
- **Configurable Filters** - Caps, symbols, emotes, links, message length

### 📝 Custom Commands
- **20+ Variables** - `$(user)`, `$(channel)`, `$(random)`, `$(time)`, `$(urlfetch)`, and more
- **Permission Levels** - Everyone, Follower, Subscriber, VIP, Moderator, Owner
- **Cooldowns** - Per-user and global cooldowns
- **Aliases** - Multiple names for the same command
- **Dashboard Management** - Create and edit commands via web UI

### ⏰ Timers & Scheduled Messages
- **Interval-Based** - Post messages every X minutes
- **Chat Activity Requirement** - Only post when chat is active
- **Online-Only Mode** - Only run when stream is live
- **Variable Support** - Use all command variables in timer messages

### 🏆 Loyalty System (Optional)
- **Watch Time Tracking** - Track how long viewers watch
- **Points System** - Earn points for watching and chatting
- **Leaderboards** - Show top viewers
- **Multipliers** - Bonus points for subscribers and VIPs
- **Fully Toggleable** - Enable/disable anytime

### 🎬 Stream Integration
- **Clip Creation** - Create clips via chat command
- **Title/Game Management** - View and change stream info
- **Uptime Display** - Show stream duration
- **Shoutouts** - Give shoutouts to other streamers

### 🌐 Web Dashboard
- **Modern Dark Theme** - Twitch-inspired design
- **Real-Time Stats** - Live bot status and activity
- **Full Management** - Commands, timers, filters, users
- **Mobile Responsive** - Works on all devices
- **Secure Login** - Password-protected access

---

## 📦 Installation

### Prerequisites
- Python 3.11 or higher
- A Twitch account for the bot
- Twitch Developer Application credentials

### Quick Install

```bash
# Clone the repository
git clone https://github.com/engelswtf/engelguard.git
cd engelguard

# Run the installer
sudo ./scripts/install.sh

# Configure your credentials
sudo nano /opt/twitch-bot/.env

# Start the bot
sudo systemctl enable twitch-bot twitch-dashboard
sudo systemctl start twitch-bot twitch-dashboard
```

### Get Twitch Credentials

1. **Client ID & Secret**: [Twitch Developer Console](https://dev.twitch.tv/console/apps)
2. **OAuth Token**: [Twitch Token Generator](https://twitchtokengenerator.com/)
   - Required scopes: `chat:read`, `chat:edit`, `channel:moderate`, `clips:edit`

### Configuration

Edit `/opt/twitch-bot/.env`:

```env
# Required
TWITCH_CLIENT_ID=your_client_id
TWITCH_CLIENT_SECRET=your_client_secret
TWITCH_OAUTH_TOKEN=oauth:your_token
TWITCH_BOT_NICK=your_bot_username
TWITCH_CHANNELS=your_channel
BOT_OWNER=your_twitch_username

# Dashboard
DASHBOARD_PASSWORD=your_secure_password

# Optional
BOT_PREFIX=!
LOG_LEVEL=INFO
```

---

## 🎮 Commands

### Fun Commands
| Command | Description | Example |
|---------|-------------|---------|
| `!dice [sides]` | Roll dice (supports D&D notation) | `!dice 2d6` |
| `!8ball <question>` | Ask the magic 8-ball | `!8ball Will I win?` |
| `!coinflip` | Flip a coin | `!coinflip` |
| `!hug @user` | Give someone a hug | `!hug @streamer` |
| `!rps <choice>` | Rock, paper, scissors | `!rps rock` |
| `!choose <options>` | Random choice | `!choose pizza, burger` |
| `!hello` | Friendly greeting | `!hello` |

### Stream Commands
| Command | Description | Permission |
|---------|-------------|------------|
| `!uptime` | Show stream uptime | Everyone |
| `!title [new]` | View/change title | View: All, Change: Mod |
| `!game [new]` | View/change game | View: All, Change: Mod |
| `!clip [duration]` | Create a clip | Everyone |
| `!shoutout @user` | Shoutout streamer | Mod |
| `!followage [@user]` | Check follow age | Everyone |

### Moderation Commands
| Command | Description | Permission |
|---------|-------------|------------|
| `!timeout @user [sec] [reason]` | Timeout user | Mod |
| `!ban @user [reason]` | Ban user | Mod |
| `!unban @user` | Unban user | Mod |
| `!permit @user` | Allow 1 link (60s) | Mod |
| `!nuke "pattern" [duration]` | Mass timeout/ban | Mod |
| `!strikes @user` | View user strikes | Mod |
| `!clearstrikes @user` | Clear strikes | Mod |

### Custom Commands
| Command | Description | Permission |
|---------|-------------|------------|
| `!addcmd <name> <response>` | Create command | Mod |
| `!editcmd <name> <response>` | Edit command | Mod |
| `!delcmd <name>` | Delete command | Mod |
| `!commands` | List all commands | Everyone |
| `!cmdinfo <name>` | View command details | Mod |

### Timer Commands
| Command | Description | Permission |
|---------|-------------|------------|
| `!addtimer <name> <min> <msg>` | Create timer | Mod |
| `!timertoggle <name>` | Enable/disable | Mod |
| `!timers` | List all timers | Mod |

### Loyalty Commands
| Command | Description | Permission |
|---------|-------------|------------|
| `!points [@user]` | Check points | Everyone |
| `!watchtime [@user]` | Check watch time | Everyone |
| `!top [count]` | Leaderboard | Everyone |
| `!loyalty on/off` | Toggle system | Owner |

### Admin Commands
| Command | Description | Permission |
|---------|-------------|------------|
| `!automod on/off` | Toggle automod | Owner |
| `!automod status` | View status | Mod |
| `!botinfo` | Bot information | Owner |
| `!ping` | Check latency | Owner |

---

## 🌐 Dashboard

Access the web dashboard at `http://your-server-ip:5000`

### Pages

| Page | Description |
|------|-------------|
| **Dashboard** | Bot status, stats, recent activity |
| **Settings** | Bot configuration, cog toggles |
| **Commands** | Create/edit custom commands |
| **Timers** | Manage scheduled messages |
| **Filters** | Configure spam filters |
| **Mod Log** | View moderation actions |
| **Users** | User management, trust scores |
| **Strikes** | View/manage user strikes |
| **Loyalty** | Points settings, leaderboard |
| **Credentials** | Update Twitch API keys |

---

## 🔧 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TWITCH_CLIENT_ID` | *required* | Twitch app client ID |
| `TWITCH_CLIENT_SECRET` | *required* | Twitch app client secret |
| `TWITCH_OAUTH_TOKEN` | *required* | Bot OAuth token |
| `TWITCH_BOT_NICK` | *required* | Bot username |
| `TWITCH_CHANNELS` | *required* | Channels to join (comma-separated) |
| `BOT_OWNER` | *required* | Your Twitch username |
| `BOT_PREFIX` | `!` | Command prefix |
| `DASHBOARD_PASSWORD` | `changeme123` | Dashboard login password |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOYALTY_ENABLED` | `false` | Enable loyalty system |
| `STRIKE_EXPIRE_DAYS` | `30` | Days until strikes expire |
| `STRIKE_MAX_BEFORE_BAN` | `5` | Strikes before auto-ban |

### Spam Filter Settings

Configure via dashboard or database:

| Filter | Default | Description |
|--------|---------|-------------|
| Caps | 70% | Max uppercase percentage |
| Emotes | 15 | Max emotes per message |
| Symbols | 50% | Max symbol percentage |
| Length | 500 | Max message length |
| Links | Whitelist | Allowed domains |

---

## 📁 Project Structure

```
engelguard/
├── src/bot/
│   ├── __init__.py          # Package init, entry point
│   ├── bot.py               # Main bot class
│   ├── config.py            # Configuration management
│   ├── cogs/
│   │   ├── admin.py         # Admin commands
│   │   ├── automod.py       # Auto-moderation
│   │   ├── clips.py         # Stream commands
│   │   ├── customcmds.py    # Custom commands
│   │   ├── fun.py           # Fun commands
│   │   ├── info.py          # Info commands
│   │   ├── loyalty.py       # Points system
│   │   ├── moderation.py    # Mod commands
│   │   ├── nuke.py          # Mass moderation
│   │   └── timers.py        # Scheduled messages
│   └── utils/
│       ├── database.py      # SQLite manager
│       ├── logging.py       # Logging setup
│       ├── permissions.py   # Permission decorators
│       ├── spam_detector.py # Spam detection
│       ├── strikes.py       # Strike system
│       └── variables.py     # Command variables
├── dashboard/
│   ├── app.py               # Flask application
│   ├── templates/           # HTML templates
│   └── static/              # CSS, JS assets
├── scripts/
│   ├── install.sh           # Installation script
│   ├── update.sh            # Update script
│   └── verify.sh            # Verification script
├── systemd/
│   ├── twitch-bot.service   # Bot service
│   └── twitch-dashboard.service
├── data/                    # SQLite databases
├── .env.example             # Example configuration
├── requirements.txt         # Python dependencies
└── README.md                # This file
```

---

## 🔒 Security Features

- **Secret Filtering** - Tokens never appear in logs
- **Non-Root Execution** - Runs as dedicated `twitchbot` user
- **Systemd Hardening** - Sandboxed with resource limits
- **Session Authentication** - Dashboard requires login
- **Subscriber Protection** - Subs immune to auto-bans

---

## 🚀 Service Management

```bash
# Start/Stop/Restart
sudo systemctl start twitch-bot
sudo systemctl stop twitch-bot
sudo systemctl restart twitch-bot

# View Logs
sudo journalctl -u twitch-bot -f

# Check Status
sudo systemctl status twitch-bot

# Dashboard
sudo systemctl start twitch-dashboard
sudo systemctl status twitch-dashboard
```

---

## 📊 Comparison with Other Bots

| Feature | EngelGuard | Nightbot | Fossabot | StreamElements |
|---------|------------|----------|----------|----------------|
| Custom Commands | ✅ | ✅ | ✅ | ✅ |
| Variables (20+) | ✅ | ✅ | ✅ | ✅ |
| Timers | ✅ | ✅ | ✅ | ✅ |
| Spam Filters | ✅ | ✅ | ✅ | ✅ |
| Lookalike Detection | ✅ | ❌ | ✅ | ❌ |
| Strike System | ✅ | ⚠️ | ✅ | ⚠️ |
| Nuke Command | ✅ | ❌ | ✅ | ✅ |
| Loyalty Points | ✅ | ❌ | ❌ | ✅ |
| Web Dashboard | ✅ | ✅ | ✅ | ✅ |
| Self-Hosted | ✅ | ❌ | ❌ | ❌ |
| Open Source | ✅ | ❌ | ❌ | ❌ |
| Free | ✅ | ✅ | ✅ | ✅ |

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- [TwitchIO](https://github.com/TwitchIO/TwitchIO) - Twitch API wrapper
- [Flask](https://flask.palletsprojects.com/) - Web dashboard framework
- Inspired by Nightbot, Fossabot, StreamElements, and Moobot

---

<div align="center">

**Made with ❤️ by [engelswtf](https://github.com/engelswtf)**

[⬆ Back to Top](#️-engelguard)

</div>
