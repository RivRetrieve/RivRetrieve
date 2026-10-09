import { describe, expect, it } from "vitest";
import { expandCatalogue } from "./catalogue";
import { matchesStation, type FactState } from "./domain";

type WireCatalogue = Parameters<typeof expandCatalogue>[0];
const unknown = (): { value: null; state: FactState } => ({
  value: null,
  state: "not_established",
});
function catalogue(): WireCatalogue {
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
    version: 1,
    providers: [
      { provider_id: "alpha", retrieval: true, bulk: true, credentials: [] },
      {
        provider_id: "beta",
        retrieval: false,
        bulk: false,
        credentials: ["CREDENTIAL_NAME"],
      },
    ],
    stations: [
      [0, "001", "River é", 1.123456789, 2, "unknown"],
      [1, "001", null, null, null, null],
    ],
    facts: [
      first,
      {
        ...first,
        quantity: { value: "stage", state: "known" },
        frequency: { value: "daily", state: "known" },
      },
    ],
    series: [[0, "exact-id", "original", "published", [0, 1]]],
  };
}

describe("compact catalogue decoding", () => {
  it("preserves qualified identities, original geometry, unknown states and separate fact segments", () => {
    const wire = catalogue();
    const result = expandCatalogue(wire);
    expect(result.providers).toEqual(wire.providers);
    expect(result.stations[0]).toMatchObject({
      provider_id: "alpha",
      station_id: "001",
      station_name: "River é",
      latitude: 1.123456789,
      longitude: 2,
      crs: "unknown",
    });
    expect(result.stations[1]).toEqual({
      provider_id: "beta",
      station_id: "001",
      station_name: null,
      latitude: null,
      longitude: null,
      crs: null,
      series: [],
    });
    expect(result.stations[0].series).toHaveLength(2);
    expect(result.stations[0].series[0]).toMatchObject({
      series_id: "exact-id",
      variant: "original",
      published_id: "published",
      admission: "supported",
      quantity: "discharge",
      quantity_state: "known",
      frequency: null,
      frequency_state: "source_silent",
      time_zone: null,
      time_zone_state: "not_established",
    });
    expect(result.stations[0].series[1]).toMatchObject({
      series_id: "exact-id",
      quantity: "stage",
      frequency: "daily",
      frequency_state: "known",
    });
    expect(
      matchesStation(result.stations[0], {
        quantity: "discharge",
        frequency: "daily",
      }),
    ).toBe(false);
    expect(
      matchesStation(result.stations[0], {
        quantity: "stage",
        frequency: "daily",
      }),
    ).toBe(true);
  });

  it("preserves unsupported admission instead of making an executable match", () => {
    const wire = catalogue();
    wire.facts[0].admission = "unsupported";
    const station = expandCatalogue(wire).stations[0];
    expect(station.series[0].admission).toBe("unsupported");
    expect(matchesStation(station, { quantity: "discharge" })).toBe(false);
  });

  it.each(["provider", "station", "facts"] as const)(
    "rejects a missing %s reference",
    (reference) => {
      const wire = catalogue();
      if (reference === "provider") wire.stations[0][0] = 9;
      if (reference === "station") wire.series[0][0] = 9;
      if (reference === "facts") wire.series[0][4] = [9];
      expect(() => expandCatalogue(wire)).toThrow(/missing/);
    },
  );

  it("rejects an unsupported wire version", () => {
    const wire = catalogue();
    wire.version = 2;
    expect(() => expandCatalogue(wire)).toThrow(/Unsupported catalogue format/);
  });
});
