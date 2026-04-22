from datetime import date, datetime, timedelta
from decimal import Decimal

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import get_settings
from app.database.models import Service

settings = get_settings()


def services_keyboard(services: list[Service]) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=f"{service.name} ({service.duration_minutes} min, {Decimal(service.price):.2f})",
                callback_data=f"service:{service.id}",
            )
        ]
        for service in services
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def dates_keyboard(days: int = 7) -> InlineKeyboardMarkup:
    today = datetime.now(settings.tz).date()
    buttons = [
        [
            InlineKeyboardButton(
                text=(today + timedelta(days=offset)).strftime("%d.%m.%Y"),
                callback_data=f"date:{(today + timedelta(days=offset)).isoformat()}",
            )
        ]
        for offset in range(days)
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def time_slots_keyboard(service_id: int, slots: list[datetime]) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=slot.strftime("%H:%M"),
                callback_data=f"book:{service_id}:{slot.isoformat()}",
            )
        ]
        for slot in slots
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_keyboard(service_id: int, dt_iso: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Confirm booking",
                    callback_data=f"confirm:{service_id}:{dt_iso}",
                )
            ]
        ]
    )
