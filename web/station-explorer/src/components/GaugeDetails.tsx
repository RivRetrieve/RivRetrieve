import type { Provider, StationRecord } from "../domain/types";
import { CoordinateWarning } from "../ui/CoordinateWarning";

interface GaugeDetailsProps {
  station: StationRecord;
  provider: Provider | undefined;
  isSelected: boolean;
  onAdd: (station: StationRecord) => void;
  onRemove: (key: string) => void;
  onClose: () => void;
}

/** Inspected station details card shown at the top of the Filtering tab. */
export function GaugeDetails({
  station,
  provider,
  isSelected,
  onAdd,
  onRemove,
  onClose,
}: GaugeDetailsProps) {
  return (
    <section className="inspection" aria-label="Gauge details">
      <div className="section-heading">
        <h3>
          {station.provider_id} / {station.station_id}
        </h3>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close gauge details"
        >
          ×
        </button>
      </div>
      <button
        type="button"
        onClick={() => (isSelected ? onRemove(station.key) : onAdd(station))}
      >
        {isSelected ? "Remove gauge" : "Add gauge"}
      </button>
      <p>{station.station_name ?? "Station name not established"}</p>
      <p>
        <strong>Water body:</strong>{" "}
        {station.water_body_names.length
          ? station.water_body_names.join(" · ")
          : "Not available"}
      </p>
      <p className="coordinate-info">
        Coordinates: {station.latitude ?? "unknown"},{" "}
        {station.longitude ?? "unknown"}. CRS: {station.crs ?? "unknown"}.
        {(!station.crs || station.crs === "unknown") && (
          <CoordinateWarning key={station.key}>
            Unknown CRS. Plotted as EPSG:4326 for exploration only.
          </CoordinateWarning>
        )}
        {station.crs === "EPSG:4269" && (
          <CoordinateWarning key={station.key}>
            NAD83 (EPSG:4269) coordinates displayed on the WGS84 basemap without
            a datum transformation. Approximate location only.
          </CoordinateWarning>
        )}
      </p>
      {!provider?.retrieval && (
        <p className="warning">
          ⚠ Catalogue only. Observation retrieval is unsupported.
        </p>
      )}
    </section>
  );
}
