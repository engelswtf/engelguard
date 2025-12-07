# 📋 EngelGuard Command Reference

Complete reference for all EngelGuard commands. See README.md for quick overview.

## Permission Levels

| Level | Description |
|-------|-------------|
| `everyone` | All viewers |
| `follower` | Followers only |
| `subscriber` | Subscribers only |
| `vip` | VIPs and above |
| `moderator` | Moderators and above |
| `owner` | Channel owner only |

## Variables for Custom Commands

| Variable | Description | Example |
|----------|-------------|---------|
| `$(user)` | Command caller | `StreamerName` |
| `$(target)` | Mentioned user | `TargetUser` |
| `$(channel)` | Channel name | `MyChannel` |
| `$(title)` | Stream title | `Playing games!` |
| `$(game)` | Current game | `Minecraft` |
| `$(uptime)` | Stream duration | `2h 30m` |
| `$(count)` | Use count | `42` |
| `$(args)` | All arguments | `hello world` |
| `$(random.1-100)` | Random number | `73` |
| `$(random.pick a,b,c)` | Random choice | `b` |
| `$(time)` | Current time | `3:45 PM` |
| `$(followage)` | Follow duration | `2 years` |
| `$(points)` | Point balance | `5000` |
| `$(urlfetch URL)` | Fetch from API | *response* |

*For full command details, see the main documentation.*
