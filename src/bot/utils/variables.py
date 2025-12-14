"""
Variable parser for custom commands.

Supports dynamic variables like:
- $(user) - Username of command caller
- $(target) - Mentioned user or command caller
- $(channel) - Channel name
- $(uptime) - Stream uptime
- $(count) - Command use count
- $(random.1-100) - Random number
- $(urlfetch URL) - Fetch text from URL
- And many more...
"""

from __future__ import annotations

import asyncio
import random
import re
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Optional, Any, Callable, Awaitable

import aiohttp
# DoS Protection Limits
MAX_VARIABLE_EXPANSIONS = 50  # Max variables per message
MAX_RESPONSE_LENGTH = 500  # Max output length


from bot.utils.logging import get_logger

if TYPE_CHECKING:
    from twitchio import Message, Channel

logger = get_logger(__name__)


class VariableParser:
    """
    Parser for custom command variables.
    
    Supports a wide range of dynamic variables that can be used
    in custom command responses.
    """
    
    # Regex to match variables like $(variable) or $(variable.arg) or $(variable arg1 arg2)
    VARIABLE_PATTERN = re.compile(r'\$\(([^)]+)\)')
    
    def __init__(self, bot: Any = None) -> None:
        """
        Initialize the variable parser.
        
        Args:
            bot: The Twitch bot instance (for API calls)
        """
        self.bot = bot
        self._cache: dict[str, tuple[Any, datetime]] = {}
        self._cache_ttl = 60  # seconds
        
        # Urlfetch rate limiting
        self._urlfetch_cooldowns: dict[str, datetime] = {}
        self._urlfetch_count = 0
        self._max_urlfetch_per_parse = 3
    
    def _get_cached(self, key: str) -> Optional[Any]:
        """Get a cached value if not expired."""
        if key in self._cache:
            value, timestamp = self._cache[key]
            if (datetime.now(timezone.utc) - timestamp).total_seconds() < self._cache_ttl:
                return value
            del self._cache[key]
        return None
    
    def _set_cached(self, key: str, value: Any) -> None:
        """Cache a value."""
        self._cache[key] = (value, datetime.now(timezone.utc))
    
    async def parse(
        self,
        template: str,
        message: Optional[Message] = None,
        channel: Optional[Channel] = None,
        user: Optional[str] = None,
        user_id: Optional[str] = None,
        args: list[str] | None = None,
        command_count: int = 0,
        is_subscriber: bool = False,
        is_vip: bool = False,
        is_mod: bool = False,
        extra_context: dict[str, Any] | None = None
    ) -> str:
        """
        Parse a template string and replace variables.
        
        Args:
            template: The template string containing variables
            message: The Twitch message object
            channel: The Twitch channel object
            user: Username of the command caller
            user_id: User ID of the command caller
            args: Arguments passed to the command
            command_count: Current command use count
            is_subscriber: Whether the user is a subscriber
            is_vip: Whether the user is a VIP
            is_mod: Whether the user is a moderator
            extra_context: Additional context variables
            
        Returns:
            The parsed string with variables replaced
        """
        if not template:
            return template
        
        # Reset urlfetch counter for this parse
        self._urlfetch_count = 0

        # Count total variables to prevent DoS
        variable_count = len(self.VARIABLE_PATTERN.findall(template))
        if variable_count > MAX_VARIABLE_EXPANSIONS:
            logger.warning("Variable expansion limit exceeded: %d variables", variable_count)
            return f"Error: Too many variables ({variable_count} > {MAX_VARIABLE_EXPANSIONS})"
        
        # Rate limit urlfetch calls - warn if too many
        urlfetch_count = template.lower().count("$(urlfetch")
        if urlfetch_count > self._max_urlfetch_per_parse:
            logger.warning(
                "Template has %d urlfetch calls, limiting to %d",
                urlfetch_count, self._max_urlfetch_per_parse
            )
        
        args = args or []
        extra_context = extra_context or {}
        
        # Extract channel name
        channel_name = ""
        if channel:
            channel_name = channel.name
        elif message and message.channel:
            channel_name = message.channel.name
        
        # Extract user info
        if not user and message and message.author:
            user = message.author.name
        if not user_id and message and message.author:
            user_id = str(message.author.id)
        
        # Determine target (mentioned user or caller)
        target = user
        target_id = user_id
        if args and args[0].startswith("@"):
            target = args[0].lstrip("@")
        elif args and len(args) > 0:
            # Check if first arg looks like a username
            first_arg = args[0]
            if re.match(r'^[a-zA-Z0-9_]{3,25}$', first_arg):
                target = first_arg
        
        # Determine permission level
        if is_mod:
            permission_level = "moderator"
        elif is_vip:
            permission_level = "vip"
        elif is_subscriber:
            permission_level = "subscriber"
        else:
            permission_level = "everyone"
        
        # Build context
        context = {
            "user": user or "user",
            "user.id": user_id or "0",
            "user.level": permission_level,
            "target": target or user or "user",
            "target.id": target_id or user_id or "0",
            "channel": channel_name,
            "channel.id": "",  # Would need API call
            "count": str(command_count),
            "args": " ".join(args),
            "query": urllib.parse.quote_plus(" ".join(args)) if args else "",
            **extra_context
        }
        
        # Add individual args
        for i, arg in enumerate(args, 1):
            context[f"args.{i}"] = arg
        
        # Find all variables in template
        result = template
        matches = list(self.VARIABLE_PATTERN.finditer(template))
        
        # Process in reverse order to maintain string positions
        for match in reversed(matches):
            var_content = match.group(1)
            replacement = await self._resolve_variable(var_content, context, channel_name)
            result = result[:match.start()] + replacement + result[match.end():]
        

        # Truncate final result to prevent oversized responses
        if len(result) > MAX_RESPONSE_LENGTH:
            result = result[:MAX_RESPONSE_LENGTH - 3] + "..."
        return result
    
    async def _resolve_variable(
        self,
        var_content: str,
        context: dict[str, str],
        channel_name: str
    ) -> str:
        """
        Resolve a single variable.
        
        Args:
            var_content: The content inside $()
            context: The context dictionary
            channel_name: The channel name
            
        Returns:
            The resolved value
        """
        # Split variable name and arguments
        parts = var_content.split(" ", 1)
        var_name = parts[0].lower()
        var_args = parts[1] if len(parts) > 1 else ""
        
        # Check simple context variables first
        if var_name in context:
            return context[var_name]
        
        # Handle special variables
        
        # Time variables
        if var_name == "time":
            return datetime.now().strftime("%H:%M:%S")
        
        if var_name == "date":
            return datetime.now().strftime("%Y-%m-%d")
        
        if var_name == "datetime":
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if var_name.startswith("time.until"):
            return await self._time_until(var_args)
        
        if var_name.startswith("time.since"):
            return await self._time_since(var_args)
        
        # Random variables
        if var_name.startswith("random."):
            return await self._resolve_random(var_name, var_args)
        
        # Stream variables (would need Twitch API)
        if var_name == "uptime":
            return await self._get_uptime(channel_name)
        
        if var_name == "title":
            return await self._get_stream_title(channel_name)
        
        if var_name == "game":
            return await self._get_game(channel_name)
        
        if var_name == "viewers":
            return await self._get_viewers(channel_name)
        
        if var_name == "followers":
            return await self._get_followers(channel_name)
        
        # User variables (would need API/database)
        if var_name == "followage":
            return await self._get_followage(context.get("user.id", ""), channel_name)
        
        if var_name == "accountage":
            return await self._get_accountage(context.get("user.id", ""))
        
        if var_name == "watchtime":
            return context.get("watchtime", "0 minutes")
        
        if var_name == "points":
            return context.get("points", "0")
        
        # URL fetch with rate limiting
        if var_name == "urlfetch":
            if self._urlfetch_count >= self._max_urlfetch_per_parse:
                return "[Max urlfetch limit reached]"
            self._urlfetch_count += 1
            return await self._urlfetch(var_args)
        
        # Touser (target or sender)
        if var_name == "touser":
            return context.get("target", context.get("user", "user"))
        
        # Sender
        if var_name == "sender":
            return context.get("user", "user")
        
        # If not found, return original
        return f"$({var_content})"
    
    async def _resolve_random(self, var_name: str, var_args: str) -> str:
        """Resolve random variables."""
        # $(random.1-100) - Random number in range
        range_match = re.match(r'random\.(\d+)-(\d+)', var_name)
        if range_match:
            low = int(range_match.group(1))
            high = int(range_match.group(2))
            return str(random.randint(low, high))
        
        # $(random.pick a,b,c) - Random choice
        if var_name == "random.pick" and var_args:
            choices = [c.strip() for c in var_args.split(",")]
            return random.choice(choices) if choices else ""
        
        # $(random.user) - Random user from recent chatters
        if var_name == "random.user":
            # Would need to track recent chatters
            return "random_user"
        
        # Default random 1-100
        if var_name == "random":
            return str(random.randint(1, 100))
        
        return "0"
    
    async def _time_until(self, date_str: str) -> str:
        """Calculate time until a date."""
        try:
            target_date = datetime.strptime(date_str.strip(), "%Y-%m-%d")
            target_date = target_date.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            
            if target_date <= now:
                return "Date has passed"
            
            delta = target_date - now
            days = delta.days
            hours, remainder = divmod(delta.seconds, 3600)
            minutes = remainder // 60
            
            parts = []
            if days > 0:
                parts.append(f"{days} day{'s' if days != 1 else ''}")
            if hours > 0:
                parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
            if minutes > 0 and days == 0:
                parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
            
            return ", ".join(parts) if parts else "Less than a minute"
        except ValueError:
            return "Invalid date format"
    
    async def _time_since(self, date_str: str) -> str:
        """Calculate time since a date."""
        try:
            target_date = datetime.strptime(date_str.strip(), "%Y-%m-%d")
            target_date = target_date.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            
            if target_date >= now:
                return "Date is in the future"
            
            delta = now - target_date
            days = delta.days
            
            years, days = divmod(days, 365)
            months, days = divmod(days, 30)
            
            parts = []
            if years > 0:
                parts.append(f"{years} year{'s' if years != 1 else ''}")
            if months > 0:
                parts.append(f"{months} month{'s' if months != 1 else ''}")
            if days > 0 and years == 0:
                parts.append(f"{days} day{'s' if days != 1 else ''}")
            
            return ", ".join(parts) if parts else "Today"
        except ValueError:
            return "Invalid date format"
    
    async def _get_uptime(self, channel: str) -> str:
        """Get stream uptime (placeholder - needs Twitch API)."""
        # Would need Twitch API call
        cache_key = f"uptime:{channel}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        # Placeholder - in production, call Twitch API
        return "Offline"
    
    async def _get_stream_title(self, channel: str) -> str:
        """Get stream title (placeholder - needs Twitch API)."""
        return "Stream Title"
    
    async def _get_game(self, channel: str) -> str:
        """Get current game (placeholder - needs Twitch API)."""
        return "Just Chatting"
    
    async def _get_viewers(self, channel: str) -> str:
        """Get viewer count (placeholder - needs Twitch API)."""
        return "0"
    
    async def _get_followers(self, channel: str) -> str:
        """Get follower count (placeholder - needs Twitch API)."""
        return "0"
    
    async def _get_followage(self, user_id: str, channel: str) -> str:
        """Get how long user has followed (placeholder - needs Twitch API)."""
        return "Not following"
    
    async def _get_accountage(self, user_id: str) -> str:
        """Get account age (placeholder - needs Twitch API)."""
        return "Unknown"
    
    def _is_internal_ip(self, hostname: str) -> bool:
        """Check if hostname resolves to an internal/private IP address."""
        import ipaddress
        import socket
        
        # Block common internal hostnames
        blocked_hostnames = {
            'localhost', 'localhost.localdomain', 
            'metadata', 'metadata.google.internal',
            '169.254.169.254',  # AWS/GCP metadata
        }
        
        hostname_lower = hostname.lower()
        if hostname_lower in blocked_hostnames:
            return True
        
        # Check if it's an IP address directly
        try:
            ip = ipaddress.ip_address(hostname)
            # Block private, loopback, link-local, and reserved ranges
            return (
                ip.is_private or 
                ip.is_loopback or 
                ip.is_link_local or 
                ip.is_reserved or
                ip.is_multicast
            )
        except ValueError:
            pass  # Not an IP address, need to resolve
        
        # Resolve hostname and check IP
        try:
            # Get all IPs for the hostname
            addrs = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
            for addr in addrs:
                ip_str = addr[4][0]
                try:
                    ip = ipaddress.ip_address(ip_str)
                    if (ip.is_private or ip.is_loopback or 
                        ip.is_link_local or ip.is_reserved or ip.is_multicast):
                        return True
                except ValueError:
                    continue
        except socket.gaierror:
            # Can't resolve - allow (will fail on actual request)
            pass
        
        return False

    async def _urlfetch(self, url: str) -> str:
        """Fetch text from a URL with SSRF protection and rate limiting."""
        if not url:
            return "No URL provided"
        
        url = url.strip()
        
        # Validate URL
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        
        # Rate limiting - max 1 fetch per URL per 10 seconds
        cache_key = f"urlfetch:{url}"
        if cache_key in self._urlfetch_cooldowns:
            elapsed = (datetime.now(timezone.utc) - self._urlfetch_cooldowns[cache_key]).total_seconds()
            if elapsed < 10:
                return f"[Rate limited - wait {10 - int(elapsed)}s]"
        
        self._urlfetch_cooldowns[cache_key] = datetime.now(timezone.utc)
        
        # Parse URL to extract hostname
        try:
            parsed = urllib.parse.urlparse(url)
            hostname = parsed.hostname
            
            if not hostname:
                return "Error: Invalid URL"
            
            # SSRF Protection: Block internal IPs and hostnames
            if self._is_internal_ip(hostname):
                logger.warning("SSRF attempt blocked for URL: %s", url)
                return "Error: Access to internal resources is not allowed"
            
            # Block dangerous ports
            port = parsed.port
            if port and port not in (80, 443, 8080, 8443):
                return "Error: Non-standard ports are not allowed"
                
        except Exception as e:
            logger.warning("URL parse error for %s: %s", url, e)
            return "Error: Invalid URL"
        
        try:
            # Create connector that doesn't follow redirects to prevent redirect-based SSRF
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, 
                    timeout=aiohttp.ClientTimeout(total=5),
                    allow_redirects=False  # Disable redirects to prevent SSRF via redirect
                ) as response:
                    # Handle redirects manually with SSRF check
                    if response.status in (301, 302, 303, 307, 308):
                        return "Error: Redirects are not allowed"
                    
                    if response.status == 200:
                        text = await response.text()
                        # Limit response length
                        return text[:400].strip()
                    else:
                        return f"Error: HTTP {response.status}"
        except asyncio.TimeoutError:
            return "Error: Request timed out"
        except Exception as e:
            logger.warning("URL fetch error for %s: %s", url, e)
            return "Error: Could not fetch URL"


