"""The gateway process.

Runs alongside the API and the worker, and does two things:

  1. answers slash commands — linking an account, and reading back what that
     account is watching;
  2. polls for alerts bound for a linked Discord account and sends them as a
     direct message.

Why a poll rather than the worker pushing: a direct message needs the gateway
connection, and only this process has one. The worker leaves those alerts
unsent on purpose (see notifications/discord.py) and they are picked up here.

Database work happens in a thread, never on the event loop. SQLAlchemy's
session is blocking, and blocking the loop stalls the heartbeat — which Discord
treats as a dead client and disconnects.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from sqlalchemy import select

from app.bot.delivery import mark_failed, mark_sent, pending_dms
from app.config import settings
from app.database.session import session_scope
from app.models.enums import PriceVerdict
from app.notifications.discord import build_payload
from app.services import discord_link

logger = logging.getLogger(__name__)

#: No message content, no members, no presences: this bot reads nothing it is
#: not directly handed. Discord gates the interesting intents behind review,
#: and needing none of them is the better position anyway.
INTENTS = discord.Intents.none()

NOT_LINKED = "This Discord account is not linked. Run /link with a code from your StockWatch dashboard."


def _embed_for(notification) -> discord.Embed:  # noqa: ANN001 - ORM object
    """Reuse the webhook's embed, so both transports look identical."""
    product = notification.product
    verdict = product.quick_verdict() if product is not None else PriceVerdict.UNKNOWN
    return discord.Embed.from_dict(build_payload(notification, verdict)["embeds"][0])


def _user_for(db, discord_user_id: str):  # noqa: ANN001, ANN202 - ORM types
    from app.models import User

    return db.scalars(select(User).where(User.discord_user_id == discord_user_id)).first()


class StockWatchBot(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=INTENTS)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        await self.tree.sync()
        self.loop.create_task(self._deliver_forever())

    async def _deliver_forever(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                await self._deliver_once()
            except Exception:  # noqa: BLE001 - the loop must outlive one bad pass
                logger.exception("Delivery pass failed")
            await asyncio.sleep(settings.discord_poll_seconds)

    async def _deliver_once(self) -> None:
        # Read, send, then write: three short transactions rather than one held
        # open across network calls to Discord.
        outbound = await asyncio.to_thread(self._collect)
        if not outbound:
            return

        results: dict[int, str | None] = {}
        for notification_id, discord_user_id, embed in outbound:
            results[notification_id] = await self._send_dm(discord_user_id, embed)

        await asyncio.to_thread(self._record, results)
        sent = sum(1 for error in results.values() if error is None)
        logger.info("Delivered %d of %d alert(s)", sent, len(results))

    def _collect(self) -> list[tuple[int, int, discord.Embed]]:
        with session_scope() as db:
            return [
                (item.id, int(item.user.discord_user_id), _embed_for(item))
                for item in pending_dms(db)
            ]

    async def _send_dm(self, discord_user_id: int, embed: discord.Embed) -> str | None:
        """Send one alert. Returns None on success, or why it failed."""
        try:
            user = self.get_user(discord_user_id) or await self.fetch_user(discord_user_id)
            await user.send(embed=embed)
        except discord.Forbidden:
            # DMs closed, or we share no server with them. Not retryable.
            return "The recipient's Discord settings do not allow direct messages."
        except discord.HTTPException as exc:
            return f"Discord HTTP {exc.status}"
        except Exception as exc:  # noqa: BLE001 - never kill the loop
            return f"{type(exc).__name__}: {exc}"
        return None

    def _record(self, results: dict[int, str | None]) -> None:
        from app.models import Notification

        with session_scope() as db:
            for notification_id, error in results.items():
                notification = db.get(Notification, notification_id)
                if notification is None:
                    continue
                if error is None:
                    mark_sent(notification)
                else:
                    mark_failed(notification, error)


bot = StockWatchBot()


@bot.tree.command(name="link", description="Connect this Discord account to your StockWatch account")
@app_commands.describe(code="The code from your StockWatch dashboard")
async def link(interaction: discord.Interaction, code: str) -> None:
    # Ephemeral throughout: a link code is a credential for as long as it lives,
    # and nobody else in the channel needs to see it or the answer.
    await interaction.response.defer(ephemeral=True, thinking=True)

    def redeem() -> str:
        with session_scope() as db:
            try:
                user = discord_link.redeem_code(db, code, str(interaction.user.id))
            except discord_link.LinkError as exc:
                return str(exc)
            return f"Linked to {user.email}. Alerts will arrive here as a direct message."

    await interaction.followup.send(await asyncio.to_thread(redeem), ephemeral=True)


@bot.tree.command(name="unlink", description="Stop sending StockWatch alerts to this Discord account")
async def unlink(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)

    def detach() -> str:
        with session_scope() as db:
            user = _user_for(db, str(interaction.user.id))
            if user is None:
                return NOT_LINKED
            discord_link.unlink(db, user)
            return "Unlinked. No further alerts will be sent here."

    await interaction.followup.send(await asyncio.to_thread(detach), ephemeral=True)


@bot.tree.command(name="watching", description="What StockWatch is tracking for you")
async def watching(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)

    def summarise() -> str:
        from app.models import TrackedProduct

        with session_scope() as db:
            user = _user_for(db, str(interaction.user.id))
            if user is None:
                return NOT_LINKED

            products = list(
                db.scalars(
                    select(TrackedProduct)
                    .where(
                        TrackedProduct.user_id == user.id,
                        TrackedProduct.tracking_enabled.is_(True),
                    )
                    .order_by(TrackedProduct.created_at.desc())
                    .limit(10)
                )
            )
            if not products:
                return "Nothing tracked yet."

            lines = [
                f"- **{item.name}** — {item.watched_availability.value.replace('_', ' ')}"
                for item in products
            ]
            return "\n".join(lines)

    await interaction.followup.send(await asyncio.to_thread(summarise), ephemeral=True)


def run() -> None:
    if not settings.discord_bot_token:
        raise SystemExit("DISCORD_BOT_TOKEN is not set; the bot has nothing to connect with.")
    bot.run(settings.discord_bot_token, log_handler=None)


if __name__ == "__main__":
    run()
