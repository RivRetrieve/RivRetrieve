"""Official ECCC evidence fixes HYDAT NO_DAYS without relabelling CSV as compiler input."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from rivretrieve._internal.recordings import ReplayTransport, UnmatchedRequestError, read_recording
from rivretrieve._internal.transport import TransportRequest
from tests.store.test_ca_eccc_streaming import _compile_rows, _representative_hydat


@pytest.fixture(scope="module")
def no_days_evidence_root(retained_evidence_root: Path) -> Path:
    return retained_evidence_root / "tests" / "test_data" / "ca_eccc_hydat_no_days"


def _decoded_sparse_rows(tmp_path: Path, evidence_root: Path):
    database = tmp_path / "Hydat.sqlite3"
    _representative_hydat(database)
    witnesses = json.loads((evidence_root / "sqlite_rows_07HF001.json").read_text())
    connection = sqlite3.connect(database)
    connection.execute("DELETE FROM DLY_LEVELS")
    columns = tuple(witnesses[0])
    placeholders = ",".join("?" for _ in columns)
    connection.executemany(
        f"INSERT INTO DLY_LEVELS ({','.join(columns)}) VALUES ({placeholders})",
        ([row[column] for column in columns] for row in witnesses),
    )
    connection.commit()
    connection.close()
    decoded = _compile_rows(database)
    return decoded.filter(decoded["station_id"] == "07HF001")


@pytest.mark.parametrize("period", ("2013-03", "2014-05"))
def test_official_daily_csv_replay_matches_sparse_hydat_cells(
    tmp_path: Path, period: str, no_days_evidence_root: Path
) -> None:
    recording = read_recording(no_days_evidence_root / f"07HF001_level_{period}.recording.json")
    request = TransportRequest(
        recording.request.method,
        recording.request.url,
        params=recording.request.parameters,
        body=recording.request.body,
    )
    response = ReplayTransport((recording,)).send(request)
    official = tuple(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    all_sparse = _decoded_sparse_rows(tmp_path, no_days_evidence_root)
    decoded = all_sparse.filter(
        (all_sparse["product"] == "stage_daily_mean") & (all_sparse["time"].dt.strftime("%Y-%m") == period)
    )
    published = decoded.filter(decoded["value"].is_not_null()).sort("time")

    assert [row["Date"] for row in official] == [value.strftime("%Y-%m-%d") for value in published["time"]]
    assert [float(row["Value/Valeur"]) for row in official] == pytest.approx(published["value"].to_list(), abs=0.0005)
    paired_symbols = [
        row[f"DLY_LEVELS.LEVEL_SYMBOL{timestamp.day}"]
        for row, timestamp in zip(published.to_dicts(), published["time"], strict=True)
    ]
    assert [row["Symbol/Symbole"] or None for row in official] == paired_symbols
    assert decoded.height == 31

    with pytest.raises(UnmatchedRequestError):
        ReplayTransport((recording,)).send(replace(request, url=request.url + "&unexpected=1"))


def test_retained_definition_and_guideline_are_exact_untouched_publisher_bytes(no_days_evidence_root: Path) -> None:
    expected = {
        "HYDAT_Definition_EN.pdf": (51748, "b3ab1954bf5aeedb026cebe939764fcfbda0266fb267cb6a7315544c9be8e1ee"),
        "WebService_Guidelines_HistoricalDailyData.pdf": (
            288257,
            "5affda6f03271194b04d8b1882eeaecbd629a86fa7ef0be8b5243a9aea4b87d5",
        ),
    }
    for name, (size, digest) in expected.items():
        content = (no_days_evidence_root / name).read_bytes()
        assert len(content) == size
        assert hashlib.sha256(content).hexdigest() == digest


def test_hydat_no_days_evidence_uses_portable_source_identities(no_days_evidence_root: Path) -> None:
    audit = json.loads((no_days_evidence_root / "audit_result.json").read_text())
    assert audit["source_database"] == "Hydat.sqlite3 (sole SQLite member of source_zip_url)"
    assert audit["source_zip"] == ("https://collaboration.cmc.ec.gc.ca/cmc/hydrometrics/www/Hydat_sqlite3_20260717.zip")
    forbidden = (b"/Users/", b"/home/", b"/private/tmp/")
    evidence_files = tuple(
        path for path in no_days_evidence_root.iterdir() if path.suffix in {".json", ".md", ".sql", ".csv"}
    )
    assert evidence_files
    assert all(marker not in path.read_bytes() for path in evidence_files for marker in forbidden)
