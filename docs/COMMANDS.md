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

---

## Song Request Commands

### Viewer Commands

| Command | Description | Example |
|---------|-------------|---------|
| `!sr <url>` | Request a song | `!sr https://youtube.com/watch?v=dQw4w9WgXcQ` |
| `!queue` | View the song queue | `!queue` |
| `!currentsong` | Show currently playing | `!currentsong` |
| `!wrongsong` | Remove your last request | `!wrongsong` |

**Aliases:**
- `!sr` = `!songrequest`, `!request`
- `!queue` = `!songlist`, `!sl`, `!songs`
- `!currentsong` = `!song`, `!nowplaying`, `!np`
- `!wrongsong` = `!removesong`, `!oops`

### Moderator Commands

| Command | Description | Example |
|---------|-------------|---------|
| `!sr on/off` | Enable/disable song requests | `!sr on` |
| `!skip` | Skip current song | `!skip` |
| `!volume <0-100>` | Set volume level | `!volume 75` |
| `!clearqueue` | Clear entire queue | `!clearqueue` |
| `!blacklist <url>` | Blacklist a song | `!blacklist https://youtube.com/...` |
| `!unblacklist <url>` | Remove from blacklist | `!unblacklist https://youtube.com/...` |
| `!promote <pos>` | Move song to front | `!promote 5` |
| `!play` | Start playing next song | `!play` |

**Aliases:**
- `!skip` = `!skipsong`, `!nextsong`
- `!volume` = `!vol`
- `!clearqueue` = `!clearq`, `!cq`
- `!blacklist` = `!bl`, `!bansong`
- `!unblacklist` = `!ubl`, `!unbansong`
- `!promote` = `!bump`

### Owner Commands

| Command | Description | Example |
|---------|-------------|---------|
| `!srset` | View current settings | `!srset` |
| `!srset maxqueue <n>` | Set max queue size | `!srset maxqueue 100` |
| `!srset maxduration <sec>` | Set max song duration | `!srset maxduration 300` |
| `!srset userlimit <n>` | Set requests per user | `!srset userlimit 5` |
| `!srset sublimit <n>` | Set requests per sub | `!srset sublimit 10` |

### Song Request Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | `false` | Whether song requests are enabled |
| `max_queue_size` | `50` | Maximum songs in queue |
| `max_duration_seconds` | `600` | Maximum song length (10 min) |
| `user_limit` | `3` | Max requests per regular user |
| `sub_limit` | `5` | Max requests per subscriber |
| `volume` | `50` | Default volume (0-100) |

### Notes

- Only YouTube URLs are supported (no search queries)
- Blacklisted songs are automatically removed from queue
- Subscribers get higher request limits than regular viewers
- Volume setting is stored for dashboard/OBS integration
- Actual audio playback is handled by external player (dashboard/OBS)
