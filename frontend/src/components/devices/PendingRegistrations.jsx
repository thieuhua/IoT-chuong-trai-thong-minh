import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import Pagination from '../common/Pagination';
import EmptyState from '../common/EmptyState';

export default function PendingRegistrations({
  registrations,
  onRefresh,
  onApprove,
  onReject,
}) {
  const { canManage } = useAuth();
  const [page, setPage] = useState(1);
  const pageSize = 6;

  const totalPages = Math.ceil(registrations.length / pageSize) || 1;
  const pagedRegistrations = registrations.slice((page - 1) * pageSize, page * pageSize);

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h2 className="card-title">Cấp Phép Thiết Bị</h2>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={onRefresh}>
          Làm mới
        </button>
      </div>

      {registrations.length === 0 ? (
        <EmptyState
          icon="✅"
          title="Không có yêu cầu chờ duyệt"
        />
      ) : (
        <>
          <table className="data-table">
            <thead>
              <tr>
                <th>Hardware ID</th>
                <th>IP Yêu Cầu</th>
                <th>Chuồng</th>
                <th>Thời Gian</th>
                <th>Thao Tác</th>
              </tr>
            </thead>
            <tbody>
              {pagedRegistrations.map((reg) => (
                <tr key={reg.hw_id}>
                  <td><code>{reg.hw_id}</code></td>
                  <td>{reg.requested_ip || 'DHCP'}</td>
                  <td>{reg.barn_id ? `#${reg.barn_id}` : '--'}</td>
                  <td>{new Date(reg.requested_at).toLocaleString()}</td>
                  <td>
                    <div className="action-buttons-row">
                      <button
                        className="btn btn-success btn-xs"
                        onClick={() => onApprove(reg.hw_id)}
                        disabled={!canManage}
                      >
                        Duyệt
                      </button>
                      <button
                        className="btn btn-danger btn-xs"
                        onClick={() => onReject(reg.hw_id)}
                        disabled={!canManage}
                      >
                        Từ chối
                      </button>
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
