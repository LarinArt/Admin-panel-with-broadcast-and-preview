from datetime import date, datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from sqlalchemy import select
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from app.bot.keyboards.inline import (
    confirm_keyboard,
    dates_keyboard,
    masters_keyboard,
    services_keyboard,
    time_slots_keyboard,
)
from app.config import get_settings
from app.database.engine import SessionLocal
from app.database.models import Appointment, AppointmentStatus, Holiday, Master, Organization, Service, Tenant, User, UserRole
from app.services.booking import calculate_available_slots
from app.bot.callbacks import AppointmentConfirm
from app.bot.i18n import get_tenant_id_by_bot_id


router = Router(name="client")
settings = get_settings()


class BookingState(StatesGroup):
    master_id = State()
    service_id = State()
    booking_date = State()

class RescheduleState(StatesGroup):
    appointment_id = State()
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


async def _get_or_create_user(
    message: Message,
    selected_lang: str | None = None,
    tenant_id: int | None = None,
) -> User:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        if user:
            # Если пользователь уже существует, но его ID есть в списке master-admin,
            # автоматически поднимаем роль до SUPER_ADMIN.
            if message.from_user.id in settings.admin_telegram_ids and user.role != UserRole.SUPER_ADMIN:
                user.role = UserRole.SUPER_ADMIN
            if selected_lang:
                user.language_code = selected_lang
            if tenant_id and user.tenant_id is None:
                user.tenant_id = tenant_id
            await session.commit()
            return user

        role = UserRole.SUPER_ADMIN if message.from_user.id in settings.admin_telegram_ids else UserRole.CLIENT
        user = User(
            telegram_id=message.from_user.id,
            full_name=message.from_user.full_name,
            role=role,
            language_code=selected_lang or "uk",
            tenant_id=tenant_id,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _try_link_deep_appointment(
    message: Message,
    user: User,
    start_arg: str | None,
    t,
    tenant_id: int | None = None,
) -> None:
    if not start_arg or not start_arg.startswith("book_"):
        return
    appointment_id_raw = start_arg.replace("book_", "", 1)
    if not appointment_id_raw.isdigit():
        await message.answer(t("start_link_not_found"))
        return

    async with SessionLocal() as session:
        stmt = select(Appointment).where(Appointment.id == int(appointment_id_raw))
        if tenant_id is not None:
            stmt = stmt.where(Appointment.tenant_id == tenant_id)
        appointment = await session.scalar(stmt)
        if not appointment:
            await message.answer(t("start_link_not_found"))
            return
        if appointment.client_id and appointment.client_id != user.id:
            await message.answer(t("start_link_already"))
            return

        appointment.client_id = user.id
        await session.commit()
    await message.answer(t("start_link_success"))


async def _require_phone_by_tg_id(tg_id: int, tenant_id: int | None = None) -> bool:
    async with SessionLocal() as session:
        stmt = select(User).where(User.telegram_id == tg_id)
        if tenant_id is not None:
            stmt = stmt.where(User.tenant_id == tenant_id)
        user = await session.scalar(stmt)
        return bool(user and user.phone_number)


async def _notify_admins_about_cancellation(bot, tenant_id: int, text: str) -> None:
    async with SessionLocal() as session:
        admins = (
            await session.scalars(
                select(User.telegram_id).where(
                    User.tenant_id == tenant_id,
                    User.role.in_([UserRole.ADMIN, UserRole.SUPER_ADMIN]),
                    User.telegram_id.is_not(None),
                    User.is_active.is_(True),
                )
            )
        ).all()
    for tg_id in admins:
        try:
            await bot.send_message(chat_id=tg_id, text=text)
        except Exception:
            continue

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
async def process_business_category(callback: CallbackQuery, state: FSMContext, tenant_id: int | None = None):
    category = callback.data.split(":")[1]
    user_data = await state.get_data()
    biz_name = user_data.get("name")

    resolved_tenant_id = tenant_id or await get_tenant_id_by_bot_id(callback.bot.id)
    
    async with SessionLocal() as session:
        # 1. Находим пользователя в БД
        user = await session.scalar(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        if not user:
            await callback.answer("Користувача не знайдено. Надішліть /start", show_alert=True)
            return

        if resolved_tenant_id is None:
            default_tenant = await session.scalar(select(Tenant).order_by(Tenant.id.asc()).limit(1))
            if default_tenant:
                resolved_tenant_id = default_tenant.id

        if resolved_tenant_id is None:
            await callback.answer("Не знайдено tenant для цього бота.", show_alert=True)
            return
        
        # 2. Создаем новую организацию
        new_org = Organization(
            name=biz_name,
            category=category,
            owner_id=user.id,
            tenant_id=resolved_tenant_id,
        )
        session.add(new_org)
        
        # 3. Присваиваем пользователю роль администратора (теперь он босс!)
        user.role = UserRole.ADMIN
        if user.tenant_id is None:
            user.tenant_id = resolved_tenant_id
        
        await session.commit()

    await state.clear()
    await callback.message.edit_text(
        f"🎉 Поздравляем! Ваш бизнес **{biz_name}** официально зарегистрирован в системе.\n"
        f"Категория: {category}\n\n"
        "Теперь в главном меню вам доступны инструменты управления (добавление услуг и просмотр записей)."
    )
    await callback.answer()

@router.message(CommandStart())
async def start(message: Message, state: FSMContext, t, tenant_id: int | None = None) -> None:
    start_arg = None
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1:
        start_arg = parts[1]

    resolved_tenant_id = tenant_id or await get_tenant_id_by_bot_id(message.bot.id)
    user = await _get_or_create_user(message, tenant_id=resolved_tenant_id)
    is_root_admin = message.from_user.id in settings.admin_telegram_ids

    # Обязательный онбординг телефона только для обычного клиента.
    if user.role == UserRole.CLIENT and not user.phone_number:
        await state.set_state(OnboardingState.waiting_contact)
        await state.update_data(start_arg=start_arg)
        await message.answer(t("onboarding_share_phone"), reply_markup=_phone_request_kb())
        return

    await _try_link_deep_appointment(message, user, start_arg, t, tenant_id=resolved_tenant_id)
    
    async with SessionLocal() as session:
        # Ищем, создана ли уже организация для этого бота
        stmt = select(Organization).limit(1)
        if resolved_tenant_id is not None:
            stmt = stmt.where(Organization.tenant_id == resolved_tenant_id)
        existing_org = await session.scalar(stmt)
    
    builder = InlineKeyboardBuilder()
    
    # 1. Если организация уже есть
    if existing_org:
        # Для master-admin из .env даем доступ в админку независимо от состояния БД.
        if is_root_admin or user.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
            welcome_text = t("start_admin_welcome", org_name=existing_org.name)
            builder.button(text="📈 Керування платформою", callback_data="admin_panel")
        else:
            welcome_text = t("start_client_welcome", org_name=existing_org.name)
            builder.button(text="📅 Записатися на послугу", callback_data="show_services_list")
            builder.button(text="🗂 Мої записи", callback_data="client_my_appointments")
    
    # 2. Если организации еще нет (самый первый запуск бота)
    else:
        welcome_text = t("start_create_business")
        builder.button(text="🏗 Створити свій бізнес", callback_data="setup_business")

    builder.adjust(1)
    await message.answer(welcome_text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "show_services_list")
@router.callback_query(F.data == "client_back_services")
async def show_services_inline(callback: CallbackQuery, state: FSMContext, tenant_id: int | None = None):
    if tenant_id is None:
        return await callback.answer("Tenant не визначено.", show_alert=True)
    async with SessionLocal() as session:
        masters = (
            await session.scalars(
                select(Master).where(Master.tenant_id == tenant_id).order_by(Master.name.asc())
            )
        ).all()
    if not masters:
        await callback.message.edit_text("Майстри ще не налаштовані.")
        await callback.answer()
        return
    await state.set_state(BookingState.master_id)
    await callback.message.edit_text("Оберіть майстра:", reply_markup=masters_keyboard(masters))
    await callback.answer()


@router.callback_query(BookingState.master_id, F.data.startswith("cl_master:"))
async def pick_master(callback: CallbackQuery, state: FSMContext, tenant_id: int | None = None):
    if tenant_id is None:
        return await callback.answer("Tenant не визначено.", show_alert=True)
    master_raw = callback.data.split(":", maxsplit=1)[1]
    await state.update_data(master_id=master_raw)
    async with SessionLocal() as session:
        services = (
            await session.scalars(
                select(Service).where(Service.tenant_id == tenant_id).order_by(Service.name.asc())
            )
        ).all()
    if not services:
        await callback.message.edit_text("Послуги ще не налаштовані.")
        await callback.answer()
        return
    await state.set_state(BookingState.service_id)
    await callback.message.edit_text("Оберіть послугу:", reply_markup=services_keyboard(services))
    await callback.answer()


@router.callback_query(F.data == "client_back_main")
async def client_back_main(callback: CallbackQuery, state: FSMContext, t, tenant_id: int | None = None):
    await state.clear()
    if tenant_id is None:
        await callback.answer("Tenant не визначено.", show_alert=True)
        return
    async with SessionLocal() as session:
        org = await session.scalar(select(Organization).where(Organization.tenant_id == tenant_id).limit(1))
    if org:
        await callback.message.edit_text(
            t("start_client_welcome", org_name=org.name),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📅 Записатися на послугу", callback_data="show_services_list")],
                    [InlineKeyboardButton(text="🗂 Мої записи", callback_data="client_my_appointments")],
                ]
            ),
        )
    else:
        await callback.message.edit_text(t("start_create_business"))
    await callback.answer()


