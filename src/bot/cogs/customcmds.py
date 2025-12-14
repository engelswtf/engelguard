"""
Custom commands cog for Twitch bot.

Allows creation and management of custom chat commands with:
- Dynamic variables
- Permission levels
- Cooldowns
- Aliases
- Usage tracking
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Optional, Any

from twitchio.ext import commands
from twitchio.ext.commands import Context

from bot.utils.database import get_database, DatabaseManager
from bot.utils.logging import get_logger
from bot.utils.permissions import is_owner, is_moderator
from bot.utils.variables import get_variable_parser, VariableParser, VARIABLE_DOCS

if TYPE_CHECKING:
    from twitchio import Message
    from bot.bot import TwitchBot

logger = get_logger(__name__)


# Permission levels in order
PERMISSION_LEVELS = ['everyone', 'follower', 'subscriber', 'vip', 'moderator', 'owner']

# Protected command names that cannot be used as custom commands or aliases
PROTECTED_COMMANDS = {
    'help', 'commands', 'points', 'gamble', 'slots', 'roulette', 'duel',
    'giveaway', 'enter', 'quote', 'addquote', 'poll', 'vote', 'predict', 'bet',
    'sr', 'songrequest', 'skip', 'queue', 'np', 'nowplaying',
    'followage', 'uptime', 'title', 'game', 'shoutout', 'so',
    'timeout', 'ban', 'unban', 'permit', 'nuke',
    'addcmd', 'editcmd', 'delcmd', 'cmdalias', 'cmdinfo',
    'timer', 'addtimer', 'deltimer', 'timers',
    'filter', 'automod', 'settings', 'bot'
}


class CustomCommands(commands.Cog):
    """
    Custom commands cog for user-defined commands.
    
    Features:
    - Create/edit/delete custom commands
    - Dynamic variable support
    - Permission levels
    - User and global cooldowns
    - Command aliases
    - Usage statistics
    """
    
    def __init__(self, bot: TwitchBot) -> None:
        """Initialize the custom commands cog."""
        self.bot = bot
        self.db: DatabaseManager = get_database()
        self.parser: VariableParser = get_variable_parser(bot)
        
        # Cooldown tracking: {command_name: {user_id: last_use, '_global': last_use}}
        self._cooldowns: dict[str, dict[str, datetime]] = {}
        
        logger.info("CustomCommands cog initialized")
    
    def _check_permission(
        self,
        required_level: str,
        is_owner: bool,
        is_mod: bool,
        is_vip: bool,
        is_subscriber: bool,
        is_follower: bool = None  # Assume follower if we cant check
    ) -> bool:
        """Check if user meets permission requirement."""
        if required_level == "everyone":
            return True
        if required_level == "follower":
            return (is_follower is True) or is_subscriber or is_vip or is_mod or is_owner
        if required_level == "subscriber":
            return is_subscriber or is_vip or is_mod or is_owner
        if required_level == "vip":
            return is_vip or is_mod or is_owner
        if required_level == "moderator":
            return is_mod or is_owner
        if required_level == "owner":
            return is_owner
        return False
    
    def _check_cooldown(
        self,
        command_name: str,
        user_id: str,
        cooldown_user: int,
        cooldown_global: int
    ) -> tuple[bool, int]:
        """
        Check if command is on cooldown.
        
        Returns:
            tuple: (is_on_cooldown, seconds_remaining)
        """
        now = datetime.now(timezone.utc)
        
        if command_name not in self._cooldowns:
            self._cooldowns[command_name] = {}
        
        cooldowns = self._cooldowns[command_name]
        
        # Check global cooldown
        if cooldown_global > 0 and '_global' in cooldowns:
            elapsed = (now - cooldowns['_global']).total_seconds()
            if elapsed < cooldown_global:
                return True, int(cooldown_global - elapsed)
        
        # Check user cooldown
        if cooldown_user > 0 and user_id in cooldowns:
            elapsed = (now - cooldowns[user_id]).total_seconds()
            if elapsed < cooldown_user:
                return True, int(cooldown_user - elapsed)
        
        return False, 0
    
    def _update_cooldown(self, command_name: str, user_id: str) -> None:
        """Update cooldown timestamps."""
        now = datetime.now(timezone.utc)
        
        if command_name not in self._cooldowns:
            self._cooldowns[command_name] = {}
        
        self._cooldowns[command_name][user_id] = now
        self._cooldowns[command_name]['_global'] = now
    
    @commands.Cog.event()
    async def event_message(self, message: Message) -> None:
        """Process messages to check for custom commands."""
        if message.echo or not message.author or not message.content:
            return
        
        # Check if message starts with command prefix
        prefix = self.bot.config.prefix
        if not message.content.startswith(prefix):
            return
        
        # Extract command name
        content = message.content[len(prefix):]
        parts = content.split(maxsplit=1)
        if not parts:
            return
        
        cmd_name = parts[0].lower()
        args = parts[1].split() if len(parts) > 1 else []
        
        # Check if its a custom command
        cmd = self.db.get_command(cmd_name)
        if not cmd:
            return
        
        # Get user info
        user_id = str(message.author.id)
        username = message.author.name
        is_owner_user = username.lower() == self.bot.config.owner.lower()
        is_mod = getattr(message.author, 'is_mod', False)
        is_vip = getattr(message.author, 'is_vip', False)
        is_subscriber = getattr(message.author, 'is_subscriber', False)
        
        # Check permission
        required_level = cmd.get('permission_level', 'everyone')
        if not self._check_permission(required_level, is_owner_user, is_mod, is_vip, is_subscriber):
            return  # Silently ignore if no permission
        
        # Check cooldown
        on_cooldown, remaining = self._check_cooldown(
            cmd['name'],
            user_id,
            cmd.get('cooldown_user', 5),
            cmd.get('cooldown_global', 0)
        )
        if on_cooldown:
            # Silently ignore cooldown for non-mods
            if is_mod or is_owner_user:
                await message.channel.send(f"@{username} Command on cooldown ({remaining}s)")
            return
        
        # Parse variables in response
        response = await self.parser.parse(
            template=cmd['response'],
            message=message,
            channel=message.channel,
            user=username,
            user_id=user_id,
            args=args,
            command_count=cmd.get('use_count', 0) + 1,
            is_subscriber=is_subscriber,
            is_vip=is_vip,
            is_mod=is_mod
        )
        
        # Send response
        await message.channel.send(response)
        
        # Update usage and cooldown
        self.db.increment_command_usage(cmd['name'])
        self._update_cooldown(cmd['name'], user_id)
        
        logger.debug("Custom command %s used by %s", cmd['name'], username)
    
    # ==================== Management Commands ====================
    
    @commands.command(name="addcmd")
    @is_moderator()
    async def add_command(self, ctx: Context, name: str = "", *, response: str = "") -> None:
        """
        Add a new custom command with name collision detection.
        
        Usage: !addcmd <name> <response>
        Example: !addcmd hello Hello $(user)! Welcome to the stream!
        """
        if not name or not response:
            await ctx.send(f"@{ctx.author.name} Usage: !addcmd <name> <response>")
            return
        
        name = name.lower().lstrip("!")
        
        # SECURITY: Check for collision with protected commands
        if name in PROTECTED_COMMANDS:
            await ctx.send(f"@{ctx.author.name} Cannot create command '!{name}' - it's a protected command name.")
            return
        
        # Check if command already exists
        existing = self.db.get_command(name)
        if existing:
            await ctx.send(f"@{ctx.author.name} Command !{name} already exists. Use !editcmd to modify.")
            return
        
        # Check if it conflicts with built-in commands
        if name in [cmd.name for cmd in self.bot.commands.values()]:
            await ctx.send(f"@{ctx.author.name} Cannot override built-in command !{name}")
            return
        
        try:
            self.db.create_command(
                name=name,
                response=response,
                created_by=ctx.author.name
            )
            await ctx.send(f"@{ctx.author.name} Command !{name} created successfully!")
            logger.info("Command !%s created by %s", name, ctx.author.name)
        except Exception as e:
            logger.error("Failed to create command: %s", e)
            await ctx.send(f"@{ctx.author.name} Failed to create command.")
    
    @commands.command(name="editcmd")
    @is_moderator()
    async def edit_command(self, ctx: Context, name: str = "", *, response: str = "") -> None:
        """
        Edit an existing custom command.
        
        Usage: !editcmd <name> <new response>
        """
        if not name or not response:
            await ctx.send(f"@{ctx.author.name} Usage: !editcmd <name> <new response>")
            return
        
        name = name.lower().lstrip("!")
        
        existing = self.db.get_command(name)
        if not existing:
            await ctx.send(f"@{ctx.author.name} Command !{name} does not exist.")
            return
        
        self.db.update_command(name, response=response)
        await ctx.send(f"@{ctx.author.name} Command !{name} updated!")
        logger.info("Command !%s edited by %s", name, ctx.author.name)
    
    @commands.command(name="delcmd")
    @is_moderator()
    async def delete_command(self, ctx: Context, name: str = "") -> None:
        """
        Delete a custom command.
        
        Usage: !delcmd <name>
        """
        if not name:
            await ctx.send(f"@{ctx.author.name} Usage: !delcmd <name>")
            return
        
        name = name.lower().lstrip("!")
        
        if self.db.delete_command(name):
            await ctx.send(f"@{ctx.author.name} Command !{name} deleted.")
            logger.info("Command !%s deleted by %s", name, ctx.author.name)
        else:
            await ctx.send(f"@{ctx.author.name} Command !{name} not found.")
    
    @commands.command(name="cmdinfo")
    @is_moderator()
    async def command_info(self, ctx: Context, name: str = "") -> None:
        """
        Show information about a custom command.
        
        Usage: !cmdinfo <name>
        """
        if not name:
            await ctx.send(f"@{ctx.author.name} Usage: !cmdinfo <name>")
            return
        
        name = name.lower().lstrip("!")
        cmd = self.db.get_command(name)
        
        if not cmd:
            await ctx.send(f"@{ctx.author.name} Command !{name} not found.")
            return
        
        uses = cmd.get('use_count', 0)
        perm = cmd.get('permission_level', 'everyone')
        cd_user = cmd.get('cooldown_user', 5)
        cd_global = cmd.get('cooldown_global', 0)
        enabled = "Yes" if cmd.get('enabled', True) else "No"
        
        aliases_json = cmd.get('aliases')
        aliases = json.loads(aliases_json) if aliases_json else []
        alias_str = f" | Aliases: {', '.join(aliases)}" if aliases else ""
        
        await ctx.send(
            f"@{ctx.author.name} !{name}: Uses: {uses} | Perm: {perm} | "
            f"CD: {cd_user}s user, {cd_global}s global | Enabled: {enabled}{alias_str}"
        )
    
    @commands.command(name="cmdperm")
    @is_moderator()
    async def set_permission(self, ctx: Context, name: str = "", level: str = "") -> None:
        """
        Set permission level for a command.
        
        Usage: !cmdperm <name> <level>
        Levels: everyone, follower, subscriber, vip, moderator, owner
        """
        if not name or not level:
            await ctx.send(
                f"@{ctx.author.name} Usage: !cmdperm <name> <level> | "
                f"Levels: {', '.join(PERMISSION_LEVELS)}"
            )
            return
        
        name = name.lower().lstrip("!")
        level = level.lower()
        
        if level not in PERMISSION_LEVELS:
            await ctx.send(f"@{ctx.author.name} Invalid level. Use: {', '.join(PERMISSION_LEVELS)}")
            return
        
        if self.db.update_command(name, permission_level=level):
            await ctx.send(f"@{ctx.author.name} !{name} permission set to {level}")
        else:
            await ctx.send(f"@{ctx.author.name} Command !{name} not found.")
    
    @commands.command(name="cmdcd")
    @is_moderator()
    async def set_cooldown(self, ctx: Context, name: str = "", user_cd: str = "5", global_cd: str = "0") -> None:
        """
        Set cooldowns for a command.
        
        Usage: !cmdcd <name> <user_seconds> [global_seconds]
        """
        if not name:
            await ctx.send(f"@{ctx.author.name} Usage: !cmdcd <name> <user_cd> [global_cd]")
            return
        
        name = name.lower().lstrip("!")
        
        try:
            user_cd_int = int(user_cd)
            global_cd_int = int(global_cd)
        except ValueError:
            await ctx.send(f"@{ctx.author.name} Cooldowns must be numbers (seconds)")
            return
        
        if self.db.update_command(name, cooldown_user=user_cd_int, cooldown_global=global_cd_int):
            await ctx.send(f"@{ctx.author.name} !{name} cooldown set to {user_cd_int}s user, {global_cd_int}s global")
        else:
            await ctx.send(f"@{ctx.author.name} Command !{name} not found.")
    
    @commands.command(name="cmdalias")
    @is_moderator()
    async def set_aliases(self, ctx: Context, name: str = "", *, aliases: str = "") -> None:
        """
        Set command aliases with collision detection.
        
        Usage: !cmdalias <name> <alias1> <alias2> ...
        Use !cmdalias <name> clear to remove all aliases
        """
        if not name:
            await ctx.send(f"@{ctx.author.name} Usage: !cmdalias <name> <alias1> <alias2> ...")
            return
        
        name = name.lower().lstrip("!")
        
        if aliases.lower() == "clear":
            alias_list = []
        else:
            alias_list = [a.lower().lstrip("!") for a in aliases.split() if a]
        
        # SECURITY: Check for collisions with protected commands
        for alias in alias_list:
            if alias in PROTECTED_COMMANDS:
                await ctx.send(f"@{ctx.author.name} Cannot use '{alias}' as alias - it's a protected command name.")
                return
            
            # Check if alias exists as another custom command
            existing = self.db.get_command(alias)
            if existing and existing["name"].lower() != name.lower():
                await ctx.send(f"@{ctx.author.name} Alias '{alias}' is already used by command '!{existing['name']}'")
                return
        
        if self.db.update_command(name, aliases=alias_list):
            if alias_list:
                await ctx.send(f"@{ctx.author.name} !{name} aliases: {', '.join(alias_list)}")
            else:
                await ctx.send(f"@{ctx.author.name} !{name} aliases cleared")
        else:
            await ctx.send(f"@{ctx.author.name} Command !{name} not found.")
    
    @commands.command(name="cmdtoggle")
    @is_moderator()
    async def toggle_command(self, ctx: Context, name: str = "") -> None:
        """
        Enable or disable a custom command.
        
        Usage: !cmdtoggle <name>
        """
        if not name:
            await ctx.send(f"@{ctx.author.name} Usage: !cmdtoggle <name>")
            return
        
        name = name.lower().lstrip("!")
        cmd = self.db.get_command(name)
        
        if not cmd:
            # Try to find disabled command
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM custom_commands WHERE name = ?", (name,))
                row = cursor.fetchone()
                if row:
                    cmd = dict(row)
        
        if not cmd:
            await ctx.send(f"@{ctx.author.name} Command !{name} not found.")
            return
        
        new_state = not cmd.get('enabled', True)
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE custom_commands SET enabled = ? WHERE name = ?",
                (new_state, name)
            )
        
        state_str = "enabled" if new_state else "disabled"
        await ctx.send(f"@{ctx.author.name} !{name} is now {state_str}")
    
    @commands.command(name="commands", aliases=["cmds"])
    async def list_commands(self, ctx: Context) -> None:
        """
        List all custom commands.
        
        Usage: !commands
        """
        cmds = self.db.get_all_commands()
        enabled_cmds = [c['name'] for c in cmds if c.get('enabled', True)]
        
        if not enabled_cmds:
            await ctx.send(f"@{ctx.author.name} No custom commands available.")
            return
        
        # Limit to first 20 for chat
        if len(enabled_cmds) > 20:
            cmd_list = ", ".join(f"!{c}" for c in enabled_cmds[:20])
            await ctx.send(f"@{ctx.author.name} Commands: {cmd_list} ... and {len(enabled_cmds) - 20} more")
        else:
            cmd_list = ", ".join(f"!{c}" for c in enabled_cmds)
            await ctx.send(f"@{ctx.author.name} Commands: {cmd_list}")
    
    @commands.command(name="variables", aliases=["vars"])
    @is_moderator()
    async def list_variables(self, ctx: Context) -> None:
        """
        Show available variables for custom commands.
        
        Usage: !variables
        """
        # Show a few common ones in chat
        common_vars = [
            "$(user)", "$(target)", "$(channel)", "$(count)",
            "$(args)", "$(random.1-100)", "$(time)"
        ]
        await ctx.send(
            f"@{ctx.author.name} Common variables: {chr(44).join(common_vars)} | "
            f"See dashboard for full list"
        )


def prepare(bot: TwitchBot) -> None:
    """Prepare the cog for loading."""
    bot.add_cog(CustomCommands(bot))
