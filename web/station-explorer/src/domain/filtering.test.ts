import { describe, expect, it } from "vitest";
import { decodeCatalogue, type WireCatalogueV3 } from "../catalogue/index";
import {
  filterCatalogueStations,
  selectionConflicts,
} from "./filtering";
import { addStations, removeStation, stationKey } from "./selection";
import { physicalFields, type FactState } from "./types";

function makeProfile(
  overrides: Partial<Record<(typeof physicalFields)[number], { value: string | null; state: FactState }>> & {
    admission?: "supported" | "unsupported";
  } = {},
) {
  const base = Object.fromEntries(
    physicalFields.map((field) => [field, { value: null, state: "not_established" as FactState }]),
  ) as Record<(typeof physicalFields)[number], { value: string | null; state: FactState }>;
  return {
    ...base,
    quantity: { value: "discharge", state: "known" as const },
    statistic: { value: "mean", state: "known" as const },
    ...overrides,
    admission: overrides.admission ?? ("supported" as const),
  };
}

function buildTestCatalogue(wire?: Partial<WireCatalogueV3>) {
  return decodeCatalogue({
    version: 3,
    providers: [
      { provider_id: "alpha", retrieval: true, bulk: false, credentials: [] },
      { provider_id: "beta", retrieval: true, bulk: false, credentials: [] },
    ],
    facts: [makeProfile()],
    fact_sets: [[0]],
    stations: [
      [0, "001", null, null, null, null, [], 0],
      [1, "001", null, null, null, null, [], 0],
    ],
    ...wire,
  });
}

describe("catalogue discovery and conflict rules", () => {
  it("matches exact scalar facts and canonical frequency equivalents, never unknown facts", () => {
    const catalogue = buildTestCatalogue({
      facts: [
        makeProfile({ frequency: { value: "PT60M", state: "known" } }),
        makeProfile({ frequency: { value: null, state: "not_established" } }),
      ],
      fact_sets: [[0], [1]],
      stations: [
        [0, "001", null, null, null, null, [], 0],
        [1, "002", null, null, null, null, [], 1],
      ],
    });
    expect(filterCatalogueStations(catalogue, {}, { quantity: "discharge", frequency: "PT1H" })).toEqual([
      catalogue.stations[0],
    ]);
    expect(filterCatalogueStations(catalogue, {}, { quantity: "Discharge" })).toEqual([]);
    expect(filterCatalogueStations(catalogue, {}, { frequency: "daily" })).toEqual([]);
  });

  it("keeps provider and station restrictions exact, including leading zeros", () => {
    const catalogue = buildTestCatalogue();
    expect(filterCatalogueStations(catalogue, { provider: "alpha", station: "001" }, {})).toEqual([
      catalogue.stations[0],
    ]);
    expect(filterCatalogueStations(catalogue, { provider: "gamma" }, {})).toEqual([]);
    expect(filterCatalogueStations(catalogue, { station: "1" }, {})).toEqual([]);
  });

  it("preserves provider-qualified selection and never clears selection with filters", () => {
    const catalogue = buildTestCatalogue();
    const [alpha, beta] = catalogue.stations;
    const selected = addStations([alpha], [alpha, beta]);
    expect(selected.map(stationKey)).toEqual(['["alpha","001"]', '["beta","001"]']);
    expect(
      selectionConflicts(selected, { frequency: "P1D" }, catalogue.facts, catalogue.factSets)[0].reasons[0],
    ).toContain("not established");
    expect(
      removeStation(removeStation(selected, stationKey(beta)), stationKey(alpha)),
    ).toEqual([]);
  });

  it("requires all filters on one supported fact segment", () => {
    const catalogue = buildTestCatalogue({
      facts: [
        makeProfile({ quantity: { value: "discharge", state: "known" } }),
        makeProfile({ quantity: { value: "stage", state: "known" }, frequency: { value: "P1D", state: "known" } }),
        makeProfile({ admission: "unsupported" }),
      ],
      fact_sets: [[0, 1], [2]],
      stations: [
        [0, "split", null, null, null, null, [], 0],
        [0, "unsup", null, null, null, null, [], 1],
      ],
    });
    expect(filterCatalogueStations(catalogue, {}, { quantity: "discharge", frequency: "P1D" })).toEqual([]);
    expect(
      selectionConflicts(
        [catalogue.stations[0]],
        { quantity: "discharge", frequency: "P1D" },
        catalogue.facts,
        catalogue.factSets,
      )[0].reasons[0],
    ).toContain("combination");
    expect(filterCatalogueStations(catalogue, { station: "unsup" }, {})).toEqual([]);
    expect(
      selectionConflicts([catalogue.stations[1]], {}, catalogue.facts, catalogue.factSets)[0].reasons[0],
    ).toContain("supported numeric admission");
  });

  it("distinguishes a known literal unknown from an unestablished fact", () => {
    const catalogue = buildTestCatalogue({
      facts: [
        makeProfile({ time_zone: { value: "unknown", state: "known" } }),
        makeProfile({ time_zone: { value: "unknown", state: "not_established" } }),
      ],
      fact_sets: [[0], [1]],
      stations: [
        [0, "known-unknown", null, null, null, null, [], 0],
        [0, "unestablished", null, null, null, null, [], 1],
      ],
    });
    expect(filterCatalogueStations(catalogue, {}, { time_zone: "unknown" })).toEqual([
      catalogue.stations[0],
    ]);
  });

  it.each(physicalFields)("matches %s as an exact scalar on established facts", (field) => {
    const catalogue = buildTestCatalogue({
      facts: [
        makeProfile({ [field]: { value: "PT60M", state: "known" } }),
        makeProfile({ [field]: { value: null, state: "source_silent" } }),
      ],
      fact_sets: [[0], [1]],
      stations: [
        [0, "known", null, null, null, null, [], 0],
        [0, "silent", null, null, null, null, [], 1],
      ],
    });
    expect(filterCatalogueStations(catalogue, {}, { [field]: "PT60M" })).toEqual([
      catalogue.stations[0],
    ]);
    expect(filterCatalogueStations(catalogue, {}, { [field]: "PT60" })).toEqual([]);
    expect(filterCatalogueStations(catalogue, {}, { [field]: "pt60m" })).toEqual([]);
  });

  it("explains a selected catalogue entry with no source series without discarding it", () => {
    const catalogue = buildTestCatalogue({
      fact_sets: [[]],
      stations: [[0, "empty", null, null, null, null, [], 0]],
    });
    expect(
      selectionConflicts(catalogue.stations, {}, catalogue.facts, catalogue.factSets)[0].reasons,
    ).toContain(
      "No source series is established for this catalogue entry. It cannot match the current discovery request.",
    );
  });

  it("returns precomputed defaultMatches identity for empty browse and request settings", () => {
    const catalogue = buildTestCatalogue({
      facts: [
        makeProfile({ admission: "supported" }),
        makeProfile({ admission: "unsupported" }),
      ],
      fact_sets: [[0], [1]],
      stations: [
        [0, "001", null, null, null, null, [], 0],
        [1, "002", null, null, null, null, [], 1],
      ],
    });
    expect(catalogue.defaultMatches).toEqual([catalogue.stations[0]]);
    const initial = filterCatalogueStations(catalogue, {}, {});
    expect(initial).toBe(catalogue.defaultMatches);
    const filtered = filterCatalogueStations(catalogue, { provider: "alpha" }, {});
    expect(filtered).toEqual([catalogue.stations[0]]);
    expect(filterCatalogueStations(catalogue, {}, {})).toBe(catalogue.defaultMatches);
  });
});
