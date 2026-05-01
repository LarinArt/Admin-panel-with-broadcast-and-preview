import React from 'react';
import { useTranslation } from 'react-i18next';

function ServiceCard({ service, isSelected, onSelect }) {
  const { t } = useTranslation();

  // Иконки для услуг
  const getServiceIcon = (serviceName) => {
    const name = serviceName.toLowerCase();
    if (name.includes('стрижка')) return '✂️';
    if (name.includes('укладка')) return '💇‍♀️';
    if (name.includes('окрашивание')) return '🎨';
    return '💅';
  };

  return (
    <div
      onClick={onSelect}
      className={`
        relative p-5 rounded-2xl cursor-pointer transition-all duration-300
        ${isSelected 
          ? 'bg-gradient-to-r from-purple-600 to-pink-500 text-white shadow-lg scale-[1.02]' 
          : 'bg-white hover:bg-gray-50 text-gray-800 shadow-md hover:shadow-xl'
        }
        border-2 ${isSelected ? 'border-transparent' : 'border-gray-100'}
      `}
      style={{
        backgroundColor: isSelected ? 'var(--tg-theme-button-color)' : '',
        color: isSelected ? 'var(--tg-theme-button-text-color)' : '',
      }}
    >
      {/* Иконка услуги */}
      <div className="text-4xl mb-3 text-center">{getServiceIcon(service.name)}</div>

      {/* Название */}
      <h3 className="text-lg font-bold mb-2 leading-tight text-center">
        {service.name}
      </h3>

      {/* Длительность и цена */}
      <div className="flex items-center justify-between mt-3">
        <span className="text-sm opacity-80">
          ⏱️ {service.duration_minutes} хв
        </span>
        <span className="text-xl font-bold">
          {service.price} ₴
        </span>
      </div>

      {/* Индикатор выбора */}
      {isSelected && (
        <div className="absolute top-3 right-3 w-6 h-6 bg-white/30 rounded-full flex items-center justify-center">
          <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
          </svg>
        </div>
      )}
    </div>
  );
}

export default ServiceCard;
