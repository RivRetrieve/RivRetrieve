export const physicalFields = [
  "quantity",
  "frequency",
  "statistic",
  "temporal_support",
  "day_definition",
  "timestamp_anchor",
  "time_zone",
  "vertical_reference",
  "vertical_datum",
] as const;

export const controlPhysicalFields = [
  "quantity",
  "frequency",
  "statistic",
  "temporal_support",
] as const;

export const filterFields = [
  "provider",
  "station",
  ...physicalFields,
] as const;

export type PhysicalField = (typeof physicalFields)[number];
export type ControlPhysicalField = (typeof controlPhysicalFields)[number];
export type FilterField = (typeof filterFields)[number];
export type Filters = Partial<Record<FilterField, string>>;
export type BrowseFilters = Pick<Filters, "provider" | "station">;
export type RequestSettings = Omit<Filters, "provider" | "station">;
export type FactState = "known" | "source_silent" | "not_established";
export type AdmissionStatus = "supported" | "unsupported";

export interface FactValue {
  value: string | null;
  state: FactState;
}

export type FactProfile = Record<PhysicalField, FactValue> & {
  admission: AdmissionStatus;
  canonicalFrequency: string | null;
};

export interface Provider {
  name?: string;
  provider_id: string;
  retrieval: boolean;
  bulk: boolean;
  credentials: string[];
}

export interface StationRecord {
  index: number;
  key: string;
  providerIndex: number;
  provider_id: string;
  station_id: string;
  station_name: string | null;
  water_body_names: string[];
  latitude: number | null;
  longitude: number | null;
  crs: string | null;
  factSetIndex: number;
  plottable: boolean;
}

export interface StationCatalogue {
  providers: Provider[];
  providerById: ReadonlyMap<string, Provider>;
  providerIndexById: ReadonlyMap<string, number>;
  facts: FactProfile[];
  factSets: number[][];
  stations: StationRecord[];
  defaultMatches: StationRecord[];
  filterOptions: Record<ControlPhysicalField, string[]>;
}

export interface RequestDates {
  start: string;
  end: string;
}

export interface Conflict {
  key: string;
  station: StationRecord;
  reasons: string[];
}

export interface RequestEvaluation {
  conflicts: Conflict[];
  blockingReasons: string[];
  groups: Map<string, string[]>;
  stationIds: string[];
  combined: boolean;
  stationCount: number;
  omittedStationCount: number;
}

export interface RequestPreview {
  code: string;
  previewCode: string;
  omittedStationCount: number;
  blockingReasons: string[];
  conflicts: Conflict[];
}
