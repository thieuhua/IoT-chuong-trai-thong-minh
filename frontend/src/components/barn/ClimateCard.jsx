import React from 'react';
import { useAuth } from '../../context/AuthContext';

export default function ClimateCard({
  currentReadings,
  onRelayToggle,
}) {
  const { canControl } = useAuth();

  return (
    <div className="env-grid">
      <div className="env-card">
        <div className="env-icon">🌡️</div>
        <div>
          <div className="env-label">Nhiệt Độ</div>
          <div className="env-val text-amber">
            {currentReadings.temp !== null ? `${currentReadings.temp} °C` : '--'}
          </div>
        </div>
      </div>

      <div className="env-card">
        <div className="env-icon">💧</div>
        <div>
          <div className="env-label">Độ Ẩm</div>
          <div className="env-val text-blue">
            {currentReadings.hum !== null ? `${currentReadings.hum} %` : '--'}
          </div>
        </div>
      </div>

      <div className="env-card">
        <div className="env-icon">🌀</div>
        <div>
          <div className="env-label">Quạt Làm Mát</div>
          <div className="env-actions">
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => onRelayToggle(1, 'on')}
              disabled={!canControl}
            >
              Bật
            </button>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => onRelayToggle(1, 'off')}
              disabled={!canControl}
            >
              Tắt
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
