"""Fixture-backed tests for pl_imgw catalogue generation."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.native import read_native_table
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.pl_imgw import generate_catalogue
from rivretrieve._internal.providers.pl_imgw.generate_catalogue import (
    generate_catalogue_from_fixture,
)

_TEST_DATA_DIR = Path(__file__).parent / "test_data"
_METADATA_FIXTURE = _TEST_DATA_DIR / "pl_imgw_metadata.csv"
_RECOVERED_FIXTURE = _TEST_DATA_DIR / "pl_imgw_stations.csv"
_KODY_STACJI_CAPTURE = _TEST_DATA_DIR / "pl_imgw_kody_stacji.csv"
_HYDRO_API_CAPTURE = _TEST_DATA_DIR / "pl_imgw_hydro_api.json"
_APIINFO_CAPTURE = _TEST_DATA_DIR / "pl_imgw_apiinfo.html"
_NATIVE_PATH = Path("src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet")
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


def _recovered_records() -> list[dict[str, str]]:
    with _RECOVERED_FIXTURE.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def _recovered_ids() -> list[str]:
    return [row["gauge_id"] for row in _recovered_records()]


def _write_roster(path: Path, ids: list[str], *, columns: int = 4) -> None:
    with path.open("w", encoding="cp1250", newline="") as file:
        writer = csv.writer(file, delimiter=",", quoting=csv.QUOTE_ALL)
        for station_id in ids:
            row = [f" {station_id}", "CHAŁUPKI", "RIVER", "00010"]
            writer.writerow(row[:columns])


def _refresh(tmp_path: Path):
    roster = tmp_path / "lista_stacji_hydro.csv"
    _write_roster(roster, _recovered_ids())
    return generate_catalogue.refresh_native_table_from_files(
        _RECOVERED_FIXTURE,
        roster,
        roster_retrieved_at=generate_catalogue.parse_roster_retrieved_at(_ROSTER_INSTANT),
        retrieved_at=generate_catalogue.parse_recovered_retrieved_at(_RECOVERED_INSTANT),
    )


def _expected_native_frame() -> pl.DataFrame:
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
        for row in _recovered_records()
    ]
    instant = datetime(2025, 10, 10, 18, 46, 34, tzinfo=UTC)
    return (
        pl.DataFrame(rows, schema=generate_catalogue.NATIVE_SOURCE_SCHEMA)
        .sort("gauge_id")
        .with_columns(pl.lit(instant).cast(pl.Datetime(time_unit="us", time_zone="UTC")).alias("retrieved_at"))
    )


def _assert_capture(path: Path) -> bytes:
    expected_size, expected_digest = _EVIDENCE[path]
    raw = path.read_bytes()
    assert len(raw) == expected_size
    assert hashlib.sha256(raw).hexdigest() == expected_digest
    return raw


def _publisher_coordinate_sets() -> tuple[set[str], dict[str, tuple[float, float]], set[str], set[str]]:
    csv_text = _assert_capture(_KODY_STACJI_CAPTURE).decode("utf-8", errors="strict")
    csv_rows = list(csv.DictReader(csv_text.splitlines(), delimiter=";"))
    csv_coordinates: dict[str, tuple[float, float]] = {}
    for row in csv_rows:
        latitude = _dms_to_degrees(row["Szerokość geograficzna"])
        longitude = _dms_to_degrees(row["Długość geograficzna"])
        csv_coordinates[row["Kod 9-znakowy"]] = (latitude, longitude)

    api_rows = json.loads(_assert_capture(_HYDRO_API_CAPTURE).decode("utf-8"))
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


def test_generate_catalogue_station_count_fixture() -> None:
    """Fixture has 3 stations with valid coordinates."""
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.stations.height == 3


def test_generate_catalogue_product_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.products.height == 3


def test_generate_catalogue_station_products_cross() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.station_products.height == 3 * 3


def test_generate_catalogue_station_fields() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == _STATION_ID)
    assert row.height == 1
    assert row["crs"][0] == "unknown"
    assert row["latitude"][0] == pytest.approx(51.5252, abs=1e-3)
    assert row["longitude"][0] == pytest.approx(14.8218, abs=1e-3)


def test_generate_catalogue_product_ids() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    ids = set(cat.products["product_id"].to_list())
    assert ids == {"discharge_daily_mean", "stage_daily_mean", "water_temperature_daily_mean"}


def test_generate_catalogue_all_availability_unknown() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.station_products["availability"].cast(pl.Utf8).to_list() == ["unknown"] * 9


def test_metadata_fixture_is_exact_recovered_subset() -> None:
    raw = _METADATA_FIXTURE.read_bytes()
    assert len(raw) == 321
    assert hashlib.sha256(raw).hexdigest() == "cdfafb36adaf894335f9d659f22b48ea32134921fffd3b575dca9a9c19a9f108"

    with _METADATA_FIXTURE.open(encoding="utf-8", newline="") as file:
        subset_records = list(csv.reader(file))
    with _RECOVERED_FIXTURE.open(encoding="utf-8", newline="") as file:
        recovered_records = list(csv.reader(file))
    selected_ids = {"149180020", "151140030", "153190040"}
    expected = [recovered_records[0], *[row for row in recovered_records[1:] if row[0] in selected_ids]]
    assert subset_records == expected


def test_committed_publisher_evidence_raw_bytes_are_attested() -> None:
    for path in _EVIDENCE:
        _assert_capture(path)


def test_full_recovered_refresh_preserves_exact_source_data(tmp_path: Path) -> None:
    outcome = _refresh(tmp_path)
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
    pl_testing.assert_frame_equal(frame, _expected_native_frame(), check_exact=True)


def test_absent_recovered_input_fails_loudly(tmp_path: Path) -> None:
    missing = tmp_path / "missing.csv"
    roster = tmp_path / "roster.csv"
    _write_roster(roster, _recovered_ids())
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.refresh_native_table_from_files(
            missing,
            roster,
            roster_retrieved_at=generate_catalogue.parse_roster_retrieved_at(_ROSTER_INSTANT),
            retrieved_at=generate_catalogue.parse_recovered_retrieved_at(_RECOVERED_INSTANT),
        )
    assert str(exc_info.value) == f"pl_imgw recovered input not found: {missing}"


def test_malformed_recovered_header_fails_loudly(tmp_path: Path) -> None:
    recovered = tmp_path / "recovered.csv"
    recovered.write_text("wrong,header\n1,2\n", encoding="utf-8")
    roster = tmp_path / "roster.csv"
    _write_roster(roster, _recovered_ids())
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


def test_malformed_recovered_value_fails_loudly(tmp_path: Path) -> None:
    recovered = tmp_path / "recovered.csv"
    rows = _RECOVERED_FIXTURE.read_text(encoding="utf-8").splitlines()
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


def test_absent_roster_input_fails_loudly(tmp_path: Path) -> None:
    missing = tmp_path / "missing.csv"
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.refresh_native_table_from_files(
            _RECOVERED_FIXTURE,
            missing,
            roster_retrieved_at=generate_catalogue.parse_roster_retrieved_at(_ROSTER_INSTANT),
            retrieved_at=generate_catalogue.parse_recovered_retrieved_at(_RECOVERED_INSTANT),
        )
    assert str(exc_info.value) == f"pl_imgw roster input not found: {missing}"


def test_invalid_cp1250_roster_fails_loudly(tmp_path: Path) -> None:
    roster = tmp_path / "roster.csv"
    roster.write_bytes(b"\x81")
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.refresh_native_table_from_files(
            _RECOVERED_FIXTURE,
            roster,
            roster_retrieved_at=generate_catalogue.parse_roster_retrieved_at(_ROSTER_INSTANT),
            retrieved_at=generate_catalogue.parse_recovered_retrieved_at(_RECOVERED_INSTANT),
        )
    assert str(exc_info.value) == f"pl_imgw roster encoding invalid: expected=cp1250; path={roster}"


def test_invalid_roster_shape_fails_loudly(tmp_path: Path) -> None:
    roster = tmp_path / "roster.csv"
    _write_roster(roster, _recovered_ids(), columns=3)
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.refresh_native_table_from_files(
            _RECOVERED_FIXTURE,
            roster,
            roster_retrieved_at=generate_catalogue.parse_roster_retrieved_at(_ROSTER_INSTANT),
            retrieved_at=generate_catalogue.parse_recovered_retrieved_at(_RECOVERED_INSTANT),
        )
    assert str(exc_info.value) == "pl_imgw roster row invalid: row=1; expected_columns=4; actual_columns=3"


def test_incomplete_roster_fails_loudly(tmp_path: Path) -> None:
    roster = tmp_path / "roster.csv"
    _write_roster(roster, _recovered_ids()[:1300])
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.refresh_native_table_from_files(
            _RECOVERED_FIXTURE,
            roster,
            roster_retrieved_at=generate_catalogue.parse_roster_retrieved_at(_ROSTER_INSTANT),
            retrieved_at=generate_catalogue.parse_recovered_retrieved_at(_RECOVERED_INSTANT),
        )
    assert str(exc_info.value) == "pl_imgw roster row count invalid: expected=1301; actual=1300"


def test_duplicate_roster_identifiers_fail_loudly(tmp_path: Path) -> None:
    roster = tmp_path / "roster.csv"
    ids = _recovered_ids()
    ids[-1] = ids[0]
    _write_roster(roster, ids)
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.refresh_native_table_from_files(
            _RECOVERED_FIXTURE,
            roster,
            roster_retrieved_at=generate_catalogue.parse_roster_retrieved_at(_ROSTER_INSTANT),
            retrieved_at=generate_catalogue.parse_recovered_retrieved_at(_RECOVERED_INSTANT),
        )
    assert str(exc_info.value) == f"pl_imgw roster identifiers duplicated: ['{ids[0]}']"


def test_complete_roster_identifier_mismatch_is_fatal_and_silent(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    roster = tmp_path / "roster.csv"
    ids = _recovered_ids()
    ids[ids.index("149180010")] = "999999999"
    _write_roster(roster, ids)
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.refresh_native_table_from_files(
            _RECOVERED_FIXTURE,
            roster,
            roster_retrieved_at=generate_catalogue.parse_roster_retrieved_at(_ROSTER_INSTANT),
            retrieved_at=generate_catalogue.parse_recovered_retrieved_at(_RECOVERED_INSTANT),
        )
    assert str(exc_info.value) == (
        "pl_imgw roster identifier mismatch: recovered-only=['149180010']; roster-only=['999999999']"
    )
    assert capsys.readouterr() == ("", "")


def test_missing_roster_retrieved_at_fails_loudly(tmp_path: Path) -> None:
    roster = tmp_path / "roster.csv"
    _write_roster(roster, _recovered_ids())
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.main(
            [
                "--fixture",
                str(_RECOVERED_FIXTURE),
                "--roster",
                str(roster),
                "--retrieved-at",
                _RECOVERED_INSTANT,
                "--native-out",
                str(tmp_path / "native.parquet"),
            ]
        )
    assert str(exc_info.value) == "pl_imgw --roster-retrieved-at is required for native refresh"


def test_malformed_roster_retrieved_at_fails_loudly(tmp_path: Path) -> None:
    roster = tmp_path / "roster.csv"
    _write_roster(roster, _recovered_ids())
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.main(
            [
                "--fixture",
                str(_RECOVERED_FIXTURE),
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


def test_malformed_recovered_retrieved_at_fails_loudly(tmp_path: Path) -> None:
    roster = tmp_path / "roster.csv"
    _write_roster(roster, _recovered_ids())
    with pytest.raises(FatalContractError) as exc_info:
        generate_catalogue.main(
            [
                "--fixture",
                str(_RECOVERED_FIXTURE),
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


def test_committed_native_frame_is_exact_recovered_projection() -> None:
    native = read_native_table(_NATIVE_PATH).data
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
    pl_testing.assert_frame_equal(native, _expected_native_frame(), check_exact=True)
    assert generate_catalogue.native_table_content_sha256(read_native_table(_NATIVE_PATH)) == _NATIVE_DIGEST


def test_recovered_coordinate_audit() -> None:
    frame = _expected_native_frame()
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


def test_publisher_route_partition_and_coordinate_agreement() -> None:
    csv_ids, csv_coordinates, api_ids, usable_api_ids = _publisher_coordinate_sets()
    recovered = {row["gauge_id"]: row for row in _recovered_records()}
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
