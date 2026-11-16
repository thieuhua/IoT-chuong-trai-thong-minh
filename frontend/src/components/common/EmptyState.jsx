import React from 'react';

export default function EmptyState({ icon = '📋', title, message }) {
  return (
    <div className="empty-state-box">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      {message && <p>{message}</p>}
    </div>
  );
}
