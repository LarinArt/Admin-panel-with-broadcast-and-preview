import logging
import calendar
import asyncio
import re



from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
from datetime import datetime, timedelta, date
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.deep_linking import create_start_link
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, func, update, and_
from sqlalchemy.orm import selectinload
from zoneinfo import ZoneInfo
from app.config import get_settings
from app.database.engine import SessionLocal
from app.database.models import Appointment, Service, User, Organization, Master, AppointmentStatus, UserRole, Holiday
from app.services.working_hours import get_working_hours, set_working_hours_for_day

# Универсальный словарь для адаптации под разные ниши
BUSINESS_THEMES = {
    "Салон краси": {
        "master": "Майстер",
        "masters_plural": "Майстри",
        "masters_genitive": "майстрів",
        "service": "Послуга",
        "services_plural": "Послуги",
        "category_icon": "💇",
        "employee_icon": "👤"
    },
    "СТО": {
        "master": "Майстер/Бокс",
        "masters_plural": "Майстри/Бокси",
        "masters_genitive": "майстрів/боксів",
        "service": "Робота",
        "services_plural": "Роботи",
        "category_icon": "🛠️",
        "employee_icon": "👨‍🔧"
    },
    "СПА": {
        "master": "Спеціаліст",
        "masters_plural": "Спеціалісти",
        "masters_genitive": "спеціалістів",
        "service": "Процедура",
        "services_plural": "Процедури",
        "category_icon": "🕯️",
        "employee_icon": "🧖"
    },
    "Інше": {
        "master": "Працівник",
        "masters_plural": "Працівники",
        "masters_genitive": "працівників",
        "service": "Послуга",
        "services_plural": "Послуги",
        "category_icon": "📋",
        "employee_icon": "🤝"
    }
}

UA_PHONE_PATTERN = re.compile(r"^\+38\(0\d{2}\)\d{3}-\d{2}-\d{2}$")

def _iter_hour_slots_for_date(target_date: date, tenant_id: int) -> list[str]:
    """Генерирует слоты с шагом 1 час на основе рабочих часов дня."""
    start_time, end_time = get_working_hours(tenant_id, target_date.weekday())
    start_dt = datetime.combine(target_date, start_time)
    end_dt = datetime.combine(target_date, end_time)

    slots: list[str] = []
    current = start_dt
    while current < end_dt:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(hours=1)
    return slots


async def get_free_slots(session, master_id: int, target_date: date, tenant_id: int) -> list[str]:
    """Возвращает свободные слоты мастера на дату (кроме отмененных записей)."""
    is_holiday = await session.scalar(
        select(Holiday.id).where(
            Holiday.tenant_id == tenant_id,
            Holiday.holiday_date == target_date,
        )
    )
    if is_holiday:
        return []

    result = await session.execute(
        select(Appointment.datetime).where(
            Appointment.tenant_id == tenant_id,
            Appointment.master_id == master_id,
            func.date(Appointment.datetime) == target_date,
            Appointment.status != AppointmentStatus.CANCELLED,
        )
    )
    booked_times = {dt_value.strftime("%H:%M") for dt_value, in result.all()}
    all_slots = _iter_hour_slots_for_date(target_date, tenant_id)
    return [slot for slot in all_slots if slot not in booked_times]


def build_admin_booking_calendar(master_id: int, service_id: int, year: int, month: int) -> InlineKeyboardMarkup:
    """Календарь-сетка для ручной записи администратора."""
    builder = InlineKeyboardBuilder()
    today = datetime.now().date()

    month_title = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                   "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"][month - 1]
    builder.row(
        InlineKeyboardButton(
            text=f"⬅️",
            callback_data=f"adm_book_nav_{master_id}_{service_id}_{year}_{month}_prev",
        ),
        InlineKeyboardButton(text=f"{month_title} {year}", callback_data="adm_book_ignore"),
        InlineKeyboardButton(
            text=f"➡️",
            callback_data=f"adm_book_nav_{master_id}_{service_id}_{year}_{month}_next",
        ),
    )

    for day_name in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]:
        builder.button(text=day_name, callback_data="adm_book_ignore")

    month_matrix = calendar.monthcalendar(year, month)
    for week in month_matrix:
        for day in week:
            if day == 0:
                builder.button(text=" ", callback_data="adm_book_ignore")
                continue

            day_date = date(year, month, day)
            if day_date < today:
                builder.button(text=f"·{day}", callback_data="adm_book_ignore")
            else:
                builder.button(
                    text=str(day),
                    callback_data=f"adm_book_day_{day_date.isoformat()}",
                )

    builder.adjust(7, *([7] * len(month_matrix)))
    builder.row(InlineKeyboardButton(text="❌ Скасувати", callback_data="admin_panel"))
    return builder.as_markup()


router = Router(name="admin")
logger = logging.getLogger(__name__)
settings = get_settings()
TZ = ZoneInfo(settings.timezone)

# --- СОСТОЯНИЯ (FSM) ---
class ServiceAddState(StatesGroup):
    service_id = State() # Добавляем это поле
    name = State()
    price = State()
    duration = State()

class MasterAddState(StatesGroup):
    name = State()
    specialty = State()
    photo = State()

class BroadcastStates(StatesGroup):
    waiting_for_message = State()
    confirm_broadcast = State()  

class AdminAppointmentState(StatesGroup):
    master_id = State()
    service_id = State()
    date = State()
    time = State()
    client_name = State()
    client_phone = State()


class AddAdminState(StatesGroup):
    telegram_id = State()
    confirm = State()

class WorkingHoursState(StatesGroup):
    day = State()
    time_range = State()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (UI) ---

def get_admin_main_kb() -> InlineKeyboardMarkup:
    """Главная клавиатура админ-панели"""
    builder = InlineKeyboardBuilder()
    
    # Добавляем новую кнопку для ручной записи клиента
    builder.button(text="📝 Записати клієнта", callback_data="admin_manual_start")
    
    builder.button(text="➕ Послугу", callback_data="add_service")
    builder.button(text="➕👤 Майстра", callback_data="add_master")
    builder.button(text="📂 Керування", callback_data="view_lists")
    builder.button(text="📅 Записи сьогодні", callback_data="view_appointments_today")
    builder.button(text="📊 Статистика", callback_data="view_stats")
    
    # Настраиваем сетку: Новая запись (1), Добавить (2), Управление (1), График/Стата (2)
    builder.adjust(1, 2, 1, 2) 
    return builder.as_markup()

async def get_user_org(session, tg_id):
    """Поиск организации по Telegram ID владельца"""
    user = await session.scalar(select(User).where(User.telegram_id == tg_id))
    if not user: return None
    return await session.scalar(
        select(Organization).where(
            Organization.owner_id == user.id,
            Organization.tenant_id == user.tenant_id,
        )
    )


async def get_user_by_tg(session, tg_id: int) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == tg_id))

# --- ГЛАВНОЕ МЕНЮ ---

