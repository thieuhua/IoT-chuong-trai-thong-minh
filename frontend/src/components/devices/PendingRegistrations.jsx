import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { apiGetRegistrations } from '../../services/api';
import Pagination from '../common/Pagination';
import EmptyState from '../common/EmptyState';

export default function PendingRegistrations({
  barns = [],
  registrations: pendingRegistrations = [],
  onRefresh,
  onApprove,
  onReject,
}) {
  const { canManage } = useAuth();
  const [page, setPage] = useState(1);
  const [assignedBarns, setAssignedBarns] = useState({});
  // 'pending' uses the list App keeps fresh; 'rejected' is fetched here on demand.
  const [view, setView] = useState('pending');
  const [rejectedRegistrations, setRejectedRegistrations] = useState([]);
  const pageSize = 6;
  const showingRejected = view === 'rejected';
  const registrations = showingRejected ? rejectedRegistrations : pendingRegistrations;

  const loadRejected = async () => {
    setRejectedRegistrations(await apiGetRegistrations('rejected').catch(() => []));
  };

  const changeView = (next) => {
    setView(next);
    setPage(1);
    if (next === 'rejected') loadRejected();
  };

  const refresh = () => (showingRejected ? loadRejected() : onRefresh());

  const approve = async (hwId) => {
    await onApprove(hwId, null, '', assignedBarns[hwId] || null);
    if (showingRejected) loadRejected();
  };

  const totalPages = Math.ceil(registrations.length / pageSize) || 1;
  const pagedRegistrations = registrations.slice((page - 1) * pageSize, page * pageSize);

  const handleBarnChange = (hwId, barnId) => {
    setAssignedBarns((prev) => ({ ...prev, [hwId]: barnId }));
  };

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h2 className="card-title">Cấp Phép Thiết Bị</h2>
        </div>
        <div className="filters-row">
          <select
            value={view}
            onChange={(e) => changeView(e.target.value)}
            className="select-control"
          >
            <option value="pending">Chờ duyệt</option>
            <option value="rejected">Đã từ chối</option>
          </select>
          <button className="btn btn-secondary btn-sm" onClick={refresh}>
            Làm mới
          </button>
        </div>
      </div>

      {registrations.length === 0 ? (
        <EmptyState
          icon="✅"
          title={showingRejected ? 'Không có yêu cầu bị từ chối' : 'Không có yêu cầu chờ duyệt'}
        />
      ) : (
        <>
          <table className="data-table">
            <thead>
              <tr>
                <th>Hardware ID</th>
                <th>Model</th>
                <th>IP Yêu Cầu</th>
                <th>Gán Chuồng Khi Duyệt</th>
                <th>Thời Gian</th>
                <th>Thao Tác</th>
              </tr>
            </thead>
            <tbody>
              {pagedRegistrations.map((reg) => (
                <tr key={reg.hw_id}>
                  <td><code>{reg.hw_id}</code></td>
                  <td>{reg.model || 'esp32'}</td>
                  <td>{reg.requested_ip || 'DHCP'}</td>
                  <td>
                    <select
                      value={assignedBarns[reg.hw_id] || ''}
                      onChange={(e) => handleBarnChange(reg.hw_id, e.target.value)}
                      className="select-control select-sm"
                      disabled={!canManage}
                    >
                      <option value="">-- Chọn chuồng --</option>
                      {barns.map((b) => (
                        <option key={b.id} value={b.id}>
                          {b.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>{new Date(reg.requested_at).toLocaleString()}</td>
                  <td>
                    <div className="action-buttons-row">
                      <button
                        className="btn btn-success btn-xs"
                        onClick={() => approve(reg.hw_id)}
                        disabled={!canManage}
                      >
                        Duyệt
                      </button>
                      {showingRejected ? (
                        <span className="text-muted" title="Lý do từ chối">
                          {reg.reason || 'Đã từ chối'}
                        </span>
                      ) : (
                        <button
                          className="btn btn-danger btn-xs"
                          onClick={() => onReject(reg.hw_id)}
                          disabled={!canManage}
                        >
                          Từ chối
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <Pagination
            currentPage={page}
            totalPages={totalPages}
            totalItems={registrations.length}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  );
}
