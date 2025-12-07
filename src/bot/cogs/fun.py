"""
Fun commands cog.

Provides entertaining interactive commands:
- !hello: Greet the user
- !dice: Roll dice (supports notation like 2d6)
- !8ball: Magic 8-ball
- !coinflip: Flip a coin
- !hug: Hug someone
"""

from __future__ import annotations

import random
import re
from typing import TYPE_CHECKING

from twitchio.ext import commands
from twitchio.ext.commands import Context

from bot.utils.logging import get_logger
from bot.utils.permissions import cooldown, CooldownBucket

if TYPE_CHECKING:
    from bot.bot import TwitchBot

logger = get_logger(__name__)

# Magic 8-ball responses
EIGHT_BALL_RESPONSES = [
    # Positive
    "It is certain.",
    "It is decidedly so.",
    "Without a doubt.",
    "Yes, definitely.",
    "You may rely on it.",
    "As I see it, yes.",
    "Most likely.",
    "Outlook good.",
    "Yes.",
    "Signs point to yes.",
    # Neutral
    "Reply hazy, try again.",
    "Ask again later.",
    "Better not tell you now.",
    "Cannot predict now.",
    "Concentrate and ask again.",
    # Negative
    "Don't count on it.",
    "My reply is no.",
    "My sources say no.",
    "Outlook not so good.",
    "Very doubtful.",
]

# Dice notation regex pattern (e.g., 2d6, 1d20, 3d8+5)
DICE_PATTERN = re.compile(r'^(\d+)?d(\d+)([+-]\d+)?$', re.IGNORECASE)


