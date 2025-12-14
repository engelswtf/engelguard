"""
Predictions system cog for Twitch bot.

Provides both native Twitch Predictions (API) and chat-based predictions:
- Create predictions with multiple outcomes
- Lock betting window
- Resolve predictions with winner selection
- Cancel predictions
- Proportional payout system using loyalty points
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Optional, Any

from twitchio.ext import commands
from twitchio.ext.commands import Context

from bot.utils.database import get_database, DatabaseManager
from bot.utils.logging import get_logger
from bot.utils.permissions import is_moderator, cooldown, CooldownBucket

if TYPE_CHECKING:
    from twitchio import Message
    from bot.bot import TwitchBot

logger = get_logger(__name__)


class Predictions(commands.Cog):
    """
    Predictions system cog for viewer engagement.
    
    Features:
    - Native Twitch Predictions (API-based) when available
    - Chat-based predictions as fallback
    - Loyalty points betting
    - Configurable prediction window
    - Proportional payout calculation
    - Min/max bet limits
    - Real-time odds display
    - Prediction history
    """
    
    # Default settings
    DEFAULT_PREDICTION_WINDOW = 120  # seconds before auto-lock
    DEFAULT_MIN_BET = 10
    DEFAULT_MAX_BET = 10000
    
    def __init__(self, bot: TwitchBot) -> None:
        """Initialize the predictions cog."""
        self.bot = bot
        self.db: DatabaseManager = get_database()
        
        # Per-channel settings (could be made persistent)
        self._settings: dict[str, dict[str, Any]] = {}
        
        # Track active predictions for quick lookup
        self._active_predictions: dict[str, int] = {}  # {channel: prediction_id}
        
        # Background task for auto-locking
        self._auto_lock_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Initialize database tables
        self._init_tables()
        
        logger.info("Predictions cog initialized")
    
    def _init_tables(self) -> None:
        """Initialize prediction database tables."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Predictions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    question TEXT NOT NULL,
                    outcomes TEXT NOT NULL,
                    started_by TEXT NOT NULL,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    locked_at TIMESTAMP,
                    resolved_at TIMESTAMP,
                    winning_outcome INTEGER,
                    status TEXT DEFAULT 'open',
                    prediction_type TEXT DEFAULT 'chat',
                    twitch_prediction_id TEXT,
                    auto_lock_at TIMESTAMP
                )
            """)
            
            # Prediction bets table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS prediction_bets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prediction_id INTEGER NOT NULL,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    outcome_index INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    bet_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    payout INTEGER DEFAULT 0,
                    UNIQUE(prediction_id, user_id),
                    FOREIGN KEY (prediction_id) REFERENCES predictions(id)
                )
            """)
            
            # Create indexes for performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_predictions_channel_status 
                ON predictions(channel, status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_prediction_bets_prediction 
                ON prediction_bets(prediction_id)
            """)
            
            logger.debug("Prediction tables initialized")
    
    async def cog_load(self) -> None:
        """Called when cog is loaded."""
        self._running = True
        self._auto_lock_task = asyncio.create_task(self._auto_lock_loop())
        
        # Load active predictions
        await self._load_active_predictions()
        
        logger.info("Predictions cog loaded, auto-lock task started")
    
    async def cog_unload(self) -> None:
        """Called when cog is unloaded."""
        self._running = False
        if self._auto_lock_task:
            self._auto_lock_task.cancel()
            try:
                await self._auto_lock_task
            except asyncio.CancelledError:
                pass
        logger.info("Predictions cog unloaded")
    
    async def _load_active_predictions(self) -> None:
        """Load active predictions from database."""
        for channel in self.bot.connected_channels:
            prediction = self._get_active_prediction(channel.name)
            if prediction:
                self._active_predictions[channel.name.lower()] = prediction["id"]
    
    async def _auto_lock_loop(self) -> None:
        """Background task to auto-lock predictions after window expires."""
        await self.bot.wait_until_ready()
        
        while self._running:
            try:
                await self._check_auto_locks()
            except Exception as e:
                logger.error("Error in auto-lock loop: %s", e)
            
            # Check every 5 seconds
            await asyncio.sleep(5)
    
    async def _check_auto_locks(self) -> None:
        """Check for predictions that need to be auto-locked."""
        now = datetime.now(timezone.utc)
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, channel FROM predictions 
                WHERE status = 'open' 
                AND auto_lock_at IS NOT NULL 
                AND auto_lock_at <= ?
            """, (now.isoformat(),))
            
            to_lock = cursor.fetchall()
        
        for row in to_lock:
            prediction_id = row["id"]
            channel_name = row["channel"]
            
            # Lock the prediction
            self._lock_prediction(prediction_id)
            
            # Find channel and announce
            for channel in self.bot.connected_channels:
                if channel.name.lower() == channel_name.lower():
                    await channel.send(
                        "⏰ Prediction betting is now LOCKED! No more bets accepted."
                    )
                    break
            
            logger.info("Auto-locked prediction %d in %s", prediction_id, channel_name)
    
    def _get_channel_settings(self, channel: str) -> dict[str, Any]:
        """Get prediction settings for a channel."""
        channel = channel.lower()
        if channel not in self._settings:
            self._settings[channel] = {
                "prediction_window": self.DEFAULT_PREDICTION_WINDOW,
                "min_bet": self.DEFAULT_MIN_BET,
                "max_bet": self.DEFAULT_MAX_BET,
                "enabled": True,
            }
        return self._settings[channel]
    
    def _get_active_prediction(self, channel: str) -> Optional[dict[str, Any]]:
        """Get the active prediction for a channel."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM predictions 
                WHERE channel = ? AND status IN ('open', 'locked')
                ORDER BY started_at DESC LIMIT 1
            """, (channel.lower(),))
            row = cursor.fetchone()
            
            if row:
                result = dict(row)
                result["outcomes"] = json.loads(result["outcomes"])
                return result
            return None
    
    def _create_prediction(
        self,
        channel: str,
        question: str,
        outcomes: list[str],
        started_by: str,
        prediction_window: int,
        prediction_type: str = "chat",
        twitch_prediction_id: Optional[str] = None
    ) -> int:
        """Create a new prediction."""
        auto_lock_at = None
        if prediction_window > 0:
            auto_lock_at = (
                datetime.now(timezone.utc) + timedelta(seconds=prediction_window)
            ).isoformat()
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO predictions 
                (channel, question, outcomes, started_by, prediction_type, 
                 twitch_prediction_id, auto_lock_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                channel.lower(),
                question,
                json.dumps(outcomes),
                started_by,
                prediction_type,
                twitch_prediction_id,
                auto_lock_at
            ))
            return cursor.lastrowid
    
    def _lock_prediction(self, prediction_id: int) -> bool:
        """Lock a prediction (no more bets)."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE predictions 
                SET status = 'locked', locked_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'open'
            """, (prediction_id,))
            return cursor.rowcount > 0
    
    def _resolve_prediction(self, prediction_id: int, winning_outcome: int) -> list[dict]:
        """Resolve a prediction and calculate payouts."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get prediction info
            cursor.execute("SELECT * FROM predictions WHERE id = ?", (prediction_id,))
            prediction = cursor.fetchone()
            if not prediction:
                return []
            
            # Get all bets
            cursor.execute("""
                SELECT * FROM prediction_bets WHERE prediction_id = ?
            """, (prediction_id,))
            all_bets = cursor.fetchall()
            
            if not all_bets:
                # No bets, just close
                cursor.execute("""
                    UPDATE predictions 
                    SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP,
                        winning_outcome = ?
                    WHERE id = ?
                """, (winning_outcome, prediction_id))
                return []
            
            # Calculate pools
            total_pool = sum(bet["amount"] for bet in all_bets)
            winner_pool = sum(
                bet["amount"] for bet in all_bets 
                if bet["outcome_index"] == winning_outcome
            )
            
            # Calculate payout ratio
            if winner_pool > 0:
                payout_ratio = total_pool / winner_pool
            else:
                payout_ratio = 0
            
            winners = []
            channel = prediction["channel"]
            
            for bet in all_bets:
                if bet["outcome_index"] == winning_outcome:
                    # Winner - calculate payout
                    payout = int(bet["amount"] * payout_ratio)
                    
                    # Update bet record
                    cursor.execute("""
                        UPDATE prediction_bets SET payout = ? WHERE id = ?
                    """, (payout, bet["id"]))
                    
                    # Award points to winner
                    self.db.update_user_loyalty(
                        user_id=bet["user_id"],
                        username=bet["username"],
                        channel=channel,
                        points_delta=payout
                    )
                    
                    winners.append({
                        "user_id": bet["user_id"],
                        "username": bet["username"],
                        "bet": bet["amount"],
                        "payout": payout
                    })
            
            # Mark prediction as resolved
            cursor.execute("""
                UPDATE predictions 
                SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP,
                    winning_outcome = ?
                WHERE id = ?
            """, (winning_outcome, prediction_id))
            
            return winners
    
    def _cancel_prediction(self, prediction_id: int) -> int:
        """Cancel a prediction and refund all bets."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get prediction info
            cursor.execute("SELECT channel FROM predictions WHERE id = ?", (prediction_id,))
            prediction = cursor.fetchone()
            if not prediction:
                return 0
            
            channel = prediction["channel"]
            
            # Get all bets for refund
            cursor.execute("""
                SELECT * FROM prediction_bets WHERE prediction_id = ?
            """, (prediction_id,))
            bets = cursor.fetchall()
            
            # Refund each bet
            for bet in bets:
                self.db.update_user_loyalty(
                    user_id=bet["user_id"],
                    username=bet["username"],
                    channel=channel,
                    points_delta=bet["amount"]
                )
            
            # Mark prediction as cancelled
            cursor.execute("""
                UPDATE predictions 
                SET status = 'cancelled', resolved_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (prediction_id,))
            
            return len(bets)
    
    def _place_bet(
        self,
        prediction_id: int,
        user_id: str,
        username: str,
        outcome_index: int,
        amount: int,
        channel: str
    ) -> tuple[bool, str]:
        """Place bet with strict transaction isolation to prevent race conditions."""
        with self.db.get_connection() as conn:
            # Set exclusive lock for this transaction to prevent race conditions
            conn.execute("BEGIN EXCLUSIVE")
            cursor = conn.cursor()
            
            try:
                # Check if prediction is open
                cursor.execute("""
                    SELECT status, outcomes FROM predictions WHERE id = ?
                """, (prediction_id,))
                prediction = cursor.fetchone()
                
                if not prediction:
                    conn.rollback()
                    return False, "Prediction not found."
                
                if prediction["status"] != "open":
                    conn.rollback()
                    return False, "Betting is closed for this prediction."
                
                outcomes = json.loads(prediction["outcomes"])
                if outcome_index < 1 or outcome_index > len(outcomes):
                    conn.rollback()
                    return False, f"Invalid outcome. Choose 1-{len(outcomes)}."
                
                # Check if user already bet
                cursor.execute("""
                    SELECT id FROM prediction_bets 
                    WHERE prediction_id = ? AND user_id = ?
                """, (prediction_id, user_id))
                
                if cursor.fetchone():
                    conn.rollback()
                    return False, "You already placed a bet on this prediction."
                
                # Ensure user exists in loyalty table
                cursor.execute("""
                    INSERT INTO user_loyalty (user_id, username, channel, points)
                    VALUES (?, ?, ?, 0)
                    ON CONFLICT(user_id, channel) DO NOTHING
                """, (user_id, username, channel.lower()))
                
                # Atomic point deduction with balance check
                cursor.execute("""
                    UPDATE user_loyalty 
                    SET points = points - ?
                    WHERE user_id = ? AND channel = ? AND points >= ?
                """, (amount, user_id, channel.lower(), amount))
                
                if cursor.rowcount == 0:
                    conn.rollback()
                    return False, "Insufficient points."
                
                # Record bet (convert to 0-indexed for storage)
                cursor.execute("""
                    INSERT INTO prediction_bets 
                    (prediction_id, user_id, username, outcome_index, amount)
                    VALUES (?, ?, ?, ?, ?)
                """, (prediction_id, user_id, username, outcome_index - 1, amount))
                
                conn.commit()
                return True, f"Bet of {amount:,} points placed!"
                
            except Exception as e:
                conn.rollback()
                logger.error("Error placing bet: %s", e)
                return False, "Error placing bet. Please try again."
    
    def _get_prediction_stats(self, prediction_id: int) -> dict[str, Any]:
        """Get statistics for a prediction."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get prediction
            cursor.execute("SELECT * FROM predictions WHERE id = ?", (prediction_id,))
            prediction = cursor.fetchone()
            
            if not prediction:
                return {}
            
            outcomes = json.loads(prediction["outcomes"])
            
            # Get bet totals per outcome
            cursor.execute("""
                SELECT outcome_index, COUNT(*) as bet_count, SUM(amount) as total_amount
                FROM prediction_bets
                WHERE prediction_id = ?
                GROUP BY outcome_index
            """, (prediction_id,))
            
            outcome_stats = {i: {"bets": 0, "amount": 0} for i in range(len(outcomes))}
            total_pool = 0
            total_bets = 0
            
            for row in cursor.fetchall():
                idx = row["outcome_index"]
                outcome_stats[idx] = {
                    "bets": row["bet_count"],
                    "amount": row["total_amount"]
                }
                total_pool += row["total_amount"]
                total_bets += row["bet_count"]
            
            # Calculate odds for each outcome
            odds = {}
            for i, outcome in enumerate(outcomes):
                if outcome_stats[i]["amount"] > 0:
                    odds[i] = total_pool / outcome_stats[i]["amount"]
                else:
                    odds[i] = 0  # No bets yet
            
            return {
                "prediction": dict(prediction),
                "outcomes": outcomes,
                "outcome_stats": outcome_stats,
                "odds": odds,
                "total_pool": total_pool,
                "total_bets": total_bets
            }
    
    def _get_user_points(self, user_id: str, channel: str) -> int:
        """Get user's current points."""
        loyalty = self.db.get_user_loyalty(user_id, channel)
        return int(loyalty.get("points", 0))
    
    # ==================== Commands ====================
    
    @commands.command(name="predict", aliases=["prediction"])
    async def predict_command(self, ctx: Context, action: str = "", *args: str) -> None:
        """
        Prediction management command.
        
        Usage:
        - !predict start "Question" "Outcome1" "Outcome2" - Start prediction (mod)
        - !predict lock - Lock betting (mod)
        - !predict resolve <outcome_number> - Resolve with winner (mod)
        - !predict cancel - Cancel prediction (mod)
        - !predict info - Show current prediction info
        - !predict odds - Show current odds
        """
        action = action.lower()
        
        if action == "start":
            await self._predict_start(ctx, *args)
        elif action == "lock":
            await self._predict_lock(ctx)
        elif action == "resolve":
            await self._predict_resolve(ctx, *args)
        elif action == "cancel":
            await self._predict_cancel(ctx)
        elif action == "info":
            await self._predict_info(ctx)
        elif action == "odds":
            await self._predict_odds(ctx)
        elif action == "history":
            await self._predict_history(ctx)
        else:
            await ctx.send(
                f"@{ctx.author.name} Prediction commands: !predict start \"Question\" \"Option1\" \"Option2\" | "
                f"!predict lock | !predict resolve <#> | !predict cancel | !predict info | !predict odds"
            )
    
    async def _predict_start(self, ctx: Context, *args: str) -> None:
        """Start a new prediction."""
        # Check permissions
        if not (ctx.author.is_mod or ctx.author.is_broadcaster):
            await ctx.send(f"@{ctx.author.name} You need to be a moderator to start predictions.")
            return
        
        channel_name = ctx.channel.name
        settings = self._get_channel_settings(channel_name)
        
        if not settings.get("enabled", True):
            await ctx.send(f"@{ctx.author.name} Predictions are disabled in this channel.")
            return
        
        # Check for existing active prediction
        existing = self._get_active_prediction(channel_name)
        if existing:
            await ctx.send(
                f"@{ctx.author.name} There's already an active prediction! "
                f"Use !predict resolve or !predict cancel first."
            )
            return
        
        # Parse arguments - expecting quoted strings
        # Reconstruct the full argument string
        full_args = " ".join(args)
        
        # Parse quoted strings
        import re
        quoted = re.findall(r'"([^"]+)"', full_args)
        
        if len(quoted) < 3:
            await ctx.send(
                f"@{ctx.author.name} Usage: !predict start \"Question\" \"Outcome1\" \"Outcome2\" [\"Outcome3\"...]"
            )
            return
        
        question = quoted[0]
        outcomes = quoted[1:]
        
        if len(outcomes) < 2:
            await ctx.send(f"@{ctx.author.name} You need at least 2 outcomes.")
            return
        
        if len(outcomes) > 10:
            await ctx.send(f"@{ctx.author.name} Maximum 10 outcomes allowed.")
            return
        
        # Create the prediction
        prediction_window = settings.get("prediction_window", self.DEFAULT_PREDICTION_WINDOW)
        prediction_id = self._create_prediction(
            channel=channel_name,
            question=question,
            outcomes=outcomes,
            started_by=ctx.author.name,
            prediction_window=prediction_window
        )
        
        # Track active prediction
        self._active_predictions[channel_name.lower()] = prediction_id
        
        # Build announcement
        outcome_list = " | ".join(
            f"[{i+1}] {outcome}" for i, outcome in enumerate(outcomes)
        )
        
        announcement = (
            f"🔮 PREDICTION: {question} | "
            f"{outcome_list} | "
            f"Use !bet <#> <amount> to bet! "
        )
        
        if prediction_window > 0:
            minutes = prediction_window // 60
            seconds = prediction_window % 60
            if minutes > 0:
                announcement += f"Betting closes in {minutes}m {seconds}s!"
            else:
                announcement += f"Betting closes in {seconds}s!"
        
        await ctx.send(announcement)
        logger.info(
            "Prediction %d started in %s by %s: %s",
            prediction_id, channel_name, ctx.author.name, question
        )
    
    async def _predict_lock(self, ctx: Context) -> None:
        """Lock betting on the current prediction."""
        # Check permissions
        if not (ctx.author.is_mod or ctx.author.is_broadcaster):
            await ctx.send(f"@{ctx.author.name} You need to be a moderator to lock predictions.")
            return
        
        channel_name = ctx.channel.name
        prediction = self._get_active_prediction(channel_name)
        
        if not prediction:
            await ctx.send(f"@{ctx.author.name} No active prediction to lock.")
            return
        
        if prediction["status"] == "locked":
            await ctx.send(f"@{ctx.author.name} Prediction is already locked.")
            return
        
        self._lock_prediction(prediction["id"])
        
        stats = self._get_prediction_stats(prediction["id"])
        total_pool = stats.get("total_pool", 0)
        total_bets = stats.get("total_bets", 0)
        
        await ctx.send(
            f"🔒 Prediction LOCKED! No more bets. "
            f"Total pool: {total_pool:,} points from {total_bets} bets."
        )
        logger.info(
            "Prediction %d locked in %s by %s",
            prediction["id"], channel_name, ctx.author.name
        )
    
    async def _predict_resolve(self, ctx: Context, *args: str) -> None:
        """Resolve the prediction with a winning outcome."""
        # Check permissions
        if not (ctx.author.is_mod or ctx.author.is_broadcaster):
            await ctx.send(f"@{ctx.author.name} You need to be a moderator to resolve predictions.")
            return
        
        channel_name = ctx.channel.name
        prediction = self._get_active_prediction(channel_name)
        
        if not prediction:
            await ctx.send(f"@{ctx.author.name} No active prediction to resolve.")
            return
        
        if not args:
            outcomes = prediction["outcomes"]
            outcome_list = " | ".join(
                f"[{i+1}] {outcome}" for i, outcome in enumerate(outcomes)
            )
            await ctx.send(
                f"@{ctx.author.name} Usage: !predict resolve <outcome_number> | "
                f"Outcomes: {outcome_list}"
            )
            return
        
        try:
            winning_outcome = int(args[0])
        except ValueError:
            await ctx.send(f"@{ctx.author.name} Please provide a valid outcome number.")
            return
        
        outcomes = prediction["outcomes"]
        if winning_outcome < 1 or winning_outcome > len(outcomes):
            await ctx.send(
                f"@{ctx.author.name} Invalid outcome. Choose 1-{len(outcomes)}."
            )
            return
        
        # Lock first if still open
        if prediction["status"] == "open":
            self._lock_prediction(prediction["id"])
        
        # Resolve and get winners (convert to 0-indexed)
        winners = self._resolve_prediction(prediction["id"], winning_outcome - 1)
        
        # Remove from active predictions
        if channel_name.lower() in self._active_predictions:
            del self._active_predictions[channel_name.lower()]
        
        # Announce results
        winning_text = outcomes[winning_outcome - 1]
        
        if winners:
            total_payout = sum(w["payout"] for w in winners)
            top_winners = sorted(winners, key=lambda x: x["payout"], reverse=True)[:3]
            winner_text = ", ".join(
                f"@{w['username']} (+{w['payout']:,})" for w in top_winners
            )
            
            await ctx.send(
                f"🎉 PREDICTION RESOLVED! Winner: [{winning_outcome}] {winning_text} | "
                f"Total payout: {total_payout:,} points | "
                f"Top winners: {winner_text}"
            )
        else:
            await ctx.send(
                f"🎉 PREDICTION RESOLVED! Winner: [{winning_outcome}] {winning_text} | "
                f"No winning bets."
            )
        
        logger.info(
            "Prediction %d resolved in %s by %s, winner: %s",
            prediction["id"], channel_name, ctx.author.name, winning_text
        )
    
    async def _predict_cancel(self, ctx: Context) -> None:
        """Cancel the current prediction and refund all bets."""
        # Check permissions
        if not (ctx.author.is_mod or ctx.author.is_broadcaster):
            await ctx.send(f"@{ctx.author.name} You need to be a moderator to cancel predictions.")
            return
        
        channel_name = ctx.channel.name
        prediction = self._get_active_prediction(channel_name)
        
        if not prediction:
            await ctx.send(f"@{ctx.author.name} No active prediction to cancel.")
            return
        
        refund_count = self._cancel_prediction(prediction["id"])
        
        # Remove from active predictions
        if channel_name.lower() in self._active_predictions:
            del self._active_predictions[channel_name.lower()]
        
        await ctx.send(
            f"❌ Prediction CANCELLED! {refund_count} bet(s) have been refunded."
        )
        logger.info(
            "Prediction %d cancelled in %s by %s, %d refunds",
            prediction["id"], channel_name, ctx.author.name, refund_count
        )
    
    async def _predict_info(self, ctx: Context) -> None:
        """Show information about the current prediction."""
        channel_name = ctx.channel.name
        prediction = self._get_active_prediction(channel_name)
        
        if not prediction:
            await ctx.send(f"@{ctx.author.name} No active prediction.")
            return
        
        stats = self._get_prediction_stats(prediction["id"])
        outcomes = stats["outcomes"]
        outcome_stats = stats["outcome_stats"]
        total_pool = stats["total_pool"]
        total_bets = stats["total_bets"]
        status = prediction["status"].upper()
        
        # Build outcome info
        outcome_info = []
        for i, outcome in enumerate(outcomes):
            bets = outcome_stats[i]["bets"]
            amount = outcome_stats[i]["amount"]
            outcome_info.append(f"[{i+1}] {outcome}: {bets} bets, {amount:,} pts")
        
        outcome_text = " | ".join(outcome_info)
        
        await ctx.send(
            f"🔮 {prediction['question']} | Status: {status} | "
            f"Pool: {total_pool:,} pts ({total_bets} bets) | "
            f"{outcome_text}"
        )
    
    async def _predict_odds(self, ctx: Context) -> None:
        """Show current odds for the prediction."""
        channel_name = ctx.channel.name
        prediction = self._get_active_prediction(channel_name)
        
        if not prediction:
            await ctx.send(f"@{ctx.author.name} No active prediction.")
            return
        
        stats = self._get_prediction_stats(prediction["id"])
        outcomes = stats["outcomes"]
        odds = stats["odds"]
        total_pool = stats["total_pool"]
        
        if total_pool == 0:
            await ctx.send(
                f"@{ctx.author.name} No bets yet! Be the first to bet with !bet <#> <amount>"
            )
            return
        
        # Build odds info
        odds_info = []
        for i, outcome in enumerate(outcomes):
            if odds[i] > 0:
                odds_info.append(f"[{i+1}] {outcome}: {odds[i]:.2f}x")
            else:
                odds_info.append(f"[{i+1}] {outcome}: No bets")
        
        odds_text = " | ".join(odds_info)
        
        await ctx.send(f"📊 Current odds: {odds_text} | Total pool: {total_pool:,} pts")
    
    async def _predict_history(self, ctx: Context) -> None:
        """Show recent prediction history."""
        channel_name = ctx.channel.name
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT question, status, winning_outcome, outcomes, resolved_at
                FROM predictions
                WHERE channel = ? AND status IN ('resolved', 'cancelled')
                ORDER BY resolved_at DESC
                LIMIT 5
            """, (channel_name.lower(),))
            
            history = cursor.fetchall()
        
        if not history:
            await ctx.send(f"@{ctx.author.name} No prediction history yet.")
            return
        
        entries = []
        for pred in history:
            question = pred["question"][:30] + "..." if len(pred["question"]) > 30 else pred["question"]
            if pred["status"] == "resolved":
                outcomes = json.loads(pred["outcomes"])
                winner = outcomes[pred["winning_outcome"]]
                entries.append(f"✓ {question} → {winner}")
            else:
                entries.append(f"✗ {question} (cancelled)")
        
        await ctx.send(f"📜 Recent predictions: {' | '.join(entries)}")
    
    # ==================== Bet Command ====================
    
    @commands.command(name="bet")
    @cooldown(rate=3.0, bucket=CooldownBucket.USER)
    async def bet_command(self, ctx: Context, outcome: str = "", amount: str = "") -> None:
        """
        Bet on a prediction outcome.
        
        Usage: !bet <outcome_number> <amount>
        Example: !bet 1 100
        """
        channel_name = ctx.channel.name
        settings = self._get_channel_settings(channel_name)
        
        if not settings.get("enabled", True):
            return
        
        prediction = self._get_active_prediction(channel_name)
        
        if not prediction:
            await ctx.send(f"@{ctx.author.name} No active prediction to bet on.")
            return
        
        if prediction["status"] != "open":
            await ctx.send(f"@{ctx.author.name} Betting is closed for this prediction.")
            return
        
        if not outcome or not amount:
            outcomes = prediction["outcomes"]
            outcome_list = " | ".join(
                f"[{i+1}] {o}" for i, o in enumerate(outcomes)
            )
            await ctx.send(
                f"@{ctx.author.name} Usage: !bet <outcome_number> <amount> | "
                f"Outcomes: {outcome_list}"
            )
            return
        
        # Validate outcome number
        try:
            outcome_num = int(outcome)
        except ValueError:
            await ctx.send(f"@{ctx.author.name} Invalid outcome number.")
            return
        
        # Validate amount
        try:
            bet_amount = int(amount)
        except ValueError:
            # Check for "all" or "max"
            if amount.lower() in ("all", "max"):
                bet_amount = self._get_user_points(str(ctx.author.id), channel_name)
                bet_amount = min(bet_amount, settings.get("max_bet", self.DEFAULT_MAX_BET))
            else:
                await ctx.send(f"@{ctx.author.name} Invalid amount. Use a number or 'all'.")
                return
        
        # Check bet limits
        min_bet = settings.get("min_bet", self.DEFAULT_MIN_BET)
        max_bet = settings.get("max_bet", self.DEFAULT_MAX_BET)
        
        if bet_amount < min_bet:
            await ctx.send(f"@{ctx.author.name} Minimum bet is {min_bet} points.")
            return
        
        if bet_amount > max_bet:
            await ctx.send(f"@{ctx.author.name} Maximum bet is {max_bet} points.")
            return
        
        # Place the bet
        success, message = self._place_bet(
            prediction_id=prediction["id"],
            user_id=str(ctx.author.id),
            username=ctx.author.name,
            outcome_index=outcome_num,
            amount=bet_amount,
            channel=channel_name
        )
        
        if success:
            outcome_name = prediction["outcomes"][outcome_num - 1]
            stats = self._get_prediction_stats(prediction["id"])
            odds = stats["odds"].get(outcome_num - 1, 0)
            odds_text = f" (current odds: {odds:.2f}x)" if odds > 0 else ""
            
            await ctx.send(
                f"@{ctx.author.name} Bet {bet_amount:,} points on [{outcome_num}] {outcome_name}{odds_text}"
            )
            logger.debug(
                "Bet placed: %s bet %d on outcome %d in prediction %d",
                ctx.author.name, bet_amount, outcome_num, prediction["id"]
            )
        else:
            await ctx.send(f"@{ctx.author.name} {message}")
    
    # ==================== Admin Commands ====================
    
    @commands.command(name="predictset")
    @is_moderator()
    async def predict_settings(self, ctx: Context, setting: str = "", value: str = "") -> None:
        """
        Configure prediction settings.
        
        Usage:
        - !predictset window <seconds> - Set betting window (0 = no auto-lock)
        - !predictset minbet <amount> - Set minimum bet
        - !predictset maxbet <amount> - Set maximum bet
        - !predictset toggle - Enable/disable predictions
        """
        channel_name = ctx.channel.name
        settings = self._get_channel_settings(channel_name)
        setting = setting.lower()
        
        if not setting:
            window = settings.get("prediction_window", self.DEFAULT_PREDICTION_WINDOW)
            min_bet = settings.get("min_bet", self.DEFAULT_MIN_BET)
            max_bet = settings.get("max_bet", self.DEFAULT_MAX_BET)
            enabled = "ON" if settings.get("enabled", True) else "OFF"
            
            await ctx.send(
                f"@{ctx.author.name} Prediction settings: "
                f"Window: {window}s | Min bet: {min_bet} | Max bet: {max_bet} | Status: {enabled}"
            )
            return
        
        if setting == "window":
            try:
                seconds = int(value)
                if seconds < 0:
                    seconds = 0
                settings["prediction_window"] = seconds
                await ctx.send(
                    f"@{ctx.author.name} Prediction window set to {seconds} seconds "
                    f"{'(auto-lock disabled)' if seconds == 0 else ''}"
                )
            except ValueError:
                await ctx.send(f"@{ctx.author.name} Usage: !predictset window <seconds>")
        
        elif setting == "minbet":
            try:
                amount = int(value)
                if amount < 1:
                    amount = 1
                settings["min_bet"] = amount
                await ctx.send(f"@{ctx.author.name} Minimum bet set to {amount} points.")
            except ValueError:
                await ctx.send(f"@{ctx.author.name} Usage: !predictset minbet <amount>")
        
        elif setting == "maxbet":
            try:
                amount = int(value)
                if amount < settings.get("min_bet", 1):
                    await ctx.send(
                        f"@{ctx.author.name} Max bet must be >= min bet ({settings.get('min_bet', 1)})"
                    )
                    return
                settings["max_bet"] = amount
                await ctx.send(f"@{ctx.author.name} Maximum bet set to {amount} points.")
            except ValueError:
                await ctx.send(f"@{ctx.author.name} Usage: !predictset maxbet <amount>")
        
        elif setting == "toggle":
            settings["enabled"] = not settings.get("enabled", True)
            status = "ENABLED" if settings["enabled"] else "DISABLED"
            await ctx.send(f"@{ctx.author.name} Predictions are now {status}.")
        
        else:
            await ctx.send(
                f"@{ctx.author.name} Unknown setting. Use: window, minbet, maxbet, toggle"
            )


def prepare(bot: TwitchBot) -> None:
    """Prepare the cog for loading."""
    bot.add_cog(Predictions(bot))
