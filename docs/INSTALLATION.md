# 🛡️ EngelGuard Installation Guide

Complete step-by-step installation guide for setting up the EngelGuard Twitch bot on your Linux server.

---

## 📋 Table of Contents

- [Prerequisites](#-prerequisites)
- [Getting Twitch Credentials](#-getting-twitch-credentials)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Running the Bot](#-running-the-bot)
- [Accessing the Dashboard](#-accessing-the-dashboard)
- [Firewall Configuration](#-firewall-configuration)
- [Updating](#-updating)
- [Troubleshooting](#-troubleshooting)
- [Next Steps](#-next-steps)

---

## 📋 Prerequisites

Before installing EngelGuard, make sure you have:

### System Requirements

- **Operating System**: Linux (Debian 11/12 or Ubuntu 22.04+ recommended)
  - Also works on: Raspberry Pi OS, Proxmox LXC containers, most Debian-based distros
- **Python**: Version 3.10 or higher
- **Git**: For cloning the repository
- **Root/Sudo Access**: Required for installation
- **Internet Connection**: For downloading dependencies

### Hardware Requirements

- **Minimum**: 512MB RAM, 1 CPU core, 1GB disk space
- **Recommended**: 1GB RAM, 2 CPU cores, 2GB disk space
- Works great on: VPS, Raspberry Pi 3/4, old PCs, home servers

### Accounts You'll Need

- **Twitch Account for the Bot**: Create a separate account (e.g., `YourChannelBot`)
- **Twitch Developer Account**: Your main account to create the application
- **Server Access**: SSH access to your Linux server

### Check Your Python Version

```bash
python3 --version
```

You should see `Python 3.10.x` or higher. If not, install it:

```bash
# Debian/Ubuntu
sudo apt update
sudo apt install python3 python3-pip python3-venv
```

---

## 🔑 Getting Twitch Credentials

You'll need three pieces of information from Twitch. Follow these steps carefully.

### Step 1: Create a Twitch Developer Application

1. **Go to the Twitch Developer Console**
   - Visit: https://dev.twitch.tv/console
   - Log in with your **main** Twitch account (not the bot account)

2. **Register a New Application**
   - Click **"Register Your Application"** (purple button in top right)
   - Fill in the form:
     - **Name**: `YourChannel Bot` (or any name you like)
     - **OAuth Redirect URLs**: `http://localhost:3000`
     - **Category**: `Chat Bot`
   - Complete the CAPTCHA
   - Click **"Create"**

3. **Get Your Client ID**
   - You'll see your new application in the list
   - Click **"Manage"** on your application
   - Copy the **Client ID** (looks like: `a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5`)
   - Save this somewhere safe - you'll need it later

4. **Generate a Client Secret**
   - On the same page, click **"New Secret"**
   - Copy the **Client Secret** immediately (you can only see it once!)
   - Save this somewhere safe - you'll need it later
   - **Important**: Never share your Client Secret publicly

### Step 2: Generate an OAuth Token

You need an OAuth token for your **bot account** (not your main account).

#### Option A: Using Twitch Token Generator (Easiest)

1. **Go to Twitch Token Generator**
   - Visit: https://twitchtokengenerator.com/
   - This is a trusted third-party tool used by many bot developers

2. **Select Custom Scope Token**
   - Scroll down to **"Custom Scope Token"**
   - Select these scopes (checkboxes):
     - ✅ `chat:read` - Read chat messages
     - ✅ `chat:edit` - Send chat messages
     - ✅ `channel:moderate` - Perform moderation actions
     - ✅ `moderator:manage:banned_users` - Ban/unban users
     - ✅ `clips:edit` - Create clips (optional but recommended)
     - ✅ `channel:read:redemptions` - Read channel point redemptions (optional)

3. **Generate Token**
   - Click **"Generate Token"**
   - You'll be redirected to Twitch
   - **Log in with your BOT account** (e.g., `YourChannelBot`)
   - Click **"Authorize"**

4. **Copy Your Tokens**
   - You'll be redirected back to the token generator
   - Copy the **Access Token** (starts with `oauth:` or just letters/numbers)
   - Copy the **Refresh Token** (optional but recommended)
   - Save both somewhere safe

#### Option B: Using Twitch CLI (Advanced)

If you prefer using the official Twitch CLI:

```bash
# Install Twitch CLI
# Visit: https://dev.twitch.tv/docs/cli/

# Generate token with required scopes
twitch token -u -s "chat:read chat:edit channel:moderate moderator:manage:banned_users clips:edit"
```

### Step 3: Make Your Bot a Moderator

**Important**: Your bot account must be a moderator in your channel!

1. Go to your Twitch channel (on your main account)
2. Type in chat: `/mod YourChannelBot`
3. You should see: `You have added YourChannelBot as a moderator of this channel.`

Without moderator status, the bot cannot timeout or ban users.

---

## 💾 Installation

Now let's install the bot on your server.

### Quick Installation (Recommended)

The easiest way to install EngelGuard is using the automated installer:

```bash
# Clone the repository
git clone https://github.com/engelswtf/engelguard.git
cd engelguard

# Run the installer (requires sudo)
sudo ./scripts/install.sh
```

The installer will:
- ✅ Check system requirements
- ✅ Create a dedicated `twitchbot` user
- ✅ Install system dependencies
- ✅ Set up a Python virtual environment
- ✅ Install Python packages
- ✅ Copy files to `/opt/twitch-bot`
- ✅ Create systemd service
- ✅ Set proper permissions

**Installation complete!** Skip to [Configuration](#-configuration).

### Manual Installation (Advanced)

If you prefer to install manually or the script doesn't work:

#### 1. Install System Dependencies

```bash
# Update package list
sudo apt update

# Install required packages
sudo apt install -y python3 python3-pip python3-venv python3-dev build-essential git
```

#### 2. Create Bot User

```bash
# Create a system user for the bot (no login, no home directory)
sudo useradd --system --no-create-home --shell /usr/sbin/nologin twitchbot
```

#### 3. Create Directories

```bash
# Create installation directory
sudo mkdir -p /opt/twitch-bot/data

# Create log directory
sudo mkdir -p /var/log/twitch-bot
```

#### 4. Clone Repository

```bash
# Clone to temporary location
cd /tmp
git clone https://github.com/engelswtf/engelguard.git
cd engelguard
```

#### 5. Set Up Virtual Environment

```bash
# Create virtual environment
sudo python3 -m venv /opt/twitch-bot/venv

# Upgrade pip
sudo /opt/twitch-bot/venv/bin/pip install --upgrade pip setuptools wheel
```

#### 6. Install Python Dependencies

```bash
# Install from requirements.txt
sudo /opt/twitch-bot/venv/bin/pip install -r requirements.txt
```

#### 7. Copy Files

```bash
# Copy bot files
sudo cp -r src /opt/twitch-bot/
sudo cp run.py /opt/twitch-bot/
sudo cp requirements.txt /opt/twitch-bot/
sudo cp .env.example /opt/twitch-bot/.env
```

#### 8. Install Systemd Service

```bash
# Copy service file
sudo cp systemd/twitch-bot.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload
```

#### 9. Set Permissions

```bash
# Set ownership
sudo chown -R twitchbot:twitchbot /opt/twitch-bot
sudo chown -R twitchbot:twitchbot /var/log/twitch-bot

# Set .env permissions (readable only by bot user)
sudo chmod 600 /opt/twitch-bot/.env

# Set directory permissions
sudo chmod 755 /opt/twitch-bot
sudo chmod 750 /opt/twitch-bot/data
```

---

## ⚙️ Configuration

Now you need to configure the bot with your Twitch credentials.

### Edit the Configuration File

```bash
sudo nano /opt/twitch-bot/.env
```

You'll see a file with many settings. Here's what you need to change:

### Required Settings

These **must** be configured for the bot to work:

```env
# --- Twitch API Credentials ---
# Paste the Client ID you got from dev.twitch.tv
TWITCH_CLIENT_ID=a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5

# Paste the Client Secret you got from dev.twitch.tv
TWITCH_CLIENT_SECRET=p9o8i7u6y5t4r3e2w1q0a9s8d7f6g5

# --- Bot Authentication ---
# Paste the OAuth token from twitchtokengenerator.com
# Make sure it starts with "oauth:" - if not, add it!
TWITCH_OAUTH_TOKEN=oauth:abcdefghijklmnopqrstuvwxyz123456

# Paste the refresh token (optional but recommended)
TWITCH_REFRESH_TOKEN=your_refresh_token_here

# --- Bot Settings ---
# Your bot's Twitch username (the account you generated the token for)
TWITCH_BOT_NICK=YourChannelBot

# Your channel name (where the bot will join)
# For multiple channels: channel1,channel2,channel3
TWITCH_CHANNELS=yourchannel

# --- Owner Settings ---
# Your main Twitch username (for owner-only commands)
BOT_OWNER=YourMainUsername
```

### Optional Settings

You can customize these, but the defaults work fine:

```env
# --- Command Prefix ---
# What character triggers commands (default: !)
BOT_PREFIX=!

# --- Logging ---
# How detailed should logs be? (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL=INFO

# Optional: Save logs to a file
# LOG_FILE=/var/log/twitch-bot/bot.log

# --- Database ---
# Where to store bot data (quotes, points, etc.)
DATABASE_URL=sqlite:///data/bot.db

# --- Feature Flags ---
# Enable/disable command groups
ENABLE_MODERATION=true
ENABLE_FUN_COMMANDS=true
ENABLE_INFO_COMMANDS=true
ENABLE_ADMIN_COMMANDS=true

# --- Rate Limiting ---
# Cooldown between commands (seconds)
DEFAULT_COOLDOWN=3

# --- Dashboard (if using web dashboard) ---
# Password to access the web dashboard
DASHBOARD_PASSWORD=your_secure_password_here
```

### Save and Exit

- Press `Ctrl + O` to save
- Press `Enter` to confirm
- Press `Ctrl + X` to exit

### Verify Your Configuration

Double-check your settings:

```bash
sudo cat /opt/twitch-bot/.env | grep -E "TWITCH_CLIENT_ID|TWITCH_BOT_NICK|TWITCH_CHANNELS|BOT_OWNER"
```

Make sure:
- ✅ No values say `your_*_here`
- ✅ `TWITCH_BOT_NICK` matches your bot account
- ✅ `TWITCH_CHANNELS` matches your channel name
- ✅ `BOT_OWNER` matches your main username

---

## 🚀 Running the Bot

You have two options for running the bot:

### Option A: Direct Execution (For Testing)

Good for testing if everything works before setting up as a service.

```bash
# Activate virtual environment
source /opt/twitch-bot/venv/bin/activate

# Run the bot
cd /opt/twitch-bot
python run.py
```

You should see output like:
```
[INFO] Loading configuration...
[INFO] Connecting to Twitch...
[INFO] Connected to Twitch as YourChannelBot
[INFO] Joined #yourchannel
[INFO] Bot is ready!
```

**Test it**: Go to your Twitch chat and type `!hello`

Press `Ctrl + C` to stop the bot when testing is done.

### Option B: Systemd Service (Recommended for Production)

This makes the bot start automatically on boot and restart if it crashes.

#### Enable and Start the Service

```bash
# Enable service to start on boot
sudo systemctl enable twitch-bot

# Start the service now
sudo systemctl start twitch-bot
```

#### Check Service Status

```bash
sudo systemctl status twitch-bot
```

You should see:
```
● twitch-bot.service - Twitch Bot Service
     Loaded: loaded (/etc/systemd/system/twitch-bot.service; enabled)
     Active: active (running) since ...
```

If you see `Active: active (running)` in green, it's working! 🎉

#### View Live Logs

```bash
# Follow logs in real-time
sudo journalctl -u twitch-bot -f

# View last 50 lines
sudo journalctl -u twitch-bot -n 50

# View logs from today
sudo journalctl -u twitch-bot --since today
```

#### Service Management Commands

```bash
# Start the bot
sudo systemctl start twitch-bot

# Stop the bot
sudo systemctl stop twitch-bot

# Restart the bot (after config changes)
sudo systemctl restart twitch-bot

# Check status
sudo systemctl status twitch-bot

# Disable auto-start on boot
sudo systemctl disable twitch-bot
```

---

## 🌐 Accessing the Dashboard

EngelGuard includes a web dashboard for managing the bot.

### Starting the Dashboard

The dashboard is a separate service that runs alongside the bot.

```bash
# Start the dashboard
sudo systemctl start twitch-dashboard

# Enable auto-start on boot
sudo systemctl enable twitch-dashboard

# Check status
sudo systemctl status twitch-dashboard
```

### Accessing the Dashboard

1. **Open your web browser**
2. **Navigate to**: `http://your-server-ip:5000`
   - If running locally: `http://localhost:5000`
   - If on a VPS: `http://123.45.67.89:5000`
3. **Login** with the password you set in `DASHBOARD_PASSWORD`

### Dashboard Features

Once logged in, you'll see:

| Page | What You Can Do |
|------|-----------------|
| **Dashboard** | View bot status, uptime, recent activity |
| **Settings** | Toggle features, change bot settings |
| **Commands** | Create, edit, delete custom commands |
| **Timers** | Set up scheduled messages |
| **Filters** | Configure spam filters (caps, emotes, links) |
| **Mod Log** | View all moderation actions (timeouts, bans) |
| **Users** | Manage users, view trust scores |
| **Strikes** | View and clear user strikes |
| **Loyalty** | Configure points system, view leaderboard |
| **Quotes** | Manage channel quotes |
| **Song Requests** | Manage song request queue |
| **Giveaways** | Create and manage giveaways |
| **Credentials** | Update Twitch API credentials |

### Dashboard Tips

- 📱 **Mobile Friendly**: Works on phones and tablets
- 🔒 **Secure**: Always use a strong password
- 🌙 **Dark Theme**: Easy on the eyes during streams
- ⚡ **Real-Time**: Most changes take effect immediately

---

## 🔥 Firewall Configuration

If you can't access the dashboard, you may need to open port 5000 in your firewall.

### Using UFW (Ubuntu/Debian)

```bash
# Check if UFW is active
sudo ufw status

# Allow port 5000 (dashboard)
sudo ufw allow 5000/tcp

# Reload firewall
sudo ufw reload

# Verify rule was added
sudo ufw status numbered
```

### Using iptables (Advanced)

```bash
# Allow port 5000
sudo iptables -A INPUT -p tcp --dport 5000 -j ACCEPT

# Save rules (Debian/Ubuntu)
sudo netfilter-persistent save

# Or on other systems
sudo iptables-save > /etc/iptables/rules.v4
```

### Cloud Provider Firewalls

If using a VPS (DigitalOcean, AWS, etc.), you may also need to:

1. Log into your provider's control panel
2. Find "Firewall" or "Security Groups"
3. Add a rule to allow TCP port 5000
4. Apply the rule to your server

### Security Tip: Restrict Access

For better security, only allow access from your IP:

```bash
# Replace 1.2.3.4 with your home IP address
sudo ufw allow from 1.2.3.4 to any port 5000
```

Or use SSH tunneling (no firewall changes needed):

```bash
# On your local machine
ssh -L 5000:localhost:5000 user@your-server-ip

# Then access: http://localhost:5000
```

---

## 🔄 Updating

Keep your bot up-to-date with the latest features and bug fixes.

### Automatic Update (Recommended)

```bash
# Use the update script
cd /opt/twitch-bot
sudo ./scripts/update.sh
```

The update script will:
- ✅ Pull latest code from GitHub
- ✅ Update Python dependencies
- ✅ Restart services
- ✅ Verify everything works

### Manual Update

```bash
# Navigate to installation directory
cd /opt/twitch-bot

# Pull latest changes
sudo git pull origin main

# Update dependencies
sudo /opt/twitch-bot/venv/bin/pip install -r requirements.txt --upgrade

# Restart services
sudo systemctl restart twitch-bot
sudo systemctl restart twitch-dashboard

# Check status
sudo systemctl status twitch-bot
```

### Check for Updates

```bash
# See if updates are available
cd /opt/twitch-bot
sudo git fetch
sudo git status
```

If you see `Your branch is behind`, updates are available.

### Rollback (If Something Breaks)

```bash
# View recent commits
cd /opt/twitch-bot
sudo git log --oneline -n 10

# Rollback to previous version (replace abc123 with commit hash)
sudo git reset --hard abc123

# Restart services
sudo systemctl restart twitch-bot
```

---

## 🔧 Troubleshooting

Common issues and how to fix them.

### Bot Won't Start

**Check the logs first:**
```bash
sudo journalctl -u twitch-bot -n 50
```

#### Error: "TWITCH_CLIENT_ID is required"

**Problem**: Configuration file not set up correctly.

**Solution**:
```bash
# Edit config file
sudo nano /opt/twitch-bot/.env

# Make sure all required fields are filled in
# Save and restart
sudo systemctl restart twitch-bot
```

#### Error: "Failed to connect to Twitch"

**Problem**: Invalid OAuth token or network issue.

**Solution**:
1. Generate a new OAuth token at https://twitchtokengenerator.com/
2. Update `.env` file with new token
3. Make sure token starts with `oauth:`
4. Restart bot

```bash
sudo nano /opt/twitch-bot/.env
# Update TWITCH_OAUTH_TOKEN
sudo systemctl restart twitch-bot
```

#### Error: "Permission denied"

**Problem**: File permissions are incorrect.

**Solution**:
```bash
# Fix ownership
sudo chown -R twitchbot:twitchbot /opt/twitch-bot
sudo chown -R twitchbot:twitchbot /var/log/twitch-bot

# Fix .env permissions
sudo chmod 600 /opt/twitch-bot/.env

# Restart
sudo systemctl restart twitch-bot
```

### Bot Connects But Doesn't Respond

#### Bot Not a Moderator

**Problem**: Bot needs moderator status to work properly.

**Solution**:
1. Go to your Twitch channel
2. Type: `/mod YourChannelBot`
3. Verify: `/mods`

#### Wrong Command Prefix

**Problem**: Using wrong prefix (e.g., `?hello` instead of `!hello`).

**Solution**: Check your prefix in `.env`:
```bash
sudo cat /opt/twitch-bot/.env | grep BOT_PREFIX
```

#### Bot in Wrong Channel

**Problem**: Bot joined a different channel.

**Solution**: Check logs to see which channel it joined:
```bash
sudo journalctl -u twitch-bot -n 50 | grep "Joined"
```

Update `TWITCH_CHANNELS` in `.env` if wrong.

### Dashboard Not Accessible

#### Port 5000 Blocked

**Problem**: Firewall blocking port 5000.

**Solution**:
```bash
# Open port 5000
sudo ufw allow 5000/tcp
sudo ufw reload
```

#### Dashboard Not Running

**Problem**: Dashboard service not started.

**Solution**:
```bash
# Check status
sudo systemctl status twitch-dashboard

# Start if stopped
sudo systemctl start twitch-dashboard

# View logs
sudo journalctl -u twitch-dashboard -n 50
```

#### Wrong Password

**Problem**: Can't log into dashboard.

**Solution**:
```bash
# Check current password
sudo cat /opt/twitch-bot/.env | grep DASHBOARD_PASSWORD

# Change password
sudo nano /opt/twitch-bot/.env
# Update DASHBOARD_PASSWORD=your_new_password

# Restart dashboard
sudo systemctl restart twitch-dashboard
```

### High CPU or Memory Usage

**Problem**: Bot using too many resources.

**Solution**:
```bash
# Check resource usage
sudo systemctl status twitch-bot

# View detailed stats
top -p $(pgrep -f "python.*run.py")

# Restart bot
sudo systemctl restart twitch-bot
```

The systemd service has built-in limits:
- CPU: 50% of one core
- Memory: 512MB max
- Tasks: 50 max

### Database Errors

**Problem**: Database locked or corrupted.

**Solution**:
```bash
# Stop bot
sudo systemctl stop twitch-bot

# Check database
sudo -u twitchbot sqlite3 /opt/twitch-bot/data/automod.db "PRAGMA integrity_check;"

# If corrupted, restore from backup
sudo cp /opt/twitch-bot/data/automod.db.backup /opt/twitch-bot/data/automod.db

# Start bot
sudo systemctl start twitch-bot
```

### Getting Help

If you're still stuck:

1. **Check the logs** (most issues show up here):
   ```bash
   sudo journalctl -u twitch-bot -n 100
   ```

2. **Search GitHub Issues**: https://github.com/engelswtf/engelguard/issues

3. **Open a new issue** with:
   - Your OS version (`cat /etc/os-release`)
   - Python version (`python3 --version`)
   - Error messages from logs
   - What you've already tried

4. **Join the Discord** (if available): Check the README for link

---

## 🎯 Next Steps

Congratulations! Your bot is now running. Here's what to do next:

### 1. Test Basic Commands

Go to your Twitch chat and try:

```
!hello          - Test if bot responds
!commands       - See all available commands
!uptime         - Check stream uptime
!dice 2d6       - Roll some dice
```

### 2. Set Up Custom Commands

Create your first custom command:

```
!addcmd discord Join our Discord: https://discord.gg/yourserver
!addcmd socials Follow me on Twitter: @yourhandle
```

Or use the dashboard: http://your-server-ip:5000/commands

### 3. Configure Auto-Moderation

Set up spam filters in the dashboard:
- Go to **Filters** page
- Configure caps limit (default: 70%)
- Configure emote limit (default: 15)
- Add allowed link domains
- Enable/disable filters

### 4. Set Up Timers

Create scheduled messages:

```
!addtimer social 15 Don't forget to follow! https://twitch.tv/yourchannel
```

Or use the dashboard: http://your-server-ip:5000/timers

### 5. Enable Loyalty System (Optional)

If you want a points system:

```bash
# Edit config
sudo nano /opt/twitch-bot/.env

# Set LOYALTY_ENABLED=true

# Restart bot
sudo systemctl restart twitch-bot
```

Then viewers can use:
```
!points         - Check their points
!watchtime      - Check watch time
!top 10         - View leaderboard
```

### 6. Read the Commands Guide

Learn all available commands:
- [COMMANDS.md](COMMANDS.md) - Complete command reference
- Includes: moderation, fun, info, admin commands
- Shows permissions and examples

### 7. Customize for Your Stream

Make the bot yours:
- Create custom commands for your community
- Set up timers for social media
- Configure filters for your chat culture
- Add quotes from your stream

### 8. Monitor and Maintain

Keep an eye on your bot:

```bash
# Check status daily
sudo systemctl status twitch-bot

# View logs for issues
sudo journalctl -u twitch-bot --since today

# Update weekly
cd /opt/twitch-bot && sudo git pull
```

### 9. Backup Your Data

Protect your custom commands and user data:

```bash
# Create backup script
sudo nano /root/backup-bot.sh
```

Add:
```bash
#!/bin/bash
cp /opt/twitch-bot/data/automod.db /root/backups/automod-$(date +%Y%m%d).db
```

```bash
# Make executable
sudo chmod +x /root/backup-bot.sh

# Add to crontab (daily at 3 AM)
sudo crontab -e
# Add: 0 3 * * * /root/backup-bot.sh
```

### 10. Join the Community

- ⭐ **Star the repo**: https://github.com/engelswtf/engelguard
- 🐛 **Report bugs**: Open GitHub issues
- 💡 **Suggest features**: Share your ideas
- 🤝 **Contribute**: Submit pull requests

---

## 📚 Additional Resources

- **[README.md](../README.md)** - Project overview and features
- **[COMMANDS.md](COMMANDS.md)** - Complete command reference
- **[GitHub Repository](https://github.com/engelswtf/engelguard)** - Source code and issues
- **[Twitch Developer Docs](https://dev.twitch.tv/docs/)** - Official Twitch API documentation
- **[TwitchIO Documentation](https://twitchio.dev/)** - Python library documentation

---

## ❤️ Thank You!

Thank you for choosing EngelGuard! If you find it useful, please:

- ⭐ Star the repository on GitHub
- 📢 Share it with other streamers
- 🐛 Report bugs and suggest features
- 💝 Consider contributing

**Happy streaming!** 🎮✨

---

<div align="center">

**Made with ❤️ by [engelswtf](https://github.com/engelswtf)**

[⬆ Back to Top](#️-engelguard-installation-guide)

</div>
