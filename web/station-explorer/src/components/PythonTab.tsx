import { dateErrors } from "../domain/dates";
import type { RequestDates } from "../domain/types";
import { PythonPreview } from "../ui/PythonPreview";

interface PythonTabProps {
  active: boolean;
  dates: RequestDates;
  selectedCount: number;
  omittedStationCount: number;
  blockingReasons: string[];
  previewCode: string;
  copyStatus: string;
  onDateChange: (field: keyof RequestDates, value: string) => void;
  onCopy: () => void;
}

/** Retrieval date inputs, validation blockers, lazy highlighted Python preview, and full copy. */
export function PythonTab({
  active,
  dates,
  selectedCount,
  omittedStationCount,
  blockingReasons,
  previewCode,
  copyStatus,
  onDateChange,
  onCopy,
}: PythonTabProps) {
  const dateFeedback = dateErrors(dates);

  return (
    <section className="request">
      <h2>Retrieval dates</h2>
      <div className="dates">
        <label>
          Start date (required)
          <input
            aria-label="Start date"
            aria-invalid={!!dateFeedback.start}
            aria-describedby={
              dateFeedback.start ? "start-date-error" : undefined
            }
            type="date"
            value={dates.start}
            onChange={(event) => onDateChange("start", event.target.value)}
          />
          {dateFeedback.start && (
            <span id="start-date-error" className="warning">
              {dateFeedback.start}
            </span>
          )}
        </label>
        <label>
          End date (optional)
          <input
            aria-label="End date"
            aria-invalid={!!dateFeedback.end}
            aria-describedby={dateFeedback.end ? "end-date-error" : undefined}
            type="date"
            value={dates.end}
            onChange={(event) => onDateChange("end", event.target.value)}
          />
          {dateFeedback.end && (
            <span id="end-date-error" className="warning">
              {dateFeedback.end}
            </span>
          )}
        </label>
      </div>
      <a
        className="date-help"
        href="../../usage/#time-labels-and-request-windows"
        target="_top"
      >
        Date documentation
      </a>
      <h2>Request preview</h2>
      {!!blockingReasons.length && (
        <div className="warning" role="status">
          <strong>⚠ Request unresolved. Copy is blocked.</strong>
          <ul>
            {blockingReasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      )}
      <button
        type="button"
        className="primary"
        disabled={!!blockingReasons.length}
        onClick={onCopy}
      >
        Copy Python request
      </button>
      <span role="status" className="copy-status">
        {copyStatus}
      </span>
      {active && <PythonPreview code={previewCode} />}
      {omittedStationCount > 0 && (
        <p className="hint">
          10 gauge IDs shown. Copy includes all {selectedCount.toLocaleString()}{" "}
          gauges.
        </p>
      )}
    </section>
  );
}
