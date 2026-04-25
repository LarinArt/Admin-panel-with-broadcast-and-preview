from datetime import date, datetime, timedelta
from decimal import Decimal

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import get_settings
from app.database.models import Master, Service

settings = get_settings()


def masters_keyboard(masters: list[Master]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=f"👤 {master.name}", callback_data=f"cl_master:{master.id}")]
        for master in masters
    ]
    buttons.insert(0, [InlineKeyboardButton(text="✨ Будь-який майстер", callback_data="cl_master:any")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="client_back_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def services_keyboard(services: list[Service]) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=f"{service.name} ({service.duration_minutes} хв, {Decimal(service.price):.2f})",
                callback_data=f"service:{service.id}",
            )
        ]
        for service in services
    ]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="show_services_list")])
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
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="client_back_to_services")])
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
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="client_back_dates")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_keyboard(service_id: int, dt_iso: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Підтвердити запис",
                    callback_data=f"confirm:{service_id}:{dt_iso}",
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="client_back_times")],
        ]
    )
