import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { StationRecord } from "../domain/types";
import { basemapTiles } from "./basemap";
import {
  buildClusterIndex,
  buildStationFeatures,
  computeStationBounds,
  getClusterAction,
  type ClusterIndexHandle,
  type StationFeature,
} from "./clusterIndex";
import { GaugeIcon, gaugePinSvg, gaugeSprites } from "./gaugeSymbol";
import { computeSpiderOffsets } from "./spiderfy";

export interface StationMapProps {
  catalogueStations: StationRecord[];
  matches: StationRecord[];
  selected: StationRecord[];
  selectedKeys: ReadonlySet<string>;
  conflictKeys: ReadonlySet<string>;
  basemapKey: string | undefined;
  onInspect: (station: StationRecord) => void;
}

const MAX_ZOOM = 18;
const SPARSE_SELECTION_THRESHOLD = 256;

/** Viewport-windowed Supercluster discovery with spiderfy and canvas selected/conflict overlay. */
export function StationMap({
  catalogueStations,
  matches,
  selected,
  selectedKeys,
  conflictKeys,
  basemapKey,
  onInspect,
}: StationMapProps) {
  const host = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const data = useRef({
    catalogueStations,
    matches,
    selected,
    selectedKeys,
    conflictKeys,
    onInspect,
  });
  data.current = {
    catalogueStations,
    matches,
    selected,
    selectedKeys,
    conflictKeys,
    onInspect,
  };
  const update = useRef<() => void>(() => {});

  useEffect(() => {
    const map = L.map(host.current!, {
      center: [46.8, 8.2],
      zoom: 7,
      minZoom: 3,
      maxZoom: MAX_ZOOM,
    });
    map.fitBounds(
      [
        [45.7, 5.8],
        [47.9, 10.6],
      ],
      {
        paddingTopLeft: [32, 32],
        paddingBottomRight: [
          host.current!.clientWidth <= 900 ? 32 : 484,
          host.current!.clientWidth <= 900
            ? host.current!.clientHeight / 2 + 32
            : 32,
        ],
        maxZoom: 8,
        animate: false,
      },
    );
    mapRef.current = map;

    let tiles: L.TileLayer | undefined;
    let tileStyle = "";
    const applyBasemap = () => {
      const source = basemapTiles(
        document.documentElement.dataset.mdColorScheme,
        basemapKey,
      );
      if (source.style === tileStyle) return;
      if (tiles) {
        map.removeLayer(tiles);
        tiles.off();
      }
      tileStyle = source.style;
      host.current!.dataset.basemap = source.style;
      tiles = L.tileLayer(source.url, {
        maxZoom: MAX_ZOOM,
        noWrap: true,
        attribution: source.attribution,
      }).addTo(map);
    };
    applyBasemap();
    const themeObserver = new MutationObserver(applyBasemap);
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-md-color-scheme"],
    });

    const clusterLayer = L.layerGroup().addTo(map);
    const spiderLayer = L.layerGroup().addTo(map);
    const pointIcon = L.divIcon({
      className: "gauge-point",
      html: gaugePinSvg("match"),
      iconSize: [25.5, 30],
      iconAnchor: [12, 28.5],
    });
    const canvas = L.DomUtil.create(
      "canvas",
      "station-points",
      map.getContainer(),
    );
    canvas.setAttribute("aria-hidden", "true");
    canvas.dataset.spiderfied = "0";
    canvas.dataset.clustered = "0";
    canvas.dataset.drawn = "0";

    let featureCacheSource: StationRecord[] | undefined;
    let featureByIndex: Array<StationFeature | null> = [];
    let unselectedClusterCache = new WeakMap<
      StationRecord[],
      ClusterIndexHandle
    >();
    let clusterHandle: ClusterIndexHandle | null = null;
    let activeSpider: {
      clusterId: number;
      center: [number, number];
      leaves: StationRecord[];
    } | null = null;

    let matchingKeys = new Set<string>();
    let plottedTotal = 0;
    let selectedPoints: { x: number; y: number; station: StationRecord }[] = [];
    let frame = 0;
    let sprites: ReturnType<typeof gaugeSprites> | undefined;
    let spriteRatio = 0;

    const clearSpiderfy = () => {
      if (!activeSpider) return;
      activeSpider = null;
      spiderLayer.clearLayers();
      canvas.dataset.spiderfied = "0";
    };

    const drawSelectedCanvas = () => {
      const size = map.getSize();
      const ratio = window.devicePixelRatio || 1;
      if (!sprites || ratio !== spriteRatio) {
        sprites = gaugeSprites(host.current!, ratio);
        spriteRatio = ratio;
      }
      canvas.width = size.x * ratio;
      canvas.height = size.y * ratio;
      canvas.style.width = `${size.x}px`;
      canvas.style.height = `${size.y}px`;
      const ctx = canvas.getContext("2d")!;
      ctx.scale(ratio, ratio);

      const sel = data.current.selected;
      const conflicts = data.current.conflictKeys;
      selectedPoints = [];

      if (sel.length) {
        const bounds = map.getBounds().pad(0.05);
        const minLat = bounds.getSouth();
        const maxLat = bounds.getNorth();
        const minLng = bounds.getWest();
        const maxLng = bounds.getEast();
        const deduplicate = sel.length > SPARSE_SELECTION_THRESHOLD;
        const gridW = Math.ceil((size.x + 48) / 2) + 2;
        const gridH = Math.ceil((size.y + 32) / 2) + 2;
        const occupied = deduplicate ? new Uint8Array(gridW * gridH) : null;

        // Draw matching selected pins first, then conflicts on top so conflicts are never hidden.
        const drawPin = (station: StationRecord, state: "selected" | "conflict") => {
          const lat = station.latitude!;
          const lng = station.longitude!;
          if (lat < minLat || lat > maxLat || lng < minLng || lng > maxLng)
            return;
          const { x, y } = map.latLngToContainerPoint([lat, lng]);
          if (x < -24 || x > size.x + 24 || y < 0 || y > size.y + 30) return;

          if (occupied) {
            const gx = Math.floor((x + 24) / 2);
            const gy = Math.floor(y / 2);
            if (gx >= 0 && gx < gridW && gy >= 0 && gy < gridH) {
              const cell = gy * gridW + gx;
              const flag = state === "conflict" ? 2 : 1;
              if ((occupied[cell] & flag) !== 0) return;
              occupied[cell] |= flag;
            }
          }

          selectedPoints.push({ x, y: y - 17, station });
          ctx.drawImage(sprites![state], x - 12, y - 28.5, 25.5, 30);
        };

        for (let i = 0; i < sel.length; i++) {
          const station = sel[i];
          if (!station.plottable || conflicts.has(station.key)) continue;
          drawPin(station, "selected");
        }
        for (let i = 0; i < sel.length; i++) {
          const station = sel[i];
          if (!station.plottable || !conflicts.has(station.key)) continue;
          drawPin(station, "conflict");
        }
      }

      canvas.dataset.drawn = String(plottedTotal);
      canvas.dataset.zoom = String(map.getZoom());
      canvas.dataset.centerLat = String(map.getCenter().lat);
      canvas.dataset.centerLng = String(map.getCenter().lng);
    };

    const scheduleCanvas = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(drawSelectedCanvas);
    };

    const renderSpiderfy = () => {
      spiderLayer.clearLayers();
      if (!activeSpider) {
        canvas.dataset.spiderfied = "0";
        return;
      }
      const centerPt = map.latLngToLayerPoint(activeSpider.center);
      const offsets = computeSpiderOffsets(activeSpider.leaves.length);
      for (let i = 0; i < activeSpider.leaves.length; i++) {
        const station = activeSpider.leaves[i];
        const offset = offsets[i];
        const targetLatLng = map.layerPointToLatLng([
          centerPt.x + offset.x,
          centerPt.y + offset.y,
        ]);
        L.polyline([activeSpider.center, targetLatLng], {
          color: "var(--gauge-cluster)",
          weight: 1.5,
          opacity: 0.75,
          interactive: false,
        }).addTo(spiderLayer);

        L.marker(targetLatLng, {
          icon: pointIcon,
          title: `Inspect ${station.provider_id} / ${station.station_id}`,
          zIndexOffset: 200,
        })
          .on("click", (event) => {
            L.DomEvent.stopPropagation(event);
            data.current.onInspect(station);
          })
          .addTo(spiderLayer);
      }
      canvas.dataset.spiderfied = String(activeSpider.leaves.length);
    };

    const renderViewportClusters = () => {
      clusterLayer.clearLayers();
      if (!clusterHandle) {
        scheduleCanvas();
        return;
      }
      const bounds = map.getBounds().pad(0.15);
      const west = Math.max(-180, bounds.getWest());
      const south = Math.max(-85.0511, bounds.getSouth());
      const east = Math.min(180, bounds.getEast());
      const north = Math.min(85.0511, bounds.getNorth());
      const zoom = Math.floor(map.getZoom());
      const features = clusterHandle.getClusters([west, south, east, north], zoom);

      for (let i = 0; i < features.length; i++) {
        const feat = features[i];
        const [lng, lat] = feat.geometry.coordinates;
        if ("cluster" in feat.properties && feat.properties.cluster) {
          const clusterId = feat.properties.cluster_id;
          if (activeSpider && activeSpider.clusterId === clusterId) continue;
          const count = feat.properties.point_count;
          const icon = L.divIcon({
            html: `<div><span>${count}</span></div>`,
            className: "marker-cluster",
            iconSize: [40, 40],
          });
          const marker = L.marker([lat, lng], {
            icon,
            title: `Zoom to group of ${count} gauges`,
          });
          marker.on("add", () => {
            marker
              .getElement()
              ?.setAttribute("aria-label", `Zoom to group of ${count} gauges`);
          });
          marker.on("click", (event) => {
            L.DomEvent.stopPropagation(event);
            if (!clusterHandle) return;
            const action = getClusterAction(
              clusterHandle,
              clusterId,
              Math.floor(map.getZoom()),
              MAX_ZOOM,
            );
            if (action.kind === "spiderfy") {
              activeSpider = {
                clusterId,
                center: action.center,
                leaves: action.leaves,
              };
              renderViewportClusters();
              renderSpiderfy();
            } else {
              clearSpiderfy();
              map.setView(action.center, action.targetZoom, { animate: false });
            }
          });
          clusterLayer.addLayer(marker);
        } else {
          const station = (feat as StationFeature).properties.station;
          const marker = L.marker([lat, lng], {
            icon: pointIcon,
            title: `Inspect ${station.provider_id} / ${station.station_id}`,
          });
          marker.on("click", (event) => {
            L.DomEvent.stopPropagation(event);
            data.current.onInspect(station);
          });
          clusterLayer.addLayer(marker);
        }
      }
      scheduleCanvas();
    };

    const symbolObserver = new MutationObserver(() => {
      sprites = undefined;
      scheduleCanvas();
    });
    symbolObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-md-color-scheme"],
    });

    let lastMatches: StationRecord[] | undefined;
    let lastSelected: StationRecord[] | undefined;
    let lastConflicts: ReadonlySet<string> | undefined;

    update.current = () => {
      const current = data.current;
      if (current.catalogueStations !== featureCacheSource) {
        featureCacheSource = current.catalogueStations;
        featureByIndex = buildStationFeatures(current.catalogueStations);
        unselectedClusterCache = new WeakMap();
      }
      if (
        current.matches === lastMatches &&
        current.selected === lastSelected
      ) {
        if (current.conflictKeys !== lastConflicts) scheduleCanvas();
        lastConflicts = current.conflictKeys;
        return;
      }

      clearSpiderfy();
      lastConflicts = current.conflictKeys;
      lastMatches = current.matches;
      lastSelected = current.selected;

      matchingKeys = new Set();
      for (let i = 0; i < current.matches.length; i++) {
        matchingKeys.add(current.matches[i].key);
      }

      if (current.selectedKeys.size === 0) {
        let cached = unselectedClusterCache.get(current.matches);
        if (!cached) {
          cached = buildClusterIndex(
            current.matches,
            current.selectedKeys,
            featureByIndex,
          );
          unselectedClusterCache.set(current.matches, cached);
        }
        clusterHandle = cached;
      } else {
        clusterHandle = buildClusterIndex(
          current.matches,
          current.selectedKeys,
          featureByIndex,
        );
      }

      let extraSelected = 0;
      for (let i = 0; i < current.selected.length; i++) {
        const station = current.selected[i];
        if (station.plottable && !matchingKeys.has(station.key)) {
          extraSelected++;
        }
      }
      let plottableMatches = 0;
      for (let i = 0; i < current.matches.length; i++) {
        if (current.matches[i].plottable) plottableMatches++;
      }
      plottedTotal = plottableMatches + extraSelected;
      canvas.dataset.clustered = String(clusterHandle.clusteredCount);

      renderViewportClusters();
    };

    map.on("zoomend", clearSpiderfy);
    map.on("moveend resize", renderViewportClusters);
    map.on("move zoom", scheduleCanvas);
    map.on("click", (event: L.LeafletMouseEvent) => {
      clearSpiderfy();
      renderViewportClusters();
      let closest: StationRecord | undefined;
      let distance = 100;
      for (const point of selectedPoints) {
        const d =
          (point.x - event.containerPoint.x) ** 2 +
          (point.y - event.containerPoint.y) ** 2;
        if (d <= distance) {
          closest = point.station;
          distance = d;
        }
      }
      if (closest) data.current.onInspect(closest);
    });

    const resizeObserver = new ResizeObserver(() => map.invalidateSize());
    resizeObserver.observe(host.current!);
    update.current();

    return () => {
      themeObserver.disconnect();
      symbolObserver.disconnect();
      resizeObserver.disconnect();
      cancelAnimationFrame(frame);
      clusterLayer.clearLayers();
      spiderLayer.clearLayers();
      map.remove();
      tiles?.off();
      mapRef.current = null;
    };
  }, [basemapKey]);

  useEffect(() => {
    update.current();
  }, [catalogueStations, matches, selected, selectedKeys, conflictKeys]);

  const fit = () => {
    const bounds = computeStationBounds(matches);
    if (!bounds) return;
    mapRef.current?.fitBounds(
      [
        [bounds.minLat, bounds.minLng],
        [bounds.maxLat, bounds.maxLng],
      ],
      {
        padding: [24, 24],
        maxZoom: 12,
        animate: false,
      },
    );
  };

  return (
    <div className="map-shell">
      <div ref={host} className="map" aria-label="Gauge map" />
      <button
        type="button"
        className="fit-map"
        onClick={fit}
        disabled={!matches.some((station) => station.plottable)}
      >
        Zoom to matches
      </button>
      <div className="legend">
        <span>
          <GaugeIcon state="match" /> Match
        </span>
        <span>
          <GaugeIcon state="selected" /> Selected
        </span>
        <span>
          <GaugeIcon state="conflict" /> Conflict
        </span>
      </div>
    </div>
  );
}
