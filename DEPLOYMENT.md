# Twitch Bot Deployment Guide

This guide covers deploying the Twitch bot on Proxmox (LXC container or VM) using systemd.

## 📋 Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Configuration](#configuration)
- [Service Management](#service-management)
- [Updating](#updating)
- [Uninstallation](#uninstallation)
- [Troubleshooting](#troubleshooting)
- [Security](#security)

---

## Prerequisites

### System Requirements

- **OS**: Debian 11+ or Ubuntu 20.04+
- **Python**: 3.9 or higher
- **Memory**: 512MB minimum (1GB recommended)
- **CPU**: 1 core minimum
- **Disk**: 2GB minimum
- **systemd**: Required for service management

### Proxmox Setup

#### Option 1: LXC Container (Recommended)

```bash
# Create Debian 12 LXC container
pct create 200 local:vztmpl/debian-12-standard_12.0-1_amd64.tar.zst \
  --hostname twitch-bot \
  --memory 1024 \
  --cores 2 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --storage local-lvm \
  --rootfs local-lvm:8 \
  --unprivileged 1 \
  --features nesting=1

# Start container
pct start 200

# Enter container
pct enter 200
```

#### Option 2: Virtual Machine

```bash
# Create VM with Debian 12 ISO
qm create 200 \
  --name twitch-bot \
  --memory 1024 \
  --cores 2 \
  --net0 virtio,bridge=vmbr0 \
  --scsihw virtio-scsi-pci \
  --scsi0 local-lvm:8

# Install Debian and proceed with installation
```

---

## Quick Start

```bash
# 1. Clone or copy bot files to /root/twitch-bot
cd /root/twitch-bot

# 2. Run installation script
sudo ./scripts/install.sh

# 3. Edit configuration
sudo nano /opt/twitch-bot/.env

# 4. Enable and start service
sudo systemctl enable twitch-bot
sudo systemctl start twitch-bot

# 5. Check status
sudo systemctl status twitch-bot
```

---

## Installation

### Step 1: Prepare Files

Ensure your bot files are in `/root/twitch-bot/`:

```
/root/twitch-bot/
├── src/
│   └── bot/
├── systemd/
│   └── twitch-bot.service
├── scripts/
│   ├── install.sh
│   ├── update.sh
│   └── uninstall.sh
├── requirements.txt
├── run.py
└── .env.example
```

### Step 2: Run Installation

```bash
cd /root/twitch-bot
sudo ./scripts/install.sh
```

The installation script will:

1. ✅ Create system user `twitchbot`
2. ✅ Create directories `/opt/twitch-bot` and `/var/log/twitch-bot`
3. ✅ Install system dependencies (Python, pip, venv)
4. ✅ Create Python virtual environment
5. ✅ Install Python packages from requirements.txt
6. ✅ Copy bot files to `/opt/twitch-bot`
7. ✅ Create `.env` file from `.env.example`
8. ✅ Install systemd service
9. ✅ Set proper permissions

### Step 3: Configure Environment

Edit the configuration file:

```bash
sudo nano /opt/twitch-bot/.env
```

**Required settings:**

```bash
# Twitch API Credentials (from https://dev.twitch.tv/console)
TWITCH_CLIENT_ID=your_client_id_here
TWITCH_CLIENT_SECRET=your_client_secret_here

# Bot Authentication (from https://twitchtokengenerator.com/)
TWITCH_OAUTH_TOKEN=oauth:your_token_here
TWITCH_REFRESH_TOKEN=your_refresh_token_here

# Bot Settings
TWITCH_BOT_NICK=your_bot_username
TWITCH_CHANNELS=channel1,channel2
BOT_PREFIX=!
BOT_OWNER=your_twitch_username

# Logging
LOG_LEVEL=INFO
```

### Step 4: Start Service

```bash
# Enable service to start on boot
sudo systemctl enable twitch-bot

# Start service now
sudo systemctl start twitch-bot

# Check status
sudo systemctl status twitch-bot
```

---

## Configuration

### Environment Variables

All configuration is done via `/opt/twitch-bot/.env`:

| Variable | Description | Required |
|----------|-------------|----------|
| `TWITCH_CLIENT_ID` | Twitch API Client ID | ✅ Yes |
| `TWITCH_CLIENT_SECRET` | Twitch API Client Secret | ✅ Yes |
| `TWITCH_OAUTH_TOKEN` | Bot OAuth token | ✅ Yes |
| `TWITCH_REFRESH_TOKEN` | OAuth refresh token | ✅ Yes |
| `TWITCH_BOT_NICK` | Bot username | ✅ Yes |
| `TWITCH_CHANNELS` | Channels to join (comma-separated) | ✅ Yes |
| `BOT_PREFIX` | Command prefix | No (default: `!`) |
| `BOT_OWNER` | Owner username | ✅ Yes |
| `LOG_LEVEL` | Logging level | No (default: `INFO`) |
| `DATABASE_URL` | Database connection string | No |

### Getting Twitch Credentials

1. **Client ID & Secret**:
   - Go to https://dev.twitch.tv/console/apps
   - Click "Register Your Application"
   - Set OAuth Redirect URL to `http://localhost:3000`
   - Copy Client ID and generate Client Secret

2. **OAuth Token**:
   - Visit https://twitchtokengenerator.com/
   - Select required scopes: `chat:read`, `chat:edit`, `channel:moderate`
   - Or use Twitch CLI: `twitch token -u -s "chat:read chat:edit"`

### Service Configuration

The systemd service is configured with:

- **User**: Runs as `twitchbot` (non-root)
- **Auto-restart**: Restarts on failure with exponential backoff
- **Resource limits**: 50% CPU, 512MB RAM max
- **Security hardening**: Multiple protections enabled
- **Logging**: All output to systemd journal

To modify service settings:

```bash
sudo nano /etc/systemd/system/twitch-bot.service
sudo systemctl daemon-reload
sudo systemctl restart twitch-bot
```

---

## Service Management

### Basic Commands

```bash
# Start service
sudo systemctl start twitch-bot

# Stop service
sudo systemctl stop twitch-bot

# Restart service
sudo systemctl restart twitch-bot

# Check status
sudo systemctl status twitch-bot

# Enable on boot
sudo systemctl enable twitch-bot

# Disable on boot
sudo systemctl disable twitch-bot
```

### Viewing Logs

```bash
# View all logs
sudo journalctl -u twitch-bot

# Follow logs in real-time
sudo journalctl -u twitch-bot -f

# View last 50 lines
sudo journalctl -u twitch-bot -n 50

# View logs since today
sudo journalctl -u twitch-bot --since today

# View logs with timestamps
sudo journalctl -u twitch-bot -o short-iso
```

### Health Checks

```bash
# Check if service is running
systemctl is-active twitch-bot

# Check if service is enabled
systemctl is-enabled twitch-bot

# View service details
systemctl show twitch-bot

# Check resource usage
systemctl status twitch-bot
```

---

## Updating

### Update from Local Files

If you've made changes to the bot code locally:

```bash
cd /root/twitch-bot
sudo ./scripts/update.sh
```

This will:
1. Create backup of current installation
2. Stop the service
3. Copy new files to `/opt/twitch-bot`
4. Update Python dependencies
5. Update systemd service file (if changed)
6. Restart the service

### Update from Git

If your bot is in a git repository:

```bash
cd /root/twitch-bot
sudo ./scripts/update.sh --from-git
```

### Update Without Restart

To update files without restarting:

```bash
sudo ./scripts/update.sh --no-restart

# Manually restart when ready
sudo systemctl restart twitch-bot
```

### Rollback on Failure

The update script automatically creates backups. If update fails, it will automatically rollback.

Manual rollback:

```bash
# Find backup
ls -la /tmp/twitch-bot-backup-*

# Restore manually
sudo rsync -a /tmp/twitch-bot-backup-YYYYMMDD_HHMMSS/ /opt/twitch-bot/
sudo systemctl restart twitch-bot
```

---

## Uninstallation

### Remove Service Only

Removes systemd service but keeps files:

```bash
cd /root/twitch-bot
sudo ./scripts/uninstall.sh
```

### Complete Removal

Removes service, files, logs, and user:

```bash
cd /root/twitch-bot
sudo ./scripts/uninstall.sh --purge
```

**Note**: Your `.env` file will be backed up to `/root/twitch-bot.env.backup.*` before deletion.

---

## Troubleshooting

### Service Won't Start

```bash
# Check service status
sudo systemctl status twitch-bot

# View detailed logs
sudo journalctl -u twitch-bot -n 100

# Check configuration
sudo cat /opt/twitch-bot/.env

# Test manually
sudo -u twitchbot /opt/twitch-bot/venv/bin/python /opt/twitch-bot/run.py
```

### Common Issues

#### 1. Permission Denied

```bash
# Fix permissions
sudo chown -R twitchbot:twitchbot /opt/twitch-bot
sudo chmod 600 /opt/twitch-bot/.env
```

#### 2. Module Not Found

```bash
# Reinstall dependencies
sudo -u twitchbot /opt/twitch-bot/venv/bin/pip install -r /opt/twitch-bot/requirements.txt
```

#### 3. OAuth Token Invalid

```bash
# Generate new token at https://twitchtokengenerator.com/
# Update .env file
sudo nano /opt/twitch-bot/.env
sudo systemctl restart twitch-bot
```

#### 4. Service Crashes Immediately

```bash
# Check Python syntax
sudo -u twitchbot /opt/twitch-bot/venv/bin/python -m py_compile /opt/twitch-bot/run.py

# Check for missing environment variables
sudo -u twitchbot /opt/twitch-bot/venv/bin/python -c "from dotenv import load_dotenv; load_dotenv('/opt/twitch-bot/.env'); import os; print(os.environ)"
```

### Debug Mode

Enable debug logging:

```bash
# Edit .env
sudo nano /opt/twitch-bot/.env

# Set LOG_LEVEL=DEBUG
LOG_LEVEL=DEBUG

# Restart service
sudo systemctl restart twitch-bot

# View debug logs
sudo journalctl -u twitch-bot -f
```

---

## Security

### Security Features

The systemd service includes extensive security hardening:

- ✅ Runs as non-root user (`twitchbot`)
- ✅ No privilege escalation (`NoNewPrivileges=true`)
- ✅ Read-only system files (`ProtectSystem=strict`)
- ✅ Private `/tmp` directory
- ✅ Kernel protections enabled
- ✅ System call filtering
- ✅ No capabilities required
- ✅ Network access restricted to IPv4/IPv6
- ✅ Memory protections enabled

### File Permissions

```bash
# .env file (secrets)
-rw------- 1 twitchbot twitchbot .env

# Bot directory
drwxr-xr-x 1 twitchbot twitchbot /opt/twitch-bot

# Data directory
drwxr-x--- 1 twitchbot twitchbot /opt/twitch-bot/data

# Log directory
drwxr-x--- 1 twitchbot twitchbot /var/log/twitch-bot
```

### Best Practices

1. **Never commit `.env` to version control**
2. **Rotate OAuth tokens regularly**
3. **Use strong, unique credentials**
4. **Keep system and dependencies updated**
5. **Monitor logs for suspicious activity**
6. **Limit bot permissions to minimum required**
7. **Use firewall to restrict network access**

### Firewall Configuration

```bash
# Allow only outbound HTTPS (Twitch API)
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw enable
```

---

## Monitoring

### Service Monitoring

```bash
# Create monitoring script
cat > /usr/local/bin/check-twitch-bot.sh << 'EOF'
#!/bin/bash
if ! systemctl is-active --quiet twitch-bot; then
    echo "Twitch bot is down!"
    systemctl restart twitch-bot
fi
EOF

chmod +x /usr/local/bin/check-twitch-bot.sh

# Add to crontab (check every 5 minutes)
(crontab -l 2>/dev/null; echo "*/5 * * * * /usr/local/bin/check-twitch-bot.sh") | crontab -
```

### Log Rotation

Systemd journal handles log rotation automatically, but you can configure it:

```bash
# Edit journal configuration
sudo nano /etc/systemd/journald.conf

# Set limits
SystemMaxUse=100M
SystemMaxFileSize=10M
MaxRetentionSec=1month

# Restart journald
sudo systemctl restart systemd-journald
```

---

## Files Created

### Installation Locations

```
/opt/twitch-bot/              # Bot installation directory
├── src/                      # Source code
├── venv/                     # Python virtual environment
├── data/                     # Bot data (database, etc.)
├── .env                      # Configuration (secrets)
├── run.py                    # Entry point
└── requirements.txt          # Python dependencies

/var/log/twitch-bot/          # Log directory (if needed)

/etc/systemd/system/
└── twitch-bot.service        # Systemd service file

/root/twitch-bot/             # Development directory
├── systemd/
│   └── twitch-bot.service    # Service template
├── scripts/
│   ├── install.sh            # Installation script
│   ├── update.sh             # Update script
│   └── uninstall.sh          # Uninstall script
└── DEPLOYMENT.md             # This file
```

---

## Support

### Useful Commands Reference

```bash
# Service management
sudo systemctl {start|stop|restart|status} twitch-bot
sudo systemctl {enable|disable} twitch-bot

# Logs
sudo journalctl -u twitch-bot [-f|-n 50|--since today]

# Configuration
sudo nano /opt/twitch-bot/.env

# Updates
sudo /root/twitch-bot/scripts/update.sh

# Manual run (for testing)
sudo -u twitchbot /opt/twitch-bot/venv/bin/python /opt/twitch-bot/run.py

# Check resource usage
systemctl status twitch-bot
ps aux | grep twitch-bot
```

### Getting Help

1. Check logs: `sudo journalctl -u twitch-bot -n 100`
2. Verify configuration: `sudo cat /opt/twitch-bot/.env`
3. Test manually: `sudo -u twitchbot /opt/twitch-bot/venv/bin/python /opt/twitch-bot/run.py`
4. Check permissions: `ls -la /opt/twitch-bot`

---

**Last Updated**: December 2025