@router.message(Command("admin"))
@router.message(Command("menu"))
async def open_admin_menu_from_command(message: Message, state: FSMContext):
    await show_admin_menu(message, state)

@router.callback_query(F.data == "admin_panel")
async def show_admin_menu(event: CallbackQuery | Message, state: FSMContext):
    await state.clear() 
    
    async with SessionLocal() as session:
        user_id = event.from_user.id
        db_user = await get_user_by_tg(session, user_id)
        if not db_user or db_user.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
            return await event.answer("Недостатньо прав.")
        org = await get_user_org(session, user_id)
        
        if not org:
            return await event.answer("Організацію не знайдено.")

        # Умный подбор темы по ключевым словам
        raw_cat = str(org.category) if org.category else ""
        
        if "СТО" in raw_cat or "Авто" in raw_cat:
            theme = BUSINESS_THEMES["СТО"]
        elif "Салон" in raw_cat or "Beauty" in raw_cat:
            theme = BUSINESS_THEMES["Салон краси"]
        elif "СПА" in raw_cat or "SPA" in raw_cat:
            theme = BUSINESS_THEMES["СПА"]
        else:
            theme = BUSINESS_THEMES.get("Інше")

    # Формируем текст с иконкой категории
    category_icon = theme.get('category_icon', '⚙️')
    text = (f"{category_icon} **Панель керування: {org.name}**\n\n"
            f"Сфера: {org.category}\n"
            f"Налаштуйте свій бізнес нижче.")
    
    builder = InlineKeyboardBuilder()
    # Для обычного админа оставляем только ручную запись и рассылку.
    if db_user.role == UserRole.ADMIN:
        builder.button(text="📝 Записати клієнта", callback_data="admin_manual_start")
        builder.button(text="📢 Розсилка", callback_data="admin_broadcast")
        builder.adjust(1)
    else:
        builder.button(text=f"➕ {theme['service']}", callback_data="add_service")
        builder.button(text=f"➕ {theme['master']}", callback_data="add_master")
        builder.button(text="📂 Керування", callback_data="view_lists")
        builder.button(text="📅 Записи сьогодні", callback_data="view_appointments_today")
        builder.button(text="📝 Записати клієнта", callback_data="admin_manual_start")
        builder.button(text="📢 Розсилка", callback_data="admin_broadcast")
        builder.button(text="🕒 Робочий час", callback_data="working_hours_menu")
        builder.button(text="🎉 Свята/вихідні", callback_data="holidays_menu")
        builder.button(text="📊 Статистика", callback_data="view_stats:today")
        builder.button(text="➕ Адміна", callback_data="add_admin_start")
        builder.adjust(2, 1, 2, 2, 2, 1)

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=builder.as_markup())
    else:
        await event.answer(text, reply_markup=builder.as_markup())

# --- БЛОК: КАЛЕНДАРЬ И ВЫБОР МАСТЕРА ---

