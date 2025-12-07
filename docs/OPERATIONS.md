# EngelGuard Operations Guide

This document provides operational procedures for managing the EngelGuard Twitch bot deployment in production.

## 📋 Table of Contents

- [Deployment Overview](#deployment-overview)
- [Container Access](#container-access)
- [Git Synchronization](#git-synchronization)
- [Verification Procedures](#verification-procedures)
- [Troubleshooting](#troubleshooting)
- [Maintenance History](#maintenance-history)

---

## Deployment Overview

### Production Environment

- **Platform**: Proxmox VE
- **Container**: LXC Container 101
- **OS**: Debian-based Linux
- **Bot Location**: `/opt/twitch-bot/`
- **GitHub Repository**: https://github.com/engelswtf/engelguard
- **Branch**: `main`

### Key Directories

```
Container 101: /opt/twitch-bot/
├── src/                    # Bot source code
├── dashboard/              # Web dashboard
├── docs/                   # Documentation
├── scripts/                # Deployment scripts
├── .git/                   # Git repository
├── .env                    # Configuration (secrets)
└── venv/                   # Python virtual environment

Host: /tmp/engelguard-temp/
└── (temporary clone for git operations)
```

---

## Container Access

### From Proxmox Host

Execute commands in container 101:

```bash
# Single command
pct exec 101 -- <command>

# Interactive shell
pct enter 101

# Examples
pct exec 101 -- systemctl status twitch-bot
pct exec 101 -- git -C /opt/twitch-bot status
pct exec 101 -- journalctl -u twitch-bot -n 50
```

### Direct SSH (if configured)

```bash
ssh root@<container-ip>
cd /opt/twitch-bot
```

---

## Git Synchronization

### Overview

The bot runs in an LXC container with its own git repository. To push changes to GitHub, we use a workflow that:

1. Clones the remote repo to the Proxmox host
2. Copies container files to the cloned repo
3. Commits and pushes from the host using GitHub CLI authentication

This approach avoids storing GitHub credentials in the container.

### Prerequisites

**On Proxmox Host:**

- GitHub CLI (`gh`) installed and authenticated
- Access to container 101
- Temporary workspace (e.g., `/tmp/engelguard-temp/`)

**Verify GitHub CLI authentication:**

```bash
gh auth status
```

Expected output:
```
✓ Logged in to github.com as engelswtf
```

### Sync Workflow: Container → GitHub

#### Step 1: Verify Container State

Check what changes exist in the container:

```bash
# Check git status
pct exec 101 -- git -C /opt/twitch-bot status

# View recent commits
pct exec 101 -- git -C /opt/twitch-bot log --oneline -5

# Check for uncommitted changes
pct exec 101 -- git -C /opt/twitch-bot diff --stat
```

#### Step 2: Clone Remote Repository (Host)

Create a temporary clone on the Proxmox host:

```bash
# Clone to temporary directory
cd /tmp
git clone https://github.com/engelswtf/engelguard.git engelguard-temp
cd engelguard-temp

# Verify current state
git log --oneline -5
git status
```

#### Step 3: Copy Container Files to Host Clone

Copy files from container to host, excluding git metadata and runtime files:

```bash
# Create temporary directory for container files
mkdir -p /tmp/container-files

# Copy files from container (excluding .git, venv, data, cache, .env)
pct exec 101 -- tar -C /opt/twitch-bot \
  --exclude='.git' \
  --exclude='venv' \
  --exclude='data' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.env' \
  --exclude='*.log' \
  -czf - . | tar -C /tmp/container-files -xzf -

# Sync to cloned repo (preserving existing .git)
rsync -av --delete \
  --exclude='.git' \
  --exclude='venv' \
  --exclude='data' \
  --exclude='__pycache__' \
  --exclude='.env' \
  /tmp/container-files/ /tmp/engelguard-temp/

# Clean up temporary files
rm -rf /tmp/container-files
```

#### Step 4: Review Changes

Check what changed:

```bash
cd /tmp/engelguard-temp

# View changed files
git status

# View detailed changes
git diff

# View staged changes (if any)
git diff --staged
```

#### Step 5: Commit Changes (if any)

If there are changes to commit:

```bash
cd /tmp/engelguard-temp

# Stage changes
git add .

# Commit with descriptive message
git commit -m "Your descriptive commit message here"

# Example:
# git commit -m "Update bot comparison guide with feature matrix"
```

#### Step 6: Push to GitHub

Push using GitHub CLI for authentication:

```bash
cd /tmp/engelguard-temp

# Push to main branch
GIT_DISCOVERY_ACROSS_FILESYSTEM=1 \
GIT_CONFIG_COUNT=1 \
GIT_CONFIG_KEY_0=credential.helper \
GIT_CONFIG_VALUE_0='!gh auth git-credential' \
git push origin main

# Verify push succeeded
git log --oneline -3
```

**Environment Variables Explained:**

- `GIT_DISCOVERY_ACROSS_FILESYSTEM=1` - Allows git to work across filesystem boundaries
- `GIT_CONFIG_COUNT=1` - Number of config overrides
- `GIT_CONFIG_KEY_0=credential.helper` - Config key to override
- `GIT_CONFIG_VALUE_0='!gh auth git-credential'` - Use GitHub CLI for credentials

#### Step 7: Update Container Git State (Optional)

If you want the container's git repo to reflect the remote state:

```bash
# Fetch latest from remote
pct exec 101 -- git -C /opt/twitch-bot fetch origin

# Reset to match remote (CAUTION: discards local commits)
pct exec 101 -- git -C /opt/twitch-bot reset --hard origin/main

# Verify state
pct exec 101 -- git -C /opt/twitch-bot log --oneline -3
pct exec 101 -- git -C /opt/twitch-bot status
```

⚠️ **Warning**: `git reset --hard` will discard any local commits in the container. Only use this if you've already pushed those changes to GitHub.

### Quick Sync Script

For convenience, here's a complete sync script:

```bash
#!/bin/bash
# sync-bot-to-github.sh - Sync container bot to GitHub

set -e

CONTAINER_ID=101
BOT_PATH="/opt/twitch-bot"
TEMP_DIR="/tmp/engelguard-temp"
REPO_URL="https://github.com/engelswtf/engelguard.git"

echo "=== EngelGuard Container → GitHub Sync ==="

# Step 1: Check container state
echo "[1/6] Checking container git state..."
pct exec $CONTAINER_ID -- git -C $BOT_PATH status

# Step 2: Clone or update temp repo
if [ -d "$TEMP_DIR" ]; then
    echo "[2/6] Updating existing clone..."
    cd $TEMP_DIR
    git fetch origin
    git reset --hard origin/main
else
    echo "[2/6] Cloning repository..."
    git clone $REPO_URL $TEMP_DIR
    cd $TEMP_DIR
fi

# Step 3: Copy container files
echo "[3/6] Copying files from container..."
mkdir -p /tmp/container-files
pct exec $CONTAINER_ID -- tar -C $BOT_PATH \
  --exclude='.git' \
  --exclude='venv' \
  --exclude='data' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.env' \
  --exclude='*.log' \
  -czf - . | tar -C /tmp/container-files -xzf -

rsync -av --delete \
  --exclude='.git' \
  --exclude='venv' \
  --exclude='data' \
  --exclude='__pycache__' \
  --exclude='.env' \
  /tmp/container-files/ $TEMP_DIR/

rm -rf /tmp/container-files

# Step 4: Check for changes
echo "[4/6] Checking for changes..."
cd $TEMP_DIR
if git diff --quiet && git diff --cached --quiet; then
    echo "✓ No changes to push"
    exit 0
fi

git status

# Step 5: Commit
echo "[5/6] Committing changes..."
git add .
read -p "Enter commit message: " COMMIT_MSG
git commit -m "$COMMIT_MSG"

# Step 6: Push
echo "[6/6] Pushing to GitHub..."
GIT_DISCOVERY_ACROSS_FILESYSTEM=1 \
GIT_CONFIG_COUNT=1 \
GIT_CONFIG_KEY_0=credential.helper \
GIT_CONFIG_VALUE_0='!gh auth git-credential' \
git push origin main

echo "✓ Sync complete!"
git log --oneline -3
```

**Usage:**

```bash
chmod +x sync-bot-to-github.sh
./sync-bot-to-github.sh
```

---

## Verification Procedures

### Verify Container Git State

Check if container is in sync with remote:

```bash
# Check current commit
pct exec 101 -- git -C /opt/twitch-bot rev-parse HEAD

# Check remote commit
pct exec 101 -- git -C /opt/twitch-bot rev-parse origin/main

# Compare (should be identical if in sync)
pct exec 101 -- bash -c 'cd /opt/twitch-bot && \
  LOCAL=$(git rev-parse HEAD) && \
  REMOTE=$(git rev-parse origin/main) && \
  if [ "$LOCAL" = "$REMOTE" ]; then \
    echo "✓ In sync with remote"; \
  else \
    echo "✗ Diverged from remote"; \
    echo "Local:  $LOCAL"; \
    echo "Remote: $REMOTE"; \
  fi'
```

### Verify File Synchronization

Check if container files match GitHub:

```bash
# Clone fresh copy
cd /tmp
git clone https://github.com/engelswtf/engelguard.git engelguard-verify
cd engelguard-verify

# Copy container files
mkdir -p /tmp/container-verify
pct exec 101 -- tar -C /opt/twitch-bot \
  --exclude='.git' \
  --exclude='venv' \
  --exclude='data' \
  --exclude='__pycache__' \
  --exclude='.env' \
  -czf - . | tar -C /tmp/container-verify -xzf -

# Compare
diff -r --exclude='.git' --exclude='venv' --exclude='data' \
  /tmp/container-verify/ /tmp/engelguard-verify/

# No output = files are identical
# Output = shows differences
```

### Verify Bot Service Status

```bash
# Check if bot is running
pct exec 101 -- systemctl status twitch-bot

# Check recent logs
pct exec 101 -- journalctl -u twitch-bot -n 50 --no-pager

# Check bot connectivity
pct exec 101 -- journalctl -u twitch-bot --since "5 minutes ago" | grep -i "connected\|joined"
```

---

## Troubleshooting

### Issue: Container Git History Diverged

**Symptoms:**
- `git status` shows "Your branch and 'origin/main' have diverged"
- Local commits don't exist on GitHub
- Remote commits don't exist locally

**Diagnosis:**

```bash
# Check divergence
pct exec 101 -- git -C /opt/twitch-bot log --oneline --graph --all -10

# Compare commits
pct exec 101 -- git -C /opt/twitch-bot log origin/main..HEAD  # Local commits not on remote
pct exec 101 -- git -C /opt/twitch-bot log HEAD..origin/main  # Remote commits not local
```

**Solution 1: Keep Container Changes (Push to GitHub)**

If container has important changes:

```bash
# Use the sync workflow above to push container changes to GitHub
./sync-bot-to-github.sh
```

**Solution 2: Discard Container Changes (Reset to Remote)**

If remote is authoritative:

```bash
# Backup container state first (optional)
pct exec 101 -- git -C /opt/twitch-bot log --oneline -10 > /tmp/container-commits-backup.txt

# Reset to remote
pct exec 101 -- git -C /opt/twitch-bot fetch origin
pct exec 101 -- git -C /opt/twitch-bot reset --hard origin/main

# Verify
pct exec 101 -- git -C /opt/twitch-bot status
```

**Solution 3: Fresh Clone in Container**

If git state is corrupted:

```bash
# Backup .env and data
pct exec 101 -- cp /opt/twitch-bot/.env /tmp/bot.env.backup
pct exec 101 -- tar -czf /tmp/bot-data-backup.tar.gz -C /opt/twitch-bot/data .

# Remove old repo
pct exec 101 -- rm -rf /opt/twitch-bot

# Clone fresh
pct exec 101 -- git clone https://github.com/engelswtf/engelguard.git /opt/twitch-bot

# Restore .env and data
pct exec 101 -- cp /tmp/bot.env.backup /opt/twitch-bot/.env
pct exec 101 -- tar -xzf /tmp/bot-data-backup.tar.gz -C /opt/twitch-bot/data/

# Fix permissions
pct exec 101 -- chown -R twitchbot:twitchbot /opt/twitch-bot

# Restart bot
pct exec 101 -- systemctl restart twitch-bot
```

### Issue: Cannot Push from Host

**Symptoms:**
- `git push` fails with authentication error
- "Permission denied" or "Could not read from remote repository"

**Solution:**

```bash
# Verify GitHub CLI authentication
gh auth status

# If not authenticated, login
gh auth login

# Test authentication
gh auth git-credential

# Retry push with explicit credential helper
cd /tmp/engelguard-temp
GIT_DISCOVERY_ACROSS_FILESYSTEM=1 \
GIT_CONFIG_COUNT=1 \
GIT_CONFIG_KEY_0=credential.helper \
GIT_CONFIG_VALUE_0='!gh auth git-credential' \
git push origin main
```

### Issue: File Differences After Sync

**Symptoms:**
- `git status` shows clean, but files differ between container and GitHub
- Sync appears successful but changes not reflected

**Diagnosis:**

```bash
# Check last sync time
ls -la /tmp/engelguard-temp/

# Check container file timestamps
pct exec 101 -- ls -la /opt/twitch-bot/

# Manually compare specific file
pct exec 101 -- cat /opt/twitch-bot/README.md > /tmp/container-readme.md
curl -s https://raw.githubusercontent.com/engelswtf/engelguard/main/README.md > /tmp/github-readme.md
diff /tmp/container-readme.md /tmp/github-readme.md
```

**Solution:**

Re-run the sync workflow, ensuring all steps complete:

```bash
# Clean temp directory
rm -rf /tmp/engelguard-temp

# Re-run sync from scratch
./sync-bot-to-github.sh
```

---

## Maintenance History

### 2025-12-07 21:00 - Git State Verification and Sync

**Issue:**
Container git repository had diverged from remote (local commits 0b85143, ce7fa5c vs remote starting at a3699ed).

**Actions Taken:**

1. Investigated container git state in `/opt/twitch-bot/`
2. Cloned remote repository to `/tmp/engelguard-temp` on host
3. Copied container files (excluding .git, venv, data, __pycache__, .env) to cloned repo
4. Compared files - discovered no actual differences
5. Confirmed container was already synced with remote at 21:00 UTC

**Findings:**

- Container git repo was resynced at 21:00 on Dec 7, 2025
- No pending changes to push
- Container and GitHub fully synchronized at commit `6e1d846`
- Working tree clean

**Current State:**

```
Container: /opt/twitch-bot/
├── Commit: 6e1d846 "Update tagline to emphasize open-source alternative to top bots"
├── Branch: main
├── Status: Clean working tree
└── Remote: In sync with origin/main

GitHub: https://github.com/engelswtf/engelguard
├── Latest commit: 6e1d846
└── Branch: main
```

**Verification Commands Used:**

```bash
# Container state
pct exec 101 -- git -C /opt/twitch-bot status
pct exec 101 -- git -C /opt/twitch-bot log --oneline -5

# File comparison
diff -r --exclude='.git' --exclude='venv' --exclude='data' \
  /tmp/container-files/ /tmp/engelguard-temp/

# Result: No differences found
```

**Lessons Learned:**

1. Container git history can diverge from remote if commits are made locally
2. File synchronization can be verified independently of git state
3. The sync workflow (clone → copy → commit → push) is reliable for pushing container changes
4. Always verify both git state AND file contents when troubleshooting sync issues

**Documentation Created:**

- Added this OPERATIONS.md guide
- Updated CHANGELOG.md with operations section
- Documented complete sync workflow for future reference

---

## Best Practices

### Regular Maintenance

1. **Weekly**: Verify container is in sync with GitHub
2. **After changes**: Always sync container changes to GitHub within 24 hours
3. **Before updates**: Verify clean git state before pulling updates
4. **After incidents**: Document in Maintenance History section

### Git Hygiene

- ✅ Always commit with descriptive messages
- ✅ Keep container and GitHub in sync
- ✅ Never commit secrets (.env files)
- ✅ Use .gitignore for runtime files (venv, data, logs)
- ✅ Document significant changes in CHANGELOG.md

### Backup Strategy

Before major changes:

```bash
# Backup entire container
pct backup 101 --storage local --compress zstd

# Backup bot data only
pct exec 101 -- tar -czf /tmp/bot-backup-$(date +%Y%m%d).tar.gz \
  -C /opt/twitch-bot \
  --exclude='venv' \
  --exclude='__pycache__' \
  .
```

---

## Quick Reference

### Common Commands

```bash
# Container access
pct exec 101 -- <command>
pct enter 101

# Git status
pct exec 101 -- git -C /opt/twitch-bot status

# Bot service
pct exec 101 -- systemctl status twitch-bot
pct exec 101 -- journalctl -u twitch-bot -f

# Sync to GitHub
./sync-bot-to-github.sh

# Verify sync
pct exec 101 -- git -C /opt/twitch-bot log --oneline -3
```

### Important Paths

- **Container bot**: `/opt/twitch-bot/`
- **Host temp clone**: `/tmp/engelguard-temp/`
- **GitHub repo**: https://github.com/engelswtf/engelguard
- **Container ID**: 101

### Key Files

- `.env` - Bot configuration (secrets, never commit)
- `requirements.txt` - Python dependencies
- `systemd/twitch-bot.service` - Service definition
- `CHANGELOG.md` - Version history
- `docs/OPERATIONS.md` - This file

---

**Last Updated**: 2025-12-07  
**Maintained By**: System Operations  
**Related Docs**: [DEPLOYMENT.md](../DEPLOYMENT.md), [CHANGELOG.md](../CHANGELOG.md)
