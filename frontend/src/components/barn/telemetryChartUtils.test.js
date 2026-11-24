import assert from 'node:assert/strict';
import test from 'node:test';
import { METRICS, metricStats, metricSegments, valueAxis, timeTicks, linePath, bandPath } from './telemetryChartUtils.js';

const start = Date.parse('2026-11-20T00:00:00Z');
const stats = (avg, min = avg, max = avg) => ({ avg, min, max, count: 2 });
const makeSeries = (readings) => ({
  since: new Date(start).toISOString(), until: new Date(start + readings.length * 60000).toISOString(),
  bucket_s: 60,
  buckets: readings.map((value, i) => ({ time: new Date(start + i * 60000).toISOString(), readings: value })),
});

test('offline and field gaps split each metric without mixing sensors', () => {
  const series = makeSeries([
    { room: { temperature: stats(28, 27, 29), humidity: stats(60) }, yard: { temp: stats(99) } },
    { room: { temp: stats(30), hum: stats(65) } },
    {},
    { room: { temp: stats(31) } },
    { room: { temp: stats(32), hum: stats(70) } },
  ]);
  const temp = metricSegments(series, 'room', METRICS[0]);
  const hum = metricSegments(series, 'room', METRICS[1]);
  assert.deepEqual(temp.map((s) => s.length), [2, 2]);
  assert.deepEqual(hum.map((s) => s.length), [2, 1]);
  assert.deepEqual(temp.flat().map((p) => p.avg), [28, 30, 31, 32]);
  assert.deepEqual(metricSegments(series, 'missing', METRICS[0]), []);
  const line = linePath(temp[0], (time) => (time - start) / 1000, (value) => value);
  const band = bandPath(temp[0], (time) => (time - start) / 1000, (value) => value);
  assert.equal(line, 'M30,28 L90,30');
  assert.equal(band, 'M30,29 L90,30 L90,30 L30,27 Z');
  assert.equal(metricSegments(series, 'yard', METRICS[0])[0].length, 1);
});

test('empty series, zero values and non-finite data are handled', () => {
  assert.deepEqual(metricSegments(null, 'room', METRICS[0]), []);
  assert.deepEqual(metricSegments(makeSeries([{}, {}]), 'room', METRICS[0]), []);
  const series = makeSeries([{ room: { temp: stats(0), hum: stats(0) } }]);
  assert.equal(metricStats(series.buckets[0], 'room', METRICS[0]).avg, 0);
  series.buckets[0].readings.room.temp.avg = NaN;
  assert.equal(metricStats(series.buckets[0], 'room', METRICS[0]), null);
  series.buckets[0].readings.room.temp = { ...stats(25), count: 0 };
  assert.equal(metricStats(series.buckets[0], 'room', METRICS[0]), null);
});

test('missing bucket entries also split paths and the last partial bucket stays inside the window', () => {
  const series = makeSeries(Array.from({ length: 5 }, () => ({ room: { temp: stats(25) } })));
  series.until = new Date(start + 4 * 60000 + 20000).toISOString();
  series.buckets.splice(2, 1);
  const segments = metricSegments(series, 'room', METRICS[0]);
  assert.deepEqual(segments.map((s) => s.length), [2, 2]);
  assert.equal(segments[1][1].time, start + 4 * 60000 + 10000);
});

test('separate axes contain extrema and temperature reference values', () => {
  assert.deepEqual(valueAxis([], 20, 40).ticks, [20, 25, 30, 35, 40]);
  assert.deepEqual(valueAxis([], 0, 100).ticks, [0, 25, 50, 75, 100]);
  const axis = valueAxis([[stats(10, -18, 56)]], 20, 40);
  assert.ok(axis.min <= -18 && axis.max >= 56);
  assert.ok(axis.min < 32 && axis.max > 35);
  assert.ok(axis.ticks.every(Number.isFinite));
});

test('time ticks cover hour to week ranges without crowding narrow screens', () => {
  for (const hours of [1, 6, 24, 72, 168]) {
    const end = start + hours * 3600000;
    for (const width of [136, 280, 800]) {
      const ticks = timeTicks(start, end, width, hours > 24);
      assert.ok(ticks.length >= 2 && ticks.length <= 12);
      assert.ok(ticks.every((tick) => tick >= start && tick <= end));
      assert.ok(ticks.every((tick, i) => i === 0 || tick > ticks[i - 1]));
    }
  }
  const days = timeTicks(start, start + 7 * 86400000, 800, true);
  for (const tick of days) assert.equal(new Date(tick).getHours(), 0);
});
