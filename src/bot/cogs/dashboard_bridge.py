"""
Dashboard-to-Bot message bridge.
Watches a JSON queue file AND database command queue for messages from the dashboard.
"""

import json
import asyncio
import sqlite3
from pathlib import Path
from twitchio.ext import commands

QUEUE_FILE = Path("/opt/twitch-bot/data/dashboard_queue.json")
DB_PATH = Path("/opt/twitch-bot/data/automod.db")


class DashboardBridge(commands.Cog):
    """Bridge between dashboard and bot for chat messages and commands."""
    
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._running = False
        self._task = None
        self._db_task = None
        QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    @commands.Cog.event()
    async def event_ready(self):
        """Start watching when bot is ready."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._watch_queue())
            self._db_task = asyncio.create_task(self._watch_db_queue())
            print("[DashboardBridge] Queue watcher started")
            print("[DashboardBridge] Database command watcher started")
    
    def cog_unload(self):
        """Stop the watchers."""
        self._running = False
        if self._task:
            self._task.cancel()
        if self._db_task:
            self._db_task.cancel()
    
    async def _watch_queue(self):
        """Watch the JSON queue file for new messages."""
        while self._running:
            try:
                await self._process_queue()
            except Exception as e:
                print(f"[DashboardBridge] JSON Queue Error: {e}")
            await asyncio.sleep(1)
    
    async def _watch_db_queue(self):
        """Watch the database command queue for new commands."""
        while self._running:
            try:
                await self._process_db_queue()
            except Exception as e:
                print(f"[DashboardBridge] DB Queue Error: {e}")
            await asyncio.sleep(2)
    
    async def _process_queue(self):
        """Process messages in the JSON queue."""
        if not QUEUE_FILE.exists():
            return
        
        try:
            content = QUEUE_FILE.read_text().strip()
            if not content:
                return
            messages = json.loads(content)
        except (json.JSONDecodeError, IOError):
            return
        
        if not messages:
            return
        
        # Clear the queue
        QUEUE_FILE.write_text("[]")
        
        # Send each message
        for msg in messages:
            channel_name = msg.get("channel", "").lower()
            text = msg.get("message", "")
            
            if not channel_name or not text:
                continue
            
            # Find the channel
            for channel in self.bot.connected_channels:
                if channel.name.lower() == channel_name:
                    try:
                        await channel.send(text)
                        print(f"[DashboardBridge] Sent to {channel_name}: {text[:50]}...")
                    except Exception as e:
                        print(f"[DashboardBridge] Failed to send to {channel_name}: {e}")
                    break
    
    async def _process_db_queue(self):
        """Process commands in the database queue."""
        if not DB_PATH.exists():
            return
        
        try:
            conn = sqlite3.connect(str(DB_PATH))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Check if table exists
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='bot_command_queue'
            """)
            if not cursor.fetchone():
                conn.close()
                return
            
            # Get unprocessed commands
            cursor.execute("""
                SELECT id, channel, command, args 
                FROM bot_command_queue 
                WHERE processed = 0
                ORDER BY created_at ASC
                LIMIT 10
            """)
            commands_to_process = cursor.fetchall()
            
            for cmd in commands_to_process:
                cmd_id = cmd["id"]
                channel_name = cmd["channel"].lower()
                command = cmd["command"]
                args = cmd["args"] or ""
                
                # Process the command
                success = await self._execute_command(channel_name, command, args)
                
                # Mark as processed
                cursor.execute(
                    "UPDATE bot_command_queue SET processed = 1 WHERE id = ?",
                    (cmd_id,)
                )
                conn.commit()
                
                if success:
                    print(f"[DashboardBridge] Executed {command} for {args} in {channel_name}")
                else:
                    print(f"[DashboardBridge] Failed to execute {command} in {channel_name}")
            
            conn.close()
            
        except Exception as e:
            print(f"[DashboardBridge] DB Error: {e}")
    
    async def _execute_command(self, channel_name: str, command: str, args: str) -> bool:
        """Execute a command from the queue."""
        # Find the channel
        target_channel = None
        for channel in self.bot.connected_channels:
            if channel.name.lower() == channel_name:
                target_channel = channel
                break
        
        if not target_channel:
            print(f"[DashboardBridge] Channel {channel_name} not found")
            return False
        
        try:
            if command == "shoutout":
                # Execute shoutout
                await self._do_shoutout(target_channel, args)
                return True
            elif command == "message":
                # Send a raw message
                await target_channel.send(args)
                return True
            else:
                print(f"[DashboardBridge] Unknown command: {command}")
                return False
        except Exception as e:
            print(f"[DashboardBridge] Command execution error: {e}")
            return False
    
    async def _do_shoutout(self, channel, username: str) -> None:
        """Execute a shoutout for a user."""
        username = username.lstrip("@").lower()
        
        # Get display name
        display_name = username
        try:
            users = await self.bot.fetch_users(names=[username])
            if users:
                display_name = users[0].display_name or users[0].name
        except Exception as e:
            print(f"[DashboardBridge] Failed to fetch user {username}: {e}")
        
        # Try to get the shoutout cog for proper message formatting
        shoutout_cog = self.bot.get_cog("ShoutoutCog")
        
        if shoutout_cog:
            try:
                # Get last game from Twitch API
                last_game = await shoutout_cog._get_last_game(username)
                settings = shoutout_cog._get_shoutout_settings(channel.name)
                
                # Parse the message template
                message = shoutout_cog._parse_shoutout_variables(
                    settings.message,
                    user=display_name,
                    game=last_game,
                    channel=channel.name,
                )
                
                # Update cooldown
                shoutout_cog._update_shoutout_cooldown(channel.name, username)
            except Exception as e:
                print(f"[DashboardBridge] Shoutout cog error: {e}")
                message = f"Go check out @{display_name} at twitch.tv/{username}! 💜"
        else:
            # Fallback if cog not available
            message = f"Go check out @{display_name} at twitch.tv/{username}! 💜"
        
        await channel.send(message)
        print(f"[DashboardBridge] Shoutout sent for {display_name}")


def prepare(bot: commands.Bot):
    """Prepare function required by TwitchIO."""
    bot.add_cog(DashboardBridge(bot))