@router.callback_query(F.data == "manage_masters")
async def show_masters_for_calendar(callback: CallbackQuery):
    """Список мастеров для открытия календаря"""
    async with SessionLocal() as session:
        org = await get_user_org(session, callback.from_user.id)
        if not org:
            return await callback.answer("Спочатку створіть компанію!", show_alert=True)

        result = await session.execute(select(Master).where(Master.organization_id == org.id))
        masters = result.scalars().all()

    builder = InlineKeyboardBuilder()
    if not masters:
        builder.button(text="➕ Додати майстра", callback_data="add_master")
    else:
        for m in masters:
            builder.button(text=f"👤 {m.name}", callback_data=f"master_cal_{m.id}")
    
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="view_lists"))

    await callback.message.edit_text(
        "📅 **Оберіть майстра для перегляду графіка:**", 
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("master_cal_"))
async def show_master_calendar(callback: CallbackQuery):
    """Генерация календарной сетки"""
    master_id = int(callback.data.split("_")[2])
    now = datetime.now()
    
    builder = InlineKeyboardBuilder()
    
    month_name = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", 
                  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"][now.month - 1]
    
    for d in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]:
        builder.button(text=d, callback_data="ignore")

    cal = calendar.monthcalendar(now.year, now.month)
    for week in cal:
        for day in week:
            if day == 0:
                builder.button(text=" ", callback_data="ignore")
            else:
                builder.button(text=f"{day}", callback_data=f"admin_day_{master_id}_{day}")

    builder.adjust(7)
    builder.row(InlineKeyboardButton(text="⬅️ К мастерам", callback_data="manage_masters"))
    
    await callback.message.edit_text(
        f"📅 Календар: **{month_name} {now.year}**\n\nОберіть день для керування записами:", 
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

# --- БЛОК: СТАТИСТИКА ---

def _stats_period_bounds(period: str) -> tuple[datetime, datetime, str]:
    now = datetime.now(TZ)
    if period == "week":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now, "Цей тиждень"
    if period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, now, "Цей місяць"
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, now, "Сьогодні"


@router.callback_query(F.data.startswith("view_stats"))
async def view_stats(callback: CallbackQuery):
    period = "today"
    if ":" in callback.data:
        period = callback.data.split(":")[1]

    start_dt, end_dt, title = _stats_period_bounds(period)
    async with SessionLocal() as session:
        current_user = await get_user_by_tg(session, callback.from_user.id)
        if not current_user or current_user.role != UserRole.SUPER_ADMIN:
            return await callback.answer("Статистика доступна лише SUPER_ADMIN.", show_alert=True)
        org = await get_user_org(session, callback.from_user.id)
        if not org: return await callback.answer("Організацію не знайдено")
        
        base_filters = and_(
            Service.organization_id == org.id,
            Appointment.datetime >= start_dt,
            Appointment.datetime <= end_dt,
            Appointment.status == AppointmentStatus.CONFIRMED,
        )
        total_appts = await session.scalar(
            select(func.count(Appointment.id)).join(Service).where(base_filters)
        ) or 0
        total_revenue = await session.scalar(
            select(func.sum(Service.price)).join(Appointment).where(base_filters)
        ) or 0
        
        top_query = await session.execute(
            select(Service.name, func.count(Appointment.id))
            .join(Appointment).where(base_filters)
            .group_by(Service.name).order_by(func.count(Appointment.id).desc()).limit(1)
        )
        pop = top_query.first()
        pop_name = pop[0] if pop else "Немає записів"

    stats_text = (
        f"📊 **Аналітика: {org.name} ({title})**\n━━━━━━━━━━━━━━\n"
        f"📅 Усього записів: {total_appts}\n"
        f"💰 Оборот: {total_revenue} грн\n"
        f"🏆 Топ послуг: {pop_name}"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Сьогодні", callback_data="view_stats:today")
    builder.button(text="Тиждень", callback_data="view_stats:week")
    builder.button(text="Місяць", callback_data="view_stats:month")
    builder.button(text="⬅️ Назад", callback_data="admin_panel")
    builder.adjust(3, 1)
    await callback.message.edit_text(stats_text, reply_markup=builder.as_markup())

# --- БЛОК: ДОБАВЛЕНИЕ МАСТЕРА ---

@router.callback_query(F.data == "add_master")
async def start_add_master(callback: CallbackQuery, state: FSMContext):
    await state.set_state(MasterAddState.name)
    builder = InlineKeyboardBuilder().button(text="❌ Скасувати", callback_data="admin_panel")
    await callback.message.edit_text("👤 **Крок 1:** Введіть ім'я майстра:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "add_admin_start")
async def add_admin_start(callback: CallbackQuery, state: FSMContext):
    async with SessionLocal() as session:
        current_user = await get_user_by_tg(session, callback.from_user.id)
        if not current_user or current_user.role != UserRole.SUPER_ADMIN:
            return await callback.answer("Лише SUPER_ADMIN може видавати права.", show_alert=True)
    await state.set_state(AddAdminState.telegram_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="admin_panel")
    await callback.message.edit_text(
        "Введіть Telegram ID користувача, якому потрібно видати роль ADMIN:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(AddAdminState.telegram_id, F.data == "admin_panel")
async def add_admin_back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_admin_menu(callback, state)
    await callback.answer()


@router.message(AddAdminState.telegram_id)
async def add_admin_finish(message: Message, state: FSMContext):
    tg_id_raw = (message.text or "").strip()
    if not tg_id_raw.isdigit():
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="admin_panel")
        return await message.answer("Невірний формат ID. Введіть число.", reply_markup=builder.as_markup())

    async with SessionLocal() as session:
        current_user = await get_user_by_tg(session, message.from_user.id)
        if not current_user or current_user.role != UserRole.SUPER_ADMIN:
            await state.clear()
            return await message.answer("Недостатньо прав.")

        target_user = await get_user_by_tg(session, int(tg_id_raw))
        if not target_user:
            builder = InlineKeyboardBuilder()
            builder.button(text="⬅️ Назад", callback_data="admin_panel")
            return await message.answer(
                "Користувач не знайдений у базі. Спочатку він має написати /start.",
                reply_markup=builder.as_markup(),
            )

    await state.update_data(target_tg_id=int(tg_id_raw))
    await state.set_state(AddAdminState.confirm)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Підтвердити", callback_data="add_admin_confirm_yes")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="add_admin_confirm_no")],
        ]
    )
    await message.answer(f"Підтвердити видачу ролі ADMIN користувачу {tg_id_raw}?", reply_markup=kb)


@router.callback_query(AddAdminState.confirm, F.data == "add_admin_confirm_no")
async def add_admin_confirm_no(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddAdminState.telegram_id)
    await callback.message.edit_text("Введіть Telegram ID користувача, якому потрібно видати роль ADMIN:")
    await callback.answer()


@router.callback_query(AddAdminState.confirm, F.data == "add_admin_confirm_yes")
async def add_admin_confirm_yes(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    target_tg_id = data.get("target_tg_id")
    if not target_tg_id:
        await state.clear()
        return await callback.answer("Сесія застаріла.", show_alert=True)
    async with SessionLocal() as session:
        target_user = await get_user_by_tg(session, int(target_tg_id))
        if not target_user:
            await state.clear()
            return await callback.answer("Користувача не знайдено.", show_alert=True)
        target_user.role = UserRole.ADMIN
        await session.commit()
    await state.clear()
    await callback.message.edit_text(f"Готово. Користувачу {target_tg_id} видано роль ADMIN.")
    await callback.answer()


WEEKDAY_UA = {
    0: "Понеділок",
    1: "Вівторок",
    2: "Середа",
    3: "Четвер",
    4: "П'ятниця",
    5: "Субота",
    6: "Неділя",
}

MONTHS_UA = [
    "Січень",
    "Лютий",
    "Березень",
    "Квітень",
    "Травень",
    "Червень",
    "Липень",
    "Серпень",
    "Вересень",
    "Жовтень",
    "Листопад",
    "Грудень",
]


async def _build_holidays_calendar(session, tenant_id: int, year: int, month: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    today = datetime.now(TZ).date()
    month_start = date(year, month, 1)
    holidays = (
        await session.scalars(
            select(Holiday.holiday_date).where(
                Holiday.tenant_id == tenant_id,
                Holiday.holiday_date >= month_start,
                Holiday.holiday_date <= date(year, month, calendar.monthrange(year, month)[1]),
            )
        )
    ).all()
    holiday_set = set(holidays)

    builder.row(
        InlineKeyboardButton(text="⬅️", callback_data=f"holiday_nav_{year}_{month}_prev"),
        InlineKeyboardButton(text=f"{MONTHS_UA[month-1]} {year}", callback_data="holiday_ignore"),
        InlineKeyboardButton(text="➡️", callback_data=f"holiday_nav_{year}_{month}_next"),
    )
    for d in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]:
        builder.button(text=d, callback_data="holiday_ignore")

    month_matrix = calendar.monthcalendar(year, month)
    for week in month_matrix:
        for day in week:
            if day == 0:
                builder.button(text=" ", callback_data="holiday_ignore")
                continue
            cur = date(year, month, day)
            prefix = "✅" if cur in holiday_set else ""
            if cur < today:
                builder.button(text=f"·{day}", callback_data="holiday_ignore")
            else:
                builder.button(text=f"{prefix}{day}", callback_data=f"holiday_toggle_{cur.isoformat()}_{year}_{month}")
    builder.adjust(7, *([7] * len(month_matrix)))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel"))
    return builder.as_markup()


@router.callback_query(F.data == "working_hours_menu")
async def working_hours_menu(callback: CallbackQuery, tenant_id: int | None = None):
    if tenant_id is None:
        return await callback.answer("Tenant не визначено.", show_alert=True)

    builder = InlineKeyboardBuilder()
    for day_idx, day_name in WEEKDAY_UA.items():
        start_t, end_t = get_working_hours(tenant_id, day_idx)
        builder.button(
            text=f"{day_name}: {start_t.strftime('%H:%M')}-{end_t.strftime('%H:%M')}",
            callback_data=f"wh_day_{day_idx}",
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel"))
    await callback.message.edit_text("🕒 Налаштування робочого часу:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("wh_day_"))
async def working_hours_day_select(callback: CallbackQuery, state: FSMContext):
    day_idx = int(callback.data.split("_")[-1])
    await state.set_state(WorkingHoursState.time_range)
    await state.update_data(weekday=day_idx)
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="working_hours_menu")
    await callback.message.edit_text(
        f"Вкажіть час для {WEEKDAY_UA[day_idx]} у форматі `HH:MM-HH:MM`.\n"
        f"Наприклад: `09:00-18:00`",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(WorkingHoursState.time_range)
async def working_hours_day_save(message: Message, state: FSMContext, tenant_id: int | None = None):
    if tenant_id is None:
        await state.clear()
        return await message.answer("Tenant не визначено.")

    payload = (message.text or "").strip()
    if "-" not in payload:
        return await message.answer("Невірний формат. Введіть `HH:MM-HH:MM`.")
    left, right = payload.split("-", maxsplit=1)
    try:
        start_t = datetime.strptime(left.strip(), "%H:%M").time()
        end_t = datetime.strptime(right.strip(), "%H:%M").time()
    except ValueError:
        return await message.answer("Невірний час. Формат має бути `HH:MM-HH:MM`.")

    if start_t >= end_t:
        return await message.answer("Початок має бути раніше за кінець.")

    data = await state.get_data()
    weekday = int(data["weekday"])
    set_working_hours_for_day(tenant_id, weekday, start_t, end_t)
    await state.clear()
    await message.answer(f"✅ Оновлено: {WEEKDAY_UA[weekday]} {start_t.strftime('%H:%M')}-{end_t.strftime('%H:%M')}")


@router.callback_query(F.data == "holidays_menu")
async def holidays_menu(callback: CallbackQuery, tenant_id: int | None = None):
    if tenant_id is None:
        return await callback.answer("Tenant не визначено.", show_alert=True)

    now = datetime.now(TZ)
    async with SessionLocal() as session:
        kb = await _build_holidays_calendar(session, tenant_id=tenant_id, year=now.year, month=now.month)
    await callback.message.edit_text("🎉 Оберіть дату для перемикання свят/вихідних:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "holiday_ignore")
async def holiday_ignore(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data.startswith("holiday_nav_"))
async def holiday_nav(callback: CallbackQuery, tenant_id: int | None = None):
    if tenant_id is None:
        return await callback.answer("Tenant не визначено.", show_alert=True)
    _, _, year_raw, month_raw, direction = callback.data.split("_")
    year = int(year_raw)
    month = int(month_raw)
    shift = -1 if direction == "prev" else 1
    month += shift
    if month == 0:
        month = 12
        year -= 1
    elif month == 13:
        month = 1
        year += 1
    async with SessionLocal() as session:
        kb = await _build_holidays_calendar(session, tenant_id=tenant_id, year=year, month=month)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("holiday_toggle_"))
async def holiday_toggle(callback: CallbackQuery, tenant_id: int | None = None):
    if tenant_id is None:
        return await callback.answer("Tenant не визначено.", show_alert=True)
    _, _, iso_date, year_raw, month_raw = callback.data.split("_", maxsplit=4)
    selected = date.fromisoformat(iso_date)
    year = int(year_raw)
    month = int(month_raw)
    async with SessionLocal() as session:
        existing = await session.scalar(
            select(Holiday).where(Holiday.tenant_id == tenant_id, Holiday.holiday_date == selected)
        )
        if existing:
            await session.delete(existing)
            status = "робочий день"
        else:
            session.add(Holiday(tenant_id=tenant_id, holiday_date=selected))
            status = "вихідний"
        await session.commit()
        kb = await _build_holidays_calendar(session, tenant_id=tenant_id, year=year, month=month)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer(f"{selected.strftime('%d.%m.%Y')} -> {status}")

@router.message(MasterAddState.name)
async def process_master_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(MasterAddState.specialty)
    await message.answer(f"🎓 **Крок 2:** Яка спеціалізація у **{message.text}**?")

@router.message(MasterAddState.specialty)
async def process_master_spec(message: Message, state: FSMContext):
    await state.update_data(spec=message.text)
    await state.set_state(MasterAddState.photo)
    builder = InlineKeyboardBuilder().button(text="⏭ Пропустити фото", callback_data="skip_photo")
    await message.answer("📸 **Крок 3:** Надішліть фото або пропустіть:", reply_markup=builder.as_markup())

@router.message(MasterAddState.photo, F.photo)
@router.callback_query(F.data == "skip_photo")
async def process_master_photo(event: Message | CallbackQuery, state: FSMContext, tenant_id: int | None = None):
    data = await state.get_data()
    photo_id = event.photo[-1].file_id if isinstance(event, Message) else None
    
    async with SessionLocal() as session:
        org = await get_user_org(session, event.from_user.id)
        if org and tenant_id is not None:
            new_master = Master(
                tenant_id=tenant_id,
                name=data['name'],
                specialty=data['spec'],
                photo_id=photo_id,
                organization_id=org.id,
            )
            session.add(new_master)
            await session.commit()
    
    await state.clear()
    text = f"✅ Майстра **{data['name']}** додано!"
    if isinstance(event, Message):
        await event.answer(text)
        await show_admin_menu(event, state)
    else:
        await event.message.edit_text(text)
        await show_admin_menu(event, state)

# --- БЛОК: ПРОСМОТР И УДАЛЕНИЕ ---

@router.callback_query(F.data == "view_lists")
async def view_lists_menu(callback: CallbackQuery):
    async with SessionLocal() as session:
        org = await get_user_org(session, callback.from_user.id)
        
        raw_cat = str(org.category) if org.category else ""
        if "СТО" in raw_cat or "Авто" in raw_cat:
            theme = BUSINESS_THEMES["СТО"]
        elif "Салон" in raw_cat or "Beauty" in raw_cat:
            theme = BUSINESS_THEMES["Салон краси"]
        elif "СПА" in raw_cat or "SPA" in raw_cat:
            theme = BUSINESS_THEMES["СПА"]
        else:
            theme = BUSINESS_THEMES["Інше"]

    builder = InlineKeyboardBuilder()
    
    # Берем готовые формы множественного числа
    services_text = theme['services_plural']
    masters_text = theme['masters_plural']
    srv_icon = theme['category_icon']
    emp_icon = theme['employee_icon']

    builder.button(
        text=f"{srv_icon} Наші {theme['services_plural']}", 
        callback_data="view_services"
    )
    builder.button(
        text=f"{emp_icon} {theme['masters_plural']} (Графік)", 
        callback_data="manage_masters"
    )
    # Используем родительный падеж здесь:
    builder.button(
        text=f"📝 Список {theme['masters_genitive']} (Редаг.)", 
        callback_data="view_masters"
    )
    builder.button(text="⬅️ Назад", callback_data="admin_panel")
    
    builder.adjust(1)
    await callback.message.edit_text("📂 **Керування ресурсами:**", reply_markup=builder.as_markup())

@router.callback_query(F.data == "view_masters")
async def view_masters(callback: CallbackQuery):
    async with SessionLocal() as session:
        org = await get_user_org(session, callback.from_user.id)
        masters = (await session.scalars(select(Master).where(Master.organization_id == org.id))).all()
    
    builder = InlineKeyboardBuilder()
    for m in masters:
        builder.button(text=f"👤 {m.name}", callback_data=f"info_master:{m.id}")
    builder.button(text="⬅️ Назад", callback_data="view_lists")
    builder.adjust(1)
    
    text = "👥 **Ваші майстри:**"
    kb = builder.as_markup()

    # ПРОВЕРКА: Если в сообщении есть фото или документ, edit_text не сработает
    if callback.message.photo or callback.message.document:
        await callback.message.delete() # Удаляем фото-карточку
        await callback.message.answer(text, reply_markup=kb) # Присылаем обычный список
    else:
        await callback.message.edit_text(text, reply_markup=kb)
    
    await callback.answer()

@router.callback_query(F.data.startswith("info_master:"))
async def master_info(callback: CallbackQuery):
    master_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        current_user = await get_user_by_tg(session, callback.from_user.id)
        if not current_user:
            return await callback.answer("Користувача не знайдено.", show_alert=True)
        master = await session.scalar(
            select(Master).where(Master.id == master_id, Master.tenant_id == current_user.tenant_id)
        )
    if not master: return await callback.answer("Майстра не знайдено")

    text = f"👤 **Майстер:** {master.name}\n🎓 **Профіль:** {master.specialty}"
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Видалити", callback_data=f"delete_master:{master.id}")
    builder.button(text="⬅️ К списку", callback_data="view_masters")
    builder.adjust(1)

    if master.photo_id:
        await callback.message.delete()
        await callback.message.answer_photo(master.photo_id, caption=text, reply_markup=builder.as_markup())
    else:
        await callback.message.edit_text(text, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("delete_master:"))
async def delete_master(callback: CallbackQuery):
    master_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        current_user = await get_user_by_tg(session, callback.from_user.id)
        if not current_user:
            return await callback.answer("Користувача не знайдено.", show_alert=True)
        master = await session.scalar(
            select(Master).where(Master.id == master_id, Master.tenant_id == current_user.tenant_id)
        )
        if master:
            await session.delete(master)
            await session.commit()
            await callback.answer("Майстра видалено")
    await view_masters(callback)

# --- УПРАВЛЕНИЕ УСЛУГАМИ ---

@router.callback_query(F.data == "view_services")
async def view_services(callback: CallbackQuery):
    async with SessionLocal() as session:
        org = await get_user_org(session, callback.from_user.id)
        if not org: return await callback.answer("Організацію не знайдено")

        # Логика подбора темы по ключевому слову
        raw_cat = str(org.category) if org.category else ""
        if "СТО" in raw_cat or "Авто" in raw_cat:
            theme = BUSINESS_THEMES["СТО"]
        elif "Салон" in raw_cat or "Beauty" in raw_cat:
            theme = BUSINESS_THEMES["Салон краси"]
        elif "СПА" in raw_cat or "SPA" in raw_cat:
            theme = BUSINESS_THEMES["СПА"]
        else:
            theme = BUSINESS_THEMES["Інше"]

        result = await session.execute(
            select(Service).where(Service.organization_id == org.id, Service.tenant_id == org.tenant_id)
        )
        services = result.scalars().all()
    
    builder = InlineKeyboardBuilder()
    icon = theme['category_icon']

    if services:
        for srv in services:
            builder.button(
                text=f"{icon} {srv.name} — {srv.price}грн", 
                callback_data=f"info_service:{srv.id}"
            )
    
    builder.button(text=f"➕ Додати {theme['service'].lower()}", callback_data="add_service")
    builder.button(text="⬅️ Назад", callback_data="view_lists")
    builder.adjust(1)

    await callback.message.edit_text(
        f"📋 **Список: {theme['service']}**\n\nОберіть позицію для керування:", 
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("info_service:"))
async def service_info(callback: CallbackQuery):
    # Достаем ID услуги из callback_data
    service_id = int(callback.data.split(":")[1])
    
    async with SessionLocal() as session:
        current_user = await get_user_by_tg(session, callback.from_user.id)
        if not current_user:
            return await callback.answer("Користувача не знайдено.", show_alert=True)
        service = await session.scalar(
            select(Service).where(Service.id == service_id, Service.tenant_id == current_user.tenant_id)
        )
    
    if not service:
        return await callback.answer("Послугу не знайдено", show_alert=True)

    # Формируем текст карточки услуги
    text = (
        f"🔎 **Картка послуги**\n"
        f"━━━━━━━━━━━━━━\n"
        f"📌 **Назва:** {service.name}\n"
        f"💰 **Ціна:** {service.price} грн\n"
        f"⏱ **Тривалість:** {service.duration_minutes} хв\n"
    )
    
    builder = InlineKeyboardBuilder()
    # ВОТ ЭТА КНОПКА: она должна вести на меню выбора, что именно менять
    builder.button(text="📝 Змінити дані", callback_data=f"edit_srv_menu:{service.id}")
    builder.button(text="🗑 Видалити послугу", callback_data=f"delete_service:{service.id}")
    builder.button(text="⬅️ Назад до списку", callback_data="view_services")
    
    builder.adjust(1) # Все кнопки в один столбец
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("delete_service:"))
async def delete_service(callback: CallbackQuery):
    service_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        current_user = await get_user_by_tg(session, callback.from_user.id)
        if not current_user:
            return await callback.answer("Користувача не знайдено.", show_alert=True)
        service = await session.scalar(
            select(Service).where(Service.id == service_id, Service.tenant_id == current_user.tenant_id)
        )
        if service:
            await session.delete(service)
            await session.commit()
    await view_services(callback)

# --- ДОБАВЛЕНИЕ УСЛУГИ ---

@router.callback_query(F.data == "add_service")
async def start_add_service(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ServiceAddState.name)
    await callback.message.edit_text("💅 **Назва послуги:**", reply_markup=InlineKeyboardBuilder().button(text="❌ Скасувати", callback_data="admin_panel").as_markup())

@router.message(ServiceAddState.name)
async def process_service_name(message: Message, state: FSMContext):
    data = await state.get_data()
    new_name = message.text
    
    if "service_id" in data:
        # Режим редактирования
        async with SessionLocal() as session:
            current_user = await get_user_by_tg(session, message.from_user.id)
            if not current_user:
                await state.clear()
                return await message.answer("Користувача не знайдено.")
            service = await session.scalar(
                select(Service).where(
                    Service.id == data["service_id"],
                    Service.tenant_id == current_user.tenant_id,
                )
            )
            if service:
                service.name = new_name
                await session.commit()
        await message.answer(f"✅ Назву успішно змінено на: **{new_name}**")
        await state.clear()
        await show_admin_menu(message, state)
    else:
        # Режим создания
        await state.update_data(name=new_name)
        await state.set_state(ServiceAddState.price)
        await message.answer(f"💰 Введіть ціну для «{new_name}»:")

@router.message(ServiceAddState.price)
async def process_service_price(message: Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("Введіть число!")
    
    data = await state.get_data()
    new_price = int(message.text)
    
    if "service_id" in data:
        # ЛОГИКА РЕДАКТИРОВАНИЯ
        async with SessionLocal() as session:
            current_user = await get_user_by_tg(session, message.from_user.id)
            if not current_user:
                await state.clear()
                return await message.answer("Користувача не знайдено.")
            service = await session.scalar(
                select(Service).where(
                    Service.id == data["service_id"],
                    Service.tenant_id == current_user.tenant_id,
                )
            )
            if not service:
                await state.clear()
                return await message.answer("Послугу не знайдено.")
            service.price = new_price
            await session.commit()
        await message.answer(f"✅ Ціну успішно змінено на {new_price} грн")
        await state.clear()
        # Возвращаем в меню управления
        await show_admin_menu(message, state)
    else:
        # ЛОГИКА СОЗДАНИЯ (та, что уже была)
        await state.update_data(price=new_price)
        await state.set_state(ServiceAddState.duration)
        await message.answer("⏱ Тривалість у хвилинах:")

@router.message(ServiceAddState.duration)
async def process_service_duration(message: Message, state: FSMContext, tenant_id: int | None = None):
    if not message.text.isdigit():
        return await message.answer("Введіть цифри!")
    
    data = await state.get_data()
    new_duration = int(message.text)
    
    if "service_id" in data:
        # Режим редактирования
        async with SessionLocal() as session:
            current_user = await get_user_by_tg(session, message.from_user.id)
            if not current_user:
                await state.clear()
                return await message.answer("Користувача не знайдено.")
            service = await session.scalar(
                select(Service).where(
                    Service.id == data["service_id"],
                    Service.tenant_id == current_user.tenant_id,
                )
            )
            if service:
                service.duration_minutes = new_duration
                await session.commit()
        await message.answer(f"✅ Тривалість змінено на: **{new_duration} хв**")
        await state.clear()
        await show_admin_menu(message, state)
    else:
        # Режим создания
        async with SessionLocal() as session:
            org = await get_user_org(session, message.from_user.id)
            if org and tenant_id is not None:
                new_service = Service(
                    tenant_id=tenant_id,
                    name=data['name'], 
                    price=data['price'], 
                    duration_minutes=new_duration, 
                    organization_id=org.id
                )
                session.add(new_service)
                await session.commit()
        
        await message.answer(f"✅ Послугу **{data['name']}** успішно додано!")
        await state.clear()
        await show_admin_menu(message, state)


@router.callback_query(F.data.startswith("edit_srv_menu:"))
async def edit_service_menu(callback: CallbackQuery, state: FSMContext):
    service_id = int(callback.data.split(":")[1])
    
    # Сохраняем ID услуги в состояние, чтобы бот знал, ЧТО мы редактируем
    await state.update_data(service_id=service_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Назва", callback_data="edit_srv_name")
    builder.button(text="💰 Цену", callback_data="edit_srv_price")
    builder.button(text="⏱ Время", callback_data="edit_srv_duration")
    builder.button(text="⬅️ Скасувати", callback_data=f"info_service:{service_id}")
    builder.adjust(2, 1)
    
    await callback.message.edit_text(
        "**Що саме ви хочете змінити?**", 
        reply_markup=builder.as_markup()
    )
    await callback.answer()

# Хендлеры для запуска ввода новых данных
@router.callback_query(F.data == "edit_srv_name")
async def edit_name_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ServiceAddState.name)
    await callback.message.answer("Введіть нову назву послуги:")
    await callback.answer()

@router.callback_query(F.data == "edit_srv_price")
async def edit_price_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ServiceAddState.price)
    await callback.message.answer("Введіть нову ціну (тільки число):")
    await callback.answer()

@router.callback_query(F.data == "edit_srv_duration")
async def edit_duration_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ServiceAddState.duration)
    await callback.message.answer("Введіть нову тривалість у хвилинах:")
    await callback.answer()
# --- ЗАПИСИ ---

@router.callback_query(F.data == "view_appointments_today")
@router.callback_query(F.data.startswith("view_appointments_today:"))
async def view_appointments_today(callback: CallbackQuery, tenant_id: int | None = None):
    if tenant_id is None:
        return await callback.answer("Tenant не визначено.", show_alert=True)
    page = 0
    if ":" in callback.data:
        page = max(0, int(callback.data.split(":")[1]))
    per_page = 10

    now = datetime.now(TZ)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    async with SessionLocal() as session:
        query = (
            select(Appointment)
            .join(Service)
            .join(Master, Master.id == Appointment.master_id)
            .where(
                Appointment.tenant_id == tenant_id,
                Appointment.datetime >= day_start,
                Appointment.datetime < day_end,
                Appointment.status != AppointmentStatus.CANCELLED,
            )
            .options(
                selectinload(Appointment.client), 
                selectinload(Appointment.service),
                selectinload(Appointment.master),
            )
            .order_by(Appointment.datetime.asc())
        )
        appointments = (await session.execute(query)).scalars().all()

    builder = InlineKeyboardBuilder()
    if not appointments:
        builder.button(text="⬅️ Назад", callback_data="admin_panel")
        return await callback.message.edit_text("📅 Сьогодні записів немає.", reply_markup=builder.as_markup())

    start_idx = page * per_page
    chunk = appointments[start_idx : start_idx + per_page]
    text = "📅 **Записи сьогодні:**\n\n"
    for appt in chunk:
        client_label = appt.client.full_name if appt.client else (appt.manual_client_name or appt.custom_client_data or "Клієнт")
        client_phone = appt.client.phone_number if appt.client else (appt.manual_client_phone or "—")
        text += f"Клієнт: {client_label} - {client_phone} | Час: {appt.datetime.astimezone(TZ).strftime('%H:%M')} | Послуга: {appt.service.name} | Майстер: {appt.master.name}\n"
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"view_appointments_today:{page-1}"))
    if start_idx + per_page < len(appointments):
        nav_row.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"view_appointments_today:{page+1}"))
    if nav_row:
        builder.row(*nav_row)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("admin_day_"))
