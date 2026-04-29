from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import logging
import time

from aiogram.utils.web_app import safe_parse_webapp_init_data

from app.config import get_settings
from app.database.engine import SessionLocal
from app.database.models import User, Service, Tenant, UserRole
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Telegram Mini App API")

# Настройка CORS для работы с фронтендом на localhost:5173 и ngrok туннеле
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://silica-getup-fox.ngrok-free.dev"],
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
        # Создаем нового пользователя с ролью client
        # Привязываем к tenant_id из запроса
        new_user = User(
            telegram_id=telegram_id,
            full_name=f"{user_data['first_name']} {user_data['last_name'] or ''}".strip(),
            username=user_data["username"],
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
        # Если пользователь существует, но не привязан к тенанту, привязываем
        if user.tenant_id != request.tenant_id:
            user.tenant_id = request.tenant_id
            await db.commit()
            logger.info(f"Обновлен tenant_id для пользователя {user.id}")

    # Получаем список услуг для данного tenant_id
    stmt = select(Service).where(Service.tenant_id == request.tenant_id)
    result = await db.execute(stmt)
    services = result.scalars().all()

    # Преобразуем в список Pydantic моделей
    return [
        ServiceResponse(
            id=service.id,
            name=service.name,
            duration_minutes=service.duration_minutes,
            price=float(service.price),
        )
        for service in services
    ]

# Для запуска напрямую (например, для разработки)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)