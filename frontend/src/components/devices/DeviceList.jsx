import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { StatusPill } from '../common/StatusBadge';
import Pagination from '../common/Pagination';
import EmptyState from '../common/EmptyState';

export default function DeviceList({
  barns = [],
  devices = [],
  onRefresh,
  onPing,
  onReboot,
  onAssignBarn,
  onRevoke,
}) {
  const { canControl, canManage } = useAuth();
  const [page, setPage] = useState(1);
  const [selectedCapabilityDev, setSelectedCapabilityDev] = useState(null);
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
                <th>Mã Thiết Bị</th>
                <th>Tên</th>
                <th>Gán Chuồng</th>
                <th>Trạng Thái</th>
                <th>Năng Lực</th>
                <th>Firmware</th>
                <th>Thao Tác</th>
              </tr>
            </thead>
            <tbody>
              {pagedDevices.map((dev) => (
                <tr key={dev.device_id}>
                  <td><code>{dev.device_id}</code></td>
                  <td><strong>{dev.name || dev.device_id}</strong></td>
                  <td>
                    {canManage ? (
                      <select
                        value={dev.barn_id || ''}
                        onChange={(e) => onAssignBarn(dev.device_id, e.target.value)}
                        className="select-control select-sm"
                      >
                        <option value="">-- Chưa gán --</option>
                        {barns.map((b) => (
                          <option key={b.id} value={b.id}>
                            {b.name}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span>{barns.find((b) => b.id === dev.barn_id)?.name || '--'}</span>
                    )}
                  </td>
                  <td>
                    <StatusPill
                      status={dev.online ? 'online' : 'offline'}
                      label={dev.online ? 'Online' : 'Offline'}
                    />
                  </td>
                  <td>
                    <button
                      className="btn btn-secondary btn-xs"
                      onClick={() => setSelectedCapabilityDev(dev)}
                      title="Xem năng lực cảm biến và bộ lệnh"
                    >
                      🔍 Năng Lực ({(dev.sensors?.length || 0)} cảm biến)
                    </button>
                  </td>
                  <td><span className="fw-tag">{dev.fw || 'v1.0.0'}</span></td>
                  <td>
                    <div className="action-buttons-row">
                      <button
                        className="btn btn-secondary btn-xs"
                        onClick={() => onPing(dev.device_id)}
                        disabled={!dev.online}
                        title={!dev.online ? 'Thiết bị đang offline' : ''}
                      >
                        Ping
                      </button>
                      <button
                        className="btn btn-danger btn-xs"
                        onClick={() => onReboot(dev.device_id)}
                        disabled={!canControl || !dev.online}
                        title={!dev.online ? 'Thiết bị đang offline' : ''}
                      >
                        Reboot
                      </button>
                      {canManage && (
                        <button
                          className="btn btn-danger btn-xs"
                          onClick={() => onRevoke(dev.device_id)}
                          title="Thu hồi và xóa quyền thiết bị"
                        >
                          Thu Hồi
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
            totalItems={devices.length}
            onPageChange={setPage}
          />
        </>
      )}

      {/* Modal chi tiết ánh xạ năng lực (Capability Mapping) */}
      {selectedCapabilityDev && (
        <div className="modal-backdrop" onClick={() => setSelectedCapabilityDev(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Ánh Xạ Năng Lực: {selectedCapabilityDev.name || selectedCapabilityDev.device_id}</h3>
              <button className="btn btn-secondary btn-sm" onClick={() => setSelectedCapabilityDev(null)}>✕</button>
            </div>
            <div className="modal-body" style={{ marginTop: '12px' }}>
              <p><strong>Mã thiết bị:</strong> <code>{selectedCapabilityDev.device_id}</code></p>
              <p><strong>Hardware ID:</strong> <code>{selectedCapabilityDev.hw_id}</code></p>
              <p><strong>Model:</strong> {selectedCapabilityDev.model || '--'}</p>
              <p><strong>Chu kỳ đo (Interval):</strong> {selectedCapabilityDev.interval_s ? `${selectedCapabilityDev.interval_s}s` : '--'}</p>

              <h4 style={{ marginTop: '16px', marginBottom: '8px' }}>Cảm Biến (Sensors)</h4>
              {(!selectedCapabilityDev.sensors || selectedCapabilityDev.sensors.length === 0) ? (
                <p className="text-muted">Chưa cấu hình cảm biến.</p>
              ) : (
                <table className="data-table" style={{ marginBottom: '16px' }}>
                  <thead>
                    <tr>
                      <th>Tên Cảm Biến</th>
                      <th>Driver</th>
                      <th>Các Trường & Đơn Vị</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedCapabilityDev.sensors.map((s, idx) => (
                      <tr key={idx}>
                        <td><strong>{s.name}</strong></td>
                        <td><code>{s.driver || '--'}</code></td>
                        <td>
                          {s.fields && Object.keys(s.fields).length > 0 ? (
                            Object.entries(s.fields).map(([f, u]) => (
                              <span key={f} className="badge-tag" style={{ marginRight: '6px' }}>
                                {f}: {u || 'N/A'}
                              </span>
                            ))
                          ) : '--'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              <h4 style={{ marginTop: '16px', marginBottom: '8px' }}>Lệnh Hỗ Trợ (Commands)</h4>
              {(!selectedCapabilityDev.commands || selectedCapabilityDev.commands.length === 0) ? (
                <p className="text-muted">Chưa cấu hình danh sách lệnh.</p>
              ) : (
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  {selectedCapabilityDev.commands.map((cmd) => (
                    <span key={cmd} className="badge-tag" style={{ background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8' }}>
                      {cmd}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="modal-footer" style={{ marginTop: '20px', textAlign: 'right' }}>
              <button className="btn btn-secondary" onClick={() => setSelectedCapabilityDev(null)}>Đóng</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
