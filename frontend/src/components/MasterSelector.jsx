import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

function MasterSelector({ masters, selectedMasterId, onSelect, loading, onBack }) {
  const { t } = useTranslation();

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-8">
        <div className="spinner w-8 h-8 mb-2"></div>
        <p className="text-gray-500">Завантаження мастрів...</p>
      </div>
    );
  }

  if (!masters || masters.length === 0) {
    return (
      <div className="text-center py-8">
        <p className="text-gray-500">Немає доступних мастрів</p>
        {onBack && (
          <button onClick={onBack} className="mt-4 text-blue-500 hover:text-blue-700">
            ← Назад
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between mb-4">
        <button
          onClick={onBack}
          className="flex items-center gap-2 text-blue-500 hover:text-blue-700 font-medium"
        >
          ← Назад
        </button>
        <h2 className="text-lg font-semibold">Оберіть майстра:</h2>
        <div className="w-20"></div>
      </div>
      
      {masters.map((master) => (
        <div
          key={master.id}
          onClick={() => onSelect(master.id)}
          className={`
            p-4 rounded-xl cursor-pointer transition-all duration-200 border-2
            ${selectedMasterId === master.id
              ? 'border-blue-500 bg-blue-50 shadow-md'
              : 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50'
            }
          `}
        >
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-full bg-gradient-to-r from-blue-400 to-purple-500 flex items-center justify-center text-white text-xl font-bold">
              {master.name.charAt(0).toUpperCase()}
            </div>
            <div className="flex-1">
              <h3 className="font-bold text-gray-800">{master.name}</h3>
              {master.specialty && (
                <p className="text-sm text-gray-500">{master.specialty}</p>
              )}
            </div>
            {selectedMasterId === master.id && (
              <div className="w-6 h-6 rounded-full bg-blue-500 flex items-center justify-center">
                <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                </svg>
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

export default MasterSelector;
