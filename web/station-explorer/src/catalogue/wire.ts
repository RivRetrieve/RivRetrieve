import {
  controlPhysicalFields,
  physicalFields,
  type AdmissionStatus,
  type ControlPhysicalField,
  type FactProfile,
  type FactState,
  type FactValue,
  type PhysicalField,
  type Provider,
  type StationCatalogue,
  type StationRecord,
} from "../domain/types";
import { isPlottableCoordinates } from "../domain/coordinates";
import { canonicalizeFrequency } from "../domain/frequency";
import { stationKey } from "../domain/selection";

export type WireFactProfile = Record<PhysicalField, FactValue> & {
  admission: AdmissionStatus;
};

export type WireStationTuple = [
  number,
  string,
  string | null,
  number | null,
  number | null,
  string | null,
  string[],
  number,
];

export interface WireCatalogueV3 {
  version: number;
  providers: Provider[];
  facts: WireFactProfile[];
  fact_sets: number[][];
  stations: WireStationTuple[];
}

/** Decode v3 wire payload into indexed stations, deduplicated fact profiles, and precomputed filter options. */
export function decodeCatalogue(data: WireCatalogueV3): StationCatalogue {
  if (data.version !== 3) {
    throw new Error("Unsupported catalogue format. Regenerate the catalogue.");
  }

  const providerById = new Map<string, Provider>();
  const providerIndexById = new Map<string, number>();
  for (let i = 0; i < data.providers.length; i++) {
    const provider = data.providers[i];
    providerById.set(provider.provider_id, provider);
    providerIndexById.set(provider.provider_id, i);
  }

  const facts: FactProfile[] = data.facts.map((raw) => {
    const freq = raw.frequency;
    const canonicalFrequency =
      freq.state === "known" && freq.value !== null
        ? (canonicalizeFrequency(freq.value) ?? freq.value)
        : null;
    const profile = {
      admission: raw.admission,
      canonicalFrequency,
    } as FactProfile;
    for (const field of physicalFields) {
      profile[field] = raw[field] ?? {
        value: null,
        state: "not_established" as FactState,
      };
    }
    return profile;
  });

  const factCount = facts.length;
  const factSets: number[][] = data.fact_sets.map((group) => {
    for (let i = 0; i < group.length; i++) {
      const idx = group[i];
      if (idx < 0 || idx >= factCount || !facts[idx]) {
        throw new Error("Catalogue fact set references missing physical facts.");
      }
    }
    return group;
  });

  const factSetCount = factSets.length;
  const stations: StationRecord[] = data.stations.map(
    (
      [
        providerIndex,
        station_id,
        station_name,
        latitude,
        longitude,
        crs,
        water_body_names,
        factSetIndex,
      ],
      index,
    ) => {
      const provider = data.providers[providerIndex];
      if (!provider) {
        throw new Error("Catalogue station references a missing provider.");
      }
      if (
        factSetIndex < 0 ||
        factSetIndex >= factSetCount ||
        !factSets[factSetIndex]
      ) {
        throw new Error("Catalogue station references a missing fact set.");
      }
      return {
        index,
        key: stationKey({ provider_id: provider.provider_id, station_id }),
        providerIndex,
        provider_id: provider.provider_id,
        station_id,
        station_name,
        water_body_names,
        latitude,
        longitude,
        crs,
        factSetIndex,
        plottable: isPlottableCoordinates(latitude, longitude, crs),
      };
    },
  );

  // Compute unique control options once across the ~173 fact profiles.
  const optionSets = Object.fromEntries(
    controlPhysicalFields.map((field) => [field, new Set<string>()]),
  ) as Record<ControlPhysicalField, Set<string>>;
  for (let i = 0; i < facts.length; i++) {
    const profile = facts[i];
    for (const field of controlPhysicalFields) {
      const val =
        field === "frequency"
          ? profile.canonicalFrequency
          : profile[field].state === "known"
            ? profile[field].value
            : null;
      if (val !== null) optionSets[field].add(val);
    }
  }
  const filterOptions = Object.fromEntries(
    controlPhysicalFields.map((field) => [
      field,
      Array.from(optionSets[field]).sort(),
    ]),
  ) as Record<ControlPhysicalField, string[]>;

  const supportedFactSet = new Uint8Array(factSetCount);
  for (let s = 0; s < factSetCount; s++) {
    const group = factSets[s];
    for (let k = 0; k < group.length; k++) {
      if (facts[group[k]].admission === "supported") {
        supportedFactSet[s] = 1;
        break;
      }
    }
  }

  const defaultMatches: StationRecord[] = [];
  for (let i = 0; i < stations.length; i++) {
    const station = stations[i];
    if (supportedFactSet[station.factSetIndex]) defaultMatches.push(station);
  }

  return {
    providers: data.providers,
    providerById,
    providerIndexById,
    facts,
    factSets,
    stations,
    defaultMatches,
    filterOptions,
  };
}
