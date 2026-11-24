import assert from 'node:assert/strict';
import test from 'node:test';
import {
  groupPermissionBarns, getBarnSelectionState, setBarnsSelected, summarizeBarnPermissions,
} from './userPermissionUtils.js';

const barns = [
  { id: 'a1', name: 'Chuồng 1', zone: 'Khu A' },
  { id: 'b1', name: 'Chuồng X', zone: 'Khu B' },
  { id: 'a2', name: 'Chuồng 2', zone: ' Khu A ' },
  { id: 'b2', name: 'Chuồng Y', zone: 'Khu B' },
  { id: 'n1', name: 'Chuồng chưa phân khu', zone: null },
  { id: 'n2', name: 'Chuồng chưa phân khu 2', zone: '  ' },
];

test('permission hierarchy groups zones and only lists each barn\'s devices without mutating inputs', () => {
  const devices = [
    { device_id: 'unassigned', barn_id: null },
    { device_id: 'blank', barn_id: '' },
    { device_id: 'orphan', barn_id: 'deleted' },
    { device_id: 'd1', name: 'Cảm biến', barn_id: 'a1', online: true },
    { device_id: 'd2', barn_id: 'a1', online: false },
    { device_id: 'd3', barn_id: 'b1', online: true },
  ];
  const snapshot = structuredClone({ barns, devices });
  const zones = groupPermissionBarns(barns, devices);
  assert.deepEqual(zones.map((zone) => zone.name), ['Khu A', 'Khu B', 'Chưa phân khu']);
  assert.deepEqual(zones[0].barns.map((barn) => barn.id), ['a1', 'a2']);
  assert.deepEqual(zones[2].barns.map((barn) => barn.id), ['n1', 'n2']);
  assert.deepEqual(zones[0].barns[0].devices, [devices[3], devices[4]]);
  assert.deepEqual(zones[0].barns[1].devices, []);
  assert.deepEqual(zones[1].barns[0].devices, [devices[5]]);
  assert.deepEqual(zones[2].barns[0].devices, []);
  assert.deepEqual({ barns, devices }, snapshot);
});

test('missing and empty zone names share the unzoned group and empty levels stay empty', () => {
  const zones = groupPermissionBarns([{ id: 'x' }, { id: 'y', zone: '' }]);
  assert.equal(zones.length, 1);
  assert.equal(zones[0].name, 'Chưa phân khu');
  assert.deepEqual(zones[0].barns.map((barn) => barn.devices), [[], []]);
  assert.deepEqual(groupPermissionBarns(), []);
  assert.deepEqual(groupPermissionBarns([], [{ device_id: 'd1', barn_id: 'a1' }]), []);
});

test('zone checkbox reflects none, partial and all grants, ignoring duplicate or unrelated ids', () => {
  const zoneBarns = groupPermissionBarns(barns)[0].barns;
  assert.deepEqual(getBarnSelectionState(zoneBarns, ['b1', 'deleted']), { checked: false, indeterminate: false });
  assert.deepEqual(getBarnSelectionState(zoneBarns, ['a1', 'a1', 'b1']), { checked: false, indeterminate: true });
  assert.deepEqual(getBarnSelectionState(zoneBarns, ['a2', 'a1', 'b1']), { checked: true, indeterminate: false });
  assert.deepEqual(getBarnSelectionState([], ['a1']), { checked: false, indeterminate: false });
  assert.deepEqual(getBarnSelectionState(), { checked: false, indeterminate: false });
});

test('selecting a zone adds all its barns once and preserves grants in other zones', () => {
  const zoneBarns = groupPermissionBarns(barns)[0].barns;
  const selected = ['b1', 'a1'];
  const snapshot = structuredClone(zoneBarns);
  const result = setBarnsSelected(selected, zoneBarns, true);
  assert.deepEqual(result, ['b1', 'a1', 'a2']);
  assert.deepEqual(setBarnsSelected(result, zoneBarns, true), result);
  assert.deepEqual(getBarnSelectionState(zoneBarns, result), { checked: true, indeterminate: false });
  assert.deepEqual(selected, ['b1', 'a1']);
  assert.deepEqual(zoneBarns, snapshot);
});

