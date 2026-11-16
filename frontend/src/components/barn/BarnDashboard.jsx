import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import {
  apiGetBarns,
  apiGetDeviceReadings,
  apiGetDeviceTelemetry,
  apiSendBarnCommand,
  apiSendDeviceCommand,
} from '../../services/api';
import ClimateCard from './ClimateCard';
import TelemetryChart from './TelemetryChart';
import EmptyState from '../common/EmptyState';

export default function BarnDashboard({ devices, onNotify }) {
  const { canControl } = useAuth();
  const [barns, setBarns] = useState([]);
  const [selectedBarnId, setSelectedBarnId] = useState('');
  const [selectedDeviceId, setSelectedDeviceId] = useState('');

  const [currentReadings, setCurrentReadings] = useState({ temp: null, hum: null });
  const [chartData, setChartData] = useState([]);

  useEffect(() => {
    const fetchBarns = async () => {
      try {
        const res = await apiGetBarns();
        setBarns(res);
        if (res.length > 0 && !selectedBarnId) {
          setSelectedBarnId(res[0].id);
        }
      } catch {
        // Bỏ qua nếu chưa có dữ liệu chuồng
      }
    };
    fetchBarns();
  }, []);

  useEffect(() => {
    if (devices.length > 0 && !selectedDeviceId) {
      setSelectedDeviceId(devices[0].device_id);
    }
  }, [devices]);

  useEffect(() => {
    if (!selectedDeviceId) return;

    let isMounted = true;
    const fetchTelemetry = async () => {
      try {
        const readings = await apiGetDeviceReadings(selectedDeviceId);
        if (!isMounted) return;

        let temp = null;
        let hum = null;
        for (const key of Object.keys(readings)) {
          const s = readings[key];
          if (s.temp !== undefined) temp = s.temp;
          if (s.temperature !== undefined) temp = s.temperature;
          if (s.hum !== undefined) hum = s.hum;
          if (s.humidity !== undefined) hum = s.humidity;
        }
        setCurrentReadings({ temp, hum });

        const history = await apiGetDeviceTelemetry(selectedDeviceId, 12);
        if (!isMounted) return;

        const mapped = history
          .map((item) => {
            const dt = new Date(item.received_at);
            const timeStr = `${dt.getHours().toString().padStart(2, '0')}:${dt.getMinutes().toString().padStart(2, '0')}`;
            let t = null;
            let h = null;
            const vals = item.readings?.values || {};
            for (const sName of Object.keys(vals)) {
              if (vals[sName].temp !== undefined) t = vals[sName].temp;
              if (vals[sName].temperature !== undefined) t = vals[sName].temperature;
              if (vals[sName].hum !== undefined) h = vals[sName].hum;
              if (vals[sName].humidity !== undefined) h = vals[sName].humidity;
            }
            return { time: timeStr, temp: t, hum: h };
          })
          .filter((pt) => pt.temp !== null || pt.hum !== null)
          .reverse();

        setChartData(mapped);
      } catch (err) {
        console.error('Lỗi tải telemetry:', err);
      }
    };

    fetchTelemetry();
    const interval = setInterval(fetchTelemetry, 4000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [selectedDeviceId]);

  const handleRelayToggle = async (channel, state) => {
    if (!canControl) {
      onNotify('Tài khoản không có quyền điều khiển thiết bị.', 'error');
      return;
    }

    try {
      if (selectedBarnId) {
        await apiSendBarnCommand(selectedBarnId, 'relay_set', { channel, state });
      } else if (selectedDeviceId) {
        await apiSendDeviceCommand(selectedDeviceId, 'relay_set', { channel, state });
      }
      onNotify(`Đã gửi lệnh bật/tắt quạt (${state})`);
    } catch (err) {
      onNotify('Lỗi gửi lệnh: ' + err.message, 'error');
    }
  };

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <div>
            <h2 className="card-title">Môi Trường Chuồng Trại</h2>
          </div>

          <div className="filters-row">
            {barns.length > 0 && (
              <select
                value={selectedBarnId}
                onChange={(e) => setSelectedBarnId(e.target.value)}
                className="select-control"
              >
                {barns.map((b) => (
                  <option key={b.id} value={b.id}>
                    Khu: {b.name}
                  </option>
                ))}
              </select>
            )}

            {devices.length > 0 && (
              <select
                value={selectedDeviceId}
                onChange={(e) => setSelectedDeviceId(e.target.value)}
                className="select-control"
              >
                {devices.map((d) => (
                  <option key={d.device_id} value={d.device_id}>
                    {d.name || d.device_id} ({d.online ? 'Online' : 'Offline'})
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>

        {devices.length === 0 ? (
          <EmptyState
            icon="🔌"
            title="Chưa có thiết bị kết nối"
          />
        ) : (
          <>
            <ClimateCard
              currentReadings={currentReadings}
              onRelayToggle={handleRelayToggle}
            />

            <h3 className="section-subtitle">Biểu Đồ Theo Thời Gian</h3>
            <TelemetryChart chartData={chartData} />
          </>
        )}
      </div>
    </div>
  );
}
