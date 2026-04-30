import logging
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TgUser, Message, CallbackQuery
from sqlalchemy import select

from app.database.engine import SessionLocal
from app.database.models import Tenant, User
from app.bot.i18n import i18n

logger = logging.getLogger(__name__)

# Grace period in days after subscription ends
GRACE_PERIOD_DAYS = 3


async def get_tenant_and_user_data(
    data: Dict[str, Any],
) -> tuple[Tenant | None, User | None, str]:
    """Extract tenant and user from middleware data."""
    bot = data.get("bot")
    tenant_id: int | None = data.get("tenant_id")
    lang: str = data.get("lang", "uk")

    # If we don't have tenant_id from i18n middleware, try to get it from bot
    if tenant_id is None and bot:
        async with SessionLocal() as session:
            tenant = await session.scalar(
                select(Tenant).where(
                    Tenant.bot_token.like(f"{bot.id}:%"), Tenant.is_active.is_(True)
                )
            )
            if tenant:
                tenant_id = tenant.id

    # Get user from DB
    db_user: User | None = None
    from_user: TgUser | None = data.get("event_from_user")
    if from_user and tenant_id is not None:
        async with SessionLocal() as session:
            db_user = await session.scalar(
                select(User).where(
                    User.telegram_id == from_user.id, User.tenant_id == tenant_id
                )
            )
            # Update language if needed
            if db_user and db_user.language_code:
                lang = i18n.normalize_lang(db_user.language_code)

    # Get tenant object
    tenant: Tenant | None = None
    if tenant_id is not None:
        async with SessionLocal() as session:
            tenant = await session.scalar(select(Tenant).where(Tenant.id == tenant_id))

    return tenant, db_user, lang


def get_chat_id(event: TelegramObject) -> int | None:
    """Extract chat ID from various event types."""
    if isinstance(event, Message):
        return event.chat.id
    elif isinstance(event, CallbackQuery):
        return event.message.chat.id if event.message else None
    return None


async def send_subscription_expired_message(
    event: TelegramObject,
    user_role: str,
    tenant: Tenant,
    lang: str,
    i18n: object,
) -> None:
    """Send role-specific message when subscription is expired."""
    bot = event.bot if hasattr(event, 'bot') else None
    if not bot:
        # Try to get bot from event data (for middleware)
        bot = getattr(event, 'bot', None)
        if not bot and hasattr(event, '__dict__'):
            bot = event.__dict__.get('bot')
    if not bot:
        logger.error("Could not get bot instance to send subscription expired message")
        return

    chat_id = get_chat_id(event)
    if not chat_id:
        logger.error("Could not get chat ID to send subscription expired message")
        return

    # Get localized messages
    if user_role == "super_admin":
        message_text = i18n.t(
            "subscription.expired.master_admin",
            lang=lang,
            tenant_name=tenant.name,
        )
    elif user_role in ("admin", "master"):
        message_text = i18n.t(
            "subscription.expired.admin_master",
            lang=lang,
            tenant_name=tenant.name,
        )
    else:  # client and other roles
        message_text = i18n.t(
            "subscription.expired.client",
            lang=lang,
            tenant_name=tenant.name,
        )

    try:
        await bot.send_message(chat_id=chat_id, text=message_text)
    except Exception as e:
        logger.error(f"Failed to send subscription expired message to chat {chat_id}: {e}")


class SubscriptionMiddleware(BaseMiddleware):
    """
    Middleware to check tenant subscription status and block access if expired.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Skip subscription check for certain updates if needed (e.g., start commands)
        # For now, we check on every update

        tenant, db_user, lang = await get_tenant_and_user_data(data)

        # If no tenant or user, let the handler deal with it (e.g., /start)
        if tenant is None or db_user is None:
            return await handler(event, data)

        # Check subscription status
        if tenant.subscription_ends_at is None:
            # If no subscription end date, treat as active (could be trial or free plan)
            is_expired = False
            grace_period_end = None
            in_grace_period = False
        else:
            now = datetime.now(tenant.subscription_ends_at.tzinfo
                               if tenant.subscription_ends_at.tzinfo
                               else None)
            is_expired = tenant.subscription_ends_at and now > tenant.subscription_ends_at
            grace_period_end = (
                tenant.subscription_ends_at + timedelta(days=GRACE_PERIOD_DAYS)
                if tenant.subscription_ends_at
                else None
            )
            in_grace_period = (
                grace_period_end and now <= grace_period_end and is_expired
            )

        # Store subscription info in data for handlers to use
        data["tenant"] = tenant
        data["subscription_expired"] = is_expired
        data["in_grace_period"] = in_grace_period
        data["lang"] = lang

        # If subscription is active or in grace period, proceed
        if tenant.is_active and (not is_expired or in_grace_period):
            return await handler(event, data)

        # Subscription expired and not in grace period - block access
        logger.warning(
            f"Subscription expired for tenant {tenant.id}. Blocking access for user {db_user.id} (role: {db_user.role})"
        )

        # Send appropriate message based on role
        try:
            await send_subscription_expired_message(
                event=event,
                user_role=db_user.role.value if hasattr(db_user.role, 'value') else str(db_user.role),
                tenant=tenant,
                lang=lang,
                i18n=i18n,
            )
        except Exception as e:
            logger.error(f"Failed to send subscription expired message: {e}")

        # Do not proceed to the handler
        return None


def setup_subscription_middleware(dp):
    """Setup subscription middleware on the dispatcher."""
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())