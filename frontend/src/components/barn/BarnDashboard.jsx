import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import {
  apiGetBarns,
  apiGetDeviceLatestTelemetry,
  apiGetDeviceTelemetrySeries,
  apiGetBarnCommands,
  apiSendDeviceCommand,
  subscribeToEvents,
} from '../../services/api';
import ClimateCard from './ClimateCard';
import TelemetryChart from './TelemetryChart';
import EmptyState from '../common/EmptyState';

// Short ranges refresh at the device's telemetry pace (5 s) for live demos; long
// ranges aggregate days of rows per request, so refresh them less often.
const seriesRefreshMs = (rangeHours) => (rangeHours <= 6 ? 5_000 : 30_000);

export default function BarnDashboard({ barns: initialBarns = [], devices = [], onNotify }) {
  const { canControl } = useAuth();
  const [barns, setBarns] = useState(initialBarns);
  const [selectedBarnId, setSelectedBarnId] = useState('');
  const [selectedDeviceId, setSelectedDeviceId] = useState('');

  const [currentReadings, setCurrentReadings] = useState({});
  const [series, setSeries] = useState(null);
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [seriesError, setSeriesError] = useState('');
  const [rangeHours, setRangeHours] = useState(24);
  const [commandHistory, setCommandHistory] = useState([]);
  const [feedSeconds, setFeedSeconds] = useState(3);
  const [feeding, setFeeding] = useState(false);

  useEffect(() => {
    if (initialBarns.length > 0) {
      setBarns(initialBarns);
      if (!selectedBarnId) setSelectedBarnId(initialBarns[0].id);
    } else {
      const fetchBarns = async () => {
        try {
          const res = await apiGetBarns();
          setBarns(res);
          if (res.length > 0 && !selectedBarnId) {
            setSelectedBarnId(res[0].id);
          }
        } catch {
          // Bỏ qua nếu chưa tải được danh sách chuồng
        }
      };
      fetchBarns();
    }
  }, [initialBarns]);

  // Lọc thiết bị theo chuồng đã chọn (nếu có gán chuồng)
  const barnDevices = selectedBarnId
    ? devices.filter((d) => d.barn_id === selectedBarnId || !d.barn_id)
    : devices;

  useEffect(() => {
    if (barnDevices.length > 0) {
      const exists = barnDevices.some((d) => d.device_id === selectedDeviceId);
      if (!exists) {
        setSelectedDeviceId(barnDevices[0].device_id);
      }
    } else if (devices.length > 0 && !selectedDeviceId) {
      setSelectedDeviceId(devices[0].device_id);
    } else if (!devices || devices.length === 0) {
      setSelectedDeviceId('');
    }
  }, [barnDevices, selectedDeviceId, devices]);

  const currentDev = devices.find((d) => d.device_id === selectedDeviceId);
  const isOnline = Boolean(currentDev?.online);

  const fetchCommandHistory = async (barnId) => {
    if (!barnId) return;
    try {
      const cmds = await apiGetBarnCommands(barnId);
      setCommandHistory(cmds);
    } catch {
      // Bỏ qua lỗi tải lịch sử lệnh
    }
  };

  useEffect(() => {
    if (selectedBarnId) {
      fetchCommandHistory(selectedBarnId);
    }
  }, [selectedBarnId]);

  useEffect(() => {
    setCurrentReadings({});
    if (!selectedDeviceId) return;

    let isMounted = true;

    // Tải dữ liệu lưu trữ gần nhất từ database (KHÔNG bắn lệnh MQTT read xuống ESP32)
    const loadInitialTelemetry = async () => {
      try {
        const latest = await apiGetDeviceLatestTelemetry(selectedDeviceId).catch(() => null);
        if (!isMounted) return;

        const vals = latest?.readings?.values || latest?.readings || {};
        setCurrentReadings(vals);
      } catch (err) {
        console.error('Lỗi tải dữ liệu telemetry ban đầu:', err);
      }
    };

    loadInitialTelemetry();

    // Lắng nghe dữ liệu vi khí hậu theo thời gian thực qua Server-Sent Events (SSE)
    const unsubscribeSSE = subscribeToEvents((type, data) => {
      if (!isMounted) return;

      if (type === 'telemetry' && data.device_id === selectedDeviceId) {
        const vals = data.readings?.values || data.readings || {};
        setCurrentReadings(vals);
      }
    });

    return () => {
      isMounted = false;
      unsubscribeSSE();
    };
  }, [selectedDeviceId]);

  useEffect(() => {
    setSeries(null);
    setSeriesError('');
    setSeriesLoading(Boolean(selectedDeviceId));
    if (!selectedDeviceId) return;

    let active = true;
    let pending = false;
    const controller = new AbortController();
    const loadSeries = async () => {
      if (pending) return;
      pending = true;
      const until = new Date();
      const since = new Date(until.getTime() - rangeHours * 3600 * 1000);
      try {
        const result = await apiGetDeviceTelemetrySeries(selectedDeviceId, {
          since: since.toISOString(), until: until.toISOString(), points: 600,
          signal: controller.signal,
        });
        if (active) {
          setSeries(result);
          setSeriesError('');
        }
      } catch (err) {
        if (active) setSeriesError(err.message || 'Không tải được biểu đồ.');
      } finally {
        pending = false;
        if (active) setSeriesLoading(false);
      }
    };

    loadSeries();
    const timer = setInterval(loadSeries, seriesRefreshMs(rangeHours));
    return () => {
      active = false;
      controller.abort();
      clearInterval(timer);
    };
  }, [selectedDeviceId, rangeHours]);

  const handleRelayToggle = async (on) => {
    if (!canControl) {
      onNotify('Lỗi 403 (Từ chối): Tài khoản không có quyền điều khiển thiết bị.', 'error');
      return;
    }

    if (!isOnline) {
      onNotify('Lỗi 409 (Xung đột): Thiết bị đang ngoại tuyến (Offline), không thể gửi lệnh.', 'error');
      return;
    }

    if (!devices || devices.length === 0 || !selectedDeviceId) {
      onNotify('Chưa có thiết bị trong chuồng', 'error');
      return;
    }

    try {
      const isOn = Boolean(on);
      // The fan is the relay named "relay" (GPIO26); boards with several relays need the name.
      const relays = (currentDev?.actuators || []).filter((act) => act.driver === 'relay');
      const fan = relays.find((act) => act.name === 'relay') || relays[0];
      const payload = { name: fan?.name || 'relay', on: isOn };

      if (selectedDeviceId) {
        await apiSendDeviceCommand(selectedDeviceId, 'relay_set', payload);
      }

      onNotify(`Đã gửi lệnh ${isOn ? 'bật' : 'tắt'} quạt`);
      if (selectedBarnId) {
        fetchCommandHistory(selectedBarnId);
      }
    } catch (err) {
      onNotify(err.message, 'error');
    }
  };

  // Firmware `feed`: gate opens (10°), waits `seconds`, closes (90°), then answers.
  const FEED_ERRORS = {
    feed_limit: 'Đã đủ số lần cho ăn trong ngày',
    bad_args: 'Thời gian cho ăn không hợp lệ (1–8 giây)',
    actuator_not_found: 'Thiết bị chưa cấu hình servo máng ăn',
  };

  const handleFeed = async () => {
    if (!canControl) {
      onNotify('Lỗi 403 (Từ chối): Tài khoản không có quyền điều khiển thiết bị.', 'error');
      return;
    }
    if (!isOnline || !selectedDeviceId) {
      onNotify('Thiết bị đang ngoại tuyến, không thể cho ăn.', 'error');
      return;
    }
    setFeeding(true);
    try {
      const result = await apiSendDeviceCommand(selectedDeviceId, 'feed', { seconds: Number(feedSeconds) });
      const count = result?.result?.feed_count;
      onNotify(`Đã cho ăn ${feedSeconds} giây${count ? ` (lần ${count} hôm nay)` : ''}`);
    } catch (err) {
      onNotify(FEED_ERRORS[err.code] || err.message, 'error');
    } finally {
      setFeeding(false);
      if (selectedBarnId) fetchCommandHistory(selectedBarnId);
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

            {devices && devices.length > 0 && (
              <select
                value={selectedDeviceId}
                onChange={(e) => setSelectedDeviceId(e.target.value)}
                className="select-control"
              >
                {barnDevices.map((d) => (
                  <option key={d.device_id} value={d.device_id}>
                    {d.name || d.device_id} ({d.online ? 'Online' : 'Offline'})
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>

        {!devices || devices.length === 0 ? (
          <EmptyState
            icon="🔌"
            title="Chưa có thiết bị kết nối"
          />
        ) : (
          <>
            <ClimateCard
              device={currentDev}
              currentReadings={currentReadings}
              isOnline={isOnline}
              onRelayToggle={handleRelayToggle}
            />

            <div className="card" style={{ marginTop: '16px' }}>
              <div className="card-header">
                <h3 className="section-subtitle" style={{ margin: 0 }}>Máng Ăn</h3>
                <span className="text-muted">Mặc định đóng (90°), mở 10° khi cho ăn</span>
              </div>
              <div className="filters-row">
                <select
                  className="select-control"
                  value={feedSeconds}
                  onChange={(e) => setFeedSeconds(Number(e.target.value))}
                  disabled={feeding}
                >
                  {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => (
                    <option key={n} value={n}>Mở {n} giây</option>
                  ))}
                </select>
                <button
                  className="btn btn-primary"
                  onClick={handleFeed}
                  disabled={!canControl || !isOnline || feeding}
                >
                  {feeding ? 'Đang cho ăn…' : 'Cho ăn'}
                </button>
              </div>
            </div>

            <h3 className="section-subtitle">Biểu Đồ Theo Thời Gian</h3>
            <TelemetryChart
              key={selectedDeviceId}
              series={series?.device_id === selectedDeviceId ? series : null}
              sensors={currentDev?.sensors}
              rangeHours={rangeHours}
              onRangeChange={setRangeHours}
              loading={seriesLoading}
              error={seriesError}
              refreshSeconds={seriesRefreshMs(rangeHours) / 1000}
            />

            <div style={{ marginTop: '28px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <h3 className="section-subtitle" style={{ margin: 0 }}>Lịch Sử Lệnh Chuồng</h3>
                {selectedBarnId && (
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => fetchCommandHistory(selectedBarnId)}
                  >
                    Làm mới lệnh
                  </button>
                )}
              </div>

              {commandHistory.length === 0 ? (
                <p className="empty-state-text">Chưa có lệnh nào được phát xuống chuồng này.</p>
              ) : (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Thời Gian</th>
                      <th>Lệnh</th>
                      <th>Tham Số</th>
                      <th>Thiết Bị</th>
                      <th>Trạng Thái</th>
                    </tr>
                  </thead>
                  <tbody>
                    {commandHistory.slice(0, 5).map((cmd) => (
                      <tr key={cmd.command_id || cmd.id}>
                        <td>{cmd.issued_at ? new Date(cmd.issued_at).toLocaleString() : '--'}</td>
                        <td><span className="log-action-tag">{cmd.action}</span></td>
                        <td><code>{cmd.params ? JSON.stringify(cmd.params) : '--'}</code></td>
                        <td><code>{cmd.device_id || '--'}</code></td>
                        <td>
                          <span className={cmd.status === 'success' ? 'text-green' : cmd.status === 'pending' ? 'text-amber' : ''}>
                            {cmd.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