@router.callback_query(F.data == "client_back_dates")
async def client_back_dates(callback: CallbackQuery):
    await callback.message.edit_text("Оберіть дату:", reply_markup=dates_keyboard())
    await callback.answer()


@router.callback_query(F.data == "client_back_to_services")
async def client_back_to_services(callback: CallbackQuery, state: FSMContext, tenant_id: int | None = None):
    if tenant_id is None:
        return await callback.answer("Tenant не визначено.", show_alert=True)
    data = await state.get_data()
    master_raw = str(data.get("master_id", "any"))
    if master_raw == "any":
        title = "Оберіть послугу (майстер буде призначений автоматично):"
    else:
        title = "Оберіть послугу:"
    async with SessionLocal() as session:
        services = (
            await session.scalars(
                select(Service).where(Service.tenant_id == tenant_id).order_by(Service.name.asc())
            )
        ).all()
    await callback.message.edit_text(title, reply_markup=services_keyboard(services))
    await callback.answer()


@router.callback_query(F.data == "client_back_times")
async def client_back_times(callback: CallbackQuery, state: FSMContext, tenant_id: int | None = None):
    if tenant_id is None:
        return await callback.answer("Tenant не визначено.", show_alert=True)
    data = await state.get_data()
    service_id = data.get("service_id")
    date_raw = data.get("booking_date")
    if not service_id or not date_raw:
        return await callback.answer("Сесія застаріла. Почніть знову.", show_alert=True)
    selected_date = date.fromisoformat(date_raw)
    master_raw = str(data.get("master_id", "any"))
    master_id = None if master_raw == "any" else int(master_raw)
    async with SessionLocal() as session:
        slots = await calculate_available_slots(
            session,
            int(service_id),
            selected_date,
            tenant_id=tenant_id,
            master_id=master_id,
        )
    await callback.message.edit_text("Оберіть час:", reply_markup=time_slots_keyboard(int(service_id), slots))
    await callback.answer()


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
    await _try_link_deep_appointment(message, refreshed_user, start_arg, t, tenant_id=refreshed_user.tenant_id)
    await start(message, state, t)


