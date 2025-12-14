"""
Gambling mini-games cog for Twitch bot.

Provides fun gambling games using loyalty points:
- Slots
- Gamble (coin flip)
- Roulette
- Duels
"""

from __future__ import annotations

import random
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Optional

from twitchio.ext import commands
from twitchio.ext.commands import Context

from bot.utils.database import get_database
from bot.utils.logging import get_logger
from bot.utils.permissions import cooldown, CooldownBucket, is_moderator

if TYPE_CHECKING:
    from bot.bot import TwitchBot

logger = get_logger(__name__)

# Slot machine symbols and payouts
SLOT_SYMBOLS = ["🍒", "🍋", "🍊", "🍇", "⭐", "💎", "7️⃣"]
SLOT_PAYOUTS = {
    "7️⃣7️⃣7️⃣": 50,   # Jackpot
    "💎💎💎": 25,
    "⭐⭐⭐": 10,
    "🍇🍇🍇": 5,
    "🍊🍊🍊": 4,
    "🍋🍋🍋": 3,
    "🍒🍒🍒": 2,
}

# Roulette red numbers
ROULETTE_RED = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}

# Bug 4 FIX: Maximum winnings cap to prevent integer overflow
MAX_WINNINGS = 1_000_000


class Gambling(commands.Cog):
    """Gambling mini-games cog."""

    def __init__(self, bot: TwitchBot) -> None:
        """Initialize the gambling cog."""
        self.bot = bot
        self.db = get_database()

        # Settings (configurable per channel in future)
        self.min_bet = 10
        self.max_bet = 10000
        self.enabled = True

        # Pending duels: {channel: {challenger: {target, amount, challenger_id, expires}}}
        self._pending_duels: dict[str, dict[str, dict]] = {}

        logger.info("Gambling cog initialized")

    def _get_points(self, user_id: str, channel: str) -> float:
        """Get user's current points."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT points FROM user_loyalty WHERE user_id = ? AND channel = ?",
                (user_id, channel.lower())
            )
            row = cursor.fetchone()
            return row["points"] if row else 0

    def _update_points(self, user_id: str, username: str, channel: str, delta: float) -> float:
        """Update user's points and return new balance."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            # Ensure user exists
            cursor.execute("""
                INSERT INTO user_loyalty (user_id, username, channel, points)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(user_id, channel) DO NOTHING
            """, (user_id, username, channel.lower()))

            # Update points
            cursor.execute("""
                UPDATE user_loyalty 
                SET points = MAX(0, points + ?)
                WHERE user_id = ? AND channel = ?
            """, (delta, user_id, channel.lower()))

            # Get new balance
            cursor.execute(
                "SELECT points FROM user_loyalty WHERE user_id = ? AND channel = ?",
                (user_id, channel.lower())
            )
            row = cursor.fetchone()
            return row["points"] if row else 0

    def _validate_bet(self, amount: str, user_id: str, channel: str) -> tuple[bool, int, str]:
        """Validate a bet amount. Returns (valid, amount, error_message)."""
        try:
            bet = int(amount)
        except ValueError:
            return False, 0, "Invalid amount. Use a number."

        if bet < self.min_bet:
            return False, 0, f"Minimum bet is {self.min_bet} points."

        if bet > self.max_bet:
            return False, 0, f"Maximum bet is {self.max_bet} points."

        current = self._get_points(user_id, channel)
        if bet > current:
            return False, 0, f"You only have {int(current)} points."

        return True, bet, ""

    def _atomic_bet_deduct(self, user_id: str, channel: str, amount: int) -> tuple[bool, int, str]:
        """Atomically validate and deduct bet amount. Returns (success, current_points, error_msg).
        
        Security Fix: Prevents race condition where users could spam multiple bets
        before deductions complete by checking AND deducting in a single transaction.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Atomic check and deduct in single UPDATE
            cursor.execute("""
                UPDATE user_loyalty 
                SET points = points - ?
                WHERE user_id = ? AND channel = ? AND points >= ?
            """, (amount, user_id, channel.lower(), amount))
            
            if cursor.rowcount == 0:
                # Get current balance for error message
                cursor.execute("""
                    SELECT points FROM user_loyalty 
                    WHERE user_id = ? AND channel = ?
                """, (user_id, channel.lower()))
                row = cursor.fetchone()
                current = int(row["points"]) if row else 0
                return False, current, f"Insufficient points. You have {current:,} points."
            
            # Get new balance
            cursor.execute("""
                SELECT points FROM user_loyalty 
                WHERE user_id = ? AND channel = ?
            """, (user_id, channel.lower()))
            row = cursor.fetchone()
            new_balance = int(row["points"]) if row else 0
            
            return True, new_balance, ""

    def _clean_expired_duels(self, channel: str) -> None:
        """Remove expired duels and refund escrowed points."""
        if channel not in self._pending_duels:
            return

        now = datetime.now(timezone.utc)
        expired = [
            challenger
            for challenger, duel in self._pending_duels[channel].items()
            if duel["expires"] <= now
        ]
        for challenger in expired:
            duel = self._pending_duels[channel][challenger]
            # SECURITY FIX: Refund escrowed points on expiry
            if duel.get("escrowed"):
                self._update_points(duel["challenger_id"], challenger, channel, duel["amount"])
                logger.info("Refunded %d points to %s for expired duel", duel["amount"], challenger)
            del self._pending_duels[channel][challenger]

    @commands.command(name="slots", aliases=["slot"])
    @cooldown(rate=5.0, bucket=CooldownBucket.USER)
    async def slots_cmd(self, ctx: Context, amount: str = "") -> None:
        """Play the slot machine! Usage: !slots <amount>"""
        if not self.enabled:
            return

        if not amount:
            await ctx.send(f"@{ctx.author.name} Usage: !slots <amount>")
            return

        user_id = str(ctx.author.id)
        channel = ctx.channel.name

        # Validate bet amount (min/max only, not balance - that's checked atomically)
        try:
            bet = int(amount)
        except ValueError:
            await ctx.send(f"@{ctx.author.name} Invalid amount. Use a number.")
            return

        if bet < self.min_bet:
            await ctx.send(f"@{ctx.author.name} Minimum bet is {self.min_bet} points.")
            return

        if bet > self.max_bet:
            await ctx.send(f"@{ctx.author.name} Maximum bet is {self.max_bet} points.")
            return

        # Security Fix: Atomic bet deduction to prevent race condition
        success, balance, error = self._atomic_bet_deduct(user_id, channel, bet)
        if not success:
            await ctx.send(f"@{ctx.author.name} {error}")
            return

        # Spin the slots
        result = [random.choice(SLOT_SYMBOLS) for _ in range(3)]
        result_str = "".join(result)
        display = " | ".join(result)

        # Check for wins
        multiplier = 0.0
        if result_str in SLOT_PAYOUTS:
            multiplier = SLOT_PAYOUTS[result_str]
        elif result[0] == result[1] or result[1] == result[2]:
            multiplier = 1.5  # Two matching

        if multiplier > 0:
            # Bug 4 FIX: Cap winnings to prevent integer overflow
            # Note: bet already deducted, so add back bet + winnings
            winnings = min(int(bet * multiplier), MAX_WINNINGS)
            new_balance = self._update_points(user_id, ctx.author.name, channel, winnings)
            await ctx.send(
                f"@{ctx.author.name} 🎰 {display} 🎰 YOU WIN! +{winnings} points! "
                f"(Balance: {int(new_balance)})"
            )
            if multiplier >= 10:
                logger.info(
                    "Big slots win: %s won %d (x%.1f) in %s",
                    ctx.author.name, winnings, multiplier, channel
                )
        else:
            # Bet already deducted atomically, just report the balance
            await ctx.send(
                f"@{ctx.author.name} 🎰 {display} 🎰 No luck! -{bet} points. "
                f"(Balance: {balance})"
            )

    @commands.command(name="gamble", aliases=["bet"])
    @cooldown(rate=5.0, bucket=CooldownBucket.USER)
    async def gamble_cmd(self, ctx: Context, amount: str = "") -> None:
        """50/50 gamble - double or nothing! Usage: !gamble <amount>"""
        if not self.enabled:
            return

        if not amount:
            await ctx.send(f"@{ctx.author.name} Usage: !gamble <amount>")
            return

        user_id = str(ctx.author.id)
        channel = ctx.channel.name

        # Validate bet amount (min/max only, not balance - that's checked atomically)
        try:
            bet = int(amount)
        except ValueError:
            await ctx.send(f"@{ctx.author.name} Invalid amount. Use a number.")
            return

        if bet < self.min_bet:
            await ctx.send(f"@{ctx.author.name} Minimum bet is {self.min_bet} points.")
            return

        if bet > self.max_bet:
            await ctx.send(f"@{ctx.author.name} Maximum bet is {self.max_bet} points.")
            return

        # Security Fix: Atomic bet deduction to prevent race condition
        success, balance, error = self._atomic_bet_deduct(user_id, channel, bet)
        if not success:
            await ctx.send(f"@{ctx.author.name} {error}")
            return

        # 50/50 chance
        if random.random() < 0.5:
            # Win: return bet + winnings (bet * 2 total, so add bet back)
            winnings = bet
            new_balance = self._update_points(user_id, ctx.author.name, channel, winnings * 2)
            await ctx.send(
                f"@{ctx.author.name} 🎲 You WON! +{winnings} points! "
                f"(Balance: {int(new_balance)})"
            )
        else:
            # Lose: bet already deducted atomically
            await ctx.send(
                f"@{ctx.author.name} 🎲 You lost! -{bet} points. "
                f"(Balance: {balance})"
            )

    @commands.command(name="roulette")
    @cooldown(rate=5.0, bucket=CooldownBucket.USER)
    async def roulette_cmd(self, ctx: Context, amount: str = "", choice: str = "") -> None:
        """Roulette! Usage: !roulette <amount> <red/black/green/0-36>"""
        if not self.enabled:
            return

        if not amount or not choice:
            await ctx.send(f"@{ctx.author.name} Usage: !roulette <amount> <red/black/green/0-36>")
            return

        user_id = str(ctx.author.id)
        channel = ctx.channel.name

        # Validate bet amount (min/max only, not balance - that's checked atomically)
        try:
            bet = int(amount)
        except ValueError:
            await ctx.send(f"@{ctx.author.name} Invalid amount. Use a number.")
            return

        if bet < self.min_bet:
            await ctx.send(f"@{ctx.author.name} Minimum bet is {self.min_bet} points.")
            return

        if bet > self.max_bet:
            await ctx.send(f"@{ctx.author.name} Maximum bet is {self.max_bet} points.")
            return

        choice = choice.lower()

        # Validate choice
        valid_choices = {"red", "black", "green"}
        if choice not in valid_choices:
            if choice.isdigit():
                num = int(choice)
                if num < 0 or num > 36:
                    await ctx.send(f"@{ctx.author.name} Invalid choice. Use red/black/green or 0-36.")
                    return
            else:
                await ctx.send(f"@{ctx.author.name} Invalid choice. Use red/black/green or 0-36.")
                return

        # Security Fix: Atomic bet deduction to prevent race condition
        success, balance, error = self._atomic_bet_deduct(user_id, channel, bet)
        if not success:
            await ctx.send(f"@{ctx.author.name} {error}")
            return

        # Spin the wheel (0-36)
        result = random.randint(0, 36)

        # Determine color (0 is green)
        if result == 0:
            color = "green"
        elif result in ROULETTE_RED:
            color = "red"
        else:
            color = "black"

        # Check win
        multiplier = 0
        if choice == color:
            multiplier = 35 if color == "green" else 2
        elif choice.isdigit() and int(choice) == result:
            multiplier = 35

        color_emoji = "🟢" if color == "green" else ("🔴" if color == "red" else "⚫")

        if multiplier > 0:
            # Bug 4 FIX: Cap winnings to prevent integer overflow
            # Note: bet already deducted, so add back bet + winnings
            winnings = min(int(bet * multiplier), MAX_WINNINGS)
            new_balance = self._update_points(user_id, ctx.author.name, channel, winnings)
            await ctx.send(
                f"@{ctx.author.name} {color_emoji} {result} ({color}) - YOU WIN! "
                f"+{winnings} points! (Balance: {int(new_balance)})"
            )
            if multiplier >= 10:
                logger.info(
                    "Big roulette win: %s won %d (x%d) in %s",
                    ctx.author.name, winnings, multiplier, channel
                )
        else:
            # Bet already deducted atomically
            await ctx.send(
                f"@{ctx.author.name} {color_emoji} {result} ({color}) - You lose! "
                f"-{bet} points. (Balance: {balance})"
            )

    @commands.command(name="duel")
    @cooldown(rate=10.0, bucket=CooldownBucket.USER)
    async def duel_cmd(self, ctx: Context, target: str = "", amount: str = "") -> None:
        """Challenge someone to a duel! Usage: !duel @user <amount>"""
        if not self.enabled:
            return

        if not target or not amount:
            await ctx.send(f"@{ctx.author.name} Usage: !duel @user <amount>")
            return

        target = target.lstrip("@").lower()
        user_id = str(ctx.author.id)
        channel = ctx.channel.name
        challenger = ctx.author.name.lower()

        if target == challenger:
            await ctx.send(f"@{ctx.author.name} You can't duel yourself!")
            return

        # Parse bet amount
        try:
            bet = int(amount)
        except ValueError:
            await ctx.send(f"@{ctx.author.name} Invalid amount. Use a number.")
            return

        if bet < self.min_bet:
            await ctx.send(f"@{ctx.author.name} Minimum bet is {self.min_bet} points.")
            return
        if bet > self.max_bet:
            await ctx.send(f"@{ctx.author.name} Maximum bet is {self.max_bet} points.")
            return

        # Clean expired duels first (refunds escrowed points)
        self._clean_expired_duels(channel)

        # SECURITY FIX: Atomically deduct points NOW (escrow)
        success, balance, error = self._atomic_bet_deduct(user_id, channel, bet)
        if not success:
            await ctx.send(f"@{ctx.author.name} {error}")
            return

        # Check if challenger already has a pending duel
        if channel in self._pending_duels and challenger in self._pending_duels[channel]:
            await ctx.send(f"@{ctx.author.name} You already have a pending duel! Wait for it to expire.")
            return

        # Store pending duel
        if channel not in self._pending_duels:
            self._pending_duels[channel] = {}

        self._pending_duels[channel][challenger] = {
            "target": target,
            "amount": bet,
            "challenger_id": user_id,
            "challenger_name": challenger,
            "escrowed": True,  # Points already deducted
            "expires": datetime.now(timezone.utc) + timedelta(minutes=2)
        }

        await ctx.send(
            f"@{target} - @{ctx.author.name} challenges you to a duel for {bet} points! "
            f"Type !accept to fight! (Expires in 2 minutes)"
        )

    @commands.command(name="accept")
    async def accept_cmd(self, ctx: Context) -> None:
        """Accept a duel challenge."""
        channel = ctx.channel.name
        username = ctx.author.name.lower()

        # Clean expired duels
        self._clean_expired_duels(channel)

        if channel not in self._pending_duels:
            await ctx.send(f"@{ctx.author.name} No pending duel for you!")
            return

        # Find a duel targeting this user
        challenger = None
        duel = None
        for c, d in self._pending_duels[channel].items():
            if d["target"] == username:
                challenger = c
                duel = d
                break

        if not duel:
            await ctx.send(f"@{ctx.author.name} No pending duel for you!")
            return

        # SECURITY FIX: Atomically deduct accepter's points
        user_id = str(ctx.author.id)
        success, balance, error = self._atomic_bet_deduct(user_id, channel, duel["amount"])
        if not success:
            await ctx.send(f"@{ctx.author.name} {error}")
            return

        # Both players have now paid - remove pending duel
        del self._pending_duels[channel][challenger]

        if random.random() < 0.5:
            winner = ctx.author.name
            loser = challenger
            winner_id = user_id
            loser_id = duel["challenger_id"]
        else:
            winner = challenger
            loser = ctx.author.name
            winner_id = duel["challenger_id"]
            loser_id = user_id

        amount = duel["amount"]
        # Both players already paid (escrowed), so winner gets 2x the bet
        # Winner gets their bet back + loser's bet = 2 * amount
        self._update_points(winner_id, winner, channel, amount * 2)
        # Loser already paid, nothing more to deduct

        await ctx.send(f"⚔️ DUEL: @{winner} defeats @{loser} and wins {amount} points! ⚔️")

        logger.info(
            "Duel in %s: %s defeated %s for %d points",
            channel, winner, loser, amount
        )

    @commands.command(name="cancelduel")
    async def cancel_duel_cmd(self, ctx: Context) -> None:
        """Cancel your pending duel challenge."""
        channel = ctx.channel.name
        challenger = ctx.author.name.lower()

        if channel not in self._pending_duels:
            await ctx.send(f"@{ctx.author.name} You don't have a pending duel.")
            return

        if challenger not in self._pending_duels[channel]:
            await ctx.send(f"@{ctx.author.name} You don't have a pending duel.")
            return

        duel = self._pending_duels[channel][challenger]
        # SECURITY FIX: Refund escrowed points on cancel
        if duel.get("escrowed"):
            self._update_points(duel["challenger_id"], challenger, channel, duel["amount"])
        del self._pending_duels[channel][challenger]
        await ctx.send(f"@{ctx.author.name} Your duel challenge has been cancelled and points refunded.")

    @commands.command(name="gamblingtoggle")
    @is_moderator()
    async def gambling_toggle_cmd(self, ctx: Context) -> None:
        """Toggle gambling on/off (mod only)."""
        self.enabled = not self.enabled
        status = "enabled" if self.enabled else "disabled"
        await ctx.send(f"@{ctx.author.name} Gambling is now {status}.")
        logger.info("Gambling %s by %s in %s", status, ctx.author.name, ctx.channel.name)

    @commands.command(name="setminbet")
    @is_moderator()
    async def set_min_bet_cmd(self, ctx: Context, amount: str = "") -> None:
        """Set minimum bet amount (mod only). Usage: !setminbet <amount>"""
        if not amount:
            await ctx.send(f"@{ctx.author.name} Current min bet: {self.min_bet}. Usage: !setminbet <amount>")
            return

        try:
            new_min = int(amount)
            if new_min < 1:
                await ctx.send(f"@{ctx.author.name} Minimum bet must be at least 1.")
                return
            if new_min > self.max_bet:
                await ctx.send(f"@{ctx.author.name} Minimum bet can't exceed max bet ({self.max_bet}).")
                return

            self.min_bet = new_min
            await ctx.send(f"@{ctx.author.name} Minimum bet set to {self.min_bet} points.")
            logger.info("Min bet set to %d by %s in %s", self.min_bet, ctx.author.name, ctx.channel.name)
        except ValueError:
            await ctx.send(f"@{ctx.author.name} Invalid amount. Use a number.")

    @commands.command(name="setmaxbet")
    @is_moderator()
    async def set_max_bet_cmd(self, ctx: Context, amount: str = "") -> None:
        """Set maximum bet amount (mod only). Usage: !setmaxbet <amount>"""
        if not amount:
            await ctx.send(f"@{ctx.author.name} Current max bet: {self.max_bet}. Usage: !setmaxbet <amount>")
            return

        try:
            new_max = int(amount)
            if new_max < self.min_bet:
                await ctx.send(f"@{ctx.author.name} Maximum bet can't be less than min bet ({self.min_bet}).")
                return

            self.max_bet = new_max
            await ctx.send(f"@{ctx.author.name} Maximum bet set to {self.max_bet} points.")
            logger.info("Max bet set to %d by %s in %s", self.max_bet, ctx.author.name, ctx.channel.name)
        except ValueError:
            await ctx.send(f"@{ctx.author.name} Invalid amount. Use a number.")


def prepare(bot: TwitchBot) -> None:
    """Prepare the cog for loading."""
    bot.add_cog(Gambling(bot))
