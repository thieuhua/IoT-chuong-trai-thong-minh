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
  device,
  currentReadings = {},
  isOnline = false,
  onRelayToggle,
}) {
  const { canControl } = useAuth();

  // Sinh danh sách cảm biến động từ device.sensors
  const sensorCards = [];
  const sensors = device?.sensors;

  if (Array.isArray(sensors) && sensors.length > 0) {
    for (const sensor of sensors) {
      const sName = sensor.name || 'sensor';
      const fields = sensor.fields || {};
      const sReadings = (currentReadings && currentReadings[sName]) || currentReadings || {};

      for (const [fieldName, unit] of Object.entries(fields)) {
        let val = sReadings[fieldName];
        if (val === undefined && currentReadings && currentReadings[fieldName] !== undefined) {
          val = currentReadings[fieldName];
        }

        const meta = getFieldMeta(fieldName, sName);
        const displayUnit = unit || meta.defaultUnit;
        const valText = val !== null && val !== undefined ? `${val} ${displayUnit}`.trim() : '--';

        sensorCards.push({
          id: `${sName}_${fieldName}`,
          icon: meta.icon,
          label: meta.defaultLabel,
          colorClass: meta.colorClass,
          value: valText,
        });
      }
    }
  }

  // Fallback nếu device.sensors chưa tải được hoặc rỗng
  if (sensorCards.length === 0) {
    let temp = null;
    let hum = null;
    if (currentReadings && typeof currentReadings === 'object') {
      for (const key of Object.keys(currentReadings)) {
        const val = currentReadings[key];
        if (val && typeof val === 'object') {
          if (val.temp !== undefined) temp = val.temp;
          if (val.temperature !== undefined) temp = val.temperature;
          if (val.hum !== undefined) hum = val.hum;
          if (val.humidity !== undefined) hum = val.humidity;
        } else if (typeof val === 'number') {
          if (key === 'temp' || key === 'temperature') temp = val;
          if (key === 'hum' || key === 'humidity') hum = val;
        }
      }
    }
    sensorCards.push({
      id: 'temp',
      icon: '🌡️',
      label: 'Nhiệt Độ',
      colorClass: 'text-amber',
      value: temp !== null ? `${temp} °C` : '--',
    });
    sensorCards.push({
      id: 'hum',
      icon: '💧',
      label: 'Độ Ẩm',
      colorClass: 'text-blue',
      value: hum !== null ? `${hum} %` : '--',
    });
  }

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
          </div>
        </div>
      </div>
    </div>
  );
}
