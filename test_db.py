import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.database.engine import SessionLocal
from app.database.models import Appointment, User, Service, AppointmentStatus, UserRole

async def create_test_data():
    async with SessionLocal() as session:
        # 1. Ищем или создаем тестового пользователя (укажи свой ID!)
        my_id = 123456789  # ЗАМЕНИ НА СВОЙ ТЕЛЕГРАМ ID
        user = await session.get(User, 1) # пробуем взять первого или создаем
        
        # 2. Создаем услугу, если их нет
        service = Service(name="Тестовая стрижка", price=500, duration=60)
        session.add(service)
        await session.flush()

        # 3. Создаем запись, которая будет ровно через 24 часа от текущего момента
        # Это как раз попадет в условие 23.5 <= hours <= 24.5
        tz = ZoneInfo("Europe/Kyiv")
        test_datetime = datetime.now(tz) + timedelta(hours=24)

        test_appt = Appointment(
            client_id=1, # ID пользователя из таблицы users
            service_id=service.id,
            datetime=test_datetime,
            status=AppointmentStatus.CONFIRMED,
            reminder_24h_sent=False,
            reminder_2h_sent=False
        )
        
        session.add(test_appt)
        await session.commit()
        print(f"✅ Тестовая запись создана на время: {test_datetime}")

if __name__ == "__main__":
    asyncio.run(create_test_data())