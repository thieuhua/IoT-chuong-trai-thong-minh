import React from 'react';
import { useAuth } from '../../context/AuthContext';

function getFieldMeta(fieldName, sensorName) {
  const l = (fieldName || '').toLowerCase();
  const s = (sensorName || '').toLowerCase();
  if (l.includes('temp') || s.includes('temp')) {
    return { icon: '🌡️', colorClass: 'text-amber', defaultLabel: 'Nhiệt Độ', defaultUnit: '°C' };
  }
  if (l.includes('hum') || s.includes('hum') || l.includes('moist') || s.includes('moist')) {
    return { icon: '💧', colorClass: 'text-blue', defaultLabel: 'Độ Ẩm', defaultUnit: '%' };
  }
  if (l.includes('lux') || l.includes('light') || s.includes('light')) {
    return { icon: '☀️', colorClass: 'text-amber', defaultLabel: 'Ánh Sáng', defaultUnit: 'lx' };
  }
  if (l.includes('gas') || l.includes('co2') || l.includes('air') || s.includes('mq')) {
    return { icon: '🌫️', colorClass: 'text-muted', defaultLabel: 'Chất Lượng Khí', defaultUnit: 'ppm' };
  }
  if (l.includes('pressure') || l.includes('baro') || s.includes('bmp') || s.includes('bme')) {
    return { icon: '⏲️', colorClass: 'text-blue', defaultLabel: 'Áp Suất', defaultUnit: 'hPa' };
  }
  if (l.includes('soil')) {
    return { icon: '🌱', colorClass: 'text-green', defaultLabel: 'Độ Ẩm Đất', defaultUnit: '%' };
  }
  return { icon: '📊', colorClass: '', defaultLabel: fieldName, defaultUnit: '' };
}

export default function ClimateCard({
  sensor,
  currentReadings = {},
  isOnline = false,
  onRelayToggle,
  onFanAuto,
  fanMode = null,
}) {
  const { canControl } = useAuth();

  // Read only the selected sensor; missing readings must not use another sensor.
  const readings = currentReadings?.[sensor?.name] || {};
  const fields = Object.keys(sensor?.fields || {}).length > 0
    ? sensor.fields
    : Object.fromEntries(Object.keys(readings).map((name) => [name, '']));
  const sensorCards = sensor ? Object.entries(fields).map(([fieldName, unit]) => {
    const meta = getFieldMeta(fieldName, sensor.name);
    const value = readings[fieldName];
    const displayUnit = unit || meta.defaultUnit;
    return {
      id: `${sensor.name}_${fieldName}`,
      icon: meta.icon,
      label: meta.defaultLabel,
      colorClass: meta.colorClass,
      value: value !== null && value !== undefined ? `${value} ${displayUnit}`.trim() : '--',
    };
  }) : [];

  return (
    <div className="env-grid">
      {sensorCards.map((card) => (
        <div key={card.id} className="env-card">
          <div className="env-icon">{card.icon}</div>
          <div>
            <div className="env-label">{card.label}</div>
            <div className={`env-val ${card.colorClass}`}>{card.value}</div>
          </div>
        </div>
      ))}

      <div className="env-card">
        <div className="env-icon">🌀</div>
        <div>
          <div className="env-label">
            Quạt Làm Mát {!isOnline && <span className="text-muted">(Offline)</span>}
            {fanMode && (
              <span className="text-muted"> · {fanMode === 'AUTO' ? 'Tự động' : 'Chỉnh tay'}</span>
            )}
          </div>
          <div className="env-actions">
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => onRelayToggle(true)}
              disabled={!canControl || !isOnline}
              title={!isOnline ? 'Thiết bị đang offline' : ''}
            >
              Bật
            </button>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => onRelayToggle(false)}
              disabled={!canControl || !isOnline}
              title={!isOnline ? 'Thiết bị đang offline' : ''}
            >
              Tắt
            </button>
            <button
              className={`btn btn-sm ${fanMode === 'AUTO' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => onFanAuto?.()}
              disabled={!canControl || !isOnline || !onFanAuto}
              title="Quạt tự bật khi ≥ 32 °C, tắt khi ≤ 30 °C"
            >
              Tự động
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
