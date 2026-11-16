import React from 'react';

export function RoleBadge({ role }) {
  const roleClass =
    role === 'Admin'
      ? 'role-admin'
      : role === 'Operator'
      ? 'role-operator'
      : 'role-viewer';

  return <span className={`role-badge ${roleClass}`}>{role}</span>;
}

export function StatusPill({ status, label }) {
  const displayLabel =
    label ||
    (status === 'active'
      ? 'Hoạt động'
      : status === 'locked'
      ? 'Đã khóa'
      : status === 'online'
      ? 'Online'
      : status === 'offline'
      ? 'Offline'
      : status === 'acknowledged'
      ? 'Đã tiếp nhận'
      : status === 'closed'
      ? 'Đã đóng'
      : status);

  return <span className={`status-pill pill-${status}`}>{displayLabel}</span>;
}

export function SeverityBadge({ severity }) {
  const isCritical = severity === 'critical';
  return (
    <span className={`badge-severity ${isCritical ? 'badge-critical' : 'badge-warning'}`}>
      {isCritical ? 'KHẨN CẤP' : 'CẢNH BÁO'}
    </span>
  );
}
