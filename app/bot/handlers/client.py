from datetime import date, datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
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
from app.bot.callbacks import AppointmentConfirm


router = Router(name="client")
settings = get_settings()


class BookingState(StatesGroup):
    service_id = State()
    booking_date = State()


class BusinessSetupState(StatesGroup):
    name = State()         # Ожидаем название компании
    category = State()     # Ожидаем выбор категории


class OnboardingState(StatesGroup):
    waiting_contact = State()


def _phone_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться контактом", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def _get_or_create_user(message: Message, selected_lang: str | None = None) -> User:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        if user:
            # Если пользователь уже существует, но его ID есть в списке master-admin,
            # автоматически поднимаем роль до SUPER_ADMIN.
            if message.from_user.id in settings.admin_telegram_ids and user.role != UserRole.SUPER_ADMIN:
                user.role = UserRole.SUPER_ADMIN
            if selected_lang:
                user.language_code = selected_lang
            await session.commit()
            return user

        role = UserRole.SUPER_ADMIN if message.from_user.id in settings.admin_telegram_ids else UserRole.CLIENT
        user = User(
            telegram_id=message.from_user.id,
            full_name=message.from_user.full_name,
            role=role,
            language_code=selected_lang or (message.from_user.language_code or "ru")[:2],
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _try_link_deep_appointment(message: Message, user: User, start_arg: str | None, t) -> None:
    if not start_arg or not start_arg.startswith("book_"):
        return
    appointment_id_raw = start_arg.replace("book_", "", 1)
    if not appointment_id_raw.isdigit():
        await message.answer(t("start_link_not_found"))
        return

    async with SessionLocal() as session:
        appointment = await session.get(Appointment, int(appointment_id_raw))
        if not appointment:
            await message.answer(t("start_link_not_found"))
            return
        if appointment.client_id and appointment.client_id != user.id:
            await message.answer(t("start_link_already"))
            return

        appointment.client_id = user.id
        await session.commit()
    await message.answer(t("start_link_success"))


async def _require_phone_by_tg_id(tg_id: int) -> bool:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == tg_id))
        return bool(user and user.phone_number)

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

@router.message(Command("lang"))
async def choose_lang(message: Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="Українська", callback_data="lang:uk")
    builder.button(text="Русский", callback_data="lang:ru")
    builder.button(text="English", callback_data="lang:en")
    builder.adjust(1)
    await message.answer("Выберите язык / Оберіть мову / Choose language", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("lang:"))
async def save_lang(callback: CallbackQuery):
    lang = callback.data.split(":")[1]
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        if user:
            user.language_code = lang
            await session.commit()
    await callback.answer("Сохранено")
    await callback.message.answer("Язык сохранен.")


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, t) -> None:
    start_arg = None
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1:
        start_arg = parts[1]

    user = await _get_or_create_user(message)
    is_root_admin = message.from_user.id in settings.admin_telegram_ids

    # Обязательный онбординг телефона только для обычного клиента.
    if user.role == UserRole.CLIENT and not user.phone_number:
        await state.set_state(OnboardingState.waiting_contact)
        await state.update_data(start_arg=start_arg)
        await message.answer(t("onboarding_share_phone"), reply_markup=_phone_request_kb())
        return

    await _try_link_deep_appointment(message, user, start_arg, t)
    
    async with SessionLocal() as session:
        # Ищем, создана ли уже организация для этого бота
        existing_org = await session.scalar(select(Organization).limit(1))
    
    builder = InlineKeyboardBuilder()
    
    # 1. Если организация уже есть
    if existing_org:
        # Для master-admin из .env даем доступ в админку независимо от состояния БД.
        if is_root_admin or user.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
            welcome_text = t("start_admin_welcome", org_name=existing_org.name)
            builder.button(text="📈 Управление платформой", callback_data="admin_panel")
        else:
            welcome_text = t("start_client_welcome", org_name=existing_org.name)
            builder.button(text="📅 Записаться на услугу", callback_data="show_services_list")
    
    # 2. Если организации еще нет (самый первый запуск бота)
    else:
        welcome_text = t("start_create_business")
        builder.button(text="🏗 Создать свой бизнес", callback_data="setup_business")

    builder.adjust(1)
    await message.answer(welcome_text, reply_markup=builder.as_markup())


