import React, { useState } from 'react';
import Pagination from '../common/Pagination';
import EmptyState from '../common/EmptyState';

export default function AuditLogTable({ auditLogs, onRefresh }) {
  const [page, setPage] = useState(1);
  const pageSize = 8;

  const totalPages = Math.ceil(auditLogs.length / pageSize) || 1;
  const pagedLogs = auditLogs.slice((page - 1) * pageSize, page * pageSize);

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h2 className="card-title">Nhật Ký Hệ Thống</h2>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={onRefresh}>
          Làm mới
        </button>
      </div>

      {auditLogs.length === 0 ? (
        <EmptyState
          icon="📝"
          title="Chưa có bản ghi nhật ký"
        />
      ) : (
        <>
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Thời Gian</th>
                <th>Người Dùng</th>
                <th>Hành Động</th>
                <th>Đối Tượng</th>
                <th>Kết Quả</th>
                <th>IP</th>
              </tr>
            </thead>
            <tbody>
              {pagedLogs.map((log) => (
                <tr key={log.id}>
                  <td><code>#{log.id}</code></td>
                  <td>{log.ts ? new Date(log.ts).toLocaleString() : (log.created_at ? new Date(log.created_at).toLocaleString() : '--')}</td>
                  <td><code>{log.user_id || log.actor_username || 'Hệ thống'}</code></td>
                  <td>
                    <span className="log-action-tag">{log.action}</span>
                  </td>
                  <td><code>{log.target || (log.target_type ? `${log.target_type}: ${log.target_id}` : '--')}</code></td>
                  <td>
                    <span className={log.result === 'success' || log.result === 'ok' ? 'text-green' : 'text-amber'}>
                      {log.result || '--'}
                    </span>
                  </td>
                  <td><code>{log.ip || '--'}</code></td>
                </tr>
              ))}
            </tbody>
          </table>

          <Pagination
            currentPage={page}
            totalPages={totalPages}
            totalItems={auditLogs.length}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  );
}
