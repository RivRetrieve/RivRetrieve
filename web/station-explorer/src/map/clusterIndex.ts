import Supercluster from "supercluster";
import type { StationRecord } from "../domain/types";

export interface StationPointProps {
  station: StationRecord;
}

export type StationFeature =
  Parameters<Supercluster<StationPointProps>["load"]>[0][number];
export type ClusterOrPoint =
  ReturnType<Supercluster<StationPointProps>["getClusters"]>[number];

export interface LatLngBoundsBox {
  minLat: number;
  maxLat: number;
  minLng: number;
  maxLng: number;
}

export interface ClusterIndexHandle {
  index: Supercluster<StationPointProps>;
  clusteredCount: number;
  getClusters: (
    bbox: [number, number, number, number],
    zoom: number,
  ) => ClusterOrPoint[];
}

export type ClusterClickAction =
  | {
      kind: "zoom";
      center: [number, number];
      targetZoom: number;
    }
  | {
      kind: "spiderfy";
      center: [number, number];
      leaves: StationRecord[];
    };

/** Compute geographic bounding box across plottable stations in one zero-allocation pass. */
export function computeStationBounds(
  stations: StationRecord[],
): LatLngBoundsBox | null {
  let minLat = Infinity;
  let maxLat = -Infinity;
  let minLng = Infinity;
  let maxLng = -Infinity;
  let found = false;

  for (let i = 0; i < stations.length; i++) {
    const station = stations[i];
    if (!station.plottable) continue;
    const lat = station.latitude!;
    const lng = station.longitude!;
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
    if (lng < minLng) minLng = lng;
    if (lng > maxLng) maxLng = lng;
    found = true;
  }

  return found ? { minLat, maxLat, minLng, maxLng } : null;
}

/** Pre-build reusable GeoJSON point features indexed by `station.index` once per catalogue load. */
export function buildStationFeatures(
  stations: StationRecord[],
): Array<StationFeature | null> {
  const features: Array<StationFeature | null> = new Array(stations.length);
  for (let i = 0; i < stations.length; i++) {
    const station = stations[i];
    if (!station.plottable) {
      features[i] = null;
    } else {
      features[i] = {
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: [station.longitude!, station.latitude!],
        },
        properties: { station },
      };
    }
  }
  return features;
}

/** Build a Supercluster spatial index for matching non-selected plottable stations. */
export function buildClusterIndex(
  matches: StationRecord[],
  selectedKeys: ReadonlySet<string>,
  featureByIndex: Array<StationFeature | null>,
): ClusterIndexHandle {
  const features: StationFeature[] = [];
  const hasSelected = selectedKeys.size > 0;
  for (let i = 0; i < matches.length; i++) {
    const station = matches[i];
    if (!station.plottable) continue;
    if (hasSelected && selectedKeys.has(station.key)) continue;
    const feature = featureByIndex[station.index] ?? {
      type: "Feature" as const,
      geometry: {
        type: "Point" as const,
        coordinates: [station.longitude!, station.latitude!],
      },
      properties: { station },
    };
    features.push(feature);
  }

  const index = new Supercluster<StationPointProps>({
    radius: 60,
    minZoom: 3,
    maxZoom: 18,
  });
  index.load(features);

  return {
    index,
    clusteredCount: features.length,
    getClusters: (bbox, zoom) =>
      index.getClusters(bbox, zoom) as ClusterOrPoint[],
  };
}

/** Decide whether clicking a cluster should zoom to separate gauges or spiderfy co-located ones. */
export function getClusterAction(
  handle: ClusterIndexHandle,
  clusterId: number,
  currentZoom: number,
  maxZoom: number,
): ClusterClickAction {
  const leavesRaw = handle.index.getLeaves(clusterId, 50, 0);
  const leaves = leavesRaw.map((leaf) => leaf.properties.station);
  const first = leaves[0];
  const center: [number, number] = first
    ? [first.latitude!, first.longitude!]
    : [0, 0];

  const allCoLocated =
    leaves.length > 0 &&
    leaves.length <= 50 &&
    leaves.every(
      (st) =>
        Math.abs(st.latitude! - first.latitude!) <= 1e-7 &&
        Math.abs(st.longitude! - first.longitude!) <= 1e-7,
    );

  if (allCoLocated || currentZoom >= maxZoom) {
    return { kind: "spiderfy", center, leaves };
  }

  const expansionZoom = handle.index.getClusterExpansionZoom(clusterId);
  const targetZoom = Math.min(maxZoom, Math.max(currentZoom + 1, expansionZoom));
  return { kind: "zoom", center, targetZoom };
}
