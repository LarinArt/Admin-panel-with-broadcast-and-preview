from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import logging
import time
from datetime import datetime, timedelta

from aiogram.utils.web_app import safe_parse_webapp_init_data

from app.config import get_settings
from app.database.engine import SessionLocal, init_models
from app.database.models import User, Service, Tenant, UserRole, Master, Appointment, AppointmentStatus, Organization
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Grace period in days after subscription ends
GRACE_PERIOD_DAYS = 3

app = FastAPI(title="Telegram Mini App API")

# Startup event — инициализируем БД при старте
@app.on_event("startup")
async def startup_event():
    await init_models()

# Настройка CORS для работы с фронтендом на localhost:5173/5174 и ngrok туннеле
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "https://silica-getup-fox.ngrok-free.dev"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Получаем настройки
settings = get_settings()

# Модели Pydantic для запроса и ответа
class InitDataRequest(BaseModel):
    init_data: str
    tenant_id: int

class ServiceResponse(BaseModel):
    id: int
    name: str
    duration_minutes: int
    price: float

class MasterResponse(BaseModel):
    id: int
    name: str
    specialty: Optional[str] = None

class AvailableSlotResponse(BaseModel):
    time: str
    master_id: int
    master_name: str

class BookingRequest(BaseModel):
    init_data: str
    tenant_id: int
    service_id: int
    master_id: int
    date: str  # format: YYYY-MM-DD
    time: str  # format: HH:MM
    client_name: Optional[str] = None
    client_phone: Optional[str] = None

# Dependency для получения асинхронной сессии БД
async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session

# Функция для валидации initData и извлечения данных пользователя
def validate_init_data(init_data: str) -> dict:
    # For development, if we have a specific fake string, we return a fake user
    if init_data == 'dev_init_data_simulation':
        return {
            "user_id": 123456789,
            "first_name": "Dev",
            "last_name": "User",
            "username": "devuser",
            "language_code": "uk",
            "auth_date": int(time.time()),
            "hash": "fake_hash",
        }
    try:
        parsed_data = safe_parse_webapp_init_data(token=settings.bot_token, init_data=init_data)
        # Возвращаем словарь с данными пользователя
        return {
            "user_id": parsed_data.user.id,
            "first_name": parsed_data.user.first_name,
            "last_name": parsed_data.user.last_name,
            "username": parsed_data.user.username,
            "language_code": parsed_data.user.language_code,
            "auth_date": parsed_data.auth_date,
            "hash": parsed_data.hash,
        }
    except Exception as e:
        # In development, we return a fake user to allow the frontend to work
        # In production, this should not happen because initData should be valid
        logger.warning(f"InitData validation failed, returning fake user for development: {e}")
        return {
            "user_id": 123456789,
            "first_name": "Dev",
            "last_name": "User",
            "username": "devuser",
            "language_code": "uk",
            "auth_date": int(time.time()),
            "hash": "fake_hash",
        }

async def check_tenant_subscription(tenant_id: int, db: AsyncSession) -> tuple[bool, bool, Optional[datetime]]:
    """
    Check tenant subscription status.
    Returns: (is_active, is_expired, subscription_ends_at)
    """
    stmt = select(Tenant).where(Tenant.id == tenant_id)
    result = await db.execute(stmt)
    tenant = result.scalar_one_or_none()
    
    if not tenant:
        return False, False, None
    
    now = datetime.now(tenant.subscription_ends_at.tzinfo
                       if tenant.subscription_ends_at and tenant.subscription_ends_at.tzinfo
                       else None)
    is_expired = tenant.subscription_ends_at and now > tenant.subscription_ends_at
    is_active = tenant.is_active and not is_expired
    
    return is_active, is_expired, tenant.subscription_ends_at


@app.post("/api/get_services", response_model=List[ServiceResponse])
async def get_services(
    request: InitDataRequest,
    db: AsyncSession = Depends(get_db)
):
    # Валидируем initData
    user_data = validate_init_data(request.init_data)
    telegram_id = user_data["user_id"]

    # Проверяем, существует ли пользователь в базе
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        new_user = User(
            telegram_id=telegram_id,
            full_name=f"{user_data['first_name']} {user_data['last_name'] or ''}".strip(),
            language_code=user_data["language_code"] or "uk",
            role=UserRole.CLIENT,
            tenant_id=request.tenant_id,
            is_active=True,
        )
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        user = new_user
        logger.info(f"Создан новый пользователь: {user.id}")
    else:
        if user.tenant_id != request.tenant_id:
            user.tenant_id = request.tenant_id
            await db.commit()
            logger.info(f"Обновлен tenant_id для пользователя {user.id}")

    is_active, is_expired, subscription_ends_at = await check_tenant_subscription(
        request.tenant_id, db
    )
    
    if not is_active:
        return []

    stmt = select(Service).where(Service.tenant_id == request.tenant_id)
    result = await db.execute(stmt)
    services = result.scalars().all()

    return [
        ServiceResponse(
            id=service.id,
            name=service.name,
            duration_minutes=service.duration_minutes,
            price=float(service.price),
        )
        for service in services
    ]


# --- НОВЫЕ ЭНДПОИНТЫ ДЛЯ ЗАПИСИ ---

class MastersRequest(BaseModel):
    init_data: str
    tenant_id: int

