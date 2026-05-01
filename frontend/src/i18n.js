import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

// Встроенные переводы (не нужно загружать с сервера)
const resources = {
  ua: {
    translation: {
      app: {
        header: "Запис до {tenantName}",
        loading: "Завантаження...",
        error: "Не вдалося завантажити послуги. Спробуйте ще раз.",
        noServices: "У цьому салону временно немає доступних послуг.",
        confirmButton: "Підтвердити вибір",
        serviceSelected: "Ви обрали послугу з ID: {serviceId}"
      },
      serviceCard: {
        duration: "Тривалість: {duration} хв",
        price: "Ціна: {price} грн"
      }
    }
  },
  en: {
    translation: {
      app: {
        header: "Booking to {tenantName}",
        loading: "Loading...",
        error: "Failed to load services. Please try again.",
        noServices: "No services available at this salon temporarily.",
        confirmButton: "Confirm selection",
        serviceSelected: "You selected service with ID: {serviceId}"
      },
      serviceCard: {
        duration: "Duration: {duration} min",
        price: "Price: {price} uah"
      }
    }
  }
};

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    fallbackLng: 'ua',
    debug: false,
    interpolation: {
      escapeValue: false,
    },
    resources: resources
  });

export default i18n;
