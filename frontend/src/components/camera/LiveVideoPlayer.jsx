import React from 'react';

export default function LiveVideoPlayer({
  cameraStatus,
  onToggleCamera,
}) {
  const getStateBadgeClass = (state) => {
    switch (state) {
      case 'walking':
        return 'badge-walking';
      case 'resting':
        return 'badge-resting';
      case 'motionless':
        return 'badge-motionless';
      default:
        return 'badge-absent';
    }
  };

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h2 className="card-title">Camera Giám Sát</h2>
        </div>
        <button
          className={`btn ${cameraStatus.is_running ? 'btn-danger' : 'btn-success'}`}
          onClick={onToggleCamera}
        >
          {cameraStatus.is_running ? 'Tắt Camera' : 'Bật Camera'}
        </button>
      </div>

      <div className="video-wrapper">
        {cameraStatus.is_running ? (
          <img
            src="/camera/feed"
            alt="Live Camera Feed"
            className="video-element"
          />
        ) : (
          <div className="video-placeholder">
            <div className="placeholder-icon">📷</div>
            <p>Camera hiện đang tắt</p>
          </div>
        )}

        {cameraStatus.is_running && (
          <div className={`video-overlay-badge ${getStateBadgeClass(cameraStatus.state)}`}>
            <span>●</span>
            <span>{cameraStatus.label || 'Đang quét...'}</span>
          </div>
        )}
      </div>

      {cameraStatus.state === 'motionless' && (
        <div className="alert-banner">
          <div className="alert-banner-content">
            <span className="alert-icon">⚠️</span>
            <div>
              <strong>Cảnh báo:</strong> Thú cưng nằm bất động liên tục {cameraStatus.still_duration_s?.toFixed(1)}s
            </div>
          </div>
        </div>
      )}

      <div className="metrics-row">
        <div className="metric-box">
          <div className="metric-label">Hành vi</div>
          <div className="metric-status-val">{cameraStatus.label}</div>
        </div>
        <div className="metric-box">
          <div className="metric-label">Vận tốc</div>
          <div className="metric-value">
            {cameraStatus.speed_px_s || 0} <span className="metric-unit">px/s</span>
          </div>
        </div>
        <div className="metric-box">
          <div className="metric-label">Đứng yên</div>
          <div className="metric-value">
            {cameraStatus.still_duration_s?.toFixed(1) || 0} <span className="metric-unit">s</span>
          </div>
        </div>
        <div className="metric-box">
          <div className="metric-label">FPS</div>
          <div className="metric-value">{cameraStatus.fps || 0}</div>
        </div>
      </div>
    </div>
  );
}
