import { groupBarnsByZone } from '../barn/barnSelectionUtils.js';

export function groupPermissionBarns(barns = [], devices = []) {
  const devicesByBarn = new Map();
  for (const device of devices) {
    if (device.barn_id == null || device.barn_id === '') continue;
    const barnId = String(device.barn_id);
    if (!devicesByBarn.has(barnId)) devicesByBarn.set(barnId, []);
    devicesByBarn.get(barnId).push(device);
  }
  return groupBarnsByZone(barns).map((zone) => ({
    ...zone,
    barns: zone.barns.map((barn) => ({ ...barn, devices: devicesByBarn.get(String(barn.id)) || [] })),
  }));
}

export function getBarnSelectionState(barns = [], selectedBarnIds = []) {
  const selected = new Set(selectedBarnIds.map(String));
  const selectedCount = barns.filter((barn) => selected.has(String(barn.id))).length;
  return {
    checked: barns.length > 0 && selectedCount === barns.length,
    indeterminate: selectedCount > 0 && selectedCount < barns.length,
  };
}

// Zone and barn checkboxes both update the same barn-level grants.
export function setBarnsSelected(selectedBarnIds = [], barns = [], checked = true) {
  const selected = new Map(selectedBarnIds.map((id) => [String(id), id]));
  for (const barn of barns) {
    if (checked) selected.set(String(barn.id), barn.id);
    else selected.delete(String(barn.id));
  }
  return [...selected.values()];
}

export function summarizeBarnPermissions(zones = [], selectedBarnIds = []) {
  const selected = new Set(selectedBarnIds.map(String));
  const labels = zones.flatMap((zone) => (
    getBarnSelectionState(zone.barns, selectedBarnIds).checked
      ? [`${zone.name} (toàn bộ)`]
      : zone.barns.filter((barn) => selected.has(String(barn.id))).map((barn) => barn.name || String(barn.id))
  ));
  return labels.join(', ') || 'Chưa được phân quyền';
}
