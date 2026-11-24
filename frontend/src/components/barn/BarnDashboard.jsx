import React, { useState, useEffect, useMemo } from 'react';
import { useAuth } from '../../context/AuthContext';
import {
  apiGetDeviceLatestTelemetry,
  apiGetDeviceTelemetrySeries,
  apiGetBarnCommands,
  apiSendDeviceCommand,
  subscribeToEvents,
} from '../../services/api';
import ClimateCard from './ClimateCard';
import TelemetryChart from './TelemetryChart';
import EmptyState from '../common/EmptyState';
import { resolveBarnSelection } from './barnSelectionUtils';

const SELECTION_STORAGE_KEY = 'barnDashboard.selection';
const EMPTY_LIST = [];

function loadSelection() {
  try {
    const saved = JSON.parse(localStorage.getItem(SELECTION_STORAGE_KEY));
    return saved && typeof saved === 'object' && !Array.isArray(saved) ? saved : {};
  } catch {
    return {};
  }
}

function saveSelection(selection) {
  try {
    localStorage.setItem(SELECTION_STORAGE_KEY, JSON.stringify(selection));
  } catch {
    // Storage may be disabled or full; selection still works in memory.
  }
}

// Short ranges refresh at the device's telemetry pace (5 s) for live demos; long
// ranges aggregate days of rows per request, so refresh them less often.
const seriesRefreshMs = (rangeHours) => (rangeHours <= 6 ? 5_000 : 30_000);

