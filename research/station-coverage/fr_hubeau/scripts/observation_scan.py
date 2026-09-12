"""Find any publisher observation value stored under the fr_hubeau research folder.

    find_stored_observations : Folder -> [Violation]   (pure read; empty list = nothing stored)
    body_carries_observations : ResponseBytes -> bool  (pure)

This project does not redistribute source observations. A value is "stored" if it can be read back
from any committed file: a JSON field, a recorded response body (base64 in a recording, or a member
of a bundle), or a CSV column. Checked:

  - every JSON document, and every response body inside a recording or bundle, is walked; a
    measurement key carrying a non-null, non-blank value is a violation, and so is a HydroPortail
    `statistics` object carrying any non-null value, because those statistics are computed from the
    observations;
  - every CSV header must be drawn from ALLOWED_CSV_COLUMNS; a new column is a violation until it has
    been reviewed and added here, because a CSV cell cannot be told apart from a measurement by its
    content;
  - any file type other than the ones below is a violation, because it cannot be scanned.

Measurement keys are the value fields of each route surveyed: Hub'Eau `obs_elab` (`resultat_obs_elab`),
`observations_tr` (`resultat_obs`), `temperature/chronique` (`resultat`), and the HydroPortail series
point value (`v`).
"""

from __future__ import annotations

import base64
import csv
import io
import json
import pathlib
import re
import tarfile
import zipfile

MEASUREMENT_KEYS = frozenset({"resultat_obs_elab", "resultat_obs", "resultat", "v"})
EMBEDDED_VALUE = re.compile(r"[\"'](?:resultat_obs_elab|resultat_obs|resultat|v)[\"']\s*:\s*-?\d")
DERIVED_FROM_OBSERVATIONS = frozenset({"statistics"})
SCANNABLE = frozenset({".md", ".csv", ".json", ".py", ".zip", ".xz", ".html"})
ALLOWED_CSV_COLUMNS = frozenset(
    {
        # evidence/hubeau_count_receipts.csv
        "request_id", "code_station", "product_id", "route", "entity_kind", "entity_code", "native_field",
        "request_url", "retrieved_at", "http_status", "content_type", "response_bytes", "response_sha256",
        "count", "returned_codes", "body_retained", "request_error",
        # evidence/hydroportail_history_receipts.csv
        "window", "window_start", "window_end", "series_code", "series_metric", "points", "first_t",
        "last_t", "statistics_state",
        # inventory/station_product_evidence.csv
        "code_site", "en_service", "status",
        "evidence_basis", "observations", "tested_entity_kind", "tested_entity_code", "window_tested",
        "evidence_refs", "station_organisation_field", "station_organisation_name",
        "organisation_scope_note", "site_series_relation",
        # inventory/history_sample.csv
        "sample_order",
    }
)  # fmt: skip


def _has_value(value: object) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())


def _leaves(node: object):
    if isinstance(node, dict):
        for value in node.values():
            yield from _leaves(value)
    elif isinstance(node, list):
        for item in node:
            yield from _leaves(item)
    else:
        yield node


def _walk(node: object, where: str, found: list[str]) -> bool:
    """Append the first violation in `node`; return True once one is found."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in MEASUREMENT_KEYS and _has_value(value) and not isinstance(value, (dict, list)):
                found.append(f"{where}: measurement key '{key}' carries a value")
                return True
            if key in DERIVED_FROM_OBSERVATIONS and any(_has_value(leaf) for leaf in _leaves(value)):
                found.append(f"{where}: '{key}' carries values computed from observations")
                return True
            if _walk(value, where, found):
                return True
    elif isinstance(node, list):
        for item in node:
            if _walk(item, where, found):
                return True
    return False


def body_carries_observations(raw: bytes) -> bool:
    """Whether a response body carries any observation value.

    A non-JSON body (an HTML page, an error) is checked as text for a measurement key followed by a
    number, because documentation pages embed example responses.
    """
    found: list[str] = []
    _scan_body(raw, "body", found)
    return bool(found)


def _scan_body(raw: bytes, where: str, found: list[str]) -> None:
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        text = raw.decode("utf-8", "replace")
        match = EMBEDDED_VALUE.search(text)
        if match:
            found.append(f"{where}: text embeds a measurement value ({match.group(0)[:40]!r})")
        return
    _walk(document, where, found)


def find_stored_observations(folder: pathlib.Path) -> list[str]:
    found: list[str] = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        name = str(path.relative_to(folder))
        if "__pycache__" in path.parts or path.name == ".DS_Store":
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
        elif path.suffix == ".xz":
            with tarfile.open(path, "r:xz") as bundle:
                for member in bundle:
                    handle = bundle.extractfile(member)
                    if handle is not None:
                        _scan_body(handle.read(), f"{name}!{member.name}", found)
        elif path.suffix == ".csv":
            header = next(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))), [])
            unknown = sorted(set(header) - ALLOWED_CSV_COLUMNS)
            if unknown:
                found.append(f"{name}: unreviewed CSV columns {unknown}")
    return found
