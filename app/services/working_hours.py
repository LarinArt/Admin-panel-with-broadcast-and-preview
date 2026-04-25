from datetime import time

from app.config import get_settings

settings = get_settings()

# weekday: 0 = Monday ... 6 = Sunday
_default_day = (time(settings.work_start_hour, 0), time(settings.work_end_hour, 0))
_working_hours_by_tenant: dict[int, dict[int, tuple[time, time]]] = {}


def get_working_hours(tenant_id: int, weekday: int) -> tuple[time, time]:
    tenant_schedule = _working_hours_by_tenant.get(tenant_id)
    if not tenant_schedule:
        return _default_day
    return tenant_schedule.get(weekday, _default_day)


def set_working_hours(tenant_id: int, start_time: time, end_time: time) -> None:
    tenant_schedule = _working_hours_by_tenant.setdefault(tenant_id, {})
    for day in range(7):
        tenant_schedule[day] = (start_time, end_time)


def set_working_hours_for_day(tenant_id: int, weekday: int, start_time: time, end_time: time) -> None:
    tenant_schedule = _working_hours_by_tenant.setdefault(tenant_id, {})
    tenant_schedule[weekday] = (start_time, end_time)
