"""Find any publisher observation value stored under a research folder.

    find_stored_observations : Folder -> [Violation]   (pure read; empty list = nothing stored)

This project does not redistribute source observations. A value is "stored" if it can be read back
from any committed file: a JSON field, a recorded response body (base64 in a recording, or a member
of a bundle), or a CSV column. Checked:

  - every JSON document, and every response body inside a recording or bundle, is walked; a
    measurement key carrying a non-null, non-blank value is a violation;
  - every CSV header must be drawn from ALLOWED_CSV_COLUMNS; a new column is a violation until it
    has been reviewed and added here, because a CSV cell cannot be told apart from a measurement by
    its content;
  - any file type other than the ones below is a violation, because it cannot be scanned.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import pathlib
import zipfile

MEASUREMENT_KEYS = frozenset(
    {
        "value",
        "discharge",
        "value_out",
        "waterlevel_m",
        "waterlevel_msl",
        "waterlevel_msl_previous",
        "flow_rate",
        "storage_percent",
        "diff_wl_bank",
    }
)
SCANNABLE = frozenset({".md", ".csv", ".json", ".py", ".zip"})
ALLOWED_CSV_COLUMNS = frozenset(
    {
        # evidence/graph_receipts.csv
        "request_id", "station_id", "window_start", "window_end", "request_url", "retrieved_at",
        "http_status", "content_type", "response_bytes", "response_sha256", "response_gzip6_bytes",
        "result", "grid_rows", "nonnull_value", "nonnull_discharge", "nonnull_value_out", "grid_first",
        "grid_last", "body_retained", "request_error",
        # inventory/station_product_evidence.csv
        "station_name_th", "river_name", "agency", "basin", "product_id", "native_field", "status",
        "evidence_basis", "nonnull_observations", "window_dates", "response_body_retained",
        "evidence_ref", "in_live_snapshot_2026_09_07", "snapshot_discharge_state",
        # inventory/metadata_vs_graph.csv
        "snapshot_presence", "graph_discharge_status", "graph_stage_status", "comparison",
        # inventory/population_churn.csv
        "change", "name_th", "name_en", "river", "latest_reading_at", "note",
        # inventory/window_limit_probe.csv (as acquired) and window_limit_readings.csv
        "requested_span", "requested_start", "requested_end", "rows", "returned_first", "returned_last",
        "probed_at", "requested_elapsed_days", "requested_inclusive_dates", "returned_inclusive_dates",
        "rows_per_returned_date", "start_honoured", "probe_label_as_recorded",
        # recordings/waterlevel_load_live.stations.csv (populated/null state only, never the value)
        "agency_en", "basin_en", "waterlevel_datetime", "discharge_state", "waterlevel_m_state",
        "waterlevel_msl_state", "waterlevel_msl_previous_state", "flow_rate_state",
        "storage_percent_state", "diff_wl_bank_state",
    }
)  # fmt: skip


def _walk(node: object, where: str, found: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in MEASUREMENT_KEYS and value is not None and not (isinstance(value, str) and not value.strip()):
                found.append(f"{where}: measurement key '{key}' carries a value")
                return  # one per document is enough to fail
            _walk(value, where, found)
            if found and found[-1].startswith(where):
                return
    elif isinstance(node, list):
        for item in node:
            _walk(item, where, found)
            if found and found[-1].startswith(where):
                return


def _scan_body(raw: bytes, where: str, found: list[str]) -> None:
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return  # a non-JSON body (an HTTP 500 stack trace) has no measurement field to carry
    _walk(document, where, found)


def find_stored_observations(folder: pathlib.Path) -> list[str]:
    found: list[str] = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        name = str(path.relative_to(folder))
        if "__pycache__" in path.parts:
            continue
        if path.suffix not in SCANNABLE:
            found.append(f"{name}: file type {path.suffix or '(none)'} cannot be scanned for observations")
        elif path.suffix == ".json":
            document = json.loads(path.read_text(encoding="utf-8"))
            encoded = (document.get("response") or {}).get("content_base64") if isinstance(document, dict) else None
            if encoded is not None:
                _scan_body(base64.b64decode(encoded), f"{name} (recorded body)", found)
            _walk(document, name, found)
        elif path.suffix == ".zip":
            with zipfile.ZipFile(path) as bundle:
                for member in bundle.namelist():
                    _scan_body(bundle.read(member), f"{name}!{member}", found)
        elif path.suffix == ".csv":
            header = next(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))), [])
            unknown = sorted(set(header) - ALLOWED_CSV_COLUMNS)
            if unknown:
                found.append(f"{name}: unreviewed CSV columns {unknown}")
    return found
