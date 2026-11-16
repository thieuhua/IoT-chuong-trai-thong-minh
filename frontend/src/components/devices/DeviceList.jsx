import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { StatusPill } from '../common/StatusBadge';
import Pagination from '../common/Pagination';
import EmptyState from '../common/EmptyState';

export default function DeviceList({
  devices,
  onRefresh,
  onPing,
  onReboot,
}) {
  const { canControl } = useAuth();
  const [page, setPage] = useState(1);
  const pageSize = 6;

  const totalPages = Math.ceil(devices.length / pageSize) || 1;
  const pagedDevices = devices.slice((page - 1) * pageSize, page * pageSize);

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h2 className="card-title">Danh Sách Thiết Bị</h2>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={onRefresh}>
          Làm mới
        </button>
      </div>

      {devices.length === 0 ? (
        <EmptyState
          icon="🔌"
          title="Không có thiết bị nào"
        />
      ) : (
        <>
          <table className="data-table">
            <thead>
              <tr>
                <th>Mã</th>
                <th>Tên</th>
                <th>Trạng Thái</th>
                <th>Firmware</th>
                <th>Thời Gian</th>
                <th>Thao Tác</th>
              </tr>
            </thead>
            <tbody>
              {pagedDevices.map((dev) => (
                <tr key={dev.device_id}>
                  <td><code>{dev.device_id}</code></td>
                  <td><strong>{dev.name || dev.device_id}</strong></td>
                  <td>
                    <StatusPill
                      status={dev.online ? 'online' : 'offline'}
                      label={dev.online ? 'Online' : 'Offline'}
                    />
                  </td>
                  <td><span className="fw-tag">{dev.fw || 'v1.0.0'}</span></td>
                  <td>
                    {dev.last_seen
                      ? new Date(dev.last_seen).toLocaleTimeString()
                      : '--'}
                  </td>
                  <td>
                    <div className="action-buttons-row">
                      <button
                        className="btn btn-secondary btn-xs"
                        onClick={() => onPing(dev.device_id)}
                      >
                        Ping
                      </button>
                      <button
                        className="btn btn-danger btn-xs"
                        onClick={() => onReboot(dev.device_id)}
                        disabled={!canControl}
                      >
                        Reboot
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
            totalItems={devices.length}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  );
}
