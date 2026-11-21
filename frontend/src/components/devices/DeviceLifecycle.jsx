import React, { useRef, useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import {
  apiSetDeviceMaintenance, apiSuspendDevice, apiResumeDevice,
  apiDecommissionDevice, apiRecommissionRegistration,
} from '../../services/api';

const LABELS = {
  provisioned: 'Đã cấp quyền, chờ kết nối',
  active: 'Đang hoạt động',
  offline: 'Mất kết nối',
  fault: 'Lỗi cảm biến',
  maintenance: 'Đang bảo trì',
  suspended: 'Tạm khóa',
  decommissioned: 'Ngừng dùng',
};

export function LifecycleBadge({ device }) {
  const state = device.lifecycle || (device.online ? 'active' : 'offline');
  return <span className={`status-pill lifecycle-${state}`}>{LABELS[state] || state}</span>;
}

export function LifecycleActions({ device, onAction, busy }) {
  const { canManage } = useAuth();
  if (!canManage) return null;
  const state = device.lifecycle;
  const normal = ['provisioned', 'active', 'offline', 'fault'].includes(state);
  const button = (action, label, danger = false) => (
    <button type="button" className={`btn btn-${danger ? 'danger' : 'secondary'} btn-xs`}
      disabled={busy} onClick={() => onAction(device, action)}>{label}</button>
  );
  return (
    <div className="action-buttons-row" aria-label="Quản lý vòng đời">
      {normal && button('maintenance', 'Bảo trì')}
      {state === 'maintenance' && button('endMaintenance', 'Thoát bảo trì')}
      {(normal || state === 'maintenance') && button('suspend', 'Tạm khóa')}
      {state === 'suspended' && button('resume', 'Mở khóa')}
      {(normal || ['maintenance', 'suspended'].includes(state)) && button('decommission', 'Ngừng dùng', true)}
      {state === 'decommissioned' && button('recommission', 'Đăng ký lại')}
    </div>
  );
}

export function useDeviceLifecycle(onRefresh, onNotify) {
  const { canManage } = useAuth();
  const [busyDeviceId, setBusyDeviceId] = useState(null);
  const pending = useRef(false);

  const changeLifecycle = async (device, action) => {
    if (!canManage || pending.current) return;
    if (action === 'decommission' && !window.confirm(
      `Ngừng dùng thiết bị ${device.name || device.device_id}? Thiết bị sẽ bị chặn kết nối; lịch sử được giữ lại.`,
    )) return;
    if (action === 'recommission' && !window.confirm(
      'Cho phép phần cứng đăng ký lại? Thiết bị cần gửi yêu cầu đăng ký và được Admin duyệt mới.',
    )) return;
    let reason = '';
    if (['maintenance', 'suspend', 'decommission'].includes(action)) {
      reason = window.prompt('Lý do (có thể để trống):', '');
      if (reason === null) return;
    }
    pending.current = true;
    setBusyDeviceId(device.device_id);
    try {
      const id = device.device_id;
      switch (action) {
        case 'maintenance': await apiSetDeviceMaintenance(id, true, reason); break;
        case 'endMaintenance': await apiSetDeviceMaintenance(id, false); break;
        case 'suspend': await apiSuspendDevice(id, reason); break;
        case 'resume': await apiResumeDevice(id); break;
        case 'decommission': await apiDecommissionDevice(id, reason); break;
        case 'recommission': await apiRecommissionRegistration(device.hw_id); break;
        default: return;
      }
      onNotify(action === 'recommission'
        ? 'Đã cho phép đăng ký lại. Chờ thiết bị gửi yêu cầu và duyệt mới.'
        : 'Đã cập nhật vòng đời thiết bị.');
      await onRefresh();
    } catch (err) {
      onNotify(err.message, 'error');
    } finally {
      pending.current = false;
      setBusyDeviceId(null);
    }
  };
  return { busyDeviceId, changeLifecycle };
}
