import { describe, expect, it, vi } from "vitest";
import { decodeCatalogue, type WireCatalogueV3 } from "./index";
import { loadCatalogue } from "./loader";
import { compileSettingsMatcher, filterCatalogueStations } from "../domain/filtering";
import type { FactState } from "../domain/types";

const unknown = (): { value: null; state: FactState } => ({
  value: null,
  state: "not_established",
});

function sampleWire(): WireCatalogueV3 {
  const first = {
    quantity: { value: "discharge", state: "known" as const },
    frequency: { value: null, state: "source_silent" as const },
    statistic: unknown(),
    temporal_support: unknown(),
    day_definition: unknown(),
    timestamp_anchor: unknown(),
    time_zone: unknown(),
    vertical_reference: unknown(),
    vertical_datum: unknown(),
    admission: "supported" as const,
  };
  return {
    version: 3,
    providers: [
      { provider_id: "alpha", retrieval: true, bulk: true, credentials: [] },
      {
        provider_id: "beta",
        retrieval: false,
        bulk: false,
        credentials: ["CREDENTIAL_NAME"],
      },
    ],
    facts: [
      first,
      {
        ...first,
        quantity: { value: "stage", state: "known" },
        frequency: { value: "PT60M", state: "known" },
      },
    ],
    fact_sets: [[0, 1], []],
    stations: [
      [0, "001", "River é", 1.123456789, 2, "unknown", ["Mår", "MÅRVATN"], 0],
      [1, "001", null, null, null, null, [], 1],
    ],
  };
}

describe("v3 catalogue decoding", () => {
  it("preserves qualified identities, original geometry, unknown states, fact-set boundaries, and filter options", () => {
    const wire = sampleWire();
    const catalogue = decodeCatalogue(wire);
    expect(catalogue.providers).toEqual(wire.providers);
    expect(catalogue.providerById.get("beta")).toEqual(wire.providers[1]);
    expect(catalogue.stations[0]).toMatchObject({
      index: 0,
      key: '["alpha","001"]',
      providerIndex: 0,
      provider_id: "alpha",
      station_id: "001",
      station_name: "River é",
      latitude: 1.123456789,
      longitude: 2,
      crs: "unknown",
      water_body_names: ["Mår", "MÅRVATN"],
      factSetIndex: 0,
      plottable: true,
    });
    expect(catalogue.stations[1]).toMatchObject({
      index: 1,
      key: '["beta","001"]',
      providerIndex: 1,
      provider_id: "beta",
      station_id: "001",
      station_name: null,
      latitude: null,
      longitude: null,
      crs: null,
      water_body_names: [],
      factSetIndex: 1,
      plottable: false,
    });
    expect(catalogue.facts[0].frequency).toEqual({
      value: null,
      state: "source_silent",
    });
    expect(catalogue.facts[1].canonicalFrequency).toBe("PT1H");
    expect(catalogue.filterOptions).toEqual({
      quantity: ["discharge", "stage"],
      frequency: ["PT1H"],
      statistic: [],
      temporal_support: [],
    });

    // Cross-segment facts are never merged
    expect(
      filterCatalogueStations(catalogue, {}, { quantity: "discharge", frequency: "PT1H" }),
    ).toEqual([]);
    expect(
      filterCatalogueStations(catalogue, {}, { quantity: "stage", frequency: "PT1H" }),
    ).toEqual([catalogue.stations[0]]);
  });

  it("preserves unsupported admission instead of making an executable match", () => {
    const wire = sampleWire();
    wire.facts[0].admission = "unsupported";
    const catalogue = decodeCatalogue(wire);
    expect(catalogue.facts[0].admission).toBe("unsupported");
    expect(filterCatalogueStations(catalogue, {}, { quantity: "discharge" })).toEqual([]);
    const matcher = compileSettingsMatcher(catalogue.facts, catalogue.factSets, {
      quantity: "discharge",
    });
    expect(matcher[0]).toBe(0);
  });

  it("rejects invalid provider, fact_set, and fact references and unsupported versions", () => {
    for (const version of [1, 2, 4]) {
      const wire = sampleWire();
      wire.version = version;
      expect(() => decodeCatalogue(wire)).toThrow(/Unsupported catalogue format/);
    }
    const badProvider = sampleWire();
    badProvider.stations[0][0] = 9;
    expect(() => decodeCatalogue(badProvider)).toThrow(/missing provider/);

    const badFactSet = sampleWire();
    badFactSet.stations[0][7] = 9;
    expect(() => decodeCatalogue(badFactSet)).toThrow(/missing fact set/);

    const badFact = sampleWire();
    badFact.fact_sets[0] = [9];
    expect(() => decodeCatalogue(badFact)).toThrow(/missing physical facts/);
  });
});

describe("catalogue loader", () => {
  it("fetches and decodes v3 catalogue and surfaces HTTP failures", async () => {
    const wire = sampleWire();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => wire,
    });
    const controller = new AbortController();
    const catalogue = await loadCatalogue("http://127.0.0.1/catalogue.json", controller.signal, fetchMock as unknown as typeof fetch);
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1/catalogue.json", {
      signal: controller.signal,
    });
    expect(catalogue.stations).toHaveLength(2);

    const failMock = vi.fn().mockResolvedValue({ ok: false, status: 404 });
    await expect(
      loadCatalogue("http://127.0.0.1/catalogue.json", controller.signal, failMock as unknown as typeof fetch),
    ).rejects.toThrow("Catalogue loading failed (404).");
  });
});