class FunCog(commands.Cog):
    """
    Fun interactive commands for chat entertainment.

    These commands are available to all users with cooldowns.
    """

    def __init__(self, bot: TwitchBot) -> None:
        """
        Initialize the fun cog.

        Args:
            bot: The bot instance
        """
        self.bot = bot

    @commands.command(name="hello", aliases=["hi", "hey"])
    @cooldown(rate=3.0, bucket=CooldownBucket.USER)
    async def hello(self, ctx: Context) -> None:
        """
        Greet the user with a friendly message.

        Usage: !hello
        """
        greetings = [
            f"Hello @{ctx.author.name}! Welcome to the stream! 👋",
            f"Hey there @{ctx.author.name}! Great to see you! 😊",
            f"Hi @{ctx.author.name}! Hope you're having a great day! 🎉",
            f"Greetings @{ctx.author.name}! Enjoy the stream! 🌟",
            f"What's up @{ctx.author.name}! Glad you're here! 💜",
        ]
        await ctx.send(random.choice(greetings))

    @commands.command(name="dice", aliases=["roll", "d"])
    @cooldown(rate=3.0, bucket=CooldownBucket.USER)
    async def dice(self, ctx: Context, dice_input: str = "1d6") -> None:
        """
        Roll dice with flexible notation.

        Usage: !dice [notation]
        Examples:
            !dice         - Roll a single d6
            !dice 20      - Roll a d20
            !dice 2d6     - Roll two 6-sided dice
            !dice 3d8+5   - Roll three d8 and add 5
            !dice 1d20-2  - Roll a d20 and subtract 2
        """
        dice_input = dice_input.strip().lower()
        
        # Check if it's just a number (shorthand for 1dX)
        if dice_input.isdigit():
            sides = int(dice_input)
            num_dice = 1
            modifier = 0
        else:
            # Try to parse dice notation
            match = DICE_PATTERN.match(dice_input)
            if not match:
                await ctx.send(
                    f"@{ctx.author.name} Invalid dice format! Use: !dice 2d6, !dice 20, or !dice 3d8+5"
                )
                return
            
            num_dice = int(match.group(1)) if match.group(1) else 1
            sides = int(match.group(2))
            modifier = int(match.group(3)) if match.group(3) else 0

        # Validate inputs
        if num_dice < 1:
            await ctx.send(f"@{ctx.author.name} You need to roll at least 1 die!")
            return
        if num_dice > 100:
            await ctx.send(f"@{ctx.author.name} Too many dice! Max: 100")
            return
        if sides < 2:
            await ctx.send(f"@{ctx.author.name} Dice must have at least 2 sides!")
            return
        if sides > 1000000:
            await ctx.send(f"@{ctx.author.name} That's too many sides! Max: 1,000,000")
            return

        # Roll the dice
        rolls = [random.randint(1, sides) for _ in range(num_dice)]
        total = sum(rolls) + modifier

        # Format the response
        if num_dice == 1 and modifier == 0:
            await ctx.send(f"@{ctx.author.name} 🎲 rolled a d{sides} and got: {total}")
        elif num_dice == 1:
            mod_str = f"+{modifier}" if modifier > 0 else str(modifier)
            await ctx.send(
                f"@{ctx.author.name} 🎲 rolled d{sides}{mod_str}: {rolls[0]} {mod_str} = {total}"
            )
        else:
            rolls_str = ", ".join(str(r) for r in rolls)
            if modifier != 0:
                mod_str = f"+{modifier}" if modifier > 0 else str(modifier)
                await ctx.send(
                    f"@{ctx.author.name} 🎲 rolled {num_dice}d{sides}{mod_str}: [{rolls_str}] {mod_str} = {total}"
                )
            else:
                await ctx.send(
                    f"@{ctx.author.name} 🎲 rolled {num_dice}d{sides}: [{rolls_str}] = {total}"
                )

    @commands.command(name="8ball", aliases=["eightball", "magic8ball"])
    @cooldown(rate=5.0, bucket=CooldownBucket.USER)
    async def eight_ball(self, ctx: Context, *, question: str | None = None) -> None:
        """
        Ask the magic 8-ball a question.

        Usage: !8ball <question>
        Example: !8ball Will I win today?
        """
        if not question:
            await ctx.send(
                f"@{ctx.author.name} You need to ask a question! "
                f"Usage: {self.bot.config.prefix}8ball <question>"
            )
            return

        response = random.choice(EIGHT_BALL_RESPONSES)
        await ctx.send(f"@{ctx.author.name} 🎱 {response}")

    @commands.command(name="coinflip", aliases=["flip", "coin"])
    @cooldown(rate=3.0, bucket=CooldownBucket.USER)
    async def coinflip(self, ctx: Context) -> None:
        """
        Flip a coin.

        Usage: !coinflip
        """
        result = random.choice(["Heads", "Tails"])
        emoji = "🪙" if result == "Heads" else "🪙"
        await ctx.send(f"@{ctx.author.name} {emoji} The coin landed on: {result}!")

    @commands.command(name="hug")
    @cooldown(rate=5.0, bucket=CooldownBucket.USER)
    async def hug(self, ctx: Context, target: str | None = None) -> None:
        """
        Give someone a hug!

        Usage: !hug @username
        Example: !hug @streamer
        """
        if not target:
            await ctx.send(f"@{ctx.author.name} gives themselves a self-hug! 🤗")
            return

        # Clean up the target name (remove @ if present)
        target = target.lstrip("@")

        # Don't let people hug the bot
        if target.lower() == self.bot.nick.lower():
            await ctx.send(f"@{ctx.author.name} Aww, thanks for the hug! 🤗💕")
            return

        # Don't let people hug themselves via command
        if target.lower() == ctx.author.name.lower():
            await ctx.send(f"@{ctx.author.name} gives themselves a big self-hug! 🤗")
            return

        await ctx.send(f"@{ctx.author.name} gives @{target} a warm hug! 🤗💕")

    @commands.command(name="rps", aliases=["rockpaperscissors"])
    @cooldown(rate=3.0, bucket=CooldownBucket.USER)
    async def rock_paper_scissors(
        self, ctx: Context, choice: str | None = None
    ) -> None:
        """
        Play rock, paper, scissors against the bot.

        Usage: !rps <rock|paper|scissors>
        Example: !rps rock
        """
        choices = ["rock", "paper", "scissors"]
        emojis = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}

        if not choice or choice.lower() not in choices:
            await ctx.send(
                f"@{ctx.author.name} Usage: {self.bot.config.prefix}rps <rock|paper|scissors>"
            )
            return

        player_choice = choice.lower()
        bot_choice = random.choice(choices)

        # Determine winner
        if player_choice == bot_choice:
            result = "It's a tie!"
        elif (
            (player_choice == "rock" and bot_choice == "scissors")
            or (player_choice == "paper" and bot_choice == "rock")
            or (player_choice == "scissors" and bot_choice == "paper")
        ):
            result = "You win! 🎉"
        else:
            result = "I win! 😎"

        await ctx.send(
            f"@{ctx.author.name} {emojis[player_choice]} vs {emojis[bot_choice]} - {result}"
        )

    @commands.command(name="choose", aliases=["pick"])
    @cooldown(rate=3.0, bucket=CooldownBucket.USER)
    async def choose(self, ctx: Context, *, options: str | None = None) -> None:
        """
        Let the bot choose between options.

        Usage: !choose option1, option2, option3
        Example: !choose pizza, burger, salad
        """
        if not options:
            await ctx.send(
                f"@{ctx.author.name} Usage: {self.bot.config.prefix}choose option1, option2, ..."
            )
            return

        # Split by comma or "or"
        choices = [c.strip() for c in options.replace(" or ", ",").split(",")]
        choices = [c for c in choices if c]  # Remove empty strings

        if len(choices) < 2:
            await ctx.send(f"@{ctx.author.name} Give me at least 2 options to choose from!")
            return

        choice = random.choice(choices)
        await ctx.send(f"@{ctx.author.name} 🤔 I choose: {choice}")


def prepare(bot: TwitchBot) -> None:
    """
    Prepare function called by TwitchIO when loading the cog.

    Args:
        bot: The bot instance
    """
    bot.add_cog(FunCog(bot))
