export function groupBarnsByZone(barns = []) {
  const zones = new Map();
  for (const barn of barns) {
    const name = barn.zone?.trim() || 'Chưa phân khu';
    if (!zones.has(name)) zones.set(name, { name, barns: [] });
    zones.get(name).barns.push(barn);
  }
  return [...zones.values()];
}

// Resolve every level within its parent, including stale saved selections.
// A changed or missing parent resets its children to their defaults.
export function resolveBarnSelection(barns = [], devices = [], selection = {}) {
  const zones = groupBarnsByZone(barns);
  const zone = zones.find((item) => item.name === selection.zone) || zones[0];
  const sameZone = Boolean(zone && zone.name === selection.zone);
  const zoneBarns = zone?.barns || [];
  const currentBarn = (sameZone && zoneBarns.find((barn) => String(barn.id) === selection.barnId)) || zoneBarns[0];
  const barnId = currentBarn ? String(currentBarn.id) : '';
  const sameBarn = sameZone && barnId === selection.barnId;
  const barnDevices = devices.filter((device) => (
    barnId && device.barn_id != null && String(device.barn_id) === barnId
  ));
  const currentDev = (sameBarn && barnDevices.find((device) => device.device_id === selection.deviceId)) || barnDevices[0];
  const sameDevice = sameBarn && currentDev?.device_id === selection.deviceId;
  const sensors = Array.isArray(currentDev?.sensors)
    ? currentDev.sensors.filter((sensor) => sensor?.name)
    : [];
  const currentSensor = (sameDevice && sensors.find((sensor) => sensor.name === selection.sensorName))
    || sensors.find((sensor) => sensor.name === 'room') || sensors[0];

  return {
    zones, zoneBarns, barnDevices, sensors, currentBarn, currentDev, currentSensor,
    selection: {
      zone: zone?.name || '',
      barnId,
      deviceId: currentDev?.device_id || '',
      sensorName: currentSensor?.name || '',
    },
  };
}
