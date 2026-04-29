import React from 'react';
import PropTypes from 'prop-types';
import { useTranslation } from 'react-i18next';

const ServiceCard = ({ service, isSelected = false, onSelect }) => {
  const { t } = useTranslation();
  return (
    <div
      className={`cursor-pointer p-4 bg-card hover:bg-card-hover rounded-lg shadow-md transition-colors duration-200 ${isSelected ? 'border-2 border-accent' : ''}`}
      onClick={onSelect}
      style={{
        backgroundColor: 'var(--tg-theme-secondary-bg-color)',
        color: 'var(--tg-theme-text-color)',
        borderColor: 'var(--tg-theme-accent-color)',
      }}
    >
      <div className="flex justify-between items-start">
        <div>
          <h3 className="font-semibold mb-1">{service.name}</h3>
          <p className="text-sm text-text/60">
            {t('serviceCard.duration', { duration: service.duration_minutes })} • {t('serviceCard.price', { price: service.price.toFixed(2) })}
          </p>
        </div>
      </div>
    </div>
  );
};

ServiceCard.propTypes = {
  service: PropTypes.shape({
    id: PropTypes.number.isRequired,
    name: PropTypes.string.isRequired,
    duration_minutes: PropTypes.number.isRequired,
    price: PropTypes.number.isRequired,
  }).isRequired,
  isSelected: PropTypes.bool,
  onSelect: PropTypes.func.isRequired,
};

export default ServiceCard;