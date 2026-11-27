import type { Conflict, Provider, StationRecord } from "../domain/types";
import { GaugeIcon } from "../map/gaugeSymbol";
import { SELECTION_PAGE_SIZE } from "../state/explorerState";

interface SelectionTabProps {
  selected: StationRecord[];
  conflicts: ReadonlyMap<string, Conflict>;
  providerById: ReadonlyMap<string, Provider>;
  blockingReasonCount: number;
  page: number;
  onPageChange: (page: number) => void;
  onInspect: (station: StationRecord) => void;
  onRemoveStation: (key: string) => void;
  onRemoveIncompatible: () => void;
  onClearSelection: () => void;
  onPreviewPython: () => void;
}

/** Paginated list of selected gauges with conflict diagnostics and bulk actions. */
export function SelectionTab({
  selected,
  conflicts,
  providerById,
  blockingReasonCount,
  page,
  onPageChange,
  onInspect,
  onRemoveStation,
  onRemoveIncompatible,
  onClearSelection,
  onPreviewPython,
}: SelectionTabProps) {
  const pageStart = page * SELECTION_PAGE_SIZE;
  const pageItems = selected.slice(pageStart, pageStart + SELECTION_PAGE_SIZE);
  const pageCount = Math.ceil(selected.length / SELECTION_PAGE_SIZE);

  return (
    <>
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
              ⚠ Selected gauges do not match the requested observations. Change
              measurement settings or remove incompatible gauges.
            </p>
            <button type="button" onClick={onRemoveIncompatible}>
              Remove incompatible gauges
            </button>
          </>
        )}
        {!!selected.length && (
          <button type="button" onClick={onClearSelection}>
            Clear selection
          </button>
        )}
        <ul className="selection-list">
          {pageItems.map((station) => {
            const conflict = conflicts.get(station.key);
            const provider = providerById.get(station.provider_id);
            return (
              <li className="selection-card" key={station.key}>
                <div className="selection-card-heading">
                  <GaugeIcon state={conflict ? "conflict" : "selected"} />
                  <div className="selection-card-identity">
                    <h3>
                      {station.station_name ?? "Station name not established"}
                    </h3>
                    <p>
                      {station.provider_id} / {station.station_id}
                    </p>
                  </div>
                </div>
                <p className="selection-state">
                  {conflict
                    ? "Does not match measurement settings"
                    : "Matches measurement settings"}
                </p>
                <div className="selection-card-actions">
                  <button
                    type="button"
                    onClick={() => onInspect(station)}
                    aria-label={`Inspect selected ${station.provider_id} / ${station.station_id}`}
                  >
                    Inspect
                  </button>
                  <button
                    type="button"
                    onClick={() => onRemoveStation(station.key)}
                    aria-label={`Remove ${station.provider_id} / ${station.station_id}`}
                  >
                    Remove
                  </button>
                </div>
                {conflict?.reasons.map((reason) => (
                  <p className="warning" key={reason}>
                    {reason}
                  </p>
                ))}
                {!provider?.retrieval && (
                  <p className="warning">
                    ⚠ Unsupported observation retrieval (catalogue only).
                  </p>
                )}
              </li>
            );
          })}
        </ul>
        {selected.length > SELECTION_PAGE_SIZE && (
          <div className="pagination">
            <button
              type="button"
              disabled={!page}
              onClick={() => onPageChange(page - 1)}
            >
              Previous selected
            </button>
            <span>
              {page + 1} / {pageCount}
            </span>
            <button
              type="button"
              disabled={(page + 1) * SELECTION_PAGE_SIZE >= selected.length}
              onClick={() => onPageChange(page + 1)}
            >
              Next selected
            </button>
          </div>
        )}
      </section>
      {!!blockingReasonCount && (
        <p className="warning">
          ⚠ Request unresolved. Check dates and copy requirements in Python.
        </p>
      )}
      <button type="button" className="primary" onClick={onPreviewPython}>
        Preview Python
      </button>
    </>
  );
}
