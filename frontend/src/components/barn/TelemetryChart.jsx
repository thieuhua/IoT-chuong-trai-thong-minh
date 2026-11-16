import React from 'react';

export default function TelemetryChart({ chartData }) {
  if (!chartData || chartData.length === 0) {
    return (
      <div className="chart-empty-box">
        Đang chờ dữ liệu đo từ cảm biến...
      </div>
    );
  }

  return (
    <div className="chart-wrapper">
      <svg viewBox="0 0 600 160" className="chart-svg">
        <line x1="40" y1="30" x2="580" y2="30" stroke="rgba(255,255,255,0.06)" />
        <line x1="40" y1="75" x2="580" y2="75" stroke="rgba(255,255,255,0.06)" />
        <line x1="40" y1="120" x2="580" y2="120" stroke="rgba(255,255,255,0.06)" />

        {chartData.map((pt, i) => {
          const x = 50 + (i * 500) / Math.max(1, chartData.length - 1);
          return (
            <g key={i}>
              {pt.temp !== null && (
                <circle
                  cx={x}
                  cy={Math.max(20, Math.min(130, 110 - (pt.temp - 25) * 10))}
                  r="5"
                  fill="#f59e0b"
                />
              )}
              {pt.hum !== null && (
                <circle
                  cx={x}
                  cy={Math.max(20, Math.min(130, 140 - pt.hum))}
                  r="5"
                  fill="#0ea5e9"
                />
              )}
              <text x={x} y="150" fill="#94a3b8" fontSize="10" textAnchor="middle">
                {pt.time}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="chart-legend">
        <span className="legend-amber">● Nhiệt độ (°C)</span>
        <span className="legend-blue">● Độ ẩm (%)</span>
      </div>
    </div>
  );
}
