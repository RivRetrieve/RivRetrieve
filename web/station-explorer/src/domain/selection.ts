import type { StationRecord } from "./types";

/** Stable provider-qualified key preserving leading zeros and exact identifiers. */
export function stationKey(
  station: Pick<StationRecord, "provider_id" | "station_id">,
): string {
  return JSON.stringify([station.provider_id, station.station_id]);
}

/** Add stations to a selection while preserving order and deduplicating by provider/station key. */
export function addStations(
  selected: StationRecord[],
  additions: StationRecord[],
): StationRecord[] {
  if (!additions.length) return selected;
  const map = new Map<string, StationRecord>();
  for (const station of selected) map.set(station.key, station);
  let changed = false;
  for (const station of additions) {
    if (!map.has(station.key)) {
      map.set(station.key, station);
      changed = true;
    }
  }
  return changed ? Array.from(map.values()) : selected;
}

/** Remove one station by its provider-qualified key. */
export function removeStation(
  selected: StationRecord[],
  key: string,
): StationRecord[] {
  return selected.filter((station) => station.key !== key);
}

/** Remove all stations whose keys belong to the provided set. */
export function removeStationKeys(
  selected: StationRecord[],
  keysToRemove: ReadonlySet<string>,
): StationRecord[] {
  if (!keysToRemove.size) return selected;
  return selected.filter((station) => !keysToRemove.has(station.key));
}
