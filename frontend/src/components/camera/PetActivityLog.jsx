import React, { useState } from 'react';
import Pagination from '../common/Pagination';
import EmptyState from '../common/EmptyState';

export default function PetActivityLog({
  petLogs,
  isRunning,
  onClear,
}) {
  const [page, setPage] = useState(1);
  const pageSize = 8;

  const totalPages = Math.ceil(petLogs.length / pageSize) || 1;
  const pagedLogs = petLogs.slice((page - 1) * pageSize, page * pageSize);

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h3 className="card-title">Nhật Ký Hoạt Động</h3>
        </div>
        {petLogs.length > 0 && (
          <button className="btn btn-secondary btn-sm" onClick={onClear}>
            Xóa
          </button>
        )}
      </div>

      {petLogs.length === 0 ? (
        <EmptyState
          icon="🐾"
          title={isRunning ? 'Đang theo dõi hoạt động...' : 'Camera đang tắt'}
        />
      ) : (
        <>
          <ul className="timeline-list">
            {pagedLogs.map((log) => (
              <li key={log.id} className={`timeline-item border-${log.state}`}>
                <strong>{log.label}</strong>
                <span className="timeline-time">{log.time}</span>
              </li>
            ))}
          </ul>

          <Pagination
            currentPage={page}
            totalPages={totalPages}
            totalItems={petLogs.length}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  );
}