# Global parser instance
_parser: Optional[VariableParser] = None


def get_variable_parser(bot: Any = None) -> VariableParser:
    """Get the global variable parser instance."""
    global _parser
    if _parser is None:
        _parser = VariableParser(bot)
    return _parser


# Variable documentation for help commands
VARIABLE_DOCS = {
    "$(user)": "Username of command caller",
    "$(user.id)": "User ID of command caller",
    "$(user.level)": "Permission level (everyone/subscriber/vip/moderator)",
    "$(target)": "Mentioned user or command caller",
    "$(target.id)": "Target user ID",
    "$(channel)": "Channel name",
    "$(channel.id)": "Channel ID",
    "$(title)": "Current stream title",
    "$(game)": "Current game/category",
    "$(uptime)": "Stream uptime (or 'Offline')",
    "$(viewers)": "Current viewer count",
    "$(followers)": "Follower count",
    "$(count)": "Command use count",
    "$(args)": "All arguments after command",
    "$(args.1)": "First argument",
    "$(args.2)": "Second argument (etc.)",
    "$(query)": "URL-encoded args for API calls",
    "$(random)": "Random number 1-100",
    "$(random.1-100)": "Random number in range",
    "$(random.pick a,b,c)": "Random choice from list",
    "$(random.user)": "Random user from recent chatters",
    "$(time)": "Current time (HH:MM:SS)",
    "$(date)": "Current date (YYYY-MM-DD)",
    "$(datetime)": "Current date and time",
    "$(time.until YYYY-MM-DD)": "Countdown to date",
    "$(time.since YYYY-MM-DD)": "Time since date",
    "$(followage)": "How long user has followed",
    "$(accountage)": "Account age",
    "$(watchtime)": "User watch time (if loyalty enabled)",
    "$(points)": "User points (if loyalty enabled)",
    "$(touser)": "Target user or sender",
    "$(sender)": "Command sender",
    "$(urlfetch URL)": "Fetch text from URL",
}
