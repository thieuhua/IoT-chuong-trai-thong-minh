import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { apiAcknowledgeAlert, apiCloseAlert } from '../../services/api';
import { SeverityBadge, StatusPill } from '../common/StatusBadge';
import Pagination from '../common/Pagination';
import EmptyState from '../common/EmptyState';

export default function AlertsCenter({ alerts, onRefreshAlerts, onNotify }) {
  const { canControl } = useAuth();
  const [filterStatus, setFilterStatus] = useState('all');

  const [page, setPage] = useState(1);
  const pageSize = 8;

  const filteredAlerts = alerts.filter((a) => {
    if (filterStatus === 'all') return true;
    if (filterStatus === 'open') return a.status === 'open' || a.status === 'active';
    return a.status === filterStatus;
  });

  const totalPages = Math.ceil(filteredAlerts.length / pageSize) || 1;
  const pagedAlerts = filteredAlerts.slice((page - 1) * pageSize, page * pageSize);

  const handleAck = async (alertId) => {
    try {
      await apiAcknowledgeAlert(alertId, 'Đã tiếp nhận');
      onNotify('Đã tiếp nhận cảnh báo.');
      onRefreshAlerts();
    } catch (err) {
      onNotify('Lỗi: ' + err.message, 'error');
    }
  };

  const handleClose = async (alertId) => {
    try {
      await apiCloseAlert(alertId, 'Đã đóng');
      onNotify('Đã đóng cảnh báo.');
      onRefreshAlerts();
    } catch (err) {
      onNotify('Lỗi: ' + err.message, 'error');
    }
  };

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h2 className="card-title">Cảnh Báo</h2>
        </div>

        <div className="filters-row">
          <select
            value={filterStatus}
            onChange={(e) => {
              setFilterStatus(e.target.value);
              setPage(1);
            }}
            className="select-control"
          >
            <option value="all">Tất cả</option>
            <option value="open">Đang mở</option>
            <option value="acknowledged">Đã tiếp nhận</option>
            <option value="closed">Đã đóng</option>
          </select>
          <button className="btn btn-secondary btn-sm" onClick={onRefreshAlerts}>
            Làm mới
          </button>
        </div>
      </div>

      {filteredAlerts.length === 0 ? (
        <EmptyState
          icon="✅"
          title="Không có cảnh báo nào"
        />
      ) : (
        <>
          <table className="data-table">
            <thead>
              <tr>
                <th>Mức Độ</th>
                <th>Mã Thiết Bị</th>
                <th>Thời Gian</th>
                <th>Trạng Thái</th>
                <th>Ghi Chú</th>
                <th>Thao Tác</th>
              </tr>
            </thead>
            <tbody>
              {pagedAlerts.map((al) => (
                <tr key={al.id}>
                  <td>
                    <SeverityBadge severity={al.severity} />
                  </td>
                  <td><code>{al.device_id || 'Hệ thống'}</code></td>
                  <td>{new Date(al.raised_at).toLocaleString()}</td>
                  <td>
                    <StatusPill
                      status={al.status}
                      label={al.status === 'open' ? 'Đang kích hoạt' : undefined}
                    />
                  </td>
                  <td>{al.note || '--'}</td>
                  <td>
                    <div className="action-buttons-row">
                      {(al.status === 'open' || al.status === 'active') && (
                        <button
                          className="btn btn-secondary btn-xs"
                          onClick={() => handleAck(al.id)}
                          disabled={!canControl}
                        >
                          Tiếp Nhận
                        </button>
                      )}
                      {al.status !== 'closed' && (
                        <button
                          className="btn btn-success btn-xs"
                          onClick={() => handleClose(al.id)}
                          disabled={!canControl}
                        >
                          Đóng
                        </button>
                      )}
                      {al.status === 'closed' && (
                        <span className="text-muted-check">✓ Đã đóng</span>
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
            totalItems={filteredAlerts.length}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  );
}
