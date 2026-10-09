import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { stationKey, type Station } from "./domain";
import { groupPoints } from "./mapPoints";

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
  onInspect: (station: Station) => void;
  onGroup: (stations: Station[]) => void;
}
/** Canvas singles plus bounded group markers avoid a Leaflet layer per gauge. */
export function StationMap({ matches, selected, onInspect, onGroup }: Props) {
  const [tileError, setTileError] = useState(false);
  const host = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const data = useRef({ matches, selected, onInspect, onGroup });
  const redraw = useRef<() => void>(() => {});
  data.current = { matches, selected, onInspect, onGroup };
  useEffect(() => {
    const map = L.map(host.current!, {
      center: [46.8, 8.2],
      zoom: 7,
      minZoom: 2,
      worldCopyJump: false,
    });
    // Initial country view only; discovery remains all-provider and unselected.
    map.fitBounds(
      [
        [45.7, 5.8],
        [47.9, 10.6],
      ],
      {
        paddingTopLeft: [32, 32],
        paddingBottomRight: [
          32,
          host.current!.clientWidth <= 640
            ? host.current!.clientHeight / 2 + 32
            : 32,
        ],
        maxZoom: 8,
        animate: false,
      },
    );
    mapRef.current = map;
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      noWrap: true,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    })
      .on("tileerror", () => setTileError(true))
      .addTo(map);
    const canvas = L.DomUtil.create(
      "canvas",
      "station-points",
      map.getContainer(),
    );
    canvas.setAttribute("aria-hidden", "true");
    const clusterLayer = L.layerGroup().addTo(map);
    let projected: { x: number; y: number; station: Station }[] = [];
    let frame = 0;
    const draw = () => {
      const { matches, selected } = data.current;
      const size = map.getSize();
      const ratio = window.devicePixelRatio || 1;
      canvas.width = size.x * ratio;
      canvas.height = size.y * ratio;
      canvas.style.width = `${size.x}px`;
      canvas.style.height = `${size.y}px`;
      const ctx = canvas.getContext("2d")!;
      ctx.scale(ratio, ratio);
      const selectedKeys = new Set(selected.map(stationKey));
      const matchingKeys = new Set(matches.map(stationKey));
      projected = [];
      const point = (
        station: Station,
        kind: "match" | "selected" | "conflict",
      ) => {
        if (!canPlot(station)) return;
        const { x, y } = map.latLngToContainerPoint([
          station.latitude!,
          station.longitude!,
        ]);
        if (x < -8 || x > size.x + 8 || y < -8 || y > size.y + 8) return;
        projected.push({ x, y, station });
        ctx.beginPath();
        if (kind === "match") {
          ctx.arc(x, y, 2.6, 0, 2 * Math.PI);
          ctx.fillStyle = "#136f91";
        } else if (kind === "selected") {
          ctx.moveTo(x, y - 6);
          ctx.lineTo(x + 6, y);
          ctx.lineTo(x, y + 6);
          ctx.lineTo(x - 6, y);
          ctx.closePath();
          ctx.fillStyle = "#6d28d9";
        } else {
          ctx.moveTo(x, y - 8);
          ctx.lineTo(x + 7, y + 6);
          ctx.lineTo(x - 7, y + 6);
          ctx.closePath();
          ctx.fillStyle = "#ad3909";
        }
        ctx.fill();
        if (kind !== "match") {
          ctx.strokeStyle = "white";
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      };
      clusterLayer.clearLayers();
      const candidates = matches
        .filter(
          (station) =>
            !selectedKeys.has(stationKey(station)) && canPlot(station),
        )
        .map((station) => {
          const position = map.latLngToContainerPoint([
            station.latitude!,
            station.longitude!,
          ]);
          return { x: position.x, y: position.y, station };
        })
        .filter(
          ({ x, y }) =>
            x >= -40 && x <= size.x + 40 && y >= -40 && y <= size.y + 40,
        );
      const groups = groupPoints(candidates, 64);
      let groupedCount = 0;
      for (const group of groups) {
        if (group.members.length === 1) {
          point(group.members[0].station, "match");
          continue;
        }
        groupedCount += group.members.length;
        const members = group.members.map((member) => member.station);
        const title = `Zoom to group of ${members.length.toLocaleString()} gauges`;
        const marker = L.marker(
          map.containerPointToLatLng([group.x, group.y]),
          {
            icon: L.divIcon({
              className: "gauge-cluster",
              html: `<span>${members.length.toLocaleString()}</span>`,
              iconSize: [44, 44],
              iconAnchor: [22, 22],
            }),
            title,
            keyboard: true,
          },
        ).addTo(clusterLayer);
        marker.getElement()?.setAttribute("aria-label", title);
        marker.on("click", () => {
          if (map.getZoom() >= 18) {
            data.current.onGroup(members);
            return;
          }
          const bounds = L.latLngBounds(
            members.map(
              (station) =>
                [station.latitude!, station.longitude!] as L.LatLngTuple,
            ),
          );
          const zoom = Math.max(
            map.getZoom() + 1,
            Math.min(18, map.getBoundsZoom(bounds, false, L.point(80, 80))),
          );
          map.setView(bounds.getCenter(), zoom, { animate: false });
        });
      }
      selected.forEach((station) =>
        point(
          station,
          matchingKeys.has(stationKey(station)) ? "selected" : "conflict",
        ),
      );
      canvas.dataset.drawn = String(projected.length + groupedCount);
      canvas.dataset.clusters = String(
        groups.filter((group) => group.members.length > 1).length,
      );
      canvas.dataset.zoom = String(map.getZoom());
      canvas.dataset.centerLat = String(map.getCenter().lat);
      canvas.dataset.centerLng = String(map.getCenter().lng);
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(draw);
    };
    redraw.current = schedule;
    map.on("move zoom resize", schedule);
    map.on("click", (event: L.LeafletMouseEvent) => {
      let nearest: Station | undefined;
      let distance = 100;
      for (const item of projected) {
        const d =
          (item.x - event.containerPoint.x) ** 2 +
          (item.y - event.containerPoint.y) ** 2;
        if (d <= distance) {
          nearest = item.station;
          distance = d;
        }
      }
      if (nearest) data.current.onInspect(nearest);
    });
    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(host.current!);
    schedule();
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      map.remove();
      mapRef.current = null;
    };
  }, []);
  useEffect(() => {
    redraw.current();
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
      {tileError && (
        <p className="tile-warning" role="status">
          Some basemap tiles are unavailable. Gauge points remain visible.
        </p>
      )}
      <div className="legend">
        <span>● Match</span>
        <span>◆ Selected</span>
        <span>▲ Conflict</span>
      </div>
    </div>
  );
}
