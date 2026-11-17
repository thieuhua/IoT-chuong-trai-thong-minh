/**
 * API Service Layer - Quản lý các yêu cầu HTTP tới FastAPI Backend
 * Tự động gắn Bearer Token, xử lý refresh token và mã lỗi an toàn.
 */

const TOKEN_KEY = 'smartbarn_access_token';
const REFRESH_KEY = 'smartbarn_refresh_token';
const USER_KEY = 'smartbarn_user';

export function getStoredToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredRefreshToken() {
  return localStorage.getItem(REFRESH_KEY);
}

export function getStoredUser() {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveSession(token, refreshToken, user) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  if (refreshToken) localStorage.setItem(REFRESH_KEY, refreshToken);
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
}

let refreshPromise = null;

async function refreshAccessToken() {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const refreshToken = getStoredRefreshToken();
      if (!refreshToken) {
        throw new Error('Phiên đăng nhập đã hết hạn.');
      }

      const response = await fetch('/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (!response.ok) {
        throw new Error('Không thể làm mới phiên làm việc.');
      }

      const data = await response.json();
      if (!data.access_token) {
        throw new Error('Phản hồi làm mới phiên không hợp lệ.');
      }

      saveSession(data.access_token, data.refresh_token, data.user);
      return data.access_token;
    })().finally(() => {
      refreshPromise = null;
    });
  }

  return refreshPromise;
}

function notifyAuthExpired() {
  clearSession();
  window.dispatchEvent(new CustomEvent('auth:expired'));
}

/**
 * Fetch wrapper chuẩn bảo mật với tự động refresh token
 */
export async function request(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const token = getStoredToken();
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const config = {
    ...options,
    headers,
  };

  let response = await fetch(url, config);

  // Nếu gặp lỗi 401 và không phải là request đăng nhập/refresh: thử refresh token
  if (response.status === 401 && !url.includes('/auth/login') && !url.includes('/auth/refresh')) {
    let retryToken;
    try {
      retryToken = await refreshAccessToken();
    } catch (error) {
      notifyAuthExpired();
      throw error;
    }

    headers.set('Authorization', `Bearer ${retryToken}`);
    response = await fetch(url, { ...config, headers });
  }

  if (!response.ok) {
    let errorDetail = 'Lỗi không xác định';
    try {
      const errData = await response.json();
      errorDetail = errData.detail || errData.message || JSON.stringify(errData);
    } catch {
      errorDetail = response.statusText || `Lỗi HTTP ${response.status}`;
    }
    throw new Error(errorDetail);
  }

  // Nếu phản hồi là JSON
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return response.json();
  }

  return response.text();
}

