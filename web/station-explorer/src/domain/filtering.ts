import { canonicalizeFrequency, frequencyError } from "./frequency";
import {
  physicalFields,
  type BrowseFilters,
  type Conflict,
  type FactProfile,
  type PhysicalField,
  type RequestSettings,
  type StationCatalogue,
  type StationRecord,
} from "./types";

function factFieldValue(
  profile: FactProfile,
  field: PhysicalField,
): string | null {
  const fact = profile[field];
  if (fact.state !== "known") return null;
  if (field === "frequency") return profile.canonicalFrequency;
  return fact.value;
}

/** Extract active physical request settings into `[field, targetValue]` pairs, returning null if frequency is invalid. */
export function resolveActiveSettings(
  settings: RequestSettings,
): [PhysicalField, string][] | null {
  const resolved: [PhysicalField, string][] = [];
  for (const field of physicalFields) {
    const raw = settings[field];
    if (raw === undefined || raw === "") continue;
    if (field === "frequency") {
      const canonical = canonicalizeFrequency(raw);
      if (canonical === null) return null;
      resolved.push([field, canonical]);
    } else {
      resolved.push([field, raw]);
    }
  }
  return resolved;
}

/**
 * Evaluate active physical settings once per unique fact profile and fact set.
 * Returns a lookup table indexed by `station.factSetIndex` (1 = matches, 0 = conflicts).
 */
export function compileSettingsMatcher(
  facts: FactProfile[],
  factSets: number[][],
  settings: RequestSettings,
): Uint8Array {
  const matchingFactSets = new Uint8Array(factSets.length);
  const resolved = resolveActiveSettings(settings);
  if (resolved === null) return matchingFactSets;

  const matchingFacts = new Uint8Array(facts.length);
  for (let i = 0; i < facts.length; i++) {
    const profile = facts[i];
    if (profile.admission !== "supported") continue;
    let ok = true;
    for (let j = 0; j < resolved.length; j++) {
      const [field, target] = resolved[j];
      if (factFieldValue(profile, field) !== target) {
        ok = false;
        break;
      }
    }
    if (ok) matchingFacts[i] = 1;
  }

  for (let s = 0; s < factSets.length; s++) {
    const indices = factSets[s];
    for (let k = 0; k < indices.length; k++) {
      if (matchingFacts[indices[k]]) {
        matchingFactSets[s] = 1;
        break;
      }
    }
  }
  return matchingFactSets;
}

/** Filter catalogue stations by browsing controls and physical measurement settings. */
export function filterCatalogueStations(
  catalogue: StationCatalogue,
  browse: BrowseFilters,
  settings: RequestSettings,
): StationRecord[] {
  if (
    !browse.provider &&
    !browse.station &&
    activeSettingsEntries(settings).length === 0
  ) {
    return catalogue.defaultMatches;
  }

  const matchingFactSets = compileSettingsMatcher(
    catalogue.facts,
    catalogue.factSets,
    settings,
  );

  let providerIdx = -1;
  if (browse.provider !== undefined && browse.provider !== "") {
    const found = catalogue.providerIndexById.get(browse.provider);
    if (found === undefined) return [];
    providerIdx = found;
  }

  const targetStation =
    browse.station !== undefined && browse.station !== ""
      ? browse.station
      : null;

  const result: StationRecord[] = [];
  const stations = catalogue.stations;
  for (let i = 0; i < stations.length; i++) {
    const station = stations[i];
    if (!matchingFactSets[station.factSetIndex]) continue;
    if (providerIdx >= 0 && station.providerIndex !== providerIdx) continue;
    if (targetStation !== null && station.station_id !== targetStation) continue;
    result.push(station);
  }
  return result;
}

function activeSettingsEntries(
  settings: RequestSettings,
): [PhysicalField, string][] {
  const entries: [PhysicalField, string][] = [];
  for (const field of physicalFields) {
    const value = settings[field];
    if (value !== undefined && value !== "") entries.push([field, value]);
  }
  return entries;
}

function buildFactSetConflictReasons(
  factSetIndices: number[],
  facts: FactProfile[],
  settingsEntries: [PhysicalField, string][],
): string[] {
  const profiles = factSetIndices.map((idx) => facts[idx]);
  const reasons: string[] = [];
  for (const [field, requested] of settingsEntries) {
    let target = requested;
    if (field === "frequency") {
      const err = frequencyError(requested);
      if (err) {
        reasons.push(err);
        continue;
      }
      target = canonicalizeFrequency(requested) ?? requested;
    }
    let matched = false;
    let hasNull = false;
    const knownSet = new Set<string>();
    for (const profile of profiles) {
      const val = factFieldValue(profile, field);
      if (val === target) {
        matched = true;
        break;
      }
      if (val == null) hasNull = true;
      else knownSet.add(val);
    }
    if (!matched) {
      const known = Array.from(knownSet);
      reasons.push(
        known.length
          ? `${field}: requested ${JSON.stringify(target)}; catalogue lists ${known.map((value) => JSON.stringify(value)).join(", ")}.${hasNull ? " Other facts are not established." : ""}`
          : `${field} is not established in the catalogue; it cannot match ${JSON.stringify(target)}.`,
      );
    }
  }
  if (!profiles.length) {
    reasons.push(
      "No source series is established for this catalogue entry. It cannot match the current discovery request.",
    );
  } else if (!profiles.some((profile) => profile.admission === "supported")) {
    reasons.push(
      "The catalogue establishes no fact segment with supported numeric admission for this gauge.",
    );
  }
  if (!reasons.length) {
    reasons.push(
      "No single supported catalogue series and fact segment matches this combination of request settings.",
    );
  }
  return reasons;
}

/** Compute conflicts for selected stations against current request settings, memoized by factSetIndex. */
export function selectionConflicts(
  selected: StationRecord[],
  settings: RequestSettings,
  facts: FactProfile[],
  factSets: number[][],
): Conflict[] {
  if (!selected.length) return [];
  const matchingFactSets = compileSettingsMatcher(facts, factSets, settings);
  const settingsEntries = activeSettingsEntries(settings);
  const reasonCache = new Map<number, string[]>();
  const conflicts: Conflict[] = [];

  for (let i = 0; i < selected.length; i++) {
    const station = selected[i];
    const setIdx = station.factSetIndex;
    if (matchingFactSets[setIdx]) continue;
    let reasons = reasonCache.get(setIdx);
    if (!reasons) {
      reasons = buildFactSetConflictReasons(
        factSets[setIdx] ?? [],
        facts,
        settingsEntries,
      );
      reasonCache.set(setIdx, reasons);
    }
    conflicts.push({ key: station.key, station, reasons });
  }
  return conflicts;
}
