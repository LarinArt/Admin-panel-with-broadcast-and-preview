from datetime import date, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.models import Appointment, AppointmentStatus, Holiday, Service
from app.services.working_hours import get_working_hours

settings = get_settings()

async def calculate_available_slots(
    session: AsyncSession,
    service_id: int,
    target_date: date,
    tenant_id: int,
    master_id: int | None = None,
) -> list[datetime]:
    service = await session.get(Service, service_id)
    if service is None or service.tenant_id != tenant_id:
        return []

    holiday = await session.scalar(
        select(Holiday.id).where(
            Holiday.tenant_id == tenant_id,
            Holiday.holiday_date == target_date,
        )
    )
    if holiday:
        return []

    # Получаем часы работы
    start_time, end_time = get_working_hours(tenant_id, target_date.weekday())
    
    # Создаем границы дня с часовым поясом
    day_start = datetime.combine(target_date, start_time, tzinfo=settings.tz)
    day_end = datetime.combine(target_date, end_time, tzinfo=settings.tz)
    now = datetime.now(settings.tz)

    filters = [
        Appointment.tenant_id == tenant_id,
        Appointment.datetime >= day_start,
        Appointment.datetime < day_end,
        Appointment.status != AppointmentStatus.CANCELLED,
    ]
    if master_id is not None:
        filters.append(Appointment.master_id == master_id)
    
    existing_stmt = select(Appointment).join(Service, Service.id == Appointment.service_id).where(and_(*filters))
    existing_appointments = (await session.scalars(existing_stmt)).all()

    busy_ranges: list[tuple[datetime, datetime]] = []
    for appt in existing_appointments:
        # Обеспечиваем, что datetime имеет информацию о часовом поясе
        # SQLite может возвращать naive datetime даже для колонки с timezone=True
        if appt.datetime.tzinfo is None:
            # Если naive datetime, предполагаем, что он в часовом поясе settings.tz
            appt_start = appt.datetime.replace(tzinfo=settings.tz)
        else:
            # Если уже aware datetime, конвертируем в settings.tz
            appt_start = appt.datetime.astimezone(settings.tz)
        appt_end = appt_start + timedelta(minutes=appt.service.duration_minutes)
        busy_ranges.append((appt_start, appt_end))

    step = timedelta(minutes=settings.slot_step_minutes)
    duration = timedelta(minutes=service.duration_minutes)
    candidate = day_start
    slots: list[datetime] = []

    while candidate + duration <= day_end:
        # Сравнение теперь сработает, так как оба объекта имеют tzinfo
        if candidate > now:
            candidate_end = candidate + duration
            overlaps = any(
                candidate < busy_end and candidate_end > busy_start
                for busy_start, busy_end in busy_ranges
            )
            if not overlaps:
                slots.append(candidate)
        candidate += step

    return slots