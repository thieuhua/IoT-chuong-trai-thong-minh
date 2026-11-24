import assert from 'node:assert/strict';
import test from 'node:test';
import { groupBarnsByZone, resolveBarnSelection } from './barnSelectionUtils.js';

const barns = [
  { id: 'a1', name: 'Chuồng 1', zone: 'Khu A' },
  { id: 'b1', name: 'Chuồng 2', zone: 'Khu B' },
  { id: 'a2', name: 'Chuồng 3', zone: 'Khu A' },
  { id: 'empty', name: 'Chuồng trống', zone: 'Khu A' },
];
const devices = [
  { device_id: 'unassigned', barn_id: null, sensors: [{ name: 'room' }] },
  { device_id: 'd1', barn_id: 'a1', sensors: [{ name: 'yard' }, { name: 'room' }] },
  { device_id: 'd2', barn_id: 'a1', sensors: [{ name: 'soil' }, { name: 'room' }] },
  { device_id: 'd3', barn_id: 'b1', sensors: [{ name: 'yard' }, { name: 'water' }] },
  { device_id: 'd4', barn_id: 'a2', sensors: [] },
  { device_id: 'blank', barn_id: '', sensors: [{ name: 'room' }] },
  { device_id: 'orphan', barn_id: 'deleted', sensors: [{ name: 'room' }] },
];

test('groups barns by zone in input order and normalizes unzoned barns', () => {
  const input = [...barns,
    { id: 'n1', zone: null }, { id: 'n2', zone: '' },
    { id: 'n3', zone: '  ' }, { id: 'n4' }, { id: 'a3', zone: ' Khu A ' },
  ];
  const snapshot = structuredClone(input);
  const groups = groupBarnsByZone(input);
  assert.deepEqual(groups.map((group) => group.name), ['Khu A', 'Khu B', 'Chưa phân khu']);
  assert.deepEqual(groups[0].barns.map((barn) => barn.id), ['a1', 'a2', 'empty', 'a3']);
  assert.deepEqual(groups[2].barns.map((barn) => barn.id), ['n1', 'n2', 'n3', 'n4']);
  assert.deepEqual(input, snapshot);
});

test('defaults to the first barn and assigned device, preferring the room sensor', () => {
  const view = resolveBarnSelection(barns, devices);
  assert.deepEqual(view.selection, { zone: 'Khu A', barnId: 'a1', deviceId: 'd1', sensorName: 'room' });
  assert.deepEqual(view.zoneBarns.map((barn) => barn.id), ['a1', 'a2', 'empty']);
  assert.deepEqual(view.barnDevices.map((device) => device.device_id), ['d1', 'd2']);
});

test('restores valid saved selections, including a non-default device and sensor', () => {
  const saved = { zone: 'Khu A', barnId: 'a1', deviceId: 'd2', sensorName: 'soil' };
  const view = resolveBarnSelection(barns, devices, saved);
  assert.deepEqual(view.selection, saved);
  assert.equal(view.currentDev, devices[2]);
  assert.equal(view.currentSensor.name, 'soil');
});

test('changing a zone or barn resets all descendants within the new parent', () => {
  const saved = { zone: 'Khu B', barnId: 'a1', deviceId: 'd2', sensorName: 'room' };
  assert.deepEqual(resolveBarnSelection(barns, devices, saved).selection,
    { zone: 'Khu B', barnId: 'b1', deviceId: 'd3', sensorName: 'yard' });
  assert.deepEqual(resolveBarnSelection(barns, devices, { zone: 'Khu A', barnId: 'a2' }).selection,
    { zone: 'Khu A', barnId: 'a2', deviceId: 'd4', sensorName: '' });
  assert.deepEqual(resolveBarnSelection(barns, devices, { zone: 'Khu A', barnId: 'a1', deviceId: 'd2' }).selection,
    { zone: 'Khu A', barnId: 'a1', deviceId: 'd2', sensorName: 'room' });
});