@router.message(OnboardingState.waiting_contact)
async def contact_required(message: Message, t):
    await message.answer(t("onboarding_phone_invalid"), reply_markup=_phone_request_kb())


@router.message(Command("services"))
async def show_services(message: Message, tenant_id: int | None = None) -> None:
    if tenant_id is None:
        await message.answer("Tenant не визначено.")
        return
    if not await _require_phone_by_tg_id(message.from_user.id, tenant_id=tenant_id):
        await message.answer("Спочатку пройдіть онбординг через /start.")
        return
    async with SessionLocal() as session:
        services = (
            await session.scalars(
                select(Service).where(Service.tenant_id == tenant_id).order_by(Service.name.asc())
            )
        ).all()
    if not services:
        await message.answer("Послуги ще не налаштовані.")
        return
    await message.answer("Оберіть послугу:", reply_markup=services_keyboard(services))


@router.callback_query(F.data == "client_my_appointments")
async def client_my_appointments(callback: CallbackQuery, tenant_id: int | None = None):
    if tenant_id is None:
        return await callback.answer("Tenant не визначено.", show_alert=True)
    async with SessionLocal() as session:
        user = await session.scalar(
            select(User).where(User.telegram_id == callback.from_user.id, User.tenant_id == tenant_id)
        )
        if not user:
            return await callback.answer("Користувача не знайдено.", show_alert=True)
        appts = (
            await session.scalars(
                select(Appointment)
                .where(
                    Appointment.tenant_id == tenant_id,
                    Appointment.client_id == user.id,
                    Appointment.status != AppointmentStatus.CANCELLED,
                )
                .order_by(Appointment.datetime.asc())
            )
        ).all()
    builder = InlineKeyboardBuilder()
    if not appts:
        builder.button(text="⬅️ Назад", callback_data="client_back_main")
        await callback.message.edit_text("У вас поки немає активних записів.", reply_markup=builder.as_markup())
        await callback.answer()
        return
    for appt in appts:
        dt_label = appt.datetime.astimezone(settings.tz).strftime("%d.%m %H:%M")
        builder.button(text=f"🗓 {dt_label}", callback_data=f"client_appt_{appt.id}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="client_back_main"))
    await callback.message.edit_text("Оберіть запис для керування:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("client_appt_"))
async def client_appointment_actions(callback: CallbackQuery, tenant_id: int | None = None):
    if tenant_id is None:
        return await callback.answer("Tenant не визначено.", show_alert=True)
    appt_id = int(callback.data.split("_")[-1])
    async with SessionLocal() as session:
        appt = await session.scalar(
            select(Appointment).where(
                Appointment.id == appt_id,
                Appointment.tenant_id == tenant_id,
                Appointment.status != AppointmentStatus.CANCELLED,
            )
        )
        if not appt:
            return await callback.answer("Запис не знайдено.", show_alert=True)
        service = await session.scalar(select(Service).where(Service.id == appt.service_id, Service.tenant_id == tenant_id))
    builder = InlineKeyboardBuilder()
    builder.button(text="🔁 Перезаписатися", callback_data=f"client_reschedule_{appt_id}")
    builder.button(text="❌ Скасувати", callback_data=f"client_cancel_{appt_id}")
    builder.button(text="⬅️ Назад", callback_data="client_my_appointments")
    builder.adjust(1)
    await callback.message.edit_text(
        f"Запис: {appt.datetime.astimezone(settings.tz):%d.%m.%Y %H:%M}\nПослуга: {service.name if service else '—'}",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("client_cancel_"))
async def client_cancel_appointment(callback: CallbackQuery):
    # 1. Сразу отвечаем на callback, чтобы кнопка перестала "мигать"
    await callback.answer()
    
    appt_id = int(callback.data.split("_")[-1])
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Так, скасувати", callback_data=f"client_cancel_confirm_{appt_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"client_appt_{appt_id}")],
        ]
    )

    # 2. Оборачиваем в try-except для защиты от двойных нажатий
    try:
        await callback.message.edit_text(
            "Ви впевнені, що хочете скасувати запис?", 
            reply_markup=kb
        )
    except TelegramBadRequest as e:
        # Если текст и кнопки те же самые, Telegram вернет ошибку "message is not modified"
        if "message is not modified" in e.message:
            pass # Просто игнорируем, сообщение уже выглядит так, как нам нужно
        else:
            raise e # Если ошибка другая (например, сообщение удалено) — пробрасываем выше

