"""IMGW's published hydrological date does not require its additional month cell."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.providers.pl_imgw import bulk

DATA = Path("tests/test_data") / "pl_imgw_date_fields"
SOURCE = (" 149220010", "NOWOSIELCE", "Pielnica (22618)", "1992", "07", "16", "137", ".170", "99.9", "")


def test_date_evidence_retains_exact_publisher_bytes(retained_evidence_root: Path):
    for name in ("codz_1992_07.zip", "hydrologia_info_ogolne.txt", "CODZ_publiczne_format.txt"):
        metadata = json.loads(((retained_evidence_root / DATA) / (name + ".metadata.json")).read_text())
        assert hashlib.sha256(((retained_evidence_root / DATA) / name).read_bytes()).hexdigest() == metadata[
            "sha256"
        ].removeprefix("sha256:")
        assert metadata["status"] == 200
    with zipfile.ZipFile((retained_evidence_root / DATA) / "codz_1992_07.zip") as archive:
        metadata = json.loads(((retained_evidence_root / DATA) / "codz_1992_07.zip.metadata.json").read_text())
        assert hashlib.sha256(archive.read(metadata["member"])).hexdigest() == metadata["member_sha256"]
    records = list(bulk._iter_imgw_raw_records((retained_evidence_root / DATA) / "codz_1992_07.zip"))
    assert len(records) == 25408
    assert records[16247] == SOURCE
    assert sum(not record[9].strip() for record in records) == 1


@pytest.mark.parametrize("month", range(1, 13))
@pytest.mark.parametrize("calendar_cell", ["", " \t", "published"])
def test_hydrological_date_alone_defines_calendar_label_and_retains_all_cells(tmp_path, month, calendar_cell):
    # Synthetic complete-year boundary cases use no neighboring records.
    calendar_month = month + 10 if month <= 2 else month - 2
    raw_month = f"{calendar_month:02d}" if calendar_cell == "published" else calendar_cell
    source = (*SOURCE[:3], "1992", f"{month:02d}", "16", *SOURCE[6:9], raw_month)
    path = tmp_path / f"codz_1992_{month:02d}.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(path.stem + ".csv", (";".join(source) + "\r\n").encode("cp1250"))
    decoded = pl.concat(batch.rows for batch in bulk.decode_imgw_batches(path).batches).sort("product")
    expected = pl.DataFrame(
        {
            "product": ["discharge_daily", "stage_daily", "water_temperature_daily"],
            "station_id": ["149220010"] * 3,
            "time": [datetime(1991 if month <= 2 else 1992, calendar_month, 16)] * 3,
            "time_zone": ["unknown"] * 3,
            "value": [0.17, 137.0, None],
            "value_state": ["published_value", "published_value", "published_null"],
            **{column.name: [value] * 3 for column, value in zip(bulk.IMGW_SOURCE_COLUMNS, source, strict=True)},
        }
    )
    assert_frame_equal(decoded.select(expected.columns), expected)


@pytest.mark.parametrize(("year", "day", "valid"), [(1992, 29, True), (1991, 29, False), (1992, 30, False)])
def test_blank_additional_month_keeps_calendar_day_validation(year, day, valid):
    source = (*SOURCE[:3], str(year), "04", str(day), *SOURCE[6:])
    rows = []
    if valid:
        bulk._emit_source_row(source, "source.csv", 1, rows)
        assert rows[0]["time"] == datetime(year, 2, day)
    else:
        with pytest.raises(ValueError, match="invalid calendar date"):
            bulk._emit_source_row(source, "source.csv", 1, rows)


@pytest.mark.parametrize(
    ("position", "value", "reason"),
    [
        (3, "", "hydrological_year"),
        (3, "unknown", "hydrological_year"),
        (3, "0", "calendar date"),
        (3, "10000", "calendar date"),
        (4, "", "month_indicator"),
        (4, "unknown", "month_indicator"),
        (4, "0", "month_indicator"),
        (4, "13", "month_indicator"),
        (5, "", "day"),
        (5, "unknown", "day"),
        (5, "0", "calendar date"),
        (5, "32", "calendar date"),
        (9, "0", "inconsistent month"),
        (9, "13", "inconsistent month"),
        (9, "06", "inconsistent month"),
        (9, "NULL", "calendar_month"),
        (9, "5.0", "calendar_month"),
    ],
)
def test_missing_hydrological_components_and_nonblank_calendar_conflicts_fail(position, value, reason):
    source = list(SOURCE)
    source[position] = value
    with pytest.raises(ValueError, match=reason):
        bulk._emit_source_row(tuple(source), "source.csv", 1, [])


@pytest.mark.parametrize("period", [(1991, (7,)), (1992, (6,))])
def test_blank_calendar_month_does_not_replace_published_hydrological_period(period):
    with pytest.raises(ValueError, match="filename publication period"):
        bulk._emit_source_row(SOURCE, "source.csv", 1, [], expected_period=period)
