import React, { useState } from 'react';
import { RoleBadge, StatusPill } from '../common/StatusBadge';
import Pagination from '../common/Pagination';
import EmptyState from '../common/EmptyState';
import { groupPermissionBarns, getBarnSelectionState, setBarnsSelected, summarizeBarnPermissions } from './userPermissionUtils';

const defaultForm = () => ({ username: '', password: '', fullName: '', role: 'Viewer' });

export default function UserManagement({
  users, barns, devices = [], assignments, currentUserId, loading, loadError,
  onRefresh, onCreateUser, onUpdateUser,
}) {
  const [createForm, setCreateForm] = useState(defaultForm);
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [page, setPage] = useState(1);
  const pageSize = 8;
  const totalPages = Math.ceil(users.length / pageSize) || 1;
  const currentPage = Math.min(page, totalPages);
  const pagedUsers = users.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const isSelf = editing?.id === currentUserId;
  const permissionZones = groupPermissionBarns(barns, devices);

  const startEdit = (user) => {
    setError('');
    setEditing({
      id: user.id, username: user.username, fullName: user.full_name || '',
      role: user.role, status: user.status, newPassword: '', confirmPassword: '',
      barnIds: assignments.filter((item) => item.user_id === user.id).map((item) => item.barn_id),
    });
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError('');
    if (!editing && (createForm.username.trim().length < 3 || createForm.username.trim().length > 100)) {
      setError('Tên đăng nhập cần từ 3 đến 100 ký tự.');
      return;
    }
    const password = editing ? editing.newPassword : createForm.password;
    if (editing && password !== editing.confirmPassword) {
      setError('Hai lần nhập mật khẩu mới không khớp.');
      return;
    }
    if ((!editing || password) && (password.length < 8 || new TextEncoder().encode(password).length > 72)) {
      setError('Mật khẩu cần ít nhất 8 ký tự và không quá 72 byte UTF-8.');
      return;
    }
    setSaving(true);
    try {
      if (editing) {
        await onUpdateUser(editing.id, { ...editing, fullName: editing.fullName.trim() });
        setEditing(null);
      } else {
        await onCreateUser({ ...createForm, username: createForm.username.trim(), fullName: createForm.fullName.trim() });
        setCreateForm(defaultForm());
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const form = editing || createForm;
  const updateField = (field, value) => {
    if (editing) setEditing((previous) => ({ ...previous, [field]: value }));
    else setCreateForm((previous) => ({ ...previous, [field]: value }));
  };

  return (
    <div className="dashboard-grid">
      <div className="card" style={{ minWidth: 0 }}>
        <div className="card-header">
          <h2 className="card-title">Danh Sách Tài Khoản</h2>
          <button className="btn btn-secondary btn-sm" onClick={onRefresh} disabled={loading || saving}>Làm mới</button>
        </div>
        {loadError && <p role="alert" style={{ color: 'var(--accent-red)' }}>{loadError}</p>}
        {loading && <p role="status">Đang tải tài khoản và phân quyền…</p>}
        {!loading && !loadError && users.length === 0 ? (
          <EmptyState icon="👤" title="Chưa có tài khoản nào" />
        ) : (
          <>
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead><tr>
                  <th>Tên Đăng Nhập</th><th>Họ Tên</th><th>Vai Trò</th><th>Trạng Thái</th><th>Phân Quyền</th><th>Thao Tác</th>
                </tr></thead>
                <tbody>
                  {pagedUsers.map((user) => (
                    <tr key={user.id}>
                      <td><code>{user.username}</code></td>
                      <td>{user.full_name || '--'}</td>
                      <td><RoleBadge role={user.role} /></td>
                      <td><StatusPill status={user.status} /></td>
                      <td>{user.role === 'Admin' ? 'Tất cả khu và chuồng' : summarizeBarnPermissions(permissionZones,
                        assignments.filter((item) => item.user_id === user.id).map((item) => item.barn_id))}</td>
                      <td><button
                        className="btn btn-secondary btn-xs" disabled={loading || saving || Boolean(loadError)}
                        onClick={() => startEdit(user)} aria-label={`Sửa tài khoản ${user.username}`}
                      >Sửa</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination currentPage={currentPage} totalPages={totalPages} totalItems={users.length} onPageChange={setPage} />
          </>
        )}
      </div>

      <div className="card">
        <h2 className="card-title">{editing ? `Sửa Tài Khoản: ${editing.username}` : 'Thêm Tài Khoản'}</h2>
        <form onSubmit={handleSubmit} className="admin-form" noValidate>
          {error && <p role="alert" style={{ color: 'var(--accent-red)' }}>{error}</p>}
          <fieldset disabled={saving || loading || Boolean(loadError)} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
            {!editing && <>
              <div className="form-group">
                <label className="form-label" htmlFor="account-username">Tên đăng nhập:</label>
                <input id="account-username" className="form-input" value={form.username} autoComplete="off"
                  onChange={(event) => updateField('username', event.target.value)} required minLength={3} maxLength={100} />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="account-password">Mật khẩu:</label>
                <input id="account-password" type="password" className="form-input" value={form.password} autoComplete="new-password"
                  onChange={(event) => updateField('password', event.target.value)} required minLength={8} maxLength={72} />
              </div>
            </>}
            <div className="form-group">
              <label className="form-label" htmlFor="account-name">Họ tên:</label>
              <input id="account-name" className="form-input" value={form.fullName} maxLength={255}
                onChange={(event) => updateField('fullName', event.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="account-role">Vai trò:</label>
              <select id="account-role" className="select-control" style={{ width: '100%' }} value={form.role}
                disabled={Boolean(editing && isSelf)} onChange={(event) => updateField('role', event.target.value)}>
                <option value="Viewer">Viewer</option><option value="Operator">Operator</option><option value="Admin">Admin</option>
              </select>
            </div>
            {editing && <>
              <div className="form-group">
                <label className="form-label" htmlFor="account-status">Trạng thái:</label>
                <select id="account-status" className="select-control" style={{ width: '100%' }} value={editing.status}
                  disabled={isSelf} onChange={(event) => updateField('status', event.target.value)}>
                  <option value="active">Hoạt động (mở khóa)</option><option value="locked">Đã khóa</option>
                </select>
              </div>
              {isSelf ? <p className="text-muted">Bạn không thể tự hạ vai trò hoặc khóa tài khoản. Đổi mật khẩu tại phần tài khoản cá nhân.</p> : <>
                <div className="form-group">
                  <label className="form-label" htmlFor="account-new-password">Mật khẩu mới (để trống nếu giữ nguyên):</label>
                  <input id="account-new-password" type="password" className="form-input" autoComplete="new-password"
                    value={editing.newPassword} minLength={8} maxLength={72}
                    onChange={(event) => updateField('newPassword', event.target.value)} />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="account-confirm-password">Nhập lại mật khẩu mới:</label>
                  <input id="account-confirm-password" type="password" className="form-input" autoComplete="new-password"
                    value={editing.confirmPassword} required={Boolean(editing.newPassword)} minLength={8} maxLength={72}
                    onChange={(event) => updateField('confirmPassword', event.target.value)} />
                </div>
              </>}
              {editing.role !== 'Admin' && <fieldset className="form-group" style={{ border: 0, padding: 0 }}>
                <legend className="form-label">Phân quyền Khu → Chuồng → Thiết bị ({editing.barnIds.length} chuồng):</legend>
                <p className="text-muted">Quyền chuồng áp dụng cho mọi thiết bị trong chuồng</p>
                {barns.length === 0 && <p className="text-muted">Chưa có chuồng để phân quyền.</p>}
                {permissionZones.map((zone) => {
                  const selection = getBarnSelectionState(zone.barns, editing.barnIds);
                  return (
                    <fieldset key={zone.name} style={{ border: '1px solid var(--border-color)', borderRadius: 8, padding: 12, margin: '12px 0', minWidth: 0 }}>
                      <legend>
                        <label style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
                          <input type="checkbox" checked={selection.checked}
                            aria-checked={selection.indeterminate ? 'mixed' : selection.checked}
                            ref={(input) => { if (input) input.indeterminate = selection.indeterminate; }}
                            onChange={(event) => updateField('barnIds', setBarnsSelected(editing.barnIds, zone.barns, event.target.checked))} />
                          {zone.name}
                        </label>
                      </legend>
                      {zone.barns.map((barn) => (
                        <div key={barn.id} style={{ margin: '8px 0 12px 12px' }}>
                          <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                            <input type="checkbox" checked={getBarnSelectionState([barn], editing.barnIds).checked}
                              onChange={(event) => updateField('barnIds', setBarnsSelected(editing.barnIds, [barn], event.target.checked))} />
                            {barn.name || barn.id}
                          </label>
                          {barn.devices.length === 0 ? <p className="text-muted" style={{ marginLeft: 24 }}>Chưa có thiết bị trong chuồng.</p> : (
                            <ul aria-label={`Thiết bị trong chuồng ${barn.name || barn.id}`} style={{ listStyle: 'none', paddingLeft: 24 }}>
                              {barn.devices.map((device) => (
                                <li key={device.device_id} style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginTop: 8, overflowWrap: 'anywhere' }}>
                                  <span>{device.name && `${device.name} — `}<code>{device.device_id}</code></span>
                                  <StatusPill status={device.online ? 'online' : 'offline'} />
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                      ))}
                    </fieldset>
                  );
                })}
              </fieldset>}
            </>}
            <button type="submit" className="btn btn-primary btn-full">
              {saving ? 'Đang lưu…' : editing ? 'Lưu thay đổi' : 'Thêm Tài Khoản'}
            </button>
          </fieldset>
          {editing && <button type="button" className="btn btn-secondary btn-full" style={{ marginTop: 8 }} disabled={saving}
            onClick={() => { setEditing(null); setError(''); }}>Hủy sửa</button>}
        </form>
      </div>
    </div>
  );
}
