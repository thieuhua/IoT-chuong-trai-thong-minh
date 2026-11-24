import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import { METRICS, metricStats, metricSegments, valueAxis, timeTicks, linePath, bandPath } from './telemetryChartUtils';

const RANGES = [[1, '1 giờ'], [6, '6 giờ'], [24, '24 giờ'], [72, '3 ngày'], [168, '7 ngày']];
const number = (value) => value.toLocaleString('vi-VN', { maximumFractionDigits: 2 });
const clock = (time, seconds = false) => new Date(time).toLocaleTimeString('vi-VN', {
  hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}),
});
const date = (time) => {
  const value = new Date(time);
  return `${String(value.getDate()).padStart(2, '0')}/${String(value.getMonth() + 1).padStart(2, '0')}`;
};

export default function TelemetryChart({ series, sensors = [], rangeHours, onRangeChange, loading, error, refreshSeconds = 30 }) {
  const [sensor, setSensor] = useState('room');
  const [hovered, setHovered] = useState(null);
  const [width, setWidth] = useState(900);
  const stage = useRef(null);
  const clipId = `telemetry-${useId().replace(/:/g, '')}`;

  useEffect(() => {
    if (!stage.current || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0) setWidth(Math.max(180, Math.round(entry.contentRect.width)));
    });
    observer.observe(stage.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => setHovered(null), [series, sensor]);

  const sensorNames = useMemo(() => {
    const names = new Set(['room']);
    if (Array.isArray(sensors)) sensors.forEach((item) => { if (item.name) names.add(item.name); });
    for (const bucket of series?.buckets || []) Object.keys(bucket.readings).forEach((name) => names.add(name));
    names.add(sensor);
    return [...names];
  }, [series, sensors, sensor]);

  const plots = useMemo(() => METRICS.map((metric) => {
    const segments = metricSegments(series, sensor, metric);
    const axis = valueAxis(segments, metric.key === 'temperature' ? 20 : 0, metric.key === 'temperature' ? 40 : 100);
    return { ...metric, segments, axis };
  }), [series, sensor]);

  const height = width < 480 ? 300 : 340;
  const left = 52;
  const right = width - 52;
  const top = 36;
  const bottom = height - 38;
  const since = Date.parse(series?.since);
  const until = Date.parse(series?.until);
  const valid = Number.isFinite(since) && until > since;
  const x = (time) => left + ((time - since) / (until - since)) * (right - left);
  const y = (value, axis) => bottom - ((value - axis.min) / (axis.max - axis.min)) * (bottom - top);
  const tempY = (value) => y(value, plots[0].axis);
  const showDates = rangeHours > 24;
  const ticks = valid ? timeTicks(since, until, right - left, showDates) : [];
  const bucket = hovered === null ? null : series?.buckets?.[hovered];
  const bucketStart = bucket ? Date.parse(bucket.time) : null;
  const bucketEnd = bucket ? Math.min(bucketStart + series.bucket_s * 1000, until) : null;
  const hoverX = bucket ? x((bucketStart + bucketEnd) / 2) : 0;
  const tooltipWidth = Math.min(270, width - 16);
  const tooltipLeft = Math.max(8, Math.min(width - tooltipWidth - 8, hoverX + 12));
  const hasData = plots.some((plot) => plot.segments.length > 0);

  const movePointer = (event) => {
    if (!valid || !series.buckets.length) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const pointerX = ((event.clientX - rect.left) / rect.width) * width;
    const pointerY = ((event.clientY - rect.top) / rect.height) * height;
    if (pointerX < left || pointerX > right || pointerY < top || pointerY > bottom) {
      setHovered(null);
      return;
    }
    const time = since + ((pointerX - left) / (right - left)) * (until - since);
    setHovered(Math.min(series.buckets.length - 1, Math.max(0, Math.floor((time - since) / (series.bucket_s * 1000)))));
  };

  const moveKeyboard = (event) => {
    const last = (series?.buckets?.length || 0) - 1;
    if (last < 0) return;
    if (['ArrowLeft', 'ArrowRight', 'Home', 'End', 'Escape'].includes(event.key)) event.preventDefault();
    if (event.key === 'Escape') setHovered(null);
    if (event.key === 'Home') setHovered(0);
    if (event.key === 'End') setHovered(last);
    if (event.key === 'ArrowLeft') setHovered((value) => Math.max(0, (value ?? last + 1) - 1));
    if (event.key === 'ArrowRight') setHovered((value) => Math.min(last, (value ?? -1) + 1));
  };

  return (
    <div className="chart-wrapper">
      <div className="chart-controls">
        <label className="chart-control">
          <span>Khoảng thời gian</span>
          <select className="select-control" value={rangeHours} onChange={(event) => onRangeChange(Number(event.target.value))}>
            {RANGES.map(([hours, label]) => <option key={hours} value={hours}>{label}</option>)}
          </select>
        </label>
        <label className="chart-control">
          <span>Cảm biến</span>
          <select className="select-control" value={sensor} onChange={(event) => setSensor(event.target.value)}>
            {sensorNames.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
        </label>
        <span className="chart-status" role="status">
          {loading ? 'Đang tải…' : series ? `Cập nhật ${clock(until, true)}` : 'Chưa có dữ liệu'} · Tự làm mới {refreshSeconds} giây
        </span>
      </div>
      {error && <p className="chart-error" role="alert">{error}{series ? ' Đang hiển thị dữ liệu lần tải trước.' : ''}</p>}

      <div className="chart-stage" ref={stage}>
        {!valid ? (
          <div className="chart-empty-box">{loading ? 'Đang tải dữ liệu đo…' : 'Chưa tải được dữ liệu đo.'}</div>
        ) : (
          <>
            <svg
              viewBox={`0 0 ${width} ${height}`} className="chart-svg" style={{ height }}
              role="img" aria-label={`Nhiệt độ và độ ẩm cảm biến ${sensor}. Dùng phím mũi tên để xem từng thời điểm.`}
              tabIndex={0} onKeyDown={moveKeyboard} onBlur={() => setHovered(null)}
              onPointerMove={movePointer} onPointerDown={movePointer} onPointerLeave={() => setHovered(null)}
            >
              <defs><clipPath id={clipId}><rect x={left} y={top} width={right - left} height={bottom - top} /></clipPath></defs>
              <text x={left} y="18" className="chart-axis-title legend-amber">{width < 480 ? '°C' : 'Nhiệt độ (°C)'}</text>
              <text x={right} y="18" textAnchor="end" className="chart-axis-title legend-blue">{width < 480 ? '%' : 'Độ ẩm (%)'}</text>
              {plots[0].axis.ticks.map((tick) => (
                <g key={tick}>
                  <line x1={left} x2={right} y1={tempY(tick)} y2={tempY(tick)} className="chart-grid" />
                  <text x={left - 9} y={tempY(tick)} dy="0.35em" textAnchor="end" className="chart-tick legend-amber">{number(tick)}</text>
                </g>
              ))}
              {plots[1].axis.ticks.map((tick) => (
                <g key={tick}>
                  <line x1={right} x2={right + 4} y1={y(tick, plots[1].axis)} y2={y(tick, plots[1].axis)} className="chart-axis" />
                  <text x={right + 9} y={y(tick, plots[1].axis)} dy="0.35em" className="chart-tick legend-blue">{number(tick)}</text>
                </g>
              ))}
              {ticks.map((tick) => (
                <g key={tick}>
                  <line x1={x(tick)} x2={x(tick)} y1={top} y2={bottom} className="chart-grid" />
                  <text x={x(tick)} y={bottom + 23} textAnchor="middle" className="chart-tick">{showDates ? date(tick) : clock(tick)}</text>
                </g>
              ))}
              <path d={`M${left},${top} V${bottom} H${right} V${top}`} className="chart-axis" />
              <g clipPath={`url(#${clipId})`}>
                {plots.map((plot) => (
                  <g key={plot.key} fill={plot.color} stroke={plot.color}>
                    {plot.segments.map((segment, i) => segment.length === 1 ? (
                      <g key={i}>
                        <line x1={x(segment[0].time)} x2={x(segment[0].time)} y1={y(segment[0].min, plot.axis)} y2={y(segment[0].max, plot.axis)} strokeWidth="7" opacity="0.16" />
                        <circle cx={x(segment[0].time)} cy={y(segment[0].avg, plot.axis)} r="2.5" stroke="none" />
                      </g>
                    ) : (
                      <g key={i}>
                        <path d={bandPath(segment, x, (value) => y(value, plot.axis))} opacity="0.16" stroke="none" />
                        <path d={linePath(segment, x, (value) => y(value, plot.axis))} fill="none" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
                      </g>
                    ))}
                  </g>
                ))}
                {[{ value: 32, label: 'Quạt 32 °C', color: '#a78bfa' }, { value: 35, label: 'Cảnh báo 35 °C', color: '#f87171' }].map((reference) => (
                  <g key={reference.value}>
                    <line x1={left} x2={right} y1={tempY(reference.value)} y2={tempY(reference.value)} stroke={reference.color} strokeDasharray="6 5" />
                    <text x={right - 6} y={tempY(reference.value) + (reference.value === 32 && Math.abs(tempY(35) - tempY(32)) < 20 ? 15 : -6)} textAnchor="end" fill={reference.color} className="chart-reference-label">{reference.label}</text>
                  </g>
                ))}
                {bucket && (
                  <g>
                    <line x1={hoverX} x2={hoverX} y1={top} y2={bottom} className="chart-crosshair" />
                    {plots.map((plot) => {
                      const stats = metricStats(bucket, sensor, plot);
                      return stats && <circle key={plot.key} cx={hoverX} cy={y(stats.avg, plot.axis)} r="4" fill={plot.color} stroke="#0f172a" strokeWidth="2" />;
                    })}
                  </g>
                )}
              </g>
            </svg>
            {!hasData && <div className="chart-no-data">Không có dữ liệu nhiệt độ / độ ẩm cho cảm biến {sensor} trong khoảng này.</div>}
            {bucket && (
              <div className="chart-tooltip" style={{ left: tooltipLeft, width: tooltipWidth }}>
                <strong>{date(bucketStart)} · {clock(bucketStart, true)} – {date(bucketEnd) !== date(bucketStart) ? `${date(bucketEnd)} ` : ''}{clock(bucketEnd, true)}</strong>
                {plots.map((plot) => {
                  const stats = metricStats(bucket, sensor, plot);
                  return (
                    <div className="chart-tooltip-metric" key={plot.key}>
                      <span style={{ color: plot.color }}>{plot.label}: {stats ? `${number(stats.avg)} ${plot.unit}` : 'Không có dữ liệu'}</span>
                      {stats && <small>Min–max: {number(stats.min)}–{number(stats.max)} {plot.unit} · {stats.count} mẫu</small>}
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}
      </div>
      <div className="chart-legend">
        <span className="legend-amber">● Nhiệt độ (°C, trục trái)</span>
        <span className="legend-blue">● Độ ẩm (%, trục phải)</span>
        <span className="chart-legend-note">Đường: trung bình · Dải mờ: min–max</span>
      </div>
      {valid && <p className="chart-caption">Giờ địa phương · {date(since)} {clock(since)} – {date(until)} {clock(until)} · Khoảng trống: không có mẫu đo</p>}
    </div>
  );
}
