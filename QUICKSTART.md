# Twitch Bot - Quick Start Guide

## 🚀 Installation (5 minutes)

```bash
# 1. Run installer
cd /root/twitch-bot
sudo ./scripts/install.sh

# 2. Configure bot
sudo nano /opt/twitch-bot/.env
# Fill in: TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET, TWITCH_OAUTH_TOKEN, 
#          TWITCH_BOT_NICK, TWITCH_CHANNELS, BOT_OWNER

# 3. Start bot
sudo systemctl enable twitch-bot
sudo systemctl start twitch-bot

# 4. Check status
sudo systemctl status twitch-bot
```

## 📝 Essential Commands

```bash
# Service Control
sudo systemctl start twitch-bot      # Start bot
sudo systemctl stop twitch-bot       # Stop bot
sudo systemctl restart twitch-bot    # Restart bot
sudo systemctl status twitch-bot     # Check status

# View Logs
sudo journalctl -u twitch-bot -f     # Follow logs (live)
sudo journalctl -u twitch-bot -n 50  # Last 50 lines

# Update Bot
cd /root/twitch-bot
sudo ./scripts/update.sh             # Update and restart

# Uninstall
sudo ./scripts/uninstall.sh          # Remove service only
sudo ./scripts/uninstall.sh --purge  # Remove everything
```

## 🔑 Get Twitch Credentials

1. **Client ID & Secret**: https://dev.twitch.tv/console/apps
2. **OAuth Token**: https://twitchtokengenerator.com/

## 📍 Important Locations

- **Config**: `/opt/twitch-bot/.env`
- **Logs**: `sudo journalctl -u twitch-bot`
- **Install Dir**: `/opt/twitch-bot/`
- **Service File**: `/etc/systemd/system/twitch-bot.service`

## 🐛 Troubleshooting

```bash
# Bot won't start?
sudo journalctl -u twitch-bot -n 100

# Test manually
sudo -u twitchbot /opt/twitch-bot/venv/bin/python /opt/twitch-bot/run.py

# Fix permissions
sudo chown -R twitchbot:twitchbot /opt/twitch-bot
sudo chmod 600 /opt/twitch-bot/.env
```

## 📚 Full Documentation

See `DEPLOYMENT.md` for complete documentation.
