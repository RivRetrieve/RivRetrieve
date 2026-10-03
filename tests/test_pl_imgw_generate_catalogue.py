"""Native-table tests for pl_imgw catalogue generation."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.native import (
    NativeTable,
    RetrievedAt,
    read_native_table,
    stamp_native_table,
    write_native_table,
)
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.pl_imgw import generate_catalogue
from tests._catalogue import catalogue_content_without_build_identity, catalogue_recording_paths

_TEST_DATA_DIR = Path("tests/test_data")
_METADATA_FIXTURE = _TEST_DATA_DIR / "pl_imgw_metadata.csv"
_RECOVERED_FIXTURE = _TEST_DATA_DIR / "pl_imgw_stations.csv"
_KODY_STACJI_CAPTURE = _TEST_DATA_DIR / "pl_imgw_kody_stacji.csv"
_HYDRO_API_CAPTURE = _TEST_DATA_DIR / "pl_imgw_hydro_api.json"
_APIINFO_CAPTURE = _TEST_DATA_DIR / "pl_imgw_apiinfo.html"
_NATIVE_PATH = Path("src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet")
_CATALOGUE_PATH = _NATIVE_PATH.parent
_STATION_ID = "151140030"
_RECOVERED_INSTANT = "2025-10-10T18:46:34Z"
_ROSTER_INSTANT = "2026-08-02T19:54:27Z"
_ID_DIGEST = "1afe2782a67081642aabebd40b0b7547e7c3b9231fb26a79b738175860a3fc20"
_NATIVE_DIGEST = "c7fb3582edcc4b66a154d5dac52acd22d2847cd04ed54f5ee94fbf7c8bc6d9ec"
_EVIDENCE = {
    _APIINFO_CAPTURE: (37075, "9b82e28e580d4b22ab6475e129f4dd6d798a0c860d52b9e2f9d2bc3098418d9c"),
    _KODY_STACJI_CAPTURE: (68371, "0ffbaa1cbda89bf9092d728552cce63ae95fd830d16b8e98d5b8de9d4b57aab5"),
    _HYDRO_API_CAPTURE: (554065, "e2b61c8772ca53e8a39a9296362b0ba1b87205afbf156b49691fb6f86679eb1f"),
}


def _recovered_records(retained_evidence_root: Path) -> list[dict[str, str]]:
    with (retained_evidence_root / _RECOVERED_FIXTURE).open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def _recovered_ids(retained_evidence_root: Path) -> list[str]:
    return [row["gauge_id"] for row in _recovered_records(retained_evidence_root)]


def _write_roster(path: Path, ids: list[str], *, columns: int = 4) -> None:
    with path.open("w", encoding="cp1250", newline="") as file:
        writer = csv.writer(file, delimiter=",", quoting=csv.QUOTE_ALL)
        for station_id in ids:
            row = [f" {station_id}", "CHAŁUPKI", "RIVER", "00010"]
            writer.writerow(row[:columns])


def _refresh(retained_evidence_root: Path, tmp_path: Path):
    roster = tmp_path / "lista_stacji_hydro.csv"
    _write_roster(roster, _recovered_ids(retained_evidence_root))
    return generate_catalogue.refresh_native_table_from_files(
        (retained_evidence_root / _RECOVERED_FIXTURE),
        roster,
        roster_retrieved_at=generate_catalogue.parse_roster_retrieved_at(_ROSTER_INSTANT),
        retrieved_at=generate_catalogue.parse_recovered_retrieved_at(_RECOVERED_INSTANT),
    )


def _subset_catalogue(retained_evidence_root: Path, tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    rows = pl.read_csv((retained_evidence_root / _METADATA_FIXTURE), schema=generate_catalogue.NATIVE_SOURCE_SCHEMA)
    native = stamp_native_table(rows, RetrievedAt(datetime(2025, 10, 10, 18, 46, 34, tzinfo=UTC)))
    native_path = tmp_path / "native.parquet"
    write_native_table(native, native_path)
    from rivretrieve._internal.providers.pl_imgw.origins import STATION_CATALOGUE_ORIGINS

    return generate_catalogue.build_catalogue(read_native_table(native_path), STATION_CATALOGUE_ORIGINS)


def _expected_native_frame(retained_evidence_root: Path) -> pl.DataFrame:
    rows = [
        {
            "gauge_id": row["gauge_id"],
            "gauge_name": row["gauge_name"],
            "river": row["river"],
            "area": float(row["area"]),
            "gauge_altitude": row["gauge_altitude"],
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
        }
        for row in _recovered_records(retained_evidence_root)
    ]
    instant = datetime(2025, 10, 10, 18, 46, 34, tzinfo=UTC)
    return (
        pl.DataFrame(rows, schema=generate_catalogue.NATIVE_SOURCE_SCHEMA)
        .sort("gauge_id")
        .with_columns(pl.lit(instant).cast(pl.Datetime(time_unit="us", time_zone="UTC")).alias("retrieved_at"))
    )


def _assert_capture(retained_evidence_root: Path, path: Path) -> bytes:
    expected_size, expected_digest = _EVIDENCE[path]
    raw = (retained_evidence_root / path).read_bytes()
    assert len(raw) == expected_size
    assert hashlib.sha256(raw).hexdigest() == expected_digest
    return raw


def _publisher_coordinate_sets(
    retained_evidence_root: Path,
) -> tuple[set[str], dict[str, tuple[float, float]], set[str], set[str]]:
    csv_text = _assert_capture(retained_evidence_root, _KODY_STACJI_CAPTURE).decode("utf-8", errors="strict")
    csv_rows = list(csv.DictReader(csv_text.splitlines(), delimiter=";"))
    csv_coordinates: dict[str, tuple[float, float]] = {}
    for row in csv_rows:
        latitude = _dms_to_degrees(row["Szerokość geograficzna"])
        longitude = _dms_to_degrees(row["Długość geograficzna"])
        csv_coordinates[row["Kod 9-znakowy"]] = (latitude, longitude)

    api_rows = json.loads(_assert_capture(retained_evidence_root, _HYDRO_API_CAPTURE).decode("utf-8"))
    api_ids = {row["id_stacji"] for row in api_rows}
    usable_api_ids = {
        row["id_stacji"]
        for row in api_rows
        if _usable_coordinate(row.get("lat")) and _usable_coordinate(row.get("lon"))
    }
    return set(csv_coordinates), csv_coordinates, api_ids, usable_api_ids


def _usable_coordinate(value: object) -> bool:
    if value is None:
        return False
    try:
        return float(str(value)) != 0.0
    except ValueError:
        return False


def _dms_to_degrees(value: str) -> float:
    degrees, minutes, seconds = (int(part) for part in value.split())
    return degrees + minutes / 60 + seconds / 3600


def _canonical_value(value: object) -> object:
    return value.isoformat() if isinstance(value, date | datetime) else value


def _frame_content_sha256(frame: pl.DataFrame) -> str:
    payload = {
        "columns": frame.columns,
        "rows": [[_canonical_value(value) for value in row] for row in frame.iter_rows()],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _expected_stations(native: NativeTable) -> pl.DataFrame:
    return (
        native.data.select(
            pl.lit("pl_imgw").alias("provider_id"),
            pl.col("gauge_id").alias("station_id"),
            pl.col("latitude").cast(pl.Float64),
            pl.col("longitude").cast(pl.Float64),
            pl.lit("unknown").alias("crs"),
        )
        .select(STATION_CATALOG_SCHEMA.polars_schema.names())
        .sort("station_id")
    )


def _expected_products() -> pl.DataFrame:
    rows = []
    for definition in generate_catalogue.PRODUCT_DEFINITIONS:
        rows.append(
            {
                "provider_id": "pl_imgw",
                "product_id": definition.product_id,
                "observed_property": definition.observed_property,
                "frequency": definition.frequency,
                "statistic": definition.statistic,
                "period_type": definition.period_type,
                "period_anchor": definition.period_anchor,
                "unit": definition.canonical_unit,
                "native_id": definition.native_column,
            }
        )
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def _expected_station_products(native: NativeTable) -> pl.DataFrame:
    rows = []
    for station_id in native.data["gauge_id"].sort().to_list():
        for definition in generate_catalogue.PRODUCT_DEFINITIONS:
            rows.append(
                {
                    "provider_id": "pl_imgw",
                    "station_id": station_id,
                    "product_id": definition.product_id,
                    "availability": "unknown",
                    "availability_reason": generate_catalogue.AVAILABILITY_REASON,
                    "published_record_start_date": None,
                    "published_record_end_date": None,
                    "last_catalogue_check": date(2025, 10, 10),
                }
            )
    return pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).with_columns(
        pl.col("availability").cast(generate_catalogue.AvailabilityDtype)
    )


def _weak_native(*, second_id: object = "151140030", latitude: object = 51.0, longitude: object = 19.0) -> NativeTable:
    instant = datetime(2025, 10, 10, 18, 46, 34, tzinfo=UTC)
    return NativeTable(
        pl.DataFrame(
            {
                "gauge_id": ["151140030", second_id],
                "gauge_name": ["first", "second"],
                "river": ["river", "river"],
                "area": [1.0, 2.0],
                "gauge_altitude": ["1", "2"],
                "latitude": [51.0, latitude],
                "longitude": [19.0, longitude],
                "retrieved_at": [instant, instant],
            },
            strict=False,
        ).with_columns(pl.col("retrieved_at").cast(pl.Datetime("us", "UTC")))
    )


@pytest.mark.derived("tests/test_data/pl_imgw_metadata.csv")
def test_generate_catalogue_station_count_fixture(retained_evidence_root: Path, tmp_path: Path) -> None:
    """Fixture has 3 stations with valid coordinates."""
    cat = _subset_catalogue(retained_evidence_root, tmp_path)
    assert cat.stations.height == 3


@pytest.mark.derived("tests/test_data/pl_imgw_metadata.csv")
def test_generate_catalogue_product_count(retained_evidence_root: Path, tmp_path: Path) -> None:
    cat = _subset_catalogue(retained_evidence_root, tmp_path)
    assert cat.products.height == 3


@pytest.mark.derived("tests/test_data/pl_imgw_metadata.csv")
def test_generate_catalogue_station_products_cross(retained_evidence_root: Path, tmp_path: Path) -> None:
    cat = _subset_catalogue(retained_evidence_root, tmp_path)
    assert cat.station_products.height == 3 * 3


@pytest.mark.derived("tests/test_data/pl_imgw_metadata.csv")
def test_generate_catalogue_station_fields(retained_evidence_root: Path, tmp_path: Path) -> None:
    cat = _subset_catalogue(retained_evidence_root, tmp_path)
    row = cat.stations.filter(pl.col("station_id") == _STATION_ID)
    assert row.height == 1
    assert row["crs"][0] == "unknown"
    assert row["latitude"][0] == pytest.approx(51.5252, abs=1e-3)
    assert row["longitude"][0] == pytest.approx(14.8218, abs=1e-3)


@pytest.mark.derived("tests/test_data/pl_imgw_metadata.csv")
def test_generate_catalogue_product_ids(retained_evidence_root: Path, tmp_path: Path) -> None:
    cat = _subset_catalogue(retained_evidence_root, tmp_path)
    ids = set(cat.products["product_id"].to_list())
    assert ids == {"discharge_daily", "stage_daily", "water_temperature_daily"}


@pytest.mark.derived("tests/test_data/pl_imgw_metadata.csv")
def test_generate_catalogue_all_availability_unknown(retained_evidence_root: Path, tmp_path: Path) -> None:
    cat = _subset_catalogue(retained_evidence_root, tmp_path)
    assert cat.station_products["availability"].cast(pl.Utf8).to_list() == ["unknown"] * 9


@pytest.mark.derived("tests/test_data/pl_imgw_metadata.csv", "tests/test_data/pl_imgw_stations.csv")
def test_metadata_fixture_is_exact_recovered_subset(retained_evidence_root: Path) -> None:
    raw = (retained_evidence_root / _METADATA_FIXTURE).read_bytes()
    assert len(raw) == 321
    assert hashlib.sha256(raw).hexdigest() == "cdfafb36adaf894335f9d659f22b48ea32134921fffd3b575dca9a9c19a9f108"

    with (retained_evidence_root / _METADATA_FIXTURE).open(encoding="utf-8", newline="") as file:
        subset_records = list(csv.reader(file))
    with (retained_evidence_root / _RECOVERED_FIXTURE).open(encoding="utf-8", newline="") as file:
        recovered_records = list(csv.reader(file))
    selected_ids = {"149180020", "151140030", "153190040"}
    expected = [recovered_records[0], *[row for row in recovered_records[1:] if row[0] in selected_ids]]
    assert subset_records == expected


@pytest.mark.governing(
    "tests/test_data/pl_imgw_apiinfo.html",
    "tests/test_data/pl_imgw_hydro_api.json",
    "tests/test_data/pl_imgw_kody_stacji.csv",
)
def test_committed_publisher_evidence_raw_bytes_are_attested(retained_evidence_root: Path) -> None:
    for path in _EVIDENCE:
        _assert_capture(retained_evidence_root, path)


@pytest.mark.governing(
    "tests/test_data/pl_imgw_apiinfo.html",
    "tests/test_data/pl_imgw_hydro_api.json",
    "tests/test_data/pl_imgw_kody_stacji.csv",
)
def test_publisher_crs_evidence_decoding_and_tokens_are_pinned(retained_evidence_root: Path) -> None:
    api_raw = _assert_capture(retained_evidence_root, _APIINFO_CAPTURE)
    csv_raw = _assert_capture(retained_evidence_root, _KODY_STACJI_CAPTURE)
    api_text = api_raw.decode("utf-8", errors="strict").lower()
    csv_text = csv_raw.decode("utf-8", errors="strict").lower()
    with pytest.raises(UnicodeDecodeError) as api_error:
        api_raw.decode("cp1250", errors="strict")
    assert (api_error.value.object[api_error.value.start], api_error.value.start) == (0x98, 13030)
    with pytest.raises(UnicodeDecodeError) as csv_error:
        csv_raw.decode("cp1250", errors="strict")
    assert (csv_error.value.object[csv_error.value.start], csv_error.value.start) == (0x81, 305)

    shared = ("wgs", "epsg", "datum", "elipsoid", "uklad", "układ", "puwg")
    html_only = ("wspolrz", "współrz", "geodez", "szerokosc", "szerokość", "dlugosc", "długość")
    assert {token: api_text.count(token) for token in (*shared, *html_only)} == dict.fromkeys((*shared, *html_only), 0)
    for decoded in (csv_text, csv_raw.decode("cp1250", errors="replace").lower(), csv_raw.decode("latin-1").lower()):
        assert {token: decoded.count(token) for token in shared} == dict.fromkeys(shared, 0)
    assert csv_text.count("szerokość") == 1
    assert csv_text.count("długość") == 1

    from rivretrieve._internal.providers.pl_imgw.origins import CRS_EVIDENCE_URL

    assert CRS_EVIDENCE_URL == "https://danepubliczne.imgw.pl/pl/apiinfo"
    assert CRS_EVIDENCE_URL.encode() in api_raw
    assert b"/api/data/hydro" in api_raw


@pytest.mark.derived("tests/test_data/pl_imgw_metadata.csv")
def test_native_build_is_network_free_and_repeatable(
    retained_evidence_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: pytest.fail("network touched"))
    first = _subset_catalogue(retained_evidence_root, tmp_path / "one")
    second = _subset_catalogue(retained_evidence_root, tmp_path / "two")
    assert first.provider_info == second.provider_info
    pl_testing.assert_frame_equal(first.products, second.products, check_exact=True)
    pl_testing.assert_frame_equal(first.stations, second.stations, check_exact=True)
    pl_testing.assert_frame_equal(first.station_products, second.station_products, check_exact=True)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (
            None,
            "pl_imgw native station invalid: row=1; field=gauge_id; value=None; expected=exactly nine numeric characters",
        ),
        (
            "",
            "pl_imgw native station invalid: row=1; field=gauge_id; value=''; expected=exactly nine numeric characters",
        ),
        (
            "15114003",
            "pl_imgw native station invalid: row=1; field=gauge_id; value='15114003'; expected=exactly nine numeric characters",
        ),
        (
            "15114003A",
            "pl_imgw native station invalid: row=1; field=gauge_id; value='15114003A'; expected=exactly nine numeric characters",
        ),
    ],
)
def test_invalid_native_identifier_fails_loudly(value: object, message: str) -> None:
    from rivretrieve._internal.providers.pl_imgw.origins import STATION_CATALOGUE_ORIGINS

    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.build_catalogue(_weak_native(second_id=value), STATION_CATALOGUE_ORIGINS)
    assert str(exc_info.value) == message


def test_duplicate_native_identifier_fails_loudly() -> None:
    from rivretrieve._internal.providers.pl_imgw.origins import STATION_CATALOGUE_ORIGINS

    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.build_catalogue(_weak_native(), STATION_CATALOGUE_ORIGINS)
    assert (
        str(exc_info.value) == "pl_imgw native station duplicate: station_id='151140030'; first_row=0; duplicate_row=1"
    )


@pytest.mark.derived("src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet")
def test_build_catalogue_is_gated_on_origins(retained_evidence_root: Path) -> None:
    from rivretrieve._internal.providers.pl_imgw.origins import STATION_CATALOGUE_ORIGINS

    broken = dict(STATION_CATALOGUE_ORIGINS)
    del broken["longitude"]

    with pytest.raises(
        FatalContractError,
        match=r"pl_imgw\.longitude: canonical column has no origin declaration",
    ):
        generate_catalogue.build_catalogue(read_native_table(retained_evidence_root / _NATIVE_PATH), broken)


def test_mixed_retrieval_dates_use_maximum_for_catalogue_date() -> None:
    from rivretrieve._internal.providers.pl_imgw.origins import STATION_CATALOGUE_ORIGINS

    mixed = _weak_native(second_id="151140031").data.with_columns(
        pl.Series(
            "retrieved_at",
            [
                datetime(2025, 10, 9, 12, tzinfo=UTC),
                datetime(2025, 10, 10, 12, tzinfo=UTC),
            ],
            dtype=pl.Datetime(time_unit="us", time_zone="UTC"),
        )
    )

    catalogue = generate_catalogue.build_catalogue(NativeTable(mixed), STATION_CATALOGUE_ORIGINS)

    assert catalogue.provider_info["catalogue_version"] == "2025-10-10"
    assert catalogue.station_products["last_catalogue_check"].unique().to_list() == [date(2025, 10, 10)]


@pytest.mark.parametrize("field", ["latitude", "longitude"])
@pytest.mark.parametrize(("value", "rendered"), [(None, "None"), ("", "''"), ("invalid", "'invalid'")])
def test_invalid_native_coordinate_fails_loudly(field: str, value: object, rendered: str) -> None:
    from rivretrieve._internal.providers.pl_imgw.origins import STATION_CATALOGUE_ORIGINS

    kwargs = {field: value}
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.build_catalogue(_weak_native(**kwargs), STATION_CATALOGUE_ORIGINS)
    assert str(exc_info.value) == (
        f"pl_imgw native station invalid: row=1; station_id='151140030'; field={field}; "
        f"value={rendered}; expected=numeric coordinate"
    )


@pytest.mark.derived("tests/test_data/pl_imgw_stations.csv")
def test_full_recovered_refresh_preserves_exact_source_data(retained_evidence_root: Path, tmp_path: Path) -> None:
    outcome = _refresh(retained_evidence_root, tmp_path)
    frame = outcome.value.data

    assert outcome.issues == ()
    assert frame.schema == pl.Schema(
        {
            **dict(generate_catalogue.NATIVE_SOURCE_SCHEMA),
            "retrieved_at": pl.Datetime(time_unit="us", time_zone="UTC"),
        }
    )
    assert frame.height == 1301
    assert frame["gauge_id"].n_unique() == 1301
    assert frame["gauge_id"].str.len_chars().eq(9).all()
    assert frame["retrieved_at"].unique().to_list() == [datetime(2025, 10, 10, 18, 46, 34, tzinfo=UTC)]
    canonical_ids = json.dumps(sorted(frame["gauge_id"].to_list()), separators=(",", ":")).encode()
    assert hashlib.sha256(canonical_ids).hexdigest() == _ID_DIGEST
    pl_testing.assert_frame_equal(frame, _expected_native_frame(retained_evidence_root), check_exact=True)


@pytest.mark.derived("tests/test_data/pl_imgw_stations.csv")
def test_absent_recovered_input_fails_loudly(retained_evidence_root: Path, tmp_path: Path) -> None:
    missing = tmp_path / "missing.csv"
    roster = tmp_path / "roster.csv"
    _write_roster(roster, _recovered_ids(retained_evidence_root))
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.refresh_native_table_from_files(
            missing,
            roster,
            roster_retrieved_at=generate_catalogue.parse_roster_retrieved_at(_ROSTER_INSTANT),
            retrieved_at=generate_catalogue.parse_recovered_retrieved_at(_RECOVERED_INSTANT),
        )
    assert str(exc_info.value) == f"pl_imgw recovered input not found: {missing}"


@pytest.mark.derived("tests/test_data/pl_imgw_stations.csv")
def test_malformed_recovered_header_fails_loudly(retained_evidence_root: Path, tmp_path: Path) -> None:
    recovered = tmp_path / "recovered.csv"
    recovered.write_text("wrong,header\n1,2\n", encoding="utf-8")
    roster = tmp_path / "roster.csv"
    _write_roster(roster, _recovered_ids(retained_evidence_root))
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.refresh_native_table_from_files(
            recovered,
            roster,
            roster_retrieved_at=generate_catalogue.parse_roster_retrieved_at(_ROSTER_INSTANT),
            retrieved_at=generate_catalogue.parse_recovered_retrieved_at(_RECOVERED_INSTANT),
        )
    assert str(exc_info.value) == (
        "pl_imgw recovered header mismatch: expected=['gauge_id', 'gauge_name', 'river', 'area', "
        "'gauge_altitude', 'latitude', 'longitude']; actual=['wrong', 'header']"
    )


@pytest.mark.derived("tests/test_data/pl_imgw_stations.csv")
def test_malformed_recovered_value_fails_loudly(retained_evidence_root: Path, tmp_path: Path) -> None:
    recovered = tmp_path / "recovered.csv"
    rows = (retained_evidence_root / _RECOVERED_FIXTURE).read_text(encoding="utf-8").splitlines()
    fields = next(csv.reader([rows[1]]))
    fields[3] = "invalid"
    recovered.write_text(f"{rows[0]}\n{','.join(fields)}\n", encoding="utf-8")
    roster = tmp_path / "roster.csv"
    _write_roster(roster, [fields[0]] * 1301)
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.refresh_native_table_from_files(
            recovered,
            roster,
            roster_retrieved_at=generate_catalogue.parse_roster_retrieved_at(_ROSTER_INSTANT),
            retrieved_at=generate_catalogue.parse_recovered_retrieved_at(_RECOVERED_INSTANT),
        )
    assert str(exc_info.value) == "pl_imgw recovered value invalid: row=2; field=area; value='invalid'"


@pytest.mark.derived("tests/test_data/pl_imgw_stations.csv")
def test_absent_roster_input_fails_loudly(retained_evidence_root: Path, tmp_path: Path) -> None:
    missing = tmp_path / "missing.csv"
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.refresh_native_table_from_files(
            (retained_evidence_root / _RECOVERED_FIXTURE),
            missing,
            roster_retrieved_at=generate_catalogue.parse_roster_retrieved_at(_ROSTER_INSTANT),
            retrieved_at=generate_catalogue.parse_recovered_retrieved_at(_RECOVERED_INSTANT),
        )
    assert str(exc_info.value) == f"pl_imgw roster input not found: {missing}"


@pytest.mark.derived("tests/test_data/pl_imgw_stations.csv")
def test_invalid_cp1250_roster_fails_loudly(retained_evidence_root: Path, tmp_path: Path) -> None:
    roster = tmp_path / "roster.csv"
    roster.write_bytes(b"\x81")
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.refresh_native_table_from_files(
            (retained_evidence_root / _RECOVERED_FIXTURE),
            roster,
            roster_retrieved_at=generate_catalogue.parse_roster_retrieved_at(_ROSTER_INSTANT),
            retrieved_at=generate_catalogue.parse_recovered_retrieved_at(_RECOVERED_INSTANT),
        )
    assert str(exc_info.value) == f"pl_imgw roster encoding invalid: expected=cp1250; path={roster}"


@pytest.mark.derived("tests/test_data/pl_imgw_stations.csv")
def test_invalid_roster_shape_fails_loudly(retained_evidence_root: Path, tmp_path: Path) -> None:
    roster = tmp_path / "roster.csv"
    _write_roster(roster, _recovered_ids(retained_evidence_root), columns=3)
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.refresh_native_table_from_files(
            (retained_evidence_root / _RECOVERED_FIXTURE),
            roster,
            roster_retrieved_at=generate_catalogue.parse_roster_retrieved_at(_ROSTER_INSTANT),
            retrieved_at=generate_catalogue.parse_recovered_retrieved_at(_RECOVERED_INSTANT),
        )
    assert str(exc_info.value) == "pl_imgw roster row invalid: row=1; expected_columns=4; actual_columns=3"


@pytest.mark.derived("tests/test_data/pl_imgw_stations.csv")
def test_incomplete_roster_fails_loudly(retained_evidence_root: Path, tmp_path: Path) -> None:
    roster = tmp_path / "roster.csv"
    _write_roster(roster, _recovered_ids(retained_evidence_root)[:1300])
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.refresh_native_table_from_files(
            (retained_evidence_root / _RECOVERED_FIXTURE),
            roster,
            roster_retrieved_at=generate_catalogue.parse_roster_retrieved_at(_ROSTER_INSTANT),
            retrieved_at=generate_catalogue.parse_recovered_retrieved_at(_RECOVERED_INSTANT),
        )
    assert str(exc_info.value) == "pl_imgw roster row count invalid: expected=1301; actual=1300"


@pytest.mark.derived("tests/test_data/pl_imgw_stations.csv")
def test_duplicate_roster_identifiers_fail_loudly(retained_evidence_root: Path, tmp_path: Path) -> None:
    roster = tmp_path / "roster.csv"
    ids = _recovered_ids(retained_evidence_root)
    ids[-1] = ids[0]
    _write_roster(roster, ids)
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.refresh_native_table_from_files(
            (retained_evidence_root / _RECOVERED_FIXTURE),
            roster,
            roster_retrieved_at=generate_catalogue.parse_roster_retrieved_at(_ROSTER_INSTANT),
            retrieved_at=generate_catalogue.parse_recovered_retrieved_at(_RECOVERED_INSTANT),
        )
    assert str(exc_info.value) == f"pl_imgw roster identifiers duplicated: ['{ids[0]}']"


@pytest.mark.derived("tests/test_data/pl_imgw_stations.csv")
def test_complete_roster_identifier_mismatch_is_fatal_and_silent(
    retained_evidence_root: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    roster = tmp_path / "roster.csv"
    ids = _recovered_ids(retained_evidence_root)
    ids[ids.index("149180010")] = "999999999"
    _write_roster(roster, ids)
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.refresh_native_table_from_files(
            (retained_evidence_root / _RECOVERED_FIXTURE),
            roster,
            roster_retrieved_at=generate_catalogue.parse_roster_retrieved_at(_ROSTER_INSTANT),
            retrieved_at=generate_catalogue.parse_recovered_retrieved_at(_RECOVERED_INSTANT),
        )
    assert str(exc_info.value) == (
        "pl_imgw roster identifier mismatch: recovered-only=['149180010']; roster-only=['999999999']"
    )
    assert capsys.readouterr() == ("", "")


@pytest.mark.derived("tests/test_data/pl_imgw_stations.csv")
def test_missing_roster_retrieved_at_fails_loudly(retained_evidence_root: Path, tmp_path: Path) -> None:
    roster = tmp_path / "roster.csv"
    _write_roster(roster, _recovered_ids(retained_evidence_root))
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.main(
            [
                "--fixture",
                str(retained_evidence_root / _RECOVERED_FIXTURE),
                "--roster",
                str(roster),
                "--retrieved-at",
                _RECOVERED_INSTANT,
                "--native-out",
                str(tmp_path / "native.parquet"),
            ]
        )
    assert str(exc_info.value) == "pl_imgw --roster-retrieved-at is required for native refresh"


@pytest.mark.derived("tests/test_data/pl_imgw_stations.csv")
def test_malformed_roster_retrieved_at_fails_loudly(retained_evidence_root: Path, tmp_path: Path) -> None:
    roster = tmp_path / "roster.csv"
    _write_roster(roster, _recovered_ids(retained_evidence_root))
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.main(
            [
                "--fixture",
                str(retained_evidence_root / _RECOVERED_FIXTURE),
                "--roster",
                str(roster),
                "--roster-retrieved-at",
                "not-an-instant",
                "--retrieved-at",
                _RECOVERED_INSTANT,
                "--native-out",
                str(tmp_path / "native.parquet"),
            ]
        )
    assert str(exc_info.value) == (
        "pl_imgw invalid --roster-retrieved-at: 'not-an-instant'; expected RFC 3339 UTC instant"
    )


@pytest.mark.derived("tests/test_data/pl_imgw_stations.csv")
def test_malformed_recovered_retrieved_at_fails_loudly(retained_evidence_root: Path, tmp_path: Path) -> None:
    roster = tmp_path / "roster.csv"
    _write_roster(roster, _recovered_ids(retained_evidence_root))
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.main(
            [
                "--fixture",
                str(retained_evidence_root / _RECOVERED_FIXTURE),
                "--roster",
                str(roster),
                "--roster-retrieved-at",
                _ROSTER_INSTANT,
                "--retrieved-at",
                "not-an-instant",
                "--native-out",
                str(tmp_path / "native.parquet"),
            ]
        )
    assert str(exc_info.value) == ("pl_imgw invalid --retrieved-at: 'not-an-instant'; expected RFC 3339 UTC instant")


def test_incomplete_native_cli_combination_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.main(
            [
                "--retrieved-at",
                _RECOVERED_INSTANT,
                "--native-out",
                str(tmp_path / "native.parquet"),
            ]
        )
    assert str(exc_info.value) == (
        "pl_imgw native refresh requires --fixture, --roster, --roster-retrieved-at, --retrieved-at, "
        "and --native-out together; missing=['--fixture', '--roster', '--roster-retrieved-at']"
    )


@pytest.mark.derived(
    "src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet",
    "tests/test_data/pl_imgw_stations.csv",
)
def test_committed_native_frame_is_exact_recovered_projection(retained_evidence_root: Path) -> None:
    native = read_native_table(retained_evidence_root / _NATIVE_PATH).data
    assert native.schema == pl.Schema(
        {
            "gauge_id": pl.String,
            "gauge_name": pl.String,
            "river": pl.String,
            "area": pl.Float64,
            "gauge_altitude": pl.String,
            "latitude": pl.Float64,
            "longitude": pl.Float64,
            "retrieved_at": pl.Datetime(time_unit="us", time_zone="UTC"),
        }
    )
    assert native.height == 1301
    assert native["gauge_id"].n_unique() == 1301
    pl_testing.assert_frame_equal(native, _expected_native_frame(retained_evidence_root), check_exact=True)
    assert (
        generate_catalogue.native_table_content_sha256(read_native_table(retained_evidence_root / _NATIVE_PATH))
        == _NATIVE_DIGEST
    )


@pytest.mark.derived("tests/test_data/pl_imgw_stations.csv")
def test_recovered_coordinate_audit(retained_evidence_root: Path) -> None:
    frame = _expected_native_frame(retained_evidence_root)
    assert frame["latitude"].null_count() == 0
    assert frame["longitude"].null_count() == 0
    assert frame.filter((pl.col("latitude") == 0) | (pl.col("longitude") == 0)).height == 0
    assert frame.filter(~pl.col("latitude").is_between(49.0, 54.9, closed="both")).height == 0
    assert frame.filter(~pl.col("longitude").is_between(14.1, 24.2, closed="both")).height == 0
    assert (
        frame.filter(
            pl.col("latitude").is_between(14.1, 24.2, closed="both")
            & pl.col("longitude").is_between(49.0, 54.9, closed="both")
        ).height
        == 0
    )
    assert frame.select(["latitude", "longitude"]).is_duplicated().sum() == 0


@pytest.mark.governing(
    "tests/test_data/pl_imgw_apiinfo.html",
    "tests/test_data/pl_imgw_hydro_api.json",
    "tests/test_data/pl_imgw_kody_stacji.csv",
    "tests/test_data/pl_imgw_stations.csv",
)
def test_publisher_route_partition_and_coordinate_agreement(retained_evidence_root: Path) -> None:
    csv_ids, csv_coordinates, api_ids, usable_api_ids = _publisher_coordinate_sets(retained_evidence_root)
    recovered = {row["gauge_id"]: row for row in _recovered_records(retained_evidence_root)}
    recovered_ids = set(recovered)

    assert len(recovered_ids) == 1301
    assert len(csv_ids) == 887
    assert len(api_ids) == 913
    assert len(usable_api_ids) == 881
    assert usable_api_ids <= csv_ids
    assert len(csv_ids & recovered_ids) == 784
    assert len(usable_api_ids & recovered_ids) == 779
    assert (usable_api_ids & recovered_ids) <= (csv_ids & recovered_ids)
    assert api_ids - csv_ids == api_ids - usable_api_ids
    assert len(api_ids - csv_ids) == 32
    assert len((csv_ids | usable_api_ids) & recovered_ids) == 784
    assert len(recovered_ids - (csv_ids | usable_api_ids)) == 517
    assert len(api_ids - recovered_ids) == 106

    overlaps = sorted(csv_ids & recovered_ids)
    exact_pairs = 0
    within_tolerance = 0
    outside: list[str] = []
    differences: dict[str, float] = {}
    tolerance = 1.5 / 3600
    for station_id in overlaps:
        recovered_pair = (
            float(recovered[station_id]["latitude"]),
            float(recovered[station_id]["longitude"]),
        )
        published_pair = csv_coordinates[station_id]
        if recovered_pair == published_pair:
            exact_pairs += 1
        axis_differences = (
            abs(recovered_pair[0] - published_pair[0]),
            abs(recovered_pair[1] - published_pair[1]),
        )
        differences[station_id] = max(axis_differences)
        if all(difference <= tolerance for difference in axis_differences):
            within_tolerance += 1
        else:
            outside.append(station_id)

    worst_station = max(differences, key=differences.__getitem__)
    assert exact_pairs == 0
    assert within_tolerance == 779
    assert len(outside) == 5
    assert worst_station == "154180190"
    assert differences[worst_station] == pytest.approx(0.0053675, abs=1e-7)
    assert differences[worst_station] == pytest.approx(0.0054, abs=5e-5)


@pytest.mark.derived("src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet")
def test_native_build_matches_independent_exact_full_projections(retained_evidence_root: Path) -> None:
    from rivretrieve._internal.providers.pl_imgw.origins import STATION_CATALOGUE_ORIGINS

    native = read_native_table(retained_evidence_root / _NATIVE_PATH)
    actual = generate_catalogue.build_catalogue(native, STATION_CATALOGUE_ORIGINS)
    pl_testing.assert_frame_equal(actual.stations, _expected_stations(native), check_exact=True)
    pl_testing.assert_frame_equal(actual.products, _expected_products(), check_exact=True)
    pl_testing.assert_frame_equal(actual.station_products, _expected_station_products(native), check_exact=True)
    assert actual.provider_info == {
        "provider_id": "pl_imgw",
        "name": "Poland Institute of Meteorology and Water Management (IMGW)",
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": (
            "true: explicit download compiles the publisher's monthly or annual ZIP archives "
            "into a local native observation store; retrieval reads that store without network access"
        ),
        "catalogue_version": "2025-10-10",
        "license": None,
        "citation": None,
    }


@pytest.mark.governing(
    "src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet",
    "tests/test_data/pl_imgw_terms_regulations.html",
)
@pytest.mark.recorded(*catalogue_recording_paths("pl_imgw"))
def test_native_build_without_reverification_input_is_byte_identical_to_committed_artifacts(
    retained_evidence_root: Path, tmp_path: Path, catalogue_build_inputs_path
) -> None:
    from rivretrieve._internal.providers.pl_imgw.origins import build_acquisition_provenance

    build_inputs_path = catalogue_build_inputs_path(build_acquisition_provenance())
    result = generate_catalogue.main(
        [
            "--build-inputs",
            str(build_inputs_path),
            "--native",
            str(retained_evidence_root / _NATIVE_PATH),
            "--out",
            str(tmp_path),
            "--terms-recording",
            str(retained_evidence_root / "tests/test_data/pl_imgw_terms_regulations.html"),
        ]
    )

    assert result == 0
    for artifact_name in (
        "provider.json",
        "products.parquet",
        "stations.parquet",
        "station_products.parquet",
        "provenance.json",
        "provenance_facts.parquet",
        "provenance_acquisitions.parquet",
        "provenance_bindings.parquet",
        "provenance_binding_facts.parquet",
        "provenance_external_inputs.parquet",
        "format.json",
        "source_series.json",
        "series_claims.parquet",
        "station_metadata.parquet",
    ):
        assert catalogue_content_without_build_identity(
            artifact_name, (tmp_path / artifact_name).read_bytes()
        ) == catalogue_content_without_build_identity(artifact_name, (_CATALOGUE_PATH / artifact_name).read_bytes())


def test_committed_canonical_artifacts_have_pinned_complete_content() -> None:
    provider_bytes = (_CATALOGUE_PATH / "provider.json").read_bytes()
    products = pl.read_parquet(_CATALOGUE_PATH / "products.parquet")
    stations = pl.read_parquet(_CATALOGUE_PATH / "stations.parquet")
    station_products = pl.read_parquet(_CATALOGUE_PATH / "station_products.parquet")

    assert products.schema == PRODUCT_CATALOG_SCHEMA.polars_schema
    assert stations.schema == STATION_CATALOG_SCHEMA.polars_schema
    assert station_products.schema == STATION_PRODUCT_CATALOG_SCHEMA.polars_schema
    assert (
        hashlib.sha256(provider_bytes).hexdigest() == "a164bc24e10b79fafb644b6bbcb8b5321de0dfa53a8e128302783f352a3899bc"
    )
    assert _frame_content_sha256(products) == "2d74a514aa12a3e5d1db13b57fdfa2bf3ed94f7833e3add2f65ca53973e6f80e"
    assert _frame_content_sha256(stations) == "738b3a71030b3ef7dfe6763a2780cabae6e00cffd2bad9e1f7b1222238de71f9"
    assert _frame_content_sha256(station_products) == (
        "aa3fce5b14c164cd896b7911aaca206eb7dafa3f0cfb731938e6481aff1eec9e"
    )