export default function BarnDashboard({ barns = EMPTY_LIST, devices = EMPTY_LIST, onNotify }) {
  const { canControl } = useAuth();
  const [selection, setSelection] = useState(loadSelection);
  const {
    zones, zoneBarns, barnDevices, sensors, currentBarn, currentDev, currentSensor,
    showSensorTabs, breadcrumb,
    selection: resolvedSelection,
  } = useMemo(() => resolveBarnSelection(barns, devices, selection), [barns, devices, selection]);
  const {
    zone: selectedZone, barnId: selectedBarnId, deviceId: selectedDeviceId, sensorName: selectedSensorName,
  } = resolvedSelection;
  const isOnline = Boolean(currentDev?.online);

  const [latestTelemetry, setLatestTelemetry] = useState(null);
  const currentReadings = latestTelemetry?.deviceId === selectedDeviceId ? latestTelemetry.values : {};
  const [series, setSeries] = useState(null);
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [seriesError, setSeriesError] = useState('');
  const [rangeHours, setRangeHours] = useState(24);
  const [history, setHistory] = useState(null);
  const commandHistory = history?.deviceId === selectedDeviceId ? history.commands : [];
  const [historyRevision, setHistoryRevision] = useState(0);
  const refreshCommandHistory = () => setHistoryRevision((revision) => revision + 1);
  const [feedSeconds, setFeedSeconds] = useState(3);
  const [feeding, setFeeding] = useState(false);
  const [fanMode, setFanMode] = useState(null); // AUTO / MANUAL, from command results

  const handleSelectionChange = (next) => {
    const validSelection = resolveBarnSelection(barns, devices, next).selection;
    setSelection(validSelection);
    saveSelection(validSelection);
  };

  useEffect(() => {
    // Keep the saved path while the parent's initial device list is loading.
    if (!selectedDeviceId) return;
    const next = { zone: selectedZone, barnId: selectedBarnId, deviceId: selectedDeviceId, sensorName: selectedSensorName };
    setSelection((previous) => Object.keys(next).every((key) => previous[key] === next[key]) ? previous : next);
    saveSelection(next);
  }, [selectedZone, selectedBarnId, selectedDeviceId, selectedSensorName]);

  useEffect(() => {
    setHistory(null);
    if (!selectedBarnId || !selectedDeviceId) return;
    let active = true;
    apiGetBarnCommands(selectedBarnId).then((commands) => {
      if (active) setHistory({
        deviceId: selectedDeviceId,
        commands: commands.filter((command) => command.device_id === selectedDeviceId),
      });
    }).catch(() => {
      // Bỏ qua lỗi tải lịch sử lệnh
    });
    return () => { active = false; };
  }, [selectedBarnId, selectedDeviceId, historyRevision]);

  useEffect(() => {
    setLatestTelemetry(null);
    setFanMode(null);
    if (!selectedDeviceId) return;

    let isMounted = true;

    // Tải dữ liệu lưu trữ gần nhất từ database (KHÔNG bắn lệnh MQTT read xuống ESP32)
    const loadInitialTelemetry = async () => {
      try {
        const latest = await apiGetDeviceLatestTelemetry(selectedDeviceId).catch(() => null);
        if (!isMounted) return;

        const vals = latest?.readings?.values || latest?.readings || {};
        setLatestTelemetry({ deviceId: selectedDeviceId, values: vals });
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
        setLatestTelemetry({ deviceId: selectedDeviceId, values: vals });
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

      setFanMode('MANUAL');
      onNotify(`Đã ${isOn ? 'bật' : 'tắt'} quạt (chỉnh tay 30 phút, sau đó tự động lại)`);
      refreshCommandHistory();
    } catch (err) {
      onNotify(err.message, 'error');
    }
  };

  // Firmware `mode_set`: AUTO follows temperature (on ≥ 32 °C, off ≤ 30 °C).
  const handleFanAuto = async () => {
    if (!canControl || !isOnline || !selectedDeviceId) {
      onNotify('Thiết bị đang ngoại tuyến hoặc tài khoản không có quyền điều khiển.', 'error');
      return;
    }
    try {
      const result = await apiSendDeviceCommand(selectedDeviceId, 'mode_set', { mode: 'auto' });
      setFanMode(result?.mode || 'AUTO');
      onNotify(`Quạt chuyển sang tự động theo nhiệt độ (hiện ${result?.fan_on ? 'đang bật' : 'đang tắt'})`);
      refreshCommandHistory();
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
      const count = result?.feed_count;
      onNotify(`Đã cho ăn ${feedSeconds} giây${count ? ` (lần ${count} hôm nay)` : ''}`);
    } catch (err) {
      onNotify(FEED_ERRORS[err.code] || err.message, 'error');
    } finally {
      setFeeding(false);
      refreshCommandHistory();
    }
  };

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <div>
            <h2 className="card-title">Môi Trường Chuồng Trại</h2>
            {selectedZone && (
              <p className="card-desc" aria-label="Vị trí cảm biến">
                {breadcrumb}
              </p>
            )}
          </div>
        </div>

        <div className="chart-controls" aria-label="Chọn khu, chuồng và thiết bị">
          <label className="chart-control">
            <span>Khu</span>
            <select
              value={selectedZone}
              onChange={(event) => handleSelectionChange({ zone: event.target.value })}
              className="select-control"
              disabled={zones.length === 0}
            >
              {zones.length === 0 && <option value="">Chưa có khu</option>}
              {zones.map((zone) => <option key={zone.name} value={zone.name}>{zone.name}</option>)}
            </select>
          </label>
          <label className="chart-control">
            <span>Chuồng</span>
            <select
              value={selectedBarnId}
              onChange={(event) => handleSelectionChange({ zone: selectedZone, barnId: event.target.value })}
              className="select-control"
              disabled={zoneBarns.length === 0}
            >
              {zoneBarns.length === 0 && <option value="">Chưa có chuồng</option>}
              {zoneBarns.map((barn) => <option key={barn.id} value={barn.id}>{barn.name || barn.id}</option>)}
            </select>
          </label>
          {barnDevices.length > 1 ? (
            <label className="chart-control">
              <span>Thiết bị</span>
              <select
                value={selectedDeviceId}
                onChange={(event) => handleSelectionChange({
                  zone: selectedZone, barnId: selectedBarnId, deviceId: event.target.value,
                })}
                className="select-control"
              >
                {barnDevices.map((device) => (
                  <option key={device.device_id} value={device.device_id}>
                    {device.name || device.device_id} ({device.online ? 'Online' : 'Offline'})
                  </option>
                ))}
              </select>
            </label>
          ) : currentDev ? (
            <div className="chart-control">
              <span>Thiết bị</span>
              <strong>{currentDev.name || currentDev.device_id}</strong>
            </div>
          ) : null}
        </div>

        {!currentBarn ? (
          <EmptyState icon="🏠" title="Chưa có chuồng" message="Tạo chuồng để theo dõi môi trường theo khu." />
        ) : !currentDev ? (
          <EmptyState
            icon="🔌"
            title="Chuồng chưa có thiết bị"
            message={`Gán thiết bị vào ${currentBarn.name || selectedBarnId} để theo dõi môi trường và điều khiển.`}
          />
        ) : (
          <>
            {showSensorTabs && (
              <div className="subtabs-bar" role="group" aria-label="Cảm biến của thiết bị" style={{ flexWrap: 'wrap' }}>
                {sensors.map((sensor) => (
                  <button
                    key={sensor.name}
                    type="button"
                    className={`subtab-btn ${selectedSensorName === sensor.name ? 'active' : ''}`}
                    aria-pressed={selectedSensorName === sensor.name}
                    onClick={() => handleSelectionChange({ ...resolvedSelection, sensorName: sensor.name })}
                  >
                    {sensor.name}
                  </button>
                ))}
              </div>
            )}
            {!currentSensor && (
              <EmptyState icon="🌡️" title="Thiết bị chưa có cảm biến" message="Chưa có cảm biến để hiển thị số đo và biểu đồ." />
            )}
            <ClimateCard
              sensor={currentSensor}
              currentReadings={currentReadings}
              isOnline={isOnline}
              onRelayToggle={handleRelayToggle}
              onFanAuto={handleFanAuto}
              fanMode={fanMode}
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

            {currentSensor && (
              <>
                <h3 className="section-subtitle">Biểu Đồ Theo Thời Gian</h3>
                <TelemetryChart
                  key={selectedDeviceId}
                  series={series?.device_id === selectedDeviceId ? series : null}
                  sensor={selectedSensorName}
                  rangeHours={rangeHours}
                  onRangeChange={setRangeHours}
                  loading={seriesLoading}
                  error={seriesError}
                  refreshSeconds={seriesRefreshMs(rangeHours) / 1000}
                />
              </>
            )}

            <div style={{ marginTop: '28px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <h3 className="section-subtitle" style={{ margin: 0 }}>Lịch Sử Lệnh Thiết Bị</h3>
                {selectedBarnId && (
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={refreshCommandHistory}
                  >
                    Làm mới lệnh
                  </button>
                )}
              </div>

              {commandHistory.length === 0 ? (
                <p className="empty-state-text">Chưa có lệnh nào được phát xuống thiết bị này.</p>
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
