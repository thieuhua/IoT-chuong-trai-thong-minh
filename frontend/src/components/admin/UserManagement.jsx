import React, { useState } from 'react';
import { RoleBadge, StatusPill } from '../common/StatusBadge';
import Pagination from '../common/Pagination';
import EmptyState from '../common/EmptyState';

export default function UserManagement({
  users,
  onRefresh,
  onCreateUser,
  onToggleStatus,
}) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [role, setRole] = useState('Viewer');

  const [page, setPage] = useState(1);
  const pageSize = 8;

  const totalPages = Math.ceil(users.length / pageSize) || 1;
  const pagedUsers = users.slice((page - 1) * pageSize, page * pageSize);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!username.trim() || !password) return;
    onCreateUser({ username: username.trim(), password, fullName: fullName.trim(), role });
    setUsername('');
    setPassword('');
    setFullName('');
  };

  return (
    <div className="dashboard-grid">
      <div>
        <div className="card">
          <div className="card-header">
            <div>
              <h2 className="card-title">Danh Sách Tài Khoản</h2>
            </div>
            <button className="btn btn-secondary btn-sm" onClick={onRefresh}>
              Làm mới
            </button>
          </div>

          {users.length === 0 ? (
            <EmptyState
              icon="👤"
              title="Chưa có tài khoản nào"
            />
          ) : (
            <>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Tên Đăng Nhập</th>
                    <th>Họ Tên</th>
                    <th>Vai Trò</th>
                    <th>Trạng Thái</th>
                    <th>Thao Tác</th>
                  </tr>
                </thead>
                <tbody>
                  {pagedUsers.map((u) => (
                    <tr key={u.id}>
                      <td><code>{u.username}</code></td>
                      <td>{u.full_name || '--'}</td>
                      <td>
                        <RoleBadge role={u.role} />
                      </td>
                      <td>
                        <StatusPill status={u.status} />
                      </td>
                      <td>
                        {u.username !== 'admin' && (
                          <button
                            className={`btn btn-xs ${
                              u.status === 'active' ? 'btn-danger' : 'btn-success'
                            }`}
                            onClick={() => onToggleStatus(u)}
                          >
                            {u.status === 'active' ? 'Khóa' : 'Mở khóa'}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <Pagination
                currentPage={page}
                totalPages={totalPages}
                totalItems={users.length}
                onPageChange={setPage}
              />
            </>
          )}
        </div>
      </div>

      <div>
        <div className="card">
          <h2 className="card-title">Thêm Tài Khoản</h2>

          <form onSubmit={handleSubmit} className="admin-form">
            <div className="form-group">
              <label className="form-label">Tên đăng nhập:</label>
              <input
                type="text"
                className="form-input"
                placeholder="Tên đăng nhập"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">Mật khẩu:</label>
              <input
                type="password"
                className="form-input"
                placeholder="Mật khẩu (tối thiểu 8 ký tự)"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
              />
            </div>

            <div className="form-group">
              <label className="form-label">Họ tên:</label>
              <input
                type="text"
                className="form-input"
                placeholder="Họ và tên"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label className="form-label">Vai trò:</label>
              <select
                className="select-control"
                style={{ width: '100%' }}
                value={role}
                onChange={(e) => setRole(e.target.value)}
              >
                <option value="Viewer">Viewer</option>
                <option value="Operator">Operator</option>
                <option value="Admin">Admin</option>
              </select>
            </div>

            <button type="submit" className="btn btn-primary btn-full">
              Thêm Tài Khoản
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