@router.message(OnboardingState.waiting_contact, F.contact)
async def save_phone_onboarding(message: Message, state: FSMContext, t):
    if not message.contact or message.contact.user_id != message.from_user.id:
        await message.answer(t("onboarding_phone_invalid"))
        return

    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        if user:
            user.phone_number = message.contact.phone_number
            await session.commit()

    data = await state.get_data()
    start_arg = data.get("start_arg")
    await state.clear()
    await message.answer(t("onboarding_phone_saved"), reply_markup=ReplyKeyboardRemove())

    refreshed_user = await _get_or_create_user(message)
    await _try_link_deep_appointment(message, refreshed_user, start_arg, t)
    await start(message, state, t)


@router.message(OnboardingState.waiting_contact)
async def contact_required(message: Message, t):
    await message.answer(t("onboarding_phone_invalid"), reply_markup=_phone_request_kb())


@router.message(Command("services"))
async def show_services(message: Message) -> None:
    if not await _require_phone_by_tg_id(message.from_user.id):
        await message.answer("Сначала пройдите онбординг через /start.")
        return
    async with SessionLocal() as session:
        services = (await session.scalars(select(Service).order_by(Service.name.asc()))).all()
    if not services:
        await message.answer("No services configured yet.")
        return
    await message.answer("Select a service:", reply_markup=services_keyboard(services))


@router.callback_query(F.data.startswith("service:"))
async def pick_service(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_phone_by_tg_id(callback.from_user.id):
        await callback.answer("Сначала отправьте телефон через /start", show_alert=True)
        return
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


@router.callback_query(F.data.startswith("confirm:")) # Исправлено: теперь бот знает, что ловить
async def confirm_booking(callback: CallbackQuery) -> None:
    if not await _require_phone_by_tg_id(callback.from_user.id):
        await callback.answer("Сначала отправьте телефон через /start", show_alert=True)
        return
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

@router.callback_query(AppointmentConfirm.filter())
async def confirm_appointment_handler(callback: CallbackQuery, callback_data: AppointmentConfirm):
    """
    Обработчик нажатия на кнопку '✅ Я буду' из автоматического напоминания
    """
    async with SessionLocal() as session:
        # 1. Ищем запись в базе по ID
        appointment = await session.get(Appointment, callback_data.appointment_id)
        
        if not appointment:
            await callback.answer("Запись не найдена", show_alert=True)
            return

        # 2. Если запись уже подтверждена, просто уведомляем
        if appointment.status == AppointmentStatus.CONFIRMED:
             # Здесь можно добавить проверку на новый статус, если ты его ввел
             # Например: if appointment.status == AppointmentStatus.CONFIRMED_BY_CLIENT:
             await callback.answer("Визит уже был подтвержден ранее!")
             await callback.message.edit_reply_markup(reply_markup=None)
             return

        # 3. Обновляем статус
        appointment.status = AppointmentStatus.CONFIRMED
        await session.commit()

    # 4. Визуальный отклик для пользователя
    # Убираем кнопку и добавляем текст к существующему сообщению
    try:
        await callback.message.edit_text(
            text=callback.message.text + "\n\n✅ <b>Вы подтвердили свой визит. Ждем вас!</b>",
            parse_mode="HTML",
            reply_markup=None # Убираем кнопку, чтобы нельзя было нажать дважды
        )
    except Exception:
        # На случай, если сообщение нельзя отредактировать
        await callback.message.answer("✅ Визит успешно подтвержден! Ждем вас.")

    await callback.answer("Визит подтвержден!")