async def show_day_details(callback: CallbackQuery, tenant_id: int | None = None):
    # Разбираем callback_data (формат: admin_day_masterid_day)
    parts = callback.data.split("_")
    master_id = int(parts[2])
    day = int(parts[3])
    
    now = datetime.now()
    # Создаем объект даты для поиска в базе
    selected_date = datetime(now.year, now.month, day)

    if tenant_id is None:
        return await callback.answer("Tenant не визначено.", show_alert=True)

    async with SessionLocal() as session:
        # Ищем записи именно к этому мастеру на этот день
        query = (
            select(Appointment)
            .where(
                Appointment.tenant_id == tenant_id,
                Appointment.master_id == master_id,
                func.date(Appointment.datetime) == selected_date.date()
            )
            .options(
                selectinload(Appointment.client),
                selectinload(Appointment.service)
            )
        )
        appointments = (await session.execute(query)).scalars().all()
        master = await session.scalar(
            select(Master).where(Master.id == master_id, Master.tenant_id == tenant_id)
        )

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад до календаря", callback_data=f"master_cal_{master_id}")
    builder.adjust(1)

    date_str = selected_date.strftime('%d.%m.%Y')
    
    if not appointments:
        await callback.message.edit_text(
            f"📅 **{date_str}**\n👤 Майстер: **{master.name}**\n\nЗаписів на цей день поки немає.",
            reply_markup=builder.as_markup()
        )
    else:
        text = f"📅 **Записи на {date_str}**\n👤 Майстер: **{master.name}**\n\n"
        for appt in appointments:
            time_str = appt.datetime.strftime('%H:%M')
            client_name = appt.client.full_name if appt.client else (appt.manual_client_name or appt.custom_client_data or "Клієнт")
            client_phone = appt.client.phone_number if appt.client else (appt.manual_client_phone or "—")
            text += f"⏰ {time_str} — {client_name}\n📞 {client_phone}\n🔹 {appt.service.name}\n\n"
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
    
    await callback.answer()

