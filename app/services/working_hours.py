from datetime import time

from app.config import get_settings

settings = get_settings()

# weekday: 0 = Monday ... 6 = Sunday
_working_hours: dict[int, tuple[time, time]] = {
    day: (time(settings.work_start_hour, 0), time(settings.work_end_hour, 0))
    for day in range(7)
}


def get_working_hours(weekday: int) -> tuple[time, time]:
    return _working_hours[weekday]


def set_working_hours(start_time: time, end_time: time) -> None:
    for day in range(7):
        _working_hours[day] = (start_time, end_time)