test('removed zones, barns, devices and sensors fall back to valid defaults', () => {
  const saved = { zone: 'Khu A', barnId: 'a1', deviceId: 'd2', sensorName: 'soil' };
  const withoutDevice = devices.filter((device) => device.device_id !== 'd2');
  assert.equal(resolveBarnSelection(barns, withoutDevice, saved).selection.deviceId, 'd1');
  const withoutSensor = devices.map((device) => device.device_id === 'd2'
    ? { ...device, sensors: [{ name: 'room' }] } : device);
  assert.equal(resolveBarnSelection(barns, withoutSensor, saved).selection.sensorName, 'room');
  const withoutBarn = barns.filter((barn) => barn.id !== 'a1');
  assert.deepEqual(resolveBarnSelection(withoutBarn, devices, saved).selection,
    { zone: 'Khu A', barnId: 'a2', deviceId: 'd4', sensorName: '' });
  assert.deepEqual(resolveBarnSelection(barns.filter((barn) => barn.zone !== 'Khu A'), devices, saved).selection,
    { zone: 'Khu B', barnId: 'b1', deviceId: 'd3', sensorName: 'yard' });
});

test('empty levels never borrow devices or sensors from other parents', () => {
  const empty = resolveBarnSelection(barns, devices, { zone: 'Khu A', barnId: 'empty' });
  assert.deepEqual(empty.barnDevices, []);
  assert.deepEqual(empty.sensors, []);
  assert.equal(empty.selection.deviceId, '');
  assert.deepEqual(resolveBarnSelection([], devices).selection,
    { zone: '', barnId: '', deviceId: '', sensorName: '' });
  assert.equal(resolveBarnSelection(barns, []).selection.deviceId, '');
  assert.equal(resolveBarnSelection(barns, [{ device_id: 'missing', barn_id: 'a1' }]).selection.sensorName, '');
});

test('numeric barn ids match select values without admitting unassigned devices', () => {
  const view = resolveBarnSelection([{ id: 7, zone: null }], [
    { device_id: 'd7', barn_id: 7, sensors: [{ name: 'temp' }] },
    ...devices,
  ], { zone: 'Chưa phân khu', barnId: '7', deviceId: 'd7', sensorName: 'temp' });
  assert.deepEqual(view.barnDevices.map((device) => device.device_id), ['d7']);
  assert.equal(view.selection.sensorName, 'temp');
});

test('multiple sensors use device subtabs and include the selected sensor in the breadcrumb', () => {
  const view = resolveBarnSelection(barns, devices, {
    zone: 'Khu A', barnId: 'a1', deviceId: 'd2', sensorName: 'soil',
  });
  assert.equal(view.showSensorTabs, true);
  assert.equal(view.breadcrumb, 'Khu A / Chuồng 1 / d2 / soil');
  const switched = resolveBarnSelection(barns, devices, { ...view.selection, sensorName: 'room' });
  assert.equal(switched.breadcrumb, 'Khu A / Chuồng 1 / d2 / room');
});

test('one sensor stays selected without subtabs or a sensor breadcrumb', () => {
  const view = resolveBarnSelection(barns, [{
    device_id: 'single', name: 'Thiết bị 1', barn_id: 'a1',
    sensors: [null, {}, { name: '' }, { name: 'room' }],
  }], { zone: 'Khu A', barnId: 'a1', deviceId: 'single', sensorName: 'removed' });
  assert.equal(view.showSensorTabs, false);
  assert.equal(view.currentSensor.name, 'room');
  assert.equal(view.breadcrumb, 'Khu A / Chuồng 1 / Thiết bị 1');
});

test('devices without sensors and empty barns have no sensor navigation', () => {
  const view = resolveBarnSelection(barns, devices, { zone: 'Khu A', barnId: 'a2' });
  assert.equal(view.showSensorTabs, false);
  assert.equal(view.breadcrumb, 'Khu A / Chuồng 3 / d4');
  const empty = resolveBarnSelection(barns, devices, { zone: 'Khu A', barnId: 'empty' });
  assert.equal(empty.showSensorTabs, false);
  assert.equal(empty.breadcrumb, 'Khu A / Chuồng trống');
  assert.equal(resolveBarnSelection().breadcrumb, '');
});
