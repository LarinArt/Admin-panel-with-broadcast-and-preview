import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';

function BookingCalendar({ serviceId, masterId, selectedDate, onDateSelect, onSlotSelect, onBack }) {
  const { t } = useTranslation();
  const [currentDate, setCurrentDate] = useState(new Date());
  const [slots, setSlots] = useState([]);
  const [loading, setLoading] = useState(false);
  const [initData] = useState('dev_init_data_simulation'); // dev mode

  const monthNames = [
    "Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень",
    "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень"
  ];
  const weekDays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"];

  // Генерация календаря
  const getCalendarDays = () => {
    const year = currentDate.getFullYear();
    const month = currentDate.getMonth();
    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    const daysInMonth = lastDay.getDate();
    const startingDay = firstDay.getDay();
    const startingDayAdjusted = startingDay === 0 ? 7 : startingDay;

    const days = [];
    for (let i = 1; i < startingDayAdjusted; i++) days.push(null);
    for (let day = 1; day <= daysInMonth; day++) days.push(new Date(year, month, day));
    return days;
  };

  // Загрузка слотов при изменении selectedDate
  useEffect(() => {
    if (!selectedDate) return;

    const fetchSlots = async () => {
      setLoading(true);
      try {
        const dateStr = selectedDate.toISOString().split('T')[0];
        const response = await fetch(
          `/api/available_slots?init_data=${encodeURIComponent(initData)}&tenant_id=1&service_id=${serviceId}&master_id=${masterId}&date=${dateStr}`
        );
        if (response.ok) {
          const data = await response.json();
          setSlots(data);
        } else {
          setSlots([]);
        }
      } catch (err) {
        console.error('Failed to fetch slots', err);
        setSlots([]);
      } finally {
        setLoading(false);
      }
    };

    fetchSlots();
  }, [selectedDate, serviceId, masterId, initData]);

  const prevMonth = () => {
    setCurrentDate(new Date(currentDate.getFullYear(), currentDate.getMonth() - 1, 1));
  };

  const nextMonth = () => {
    setCurrentDate(new Date(currentDate.getFullYear(), currentDate.getMonth() + 1, 1));
  };

  const isPastDate = (date) => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return date < today;
  };

  const handleDayClick = (date) => {
    if (date && !isPastDate(date)) {
      onDateSelect(date);
    }
  };

  const renderCalendar = () => {
    const days = getCalendarDays();
    const weeks = [];
    let week = [];

    days.forEach((day, index) => {
      if (index % 7 === 0 && index > 0) {
        weeks.push(week);
        week = [];
      }
      week.push(day);
    });
    weeks.push(week);

    return weeks.map((week, wIndex) => (
      <div key={wIndex} className="grid grid-cols-7 gap-1">
        {week.map((day, dIndex) => {
          if (!day) return <div key={dIndex} className="h-10"></div>;
          const dateStr = day.toISOString().split('T')[0];
          const isSelected = selectedDate && dateStr === selectedDate.toISOString().split('T')[0];
          const disabled = isPastDate(day);

          return (
            <button
              key={dIndex}
              onClick={() => handleDayClick(day)}
              disabled={disabled}
              className={`
                h-10 rounded-lg text-sm font-medium transition-all
                ${isSelected
                  ? 'bg-blue-500 text-white shadow-md'
                  : disabled
                    ? 'text-gray-300 cursor-not-allowed'
                    : 'hover:bg-blue-100 text-gray-700'
                }
              `}
            >
              {day.getDate()}
            </button>
          );
        })}
      </div>
    ));
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between mb-4">
        <button onClick={onBack} className="flex items-center gap-2 text-blue-500 hover:text-blue-700 font-medium">
          ← Назад
        </button>
        <h2 className="text-lg font-semibold">Оберіть дату</h2>
        <div className="w-20"></div>
      </div>

      {/* Календарь */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4">
        <div className="flex items-center justify-between mb-4">
          <button onClick={prevMonth} className="p-2 hover:bg-gray-100 rounded-lg">‹</button>
          <h3 className="font-bold text-lg">{monthNames[currentDate.getMonth()]} {currentDate.getFullYear()}</h3>
          <button onClick={nextMonth} className="p-2 hover:bg-gray-100 rounded-lg">›</button>
        </div>

        <div className="grid grid-cols-7 gap-1 mb-2">
          {weekDays.map(day => (
            <div key={day} className="text-center text-xs font-semibold text-gray-500 py-2">{day}</div>
          ))}
        </div>

        {renderCalendar()}
      </div>

      {/* Слоты */}
      {selectedDate && (
        <div className="mt-6">
          <h3 className="text-md font-semibold mb-3">
            Доступні слоти на {selectedDate.toLocaleDateString('uk-UA')}
          </h3>
          {loading ? (
            <div className="flex justify-center py-4">
              <div className="spinner w-6 h-6"></div>
            </div>
          ) : slots.length > 0 ? (
            <div className="grid grid-cols-3 gap-2">
              {slots.map((slot, idx) => (
                <button
                  key={idx}
                  onClick={() => onSlotSelect(slot)}
                  className="py-3 px-4 rounded-lg border-2 border-blue-200 bg-blue-50 hover:bg-blue-100 hover:border-blue-300 transition-all font-medium"
                >
                  {slot.time}
                </button>
              ))}
            </div>
          ) : (
            <p className="text-gray-500 text-center py-4">Немає вільних слотів на цю дату</p>
          )}
        </div>
      )}
    </div>
  );
}

export default BookingCalendar;
