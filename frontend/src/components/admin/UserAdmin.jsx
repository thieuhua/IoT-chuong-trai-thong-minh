import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import {
  apiGetUsers, apiCreateUser, apiUpdateUser, apiResetUserPassword, apiGetAuditLogs,
  apiGetBarns, apiGetDevices, apiGetBarnAssignments, apiAssignBarnUser, apiRemoveBarnUser,
} from '../../services/api';
import UserManagement from './UserManagement';
import AuditLogTable from './AuditLogTable';

function accountError(error) {
  const translations = {
    'Username already exists': 'Tên đăng nhập đã tồn tại.',
    'User not found': 'Không tìm thấy tài khoản. Hãy làm mới danh sách.',
    'Barn not found': 'Chuồng không còn tồn tại. Hãy làm mới danh sách.',
    'User is not assigned to this barn': 'Phân quyền chuồng đã thay đổi. Hãy làm mới danh sách.',
    "Access level must match the user's role": 'Vai trò đã thay đổi. Hãy làm mới và thử lại.',
    'Only Operator or Viewer can be assigned to a barn': 'Chỉ phân quyền chuồng cho Operator hoặc Viewer.',
  };
  if (translations[error.detail]) return translations[error.detail];
  if (error.status === 401) return 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.';
  if (error.status === 403) return 'Bạn không có quyền quản lý tài khoản.';
  if (error.status === 422) return 'Dữ liệu không hợp lệ. Tên đăng nhập cần 3–100 ký tự; mật khẩu cần 8–72 ký tự và tối đa 72 byte UTF-8.';
  if (typeof error.detail === 'string' && /[À-ỹ]/.test(error.detail)) return error.detail;
  return 'Không thể hoàn tất yêu cầu. Kiểm tra kết nối và thử lại.';
}

export default function UserAdmin({ onNotify }) {
  const { isAdmin, user: currentUser } = useAuth();
  const [activeTab, setActiveTab] = useState('users');
  const [users, setUsers] = useState([]);
  const [barns, setBarns] = useState([]);
  const [devices, setDevices] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [auditLogs, setAuditLogs] = useState([]);

  const fetchUsers = async () => {
    setLoading(true);
    setLoadError('');
    try {
      const [nextUsers, nextBarns, nextDevices] = await Promise.all([apiGetUsers(), apiGetBarns(), apiGetDevices()]);
      const grants = await Promise.all(nextBarns.map((barn) => apiGetBarnAssignments(barn.id)));
      setUsers(nextUsers);
      setBarns(nextBarns);
      setDevices(nextDevices);
      setAssignments(grants.flat());
      return true;
    } catch (err) {
      const message = 'Lỗi tải tài khoản và phân quyền: ' + accountError(err);
      setLoadError(message);
      onNotify(message, 'error');
      return false;
    } finally {
      setLoading(false);
    }
  };

  const fetchAuditLogs = async () => {
    try {
      setAuditLogs(await apiGetAuditLogs());
    } catch (err) {
      onNotify('Lỗi tải nhật ký: ' + accountError(err), 'error');
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
    } catch (err) {
      throw new Error(accountError(err));
    }
    onNotify(`Đã tạo tài khoản ${username}`);
    await Promise.all([fetchUsers(), fetchAuditLogs()]);
  };

  const handleUpdateUser = async (userId, { fullName, role, status, barnIds, newPassword }) => {
    let profileSaved = false;
    try {
      await apiUpdateUser(userId, { full_name: fullName, role, status });
      profileSaved = true;
      if (role !== 'Admin') {
        const previous = assignments.filter((item) => item.user_id === userId);
        for (const grant of previous) {
          if (!barnIds.includes(grant.barn_id)) await apiRemoveBarnUser(grant.barn_id, userId);
        }
        for (const barnId of barnIds) {
          // PATCH synchronizes existing grants with the role; PUT adds new barns.
          if (!previous.some((grant) => grant.barn_id === barnId)) {
            await apiAssignBarnUser(barnId, userId, role);
          }
        }
      }
      if (newPassword) await apiResetUserPassword(userId, newPassword);
    } catch (err) {
      await Promise.all([fetchUsers(), fetchAuditLogs()]);
      throw new Error((profileSaved ? 'Một phần thay đổi đã được lưu. ' : '') + accountError(err));
    }
    onNotify('Đã cập nhật tài khoản' + (newPassword ? ' và đặt lại mật khẩu' : ''));
    await Promise.all([fetchUsers(), fetchAuditLogs()]);
  };

  if (!isAdmin) {
    return <div className="card"><p className="empty-state-text">Chỉ Quản trị viên mới có quyền truy cập.</p></div>;
  }

  return (
    <div>
      <div className="subtabs-bar">
        <button className={`subtab-btn ${activeTab === 'users' ? 'active' : ''}`} onClick={() => setActiveTab('users')}>
          Tài Khoản ({users.length})
        </button>
        <button className={`subtab-btn ${activeTab === 'audit' ? 'active' : ''}`} onClick={() => setActiveTab('audit')}>
          Nhật Ký ({auditLogs.length})
        </button>
      </div>
      {activeTab === 'users' ? (
        <UserManagement
          users={users} barns={barns} devices={devices} assignments={assignments} currentUserId={currentUser?.id}
          loading={loading} loadError={loadError} onRefresh={fetchUsers}
          onCreateUser={handleCreateUser} onUpdateUser={handleUpdateUser}
        />
      ) : <AuditLogTable auditLogs={auditLogs} onRefresh={fetchAuditLogs} />}
    </div>
  );
}