// ==========================================
// 1. AUTHENTICATION & PROFILE
// ==========================================
export async function apiLogin(username, password) {
  const data = await request('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
  saveSession(data.access_token, data.refresh_token, data.user);
  return data;
}

export async function apiLogout() {
  const refreshToken = getStoredRefreshToken();
  try {
    if (refreshToken) {
      await request('/auth/logout', {
        method: 'POST',
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    }
  } catch {
    // Vẫn dọn dẹp session ở client
  } finally {
    clearSession();
  }
}

export async function apiChangePassword(old_password, new_password) {
  return request('/me/password', {
    method: 'PUT',
    body: JSON.stringify({ old_password, new_password }),
  });
}

// ==========================================
// 2. SYSTEM HEALTH
// ==========================================
export async function apiGetHealth() {
  return request('/health');
}

// ==========================================
// 3. BARNS (KHU CHUỒNG TRẠI)
// ==========================================
export async function apiGetBarns() {
  const res = await request('/barns');
  return Array.isArray(res) ? res : [];
}

export async function apiCreateBarn(name, zone = null, animal_type = null) {
  return request('/barns', {
    method: 'POST',
    body: JSON.stringify({ name, zone, animal_type }),
  });
}

export async function apiSendBarnCommand(barnId, action, params = null) {
  return request(`/barns/${barnId}/commands`, {
    method: 'POST',
    body: JSON.stringify({ action, params }),
  });
}

export async function apiGetBarnCommands(barnId) {
  const res = await request(`/barns/${barnId}/commands`);
  return Array.isArray(res) ? res : [];
}

// ==========================================
// 4. DEVICES & TELEMETRY
// ==========================================
export async function apiGetDevices(onlineOnly = null) {
  const query = onlineOnly !== null ? `?online=${onlineOnly}` : '';
  const res = await request(`/devices${query}`);
  return Array.isArray(res) ? res : [];
}

export async function apiGetDevice(deviceId) {
  return request(`/devices/${deviceId}`);
}

export async function apiGetDeviceReadings(deviceId) {
  const res = await request(`/devices/${deviceId}/readings`);
  return {
    values: res?.values || {},
    errors: res?.errors || {},
  };
}

export async function apiGetDeviceLatestTelemetry(deviceId) {
  return request(`/devices/${deviceId}/telemetry/latest`);
}

export async function apiGetDeviceTelemetry(deviceId, limit = 20) {
  const res = await request(`/devices/${deviceId}/telemetry?limit=${limit}`);
  return Array.isArray(res) ? res : [];
}

export async function apiSendDeviceCommand(deviceId, name, args = null, timeout_s = 10) {
  return request(`/devices/${deviceId}/commands`, {
    method: 'POST',
    body: JSON.stringify({ name, args, timeout_s }),
  });
}

export async function apiPingDevice(deviceId) {
  return request(`/devices/${deviceId}/ping`, { method: 'POST' });
}

export async function apiRebootDevice(deviceId) {
  return request(`/devices/${deviceId}/reboot`, { method: 'POST' });
}

export async function apiSetDeviceInterval(deviceId, seconds) {
  return request(`/devices/${deviceId}/interval`, {
    method: 'PUT',
    body: JSON.stringify({ seconds }),
  });
}

// ==========================================
// 5. REGISTRATIONS (PROVISIONING)
// ==========================================
export async function apiGetRegistrations(status = 'pending') {
  const res = await request(`/registrations?status=${status}`);
  return Array.isArray(res) ? res : [];
}

export async function apiApproveRegistration(hwId, deviceId = null, name = '') {
  return request(`/registrations/${hwId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ device_id: deviceId, name }),
  });
}

export async function apiRejectRegistration(hwId, reason = '') {
  return request(`/registrations/${hwId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  });
}

// ==========================================
// 6. ALERTS (CẢNH BÁO)
// ==========================================
export async function apiGetAlerts(status = null) {
  const query = status ? `?status=${status}` : '';
  const res = await request(`/alerts${query}`);
  return Array.isArray(res) ? res : [];
}

export async function apiAcknowledgeAlert(alertId, note = '') {
  return request(`/alerts/${alertId}/ack`, {
    method: 'POST',
    body: JSON.stringify({ note }),
  });
}

export async function apiCloseAlert(alertId, note = '') {
  return request(`/alerts/${alertId}/close`, {
    method: 'POST',
    body: JSON.stringify({ note }),
  });
}

// ==========================================
// 7. USER MANAGEMENT & AUDIT LOGS (ADMIN)
// ==========================================
export async function apiGetUsers() {
  const res = await request('/users');
  return Array.isArray(res) ? res : [];
}

export async function apiCreateUser(username, password, full_name = '', role = 'Viewer') {
  return request('/users', {
    method: 'POST',
    body: JSON.stringify({ username, password, full_name, role }),
  });
}

export async function apiUpdateUser(userId, data) {
  return request(`/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function apiGetAuditLogs() {
  const res = await request('/audit-logs');
  return Array.isArray(res) ? res : [];
}

// ==========================================
// 8. CAMERA AI VISION
// ==========================================
export async function apiGetCameraStatus() {
  return request('/camera/status');
}

export async function apiStartCamera() {
  return request('/camera/start', { method: 'POST' });
}

export async function apiStopCamera() {
  return request('/camera/stop', { method: 'POST' });
}

export async function apiConfigCamera(config) {
  return request('/camera/config', {
    method: 'POST',
    body: JSON.stringify(config),
  });
}
