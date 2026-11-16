import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { apiSendDeviceCommand } from '../../services/api';
import { RoleBadge } from '../common/StatusBadge';

export default function MobileAppView({
  devices,
  alerts,
  onNotify,
}) {
  const { user, logout, canControl } = useAuth();
  const [mobileTab, setMobileTab] = useState('camera');
  const [servoAngle, setServoAngle] = useState(90);
  const [isFeeding, setIsFeeding] = useState(false);

  const handleFeed = async () => {
    if (!canControl) {
      onNotify('Không có quyền điều khiển.', 'error');
      return;
    }
    if (!devices || devices.length === 0) {
      onNotify('Chưa có thiết bị kết nối.', 'error');
      return;
    }

    const target = devices[0].device_id;
    setIsFeeding(true);
    try {
      await apiSendDeviceCommand(target, 'servo_set', { angle: Number(servoAngle) });
      onNotify(`Đã mở máng ăn (${servoAngle}°)`);
    } catch (err) {
      onNotify('Lỗi: ' + err.message, 'error');
    } finally {
      setIsFeeding(false);
    }
  };

  return (
    <div className="mobile-view-wrapper">
      <div className="mobile-phone">
        <div className="phone-status-bar">
          <span>09:41</span>
          <div className="phone-notch" />
          <span>5G 🔋 100%</span>
        </div>

        <div className="phone-content">
          <div className="phone-app-header">
            <div>
              <div className="phone-title">SmartBarn</div>
            </div>
            <RoleBadge role={user?.role} />
          </div>

          {mobileTab === 'camera' && (
            <div className="mobile-tab-pane">
              <div className="mobile-video-box">
                <img
                  src="/camera/feed"
                  alt="Camera AI live stream"
                  className="video-element"
                />
                <div className="video-overlay-badge badge-walking">
                  <span>●</span>
                  <span>AI</span>
                </div>
              </div>

              <div className="mobile-action-card">
                <div className="input-inline">
                  <label>Góc mở:</label>
                  <input
                    type="number"
                    value={servoAngle}
                    onChange={(e) => setServoAngle(e.target.value)}
                    className="input-number"
                  />
                  <span>độ</span>
                </div>
                <button
                  className="btn btn-success btn-full"
                  onClick={handleFeed}
                  disabled={isFeeding || !canControl}
                >
                  {isFeeding ? 'Đang mở...' : 'Cho Ăn'}
                </button>
              </div>

              <div className="mobile-quick-stats">
                <div className="quick-stat-box">
                  <span className="stat-label">Online</span>
                  <span className="stat-val text-green">{devices.filter((d) => d.online).length}</span>
                </div>
                <div className="quick-stat-box">
                  <span className="stat-label">Cảnh báo</span>
                  <span className="stat-val text-amber">{alerts.length}</span>
                </div>
              </div>
            </div>
          )}

          {mobileTab === 'sensors' && (
            <div className="mobile-tab-pane">
              <h3 className="section-subtitle">Cảm Biến</h3>
              {devices.length === 0 ? (
                <p className="empty-state-text">Chưa có thiết bị kết nối.</p>
              ) : (
                devices.map((d) => (
                  <div key={d.device_id} className="mobile-device-card">
                    <div className="device-card-header">
                      <strong>{d.name || d.device_id}</strong>
                      <span className={`status-dot ${d.online ? 'dot-online' : 'dot-offline'}`} />
                    </div>
                    <div className="device-card-body">
                      <div>Mã: <code>{d.device_id}</code></div>
                      <div>Firmware: {d.fw || 'v1.0.0'}</div>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

          {mobileTab === 'alerts' && (
            <div className="mobile-tab-pane">
              <h3 className="section-subtitle">Cảnh Báo ({alerts.length})</h3>
              {alerts.length === 0 ? (
                <p className="empty-state-text">Không có cảnh báo nào.</p>
              ) : (
                alerts.map((a) => (
                  <div key={a.id} className="mobile-alert-card">
                    <div className="alert-card-title">{a.severity === 'critical' ? '🔴' : '🟡'} {a.device_id || 'Hệ thống'}</div>
                    <div className="alert-card-note">{a.note || 'Cảnh báo vi khí hậu'}</div>
                    <small className="alert-card-time">{new Date(a.raised_at).toLocaleTimeString()}</small>
                  </div>
                ))
              )}
            </div>
          )}

          {mobileTab === 'account' && (
            <div className="mobile-tab-pane">
              <div className="mobile-user-card">
                <div className="user-card-name">{user?.full_name || user?.username}</div>
                <div className="user-card-sub">Tài khoản: <strong>{user?.username}</strong></div>
                <div className="user-card-sub">Vai trò: <RoleBadge role={user?.role} /></div>
                <button className="btn btn-danger btn-full" style={{ marginTop: '16px' }} onClick={logout}>
                  Đăng Xuất
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="phone-bottom-nav">
          <button
            className={`nav-item ${mobileTab === 'camera' ? 'active' : ''}`}
            onClick={() => setMobileTab('camera')}
          >
            <span className="nav-item-icon">📹</span>
            <span>Camera</span>
          </button>
          <button
            className={`nav-item ${mobileTab === 'sensors' ? 'active' : ''}`}
            onClick={() => setMobileTab('sensors')}
          >
            <span className="nav-item-icon">🌡️</span>
            <span>Cảm Biến</span>
          </button>
          <button
            className={`nav-item ${mobileTab === 'alerts' ? 'active' : ''}`}
            onClick={() => setMobileTab('alerts')}
          >
            <span className="nav-item-icon">🔔</span>
            <span>Cảnh Báo</span>
          </button>
          <button
            className={`nav-item ${mobileTab === 'account' ? 'active' : ''}`}
            onClick={() => setMobileTab('account')}
          >
            <span className="nav-item-icon">👤</span>
            <span>Cá Nhân</span>
          </button>
        </div>
      </div>
    </div>
  );
}
