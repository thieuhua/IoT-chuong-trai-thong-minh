export const METRICS = [
  { key: 'temperature', aliases: ['temperature', 'temp'], label: 'Nhiệt độ', unit: '°C', color: '#f59e0b' },
  { key: 'humidity', aliases: ['humidity', 'hum'], label: 'Độ ẩm', unit: '%', color: '#0ea5e9' },
];

export function metricStats(bucket, sensor, metric) {
  const fields = bucket?.readings?.[sensor];
  for (const alias of metric.aliases) {
    const stats = fields?.[alias];
    if (stats?.count > 0 && [stats.avg, stats.min, stats.max].every(Number.isFinite)) return stats;
  }
  return null;
}

// Split each metric independently: a missing humidity sample must not erase
// temperature, and no path or min/max band may bridge an empty time bucket.
export function metricSegments(series, sensor, metric) {
  const segments = [];
  let current = null;
  let previousTime = null;
  for (const bucket of series?.buckets || []) {
    const stats = metricStats(bucket, sensor, metric);
    const start = Date.parse(bucket.time);
    if (!stats || !Number.isFinite(start)) {
      current = null;
      previousTime = null;
      continue;
    }
    if (!current || start - previousTime > series.bucket_s * 1000 * 1.5) {
      current = [];
      segments.push(current);
    }
    const end = Math.min(start + series.bucket_s * 1000, Date.parse(series.until));
    current.push({ ...stats, time: (start + end) / 2 });
    previousTime = start;
  }
  return segments;
}

export function valueAxis(segments, defaultMin, defaultMax) {
  let min = defaultMin;
  let max = defaultMax;
  for (const segment of segments) {
    for (const point of segment) {
      min = Math.min(min, point.min);
      max = Math.max(max, point.max);
    }
  }
  const rawStep = (max - min) / 4;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const step = [1, 2, 2.5, 5, 10].find((n) => n * magnitude >= rawStep) * magnitude;
  min = Math.floor(min / step) * step;
  max = Math.ceil(max / step) * step;
  const ticks = Array.from({ length: Math.round((max - min) / step) + 1 }, (_, i) => min + i * step);
  return { min, max, ticks };
}

export function timeTicks(since, until, plotWidth, showDates) {
  const count = Math.max(2, Math.floor(plotWidth / 80));
  const targetMs = (until - since) / count;
  const ticks = [];
  const midnight = new Date(since);
  midnight.setHours(0, 0, 0, 0);
  if (showDates) {
    const days = [1, 2, 3, 7, 14].find((n) => n * 86400000 >= targetMs) || 14;
    // Calendar days keep date labels at local midnight even across DST changes.
    const tick = new Date(midnight);
    while (tick.getTime() < since) tick.setDate(tick.getDate() + days);
    while (tick.getTime() <= until) {
      ticks.push(tick.getTime());
      tick.setDate(tick.getDate() + days);
    }
  } else {
    const minutes = [5, 10, 15, 30, 60, 120, 180, 360, 720, 1440]
      .find((n) => n * 60000 >= targetMs) || 1440;
    const step = minutes * 60000;
    const first = midnight.getTime() + Math.ceil((since - midnight.getTime()) / step) * step;
    for (let tick = first; tick <= until; tick += step) ticks.push(tick);
  }
  return ticks.length < 2 ? [since, until] : ticks;
}

export function linePath(segment, x, y) {
  return segment.map((point, i) => `${i ? 'L' : 'M'}${x(point.time)},${y(point.avg)}`).join(' ');
}

export function bandPath(segment, x, y) {
  const upper = segment.map((point, i) => `${i ? 'L' : 'M'}${x(point.time)},${y(point.max)}`);
  const lower = [...segment].reverse().map((point) => `L${x(point.time)},${y(point.min)}`);
  return `${upper.join(' ')} ${lower.join(' ')} Z`;
}