# Добавьте state=None или фильтр на любое состояние
@router.callback_query(F.data.startswith("client_cancel_confirm_"), StateFilter(None)) 
# ИЛИ просто разрешите любые состояния:
@router.callback_query(F.data.startswith("client_cancel_confirm_"))
async def client_cancel_confirm(
    callback: CallbackQuery, 
    state: FSMContext,    # Добавили FSM
    t,                    # Добавили переводчик (важно для i18n middleware)
    tenant_id: int | None = None
):
    # 1. Сразу логируем в консоль, чтобы убедиться, что вход выполнен
    print(f"!!! ХЕНДЛЕР СРАБОТАЛ для ID: {callback.data}")
    
    await callback.answer() # Убираем индикатор загрузки

    if tenant_id is None:
        tenant_id = await get_tenant_id_by_bot_id(callback.bot.id)

    appt_id = int(callback.data.split("_")[-1])

    try:
        async with SessionLocal() as session:
            # Ищем юзера
            user = await session.scalar(
                select(User).where(User.telegram_id == callback.from_user.id, User.tenant_id == tenant_id)
            )
            
            if not user:
                print("ОШИБКА: Юзер не найден в БД")
                return await callback.message.answer("Користувача не знайдено.")

            # Ищем запись
            appt = await session.scalar(
                select(Appointment).where(
                    Appointment.id == appt_id,
                    Appointment.tenant_id == tenant_id,
                    Appointment.client_id == user.id,
                    Appointment.status != AppointmentStatus.CANCELLED
                )
            )

            if not appt:
                print("ОШИБКА: Запись не найдена или уже отменена")
                return await client_my_appointments(callback, tenant_id=tenant_id)

            # Отменяем
            appt_time = appt.datetime
            master_id = appt.master_id
            appt.status = AppointmentStatus.CANCELLED
            await session.commit()
            
            master = await session.get(Master, master_id)
            master_name = master.name if master else "—"

        # Уведомление админов
        dt_str = appt_time.astimezone(settings.tz).strftime("%d.%m.%Y %H:%M")
        notify_text = f"❌ Скасовано: {callback.from_user.full_name} на {dt_str} (Майстер: {master_name})"
        await _notify_admins_about_cancellation(callback.bot, tenant_id, notify_text)

        # Очищаем состояние, если пользователь был в процессе чего-то
        await state.clear()
        
        # Обновляем сообщение
        await callback.message.edit_text("✅ Запис успішно скасовано.")
        
        # Предлагаем вернуться в меню через 1 секунду или обновляем список
        await client_my_appointments(callback, tenant_id=tenant_id)

    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: {e}")
        await callback.message.answer("Виникла помилка. Спробуйте пізніше.")


