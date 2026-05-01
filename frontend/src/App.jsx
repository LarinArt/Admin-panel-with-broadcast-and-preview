import React, { useEffect, useState } from 'react';
import ServiceCard from './components/ServiceCard';
import { getServices } from './services/api';
import { useTranslation } from 'react-i18next';
import './App.css';

function App() {
  const { t } = useTranslation();
  const [tenantName, setTenantName] = useState('');
  const [services, setServices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedServiceId, setSelectedServiceId] = useState(null);

  useEffect(() => {
    // Check if we're in Telegram WebApp environment
    const isTelegramWebApp = window.Telegram?.WebApp;
    
    // For development/testing outside Telegram, we'll simulate the environment
    if (!isTelegramWebApp && window.location.hostname === 'localhost') {
      console.log('Running in development mode - simulating Telegram WebApp');
      
      // Simulate Telegram WebApp object for development
      window.Telegram = {
        WebApp: {
          ready: () => {},
          expand: () => {},
          initDataUnsafe: {
            start_param: 'tenant_1' // Default tenant for development
          },
          initData: 'dev_init_data_simulation', // This will fail validation but we'll handle it
          HapticFeedback: {
            impactOccurred: () => {}
          },
          MainButton: {
            setText: () => {},
            onClick: () => {},
            show: () => {},
            hide: () => {}
          }
        }
      };
    }

    // Инициализация Telegram WebApp
    if (window.Telegram?.WebApp) {
      window.Telegram.WebApp.ready();
      window.Telegram.WebApp.expand();

      // Получаем start_param из initDataUnsafe
      const startParam = window.Telegram.WebApp.initDataUnsafe.start_param;
      let tenantId = null;
      let tenantNameFromParam = '';

      if (startParam && startParam.startsWith('tenant_')) {
        tenantId = parseInt(startParam.split('_')[1], 10);
        // В реальном приложении, название салона можно получить из бэкенда или хранить в маппинге
        // Для демонстрации, предположим, что мы получаем его из бэкенда вместе с услугами
        // Но в данном случае, мы можем сохранить название в состоянии и обновить после загрузки услуг
        // Однако, для простоты, мы можем использовать статическое название или получить его из бэкенда отдельно.
        // Поскольку в задании не указано, как получить название салона, мы будем использовать заглушку.
        tenantNameFromParam = `Салон ${tenantId}`;
      }

      // Получаем инициализационные данные для отправки в бэкенд
      const initData = window.Telegram.WebApp.initData;

      // Запрашиваем услуги
      getServices(initData, tenantId)
        .then((data) => {
          setServices(data);
          // Если у нас есть хотя бы одна услуга, мы можем попытаться получить название салона из первой услуги?
          // Но в модели Service нет названия салона. Поэтому, возможно, нам нужно отдельно запрашивать информацию о салоне.
          // Поскольку в задании требуется отображать название салона в заголовке, и мы не имеем его в ответе,
          // мы будем использовать tenantId для поиска в базе или хранить в маппинге.
          // Для простоты, мы оставим заглушку.
          setTenantName(tenantNameFromParam || 'Невідомий салон');
          setLoading(false);
        })
        .catch((err) => {
          console.error('Ошибка при получении услуг:', err);
          // In development, we can show mock data instead of error
          if (window.location.hostname === 'localhost') {
            console.log('Development mode: showing mock services');
            setServices([
              { id: 1, name: 'Стрижка', duration_minutes: 30, price: 200.0 },
              { id: 2, name: 'Укладка', duration_minutes: 45, price: 150.0 },
              { id: 3, name: 'Окрашивание', duration_minutes: 60, price: 500.0 }
            ]);
            setTenantName('Демо-салон');
            setLoading(false);
          } else {
            setError('Не вдалося завантажити послуги. Спробуйте ще раз.');
            setLoading(false);
          }
        });
    } else {
      setError('Telegram WebApp не доступний');
      setLoading(false);
    }
  }, []);

  const handleServiceSelect = (serviceId) => {
    setSelectedServiceId(serviceId);
    // Soвторожаем тактильную обратную связь
    if (window.Telegram?.WebApp?.HapticFeedback) {
      window.Telegram.WebApp.HapticFeedback.impactOccurred('medium');
    }
  };

   const handleConfirm = () => {
     if (selectedServiceId) {
       // Здесь можно отправить выбор на бэкенд или просто закрыть приложение
       // Для демонстрации, мы просто покажем alert и закроем приложение
       alert(t('app.serviceSelected', { serviceId: selectedServiceId }));
       if (window.Telegram?.WebApp) {
         window.Telegram.WebApp.close();
       }
     }
   };

  // Настраиваем MainButton
  useEffect(() => {
    if (window.Telegram?.WebApp) {
      const mainButton = window.Telegram.WebApp.MainButton;
      mainButton.setText('Підтвердити вибір');
      mainButton.onClick(handleConfirm);
      mainButton.show();
      return () => {
        mainButton.hide();
      };
    }
  }, [selectedServiceId]);

   if (loading) {
     return <div className="flex h-screen items-center justify-center">{t('app.loading')}</div>;
   }
 
   if (error) {
     return <div className="flex h-screen items-center justify-center text-red-500">{t('app.error')}</div>;
   }
 
    return (
      <div className="min-h-screen">
        {/* Градиентный хедер */}
        <header className="page-header">
          <h1>{t('app.header', { tenantName })}</h1>
        </header>

        {/* Основной контент */}
        <main>
          {loading ? (
            <div className="loading-container">
              <div className="spinner"></div>
              <p className="text-lg" style={{ color: 'var(--tg-theme-hint-color)' }}>
                {t('app.loading')}
              </p>
            </div>
          ) : error ? (
            <div className="error-container">
              <div className="error-icon">⚠️</div>
              <p className="text-xl font-semibold">{t('app.error')}</p>
              <button
                onClick={() => window.location.reload()}
                className="mt-4 px-6 py-2 rounded-xl"
                style={{
                  backgroundColor: 'var(--tg-theme-button-color)',
                  color: 'var(--tg-theme-button-text-color)',
                }}
              >
                Перезагрузити
              </button>
            </div>
          ) : services.length > 0 ? (
            <div className="services-grid">
              {services.map((service) => (
                <ServiceCard
                  key={service.id}
                  service={service}
                  isSelected={selectedServiceId === service.id}
                  onSelect={() => handleServiceSelect(service.id)}
                />
              ))}
            </div>
          ) : (
            <div className="empty-state">
              <div className="empty-icon">📋</div>
              <p className="text-lg">{t('app.noServices')}</p>
            </div>
          )}
        </main>

        {/* Кнопка подтверждения (если выбран сервис) */}
        {selectedServiceId && (
          <div className="fixed bottom-6 left-4 right-4">
            <button
              onClick={handleConfirm}
              className="w-full py-4 rounded-2xl font-bold text-lg shadow-xl transform transition-all active:scale-95"
              style={{
                backgroundColor: 'var(--tg-theme-button-color)',
                color: 'var(--tg-theme-button-text-color)',
              }}
            >
              {t('app.confirmButton')}
            </button>
          </div>
        )}
      </div>
    );
}

export default App;