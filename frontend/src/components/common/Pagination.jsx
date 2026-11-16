import React from 'react';

/**
 * Reusable Pagination component
 * @param {number} currentPage - Current active page (1-indexed)
 * @param {number} totalPages - Total number of pages
 * @param {function} onPageChange - Callback when page changes: (page) => void
 * @param {number} totalItems - Optional total items count
 */
export default function Pagination({
  currentPage,
  totalPages,
  onPageChange,
  totalItems,
}) {
  if (totalPages <= 1) return null;

  // Generate range of page numbers around current page
  const getPageNumbers = () => {
    const pages = [];
    const delta = 2; // how many pages before and after current
    const left = Math.max(1, currentPage - delta);
    const right = Math.min(totalPages, currentPage + delta);

    for (let i = left; i <= right; i++) {
      pages.push(i);
    }
    return pages;
  };

  const pages = getPageNumbers();

  return (
    <div className="pagination-bar">
      <div className="pagination-info">
        {totalItems !== undefined && (
          <span className="total-items-text">Tổng số: {totalItems}</span>
        )}
      </div>

      <div className="pagination-controls">
        <button
          className="btn btn-secondary btn-xs"
          disabled={currentPage <= 1}
          onClick={() => onPageChange(currentPage - 1)}
          aria-label="Trang trước"
        >
          &larr; Trang trước
        </button>

        {pages[0] > 1 && (
          <>
            <button
              className={`btn btn-xs ${currentPage === 1 ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => onPageChange(1)}
            >
              1
            </button>
            {pages[0] > 2 && <span className="pagination-ellipsis">...</span>}
          </>
        )}

        {pages.map((p) => (
          <button
            key={p}
            className={`btn btn-xs ${p === currentPage ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => onPageChange(p)}
          >
            {p}
          </button>
        ))}

        {pages[pages.length - 1] < totalPages && (
          <>
            {pages[pages.length - 1] < totalPages - 1 && (
              <span className="pagination-ellipsis">...</span>
            )}
            <button
              className={`btn btn-xs ${currentPage === totalPages ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => onPageChange(totalPages)}
            >
              {totalPages}
            </button>
          </>
        )}

        <button
          className="btn btn-secondary btn-xs"
          disabled={currentPage >= totalPages}
          onClick={() => onPageChange(currentPage + 1)}
          aria-label="Trang sau"
        >
          Trang sau &rarr;
        </button>
      </div>

      <span className="page-indicator">
        Trang {currentPage} / {totalPages}
      </span>
    </div>
  );
}
