import logging
import calendar
import asyncio



from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
from datetime import datetime
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, func, update
from sqlalchemy.orm import selectinload
from app.database.engine import SessionLocal
from app.database.models import Appointment, Service, User, Organization, Master

# Универсальный словарь для адаптации под разные ниши
BUSINESS_THEMES = {
    "Салон красоты": {
        "master": "Мастер",
        "masters_plural": "Мастера",
        "masters_genitive": "мастеров",
        "service": "Услуга",
        "services_plural": "Услуги",
        "category_icon": "💇",
        "employee_icon": "👤"
    },
    "СТО": {
        "master": "Мастер/Бокс",
        "masters_plural": "Мастера/Боксы",
        "masters_genitive": "мастеров/боксов",
        "service": "Работа",
        "services_plural": "Работы",
        "category_icon": "🛠️",
        "employee_icon": "👨‍🔧"
    },
    "СПА": {
        "master": "Специалист",
        "masters_plural": "Специалисты",
        "masters_genitive": "специалистов",
        "service": "Процедура",
        "services_plural": "Процедуры",
        "category_icon": "🕯️",
        "employee_icon": "🧖"
    },
    "Другое": {
        "master": "Сотрудник",
        "masters_plural": "Сотрудники",
        "masters_genitive": "сотрудников",
        "service": "Услуга",
        "services_plural": "Услуги",
        "category_icon": "📋",
        "employee_icon": "🤝"
    }
}

router = Router(name="admin")
logger = logging.getLogger(__name__)

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


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (UI) ---

def get_admin_main_kb() -> InlineKeyboardMarkup:
    """Главная клавиатура админ-панели"""
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Услугу", callback_data="add_service")
    builder.button(text="➕👤 Мастера", callback_data="add_master")
    builder.button(text="📂 Управление", callback_data="view_lists")
    builder.button(text="📅 Записи", callback_data="view_appointments")
    builder.button(text="📊 Статистика", callback_data="view_stats")
    builder.adjust(2, 1, 2) 
    return builder.as_markup()

async def get_user_org(session, tg_id):
    """Поиск организации по Telegram ID владельца"""
    user = await session.scalar(select(User).where(User.telegram_id == tg_id))
    if not user: return None
    return await session.scalar(select(Organization).where(Organization.owner_id == user.id))

# --- ГЛАВНОЕ МЕНЮ ---