@router.callback_query(F.data == "admin_broadcast")
async def start_broadcast(callback: CallbackQuery, state: FSMContext):
    async with SessionLocal() as session:
        current_user = await get_user_by_tg(session, callback.from_user.id)
        if not current_user or current_user.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
            return await callback.answer("Недостатньо прав.", show_alert=True)
    await callback.message.answer("Введіть текст розсилки (можна додати фото):")
    await state.set_state(BroadcastStates.waiting_for_message)
    await callback.answer()

@router.message(BroadcastStates.waiting_for_message)
async def preview_broadcast(message: Message, state: FSMContext):
    await state.update_data(broadcast_message_id=message.message_id)
    await message.answer("🔍 **ПЕРЕГЛЯД:**")
    await message.copy_to(chat_id=message.from_user.id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚀 Запустить", callback_data="start_confirmed"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_broadcast")
        ]
    ])
    await message.answer("Почати розсилку для клієнтів вашого бізнесу?", reply_markup=kb)
    await state.set_state(BroadcastStates.confirm_broadcast)

@router.callback_query(BroadcastStates.confirm_broadcast, F.data == "start_confirmed")
async def final_send_broadcast(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    msg_id = data.get("broadcast_message_id")
    
    await callback.message.edit_text("⏳ Розсилку запущено...")

    async with SessionLocal() as session:
        current_user = await get_user_by_tg(session, callback.from_user.id)
        if not current_user:
            await state.clear()
            return await callback.answer("Користувача не знайдено.", show_alert=True)
        result = await session.execute(
            select(User.telegram_id).where(
                User.is_active == True,
                User.tenant_id == current_user.tenant_id,
                User.role == UserRole.CLIENT,
            )
        )
        users = result.scalars().all()

    sent_count = 0
    blocked_count = 0

    for user_id in users:
        try:
            await callback.bot.copy_message(
                chat_id=user_id,
                from_chat_id=callback.from_user.id,
                message_id=msg_id
            )
            sent_count += 1
            await asyncio.sleep(0.05)
        except (TelegramForbiddenError, TelegramBadRequest):
            blocked_count += 1
            async with SessionLocal() as session:
                await session.execute(
                    update(User).where(User.telegram_id == user_id).values(is_active=False)
                )
                await session.commit()
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            await callback.bot.copy_message(
                chat_id=user_id,
                from_chat_id=callback.from_user.id,
                message_id=msg_id
            )
            sent_count += 1
        except Exception as e:
            print(f"Помилка під час розсилки {user_id}: {e}")

    await callback.message.answer(
        f"✅ **Розсилку завершено!**\n\n"
        f"📈 Доставлено: {sent_count}\n"
        f"🚫 Помилок: {blocked_count}\n"
        f"👥 Всього було в базі: {len(users)}"
    )
    await state.clear()

@router.callback_query(BroadcastStates.confirm_broadcast, F.data == "cancel_broadcast")
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Розсилку скасовано.")

# --- БЛОК: РУЧНАЯ ЗАПИСЬ АДМИНОМ ---

@router.callback_query(F.data == "admin_manual_start")
async def admin_record_start(callback: CallbackQuery, state: FSMContext):
    """Крок 1: вибір майстра для ручного запису."""
    async with SessionLocal() as session:
        current_user = await get_user_by_tg(session, callback.from_user.id)
        if not current_user or current_user.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
            return await callback.answer("Недостатньо прав.", show_alert=True)
        org = await get_user_org(session, callback.from_user.id)
        if not org:
            return await callback.answer("Організацію не знайдено.", show_alert=True)

        masters = (
            await session.scalars(
                select(Master).where(Master.organization_id == org.id, Master.tenant_id == org.tenant_id)
            )
        ).all()

    if not masters:
        return await callback.answer("Спочатку додайте майстрів!", show_alert=True)

    builder = InlineKeyboardBuilder()
    for m in masters:
        builder.button(text=f"👤 {m.name}", callback_data=f"adm_book_master_{m.id}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="❌ Скасувати", callback_data="admin_panel"))

    await callback.message.edit_text("🎯 **Крок 1:** Оберіть майстра для запису:", reply_markup=builder.as_markup())
    await state.set_state(AdminAppointmentState.master_id)
    await callback.answer()

@router.callback_query(AdminAppointmentState.master_id, F.data.startswith("adm_book_master_"))
async def admin_record_service(callback: CallbackQuery, state: FSMContext):
    """Крок 2: вибір послуги."""
    master_id = int(callback.data.split("_")[-1])
    await state.update_data(master_id=master_id)

    async with SessionLocal() as session:
        org = await get_user_org(session, callback.from_user.id)
        if not org:
            return await callback.answer("Організацію не знайдено.", show_alert=True)
        services = (
            await session.scalars(
                select(Service).where(Service.organization_id == org.id, Service.tenant_id == org.tenant_id)
            )
        ).all()

    if not services:
        return await callback.answer("Спочатку додайте послуги!", show_alert=True)

    builder = InlineKeyboardBuilder()
    for s in services:
        builder.button(text=f"🔹 {s.name} ({s.price}грн)", callback_data=f"adm_book_service_{s.id}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="❌ Скасувати", callback_data="admin_panel"))

    await callback.message.edit_text("💅 **Крок 2:** Оберіть послугу:", reply_markup=builder.as_markup())
    await state.set_state(AdminAppointmentState.service_id)
    await callback.answer()

@router.callback_query(AdminAppointmentState.service_id, F.data.startswith("adm_book_service_"))
async def admin_record_calendar(callback: CallbackQuery, state: FSMContext):
    """Крок 3: вибір дати в календарі."""
    service_id = int(callback.data.split("_")[-1])
    state_data = await state.get_data()
    master_id = state_data.get("master_id")
    if not master_id:
        await state.clear()
        return await callback.answer("Сесія застаріла. Почніть знову.", show_alert=True)

    await state.update_data(service_id=service_id)
    now = datetime.now()
    calendar_kb = build_admin_booking_calendar(master_id=master_id, service_id=service_id, year=now.year, month=now.month)
    await callback.message.edit_text("📅 **Крок 3:** Оберіть дату:", reply_markup=calendar_kb)
    await state.set_state(AdminAppointmentState.date)
    await callback.answer()

@router.callback_query(AdminAppointmentState.date, F.data == "adm_book_ignore")
async def ignore_booking_calendar(callback: CallbackQuery):
    await callback.answer()

@router.callback_query(AdminAppointmentState.date, F.data.startswith("adm_book_nav_"))
async def admin_record_calendar_nav(callback: CallbackQuery, state: FSMContext):
    """Навигация по месяцам в календаре ручной записи."""
    parts = callback.data.split("_")
    if len(parts) < 8:
        return await callback.answer("Некоректні дані календаря.", show_alert=True)

    master_id = int(parts[3])
    service_id = int(parts[4])
    year = int(parts[5])
    month = int(parts[6])
    direction = parts[7]

    shift = -1 if direction == "prev" else 1
    new_month = month + shift
    new_year = year
    if new_month == 0:
        new_month = 12
        new_year -= 1
    elif new_month == 13:
        new_month = 1
        new_year += 1

    today = datetime.now().date()
    if date(new_year, new_month, 1) < date(today.year, today.month, 1):
        return await callback.answer("Не можна обрати минулий місяць.", show_alert=True)

    await state.update_data(master_id=master_id, service_id=service_id)
    calendar_kb = build_admin_booking_calendar(
        master_id=master_id,
        service_id=service_id,
        year=new_year,
        month=new_month,
    )
    await callback.message.edit_reply_markup(reply_markup=calendar_kb)
    await callback.answer()

@router.callback_query(AdminAppointmentState.date, F.data.startswith("adm_book_day_"))
async def admin_record_time(callback: CallbackQuery, state: FSMContext, tenant_id: int | None = None):
    """Крок 4: вибір вільного часу."""
    selected_date_str = callback.data.replace("adm_book_day_", "", 1)
    try:
        selected_date = datetime.strptime(selected_date_str, "%Y-%m-%d").date()
    except ValueError:
        return await callback.answer("Некоректна дата.", show_alert=True)

    fsm_data = await state.get_data()
    master_id = fsm_data.get("master_id")
    if not master_id:
        await state.clear()
        return await callback.answer("Сесія застаріла. Почніть знову.", show_alert=True)

    if tenant_id is None:
        return await callback.answer("Tenant не визначено.", show_alert=True)

    async with SessionLocal() as session:
        free_slots = await get_free_slots(
            session=session,
            master_id=int(master_id),
            target_date=selected_date,
            tenant_id=tenant_id,
        )

    await state.update_data(date=selected_date.isoformat())
    builder = InlineKeyboardBuilder()
    for slot in free_slots:
        builder.button(text=slot, callback_data=f"adm_book_time_{slot}")
    if free_slots:
        builder.adjust(4)
    builder.row(InlineKeyboardButton(text="❌ Скасувати", callback_data="admin_panel"))

    if not free_slots:
        await callback.message.edit_text(
            f"⏰ На дату **{selected_date.strftime('%d.%m.%Y')}** вільних слотів немає.\n"
            f"Оберіть іншу дату через кнопку нижче.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="↩️ До вибору дати", callback_data=f"adm_book_service_{fsm_data['service_id']}")]]
            ),
        )
        await state.set_state(AdminAppointmentState.service_id)
        await callback.answer()
        return

    await callback.message.edit_text(
        f"⏰ **Крок 4:** Дата **{selected_date.strftime('%d.%m.%Y')}**. Оберіть час:",
        reply_markup=builder.as_markup(),
    )
    await state.set_state(AdminAppointmentState.time)
    await callback.answer()

@router.callback_query(AdminAppointmentState.time, F.data.startswith("adm_book_time_"))
async def admin_record_name(callback: CallbackQuery, state: FSMContext):
    """Крок 5: введення імені клієнта."""
    time_val = callback.data.replace("adm_book_time_", "", 1)
    await state.update_data(time=time_val)

    await callback.message.edit_text("📝 **Крок 5:** Введіть ім'я клієнта:")
    await state.set_state(AdminAppointmentState.client_name)
    await callback.answer()

@router.message(AdminAppointmentState.client_name)
async def admin_record_phone(message: Message, state: FSMContext):
    client_name = (message.text or "").strip()
    if not client_name:
        return await message.answer("Ім'я клієнта не може бути порожнім.")
    await state.update_data(client_name=client_name)
    await state.set_state(AdminAppointmentState.client_phone)
    await message.answer("📞 **Крок 6:** Введіть номер телефону клієнта у форматі +38(0XX)XXX-XX-XX:")


@router.message(AdminAppointmentState.client_phone)
async def admin_record_finish(message: Message, state: FSMContext, tenant_id: int | None = None):
    """Сохранение ручной записи в БД."""
    client_phone = (message.text or "").strip()
    if not client_phone:
        return await message.answer("Введіть номер телефону клієнта.")
    if not UA_PHONE_PATTERN.fullmatch(client_phone):
        return await message.answer(
            "Невірний формат номера.\n"
            "Використайте формат: +38(0XX)XXX-XX-XX\n"
            "Після +38(0 має бути рівно 9 цифр українського номера."
        )

    data = await state.get_data()

    time_val = str(data.get("time", "")).strip()
    if ":" not in time_val:
        time_val = f"{time_val}:00"
    elif len(time_val.split(":")) == 1:
        time_val = f"{time_val}:00"

    dt_str = f"{data.get('date')} {time_val}"
    try:
        appt_datetime = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
    except ValueError:
        await message.answer("❌ Помилка у форматі дати або часу. Спробуйте почати знову.")
        await state.clear()
        return

    if tenant_id is None:
        await state.clear()
        return await message.answer("Tenant не визначено.")

    async with SessionLocal() as session:
        org = await get_user_org(session, message.from_user.id)
        if not org:
            await message.answer("❌ Помилка: організацію не знайдено.")
            await state.clear()
            return

        free_slots = await get_free_slots(
            session=session,
            master_id=int(data["master_id"]),
            target_date=appt_datetime.date(),
            tenant_id=tenant_id,
        )
        if appt_datetime.strftime("%H:%M") not in free_slots:
            await message.answer("❌ Цей слот уже зайнятий. Почніть запис заново та оберіть інший час.")
            await state.clear()
            return

        new_appt = Appointment(
            tenant_id=tenant_id,
            client_id=None,
            manual_client_name=data.get("client_name"),
            manual_client_phone=client_phone,
            custom_client_data=f"{data.get('client_name', '')} | {client_phone}",
            master_id=int(data["master_id"]),
            service_id=int(data["service_id"]),
            organization_id=org.id,
            datetime=appt_datetime.replace(tzinfo=TZ),
            status=AppointmentStatus.CONFIRMED,
        )
        session.add(new_appt)
        await session.commit()
        await session.refresh(new_appt)

    deep_link = await create_start_link(message.bot, payload=f"book_{new_appt.id}", encode=False)

    await message.answer(
        f"✅ **Запис успішно створено!**\n\n"
        f"👤 **Клієнт:** {data.get('client_name')}\n"
        f"📞 **Телефон:** {client_phone}\n"
        f"📅 **Дата й час:** {appt_datetime.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"🔗 **Посилання для прив'язки Telegram:**\n{deep_link}"
    )
    await state.clear()
    await show_admin_menu(message, state)