import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import {
  apiGetUsers,
  apiCreateUser,
  apiUpdateUser,
  apiGetAuditLogs,
} from '../../services/api';
import UserManagement from './UserManagement';
import AuditLogTable from './AuditLogTable';

export default function UserAdmin({ onNotify }) {
  const { isAdmin } = useAuth();
  const [activeTab, setActiveTab] = useState('users');

  const [users, setUsers] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);

  const fetchUsers = async () => {
    try {
      const res = await apiGetUsers();
      setUsers(res);
    } catch (err) {
      onNotify('Lỗi tải người dùng: ' + err.message, 'error');
    }
  };

  const fetchAuditLogs = async () => {
    try {
      const res = await apiGetAuditLogs();
      setAuditLogs(res);
    } catch (err) {
      onNotify('Lỗi tải nhật ký: ' + err.message, 'error');
    }
  };

  useEffect(() => {
    if (isAdmin) {
      fetchUsers();
      fetchAuditLogs();
    }
  }, [isAdmin]);

  const handleCreateUser = async ({ username, password, fullName, role }) => {
    try {
      await apiCreateUser(username, password, fullName, role);
      onNotify(`Đã tạo tài khoản ${username}`);
      fetchUsers();
    } catch (err) {
      onNotify('Lỗi tạo tài khoản: ' + err.message, 'error');
    }
  };

  const handleToggleStatus = async (user) => {
    const nextStatus = user.status === 'active' ? 'locked' : 'active';
    try {
      await apiUpdateUser(user.id, { status: nextStatus });
      onNotify(`Đã ${nextStatus === 'locked' ? 'khóa' : 'mở khóa'} ${user.username}`);
      fetchUsers();
    } catch (err) {
      onNotify('Lỗi cập nhật: ' + err.message, 'error');
    }
  };

  if (!isAdmin) {
    return (
      <div className="card">
        <p className="empty-state-text">Chỉ Quản trị viên mới có quyền truy cập.</p>
      </div>
    );
  }

  return (
    <div>
      <div className="subtabs-bar">
        <button
          className={`subtab-btn ${activeTab === 'users' ? 'active' : ''}`}
          onClick={() => setActiveTab('users')}
        >
          Tài Khoản ({users.length})
        </button>
        <button
          className={`subtab-btn ${activeTab === 'audit' ? 'active' : ''}`}
          onClick={() => setActiveTab('audit')}
        >
          Nhật Ký ({auditLogs.length})
        </button>
      </div>

      {activeTab === 'users' ? (
        <UserManagement
          users={users}
          onRefresh={fetchUsers}
          onCreateUser={handleCreateUser}
          onToggleStatus={handleToggleStatus}
        />
      ) : (
        <AuditLogTable
          auditLogs={auditLogs}
          onRefresh={fetchAuditLogs}
        />
      )}
    </div>
  );
}
