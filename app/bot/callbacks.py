from aiogram.filters.callback_data import CallbackData

class AppointmentConfirm(CallbackData, prefix="confirm_appt"):
    appointment_id: int