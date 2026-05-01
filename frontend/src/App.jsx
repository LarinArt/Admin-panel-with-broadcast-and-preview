import React, { useEffect, useState, useCallback } from 'react';
import ServiceCard from './components/ServiceCard';
import MasterSelector from './components/MasterSelector';
import BookingCalendar from './components/BookingCalendar';
import { getServices } from './services/api';
import { useTranslation } from 'react-i18next';
import './App.css';

function App() {
  const { t } = useTranslation();
  const [tenantName, setTenantName] = useState('');
  const [services, setServices] = useState([]);
  const [masters, setMasters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  // Booking flow state
  const [step, setStep] = useState('services'); // 'services' | 'masters' | 'calendar' | 'confirm'
  const [selectedServiceId, setSelectedServiceId] = useState(null);
  const [selectedMasterId, setSelectedMasterId] = useState(null);
  const [selectedDate, setSelectedDate] = useState(null);
  const [selectedTime, setSelectedTime] = useState(null);
  const [selectedSlot, setSelectedSlot] = useState(null);
  const [mastersLoading, setMastersLoading] = useState(false);

  const initData = 'dev_init_data_simulation';
  const tenantId = 1; // dev

  // Инициализация
  useEffect(() => {
    const isTelegramWebApp = window.Telegram?.WebApp;
    
    if (!isTelegramWebApp && window.location.hostname === 'localhost') {
      window.Telegram = {
        WebApp: {
          ready: () => {},
          expand: () => {},
          initDataUnsafe: { start_param: 'tenant_1' },
          initData: initData,
          HapticFeedback: { impactOccurred: () => {} },
          MainButton: { setText: () => {}, onClick: () => {}, show: () => {}, hide: () => {} }
        }
      };
    }

    if (window.Telegram?.WebApp) {
      window.Telegram.WebApp.ready();
      window.Telegram.WebApp.expand();

      const startParam = window.Telegram.WebApp.initDataUnsafe.start_param;
      let tid = null;
      let tName = '';
      if (startParam && startParam.startsWith('tenant_')) {
        tid = parseInt(startParam.split('_')[1], 10);
        tName = `Салон ${tid}`;
      }

      getServices(initData, tid || tenantId)
        .then((data) => {
          setServices(data);
          setTenantName(tName || 'Демо-салон');
          setLoading(false);
        })
        .catch((err) => {
          console.error('Ошибка при получении услуг:', err);
          if (window.location.hostname === 'localhost') {
            setServices([
              { id: 1, name: 'Стрижка', duration_minutes: 30, price: 200.0 },
              { id: 2, name: 'Укладка', duration_minutes: 45, price: 300.0 },
              { id: 3, name: 'Окрашивание', duration_minutes: 60, price: 500.0 }
            ]);
            setTenantName('Демо-салон');
            setLoading(false);
          } else {
            setError('Не вдалося завантажити послуги.');
            setLoading(false);
          }
        });
    } else {
      setError('Telegram WebApp не доступний');
      setLoading(false);
    }
  }, []);

  // Загрузка мастеров при выборе услуги
  useEffect(() => {
    if (step !== 'masters' || !selectedServiceId) return;

    const fetchMasters = async () => {
      setMastersLoading(true);
      try {
        // В dev-режиме используем фиктивных мастеров
        if (window.location.hostname === 'localhost') {
          const mockMasters = [
            { id: 1, name: 'Майстер Олександр', specialty: 'Волосся' },
            { id: 2, name: 'Майстер Марія', specialty: 'Зачіска' },
            { id: 3, name: 'Майстер Іван', specialty: 'Фарбування' },
          ];
          setMasters(mockMasters);
        } else {
          const response = await fetch(
            `/api/masters?init_data=${encodeURIComponent(initData)}&tenant_id=${tenantId}`
          );
          if (response.ok) {
            const data = await response.json();
            setMasters(data);
          } else {
            setMasters([]);
          }
        }
      } catch (err) {
        console.error('Failed to fetch masters', err);
        setMasters([]);
      } finally {
        setMastersLoading(false);
      }
    };

    fetchMasters();
  }, [step, selectedServiceId]);

  // Обработчики
  const handleServiceSelect = useCallback((serviceId) => {
    setSelectedServiceId(serviceId);
    setStep('masters');
    if (window.Telegram?.WebApp?.HapticFeedback) {
      window.Telegram.WebApp.HapticFeedback.impactOccurred('medium');
    }
  }, []);

  const handleMasterSelect = useCallback((masterId) => {
    setSelectedMasterId(masterId);
    setStep('calendar');
  }, []);

  const handleSlotSelect = useCallback((slot) => {
    setSelectedSlot(slot);
    setStep('confirm');
  }, []);

  const handleDateSelect = useCallback((date) => {
    setSelectedDate(date);
  }, []);

  const handleBackToServices = useCallback(() => {
    setStep('services');
    setSelectedServiceId(null);
    setMasters([]);
    setSelectedDate(null);
    setSelectedSlot(null);
  }, []);

  const handleBackToMasters = useCallback(() => {
    setStep('masters');
    setSelectedDate(null);
    setSelectedSlot(null);
  }, []);

  const handleBackToCalendar = useCallback(() => {
    setStep('calendar');
    setSelectedSlot(null);
  }, []);

  const handleBookingConfirm = async () => {
    if (!selectedSlot || !selectedDate) return;

    const dateStr = selectedDate.toISOString().split('T')[0];
    
    try {
      const response = await fetch(
        `/api/book?init_data=${encodeURIComponent(initData)}&tenant_id=${tenantId}` +
        `&service_id=${selectedServiceId}&master_id=${selectedMasterId}&date=${dateStr}&time=${selectedSlot.time}`,
        { method: 'POST' }
      );
      
      if (response.ok) {
        const result = await response.json();
        alert(t('app.serviceSelected', { serviceId: selectedServiceId }));
        if (window.Telegram?.WebApp) {
          window.Telegram.WebApp.close();
        }
      } else {
        alert('Помилка при записі: ' + response.statusText);
      }
    } catch (err) {
      alert('Помилка мережі');
    }
  };

  // MainButton для подтверждения записи (на шаге confirm)
  useEffect(() => {
    if (window.Telegram?.WebApp && step === 'confirm') {
      const mainButton = window.Telegram.WebApp.MainButton;
      mainButton.setText(t('app.confirmButton') || 'Підтвердити запис');
      mainButton.onClick(handleBookingConfirm);
      mainButton.show();
      return () => { mainButton.hide(); };
    }
  }, [step, selectedSlot, t]);

  if (loading) {
    return (
      <div className="loading-container">
        <div className="spinner"></div>
        <p className="text-lg" style={{ color: 'var(--tg-theme-hint-color)' }}>{t('app.loading')}</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="error-container">
        <div className="error-icon">⚠️</div>
        <p className="text-xl font-semibold">{t('app.error')}</p>
        <button onClick={() => window.location.reload()} className="mt-4 px-6 py-2 rounded-xl"
          style={{ backgroundColor: 'var(--tg-theme-button-color)', color: 'var(--tg-theme-button-text-color)' }}>
          Перезагрузити
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <header className="page-header">
        <h1>{t('app.header', { tenantName })}</h1>
      </header>

      <main className="p-4">
        {step === 'services' && services.length > 0 && (
          <div className="services-grid">
            {services.map((service) => (
              <ServiceCard
                key={service.id}
                service={service}
                isSelected={selectedServiceId === service.id}
                onSelect={handleServiceSelect}
              />
            ))}
          </div>
        )}

         {step === 'masters' && (
           <MasterSelector
             masters={masters}
             selectedMasterId={selectedMasterId}
             onSelect={handleMasterSelect}
             loading={mastersLoading}
             onBack={handleBackToServices}
           />
         )}

         {step === 'calendar' && selectedMasterId && (
           <BookingCalendar
             serviceId={selectedServiceId}
             masterId={selectedMasterId}
             selectedDate={selectedDate}
             onDateSelect={handleDateSelect}
             onSlotSelect={handleSlotSelect}
             onBack={handleBackToMasters}
           />
         )}

        {step === 'confirm' && selectedSlot && selectedDate && (
          <div className="space-y-4">
            <button
              onClick={handleBackToCalendar}
              className="flex items-center gap-2 text-blue-500 hover:text-blue-700 font-medium mb-4"
            >
              ← Назад до календаря
            </button>

            <div className="bg-white rounded-xl p-6 shadow-md border border-gray-200">
              <h2 className="text-xl font-bold mb-4">Підтвердження запису</h2>
              
              <div className="space-y-3">
                <div className="flex justify-between">
                  <span className="text-gray-600">Послуга:</span>
                  <span className="font-semibold">{services.find(s => s.id === selectedServiceId)?.name}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Майстер:</span>
                  <span className="font-semibold">{masters.find(m => m.id === selectedMasterId)?.name}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Дата:</span>
                  <span className="font-semibold">{selectedDate.toLocaleDateString('uk-UA')}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Час:</span>
                  <span className="font-semibold">{selectedSlot.time}</span>
                </div>
              </div>

              <p className="text-sm text-gray-500 mt-4">
                Після підтвердження запис буде створено. Ви отримаєте сповіщення.
              </p>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