test('clearing a full or partial zone removes only that zone\'s barn grants', () => {
  const zoneBarns = groupPermissionBarns(barns)[0].barns;
  assert.deepEqual(setBarnsSelected(['a1', 'b1', 'a2', 'n1'], zoneBarns, false), ['b1', 'n1']);
  assert.deepEqual(setBarnsSelected(['a1', 'b1'], zoneBarns, false), ['b1']);
  assert.deepEqual(setBarnsSelected(['b1'], [], true), ['b1']);
  assert.deepEqual(setBarnsSelected(), []);
});

test('individual barn changes update the parent zone through partial, full and empty states', () => {
  const zoneBarns = groupPermissionBarns(barns)[0].barns;
  let selected = setBarnsSelected([], [zoneBarns[0]], true);
  assert.deepEqual(getBarnSelectionState(zoneBarns, selected), { checked: false, indeterminate: true });
  selected = setBarnsSelected(selected, [zoneBarns[1]], true);
  assert.deepEqual(getBarnSelectionState(zoneBarns, selected), { checked: true, indeterminate: false });
  selected = setBarnsSelected(selected, [zoneBarns[0]], false);
  assert.deepEqual(getBarnSelectionState(zoneBarns, selected), { checked: false, indeterminate: true });
  selected = setBarnsSelected(selected, [zoneBarns[1]], false);
  assert.deepEqual(getBarnSelectionState(zoneBarns, selected), { checked: false, indeterminate: false });
});

test('numeric barn ids match string grants and device references across every permission operation', () => {
  const zones = groupPermissionBarns([{ id: 7, name: 'Chuồng 7' }], [{ device_id: 'd7', barn_id: '7' }]);
  assert.equal(zones[0].barns[0].devices[0].device_id, 'd7');
  assert.deepEqual(getBarnSelectionState(zones[0].barns, ['7']), { checked: true, indeterminate: false });
  assert.deepEqual(setBarnsSelected(['7', '7', 'other'], zones[0].barns, true), [7, 'other']);
  assert.deepEqual(setBarnsSelected(['7', 'other'], zones[0].barns, false), ['other']);
  assert.equal(summarizeBarnPermissions(zones, ['7']), 'Chưa phân khu (toàn bộ)');
});

test('summary compresses complete zones and names only selected barns in partial zones', () => {
  const zones = groupPermissionBarns(barns);
  assert.equal(summarizeBarnPermissions(zones, ['a1', 'b1', 'a2']), 'Khu A (toàn bộ), Chuồng X');
  assert.equal(summarizeBarnPermissions(zones, ['a1', 'a1', 'b1', 'deleted']), 'Chuồng 1, Chuồng X');
  assert.equal(summarizeBarnPermissions(zones, ['n1', 'n2']), 'Chưa phân khu (toàn bộ)');
  assert.equal(summarizeBarnPermissions(zones, ['n1']), 'Chuồng chưa phân khu');
  assert.equal(summarizeBarnPermissions(zones, barns.map((barn) => barn.id)),
    'Khu A (toàn bộ), Khu B (toàn bộ), Chưa phân khu (toàn bộ)');
});

test('summary handles missing grants, removed barns and unnamed barns without implying zone-wide access', () => {
  assert.equal(summarizeBarnPermissions(), 'Chưa được phân quyền');
  assert.equal(summarizeBarnPermissions(groupPermissionBarns(barns), ['deleted']), 'Chưa được phân quyền');
  assert.equal(summarizeBarnPermissions([{ name: 'Khu trống', barns: [] }], ['a1']), 'Chưa được phân quyền');
  const zones = groupPermissionBarns([{ id: 'x', zone: 'Khu A' }, { id: 'y', zone: 'Khu A' }]);
  assert.equal(summarizeBarnPermissions(zones, ['x']), 'x');
});
