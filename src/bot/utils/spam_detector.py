"""
Advanced spam detection system for Twitch chat automod.

Provides comprehensive spam detection including:
- URL filtering (whitelist/blacklist)
- High confidence spam patterns
- Obfuscated URL detection
- Lookalike character detection
- Emote spam detection
- Symbol spam detection
- Zalgo text detection
- Length/paragraph filtering
- Spam score calculation
- Action recommendations
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Optional, Any

from bot.utils.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class ModAction(Enum):
    """Moderation actions that can be taken."""
    ALLOW = "allow"
    FLAG = "flag"
    DELETE = "delete"
    TIMEOUT = "timeout"
    BAN = "ban"


@dataclass
class SpamResult:
    """Result of spam detection analysis."""
    score: int
    action: ModAction
    reasons: list[str]
    matched_patterns: list[str] = field(default_factory=list)
    is_subscriber_protected: bool = False
    
    @property
    def should_act(self) -> bool:
        """Check if any action should be taken."""
        return self.action != ModAction.ALLOW


# Lookalike character mappings for normalization
LOOKALIKES: dict[str, list[str]] = {
    'a': ['@', '4', 'α', 'а', 'ą', 'ä', 'à', 'á', 'â', 'ã', 'å', 'ā', 'ă'],
    'b': ['8', 'ь', 'в', 'ß', 'ḃ'],
    'c': ['(', 'с', 'ç', 'ć', 'č', '¢', '©'],
    'd': ['ԁ', 'ď', 'đ'],
    'e': ['3', 'є', 'е', 'ę', 'ë', 'è', 'é', 'ê', 'ē', 'ĕ', 'ė'],
    'f': ['ƒ'],
    'g': ['9', 'ğ', 'ģ', 'ġ'],
    'h': ['һ', 'ħ'],
    'i': ['1', '!', 'і', 'ї', '|', 'l', 'ì', 'í', 'î', 'ï', 'ī', 'ĭ', '¡'],
    'j': ['ј'],
    'k': ['κ', 'ķ'],
    'l': ['1', '|', 'і', 'ł', 'ļ'],
    'm': ['м', 'ṁ'],
    'n': ['п', 'ñ', 'ń', 'ņ', 'ň'],
    'o': ['0', 'о', 'ø', 'ö', 'ò', 'ó', 'ô', 'õ', 'ō', 'ŏ', 'ő'],
    'p': ['р', 'ρ'],
    'q': ['ԛ'],
    'r': ['г', 'ŕ', 'ř'],
    's': ['$', '5', 'ѕ', 'ś', 'ş', 'š', '§'],
    't': ['7', '+', 'т', 'ţ', 'ť', '†'],
    'u': ['υ', 'ü', 'ù', 'ú', 'û', 'ū', 'ŭ', 'ů'],
    'v': ['ν', 'ѵ'],
    'w': ['ω', 'ẃ', 'ẁ', 'ŵ'],
    'x': ['х', '×'],
    'y': ['у', 'ý', 'ÿ', 'ŷ'],
    'z': ['ż', 'ź', 'ž'],
}

# Build reverse lookup for normalization
LOOKALIKE_MAP: dict[str, str] = {}
for char, lookalikes in LOOKALIKES.items():
    for lookalike in lookalikes:
        LOOKALIKE_MAP[lookalike] = char
        LOOKALIKE_MAP[lookalike.upper()] = char.upper()


class SpamDetector:
    """
    Comprehensive spam detection for Twitch chat.
    
    Features:
    - URL whitelist/blacklist
    - High confidence spam pattern matching
    - Obfuscated URL detection
    - Lookalike character normalization
    - Emote spam detection
    - Symbol spam detection
    - Zalgo text detection
    - Dynamic spam scoring
    - Subscriber protection
    """
    
    # URL Whitelist - trusted domains
    URL_WHITELIST: set[str] = {
        "twitch.tv", "clips.twitch.tv", "youtube.com", "youtu.be",
        "twitter.com", "x.com", "imgur.com", "giphy.com",
        "www.twitch.tv", "www.youtube.com", "www.twitter.com",
        "www.imgur.com", "m.youtube.com", "m.twitch.tv",
        "streamlabs.com", "streamelements.com", "nightbot.tv",
    }
    
    # URL Blacklist - always blocked
    URL_BLACKLIST: set[str] = {
        "discord.gg", "discord.com", "discordapp.com",
    }
    
    # Suspicious TLDs
    SUSPICIOUS_TLDS: set[str] = {
        ".xyz", ".top", ".club", ".work", ".click", ".link",
        ".gq", ".ml", ".cf", ".ga", ".tk", ".buzz",
        ".monster", ".rest", ".cam", ".icu", ".loan",
        ".racing", ".win", ".download", ".stream", ".party",
    }
    
    # URL Shorteners
    URL_SHORTENERS: set[str] = {
        "bit.ly", "tinyurl.com", "goo.gl", "t.co", "ow.ly",
        "is.gd", "buff.ly", "adf.ly", "j.mp", "rb.gy",
        "cutt.ly", "shorturl.at", "tiny.cc", "bc.vc",
    }
    
    # High confidence spam patterns (regex)
    HIGH_CONFIDENCE_PATTERNS: list[tuple[str, str]] = [
        # Followbot/Viewbot spam
        (r"(?:buy|get|cheap|free)\s*(?:followers?|views?|viewers?|subs?)", "followbot_spam"),
        (r"(?:become|get|go)\s*(?:famous|viral|big|popular)", "fame_spam"),
        (r"\d+\s*(?:for|=)\s*\d+[k]?\s*(?:followers?|views?|subs?)", "follower_price_spam"),
        (r"(?:grow|boost|increase)\s*(?:your)?\s*(?:channel|stream|followers?)", "growth_spam"),
        (r"viewbot|followbot|follow\s*bot|view\s*bot", "bot_spam"),
        (r"(?:best|cheap|legit)\s*(?:site|website)\s*(?:for)?\s*(?:followers?|views?)", "site_spam"),
        
        # Crypto scams
        (r"(?:double|triple|10x)\s*(?:your)?\s*(?:crypto|btc|eth|bitcoin|ethereum)", "crypto_double_scam"),
        (r"send\s*[\d\.]+\s*(?:btc|eth)\s*(?:get|receive)\s*[\d\.]+\s*(?:btc|eth)", "crypto_send_scam"),
        (r"(?:free|giving away)\s*(?:crypto|btc|eth|bitcoin|ethereum|nft)", "crypto_giveaway_scam"),
        (r"(?:elon|musk|vitalik)\s*(?:is)?\s*(?:giving|giveaway|sending)", "celebrity_crypto_scam"),
        (r"(?:claim|get|receive)\s*(?:your|free)\s*(?:airdrop|tokens?|nft)", "airdrop_scam"),
        (r"(?:invest|deposit).*(?:guaranteed|100%|profit)", "investment_scam"),
        
        # Phishing
        (r"(?:account|channel)\s*(?:will be|is being|has been)\s*(?:suspended|banned|terminated)", "phishing_suspension"),
        (r"(?:urgent|immediately|now)\s*(?:verify|confirm|validate)\s*(?:your)?\s*(?:account|email)", "phishing_verify"),
        (r"twitch\s*(?:staff|support|admin|team)", "twitch_impersonation"),
        (r"(?:login|sign in).*(?:verify|confirm|secure)", "phishing_login"),
        
        # Adult spam
        (r"(?:18\+|adult|xxx|nsfw).*(?:content|pics|videos?).*(?:bio|profile|link)", "adult_spam"),
        (r"(?:hot|sexy|single).*(?:girl|guy|women|men).*(?:near|local|area)", "dating_spam"),
        (r"(?:onlyfans|of|fansly).*(?:link|bio|profile|free)", "adult_promo_spam"),
    ]
    
    # High confidence exact terms (case-insensitive)
    HIGH_CONFIDENCE_TERMS: set[str] = {
        "buy followers", "cheap followers", "free followers",
        "buy viewers", "cheap viewers", "viewbot", "followbot",
        "double your btc", "double your eth", "free bitcoin",
        "send btc receive", "send eth receive", "check my bio",
        "link in bio", "promo sm", "wanna be famous",
        "want to be famous", "become famous", "i'll help you grow",
        "fr33 f0ll0w3rs", "fr33 v13ws",  # Common obfuscations
    }
    
    # Emote patterns (Twitch, BTTV, FFZ, 7TV)
    EMOTE_PATTERN = re.compile(
        r'(?:'
        r'[A-Z][a-z]+[A-Z][a-zA-Z]*|'  # CamelCase emotes like PogChamp, Kappa
        r'[A-Z]{2,}[a-z]*|'  # CAPS emotes like LUL, KEKW
        r':[a-zA-Z0-9_]+:|'  # :emote: format
        r'[a-zA-Z]+[0-9]+[a-zA-Z]*'  # Emotes with numbers like monkaS, 4Head
        r')'
    )
    
    # Common Twitch emotes for detection
    COMMON_EMOTES: set[str] = {
        "Kappa", "PogChamp", "LUL", "KEKW", "OMEGALUL", "Pepega",
        "monkaS", "monkaW", "POGGERS", "PepeHands", "FeelsBadMan",
        "FeelsGoodMan", "4Head", "ResidentSleeper", "BibleThump",
        "Kreygasm", "PJSalt", "NotLikeThis", "TriHard", "CoolStoryBob",
        "DansGame", "WutFace", "Jebaited", "cmonBruh", "haHAA",
        "LULW", "PepeLaugh", "Sadge", "widepeepoHappy", "peepoSad",
    }
    
    # Obfuscated URL pattern
    OBFUSCATED_URL_PATTERN = re.compile(
        r"[-a-zA-Z0-9]{2,}\s*(?:\[dot\]|\(dot\)|d0t|d\.o\.t|\.\s+)\s*(?:com|net|org|tv|gg|co|io|xyz|me)",
        re.IGNORECASE
    )
    
    # General URL pattern
    URL_PATTERN = re.compile(
        r"https?://[^\s]+|(?:www\.)?[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:/[^\s]*)?",
        re.IGNORECASE
    )
    
    # Domain extraction pattern
    DOMAIN_PATTERN = re.compile(
        r"(?:https?://)?(?:www\.)?([a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z0-9][-a-zA-Z0-9.]*)",
        re.IGNORECASE
    )
    
    # Zalgo text pattern (combining characters)
    ZALGO_PATTERN = re.compile(r'[\u0300-\u036f\u0489]')
    
    # ASCII art pattern (lines of similar characters)
    ASCII_ART_PATTERN = re.compile(r'([^\w\s])\1{5,}')
    
    def __init__(
        self,
        sensitivity: str = "medium",
        max_emotes: int = 15,
        max_message_length: int = 500,
        max_caps_percent: int = 70,
        max_symbol_percent: int = 50,
        max_repeated_words: int = 10
    ) -> None:
        """
        Initialize spam detector.
        
        Args:
            sensitivity: Detection sensitivity (low, medium, high)
            max_emotes: Maximum emotes allowed per message
            max_message_length: Maximum message length
            max_caps_percent: Maximum percentage of caps allowed
            max_symbol_percent: Maximum percentage of symbols allowed
            max_repeated_words: Maximum repeated words allowed
        """
        self.sensitivity = sensitivity
        self.max_emotes = max_emotes
        self.max_message_length = max_message_length
        self.max_caps_percent = max_caps_percent
        self.max_symbol_percent = max_symbol_percent
        self.max_repeated_words = max_repeated_words
        
        self._compile_patterns()
        self._recent_spam: list[str] = []
        self._recent_spam_max = 50
        self._thresholds = self._get_thresholds(sensitivity)
        
        logger.info("SpamDetector initialized with %s sensitivity", sensitivity)
    
    def _get_thresholds(self, sensitivity: str) -> dict[str, int]:
        """Get action thresholds based on sensitivity."""
        thresholds = {
            "low": {"flag": 40, "delete": 60, "timeout": 80, "ban": 95},
            "medium": {"flag": 31, "delete": 51, "timeout": 71, "ban": 86},
            "high": {"flag": 25, "delete": 40, "timeout": 60, "ban": 75},
        }
        return thresholds.get(sensitivity, thresholds["medium"])
    
    def set_sensitivity(self, sensitivity: str) -> None:
        """Update detection sensitivity."""
        if sensitivity in ("low", "medium", "high"):
            self.sensitivity = sensitivity
            self._thresholds = self._get_thresholds(sensitivity)
            logger.info("Sensitivity updated to %s", sensitivity)
    
    def _compile_patterns(self) -> None:
        """Compile regex patterns for efficiency."""
        self._compiled_patterns: list[tuple[re.Pattern, str]] = []
        for pattern, name in self.HIGH_CONFIDENCE_PATTERNS:
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
                self._compiled_patterns.append((compiled, name))
            except re.error as e:
                logger.error("Failed to compile pattern %s: %s", name, e)
    
    def normalize_text(self, text: str) -> str:
        """
        Normalize text by replacing lookalike characters.
        
        This catches attempts like "fr33 f0ll0w3rs" -> "free followers"
        
        Args:
            text: Original text
            
        Returns:
            Normalized text
        """
        result = []
        for char in text:
            if char in LOOKALIKE_MAP:
                result.append(LOOKALIKE_MAP[char])
            else:
                result.append(char)
        return ''.join(result)
    
    def count_emotes(self, message: str) -> int:
        """
        Count emotes in a message.
        
        Args:
            message: Message to analyze
            
        Returns:
            Number of emotes detected
        """
        count = 0
        words = message.split()
        
        for word in words:
            # Check against known emotes
            if word in self.COMMON_EMOTES:
                count += 1
                continue
            
            # Check emote pattern
            if self.EMOTE_PATTERN.match(word):
                count += 1
        
        return count
    
    def check_emote_spam(self, message: str) -> tuple[bool, int]:
        """
        Check if message has too many emotes.
        
        Args:
            message: Message to check
            
        Returns:
            tuple: (is_spam, emote_count)
        """
        count = self.count_emotes(message)
        return count > self.max_emotes, count
    
    def check_symbol_spam(self, message: str) -> tuple[bool, float]:
        """
        Check for excessive symbols in message.
        
        Args:
            message: Message to check
            
        Returns:
            tuple: (is_spam, symbol_percentage)
        """
        if len(message) < 5:
            return False, 0.0
        
        symbol_count = sum(1 for c in message if not c.isalnum() and not c.isspace())
        total = len(message.replace(" ", ""))
        
        if total == 0:
            return False, 0.0
        
        percentage = (symbol_count / total) * 100
        return percentage > self.max_symbol_percent, percentage
    
    def check_zalgo(self, message: str) -> tuple[bool, int]:
        """
        Check for Zalgo text (excessive combining characters).
        
        Args:
            message: Message to check
            
        Returns:
            tuple: (is_zalgo, combining_char_count)
        """
        combining_count = len(self.ZALGO_PATTERN.findall(message))
        # More than 5 combining characters is suspicious
        return combining_count > 5, combining_count
    
    def check_ascii_art(self, message: str) -> bool:
        """
        Check for ASCII art patterns.
        
        Args:
            message: Message to check
            
        Returns:
            bool: True if ASCII art detected
        """
        return bool(self.ASCII_ART_PATTERN.search(message))
    
    def check_length(self, message: str) -> tuple[bool, int]:
        """
        Check if message exceeds maximum length.
        
        Args:
            message: Message to check
            
        Returns:
            tuple: (is_too_long, length)
        """
        length = len(message)
        return length > self.max_message_length, length
    
    def check_repeated_words(self, message: str) -> tuple[bool, int]:
        """
        Check for excessive word repetition.
        
        Args:
            message: Message to check
            
        Returns:
            tuple: (has_repetition, max_repeat_count)
        """
        words = message.lower().split()
        if len(words) < 3:
            return False, 0
        
        word_counts: dict[str, int] = {}
        for word in words:
            if len(word) > 2:  # Ignore short words
                word_counts[word] = word_counts.get(word, 0) + 1
        
        max_count = max(word_counts.values()) if word_counts else 0
        return max_count > self.max_repeated_words, max_count
    
    def _extract_urls(self, message: str) -> list[str]:
        """Extract all URLs from message."""
        return self.URL_PATTERN.findall(message)
    
    def _extract_domains(self, message: str) -> list[str]:
        """Extract domains from message."""
        domains = []
        for match in self.DOMAIN_PATTERN.finditer(message):
            domain = match.group(1).lower()
            domains.append(domain)
        return domains
    
    def _check_url(self, domain: str) -> tuple[bool, str]:
        """
        Check if a domain is allowed.
        
        Returns:
            tuple: (is_blocked, reason)
        """
        domain_lower = domain.lower()
        
        # Check blacklist first
        for blocked in self.URL_BLACKLIST:
            if blocked in domain_lower:
                return True, f"blocked_domain:{blocked}"
        
        # Check whitelist
        for allowed in self.URL_WHITELIST:
            if domain_lower == allowed or domain_lower.endswith("." + allowed):
                return False, "whitelisted"
        
        # Check URL shorteners
        for shortener in self.URL_SHORTENERS:
            if shortener in domain_lower:
                return True, f"url_shortener:{shortener}"
        
        # Check suspicious TLDs
        for tld in self.SUSPICIOUS_TLDS:
            if domain_lower.endswith(tld):
                return True, f"suspicious_tld:{tld}"
        
        return False, "unknown_domain"
    
    def _check_patterns(self, message: str) -> list[tuple[str, str]]:
        """
        Check message against spam patterns.
        
        Returns:
            list: List of (pattern_name, matched_text) tuples
        """
        matches = []
        message_lower = message.lower()
        
        # Also check normalized version
        normalized = self.normalize_text(message_lower)
        
        # Check compiled regex patterns
        for pattern, name in self._compiled_patterns:
            match = pattern.search(message)
            if match:
                matches.append((name, match.group()))
            elif normalized != message_lower:
                match = pattern.search(normalized)
                if match:
                    matches.append((f"{name}_obfuscated", match.group()))
        
        # Check exact terms
        for term in self.HIGH_CONFIDENCE_TERMS:
            if term in message_lower or term in normalized:
                matches.append((f"term:{term}", term))
        
        return matches
    
    def _check_obfuscated_urls(self, message: str) -> bool:
        """Check for obfuscated URLs."""
        return bool(self.OBFUSCATED_URL_PATTERN.search(message))
    
    def _check_excessive_caps(self, message: str) -> tuple[bool, float]:
        """Check for excessive capital letters."""
        if len(message) < 10:
            return False, 0.0
        
        alpha_chars = [c for c in message if c.isalpha()]
        if not alpha_chars:
            return False, 0.0
        
        upper_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars) * 100
        return upper_ratio > self.max_caps_percent, upper_ratio
    
    def _check_repeated_chars(self, message: str) -> bool:
        """Check for repeated characters (5+ same char)."""
        return bool(re.search(r'(.)\1{4,}', message))
    
    def _check_similarity_to_spam(self, message: str) -> bool:
        """Check if message is similar to recent spam."""
        if not self._recent_spam:
            return False
        
        message_lower = message.lower()
        message_words = set(message_lower.split())
        
        for spam in self._recent_spam[-20:]:
            spam_words = set(spam.lower().split())
            if len(message_words) > 2 and len(spam_words) > 2:
                intersection = len(message_words & spam_words)
                union = len(message_words | spam_words)
                if union > 0 and intersection / union > 0.6:
                    return True
        
        return False
    
    def _add_to_spam_history(self, message: str) -> None:
        """Add message to spam history for similarity checking."""
        self._recent_spam.append(message)
        if len(self._recent_spam) > self._recent_spam_max:
            self._recent_spam = self._recent_spam[-self._recent_spam_max:]
    
    def analyze(
        self,
        message: str,
        user_id: str,
        username: str,
        is_subscriber: bool = False,
        is_vip: bool = False,
        is_mod: bool = False,
        is_broadcaster: bool = False,
        follow_age_days: int = 0,
        message_count: int = 0,
        is_whitelisted: bool = False,
        has_permit: bool = False,
        filter_settings: dict[str, Any] | None = None,
    ) -> SpamResult:
        """
        Analyze a message for spam.
        
        Args:
            message: Message content
            user_id: Twitch user ID
            username: Twitch username
            is_subscriber: User is a subscriber
            is_vip: User is a VIP
            is_mod: User is a moderator
            is_broadcaster: User is the broadcaster
            follow_age_days: Days since user followed
            message_count: User's total message count
            is_whitelisted: User is on whitelist
            has_permit: User has temporary link permit
            filter_settings: Channel-specific filter settings
            
        Returns:
            SpamResult: Analysis result with score and recommended action
        """
        # Skip checks for mods and broadcaster
        if is_mod or is_broadcaster:
            return SpamResult(
                score=0,
                action=ModAction.ALLOW,
                reasons=["moderator_or_broadcaster"],
            )
        
        # Skip checks for whitelisted users
        if is_whitelisted:
            return SpamResult(
                score=0,
                action=ModAction.ALLOW,
                reasons=["whitelisted"],
            )
        
        # Apply filter settings if provided
        settings = filter_settings or {}
        
        score = 0
        reasons: list[str] = []
        matched_patterns: list[str] = []
        
        # ==================== Score Additions ====================
        
        # Check high confidence patterns (always enabled)
        pattern_matches = self._check_patterns(message)
        if pattern_matches:
            score += 35
            for name, matched in pattern_matches:
                matched_patterns.append(f"{name}: {matched[:30]}")
            reasons.append(f"spam_pattern_match ({len(pattern_matches)} patterns)")
        
        # Check URLs (if link filter enabled)
        if settings.get("link_enabled", True):
            domains = self._extract_domains(message)
            has_blocked_url = False
            has_suspicious_url = False
            has_any_url = len(domains) > 0
            
            for domain in domains:
                is_blocked, url_reason = self._check_url(domain)
                if is_blocked:
                    if "blocked_domain" in url_reason:
                        has_blocked_url = True
                        score += 30
                        reasons.append(f"blocked_url:{domain}")
                    elif "url_shortener" in url_reason:
                        has_suspicious_url = True
                        if follow_age_days < 7:
                            score += 25
                            reasons.append(f"url_shortener_new_user:{domain}")
                        else:
                            score += 15
                            reasons.append(f"url_shortener:{domain}")
                    elif "suspicious_tld" in url_reason:
                        has_suspicious_url = True
                        score += 20
                        reasons.append(f"suspicious_tld:{domain}")
                elif url_reason == "unknown_domain":
                    has_suspicious_url = True
                    score += 10
                    reasons.append(f"unknown_domain:{domain}")
            
            # First message contains link (unless permitted)
            if has_any_url and message_count == 0 and not has_permit:
                if not has_blocked_url:
                    score += 15
                    reasons.append("first_message_with_link")
        
        # Check for obfuscated URLs
        if self._check_obfuscated_urls(message):
            score += 10
            reasons.append("obfuscated_url")
        
        # Check excessive caps (if enabled)
        if settings.get("caps_enabled", True):
            min_length = settings.get("caps_min_length", 10)
            max_percent = settings.get("caps_max_percent", self.max_caps_percent)
            if len(message) >= min_length:
                is_caps, caps_percent = self._check_excessive_caps(message)
                if caps_percent > max_percent:
                    score += 20
                    reasons.append(f"excessive_caps:{caps_percent:.0f}%")
        
        # Check emote spam (if enabled)
        if settings.get("emote_enabled", True):
            max_emotes = settings.get("emote_max_count", self.max_emotes)
            is_emote_spam, emote_count = self.check_emote_spam(message)
            if emote_count > max_emotes:
                score += 15
                reasons.append(f"emote_spam:{emote_count}")
        
        # Check symbol spam (if enabled)
        if settings.get("symbol_enabled", True):
            max_symbol = settings.get("symbol_max_percent", self.max_symbol_percent)
            is_symbol_spam, symbol_percent = self.check_symbol_spam(message)
            if symbol_percent > max_symbol:
                score += 15
                reasons.append(f"symbol_spam:{symbol_percent:.0f}%")
        
        # Check Zalgo text (if enabled)
        if settings.get("zalgo_enabled", True):
            is_zalgo, zalgo_count = self.check_zalgo(message)
            if is_zalgo:
                score += 25
                reasons.append(f"zalgo_text:{zalgo_count}")
        
        # Check message length (if enabled)
        if settings.get("length_enabled", True):
            max_length = settings.get("length_max_chars", self.max_message_length)
            is_too_long, length = self.check_length(message)
            if length > max_length:
                score += 10
                reasons.append(f"message_too_long:{length}")
        
        # Check repeated words (if enabled)
        if settings.get("repetition_enabled", True):
            max_repeat = settings.get("repetition_max_words", self.max_repeated_words)
            has_repetition, repeat_count = self.check_repeated_words(message)
            if repeat_count > max_repeat:
                score += 15
                reasons.append(f"word_repetition:{repeat_count}")
        
        # Check ASCII art
        if self.check_ascii_art(message):
            score += 10
            reasons.append("ascii_art")
        
        # Check repeated characters
        if self._check_repeated_chars(message):
            score += 15
            reasons.append("repeated_characters")
        
        # Check similarity to recent spam
        if self._check_similarity_to_spam(message):
            score += 10
            reasons.append("similar_to_recent_spam")
        
        # New follower penalty
        if follow_age_days < 7:
            score += 5
            reasons.append("new_follower")
        
        # ==================== Score Reductions ====================
        
        # Subscriber reduction
        if is_subscriber:
            score -= 30
            reasons.append("subscriber_reduction")
        
        # VIP reduction
        if is_vip:
            score -= 25
            reasons.append("vip_reduction")
        
        # Long-time follower reduction
        if follow_age_days >= 30:
            score -= 15
            reasons.append("longtime_follower_reduction")
        
        # Active chatter reduction
        if message_count >= 10:
            score -= 10
            reasons.append("active_chatter_reduction")
        
        # Has permit - allow links
        if has_permit and settings.get("link_enabled", True):
            domains = self._extract_domains(message)
            has_blocked = any(self._check_url(d)[0] and "blocked_domain" in self._check_url(d)[1] for d in domains)
            if not has_blocked:
                score -= 20
                reasons.append("has_permit")
        
        # Ensure score stays in bounds
        score = max(0, min(100, score))
        
        # ==================== Determine Action ====================
        
        action = self._determine_action(score, is_subscriber, is_vip)
        
        # Track spam for similarity checking
        if action in (ModAction.DELETE, ModAction.TIMEOUT, ModAction.BAN):
            self._add_to_spam_history(message)
        
        return SpamResult(
            score=score,
            action=action,
            reasons=reasons,
            matched_patterns=matched_patterns,
            is_subscriber_protected=(is_subscriber or is_vip) and action == ModAction.TIMEOUT,
        )
    
    def _determine_action(
        self,
        score: int,
        is_subscriber: bool,
        is_vip: bool,
    ) -> ModAction:
        """Determine action based on score and user status."""
        thresholds = self._thresholds
        
        if score >= thresholds["ban"]:
            if is_subscriber or is_vip:
                return ModAction.TIMEOUT
            return ModAction.BAN
        
        if score >= thresholds["timeout"]:
            return ModAction.TIMEOUT
        
        if score >= thresholds["delete"]:
            return ModAction.DELETE
        
        if score >= thresholds["flag"]:
            return ModAction.FLAG
        
        return ModAction.ALLOW


# Global spam detector instance
_detector: Optional[SpamDetector] = None


def get_spam_detector(sensitivity: str = "medium") -> SpamDetector:
    """
    Get the global spam detector instance.
    
    Args:
        sensitivity: Detection sensitivity (only used on first call)
        
    Returns:
        SpamDetector: Spam detector instance
    """
    global _detector
    if _detector is None:
        _detector = SpamDetector(sensitivity)
    return _detector
