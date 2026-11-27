import {
  controlPhysicalFields,
  type BrowseFilters,
  type ControlPhysicalField,
  type RequestSettings,
  type StationCatalogue,
  type StationRecord,
} from "../domain/types";
import { frequencyError } from "../domain/frequency";
import { GaugeDetails } from "./GaugeDetails";

const label = (field: string) =>
  field[0].toUpperCase() + field.slice(1).replaceAll("_", " ");

interface FilteringTabProps {
  catalogue: StationCatalogue | null;
  catalogueStatus: "loading" | "ready" | "error";
  browse: BrowseFilters;
  settings: RequestSettings;
  matches: StationRecord[];
  inspected: StationRecord | null;
  selectedKeys: ReadonlySet<string>;
  onBrowseChange: (field: "provider" | "station", value: string) => void;
  onSettingChange: (field: ControlPhysicalField, value: string) => void;
  onAddStations: (stations: StationRecord[]) => void;
  onRemoveStation: (key: string) => void;
  onCloseInspection: () => void;
  onClearSearch: () => void;
}

/** Provider/station discovery controls, shared measurement settings, and inspected gauge details. */
export function FilteringTab({
  catalogue,
  catalogueStatus,
  browse,
  settings,
  matches,
  inspected,
  selectedKeys,
  onBrowseChange,
  onSettingChange,
  onAddStations,
  onRemoveStation,
  onCloseInspection,
  onClearSearch,
}: FilteringTabProps) {
  if (catalogueStatus !== "ready" || !catalogue) {
    return <p role="status">Loading public catalogue…</p>;
  }

  const freqFeedback = frequencyError(settings.frequency);

  const physicalControl = (field: ControlPhysicalField) => {
    const fieldError = field === "frequency" ? freqFeedback : null;
    const errorId = fieldError ? `${field}-error` : undefined;
    const options = catalogue.filterOptions[field];
    return (
      <label key={field}>
        {label(field)}
        <input
          aria-label={label(field)}
          aria-invalid={field === "frequency" ? !!fieldError : undefined}
          aria-describedby={errorId}
          value={settings[field] ?? ""}
          list={`values-${field}`}
          placeholder={
            field === "frequency" ? "e.g. PT15M, PT1H, P1D" : "Any (exact match)"
          }
          onChange={(event) => onSettingChange(field, event.target.value)}
        />
        <datalist id={`values-${field}`}>
          {options.map((value) => (
            <option key={value} value={value} />
          ))}
        </datalist>
        {fieldError && (
          <span id={errorId} className="warning">
            {fieldError}
          </span>
        )}
      </label>
    );
  };

  return (
    <>
      {inspected && (
        <GaugeDetails
          station={inspected}
          provider={catalogue.providerById.get(inspected.provider_id)}
          isSelected={selectedKeys.has(inspected.key)}
          onAdd={(station) => onAddStations([station])}
          onRemove={onRemoveStation}
          onClose={onCloseInspection}
        />
      )}
      <h2 data-testid="match-count">
        {matches.length.toLocaleString()} matching{" "}
        {matches.length === 1 ? "gauge" : "gauges"}
      </h2>
      <div className="filter-row">
        <label>
          Provider
          <select
            aria-label="Provider"
            value={browse.provider ?? ""}
            onChange={(event) => onBrowseChange("provider", event.target.value)}
          >
            <option value="">All providers</option>
            {catalogue.providers.map((provider) => (
              <option key={provider.provider_id} value={provider.provider_id}>
                {provider.name ?? provider.provider_id} ({provider.provider_id})
                {provider.retrieval ? "" : " (catalogue only)"}
              </option>
            ))}
          </select>
        </label>
        <label>
          Station
          <input
            aria-label="Station"
            value={browse.station ?? ""}
            placeholder="Any (exact match)"
            onChange={(event) => onBrowseChange("station", event.target.value)}
          />
        </label>
      </div>
      <section
        className="request-settings"
        aria-label="Measurement settings"
      >
        <h3>Requested observations</h3>
        {physicalControl("quantity")}
        <details>
          <summary>More filters</summary>
          <div className="filter-row">
            {controlPhysicalFields.slice(1).map(physicalControl)}
          </div>
        </details>
      </section>
      <div className="actions">
        <button
          type="button"
          className="primary"
          disabled={!matches.length}
          onClick={() => onAddStations(matches)}
        >
          Add all matches
        </button>
        <button type="button" onClick={onClearSearch}>
          Clear search
        </button>
      </div>
    </>
  );
}
