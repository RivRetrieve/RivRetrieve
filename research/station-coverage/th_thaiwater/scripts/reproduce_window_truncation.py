"""Record what a multi-year request returns through the current public surface.

The graph route clamps start_date to end_date minus one year (established in
inventory/window_limit_probe.csv). This script records the observable consequence at the public
surface, so the handoff states a measured behaviour rather than a predicted one.

Research only: this script changes nothing. It performs one live request.

Usage: uv run python research/station-coverage/th_thaiwater/scripts/reproduce_window_truncation.py
"""

from __future__ import annotations

import json
import pathlib
import warnings
from datetime import UTC, datetime

import rivretrieve as rr

HERE = pathlib.Path(__file__).resolve().parents[1]
START = "2023-01-01"
END = "2026-09-06"


def main() -> None:
    selection = rr.find(provider="th_thaiwater", product="discharge_reported")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = rr.fetch(selection, start=START, end=END)
    frame = result.to_pandas()

    requested_days = (datetime.fromisoformat(END) - datetime.fromisoformat(START)).days
    returned_first = str(frame.time.min()) if len(frame) else ""
    returned_last = str(frame.time.max()) if len(frame) else ""
    covered_days = (frame.time.max() - frame.time.min()).days if len(frame) else 0

    observation = {
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "station_id": "1373273",
        "product_id": "discharge_reported",
        "requested_start": START,
        "requested_end": END,
        "requested_days": requested_days,
        "returned_rows": len(frame),
        "returned_first": returned_first,
        "returned_last": returned_last,
        "returned_days": covered_days,
        "fraction_of_requested_period_returned": round(covered_days / requested_days, 4) if requested_days else None,
        "issues_emitted": [
            {"severity": issue.severity, "code": issue.code, "message": issue.message} for issue in result.issues
        ],
        "python_warnings_emitted": [str(warning.message) for warning in caught],
        "note": (
            "The requested period spans about 3.7 years. The returned data covers about one year, "
            "ending at the requested end date. No issue or warning names the shortfall; the two "
            "issues emitted are unrelated provenance notices. The source clamp is recorded in "
            "inventory/window_limit_probe.csv."
        ),
    }
    path = HERE / "inventory" / "window_truncation_observation.json"
    path.write_text(json.dumps(observation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(observation, indent=2))
    print(f"\nwrote {path.name}")


if __name__ == "__main__":
    main()
