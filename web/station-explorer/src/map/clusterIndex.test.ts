import { describe, expect, it } from "vitest";
import { decodeCatalogue } from "../catalogue/index";
import { physicalFields, type FactState } from "../domain/types";
import {
  buildClusterIndex,
  buildStationFeatures,
  computeStationBounds,
  getClusterAction,
} from "./clusterIndex";
import { computeSpiderOffsets } from "./spiderfy";

function makeStations(
  coords: Array<{ providerIdx?: number; id: string; lat: number | null; lng: number | null; crs?: string | null }>,
) {
  const base = Object.fromEntries(
    physicalFields.map((f) => [f, { value: null, state: "not_established" as FactState }]),
  ) as Record<(typeof physicalFields)[number], { value: string | null; state: FactState }>;
  const cat = decodeCatalogue({
    version: 3,
    providers: [
      { provider_id: "alpha", retrieval: true, bulk: false, credentials: [] },
      { provider_id: "beta", retrieval: true, bulk: false, credentials: [] },
    ],
    facts: [{ ...base, quantity: { value: "discharge", state: "known" }, admission: "supported" }],
    fact_sets: [[0]],
    stations: coords.map((c) => [
      c.providerIdx ?? 0,
      c.id,
      null,
      c.lat,
      c.lng,
      c.crs ?? "EPSG:4326",
      [],
      0,
    ]),
  });
  return cat.stations;
}

describe("clusterIndex and bounds", () => {
  it("computes exact geographic bounds across plottable stations only", () => {
    const stations = makeStations([
      { id: "a", lat: 46.2, lng: 6.2 },
      { id: "b", lat: 47.4, lng: 9.8 },
      { id: "missing", lat: null, lng: null, crs: null },
      { id: "bad-crs", lat: 10, lng: 10, crs: "EPSG:2056" },
    ]);
    expect(computeStationBounds(stations)).toEqual({
      minLat: 46.2,
      maxLat: 47.4,
      minLng: 6.2,
      maxLng: 9.8,
    });
    expect(computeStationBounds(stations.slice(2))).toBeNull();
  });

  it("clusters Swiss groups, separates nearby points on expansion zoom, and excludes selected stations", () => {
    const coords: Array<{ providerIdx?: number; id: string; lat: number; lng: number }> = [];
    const groups = [
      { count: 2, lat: 46.2, lng: 6.2, providerIdx: 0 },
      { count: 15, lat: 46.8, lng: 8.2, providerIdx: 0 },
      { count: 120, lat: 47.4, lng: 9.8, providerIdx: 1 },
    ];
    let idx = 0;
    for (const g of groups) {
      for (let i = 0; i < g.count; i++) {
        coords.push({
          providerIdx: g.providerIdx,
          id: `s-${idx++}`,
          lat: g.lat + (i % 5) * 0.0002,
          lng: g.lng + Math.floor(i / 5) * 0.0002,
        });
      }
    }
    const stations = makeStations(coords);
    const featureByIndex = buildStationFeatures(stations);
    const index = buildClusterIndex(stations, new Set([stations[0].key]), featureByIndex);
    expect(index.clusteredCount).toBe(136);
    const clusters = index.getClusters([5.0, 45.5, 11.0, 48.0], 7);
    const counts = clusters
      .map((c) => ("cluster" in c.properties && c.properties.cluster ? c.properties.point_count : 1))
      .sort((a, b) => a - b);
    expect(counts).toEqual([1, 15, 120]);

    const zoom3Clusters = index.getClusters([-180, -85, 180, 85], 3);
    expect(zoom3Clusters.length).toBeGreaterThan(0);
    const zoom3Total = zoom3Clusters.reduce(
      (sum, c) => sum + ("cluster" in c.properties && c.properties.cluster ? c.properties.point_count : 1),
      0,
    );
    expect(zoom3Total).toBe(136);
  });

  it("zooms nearby non-colocated points and spiderfies co-located points immediately", () => {
    const stations = makeStations([
      { providerIdx: 0, id: "001", lat: 10, lng: 10 },
      { providerIdx: 1, id: "001", lat: 10, lng: 10.001 },
      { providerIdx: 0, id: "coloc-a", lat: 20, lng: 20 },
      { providerIdx: 1, id: "coloc-b", lat: 20, lng: 20 },
    ]);
    const featureByIndex = buildStationFeatures(stations);
    const index = buildClusterIndex(stations, new Set(), featureByIndex);
    const clusters = index.getClusters([9, 9, 21, 21], 10);
    expect(clusters).toHaveLength(2);

    const nearby = clusters.find((c) => Math.abs(c.geometry.coordinates[1] - 10) < 0.1)!;
    expect("cluster" in nearby.properties && nearby.properties.cluster).toBe(true);
    if (!("cluster" in nearby.properties)) throw new Error("Expected cluster");
    const nearbyAction = getClusterAction(index, nearby.properties.cluster_id, 10, 18);
    expect(nearbyAction.kind).toBe("zoom");
    if (nearbyAction.kind === "zoom") {
      expect(nearbyAction.targetZoom).toBeGreaterThan(10);
    }

    const colocated = clusters.find((c) => Math.abs(c.geometry.coordinates[1] - 20) < 0.1)!;
    expect("cluster" in colocated.properties && colocated.properties.cluster).toBe(true);
    if (!("cluster" in colocated.properties)) throw new Error("Expected cluster");
    const colocAction = getClusterAction(index, colocated.properties.cluster_id, 12, 18);
    expect(colocAction.kind).toBe("spiderfy");
    if (colocAction.kind === "spiderfy") {
      expect(colocAction.leaves).toHaveLength(2);
    }
  });
});

describe("spiderfy offsets", () => {
  it("produces distinct non-overlapping pixel offsets for circle and spiral counts", () => {
    for (const count of [2, 8, 12]) {
      const offsets = computeSpiderOffsets(count);
      expect(offsets).toHaveLength(count);
      const unique = new Set(offsets.map((p) => `${Math.round(p.x)},${Math.round(p.y)}`));
      expect(unique.size).toBe(count);
      for (const pt of offsets) {
        expect(Math.hypot(pt.x, pt.y)).toBeGreaterThan(10);
      }
    }
  });
});