@app.post("/api/masters", response_model=List[MasterResponse])
async def get_masters(
    request: MastersRequest,
    db: AsyncSession = Depends(get_db)
):
    """Получить список мастеров для tenant_id"""
    user_data = validate_init_data(request.init_data)
    
    is_active, _, _ = await check_tenant_subscription(request.tenant_id, db)
    if not is_active:
        raise HTTPException(status_code=403, detail="Tenant subscription inactive")
    
    stmt = select(Master).where(Master.tenant_id == request.tenant_id)
    result = await db.execute(stmt)
    masters = result.scalars().all()
    
    return [
        MasterResponse(id=m.id, name=m.name, specialty=m.specialty)
        for m in masters
    ]


class AvailableSlotsRequest(BaseModel):
    init_data: str
    tenant_id: int
    service_id: int
    master_id: int
    date: str  # YYYY-MM-DD

@app.post("/api/available_slots", response_model=List[AvailableSlotResponse])
async def get_available_slots(
    request: AvailableSlotsRequest,
    db: AsyncSession = Depends(get_db)
):
    """Получить свободные слоты на дату для мастера и услуги"""
    from datetime import datetime as dt_datetime, timedelta
    
    user_data = validate_init_data(request.init_data)
    
    is_active, _, _ = await check_tenant_subscription(request.tenant_id, db)
    if not is_active:
        raise HTTPException(status_code=403, detail="Subscription inactive")
    
    try:
        target_date = dt_datetime.strptime(request.date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    master = await db.scalar(select(Master).where(
        Master.id == request.master_id,
        Master.tenant_id == request.tenant_id
    ))
    if not master:
        raise HTTPException(status_code=404, detail="Master not found")
    
    from app.services.working_hours import get_working_hours
    try:
        start_time, end_time = get_working_hours(request.tenant_id, target_date.weekday())
    except Exception:
        return []
    
    service = await db.scalar(select(Service).where(Service.id == request.service_id))
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    slot_duration = service.duration_minutes
    start_dt = dt_datetime.combine(target_date, start_time)
    end_dt = dt_datetime.combine(target_date, end_time)
    
    slots = []
    current = start_dt
    while current + timedelta(minutes=slot_duration) <= end_dt:
        slot_end = current + timedelta(minutes=slot_duration)
        
        conflicting = await db.scalar(
            select(Appointment).where(
                Appointment.master_id == request.master_id,
                Appointment.datetime >= current,
                Appointment.datetime < slot_end,
                Appointment.status != AppointmentStatus.CANCELLED,
                Appointment.tenant_id == request.tenant_id,
            )
        )
        
        if not conflicting:
            slots.append({
                "time": current.strftime("%H:%M"),
                "master_id": request.master_id,
                "master_name": master.name,
            })
        
        current += timedelta(minutes=30)
    
    return slots


class BookingRequest(BaseModel):
    init_data: str
    tenant_id: int
    service_id: int
    master_id: int
    date: str  # YYYY-MM-DD
    time: str  # HH:MM
    client_name: Optional[str] = None
    client_phone: Optional[str] = None

@app.post("/api/book")
async def create_booking(
    request: BookingRequest,
    db: AsyncSession = Depends(get_db)
):
    """Создать запись на услугу"""
    from datetime import datetime as dt_datetime, timedelta
    
    user_data = validate_init_data(request.init_data)
    telegram_id = user_data["user_id"]
    
    user = await db.scalar(select(User).where(User.telegram_id == telegram_id))
    if not user:
        user = User(
            telegram_id=telegram_id,
            full_name=f"{user_data['first_name']} {user_data['last_name'] or ''}".strip(),
            language_code=user_data.get("language_code", "uk"),
            role=UserRole.CLIENT,
            tenant_id=request.tenant_id,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    
    is_active, _, _ = await check_tenant_subscription(request.tenant_id, db)
    if not is_active:
        raise HTTPException(status_code=403, detail="Subscription inactive")
    
    try:
        dt_str = f"{request.date} {request.time}"
        appointment_dt = dt_datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date/time format")
    
    master = await db.scalar(select(Master).where(
        Master.id == request.master_id,
        Master.tenant_id == request.tenant_id
    ))
    if not master:
        raise HTTPException(status_code=404, detail="Master not found")
    
    service = await db.scalar(select(Service).where(
        Service.id == request.service_id,
        Service.tenant_id == request.tenant_id
    ))
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    slot_end = appointment_dt + timedelta(minutes=service.duration_minutes)
    conflict = await db.scalar(
        select(Appointment).where(
            Appointment.master_id == request.master_id,
            Appointment.datetime >= appointment_dt,
            Appointment.datetime < slot_end,
            Appointment.status != AppointmentStatus.CANCELLED,
            Appointment.tenant_id == request.tenant_id,
        )
    )
    if conflict:
        raise HTTPException(status_code=409, detail="Time slot already booked")
    
    appointment = Appointment(
        tenant_id=request.tenant_id,
        master_id=request.master_id,
        organization_id=master.organization_id,
        client_id=user.id,
        service_id=request.service_id,
        datetime=appointment_dt,
        status=AppointmentStatus.CONFIRMED,
    )
    db.add(appointment)
    await db.commit()
    
    return {
        "success": True,
        "appointment_id": appointment.id,
        "message": "Запись создана успешно"
    }


# Для запуска напрямую (например, для разработки)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)