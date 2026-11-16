import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';

export default function Login() {
  const { login, loading } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = async (e, customUser = null, customPass = null) => {
    if (e?.preventDefault) e.preventDefault();
    setError('');

    const u = customUser || username;
    const p = customPass || password;

    if (!u || !p) {
      setError('Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu.');
      return;
    }

    try {
      await login(u, p);
    } catch (err) {
      setError(err.message || 'Tên đăng nhập hoặc mật khẩu không chính xác.');
    }
  };

  return (
    <div className="login-screen-wrapper">
      <div className="login-card">
        <div className="login-brand-icon">🐾</div>
        <h1 className="login-title">Smart Barn</h1>

        {error && (
          <div className="login-error-banner">
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="login-input-group">
            <label className="login-label">Tên đăng nhập</label>
            <input
              type="text"
              className="login-input"
              placeholder="Tên đăng nhập"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              disabled={loading}
            />
          </div>

          <div className="login-input-group">
            <label className="login-label">Mật khẩu</label>
            <input
              type="password"
              className="login-input"
              placeholder="Mật khẩu"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={loading}
            />
          </div>

          <button type="submit" className="login-submit-btn" disabled={loading}>
            {loading ? 'Đang đăng nhập...' : 'Đăng Nhập'}
          </button>
        </form>

        <div className="demo-accounts-box">
          <div className="demo-btn-row">
            <button
              type="button"
              className="demo-pill-btn role-admin"
              onClick={() => handleSubmit(null, 'admin', 'Admin@123456')}
            >
              Admin
            </button>
            <button
              type="button"
              className="demo-pill-btn role-operator"
              onClick={() => handleSubmit(null, 'operator', 'Operator@123')}
            >
              Operator
            </button>
            <button
              type="button"
              className="demo-pill-btn role-viewer"
              onClick={() => handleSubmit(null, 'viewer', 'Viewer@123456')}
            >
              Viewer
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
