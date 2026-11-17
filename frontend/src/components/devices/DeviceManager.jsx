import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import {
  apiPingDevice,
  apiRebootDevice,
  apiApproveRegistration,
  apiRejectRegistration,
} from '../../services/api';
import DeviceList from './DeviceList';
import PendingRegistrations from './PendingRegistrations';

export default function DeviceManager({
  devices,
  registrations,
  onRefreshDevices,
  onRefreshRegistrations,
  onNotify,
}) {
  const { canManage, canControl } = useAuth();
  const [activeSubTab, setActiveSubTab] = useState('devices');

  const handlePing = async (deviceId) => {
    try {
      await apiPingDevice(deviceId);
      onNotify(`Đã gửi Ping tới ${deviceId}`);
    } catch (err) {
      onNotify('Lỗi: ' + err.message, 'error');
    }
  };

  const handleReboot = async (deviceId) => {
    if (!canControl) {
      onNotify('Không có quyền khởi động lại thiết bị.', 'error');
      return;
    }
    try {
      await apiRebootDevice(deviceId);
      onNotify(`Đã gửi lệnh khởi động lại ${deviceId}`);
    } catch (err) {
      onNotify('Lỗi: ' + err.message, 'error');
    }
  };

  const handleApprove = async (hwId) => {
    if (!canManage) {
      onNotify('Chỉ Quản trị viên mới có quyền duyệt thiết bị.', 'error');
      return;
    }
    try {
      await apiApproveRegistration(hwId);
      onNotify(`Đã phê duyệt ${hwId}`);
      onRefreshRegistrations();
      onRefreshDevices();
    } catch (err) {
      onNotify('Lỗi: ' + err.message, 'error');
    }
  };

  const handleReject = async (hwId) => {
    if (!canManage) {
      onNotify('Chỉ Quản trị viên mới có quyền từ chối thiết bị.', 'error');
      return;
    }
    try {
      await apiRejectRegistration(hwId, 'Admin rejected');
      onNotify(`Đã từ chối ${hwId}`);
      onRefreshRegistrations();
    } catch (err) {
      onNotify('Lỗi: ' + err.message, 'error');
    }
  };

  return (
    <div>
      <div className="subtabs-bar">
        <button
          className={`subtab-btn ${activeSubTab === 'devices' ? 'active' : ''}`}
          onClick={() => setActiveSubTab('devices')}
        >
          Thiết Bị ({devices.length})
        </button>
        <button
          className={`subtab-btn ${activeSubTab === 'registrations' ? 'active' : ''}`}
          onClick={() => setActiveSubTab('registrations')}
        >
          Chờ Cấp Phép ({registrations.length})
        </button>
      </div>

      {activeSubTab === 'devices' ? (
        <DeviceList
          devices={devices}
          onRefresh={onRefreshDevices}
          onPing={handlePing}
          onReboot={handleReboot}
        />
      ) : (
        <PendingRegistrations
          registrations={registrations}
          onRefresh={onRefreshRegistrations}
          onApprove={handleApprove}
          onReject={handleReject}
        />
      )}
    </div>
  );
}
