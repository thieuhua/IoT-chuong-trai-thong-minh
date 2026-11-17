import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import {
  apiPingDevice,
  apiRebootDevice,
  apiApproveRegistration,
  apiRejectRegistration,
  apiRevokeDevice,
  apiUpdateDevice,
} from '../../services/api';
import DeviceList from './DeviceList';
import PendingRegistrations from './PendingRegistrations';

export default function DeviceManager({
  barns = [],
  devices = [],
  registrations = [],
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
      onNotify(err.message, 'error');
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
      onNotify(err.message, 'error');
    }
  };

  const handleAssignBarn = async (deviceId, barnId) => {
    if (!canManage) {
      onNotify('Chỉ Quản trị viên mới có quyền gán chuồng cho thiết bị.', 'error');
      return;
    }
    try {
      await apiUpdateDevice(deviceId, { barn_id: barnId || null });
      onNotify(`Đã gán thiết bị ${deviceId} vào chuồng`);
      onRefreshDevices();
    } catch (err) {
      onNotify(err.message, 'error');
    }
  };

  const handleRevoke = async (deviceId) => {
    if (!canManage) {
      onNotify('Chỉ Quản trị viên mới có quyền thu hồi thiết bị.', 'error');
      return;
    }
    if (!window.confirm(`Bạn có chắc chắn muốn thu hồi thiết bị ${deviceId}? Sau khi thu hồi, thiết bị sẽ bị ngắt kết nối.`)) {
      return;
    }
    try {
      await apiRevokeDevice(deviceId);
      onNotify(`Đã thu hồi thiết bị ${deviceId}`);
      onRefreshDevices();
      onRefreshRegistrations();
    } catch (err) {
      onNotify(err.message, 'error');
    }
  };

  const handleApprove = async (hwId, deviceId = null, name = '', barnId = null) => {
    if (!canManage) {
      onNotify('Chỉ Quản trị viên mới có quyền duyệt thiết bị.', 'error');
      return;
    }
    try {
      await apiApproveRegistration(hwId, deviceId, name, barnId);
      onNotify(`Đã phê duyệt thiết bị ${hwId}`);
      onRefreshRegistrations();
      onRefreshDevices();
    } catch (err) {
      onNotify(err.message, 'error');
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
      onNotify(err.message, 'error');
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
          barns={barns}
          devices={devices}
          onRefresh={onRefreshDevices}
          onPing={handlePing}
          onReboot={handleReboot}
          onAssignBarn={handleAssignBarn}
          onRevoke={handleRevoke}
        />
      ) : (
        <PendingRegistrations
          barns={barns}
          registrations={registrations}
          onRefresh={onRefreshRegistrations}
          onApprove={handleApprove}
          onReject={handleReject}
        />
      )}
    </div>
  );
}