@router.callback_query(F.data == "admin_panel")
async def show_admin_menu(event: CallbackQuery | Message, state: FSMContext):
    await state.clear() 
    
    async with SessionLocal() as session:
        user_id = event.from_user.id
        org = await get_user_org(session, user_id)
        
        if not org:
            return await event.answer("Организация не найдена.")

        # Умный подбор темы по ключевым словам
        raw_cat = str(org.category) if org.category else ""
        
        if "СТО" in raw_cat or "Авто" in raw_cat:
            theme = BUSINESS_THEMES["СТО"]
        elif "Салон" in raw_cat or "Beauty" in raw_cat:
            theme = BUSINESS_THEMES["Салон красоты"]
        elif "СПА" in raw_cat or "SPA" in raw_cat:
            theme = BUSINESS_THEMES["СПА"]
        else:
            # Если ничего не подошло, берем "Другое"
            theme = BUSINESS_THEMES.get("Другое")

    # Формируем текст с иконкой категории
    category_icon = theme.get('category_icon', '⚙️')
    text = (f"{category_icon} **Панель управления: {org.name}**\n\n"
            f"Сфера: {org.category}\n"
            f"Настройте ваш бизнес ниже.")
    
    builder = InlineKeyboardBuilder()
    # Кнопки теперь берут названия из theme (Мастер/Бокс, Работа и т.д.)
    builder.button(text=f"➕ {theme['service']}", callback_data="add_service")
    builder.button(text=f"➕ {theme['master']}", callback_data="add_master")
    builder.button(text="📂 Управление", callback_data="view_lists")
    builder.button(text="📅 График", callback_data="view_appointments")
    builder.button(text="📢 Рассылка", callback_data="admin_broadcast") # Новая кнопка
    builder.button(text="📊 Статистика", callback_data="view_stats")
    builder.adjust(2, 1, 2, 1) # Подправь разметку (добавили 1 кнопку в новый ряд)

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
            return await callback.answer("Сначала создайте компанию!", show_alert=True)

        result = await session.execute(select(Master).where(Master.organization_id == org.id))
        masters = result.scalars().all()

    builder = InlineKeyboardBuilder()
    if not masters:
        builder.button(text="➕ Добавить мастера", callback_data="add_master")
    else:
        for m in masters:
            builder.button(text=f"👤 {m.name}", callback_data=f"master_cal_{m.id}")
    
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="view_lists"))

    await callback.message.edit_text(
        "📅 **Выберите мастера для просмотра графика:**", 
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
        f"📅 Календарь: **{month_name} {now.year}**\n\nВыберите день для управления записями:", 
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

# --- БЛОК: СТАТИСТИКА ---

@router.callback_query(F.data == "view_stats")
async def view_stats(callback: CallbackQuery):
    async with SessionLocal() as session:
        org = await get_user_org(session, callback.from_user.id)
        if not org: return await callback.answer("Организация не найдена")
        
        total_appts = await session.scalar(select(func.count(Appointment.id)).join(Service).where(Service.organization_id == org.id)) or 0
        total_revenue = await session.scalar(select(func.sum(Service.price)).join(Appointment).where(Service.organization_id == org.id)) or 0
        
        top_query = await session.execute(
            select(Service.name, func.count(Appointment.id))
            .join(Appointment).where(Service.organization_id == org.id)
            .group_by(Service.name).order_by(func.count(Appointment.id).desc()).limit(1)
        )
        pop = top_query.first()
        pop_name = pop[0] if pop else "Нет записей"

    stats_text = (
        f"📊 **Аналитика: {org.name}**\n━━━━━━━━━━━━━━\n"
        f"📅 Всего записей: {total_appts}\n"
        f"💰 Оборот: {total_revenue} грн\n"
        f"🏆 Топ услуг: {pop_name}"
    )
    
    builder = InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="admin_panel")
    await callback.message.edit_text(stats_text, reply_markup=builder.as_markup())

# --- БЛОК: ДОБАВЛЕНИЕ МАСТЕРА ---

@router.callback_query(F.data == "add_master")
async def start_add_master(callback: CallbackQuery, state: FSMContext):
    await state.set_state(MasterAddState.name)
    builder = InlineKeyboardBuilder().button(text="❌ Отмена", callback_data="admin_panel")
    await callback.message.edit_text("👤 **Шаг 1:** Введите имя мастера:", reply_markup=builder.as_markup())
    await callback.answer()

@router.message(MasterAddState.name)
async def process_master_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(MasterAddState.specialty)
    await message.answer(f"🎓 **Шаг 2:** Какая специализация у **{message.text}**?")

@router.message(MasterAddState.specialty)
async def process_master_spec(message: Message, state: FSMContext):
    await state.update_data(spec=message.text)
    await state.set_state(MasterAddState.photo)
    builder = InlineKeyboardBuilder().button(text="⏭ Пропустить фото", callback_data="skip_photo")
    await message.answer("📸 **Шаг 3:** Отправьте фото или пропустите:", reply_markup=builder.as_markup())

