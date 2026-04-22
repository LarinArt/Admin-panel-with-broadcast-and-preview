import logging
from datetime import datetime, timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database.engine import SessionLocal
from app.database.models import Appointment, AppointmentStatus

logger = logging.getLogger(__name__)
settings = get_settings()


async def _send_due_reminders(bot: Bot) -> None:
    now = datetime.now(settings.tz)
    window_end = now + timedelta(minutes=20)

    async with SessionLocal() as session:
        stmt = (
            select(Appointment)
            .options(selectinload(Appointment.client))
            .where(
                and_(
                    Appointment.status == AppointmentStatus.CONFIRMED,
                    Appointment.datetime > now,
                    Appointment.datetime <= now + timedelta(days=1, hours=1),
                )
            )
            .order_by(Appointment.datetime.asc())
        )
        appointments = (await session.scalars(stmt)).all()

        for appointment in appointments:
            delta = appointment.datetime - now
            hours_to_appointment = delta.total_seconds() / 3600

            should_send_24h = (
                not appointment.reminder_24h_sent and 23.8 <= hours_to_appointment <= 24.2
            )
            should_send_2h = (
                not appointment.reminder_2h_sent and 1.8 <= hours_to_appointment <= 2.2
            )

            if appointment.datetime > window_end and not (should_send_24h or should_send_2h):
                continue

            if should_send_24h:
                await bot.send_message(
                    chat_id=appointment.client.telegram_id,
                    text=(
                        "Reminder: your appointment is in 24 hours.\n"
                        f"Date and time: {appointment.datetime.astimezone(settings.tz):%Y-%m-%d %H:%M}"
                    ),
                )
                appointment.reminder_24h_sent = True
                logger.info("24h reminder sent for appointment %s", appointment.id)

            if should_send_2h:
                await bot.send_message(
                    chat_id=appointment.client.telegram_id,
                    text=(
                        "Reminder: your appointment is in 2 hours.\n"
                        f"Date and time: {appointment.datetime.astimezone(settings.tz):%Y-%m-%d %H:%M}"
                    ),
                )
                appointment.reminder_2h_sent = True
                logger.info("2h reminder sent for appointment %s", appointment.id)

        await session.commit()


def build_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(
        _send_due_reminders,
        trigger="interval",
        seconds=settings.scheduler_poll_seconds,
        args=[bot],
        max_instances=1,
        coalesce=True,
    )
    return scheduler
