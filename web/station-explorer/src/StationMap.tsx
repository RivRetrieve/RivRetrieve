import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";
import { stationKey, type Station } from "./domain";
import { basemapTiles } from "./basemap";
import { GaugeIcon, gaugePinSvg, gaugeSprites } from "./GaugeIcon";

export function canPlot(station: Station): boolean {
  return (
    station.latitude !== null &&
    station.longitude !== null &&
    Number.isFinite(station.latitude) &&
    Number.isFinite(station.longitude) &&
    Math.abs(station.latitude) <= 90 &&
    Math.abs(station.longitude) <= 180 &&
    (station.crs === "EPSG:4326" ||
      station.crs === "EPSG:4269" ||
      station.crs === "unknown" ||
      station.crs === null)
  );
}
interface Props {
  matches: Station[];
  selected: Station[];
  basemapKey: string | undefined;
  onInspect: (station: Station) => void;
}
/** Native MarkerCluster discovery; selected gauges keep distinct canvas symbols. */
export function StationMap({
  matches,
  selected,
  basemapKey,
  onInspect,
}: Props) {
  const host = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const data = useRef({ matches, selected, onInspect });
  data.current = { matches, selected, onInspect };
  const update = useRef<() => void>(() => {});
  useEffect(() => {
    const map = L.map(host.current!, {
      center: [46.8, 8.2],
      zoom: 7,
      minZoom: 3,
      maxZoom: 18,
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
        maxZoom: 18,
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

    // Same default grouping, zoom-to-bounds and spiderfy behavior as eStreams.
    const clusters = L.markerClusterGroup().addTo(map);
    const markerCache = new Map<string, L.Marker>();
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
    let matchingKeys = new Set<string>();
    let plotted = 0;
    let selectedPoints: { x: number; y: number; station: Station }[] = [];
    let frame = 0;
    const labelClusters = () => {
      host.current
        ?.querySelectorAll<HTMLElement>(".marker-cluster")
        .forEach((element) => {
          element.setAttribute(
            "aria-label",
            `Zoom to group of ${element.textContent?.trim()} gauges`,
          );
        });
    };
    let sprites: ReturnType<typeof gaugeSprites> | undefined;
    let spriteRatio = 0;
    const draw = () => {
      const size = map.getSize(),
        ratio = window.devicePixelRatio || 1;
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
      selectedPoints = [];
      for (const station of data.current.selected) {
        if (!canPlot(station)) continue;
        const { x, y } = map.latLngToContainerPoint([
          station.latitude!,
          station.longitude!,
        ]);
        if (x < -24 || x > size.x + 24 || y < 0 || y > size.y + 30) continue;
        selectedPoints.push({ x, y: y - 17, station });
        const state = matchingKeys.has(stationKey(station))
          ? "selected"
          : "conflict";
        ctx.drawImage(sprites![state], x - 12, y - 28.5, 25.5, 30);
      }
      canvas.dataset.drawn = String(plotted);
      canvas.dataset.zoom = String(map.getZoom());
      canvas.dataset.centerLat = String(map.getCenter().lat);
      canvas.dataset.centerLng = String(map.getCenter().lng);
      labelClusters();
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(draw);
    };
    const symbolObserver = new MutationObserver(() => {
      sprites = undefined;
      schedule();
    });
    symbolObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-md-color-scheme"],
    });
    let lastMatches: Station[] | undefined, lastSelected: Station[] | undefined;
    update.current = () => {
      const current = data.current;
      if (current.matches === lastMatches && current.selected === lastSelected)
        return;
      lastMatches = current.matches;
      lastSelected = current.selected;
      matchingKeys = new Set(current.matches.map(stationKey));
      const selectedKeys = new Set(current.selected.map(stationKey));
      const markers: L.Marker[] = [];
      plotted = 0;
      for (const station of current.matches) {
        if (!canPlot(station)) continue;
        plotted++;
        const key = stationKey(station);
        if (selectedKeys.has(key)) continue;
        let marker = markerCache.get(key);
        if (!marker) {
          marker = L.marker([station.latitude!, station.longitude!], {
            icon: pointIcon,
            title: `Inspect ${station.provider_id} / ${station.station_id}`,
          }).on("click", () => data.current.onInspect(station));
          markerCache.set(key, marker);
        }
        markers.push(marker);
      }
      plotted += current.selected.filter(
        (station) => canPlot(station) && !matchingKeys.has(stationKey(station)),
      ).length;
      clusters.clearLayers();
      clusters.addLayers(markers);
      canvas.dataset.clustered = String(clusters.getLayers().length);
      schedule();
    };
    clusters.on("animationend", schedule);
    clusters.on("spiderfied", (event) => {
      canvas.dataset.spiderfied = String(
        (event as L.LeafletEvent & { markers: L.Marker[] }).markers.length,
      );
      schedule();
    });
    clusters.on("unspiderfied", () => {
      canvas.dataset.spiderfied = "0";
      schedule();
    });
    map.on("move zoom resize", schedule);
    map.on("click", (event: L.LeafletMouseEvent) => {
      let closest: Station | undefined,
        distance = 100;
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
      map.remove();
      tiles?.off();
      clusters.off();
      mapRef.current = null;
    };
  }, [basemapKey]);
  useEffect(() => {
    update.current();
  }, [matches, selected]);
  const fit = () => {
    const coordinates = matches
      .filter(canPlot)
      .map(
        (station) => [station.latitude!, station.longitude!] as L.LatLngTuple,
      );
    if (coordinates.length)
      mapRef.current?.fitBounds(L.latLngBounds(coordinates), {
        padding: [24, 24],
        maxZoom: 12,
        animate: false,
      });
  };
  return (
    <div className="map-shell">
      <div ref={host} className="map" aria-label="Gauge map" />
      <button
        className="fit-map"
        onClick={fit}
        disabled={!matches.some(canPlot)}
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
