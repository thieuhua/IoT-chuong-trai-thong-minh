import React from 'react';
import { useAuth } from '../../context/AuthContext';
import { RoleBadge } from '../common/StatusBadge';

export default function Navbar({
  viewMode,
  setViewMode,
  brokerOnline,
}) {
  const { user, logout } = useAuth();

  return (
    <header className="app-header">
      <div className="brand">
        <div className="brand-icon">🐾</div>
        <h1 className="brand-title">Smart Barn</h1>
      </div>

      <div className="header-actions">
        <div className="view-mode-toggle">
          <button
            className={`view-btn ${viewMode === 'desktop' ? 'active' : ''}`}
            onClick={() => setViewMode('desktop')}
          >
            Dashboard
          </button>
          <button
            className={`view-btn ${viewMode === 'mobile' ? 'active' : ''}`}
            onClick={() => setViewMode('mobile')}
          >
            Mobile App
          </button>
        </div>

        <div className="status-indicator">
          <span className={`status-dot ${brokerOnline ? 'dot-online' : 'dot-offline'}`} />
          <span>MQTT</span>
        </div>

        <div className="user-profile-badge">
          <span className="user-name">{user?.full_name || user?.username}</span>
          <RoleBadge role={user?.role} />
          <button className="btn-logout" onClick={logout} title="Đăng xuất">
            Thoát
          </button>
        </div>
      </div>
    </header>
  );
}
