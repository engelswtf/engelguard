# Changelog

All notable changes to EngelGuard will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Operations
- Added comprehensive operations documentation for container-to-GitHub sync workflow
- Documented git state verification and synchronization procedures
- Created runbook for managing bot deployment in Proxmox LXC container 101

## [1.0.0] - 2024-12-07

### Added

#### Core Bot
- TwitchIO 2.x based bot with modular cog system
- Environment-based configuration with validation
- Secret filtering in logs (tokens never exposed)
- Systemd service with security hardening
- Graceful shutdown handling

#### Auto-Moderation
- Smart spam detection with pattern matching
- Lookalike character detection (catches "fr33 f0ll0w3rs")
- Configurable filters: caps, symbols, emotes, links, length
- URL whitelist/blacklist system
- Strike system with escalating punishments (warn → timeout → ban)
- Subscriber/VIP protection (immune to auto-bans)

#### Custom Commands
- Full custom command system with 20+ variables
- Permission levels (everyone to owner)
- User and global cooldowns
- Command aliases
- Dashboard management

#### Timers
- Scheduled message system
- Interval-based (5-120 minutes)
- Chat activity requirements
- Online-only mode
- Variable support in messages

#### Loyalty System (Optional)
- Watch time tracking
- Points for watching and chatting
- Subscriber/VIP multipliers
- Leaderboards
- Fully toggleable

#### Moderation Tools
- Nuke command for mass moderation
- Safety features (preview mode, user limits, excludes)
- Permit system for temporary link allowance
- Manual strike management

#### Stream Integration
- Clip creation via chat
- Title/game viewing and changing
- Uptime display
- Shoutout command
- Follow age checking

#### Web Dashboard
- Modern dark theme (Twitch-inspired)
- Real-time bot status
- Command management
- Timer management
- Filter configuration
- User management
- Mod log viewer
- Credential management
- Mobile responsive

#### Fun Commands
- Dice rolling (with D&D notation)
- Magic 8-ball
- Coin flip
- Hugs
- Rock, paper, scissors
- Random choice

### Security
- Runs as non-root user
- Systemd sandboxing
- Resource limits
- Session-based dashboard auth
- CSRF protection

---

## Future Plans

### [1.1.0] - Planned
- Quote system
- Giveaway system
- Song requests (YouTube)
- Activity logging to database
- Log viewer in dashboard

### [1.2.0] - Planned
- Polls and voting
- Channel point integration
- Discord integration
- Webhook support

---

*For feature requests, please open an issue on GitHub.*
