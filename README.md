<div align="center">

# 🛡️ EngelGuard

### Your Stream, Your Bot, Your Rules

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![TwitchIO](https://img.shields.io/badge/TwitchIO-2.x-9146FF.svg)](https://github.com/TwitchIO/TwitchIO)
[![Self-Hosted](https://img.shields.io/badge/self--hosted-100%25-green.svg)](https://github.com/engelswtf/engelguard)

**EngelGuard is a feature-rich, production-ready Twitch chat bot built with Python and TwitchIO.**  
It rivals top bots like Nightbot, Fossabot, and StreamElements with advanced moderation, custom commands, loyalty systems, and more — all completely free and open-source.

[Why EngelGuard?](#-why-engelguard) • [Features](#-features) • [Quick Start](#-quick-start) • [Dashboard](#-web-dashboard) • [Docs](#-documentation)

</div>

---

## 🎯 Why EngelGuard?

Tired of paying for Nightbot Premium? Frustrated by StreamElements' limitations? Want more control than Moobot offers?

**EngelGuard is built for small streamers who want:**

- ✅ **Zero Monthly Costs** - Free forever, no premium upsells
- ✅ **Complete Control** - Self-hosted on YOUR Linux machine
- ✅ **Privacy First** - Your data stays on your server, not theirs
- ✅ **Full Customization** - Open source means you can modify anything
- ✅ **Modern Web Dashboard** - Manage everything without typing chat commands
- ✅ **No Vendor Lock-In** - Export your data anytime, switch whenever you want

### 📊 Quick Comparison

| Feature | EngelGuard | Nightbot | StreamElements | Moobot |
|---------|------------|----------|----------------|--------|
| **Cost** | **Free Forever** | Free + Premium ($10/mo) | Free + Premium | Free + Premium |
| **Self-Hosted** | ✅ **Yes** | ❌ Cloud Only | ❌ Cloud Only | ❌ Cloud Only |
| **Open Source** | ✅ **MIT License** | ❌ Proprietary | ❌ Proprietary | ❌ Proprietary |
| **Your Data** | ✅ **You Own It** | ❌ Their Servers | ❌ Their Servers | ❌ Their Servers |
| **Custom Commands** | ✅ Unlimited | ✅ Limited (25 free) | ✅ Limited | ✅ Limited |
| **Timers** | ✅ Unlimited | ✅ Limited (5 free) | ✅ Limited | ✅ Limited |
| **Loyalty Points** | ✅ Built-in | ❌ Premium Only | ✅ Yes | ❌ No |
| **Song Requests** | ✅ Built-in | ❌ Premium Only | ✅ Yes | ✅ Yes |
| **Giveaways** | ✅ Built-in | ❌ Premium Only | ✅ Yes | ❌ No |
| **Quotes System** | ✅ Built-in | ❌ No | ✅ Yes | ✅ Yes |
| **Advanced AutoMod** | ✅ Lookalike Detection | ⚠️ Basic | ⚠️ Basic | ⚠️ Basic |
| **Strike System** | ✅ Full Control | ⚠️ Limited | ⚠️ Limited | ⚠️ Limited |
| **Web Dashboard** | ✅ Full-Featured | ✅ Yes | ✅ Yes | ✅ Yes |
| **API Access** | ✅ **Full Access** | ❌ Premium Only | ⚠️ Limited | ❌ No |

**The catch?** You need a Linux machine (even a $5/month VPS works!) and basic technical skills. If you can follow a tutorial, you can run EngelGuard.

---

## ✨ Features

EngelGuard packs **13 feature modules** that rival (and often exceed) what paid bots offer:

### 🛡️ Advanced Auto-Moderation
- **Smart Spam Detection** - Pattern matching with scoring system
- **Lookalike Detection** - Catches "fr33 f0ll0w3rs" → "free followers" evasion
- **Strike System** - Escalating punishments (warn → timeout → ban)
- **Nuke Command** - Mass moderation for raid attacks with safety features
- **Configurable Filters** - Caps, symbols, emotes, links, message length
- **Subscriber Protection** - Subs immune to auto-bans (configurable)

### 📝 Custom Commands & Timers
- **Unlimited Commands** - No artificial limits (unlike Nightbot's 25)
- **20+ Variables** - `$(user)`, `$(channel)`, `$(random)`, `$(time)`, `$(urlfetch)`, and more
- **Permission Levels** - Everyone, Follower, Subscriber, VIP, Moderator, Owner
- **Cooldowns** - Per-user and global cooldowns
- **Aliases** - Multiple names for the same command
- **Unlimited Timers** - Automated messages with chat activity detection

### 🏆 Loyalty & Engagement
- **Points System** - Viewers earn points for watching and chatting
- **Watch Time Tracking** - Track viewer engagement
- **Leaderboards** - Show top viewers
- **Multipliers** - Bonus points for subscribers and VIPs
- **Fully Toggleable** - Enable/disable anytime

### 🎁 Giveaways
- **Keyword Entry** - Viewers enter with `!enter` or custom keyword
- **Subscriber Luck** - Give subs extra entries (configurable multiplier)
- **Auto-End Timer** - Giveaways end automatically
- **Winner Selection** - Random, fair selection from all entries
- **Dashboard Management** - Create and manage giveaways from web UI

### 💬 Quotes System
- **Save Memorable Moments** - `!addquote` to capture funny/epic moments
- **Random Quotes** - `!quote` shows a random quote
- **Quote Search** - `!quote 42` shows specific quote by ID
- **Dashboard Management** - View, edit, delete quotes from web UI

### 🎵 Song Requests
- **YouTube Integration** - Viewers request songs with `!sr <YouTube URL>`
- **Queue Management** - `!queue`, `!skip`, `!clear` commands
- **Volume Control** - Adjust playback volume
- **Auto-Play** - Queue plays automatically
- **Dashboard Control** - Manage queue from web UI

### 🎬 Stream Integration
- **Clip Creation** - Create clips via chat command
- **Title/Game Management** - View and change stream info
- **Uptime Display** - Show stream duration
- **Shoutouts** - Give shoutouts to other streamers
- **Followage** - Check how long someone has been following

### 🎮 Fun Commands
- **Dice Rolls** - D&D notation support (`!dice 2d20+5`)
- **Magic 8-Ball** - Ask questions, get answers
- **Coin Flip** - Heads or tails
- **Rock Paper Scissors** - Play against the bot
- **Hugs & Slaps** - Interactive fun commands
- **Random Choice** - `!choose pizza, burger, tacos`

### 🌐 Modern Web Dashboard
- **Dark Theme UI** - Twitch-inspired design
- **Real-Time Stats** - Live bot status, uptime, and activity
- **Full Management** - Commands, timers, filters, users, quotes, giveaways, songs
- **Mobile Responsive** - Works on all devices
- **Secure Login** - Password-protected access
- **Toggle Features** - Enable/disable any module with one click

---

## 🚀 Quick Start

### What You Need

- **Linux System** - Debian/Ubuntu recommended (or any Linux distro)
  - Local machine, Raspberry Pi, or VPS ($5/month gets you started)
- **Python 3.10+** - Usually pre-installed on modern Linux
- **Twitch Account** - For the bot (can be a separate account)
- **10 Minutes** - That's all it takes to get running

### Installation

**Full installation guide:** [INSTALLATION.md](INSTALLATION.md)

```bash
# 1. Clone the repository
git clone https://github.com/engelswtf/engelguard.git
cd engelguard

# 2. Run the installer (handles everything automatically)
sudo ./scripts/install.sh

# 3. Configure your Twitch credentials
sudo nano /opt/twitch-bot/.env

# 4. Start the bot and dashboard
sudo systemctl enable twitch-bot twitch-dashboard
sudo systemctl start twitch-bot twitch-dashboard

# 5. Access the dashboard
# Open http://your-server-ip:5000 in your browser
```

### Get Twitch Credentials

1. **Client ID & Secret**: [Twitch Developer Console](https://dev.twitch.tv/console/apps)
   - Create a new application
   - Set OAuth Redirect URL to `http://localhost`
   
2. **OAuth Token**: [Twitch Token Generator](https://twitchtokengenerator.com/)
   - Required scopes: `chat:read`, `chat:edit`, `channel:moderate`, `clips:edit`, `moderator:manage:banned_users`

**Need help?** Check out our [Quick Start Guide](QUICKSTART.md) for detailed step-by-step instructions.

---

## 🎮 Core Commands

### Fun Commands
| Command | Description | Example |
|---------|-------------|---------|
| `!dice [sides]` | Roll dice (D&D notation supported) | `!dice 2d6+3` |
| `!8ball <question>` | Ask the magic 8-ball | `!8ball Will I win?` |
| `!coinflip` | Flip a coin | `!coinflip` |
| `!hug @user` | Give someone a hug | `!hug @streamer` |
| `!rps <choice>` | Rock, paper, scissors | `!rps rock` |
| `!choose <options>` | Random choice from list | `!choose pizza, burger, tacos` |

### Stream Commands
| Command | Description | Permission |
|---------|-------------|------------|
| `!uptime` | Show stream uptime | Everyone |
| `!title [new]` | View/change stream title | View: All, Change: Mod |
| `!game [new]` | View/change game category | View: All, Change: Mod |
| `!clip [duration]` | Create a clip | Everyone |
| `!shoutout @user` | Shoutout another streamer | Mod |
| `!followage [@user]` | Check follow duration | Everyone |

### Moderation Commands
| Command | Description | Permission |
|---------|-------------|------------|
| `!timeout @user [sec] [reason]` | Timeout user | Mod |
| `!ban @user [reason]` | Ban user | Mod |
| `!unban @user` | Unban user | Mod |
| `!permit @user` | Allow 1 link (60s window) | Mod |
| `!nuke "pattern" [duration]` | Mass timeout/ban matching users | Mod |
| `!strikes @user` | View user's strike count | Mod |
| `!clearstrikes @user` | Clear user's strikes | Mod |

### Custom Commands
| Command | Description | Permission |
|---------|-------------|------------|
| `!addcmd <name> <response>` | Create custom command | Mod |
| `!editcmd <name> <response>` | Edit existing command | Mod |
| `!delcmd <name>` | Delete command | Mod |
| `!commands` | List all custom commands | Everyone |
| `!cmdinfo <name>` | View command details | Mod |

### Loyalty System
| Command | Description | Permission |
|---------|-------------|------------|
| `!points [@user]` | Check points balance | Everyone |
| `!watchtime [@user]` | Check watch time | Everyone |
| `!top [count]` | Show leaderboard | Everyone |
| `!loyalty on/off` | Toggle loyalty system | Owner |

### Quotes
| Command | Description | Permission |
|---------|-------------|------------|
| `!quote [id]` | Show random or specific quote | Everyone |
| `!addquote <text>` | Add a new quote | Mod |
| `!delquote <id>` | Delete a quote | Mod |
| `!editquote <id> <text>` | Edit existing quote | Mod |

### Giveaways
| Command | Description | Permission |
|---------|-------------|------------|
| `!giveaway start <prize>` | Start a giveaway | Mod |
| `!giveaway end` | End giveaway & pick winner | Mod |
| `!enter` | Enter current giveaway | Everyone |
| `!giveaway status` | Check giveaway status | Everyone |

### Song Requests
| Command | Description | Permission |
|---------|-------------|------------|
| `!sr <YouTube URL>` | Request a song | Everyone |
| `!queue` | Show song queue | Everyone |
| `!skip` | Skip current song | Mod |
| `!clear` | Clear song queue | Mod |
| `!volume <0-100>` | Adjust volume | Mod |

**Full command list:** [COMMANDS.md](docs/COMMANDS.md)

---

## 🌐 Web Dashboard

Access at `http://your-server-ip:5000` (default password: set during installation)

### Dashboard Pages

| Page | What You Can Do |
|------|-----------------|
| **🏠 Dashboard** | View bot status, uptime, recent activity, quick stats |
| **⚙️ Settings** | Toggle features on/off, configure bot behavior |
| **📝 Commands** | Create, edit, delete custom commands with variables |
| **⏰ Timers** | Manage automated messages and intervals |
| **🛡️ Filters** | Configure spam filters, caps limits, link whitelist |
| **👥 Users** | View user list, trust scores, manage permissions |
| **⚠️ Strikes** | View and manage user strike history |
| **📋 Mod Log** | See all moderation actions (bans, timeouts, warnings) |
| **🏆 Loyalty** | Configure points system, view leaderboard |
| **💬 Quotes** | Browse, add, edit, delete quotes |
| **🎁 Giveaways** | Create and manage giveaways |
| **🎵 Song Requests** | View and manage song queue |
| **🔑 Credentials** | Update Twitch API keys and tokens |

**Mobile-friendly** - Manage your bot from your phone!

---

## 📚 Documentation

- **[Quick Start Guide](QUICKSTART.md)** - Get up and running in 10 minutes
- **[Installation Guide](INSTALLATION.md)** - Detailed setup instructions
- **[Commands Reference](docs/COMMANDS.md)** - Complete command list
- **[Deployment Guide](DEPLOYMENT.md)** - Production deployment tips
- **[Project Status](docs/PROJECT_STATUS.md)** - Current features and roadmap

---

## 🔧 System Requirements

### Minimum
- **OS**: Any Linux distribution (Debian/Ubuntu recommended)
- **RAM**: 512 MB
- **CPU**: 1 core
- **Disk**: 500 MB
- **Network**: Stable internet connection

### Recommended
- **OS**: Ubuntu 22.04 LTS or Debian 12
- **RAM**: 1 GB
- **CPU**: 2 cores
- **Disk**: 2 GB (for logs and database growth)

### Where to Host
- **Local Machine** - Old laptop, desktop, or Raspberry Pi
- **VPS** - DigitalOcean, Linode, Vultr ($5-10/month)
- **Home Server** - Any Linux box on your network
- **Cloud** - AWS, Google Cloud, Azure (free tier eligible)

---

## 🔒 Security & Privacy

### Your Data, Your Control
- **No Telemetry** - We don't track you or your viewers
- **No External Dependencies** - All data stored locally in SQLite
- **No Cloud Services** - Everything runs on YOUR server
- **Open Source** - Audit the code yourself

### Security Features
- **Secret Filtering** - Tokens never appear in logs
- **Non-Root Execution** - Runs as dedicated `twitchbot` user
- **Systemd Hardening** - Sandboxed with resource limits
- **Session Authentication** - Dashboard requires password login
- **Subscriber Protection** - Subs immune to auto-bans (configurable)

---

## 🛠️ Service Management

```bash
# Start/Stop/Restart the bot
sudo systemctl start twitch-bot
sudo systemctl stop twitch-bot
sudo systemctl restart twitch-bot

# Start/Stop the dashboard
sudo systemctl start twitch-dashboard
sudo systemctl stop twitch-dashboard

# View live logs
sudo journalctl -u twitch-bot -f

# Check status
sudo systemctl status twitch-bot
sudo systemctl status twitch-dashboard

# Enable auto-start on boot
sudo systemctl enable twitch-bot twitch-dashboard
```

---

## 🤝 Contributing

EngelGuard is built by streamers, for streamers. We welcome contributions!

### How to Contribute
1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/AmazingFeature`)
3. **Commit** your changes (`git commit -m 'Add some AmazingFeature'`)
4. **Push** to the branch (`git push origin feature/AmazingFeature`)
5. **Open** a Pull Request

### Ideas for Contributions
- 🐛 Bug fixes
- ✨ New features (cogs/modules)
- 📝 Documentation improvements
- 🌍 Translations
- 🎨 Dashboard UI enhancements
- 🧪 Tests and quality improvements

**Not a coder?** You can still help by:
- Reporting bugs
- Suggesting features
- Writing tutorials
- Helping other users

---

## 📄 License

EngelGuard is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

**What this means:**
- ✅ Use it commercially
- ✅ Modify it however you want
- ✅ Distribute it freely
- ✅ Use it privately
- ⚠️ No warranty provided
- ⚠️ Must include license and copyright notice

---

## 🗺️ Roadmap

### ✅ Phase 1 - Core Bot (Complete)
- Basic commands and moderation
- Custom commands with variables
- AutoMod with spam detection
- Web dashboard

### ✅ Phase 2 - Advanced Features (Complete)
- Loyalty points system
- Quotes system
- Giveaways
- Song requests (YouTube integration)

### 🚧 Phase 3 - Community & Integrations (In Progress)
- [ ] Discord notifications
- [ ] Multi-channel support
- [ ] Twitch EventSub integration
- [ ] Prediction/Poll integration
- [ ] Raid alerts
- [ ] Hype train tracking

### 🔮 Phase 4 - Advanced Customization (Planned)
- [ ] Plugin system for community extensions
- [ ] Custom dashboard themes
- [ ] Advanced analytics
- [ ] Backup/restore system
- [ ] Migration tools (import from Nightbot/StreamElements)

**Have an idea?** [Open an issue](https://github.com/engelswtf/engelguard/issues) and let's discuss it!

---

## 💬 Support & Community

### Need Help?
- **📖 Documentation** - Check the [docs](docs/) folder
- **🐛 Bug Reports** - [Open an issue](https://github.com/engelswtf/engelguard/issues)
- **💡 Feature Requests** - [Open an issue](https://github.com/engelswtf/engelguard/issues)
- **❓ Questions** - [Discussions](https://github.com/engelswtf/engelguard/discussions)

### Community
- **GitHub Discussions** - Ask questions, share setups
- **Discord** - Coming soon!
- **Twitch** - Watch development streams (coming soon!)

---

## 🙏 Acknowledgments

EngelGuard wouldn't exist without these amazing projects:

- **[TwitchIO](https://github.com/TwitchIO/TwitchIO)** - Twitch API wrapper for Python
- **[Flask](https://flask.palletsprojects.com/)** - Web dashboard framework
- **[SQLite](https://www.sqlite.org/)** - Lightweight database engine

**Inspired by:** Nightbot, Fossabot, StreamElements, and Moobot - but built to be free and open.

---

## ⭐ Star History

If EngelGuard helps your stream, consider giving it a star! It helps others discover the project.

[![Star History](https://img.shields.io/github/stars/engelswtf/engelguard?style=social)](https://github.com/engelswtf/engelguard)

---

<div align="center">

**Built with ❤️ by streamers, for streamers**

[⬆ Back to Top](#️-engelguard)

---

**Your stream. Your bot. Your rules.**

*No monthly fees. No premium tiers. No BS.*

</div>
