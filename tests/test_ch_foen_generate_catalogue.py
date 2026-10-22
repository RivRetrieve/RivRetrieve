"""Historical Existenz source snapshots, independent of the official catalogue build.

These approved byte and native-content controls describe retained historical inputs.
Current generator behavior is covered by official tests.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import cast

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.native import read_native_table

FIXTURE_PATH = Path("tests/test_data/switzerland_metadata_locations.json")
NATIVE_PATH = Path("src/rivretrieve/_internal/providers/ch_foen/catalogue/native.parquet")
ATTESTED_DATETIME = datetime(2026, 8, 2, 0, 14, 31, tzinfo=UTC)
ATTESTED_DIGEST = "7471e85de4f4a6d1e0968a9fe35a962c98729a4bb3b244e0991818f3038ce24a"
NATIVE_FRAME_DIGEST = "5ceb95706d653ca3cf18632156cccea54b768712cd2e7d81b32876a11f62426a"
NATIVE_SOURCE_SCHEMA = pl.Schema(
    {
        "payload_key": pl.String,
        "id": pl.Int64,
        "name": pl.String,
        "details.id": pl.String,
        "details.name": pl.String,
        "details.water-body-name": pl.String,
        "details.water-body-type": pl.String,
        "details.chx": pl.Int64,
        "details.chy": pl.Int64,
        "details.lat": pl.Float64,
        "details.lon": pl.Float64,
        "source": pl.String,
        "apiurl": pl.String,
        "opendata": pl.String,
        "license": pl.String,
    }
)

NATIVE_SCHEMA = pl.Schema(
    {
        **NATIVE_SOURCE_SCHEMA,
        "retrieved_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    }
)

CRS_EVIDENCE_PATH = Path("tests/test_data/ch_foen_api_docs.html")
CRS_ABSENCE_TOKENS = (
    "wgs84",
    "wgs 84",
    "wgs-84",
    "epsg",
    "datum",
    "crs",
    "srid",
    "coordinate reference",
    "geodetic",
    "geodät",
    "ellipsoid",
    "etrs",
)


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


@pytest.mark.recorded("tests/test_data/ch_foen_api_docs.html")
def test_publisher_crs_evidence_names_hydro_but_no_reference_system(retained_evidence_root: Path) -> None:
    # The documentation fixture retains source text except the explicitly redacted archive credential.
    capture = (retained_evidence_root / CRS_EVIDENCE_PATH).read_bytes()
    parser = _TextParser()
    parser.feed(capture.decode("utf-8"))
    text = " ".join(" ".join(parser.parts).split()).casefold()

    assert len(capture) == 15_683
    assert hashlib.sha256(capture).hexdigest() == ("b353852a474516acf404c1d8b775cc77c5cf3c97bd3055380fc4534bcba9111c")
    assert text
    assert "hydro" in text
    assert all(token.casefold() not in text for token in CRS_ABSENCE_TOKENS)


def _fixture_response(retained_evidence_root: Path) -> dict[str, object]:
    value = json.loads((retained_evidence_root / FIXTURE_PATH).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast("dict[str, object]", value)


def _expected_native_frame(retained_evidence_root: Path, response: dict[str, object] | None = None) -> pl.DataFrame:
    source = _fixture_response(retained_evidence_root) if response is None else response
    payload_value = source["payload"]
    assert isinstance(payload_value, dict)
    payload = cast("dict[str, object]", payload_value)
    rows = []
    for payload_key, station_value in payload.items():
        assert isinstance(station_value, dict)
        station = cast("dict[str, object]", station_value)
        details_value = station["details"]
        assert isinstance(details_value, dict)
        details = cast("dict[str, object]", details_value)
        rows.append(
            {
                "payload_key": payload_key,
                "id": station["id"],
                "name": station["name"],
                "details.id": str(details["id"]),
                "details.name": details["name"],
                "details.water-body-name": details["water-body-name"],
                "details.water-body-type": details["water-body-type"],
                "details.chx": details["chx"],
                "details.chy": details["chy"],
                "details.lat": details["lat"],
                "details.lon": details["lon"],
                "source": source["source"],
                "apiurl": source["apiurl"],
                "opendata": source["opendata"],
                "license": source["license"],
            }
        )
    return (
        pl.DataFrame(rows, schema=NATIVE_SOURCE_SCHEMA)
        .sort("payload_key")
        .with_columns(
            pl.lit(ATTESTED_DATETIME).cast(pl.Datetime(time_unit="us", time_zone="UTC")).alias("retrieved_at")
        )
    )


def _canonical_native_digest(table: pl.DataFrame) -> str:
    canonical = {
        "columns": table.columns,
        "rows": [
            [value.isoformat().replace("+00:00", "Z") if isinstance(value, date | datetime) else value for value in row]
            for row in table.sort("payload_key").iter_rows()
        ],
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


@pytest.mark.recorded("tests/test_data/switzerland_metadata_locations.json")
def test_swiss_fixture_matches_attested_complete_response(retained_evidence_root: Path) -> None:
    response = _fixture_response(retained_evidence_root)
    canonical = json.dumps(response, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    payload = response["payload"]

    assert isinstance(payload, dict)
    assert len(payload) == 246
    assert hashlib.sha256(canonical).hexdigest() == ATTESTED_DIGEST
    assert set(response) == {"source", "apiurl", "opendata", "license", "payload"}


@pytest.mark.derived(
    "src/rivretrieve/_internal/providers/ch_foen/catalogue/native.parquet",
    "tests/test_data/switzerland_metadata_locations.json",
)
def test_committed_native_table_matches_attested_rematerialization(retained_evidence_root: Path) -> None:
    committed = read_native_table(retained_evidence_root / NATIVE_PATH).data

    assert committed.schema == NATIVE_SCHEMA
    pl_testing.assert_frame_equal(committed, _expected_native_frame(retained_evidence_root), check_exact=True)


@pytest.mark.derived("src/rivretrieve/_internal/providers/ch_foen/catalogue/native.parquet")
def test_committed_native_table_has_pinned_full_content(retained_evidence_root: Path) -> None:
    committed = read_native_table(retained_evidence_root / NATIVE_PATH).data

    assert committed.height == 246
    assert committed.columns == list(NATIVE_SCHEMA)
    assert _canonical_native_digest(committed) == NATIVE_FRAME_DIGEST