@router.callback_query(F.data.startswith("client_reschedule_"))
async def client_start_reschedule(callback: CallbackQuery, state: FSMContext, tenant_id: int | None = None):
    if tenant_id is None:
        return await callback.answer("Tenant не визначено.", show_alert=True)
    appt_id = int(callback.data.split("_")[-1])
    async with SessionLocal() as session:
        appt = await session.scalar(
            select(Appointment).where(
                Appointment.id == appt_id,
                Appointment.tenant_id == tenant_id,
                Appointment.status != AppointmentStatus.CANCELLED,
            )
        )
        if not appt:
            return await callback.answer("Запис не знайдено.", show_alert=True)
    await state.set_state(RescheduleState.booking_date)
    await state.update_data(appointment_id=appt_id, service_id=appt.service_id)
    await callback.message.edit_text("Оберіть нову дату:", reply_markup=dates_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("service:"))
async def pick_service(callback: CallbackQuery, state: FSMContext, tenant_id: int | None = None) -> None:
    if tenant_id is None:
        await callback.answer("Tenant не визначено.", show_alert=True)
        return
    if not await _require_phone_by_tg_id(callback.from_user.id, tenant_id=tenant_id):
        await callback.answer("Спочатку відправте телефон через /start", show_alert=True)
        return
    service_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        service = await session.get(Service, service_id)
        if not service or service.tenant_id != tenant_id:
            await callback.answer("Послугу не знайдено", show_alert=True)
            return
    await state.update_data(service_id=service_id)
    await state.set_state(BookingState.booking_date)
    await callback.message.edit_text("Оберіть дату:", reply_markup=dates_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("date:"))
async def pick_date(callback: CallbackQuery, state: FSMContext, tenant_id: int | None = None) -> None:
    if tenant_id is None:
        await callback.answer("Tenant не визначено.", show_alert=True)
        return
    data = await state.get_data()
    service_id = data.get("service_id")
    if not service_id:
        await callback.answer("Спочатку оберіть послугу", show_alert=True)
        return

    selected_date = date.fromisoformat(callback.data.split(":", maxsplit=1)[1])
    async with SessionLocal() as session:
        is_holiday = await session.scalar(
            select(Holiday.id).where(Holiday.tenant_id == tenant_id, Holiday.holiday_date == selected_date)
        )
        if is_holiday:
            await callback.message.edit_text("Ця дата позначена як вихідний. Оберіть іншу дату.", reply_markup=dates_keyboard())
            await callback.answer()
            return
        master_raw = str(data.get("master_id", "any"))
        master_id = None if master_raw == "any" else int(master_raw)
        slots = await calculate_available_slots(
            session,
            service_id,
            selected_date,
            tenant_id=tenant_id,
            master_id=master_id,
        )

    if not slots:
        await callback.message.edit_text("На цю дату немає вільного часу. Оберіть іншу дату.", reply_markup=dates_keyboard())
        await callback.answer()
        return

    await state.update_data(booking_date=selected_date.isoformat())
    await callback.message.edit_text(
        "Оберіть час:",
        reply_markup=time_slots_keyboard(service_id, slots),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("book:"))
