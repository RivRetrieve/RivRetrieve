import { useEffect, useMemo, useState } from "react";
import { expandCatalogue } from "./catalogue";
import {
  addStations,
  filterStations,
  generateRequest,
  physicalFields,
  removeStation,
  stationKey,
  type FilterField,
  type Filters,
  type Provider,
  type Station,
} from "./domain";
import { canPlot, StationMap } from "./StationMap";
import "./style.css";

const label = (field: string) => field.replaceAll("_", " ");
export function App() {
  const [catalogue, setCatalogue] = useState<{
    stations: Station[];
    providers: Provider[];
  } | null>(null);
  const [error, setError] = useState("");
  const [filters, setFilters] = useState<Filters>({});
  const [selected, setSelected] = useState<Station[]>([]);
  const [inspected, setInspected] = useState<Station | null>(null);
  const [dates, setDates] = useState({ start: "", end: "" });
  const [copyStatus, setCopyStatus] = useState("");
  const [page, setPage] = useState(0);
  const [browseAll, setBrowseAll] = useState(false);
  const [groupStations, setGroupStations] = useState<Station[] | null>(null);
  const [selectionPage, setSelectionPage] = useState(0);
  const [showCode, setShowCode] = useState(false);
  const [tab, setTab] = useState<"discover" | "selection" | "python">(
    "discover",
  );
  const [panelOpen, setPanelOpen] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    fetch(new URL("catalogue.json", document.baseURI), {
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok)
          throw new Error(`Catalogue loading failed (${response.status}).`);
        return response.json();
      })
      .then((wire) => setCatalogue(expandCatalogue(wire)))
      .catch((reason) => {
        if (reason.name !== "AbortError") setError(String(reason));
      });
    return () => controller.abort();
  }, []);
  const matches = useMemo(
    () => filterStations(catalogue?.stations ?? [], filters),
    [catalogue, filters],
  );
  const preview = useMemo(
    () => generateRequest(selected, filters, dates, catalogue?.providers ?? []),
    [selected, filters, dates, catalogue],
  );
  const conflicts = useMemo(
    () =>
      new Map(preview.conflicts.map((conflict) => [conflict.key, conflict])),
    [preview],
  );
  const selectedKeys = useMemo(
    () => new Set(selected.map(stationKey)),
    [selected],
  );
  const options = useMemo(
    () =>
      Object.fromEntries(
        physicalFields.map((field) => [
          field,
          [
            ...new Set(
              catalogue?.stations.flatMap((station) =>
                station.series
                  .map((series) => series[field])
                  .filter((value) => value != null),
              ) ?? [],
            ),
          ].sort(),
        ]),
      ),
    [catalogue],
  );
  function updateFilter(field: FilterField, value: string) {
    setFilters((current) => {
      const next = { ...current };
      if (value === "") delete next[field];
      else next[field] = value;
      return next;
    });
    setPage(0);
    setGroupStations(null);
    setCopyStatus("");
  }
  function add(stations: Station[]) {
    setSelected((current) => addStations(current, stations));
    setCopyStatus("");
  }
  function remove(station: Station) {
    setSelected((current) => removeStation(current, stationKey(station)));
    setSelectionPage(0);
    setCopyStatus("");
  }
  async function copy() {
    if (preview.blockingReasons.length) return;
    try {
      await navigator.clipboard.writeText(preview.code);
      setCopyStatus("Complete Python request copied.");
    } catch {
      setCopyStatus(
        "Clipboard unavailable. Select the complete preview text to copy it.",
      );
      setShowCode(true);
    }
  }
  const control = (field: FilterField) => (
    <label key={field}>
      {label(field)}
      <input
        aria-label={label(field)}
        value={filters[field] ?? ""}
        list={
          physicalFields.includes(field as (typeof physicalFields)[number])
            ? `values-${field}`
            : undefined
        }
        placeholder="Any (exact match)"
        onChange={(event) => updateFilter(field, event.target.value)}
      />
      {options[field] && (
        <datalist id={`values-${field}`}>
          {options[field].map((value) => (
            <option key={value} value={value!} />
          ))}
        </datalist>
      )}
    </label>
  );
  if (error)
    return (
      <main>
        <h1>Station request builder</h1>
        <p role="alert">
          {error} Prepare the catalogue assets and reload this page.
        </p>
      </main>
    );
  if (!catalogue)
    return (
      <main>
        <h1>Station request builder</h1>
        <p role="status">Loading public catalogue…</p>
      </main>
    );
  const shownCode =
    showCode || preview.code.length < 5000
      ? preview.code
      : preview.code.slice(0, 4000) +
        "\n# … Preview shortened. Copy includes every selected station.\n";
  const browsed =
    groupStations ??
    (browseAll
      ? catalogue.stations.filter(
          (station) =>
            (!filters.provider || station.provider_id === filters.provider) &&
            (!filters.station || station.station_id === filters.station),
        )
      : matches);
  const pageCount = Math.ceil(browsed.length / 30);
  const safeSelectionPage = Math.min(
    selectionPage,
    Math.max(0, Math.ceil(selected.length / 30) - 1),
  );
  return (
    <main className="explorer">
      <StationMap
        matches={matches}
        selected={selected}
        onGroup={(stations) => {
          setGroupStations(stations);
          setPage(0);
          setTab("discover");
          setPanelOpen(true);
        }}
        onInspect={(station) => {
          setInspected(station);
          setTab("discover");
          setPanelOpen(true);
        }}
      />
      <button
        className="panel-toggle"
        onClick={() => setPanelOpen(!panelOpen)}
        aria-expanded={panelOpen}
      >
        {panelOpen ? "Hide panel" : `Gauges · ${selected.length} selected`}
      </button>
      <aside
        className={panelOpen ? "panel" : "panel hidden"}
        aria-label="Gauge request panel"
      >
        <div className="tabs" role="tablist" aria-label="Request steps">
          <button
            role="tab"
            aria-selected={tab === "discover"}
            onClick={() => setTab("discover")}
          >
            Discover
          </button>
          <button
            role="tab"
            aria-selected={tab === "selection"}
            onClick={() => setTab("selection")}
          >
            Selection ({selected.length.toLocaleString()})
            {conflicts.size ? " ⚠" : ""}
          </button>
          <button
            role="tab"
            aria-selected={tab === "python"}
            onClick={() => setTab("python")}
          >
            Python
          </button>
        </div>
        <div className="panel-content">
          <div role="tabpanel" hidden={tab !== "discover"}>
            <h2 data-testid="match-count">
              {matches.length.toLocaleString()} matching gauges
            </h2>
            <div className="filter-row">
              <label>
                provider
                <select
                  aria-label="provider"
                  value={filters.provider ?? ""}
                  onChange={(event) =>
                    updateFilter("provider", event.target.value)
                  }
                >
                  <option value="">All providers</option>
                  {catalogue.providers.map((provider) => (
                    <option
                      key={provider.provider_id}
                      value={provider.provider_id}
                    >
                      {provider.provider_id}
                      {provider.retrieval ? "" : " (catalogue only)"}
                    </option>
                  ))}
                </select>
              </label>
              {control("station")}
              {control("quantity")}
            </div>
            <details>
              <summary>More filters</summary>
              <div className="filter-row">
                {physicalFields.slice(1).map(control)}
                {control("variant")}
                {control("series_id")}
              </div>
              <p className="hint">
                Exact, case-sensitive facts. Unknown facts do not match explicit
                filters.
              </p>
            </details>
            <div className="actions">
              <button
                className="primary"
                disabled={!matches.length}
                onClick={() => add(matches)}
              >
                Add all matches
              </button>
              <button
                onClick={() => {
                  setFilters({});
                  setGroupStations(null);
                  setPage(0);
                  setCopyStatus("");
                }}
              >
                Clear filters
              </button>
            </div>
            {inspected && (
              <section className="inspection" aria-label="Gauge details">
                <div className="section-heading">
                  <h3>
                    {inspected.provider_id} / {inspected.station_id}
                  </h3>
                  <button
                    onClick={() => setInspected(null)}
                    aria-label="Close gauge details"
                  >
                    ×
                  </button>
                </div>
                <p>
                  {inspected.station_name ?? "Station name not established"}
                </p>
                <p>
                  Coordinates: {inspected.latitude ?? "unknown"},{" "}
                  {inspected.longitude ?? "unknown"}. CRS:{" "}
                  {inspected.crs ?? "unknown"}.
                </p>
                {(!inspected.crs || inspected.crs === "unknown") && (
                  <p className="warning">
                    ⚠ Unknown CRS. Plotted as EPSG:4326 for exploration only.
                  </p>
                )}
                {inspected.crs === "EPSG:4269" && (
                  <p className="warning">
                    ⚠ NAD83 (EPSG:4269) coordinates displayed on the WGS84
                    basemap without a datum transformation. Approximate location
                    only.
                  </p>
                )}
                {!catalogue.providers.find(
                  (provider) => provider.provider_id === inspected.provider_id,
                )?.retrieval && (
                  <p className="warning">
                    ⚠ Catalogue only. Observation retrieval is unsupported.
                  </p>
                )}
                <button
                  onClick={() =>
                    selectedKeys.has(stationKey(inspected))
                      ? remove(inspected)
                      : add([inspected])
                  }
                >
                  {selectedKeys.has(stationKey(inspected))
                    ? "Remove gauge"
                    : "Add gauge"}
                </button>
                <details>
                  <summary>
                    Catalogue series and physical facts (
                    {inspected.series.length} fact segments)
                  </summary>
                  {inspected.series.map((series, index) => (
                    <dl key={index}>
                      <dt>Series identity</dt>
                      <dd>{series.series_id}</dd>
                      <dt>Source variant / published ID</dt>
                      <dd>
                        {series.variant ?? "not established"} /{" "}
                        {series.published_id ?? "not established"}
                      </dd>
                      {physicalFields.map((field) => (
                        <div key={field}>
                          <dt>{label(field)}</dt>
                          <dd>
                            {series[field] ??
                              `not established (${series[`${field}_state`] ?? "unknown"})`}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  ))}
                </details>
              </section>
            )}
            <details
              className="match-list"
              open={groupStations ? true : undefined}
            >
              <summary>Browse gauge list</summary>
              {groupStations && (
                <p className="hint">
                  {groupStations.length} gauges in the clicked group.{" "}
                  <button onClick={() => setGroupStations(null)}>
                    Return to matches
                  </button>
                </p>
              )}
              <label className="browse-all">
                <input
                  type="checkbox"
                  checked={browseAll}
                  onChange={(event) => {
                    setBrowseAll(event.target.checked);
                    setGroupStations(null);
                    setPage(0);
                  }}
                />
                Include entries without matching series (provider and station
                filters still apply)
              </label>
              <p>
                {browsed.length.toLocaleString()} entries in this list. Adding a
                non-match creates a conflict.
              </p>
              <ul>
                {browsed.slice(page * 30, page * 30 + 30).map((station) => (
                  <li key={stationKey(station)}>
                    <button onClick={() => setInspected(station)}>
                      Inspect {station.provider_id} / {station.station_id}
                    </button>
                    <span>{station.station_name}</span>
                    {selectedKeys.has(stationKey(station)) && (
                      <strong>◆ Selected</strong>
                    )}
                  </li>
                ))}
              </ul>
              <div className="pagination">
                <button disabled={page === 0} onClick={() => setPage(page - 1)}>
                  Previous matches
                </button>
                <span>
                  Page {pageCount ? page + 1 : 0} of {pageCount}
                </span>
                <button
                  disabled={page + 1 >= pageCount}
                  onClick={() => setPage(page + 1)}
                >
                  Next matches
                </button>
              </div>
            </details>

            <details className="about">
              <summary>About this catalogue</summary>
              <p className="hint">
                {catalogue.stations.length.toLocaleString()} catalogue entries.
                Some have no series described; include them in the list to
                inspect them.{" "}
                {matches
                  .filter((station) => !canPlot(station))
                  .length.toLocaleString()}{" "}
                matches cannot be plotted.
              </p>
              <p className="hint">
                A listing does not guarantee observations in any period, or a
                unique physical site across providers. Retrieval may reveal more
                matching series. Unknown-CRS and NAD83 positions are approximate
                displays, not certified coordinates.
              </p>
            </details>
          </div>
          <div role="tabpanel" hidden={tab !== "selection"}>
            {" "}
            <section>
              <h2>Selection ({selected.length.toLocaleString()})</h2>
              <p data-testid="selection-counts">
                {(selected.length - conflicts.size).toLocaleString()} matching ·{" "}
                {conflicts.size.toLocaleString()} conflicting
              </p>
              {!selected.length && (
                <p>No gauges selected. Inspect a gauge or add all matches.</p>
              )}
              {!!conflicts.size && (
                <>
                  <p className="warning">
                    ⚠ Filters changed. Your gauges are preserved. Change filters
                    or remove non-matching gauges.
                  </p>
                  <button
                    onClick={() => {
                      setSelected((current) =>
                        current.filter(
                          (station) => !conflicts.has(stationKey(station)),
                        ),
                      );
                      setSelectionPage(0);
                    }}
                  >
                    Remove non-matching gauges
                  </button>
                </>
              )}
              {!!selected.length && (
                <button
                  onClick={() => {
                    setSelected([]);
                    setSelectionPage(0);
                    setCopyStatus("");
                  }}
                >
                  Clear selection
                </button>
              )}
              <ul className="selection-list">
                {selected
                  .slice(safeSelectionPage * 30, safeSelectionPage * 30 + 30)
                  .map((station) => (
                    <li key={stationKey(station)}>
                      <strong>
                        {conflicts.has(stationKey(station)) ? "⚠" : "◆"}{" "}
                        {station.provider_id} / {station.station_id}
                      </strong>
                      <button
                        onClick={() => {
                          setInspected(station);
                          setTab("discover");
                        }}
                        aria-label={`Inspect selected ${station.provider_id} / ${station.station_id}`}
                      >
                        Inspect
                      </button>
                      <button
                        onClick={() => remove(station)}
                        aria-label={`Remove ${station.provider_id} / ${station.station_id}`}
                      >
                        Remove
                      </button>
                      {conflicts
                        .get(stationKey(station))
                        ?.reasons.map((reason) => (
                          <p className="warning" key={reason}>
                            {reason}
                          </p>
                        ))}
                      {!catalogue.providers.find(
                        (provider) =>
                          provider.provider_id === station.provider_id,
                      )?.retrieval && (
                        <p className="warning">
                          ⚠ Unsupported observation retrieval (catalogue only).
                        </p>
                      )}
                    </li>
                  ))}
              </ul>
              {selected.length > 30 && (
                <div className="pagination">
                  <button
                    disabled={!safeSelectionPage}
                    onClick={() => setSelectionPage(safeSelectionPage - 1)}
                  >
                    Previous selected
                  </button>
                  <span>
                    {safeSelectionPage + 1} / {Math.ceil(selected.length / 30)}
                  </span>
                  <button
                    disabled={(safeSelectionPage + 1) * 30 >= selected.length}
                    onClick={() => setSelectionPage(safeSelectionPage + 1)}
                  >
                    Next selected
                  </button>
                </div>
              )}
            </section>
            {!!preview.blockingReasons.length && (
              <p className="warning">
                ⚠ Request unresolved. Review the Python tab for dates and copy
                requirements.
              </p>
            )}
            <button className="primary" onClick={() => setTab("python")}>
              Preview Python
            </button>
          </div>
          <div role="tabpanel" hidden={tab !== "python"}>
            {" "}
            <section className="request">
              <h2>Request preview</h2>
              <div className="dates">
                <label>
                  Start date (required)
                  <input
                    aria-label="Start date"
                    type="date"
                    value={dates.start}
                    onChange={(event) => {
                      setDates({ ...dates, start: event.target.value });
                      setCopyStatus("");
                    }}
                  />
                </label>
                <label>
                  End date (optional)
                  <input
                    aria-label="End date"
                    type="date"
                    value={dates.end}
                    onChange={(event) => {
                      setDates({ ...dates, end: event.target.value });
                      setCopyStatus("");
                    }}
                  />
                </label>
              </div>
              <p className="hint">
                Source wall-clock dates; both endpoints are included. An omitted
                end uses the caller machine’s current local date; start must not
                be later than that date at execution. These dates do not test
                observation coverage.
              </p>
              {!!preview.blockingReasons.length && (
                <div className="warning" role="status">
                  <strong>⚠ Request unresolved. Copy is blocked.</strong>
                  <ul>
                    {preview.blockingReasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                </div>
              )}
              <button
                className="primary"
                disabled={!!preview.blockingReasons.length}
                onClick={copy}
              >
                Copy Python request
              </button>
              <span role="status" className="copy-status">
                {copyStatus}
              </span>
              <pre aria-label="Python request">
                <code>{shownCode}</code>
              </pre>
              {preview.code.length >= 5000 && (
                <button onClick={() => setShowCode(!showCode)}>
                  {showCode ? "Shorten preview" : "Show complete preview"}
                </button>
              )}
            </section>
          </div>
        </div>
      </aside>
    </main>
  );
}
