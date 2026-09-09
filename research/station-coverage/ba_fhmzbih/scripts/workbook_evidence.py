"""Shared workbook parsing, classification and evidence writing for the ba_fhmzbih survey.

Measurement presence is read from the worksheet XML directly, never from a dataframe loader.
A blank measurement cell in these workbooks is a self-closing element carrying no value child:

    <c r="B171" s="3"/>                      <- no measurement
    <c r="B5196" s="5" t="n"><v>1.331</v></c> <- measurement

A dataframe loader renders both as NaN, so it cannot distinguish a published blank from a
decode failure. Reading the cell elements keeps that distinction, which is the whole point of
the classification below.

No observation values are committed anywhere in this survey. Responses that carry measurements
keep their request, status, media type, acquisition instant and full-response digest, plus a
derived reading; their bytes are not retained. Responses that carry no measurements - blank-only
workbooks, empty workbooks and failed requests - are retained whole, because establishing that a
file is blank requires every cell and no observation value exists in them to redistribute.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import pathlib
import re
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

EXCEL_EPOCH = datetime(1899, 12, 30)
# The excerpt keeps the opening rows (which show the window start and the row shape) and,
# separately, rows that actually carry a value. Both are needed: a station that begins
# reporting partway through the window has blank opening rows, so opening rows alone cannot
# substantiate a "measurements present" classification.
EXCERPT_HEAD_ROWS = 10
EXCERPT_WITNESS_ROWS = 10

# Status vocabulary. Names are download-scoped on purpose: a blank-only download establishes
# what that download contained, never that the station cannot supply the measurement.
MEASUREMENTS_PRESENT = "measurements_present"
TIMESTAMPED_WITHOUT_MEASUREMENTS = "timestamped_without_measurements"
NO_DATA_ROWS = "no_data_rows"
ACCESS_FAILED = "access_failed"
UNINVESTIGATED = "uninvestigated"
# Expressible because issue #223 requires the category to be distinguishable, but never
# assigned by this survey: no recorded evidence states a station cannot measure a parameter.
UNSUPPORTED = "unsupported"

VOCABULARY = {
    MEASUREMENTS_PRESENT,
    TIMESTAMPED_WITHOUT_MEASUREMENTS,
    NO_DATA_ROWS,
    ACCESS_FAILED,
    UNINVESTIGATED,
    UNSUPPORTED,
}
# Categories whose bytes carry no observations, so the full response is committed.
FULL_BYTES_STATUSES = {TIMESTAMPED_WITHOUT_MEASUREMENTS, NO_DATA_ROWS, ACCESS_FAILED}

_ROW = re.compile(r"<row[^>]*r=\"(\d+)\"[^>]*>(.*?)</row>", re.S)
_SELF_CLOSING_ROW = re.compile(r"<row[^>]*r=\"(\d+)\"[^>]*/>")
_CELL = re.compile(r"<c\b([^>]*?)(?:/>|>(.*?)</c>)", re.S)
_REF = re.compile(r'r="([A-Z]+)(\d+)"')
_TYPE = re.compile(r't="([^"]+)"')
_VALUE = re.compile(r"<v>(.*?)</v>", re.S)
_SI = re.compile(r"<si>(.*?)</si>", re.S)
_TAG = re.compile(r"<[^>]+>")


@dataclass
class WorkbookReading:
    """What one workbook download establishes, read from the worksheet XML."""

    declared_rows: int | None = None
    declared_unit: str = ""
    declared_parameter: str = ""
    declared_station_name: str = ""
    declared_station_number: str = ""
    timeseries_name: str = ""
    data_rows: int = 0
    populated_measurements: int = 0
    observed_window_start: str = ""
    observed_window_end: str = ""
    head_rows: list[tuple[str, str]] = field(default_factory=list)
    witness_rows: list[tuple[str, str]] = field(default_factory=list)
    parse_error: str = ""

    @property
    def status(self) -> str:
        if self.parse_error:
            return ACCESS_FAILED
        if self.data_rows == 0:
            return NO_DATA_ROWS
        if self.populated_measurements == 0:
            return TIMESTAMPED_WITHOUT_MEASUREMENTS
        return MEASUREMENTS_PRESENT

    @property
    def evidence_basis(self) -> str:
        if self.parse_error:
            return f"workbook could not be read: {self.parse_error}"
        if self.data_rows == 0:
            return (
                f"publisher declares #Rows = 0 while still declaring parameter "
                f"{self.declared_parameter!r} and unit {self.declared_unit!r}"
            )
        if self.populated_measurements == 0:
            return (
                f"{self.data_rows} timestamped rows, every measurement cell published empty "
                f"(no <v> child); parameter {self.declared_parameter!r} and unit "
                f"{self.declared_unit!r} still declared"
            )
        return f"{self.populated_measurements} populated measurement cells across {self.data_rows} timestamped rows"


def _serial_to_iso(raw: str) -> str:
    try:
        return (EXCEL_EPOCH + timedelta(days=float(raw))).isoformat(sep=" ", timespec="seconds")
    except (TypeError, ValueError):
        return ""


def read_workbook(raw: bytes) -> WorkbookReading:
    """Read header fields and measurement-cell occupancy straight from the worksheet XML."""
    reading = WorkbookReading()
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8", "replace")
        shared = [
            _TAG.sub("", chunk)
            for chunk in _SI.findall(archive.read("xl/sharedStrings.xml").decode("utf-8", "replace"))
        ]
    except (zipfile.BadZipFile, KeyError, OSError) as error:
        reading.parse_error = f"{type(error).__name__}: {error}"
        return reading

    def cell_text(attributes: str, body: str | None) -> str:
        if body is None:
            return ""
        found = _VALUE.search(body)
        if not found:
            return ""
        text = found.group(1)
        if (kind := _TYPE.search(attributes)) and kind.group(1) == "s":
            index = int(text)
            return shared[index] if 0 <= index < len(shared) else ""
        return text

    rows: dict[int, dict[str, tuple[str, str | None]]] = {}
    for number, body in _ROW.findall(sheet):
        columns: dict[str, tuple[str, str | None]] = {}
        for attributes, inner in _CELL.findall(body):
            if reference := _REF.search(attributes):
                columns[reference.group(1)] = (attributes, inner if inner != "" else None)
        rows[int(number)] = columns
    for number in _SELF_CLOSING_ROW.findall(sheet):
        rows.setdefault(int(number), {})

    header_labels: dict[str, str] = {}
    data_start = None
    for number in sorted(rows):
        columns = rows[number]
        label = cell_text(*columns["A"]) if "A" in columns else ""
        if label == "#Timestamp":
            data_start = number + 1
            break
        if label.startswith("#"):
            header_labels[label] = cell_text(*columns["B"]) if "B" in columns else ""

    reading.declared_station_name = header_labels.get("#Station Name", "")
    reading.declared_station_number = header_labels.get("#Station Number", "")
    reading.declared_parameter = header_labels.get("#Station Parameter Name", "")
    reading.timeseries_name = header_labels.get("#Timeseries Name", "")
    reading.declared_unit = header_labels.get("#Unit Symbol", "")
    declared = header_labels.get("#Rows", "")
    try:
        reading.declared_rows = int(float(declared)) if declared != "" else None
    except ValueError:
        reading.declared_rows = None

    if data_start is None:
        reading.parse_error = "no '#Timestamp' header row found"
        return reading

    timestamps: list[str] = []
    for number in sorted(n for n in rows if n >= data_start):
        columns = rows[number]
        if "A" not in columns:
            continue
        stamp = _serial_to_iso(cell_text(*columns["A"]))
        if not stamp:
            continue
        reading.data_rows += 1
        timestamps.append(stamp)
        # A measurement exists only when the cell carries a value child. A self-closing or
        # value-less <c> is the publisher stating no measurement for that timestamp.
        value = cell_text(*columns["B"]) if "B" in columns else ""
        if value != "":
            reading.populated_measurements += 1
            if len(reading.witness_rows) < EXCERPT_WITNESS_ROWS:
                reading.witness_rows.append((stamp, value))
        if len(reading.head_rows) < EXCERPT_HEAD_ROWS:
            reading.head_rows.append((stamp, value))

    if timestamps:
        reading.observed_window_start = timestamps[0]
        reading.observed_window_end = timestamps[-1]
    return reading


def write_evidence(
    path: pathlib.Path,
    *,
    url: str,
    method: str,
    status_code: int | str,
    content_type: str,
    retrieved_at: str,
    raw: bytes,
    station_no: str,
    product_id: str,
    reading: WorkbookReading | None,
    note: str = "",
) -> dict:
    """Write one evidence file, retaining bytes only where they carry no observations."""
    status = reading.status if reading is not None else ACCESS_FAILED
    digest = hashlib.sha256(raw).hexdigest()
    document: dict = {
        "format_version": 2,
        "station_no": station_no,
        "product_id": product_id,
        "request": {"method": method, "url": url, "parameters": None, "body": None},
        "response": {
            "status_code": status_code,
            "content_type": content_type,
            "retrieved_at": retrieved_at,
            "byte_size": len(raw),
            # Digest of the exact publisher response, never of any derived excerpt below.
            "response_sha256": digest,
        },
    }
    if status in FULL_BYTES_STATUSES:
        document["evidence_kind"] = "response_recording"
        document["response"]["content_base64"] = base64.b64encode(raw).decode()
        document["retention"] = "full response bytes retained; this response carries no observation values"
    else:
        document["evidence_kind"] = "response_digest"
        document["retention"] = (
            "full response bytes not retained: this workbook holds a year of the publisher's "
            "observations. Issue #223 forbids downloading whole observation histories to prove "
            "access, and the source records no redistribution grant. The digest above is over "
            "the exact response; the excerpt below is derived and carries its own separate "
            "digest. The source is a rolling window, so the response digest will not reproduce "
            "on a later fetch."
        )
    if reading is not None:
        excerpt = {
            "note": (
                "derived from the response, not the response itself. Measurement values are NOT "
                "retained: each row records only whether the publisher's cell carried a value. "
                "'head' is the opening data rows; 'witness' is rows whose measurement cell was "
                "populated, which is what substantiates a measurements_present classification - "
                "needed separately because a station beginning partway through the window has "
                "blank opening rows."
            ),
            "head": [{"timestamp": stamp, "has_value": bool(value)} for stamp, value in reading.head_rows],
            "witness": [{"timestamp": stamp, "has_value": bool(value)} for stamp, value in reading.witness_rows],
        }
        excerpt["excerpt_sha256"] = hashlib.sha256(
            json.dumps([excerpt["head"], excerpt["witness"]], ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        document["reading"] = {
            "status": status,
            "evidence_basis": reading.evidence_basis,
            "declared_rows": reading.declared_rows,
            "data_rows": reading.data_rows,
            "populated_measurements": reading.populated_measurements,
            "declared_unit": reading.declared_unit,
            "declared_parameter": reading.declared_parameter,
            "declared_station_name": reading.declared_station_name,
            "declared_station_number": reading.declared_station_number,
            "timeseries_name": reading.timeseries_name,
            "observed_window_start": reading.observed_window_start,
            "observed_window_end": reading.observed_window_end,
            "measurement_cells_read_from": "xl/worksheets/sheet1.xml cell elements",
        }
        document["excerpt"] = excerpt
    if note:
        document["note"] = note
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    return document


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
