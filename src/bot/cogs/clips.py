"""
Clips and stream management cog.

Provides stream-related commands:
- !clip: Create a clip of the stream
- !followage: Check how long a user has been following
- !title: View or change stream title
- !game: View or change stream game/category
- !shoutout: Give a shoutout to another streamer
- !uptime: Show how long the stream has been live
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import aiohttp
from twitchio.ext import commands
from twitchio.ext.commands import Context

from bot.utils.logging import get_logger
from bot.utils.permissions import cooldown, CooldownBucket, is_moderator, is_owner

if TYPE_CHECKING:
    from bot.bot import TwitchBot

logger = get_logger(__name__)


class ClipsCog(commands.Cog):
    """
    Stream management and clip commands.

    Provides commands for creating clips, checking followage,
    and managing stream info.
    """

    def __init__(self, bot: TwitchBot) -> None:
        """
        Initialize the clips cog.

        Args:
            bot: The bot instance
        """
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None
        self._token_cache: dict[str, str] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def cog_unload(self) -> None:
        """Clean up when cog is unloaded."""
        if self._session and not self._session.closed:
            import asyncio
            asyncio.create_task(self._session.close())

    async def _get_app_access_token(self) -> str | None:
        """Get an app access token for API calls."""
        if "app_token" in self._token_cache:
            return self._token_cache["app_token"]

        session = await self._get_session()
        try:
            async with session.post(
                "https://id.twitch.tv/oauth2/token",
                data={
                    "client_id": self.bot.config.client_id,
                    "client_secret": self.bot.config.client_secret,
                    "grant_type": "client_credentials",
                },
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._token_cache["app_token"] = data["access_token"]
                    return data["access_token"]
                else:
                    logger.error("Failed to get app token: %s", resp.status)
                    return None
        except Exception as e:
            logger.error("Error getting app token: %s", e)
            return None

    async def _get_broadcaster_id(self, channel_name: str) -> str | None:
        """Get the broadcaster ID for a channel."""
        try:
            users = await self.bot.fetch_users(names=[channel_name])
            if users:
                return str(users[0].id)
            return None
        except Exception as e:
            logger.error("Error fetching broadcaster ID: %s", e)
            return None

    async def _get_user_id(self, username: str) -> str | None:
        """Get user ID from username."""
        try:
            users = await self.bot.fetch_users(names=[username])
            if users:
                return str(users[0].id)
            return None
        except Exception as e:
            logger.error("Error fetching user ID: %s", e)
            return None

    @commands.command(name="clip")
    @cooldown(rate=30.0, bucket=CooldownBucket.CHANNEL)
    async def create_clip(self, ctx: Context, duration: int = 30) -> None:
        """
        Create a clip of the current stream.

        Usage: !clip [duration]
        Examples:
            !clip       - Create a 30-second clip
            !clip 60    - Create a 60-second clip

        Duration options: 15, 30, 45, 60 seconds (max 60)
        """
        # Validate and cap duration
        valid_durations = [15, 30, 45, 60]
        if duration not in valid_durations:
            # Find closest valid duration
            duration = min(valid_durations, key=lambda x: abs(x - duration))
        duration = min(duration, 60)  # Cap at 60 seconds

        broadcaster_id = await self._get_broadcaster_id(ctx.channel.name)
        if not broadcaster_id:
            await ctx.send(f"@{ctx.author.name} Couldn't find channel information.")
            return

        # Check if stream is live
        streams = await self.bot.fetch_streams(user_logins=[ctx.channel.name])
        if not streams:
            await ctx.send(f"@{ctx.author.name} Can't create a clip - stream is offline!")
            return

        session = await self._get_session()
        
        # Use the bot's OAuth token for clip creation
        headers = {
            "Authorization": f"Bearer {self.bot.config.get_oauth_token_clean()}",
            "Client-Id": self.bot.config.client_id,
            "Content-Type": "application/json",
        }

        try:
            await ctx.send(f"@{ctx.author.name} Creating clip... 📹")
            
            async with session.post(
                "https://api.twitch.tv/helix/clips",
                headers=headers,
                json={"broadcaster_id": broadcaster_id},
            ) as resp:
                if resp.status == 202:
                    data = await resp.json()
                    if data.get("data"):
                        clip_id = data["data"][0]["id"]
                        edit_url = data["data"][0]["edit_url"]
                        # The clip URL follows a pattern
                        clip_url = f"https://clips.twitch.tv/{clip_id}"
                        await ctx.send(
                            f"@{ctx.author.name} Clip created! 🎬 {clip_url}"
                        )
                    else:
                        await ctx.send(f"@{ctx.author.name} Clip creation started but no URL returned.")
                elif resp.status == 401:
                    await ctx.send(f"@{ctx.author.name} Bot doesn't have permission to create clips.")
                elif resp.status == 404:
                    await ctx.send(f"@{ctx.author.name} Stream must be live to create clips!")
                else:
                    error_text = await resp.text()
                    logger.error("Clip creation failed: %s - %s", resp.status, error_text)
                    await ctx.send(f"@{ctx.author.name} Failed to create clip. Try again later.")

        except Exception as e:
            logger.error("Error creating clip: %s", e)
            await ctx.send(f"@{ctx.author.name} An error occurred while creating the clip.")

    @commands.command(name="followage")
    @cooldown(rate=10.0, bucket=CooldownBucket.USER)
    async def followage(self, ctx: Context, username: str | None = None) -> None:
        """
        Check how long a user has been following the channel.

        Usage: !followage [username]
        Examples:
            !followage          - Check your own followage
            !followage @user    - Check another user's followage
        """
        # Determine target user
        target = username.lstrip("@") if username else ctx.author.name
        
        broadcaster_id = await self._get_broadcaster_id(ctx.channel.name)
        user_id = await self._get_user_id(target)
        
        if not broadcaster_id or not user_id:
            await ctx.send(f"@{ctx.author.name} Couldn't find user information.")
            return

        session = await self._get_session()
        
        # Get app access token for this request
        token = await self._get_app_access_token()
        if not token:
            await ctx.send(f"@{ctx.author.name} Couldn't authenticate with Twitch API.")
            return

        headers = {
            "Authorization": f"Bearer {token}",
            "Client-Id": self.bot.config.client_id,
        }

        try:
            # Use the channel.follow endpoint
            async with session.get(
                f"https://api.twitch.tv/helix/channels/followers",
                headers=headers,
                params={
                    "broadcaster_id": broadcaster_id,
                    "user_id": user_id,
                },
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("data"):
                        follow_data = data["data"][0]
                        followed_at_str = follow_data["followed_at"]
                        followed_at = datetime.fromisoformat(followed_at_str.replace("Z", "+00:00"))
                        
                        # Calculate follow duration
                        now = datetime.now(timezone.utc)
                        delta = now - followed_at
                        
                        years = delta.days // 365
                        months = (delta.days % 365) // 30
                        days = delta.days % 30
                        
                        parts = []
                        if years > 0:
                            parts.append(f"{years} year{'s' if years != 1 else ''}")
                        if months > 0:
                            parts.append(f"{months} month{'s' if months != 1 else ''}")
                        if days > 0 or not parts:
                            parts.append(f"{days} day{'s' if days != 1 else ''}")
                        
                        duration_str = ", ".join(parts)
                        
                        if target.lower() == ctx.author.name.lower():
                            await ctx.send(
                                f"@{ctx.author.name} You've been following {ctx.channel.name} for {duration_str}! 💜"
                            )
                        else:
                            await ctx.send(
                                f"@{ctx.author.name} {target} has been following {ctx.channel.name} for {duration_str}! 💜"
                            )
                    else:
                        if target.lower() == ctx.author.name.lower():
                            await ctx.send(f"@{ctx.author.name} You're not following {ctx.channel.name} yet!")
                        else:
                            await ctx.send(f"@{ctx.author.name} {target} is not following {ctx.channel.name}.")
                elif resp.status == 401:
                    await ctx.send(f"@{ctx.author.name} API authentication error. Please try again later.")
                else:
                    logger.error("Followage check failed: %s", resp.status)
                    await ctx.send(f"@{ctx.author.name} Couldn't fetch follow information.")

        except Exception as e:
            logger.error("Error checking followage: %s", e)
            await ctx.send(f"@{ctx.author.name} An error occurred while checking followage.")

    @commands.command(name="title")
    @cooldown(rate=10.0, bucket=CooldownBucket.CHANNEL)
    async def stream_title(self, ctx: Context, *, new_title: str | None = None) -> None:
        """
        View or change the stream title.

        Usage: 
            !title              - Show current title
            !title New Title    - Change title (mod/owner only)
        """
        channel = ctx.channel.name

        # If no new title, just show current title
        if not new_title:
            try:
                streams = await self.bot.fetch_streams(user_logins=[channel])
                if streams:
                    title = streams[0].title
                    await ctx.send(f"@{ctx.author.name} Current title: {title}")
                else:
                    # Try to get channel info even if offline
                    users = await self.bot.fetch_users(names=[channel])
                    if users:
                        await ctx.send(f"@{ctx.author.name} Stream is offline.")
                    else:
                        await ctx.send(f"@{ctx.author.name} Couldn't fetch channel info.")
            except Exception as e:
                logger.error("Failed to get title: %s", e)
                await ctx.send(f"@{ctx.author.name} Couldn't fetch stream info.")
            return

        # Changing title requires mod/owner permissions
        is_mod = ctx.author.is_mod
        is_broadcaster = ctx.author.is_broadcaster
        is_owner_user = ctx.author.name.lower() == self.bot.config.owner.lower()

        if not (is_mod or is_broadcaster or is_owner_user):
            await ctx.send(f"@{ctx.author.name} Only moderators can change the stream title.")
            return

        # Update the title
        broadcaster_id = await self._get_broadcaster_id(channel)
        if not broadcaster_id:
            await ctx.send(f"@{ctx.author.name} Couldn't find channel information.")
            return

        session = await self._get_session()
        headers = {
            "Authorization": f"Bearer {self.bot.config.get_oauth_token_clean()}",
            "Client-Id": self.bot.config.client_id,
            "Content-Type": "application/json",
        }

        try:
            async with session.patch(
                "https://api.twitch.tv/helix/channels",
                headers=headers,
                params={"broadcaster_id": broadcaster_id},
                json={"title": new_title},
            ) as resp:
                if resp.status == 204:
                    await ctx.send(f"@{ctx.author.name} Title updated to: {new_title} ✅")
                elif resp.status == 401:
                    await ctx.send(f"@{ctx.author.name} Bot doesn't have permission to change the title.")
                else:
                    logger.error("Title update failed: %s", resp.status)
                    await ctx.send(f"@{ctx.author.name} Failed to update title.")

        except Exception as e:
            logger.error("Error updating title: %s", e)
            await ctx.send(f"@{ctx.author.name} An error occurred while updating the title.")

    @commands.command(name="game", aliases=["category"])
    @cooldown(rate=10.0, bucket=CooldownBucket.CHANNEL)
    async def stream_game(self, ctx: Context, *, new_game: str | None = None) -> None:
        """
        View or change the stream game/category.

        Usage:
            !game               - Show current game
            !game Minecraft     - Change game (mod/owner only)
        """
        channel = ctx.channel.name

        # If no new game, just show current game
        if not new_game:
            try:
                streams = await self.bot.fetch_streams(user_logins=[channel])
                if streams:
                    game = streams[0].game_name
                    await ctx.send(f"@{ctx.author.name} Current game: {game}")
                else:
                    await ctx.send(f"@{ctx.author.name} Stream is offline.")
            except Exception as e:
                logger.error("Failed to get game: %s", e)
                await ctx.send(f"@{ctx.author.name} Couldn't fetch stream info.")
            return

        # Changing game requires mod/owner permissions
        is_mod = ctx.author.is_mod
        is_broadcaster = ctx.author.is_broadcaster
        is_owner_user = ctx.author.name.lower() == self.bot.config.owner.lower()

        if not (is_mod or is_broadcaster or is_owner_user):
            await ctx.send(f"@{ctx.author.name} Only moderators can change the game.")
            return

        # First, find the game ID
        session = await self._get_session()
        token = await self._get_app_access_token()
        if not token:
            await ctx.send(f"@{ctx.author.name} Couldn't authenticate with Twitch API.")
            return

        headers = {
            "Authorization": f"Bearer {token}",
            "Client-Id": self.bot.config.client_id,
        }

        try:
            # Search for the game
            async with session.get(
                "https://api.twitch.tv/helix/games",
                headers=headers,
                params={"name": new_game},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if not data.get("data"):
                        await ctx.send(f"@{ctx.author.name} Game '{new_game}' not found on Twitch.")
                        return
                    game_id = data["data"][0]["id"]
                    game_name = data["data"][0]["name"]
                else:
                    await ctx.send(f"@{ctx.author.name} Couldn't search for game.")
                    return

            # Update the game
            broadcaster_id = await self._get_broadcaster_id(channel)
            if not broadcaster_id:
                await ctx.send(f"@{ctx.author.name} Couldn't find channel information.")
                return

            headers["Authorization"] = f"Bearer {self.bot.config.get_oauth_token_clean()}"
            headers["Content-Type"] = "application/json"

            async with session.patch(
                "https://api.twitch.tv/helix/channels",
                headers=headers,
                params={"broadcaster_id": broadcaster_id},
                json={"game_id": game_id},
            ) as resp:
                if resp.status == 204:
                    await ctx.send(f"@{ctx.author.name} Game changed to: {game_name} ✅")
                elif resp.status == 401:
                    await ctx.send(f"@{ctx.author.name} Bot doesn't have permission to change the game.")
                else:
                    logger.error("Game update failed: %s", resp.status)
                    await ctx.send(f"@{ctx.author.name} Failed to update game.")

        except Exception as e:
            logger.error("Error updating game: %s", e)
            await ctx.send(f"@{ctx.author.name} An error occurred while updating the game.")

# DISABLED - moved to shoutout.py cog:     @commands.command(name="shoutout", aliases=["so"])
# DISABLED - moved to shoutout.py cog:     @is_moderator()
# DISABLED - moved to shoutout.py cog:     @cooldown(rate=30.0, bucket=CooldownBucket.CHANNEL)
# DISABLED - moved to shoutout.py cog:     async def shoutout(self, ctx: Context, username: str | None = None) -> None:
# DISABLED - moved to shoutout.py cog:         """
# DISABLED - moved to shoutout.py cog:         Give a shoutout to another streamer.
# DISABLED - moved to shoutout.py cog: 
# DISABLED - moved to shoutout.py cog:         Usage: !shoutout @username
# DISABLED - moved to shoutout.py cog:         Example: !shoutout @coolstreamer
# DISABLED - moved to shoutout.py cog: 
# DISABLED - moved to shoutout.py cog:         Moderator-only command.
# DISABLED - moved to shoutout.py cog:         """
# DISABLED - moved to shoutout.py cog:         if not username:
# DISABLED - moved to shoutout.py cog:             await ctx.send(f"@{ctx.author.name} Usage: !shoutout @username")
# DISABLED - moved to shoutout.py cog:             return
# DISABLED - moved to shoutout.py cog: 
# DISABLED - moved to shoutout.py cog:         # Clean up username
# DISABLED - moved to shoutout.py cog:         target = username.lstrip("@").lower()
# DISABLED - moved to shoutout.py cog: 
# DISABLED - moved to shoutout.py cog:         # Get target user info
# DISABLED - moved to shoutout.py cog:         try:
# DISABLED - moved to shoutout.py cog:             users = await self.bot.fetch_users(names=[target])
# DISABLED - moved to shoutout.py cog:             if not users:
# DISABLED - moved to shoutout.py cog:                 await ctx.send(f"@{ctx.author.name} User '{target}' not found.")
# DISABLED - moved to shoutout.py cog:                 return
# DISABLED - moved to shoutout.py cog: 
# DISABLED - moved to shoutout.py cog:             user = users[0]
# DISABLED - moved to shoutout.py cog:             display_name = user.display_name or user.name
# DISABLED - moved to shoutout.py cog: 
# DISABLED - moved to shoutout.py cog:             # Try to get their last played game
# DISABLED - moved to shoutout.py cog:             session = await self._get_session()
# DISABLED - moved to shoutout.py cog:             token = await self._get_app_access_token()
# DISABLED - moved to shoutout.py cog:             
# DISABLED - moved to shoutout.py cog:             last_game = "an awesome game"
# DISABLED - moved to shoutout.py cog:             
# DISABLED - moved to shoutout.py cog:             if token:
# DISABLED - moved to shoutout.py cog:                 headers = {
# DISABLED - moved to shoutout.py cog:                     "Authorization": f"Bearer {token}",
# DISABLED - moved to shoutout.py cog:                     "Client-Id": self.bot.config.client_id,
# DISABLED - moved to shoutout.py cog:                 }
# DISABLED - moved to shoutout.py cog:                 
# DISABLED - moved to shoutout.py cog:                 # Check if they're live
# DISABLED - moved to shoutout.py cog:                 async with session.get(
# DISABLED - moved to shoutout.py cog:                     "https://api.twitch.tv/helix/streams",
# DISABLED - moved to shoutout.py cog:                     headers=headers,
# DISABLED - moved to shoutout.py cog:                     params={"user_login": target},
# DISABLED - moved to shoutout.py cog:                 ) as resp:
# DISABLED - moved to shoutout.py cog:                     if resp.status == 200:
# DISABLED - moved to shoutout.py cog:                         data = await resp.json()
# DISABLED - moved to shoutout.py cog:                         if data.get("data"):
# DISABLED - moved to shoutout.py cog:                             last_game = data["data"][0].get("game_name", "an awesome game")
# DISABLED - moved to shoutout.py cog:                         else:
# DISABLED - moved to shoutout.py cog:                             # Get channel info for last game
# DISABLED - moved to shoutout.py cog:                             async with session.get(
# DISABLED - moved to shoutout.py cog:                                 "https://api.twitch.tv/helix/channels",
# DISABLED - moved to shoutout.py cog:                                 headers=headers,
# DISABLED - moved to shoutout.py cog:                                 params={"broadcaster_id": str(user.id)},
# DISABLED - moved to shoutout.py cog:                             ) as ch_resp:
# DISABLED - moved to shoutout.py cog:                                 if ch_resp.status == 200:
# DISABLED - moved to shoutout.py cog:                                     ch_data = await ch_resp.json()
# DISABLED - moved to shoutout.py cog:                                     if ch_data.get("data"):
# DISABLED - moved to shoutout.py cog:                                         last_game = ch_data["data"][0].get("game_name", "an awesome game")
# DISABLED - moved to shoutout.py cog: 
# DISABLED - moved to shoutout.py cog:             await ctx.send(
# DISABLED - moved to shoutout.py cog:                 f"Go check out @{display_name}! They were last playing {last_game} "
# DISABLED - moved to shoutout.py cog:                 f"at twitch.tv/{target} 💜"
# DISABLED - moved to shoutout.py cog:             )
# DISABLED - moved to shoutout.py cog: 
# DISABLED - moved to shoutout.py cog:         except Exception as e:
            logger.error("Error in shoutout: %s", e)
            await ctx.send(f"@{ctx.author.name} Couldn't complete the shoutout.")

    @commands.command(name="uptime")
    @cooldown(rate=10.0, bucket=CooldownBucket.CHANNEL)
    async def uptime(self, ctx: Context) -> None:
        """
        Show how long the stream has been live.

        Usage: !uptime
        """
        try:
            channel = ctx.channel.name
            streams = await self.bot.fetch_streams(user_logins=[channel])

            if streams:
                stream = streams[0]
                started_at = stream.started_at

                # Calculate uptime
                now = datetime.now(timezone.utc)
                uptime_delta = now - started_at

                # Format uptime
                total_seconds = int(uptime_delta.total_seconds())
                hours, remainder = divmod(total_seconds, 3600)
                minutes, seconds = divmod(remainder, 60)

                if hours > 0:
                    uptime_str = f"{hours}h {minutes}m {seconds}s"
                elif minutes > 0:
                    uptime_str = f"{minutes}m {seconds}s"
                else:
                    uptime_str = f"{seconds}s"

                await ctx.send(
                    f"@{ctx.author.name} {channel} has been live for {uptime_str}! 📺"
                )
            else:
                await ctx.send(f"@{ctx.author.name} Stream is currently offline. 😴")

        except Exception as e:
            logger.error("Failed to get uptime: %s", e)
            await ctx.send(f"@{ctx.author.name} Couldn't fetch stream info.")


def prepare(bot: TwitchBot) -> None:
    """
    Prepare function called by TwitchIO when loading the cog.

    Args:
        bot: The bot instance
    """
    bot.add_cog(ClipsCog(bot))