@router.message(MasterAddState.photo, F.photo)
@router.callback_query(F.data == "skip_photo")
async def process_master_photo(event: Message | CallbackQuery, state: FSMContext):
    data = await state.get_data()
    photo_id = event.photo[-1].file_id if isinstance(event, Message) else None
    
    async with SessionLocal() as session:
        org = await get_user_org(session, event.from_user.id)
        if org:
            new_master = Master(name=data['name'], specialty=data['spec'], photo_id=photo_id, organization_id=org.id)
            session.add(new_master)
            await session.commit()
    
    await state.clear()
    text = f"✅ Мастер **{data['name']}** добавлен!"
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
            theme = BUSINESS_THEMES["Салон красоты"]
        elif "СПА" in raw_cat or "SPA" in raw_cat:
            theme = BUSINESS_THEMES["СПА"]
        else:
            theme = BUSINESS_THEMES["Другое"]

    builder = InlineKeyboardBuilder()
    
    # Берем готовые формы множественного числа
    services_text = theme['services_plural']
    masters_text = theme['masters_plural']
    srv_icon = theme['category_icon']
    emp_icon = theme['employee_icon']

    builder.button(
        text=f"{srv_icon} Наши {theme['services_plural']}", 
        callback_data="view_services"
    )
    builder.button(
        text=f"{emp_icon} {theme['masters_plural']} (График)", 
        callback_data="manage_masters"
    )
    # Используем родительный падеж здесь:
    builder.button(
        text=f"📝 Список {theme['masters_genitive']} (Редакт.)", 
        callback_data="view_masters"
    )
    builder.button(text="⬅️ Назад", callback_data="admin_panel")
    
    builder.adjust(1)
    await callback.message.edit_text("📂 **Управление ресурсами:**", reply_markup=builder.as_markup())

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
    
    text = "👥 **Ваши мастера:**"
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
        master = await session.get(Master, master_id)
    if not master: return await callback.answer("Мастер не найден")

    text = f"👤 **Мастер:** {master.name}\n🎓 **Профиль:** {master.specialty}"
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Удалить", callback_data=f"delete_master:{master.id}")
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
        master = await session.get(Master, master_id)
        if master:
            await session.delete(master)
            await session.commit()
            await callback.answer("Мастер удален")
    await view_masters(callback)

# --- УПРАВЛЕНИЕ УСЛУГАМИ ---

@router.callback_query(F.data == "view_services")
async def view_services(callback: CallbackQuery):
    async with SessionLocal() as session:
        org = await get_user_org(session, callback.from_user.id)
        if not org: return await callback.answer("Организация не найдена")

        # Логика подбора темы по ключевому слову
        raw_cat = str(org.category) if org.category else ""
        if "СТО" in raw_cat or "Авто" in raw_cat:
            theme = BUSINESS_THEMES["СТО"]
        elif "Салон" in raw_cat or "Beauty" in raw_cat:
            theme = BUSINESS_THEMES["Салон красоты"]
        elif "СПА" in raw_cat or "SPA" in raw_cat:
            theme = BUSINESS_THEMES["СПА"]
        else:
            theme = BUSINESS_THEMES["Другое"]

    result = await session.execute(select(Service).where(Service.organization_id == org.id))
    services = result.scalars().all()
    
    builder = InlineKeyboardBuilder()
    icon = theme['category_icon']

    if services:
        for srv in services:
            builder.button(
                text=f"{icon} {srv.name} — {srv.price}грн", 
                callback_data=f"info_service:{srv.id}"
            )
    
    builder.button(text=f"➕ Добавить {theme['service'].lower()}", callback_data="add_service")
    builder.button(text="⬅️ Назад", callback_data="view_lists")
    builder.adjust(1)

    await callback.message.edit_text(
        f"📋 **Список: {theme['service']}**\n\nВыберите позицию для управления:", 
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("info_service:"))
async def service_info(callback: CallbackQuery):
    # Достаем ID услуги из callback_data
    service_id = int(callback.data.split(":")[1])
    
    async with SessionLocal() as session:
        service = await session.get(Service, service_id)
    
    if not service:
        return await callback.answer("Услуга не найдена", show_alert=True)

    # Формируем текст карточки услуги
    text = (
        f"🔎 **Карточка услуги**\n"
        f"━━━━━━━━━━━━━━\n"
        f"📌 **Название:** {service.name}\n"
        f"💰 **Цена:** {service.price} грн\n"
        f"⏱ **Длительность:** {service.duration_minutes} мин\n"
    )
    
    builder = InlineKeyboardBuilder()
    # ВОТ ЭТА КНОПКА: она должна вести на меню выбора, что именно менять
    builder.button(text="📝 Изменить данные", callback_data=f"edit_srv_menu:{service.id}")
    builder.button(text="🗑 Удалить услугу", callback_data=f"delete_service:{service.id}")
    builder.button(text="⬅️ Назад к списку", callback_data="view_services")
    
    builder.adjust(1) # Все кнопки в один столбец
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("delete_service:"))
async def delete_service(callback: CallbackQuery):
    service_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        service = await session.get(Service, service_id)
        if service:
            await session.delete(service)
            await session.commit()
    await view_services(callback)

