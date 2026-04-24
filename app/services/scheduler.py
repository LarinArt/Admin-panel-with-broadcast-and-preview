import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from app.bot.callbacks import AppointmentConfirm
from app.config import get_settings
from app.database.engine import SessionLocal
from app.database.models import Appointment, AppointmentStatus

logger = logging.getLogger(__name__)
settings = get_settings()

async def _send_due_reminders(bot: Bot) -> None:
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz)
    
    async with SessionLocal() as session:
        # 1. Загружаем записи с подгрузкой связанных данных (клиент, услуга, мастер)
        stmt = (
            select(Appointment)
            .options(
                selectinload(Appointment.client),
                selectinload(Appointment.service),
                selectinload(Appointment.master)
            )
            .where(
                and_(
                    Appointment.status == AppointmentStatus.CONFIRMED,
                    Appointment.datetime > now,
                    Appointment.datetime <= now + timedelta(hours=25),
                )
            )
        )
        appointments = (await session.scalars(stmt)).all()

        for appointment in appointments:
            delta = appointment.datetime.replace(tzinfo=None) - datetime.now().replace(tzinfo=None)
            hours_to_appt = delta.total_seconds() / 3600

            # Определяем, какое именно напоминание нужно отправить
            send_24h = not appointment.reminder_24h_sent and 23.5 <= hours_to_appt <= 24.5
            send_2h = not appointment.reminder_2h_sent and 1.5 <= hours_to_appt <= 2.5

            if not (send_24h or send_2h):
                continue

            try:
                # Формируем время именно в твоем часовом поясе
                display_time = appointment.datetime.astimezone(tz).strftime('%d.%m в %H:%M')
                
                text = (
                    f"🌸 <b>Напоминание о визите</b>\n\n"
                    f"Ждем вас: <code>{display_time}</code>\n"
                    f"Услуга: <b>{appointment.service.name}</b>\n"
                    f"Мастер: <b>{appointment.master.name}</b>\n\n"
                    f"📍 Пожалуйста, если ваши планы изменились, предупредите нас заранее."
                )

                # --- ДОБАВЛЕННЫЙ БЛОК С КНОПКОЙ ---
                builder = InlineKeyboardBuilder()
                builder.button(
                    text="✅ Я буду", 
                    callback_data=AppointmentConfirm(appointment_id=appointment.id)
                )
                # ----------------------------------

                await bot.send_message(
                    chat_id=appointment.client.telegram_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=builder.as_markup() # Привязываем кнопку
                )
                
                # Обновляем флаги, чтобы не отправлять повторно
                if send_24h:
                    appointment.reminder_24h_sent = True
                else:
                    appointment.reminder_2h_sent = True
                
                logger.info(f"Sent reminder with button to {appointment.client.telegram_id}")

            except Exception as e:
                logger.error(f"Error sending msg to client {appointment.client_id}: {e}")

        # Сохраняем изменения флагов (sent = True) в базе данных
        await session.commit()

def build_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Сборка и настройка планировщика"""
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