async def pick_time(callback: CallbackQuery) -> None:
    _, service_id, dt_iso = callback.data.split(":", maxsplit=2)
    await callback.message.edit_text(
        f"Підтвердити запис на {datetime.fromisoformat(dt_iso).astimezone(settings.tz):%d.%m.%Y %H:%M}?",
        reply_markup=confirm_keyboard(int(service_id), dt_iso),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm:")) # Исправлено: теперь бот знает, что ловить
async def confirm_booking(callback: CallbackQuery, state: FSMContext, tenant_id: int | None = None) -> None:
    if tenant_id is None:
        await callback.answer("Tenant не визначено.", show_alert=True)
        return
    if not await _require_phone_by_tg_id(callback.from_user.id, tenant_id=tenant_id):
        await callback.answer("Спочатку відправте телефон через /start", show_alert=True)
        return
    _, service_id_raw, dt_iso = callback.data.split(":", maxsplit=2)
    service_id = int(service_id_raw)
    appointment_dt = datetime.fromisoformat(dt_iso).astimezone(settings.tz)

    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        if user is None:
            await callback.answer("Спочатку надішліть /start", show_alert=True)
            return

        service = await session.get(Service, service_id)
        if service is None or service.tenant_id != tenant_id:
            await callback.answer("Послугу не знайдено", show_alert=True)
            return

        state_data = await state.get_data()
        master_raw = str(state_data.get("master_id", "any"))
        selected_master_id = None if master_raw == "any" else int(master_raw)
        available = await calculate_available_slots(
            session,
            service.id,
            appointment_dt.date(),
            tenant_id=tenant_id,
            master_id=selected_master_id,
        )
        if appointment_dt not in available:
            await callback.message.edit_text("Обраний слот вже недоступний. Спробуйте ще раз.")
            await callback.answer()
            return

        appt_to_reschedule_id = state_data.get("appointment_id")
        master_id_to_save: int | None = selected_master_id
        if master_id_to_save is None:
            masters = (
                await session.scalars(
                    select(Master).where(Master.tenant_id == tenant_id).order_by(Master.id.asc())
                )
            ).all()
            for master in masters:
                master_slots = await calculate_available_slots(
                    session,
                    service.id,
                    appointment_dt.date(),
                    tenant_id=tenant_id,
                    master_id=master.id,
                )
                if appointment_dt in master_slots:
                    master_id_to_save = master.id
                    break
            if master_id_to_save is None:
                await callback.message.edit_text("Немає доступного майстра на цей час. Оберіть інший слот.")
                await callback.answer()
                return
        if appt_to_reschedule_id:
            appt = await session.scalar(
                select(Appointment).where(
                    Appointment.id == int(appt_to_reschedule_id),
                    Appointment.tenant_id == tenant_id,
                    Appointment.client_id == user.id,
                    Appointment.status != AppointmentStatus.CANCELLED,
                )
            )
            if not appt:
                await callback.answer("Запис для перезапису не знайдено.", show_alert=True)
                return
            appt.datetime = appointment_dt
            appt.service_id = service.id
            appt.master_id = master_id_to_save
        else:
            appointment = Appointment(
                tenant_id=tenant_id,
                client_id=user.id,
                service_id=service.id,
                master_id=master_id_to_save,
                datetime=appointment_dt,
                status=AppointmentStatus.CONFIRMED,
            )
            session.add(appointment)
        await session.commit()
        await state.clear()

    await callback.message.edit_text(
        f"Запис успішно збережено.\nПослуга: {service.name}\n"
        f"Коли: {appointment_dt:%d.%m.%Y %H:%M} ({settings.timezone})"
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