# --- ДОБАВЛЕНИЕ УСЛУГИ ---

@router.callback_query(F.data == "add_service")
async def start_add_service(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ServiceAddState.name)
    await callback.message.edit_text("💅 **Название услуги:**", reply_markup=InlineKeyboardBuilder().button(text="❌ Отмена", callback_data="admin_panel").as_markup())

@router.message(ServiceAddState.name)
async def process_service_name(message: Message, state: FSMContext):
    data = await state.get_data()
    new_name = message.text
    
    if "service_id" in data:
        # Режим редактирования
        async with SessionLocal() as session:
            service = await session.get(Service, data["service_id"])
            if service:
                service.name = new_name
                await session.commit()
        await message.answer(f"✅ Название успешно изменено на: **{new_name}**")
        await state.clear()
        await show_admin_menu(message, state)
    else:
        # Режим создания
        await state.update_data(name=new_name)
        await state.set_state(ServiceAddState.price)
        await message.answer(f"💰 Введите цену для «{new_name}»:")

@router.message(ServiceAddState.price)
async def process_service_price(message: Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("Введите число!")
    
    data = await state.get_data()
    new_price = int(message.text)
    
    if "service_id" in data:
        # ЛОГИКА РЕДАКТИРОВАНИЯ
        async with SessionLocal() as session:
            service = await session.get(Service, data["service_id"])
            service.price = new_price
            await session.commit()
        await message.answer(f"✅ Цена успешно изменена на {new_price} грн")
        await state.clear()
        # Возвращаем в меню управления
        await show_admin_menu(message, state)
    else:
        # ЛОГИКА СОЗДАНИЯ (та, что уже была)
        await state.update_data(price=new_price)
        await state.set_state(ServiceAddState.duration)
        await message.answer("⏱ Длительность в минутах:")

@router.message(ServiceAddState.duration)
async def process_service_duration(message: Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("Введите цифры!")
    
    data = await state.get_data()
    new_duration = int(message.text)
    
    if "service_id" in data:
        # Режим редактирования
        async with SessionLocal() as session:
            service = await session.get(Service, data["service_id"])
            if service:
                service.duration_minutes = new_duration
                await session.commit()
        await message.answer(f"✅ Длительность изменена на: **{new_duration} мин**")
        await state.clear()
        await show_admin_menu(message, state)
    else:
        # Режим создания
        async with SessionLocal() as session:
            org = await get_user_org(session, message.from_user.id)
            if org:
                new_service = Service(
                    name=data['name'], 
                    price=data['price'], 
                    duration_minutes=new_duration, 
                    organization_id=org.id
                )
                session.add(new_service)
                await session.commit()
        
        await message.answer(f"✅ Услуга **{data['name']}** успешно добавлена!")
        await state.clear()
        await show_admin_menu(message, state)


@router.callback_query(F.data.startswith("edit_srv_menu:"))
async def edit_service_menu(callback: CallbackQuery, state: FSMContext):
    service_id = int(callback.data.split(":")[1])
    
    # Сохраняем ID услуги в состояние, чтобы бот знал, ЧТО мы редактируем
    await state.update_data(service_id=service_id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Название", callback_data="edit_srv_name")
    builder.button(text="💰 Цену", callback_data="edit_srv_price")
    builder.button(text="⏱ Время", callback_data="edit_srv_duration")
    builder.button(text="⬅️ Отмена", callback_data=f"info_service:{service_id}")
    builder.adjust(2, 1)
    
    await callback.message.edit_text(
        "**Что именно вы хотите изменить?**", 
        reply_markup=builder.as_markup()
    )
    await callback.answer()

# Хендлеры для запуска ввода новых данных
@router.callback_query(F.data == "edit_srv_name")
async def edit_name_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ServiceAddState.name)
    await callback.message.answer("Введите новое название услуги:")
    await callback.answer()

@router.callback_query(F.data == "edit_srv_price")
async def edit_price_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ServiceAddState.price)
    await callback.message.answer("Введите новую цену (только число):")
    await callback.answer()

@router.callback_query(F.data == "edit_srv_duration")
async def edit_duration_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ServiceAddState.duration)
    await callback.message.answer("Введите новую длительность в минутах:")
    await callback.answer()
