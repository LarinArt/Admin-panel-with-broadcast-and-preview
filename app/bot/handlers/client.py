from datetime import date, datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.inline import (
    confirm_keyboard,
    dates_keyboard,
    services_keyboard,
    time_slots_keyboard,
)
from app.config import get_settings
from app.database.engine import SessionLocal
from app.database.models import Appointment, AppointmentStatus, Service, User, UserRole, Organization
from app.services.booking import calculate_available_slots

router = Router(name="client")
settings = get_settings()


class BookingState(StatesGroup):
    service_id = State()
    booking_date = State()

class BusinessSetupState(StatesGroup):
    name = State()         # Ожидаем название компании
    category = State()     # Ожидаем выбор категории


async def _get_or_create_user(message: Message) -> User:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        if user:
            return user

        role = UserRole.ADMIN if message.from_user.id in settings.admin_telegram_ids else UserRole.CLIENT
        user = User(
            telegram_id=message.from_user.id,
            full_name=message.from_user.full_name,
            role=role,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

# 1. Начало регистрации — спрашиваем название
@router.callback_query(F.data == "setup_business")
async def start_business_setup(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BusinessSetupState.name)
    await callback.message.answer("🚀 Отлично! Как будет называться ваша компания?")
    await callback.answer()

# 2. Получаем название — спрашиваем категорию
@router.message(BusinessSetupState.name)
async def process_business_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    
    # Создаем клавиатуру выбора категорий
    builder = InlineKeyboardBuilder()
    categories = ["Салон красоты 💅", "СТО / Автосервис 🚗", "Массаж / СПА 🧘"]
    
    for cat in categories:
        builder.button(text=cat, callback_data=f"biz_cat:{cat}")
    builder.adjust(2)
    
    await state.set_state(BusinessSetupState.category)
    await message.answer(
        f"Принято: **{message.text}**!\nТеперь выберите сферу деятельности:",
        reply_markup=builder.as_markup()
    )

# 3. Финал регистрации
@router.callback_query(F.data.startswith("biz_cat:"))
async def process_business_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split(":")[1]
    user_data = await state.get_data()
    biz_name = user_data.get("name")
    
    async with SessionLocal() as session:
        # 1. Находим пользователя в БД
        user = await session.scalar(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        
        # 2. Создаем новую организацию
        new_org = Organization(
            name=biz_name,
            category=category,
            owner_id=user.id
        )
        session.add(new_org)
        
        # 3. Присваиваем пользователю роль администратора (теперь он босс!)
        user.role = UserRole.ADMIN
        
        await session.commit()

    await state.clear()
    await callback.message.edit_text(
        f"🎉 Поздравляем! Ваш бизнес **{biz_name}** официально зарегистрирован в системе.\n"
        f"Категория: {category}\n\n"
        "Теперь в главном меню вам доступны инструменты управления (добавление услуг и просмотр записей)."
    )
    await callback.answer()

@router.message(Command("start"))
async def start(message: Message) -> None:
    user = await _get_or_create_user(message)
    
    async with SessionLocal() as session:
        # Ищем, создана ли уже организация для этого бота
        existing_org = await session.scalar(select(Organization).limit(1))
    
    builder = InlineKeyboardBuilder()
    
    # 1. Если организация уже есть
    if existing_org:
        if user.role == UserRole.ADMIN:
            welcome_text = (
                f"👋 Привет, {user.full_name}!\n\n"
                f"Вы являетесь администратором **{existing_org.name}**.\n"
                "Используйте панель управления для настройки услуг."
            )
            builder.button(text="📈 Управление платформой", callback_data="admin_panel")
        else:
            welcome_text = (
                f"👋 Добро пожаловать в **{existing_org.name}**!\n"
                f"Сфера: {existing_org.category}\n\n"
                "Выберите услугу для записи:"
            )
            builder.button(text="📅 Записаться на услугу", callback_data="show_services_list")
    
    # 2. Если организации еще нет (самый первый запуск бота)
    else:
        welcome_text = (
            "🚀 Система готова к работе!\n\n"
            "Похоже, вы первый пользователь. Создайте свой бизнес, чтобы клиенты могли начать запись."
        )
        builder.button(text="🏗 Создать свой бизнес", callback_data="setup_business")

    builder.adjust(1)
    await message.answer(welcome_text, reply_markup=builder.as_markup())


@router.message(Command("services"))
async def show_services(message: Message) -> None:
    async with SessionLocal() as session:
        services = (await session.scalars(select(Service).order_by(Service.name.asc()))).all()
    if not services:
        await message.answer("No services configured yet.")
        return
    await message.answer("Select a service:", reply_markup=services_keyboard(services))


@router.callback_query(F.data.startswith("service:"))
async def pick_service(callback: CallbackQuery, state: FSMContext) -> None:
    service_id = int(callback.data.split(":")[1])
    await state.update_data(service_id=service_id)
    await callback.message.edit_text("Select a date:", reply_markup=dates_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("date:"))
async def pick_date(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    service_id = data.get("service_id")
    if not service_id:
        await callback.answer("Please select service first", show_alert=True)
        return

    selected_date = date.fromisoformat(callback.data.split(":", maxsplit=1)[1])
    async with SessionLocal() as session:
        slots = await calculate_available_slots(session, service_id, selected_date)

    if not slots:
        await callback.message.edit_text("No available slots on this date. Pick another date.")
        await callback.answer()
        return

    await state.update_data(booking_date=selected_date.isoformat())
    await callback.message.edit_text(
        "Select time:",
        reply_markup=time_slots_keyboard(service_id, slots),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("book:"))
async def pick_time(callback: CallbackQuery) -> None:
    _, service_id, dt_iso = callback.data.split(":", maxsplit=2)
    await callback.message.edit_text(
        f"Confirm booking at {datetime.fromisoformat(dt_iso).astimezone(settings.tz):%Y-%m-%d %H:%M}?",
        reply_markup=confirm_keyboard(int(service_id), dt_iso),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm:"))
async def confirm_booking(callback: CallbackQuery) -> None:
    _, service_id_raw, dt_iso = callback.data.split(":", maxsplit=2)
    service_id = int(service_id_raw)
    appointment_dt = datetime.fromisoformat(dt_iso).astimezone(settings.tz)

    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        if user is None:
            await callback.answer("Please send /start first", show_alert=True)
            return

        service = await session.get(Service, service_id)
        if service is None:
            await callback.answer("Service not found", show_alert=True)
            return

        available = await calculate_available_slots(session, service.id, appointment_dt.date())
        if appointment_dt not in available:
            await callback.message.edit_text("Selected slot is no longer available. Please try again.")
            await callback.answer()
            return

        appointment = Appointment(
            client_id=user.id,
            service_id=service.id,
            datetime=appointment_dt,
            status=AppointmentStatus.CONFIRMED,
        )
        session.add(appointment)
        await session.commit()

    await callback.message.edit_text(
        f"Booked successfully.\nService: {service.name}\n"
        f"When: {appointment_dt:%Y-%m-%d %H:%M} ({settings.timezone})"
    )
    await callback.answer()

