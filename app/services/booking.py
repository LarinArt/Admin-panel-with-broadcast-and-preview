from datetime import date, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.models import Appointment, AppointmentStatus, Service
from app.services.working_hours import get_working_hours

settings = get_settings()


async def calculate_available_slots(
    session: AsyncSession,
    service_id: int,
    target_date: date,
) -> list[datetime]:
    service = await session.get(Service, service_id)
    if service is None:
        return []

    start_time, end_time = get_working_hours(target_date.weekday())
    day_start = datetime.combine(target_date, start_time, tzinfo=settings.tz)
    day_end = datetime.combine(target_date, end_time, tzinfo=settings.tz)
    now = datetime.now(settings.tz)

    existing_stmt = (
        select(Appointment)
        .join(Service, Service.id == Appointment.service_id)
        .where(
            and_(
                Appointment.datetime >= day_start,
                Appointment.datetime < day_end,
                Appointment.status != AppointmentStatus.CANCELLED,
            )
        )
    )
    existing_appointments = (await session.scalars(existing_stmt)).all()

    busy_ranges: list[tuple[datetime, datetime]] = []
    for appt in existing_appointments:
        appt_end = appt.datetime + timedelta(minutes=appt.service.duration_minutes)
        busy_ranges.append((appt.datetime, appt_end))

    step = timedelta(minutes=settings.slot_step_minutes)
    duration = timedelta(minutes=service.duration_minutes)
    candidate = day_start
    slots: list[datetime] = []

    while candidate + duration <= day_end:
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