# --- ЗАПИСИ ---

@router.callback_query(F.data == "view_appointments")
async def view_appointments(callback: CallbackQuery):
    async with SessionLocal() as session:
        org = await get_user_org(session, callback.from_user.id)
        query = (
            select(Appointment)
            .join(Service)
            .where(Service.organization_id == org.id)
            .options(
                selectinload(Appointment.client), 
                selectinload(Appointment.service)
            )
            .order_by(Appointment.datetime.asc())
        )
        appointments = (await session.execute(query)).scalars().all()

    builder = InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="admin_panel")
    if not appointments:
        return await callback.message.edit_text("📅 Записей нет.", reply_markup=builder.as_markup())

    text = "📅 **Список записей:**\n\n"
    for appt in appointments:
        text += f"👤 {appt.client.full_name if appt.client else 'Клиент'}\n🔹 {appt.service.name}\n⏰ {appt.datetime.strftime('%d.%m %H:%M')}\n━━━━━━━━━━━━━━\n"
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("admin_day_"))
async def show_day_details(callback: CallbackQuery):
    # Разбираем callback_data (формат: admin_day_masterid_day)
    parts = callback.data.split("_")
    master_id = int(parts[2])
    day = int(parts[3])
    
    now = datetime.now()
    # Создаем объект даты для поиска в базе
    selected_date = datetime(now.year, now.month, day)

    async with SessionLocal() as session:
        # Ищем записи именно к этому мастеру на этот день
        query = (
            select(Appointment)
            .where(
                Appointment.master_id == master_id,
                func.date(Appointment.datetime) == selected_date.date()
            )
            .options(
                selectinload(Appointment.client),
                selectinload(Appointment.service)
            )
        )
        appointments = (await session.execute(query)).scalars().all()
        master = await session.get(Master, master_id)

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад к календарю", callback_data=f"master_cal_{master_id}")
    builder.adjust(1)

    date_str = selected_date.strftime('%d.%m.%Y')
    
    if not appointments:
        await callback.message.edit_text(
            f"📅 **{date_str}**\n👤 Мастер: **{master.name}**\n\nЗаписей на этот день пока нет.",
            reply_markup=builder.as_markup()
        )
    else:
        text = f"📅 **Записи на {date_str}**\n👤 Мастер: **{master.name}**\n\n"
        for appt in appointments:
            time_str = appt.datetime.strftime('%H:%M')
            client_name = appt.client.full_name if appt.client else "Клиент"
            text += f"⏰ {time_str} — {client_name}\n🔹 {appt.service.name}\n\n"
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
    
    await callback.answer()

@router.callback_query(F.data == "admin_broadcast")
async def start_broadcast(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите текст рассылки (можно добавить фото):")
    await state.set_state(BroadcastStates.waiting_for_message)
    await callback.answer()

@router.message(BroadcastStates.waiting_for_message)
async def preview_broadcast(message: Message, state: FSMContext):
    await state.update_data(broadcast_message_id=message.message_id)
    await message.answer("🔍 **ПРЕДПРОСМОТР:**")
    await message.copy_to(chat_id=message.from_user.id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚀 Запустить", callback_data="start_confirmed"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_broadcast")
        ]
    ])
    await message.answer("Начать рассылку на всех клиентов?", reply_markup=kb)
    await state.set_state(BroadcastStates.confirm_broadcast)

@router.callback_query(BroadcastStates.confirm_broadcast, F.data == "start_confirmed")
async def final_send_broadcast(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    msg_id = data.get("broadcast_message_id")
    
    await callback.message.edit_text("⏳ Рассылка запущена...")

    async with SessionLocal() as session:
        result = await session.execute(select(User.telegram_id).where(User.is_active == True))
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
            print(f"Ошибка при рассылке {user_id}: {e}")

    await callback.message.answer(
        f"✅ **Рассылка завершена!**\n\n"
        f"📈 Доставлено: {sent_count}\n"
        f"🚫 Ошибки: {blocked_count}\n"
        f"👥 Всего было в базе: {len(users)}"
    )
    await state.clear()

@router.callback_query(BroadcastStates.confirm_broadcast, F.data == "cancel_broadcast")
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Рассылка отменена.")