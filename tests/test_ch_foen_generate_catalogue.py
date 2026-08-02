from __future__ import annotations

import copy
import hashlib
import io
import json
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.artifact import packaged_catalogue_artifact_from_components
from rivretrieve._internal.catalogues.native import RetrievedAt, read_native_table
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
    validate_catalogue,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ch_foen import generate_catalogue

FIXTURE_PATH = Path("tests/test_data/switzerland_metadata_locations.json")
NATIVE_PATH = Path("src/rivretrieve/_internal/providers/ch_foen/catalogue/native.parquet")
STATIONS_PATH = NATIVE_PATH.with_name("stations.parquet")
CATALOGUE_DATE = date(2026, 5, 28)
ATTESTED_DATETIME = datetime(2026, 8, 2, 0, 14, 31, tzinfo=UTC)
ATTESTED_RETRIEVED_AT = RetrievedAt(ATTESTED_DATETIME)
ATTESTED_DIGEST = "7471e85de4f4a6d1e0968a9fe35a962c98729a4bb3b244e0991818f3038ce24a"
NATIVE_SCHEMA = pl.Schema(
    {
        **generate_catalogue.NATIVE_SOURCE_SCHEMA,
        "retrieved_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    }
)
BULK_OBSERVATIONS_DESCRIPTION = (
    "true: 366-day window decomposition with stitched N x M station-product requests; partial failures reported "
    "as recoverable issues"
)


def _fixture_response() -> dict[str, object]:
    value = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _expected_native_frame(response: dict[str, object] | None = None) -> pl.DataFrame:
    source = _fixture_response() if response is None else response
    payload = source["payload"]
    assert isinstance(payload, dict)
    rows = []
    for payload_key, station in payload.items():
        assert isinstance(station, dict)
        details = station["details"]
        assert isinstance(details, dict)
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
        pl.DataFrame(rows, schema=generate_catalogue.NATIVE_SOURCE_SCHEMA)
        .sort("payload_key")
        .with_columns(
            pl.lit(ATTESTED_DATETIME).cast(pl.Datetime(time_unit="us", time_zone="UTC")).alias("retrieved_at")
        )
    )


class _FixtureResponse(io.BytesIO):
    status = 200


def test_ch_foen_generator_uses_committed_fixture_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_live_json(url: str) -> object:
        raise AssertionError(f"unexpected live request to {url}")

    monkeypatch.setattr(generate_catalogue, "_read_live_json", fail_live_json)

    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )

    assert catalogue.stations.height == 246


def test_ch_foen_generator_station_count_matches_legacy_fixture() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )

    assert catalogue.stations.height == 246


def test_ch_foen_generator_station_2016_brugg_matches_legacy_fixture() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )

    row = catalogue.stations.filter(pl.col("station_id") == "2016").row(0, named=True)
    assert row["latitude"] == 47.4825
    assert row["longitude"] == 8.1949
    assert row["crs"] == "unknown"


def test_ch_foen_generator_station_2386_matches_attested_live_coordinates() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )

    row = catalogue.stations.filter(pl.col("station_id") == "2386").row(0, named=True)
    assert (row["latitude"], row["longitude"]) == (47.5687, 8.8944)


def test_ch_foen_generator_station_schema_and_crs() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )

    assert catalogue.stations.schema == STATION_CATALOG_SCHEMA.polars_schema
    assert catalogue.stations["crs"].unique().to_list() == ["unknown"]
    validate_catalogue(catalogue.stations, STATION_CATALOG_SCHEMA, on_issue="raise")


def test_ch_foen_generator_artifacts_validate_against_all_catalogue_schemas() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )
    provider_info = pl.DataFrame([catalogue.provider_info], schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema)

    validate_catalogue(provider_info, PROVIDER_INFO_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(catalogue.products, PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(catalogue.stations, STATION_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(catalogue.station_products, STATION_PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    packaged_catalogue_artifact_from_components(
        catalogue.provider_info,
        catalogue.products,
        catalogue.stations,
        catalogue.station_products,
        on_issue="raise",
    )


def test_ch_foen_generator_declares_bulk_observations_description() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )

    assert catalogue.provider_info["bulk_observations"] == BULK_OBSERVATIONS_DESCRIPTION
    assert isinstance(catalogue.provider_info["bulk_observations"], str)


def test_ch_foen_generator_rejects_unknown_variable_code() -> None:
    unknown = (
        generate_catalogue.ProductDefinition(
            legacy_variable="UNKNOWN_VARIABLE",
            product_id="discharge_daily_mean",
            observed_property="discharge",
            frequency="daily",
            statistic="mean",
            period_type="interval",
            period_anchor="provider_defined",
            unit="m3/s",
            parameters=("flow",),
            preferred_parameter="flow",
            fallback_parameter=None,
            aggregate_daily=True,
            notes=None,
        ),
    )

    with pytest.raises(FatalContractError, match="unknown"):
        generate_catalogue.build_products(unknown)


def test_ch_foen_generator_rejects_corrupt_fixture(tmp_path: Path) -> None:
    corrupt_fixture = tmp_path / "corrupt.json"
    response = _fixture_response()
    response["payload"] = []
    corrupt_fixture.write_text(json.dumps(response), encoding="utf-8")

    with pytest.raises(FatalContractError, match="payload"):
        generate_catalogue.generate_catalogue_from_fixture(corrupt_fixture)


def test_ch_foen_generator_writes_artifacts(tmp_path: Path) -> None:
    output_path = tmp_path / "catalogue"

    result = generate_catalogue.main(
        [
            "--fixture",
            str(FIXTURE_PATH),
            "--out",
            str(output_path),
            "--catalogue-date",
            CATALOGUE_DATE.isoformat(),
        ]
    )

    assert result == 0
    assert (output_path / "provider.json").is_file()
    assert (output_path / "products.parquet").is_file()
    assert (output_path / "stations.parquet").is_file()
    assert (output_path / "station_products.parquet").is_file()

    provider_info = json.loads((output_path / "provider.json").read_text(encoding="utf-8"))
    assert provider_info["bulk_observations"] == BULK_OBSERVATIONS_DESCRIPTION


def test_ch_foen_generator_provider_json_drift_is_limited_to_bulk_observations(tmp_path: Path) -> None:
    output_path = tmp_path / "catalogue"
    original_json = subprocess.check_output(
        [
            "git",
            "show",
            "HEAD:src/rivretrieve/_internal/providers/ch_foen/catalogue/provider.json",
        ],
        text=True,
    )
    original_provider_info = json.loads(original_json)

    result = generate_catalogue.main(
        [
            "--fixture",
            str(FIXTURE_PATH),
            "--out",
            str(output_path),
            "--catalogue-date",
            CATALOGUE_DATE.isoformat(),
        ]
    )

    assert result == 0
    generated_provider_info = json.loads((output_path / "provider.json").read_text(encoding="utf-8"))
    changed_keys = {
        key for key in original_provider_info if original_provider_info[key] != generated_provider_info[key]
    }
    assert changed_keys <= {"bulk_observations"}


def test_committed_stations_match_fixture_regeneration() -> None:
    regenerated = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    ).stations

    pl_testing.assert_frame_equal(pl.read_parquet(STATIONS_PATH), regenerated, check_exact=True)


def test_swiss_fixture_matches_attested_complete_response() -> None:
    response = _fixture_response()
    canonical = json.dumps(
        response,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    payload = response["payload"]

    assert isinstance(payload, dict)
    assert len(payload) == 246
    assert hashlib.sha256(canonical).hexdigest() == ATTESTED_DIGEST
    assert set(response) == {"source", "apiurl", "opendata", "license", "payload"}


def test_refresh_native_table_has_exact_ordered_schema_and_preserves_source() -> None:
    outcome = generate_catalogue.refresh_native_table(
        _fixture_response(),
        retrieved_at=ATTESTED_RETRIEVED_AT,
    )

    assert outcome.value.data.schema == NATIVE_SCHEMA
    assert outcome.issues == ()
    pl_testing.assert_frame_equal(outcome.value.data, _expected_native_frame(), check_exact=True)


def test_refresh_native_table_normalizes_only_integer_details_id() -> None:
    response = _fixture_response()
    payload = response["payload"]
    assert isinstance(payload, dict)
    integer_detail_ids = [
        payload_key
        for payload_key, station in payload.items()
        if isinstance(station, dict) and isinstance(station["details"], dict) and type(station["details"]["id"]) is int
    ]

    outcome = generate_catalogue.refresh_native_table(
        response,
        retrieved_at=ATTESTED_RETRIEVED_AT,
    )

    assert integer_detail_ids == ["2071"]
    assert payload["2071"]["details"]["id"] == 2071
    assert outcome.value.data.schema["details.id"] == pl.String
    assert outcome.value.data.filter(pl.col("payload_key") == "2071").select("details.id").item() == "2071"


def test_refresh_native_table_stamps_all_rows_with_attested_retrieval_instant() -> None:
    table = generate_catalogue.refresh_native_table(
        _fixture_response(),
        retrieved_at=ATTESTED_RETRIEVED_AT,
    ).value.data

    assert table.height == 246
    assert table["retrieved_at"].n_unique() == 1
    assert table["retrieved_at"].item(0) == ATTESTED_DATETIME


def test_refresh_native_table_from_fixture_is_network_free(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_live_json(url: str) -> object:
        raise AssertionError(f"unexpected live request to {url}")

    monkeypatch.setattr(generate_catalogue, "_read_live_json", fail_live_json)

    outcome = generate_catalogue.refresh_native_table_from_fixture(
        FIXTURE_PATH,
        retrieved_at=ATTESTED_RETRIEVED_AT,
    )

    pl_testing.assert_frame_equal(outcome.value.data, _expected_native_frame(), check_exact=True)


def test_refresh_native_table_from_live_exercises_transport_seam_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_bytes = FIXTURE_PATH.read_bytes()
    calls: list[tuple[str, int]] = []

    def fake_urlopen(url: str, *, timeout: int) -> _FixtureResponse:
        calls.append((url, timeout))
        return _FixtureResponse(fixture_bytes)

    monkeypatch.setattr(generate_catalogue.urllib.request, "urlopen", fake_urlopen)

    outcome = generate_catalogue.refresh_native_table_from_live(retrieved_at=ATTESTED_RETRIEVED_AT)

    assert calls == [(generate_catalogue.SOURCE_URL, 30)]
    pl_testing.assert_frame_equal(outcome.value.data, _expected_native_frame(), check_exact=True)


def test_live_refresh_rejects_implausibly_small_station_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _fixture_response()
    payload = response["payload"]
    assert isinstance(payload, dict)
    response["payload"] = dict(list(payload.items())[:199])
    monkeypatch.setattr(generate_catalogue, "_read_live_json", lambda url: response)

    with pytest.raises(FatalContractError, match="fewer than 200 stations"):
        generate_catalogue.refresh_native_table_from_live(retrieved_at=ATTESTED_RETRIEVED_AT)


def test_fixture_refresh_has_no_exact_station_count_invariant(tmp_path: Path) -> None:
    response = _fixture_response()
    payload = response["payload"]
    assert isinstance(payload, dict)
    response["payload"] = dict(list(payload.items())[:1])
    fixture_path = tmp_path / "one-station.json"
    fixture_path.write_text(json.dumps(response), encoding="utf-8")

    outcome = generate_catalogue.refresh_native_table_from_fixture(
        fixture_path,
        retrieved_at=ATTESTED_RETRIEVED_AT,
    )

    assert outcome.value.data.height == 1


@pytest.mark.parametrize(
    ("scope", "field"),
    [
        *(("envelope", field) for field in ("source", "apiurl", "opendata", "license")),
        *(("station", field) for field in ("id", "name", "details")),
        *(
            ("details", field)
            for field in (
                "id",
                "name",
                "water-body-name",
                "water-body-type",
                "chx",
                "chy",
                "lat",
                "lon",
            )
        ),
    ],
)
def test_refresh_native_table_rejects_each_absent_required_field(
    scope: str,
    field: str,
) -> None:
    response = copy.deepcopy(_fixture_response())
    payload = response["payload"]
    assert isinstance(payload, dict)
    station = payload["2004"]
    assert isinstance(station, dict)
    details = station["details"]
    assert isinstance(details, dict)
    target = response if scope == "envelope" else station if scope == "station" else details
    target.pop(field)

    with pytest.raises(FatalContractError, match=field):
        generate_catalogue.refresh_native_table(
            response,
            retrieved_at=ATTESTED_RETRIEVED_AT,
        )


def test_canonical_station_generation_rejects_absent_details_id() -> None:
    response = copy.deepcopy(_fixture_response())
    payload = response["payload"]
    assert isinstance(payload, dict)
    station = payload["2004"]
    assert isinstance(station, dict)
    details = station["details"]
    assert isinstance(details, dict)
    details.pop("id")

    with pytest.raises(FatalContractError, match="details.*id"):
        generate_catalogue.generate_catalogue(response, catalogue_date=CATALOGUE_DATE)


@pytest.mark.parametrize(
    ("scope", "field"),
    [
        ("station", "id"),
        ("details", "chx"),
        ("details", "chy"),
        ("details", "lat"),
        ("details", "lon"),
    ],
)
def test_refresh_native_table_rejects_boolean_numeric_fields(scope: str, field: str) -> None:
    response = copy.deepcopy(_fixture_response())
    payload = response["payload"]
    assert isinstance(payload, dict)
    station = payload["2004"]
    assert isinstance(station, dict)
    details = station["details"]
    assert isinstance(details, dict)
    target = station if scope == "station" else details
    target[field] = True

    with pytest.raises(FatalContractError, match=field):
        generate_catalogue.refresh_native_table(
            response,
            retrieved_at=ATTESTED_RETRIEVED_AT,
        )


def test_native_output_cli_writes_expected_table(tmp_path: Path) -> None:
    output_path = tmp_path / "native.parquet"

    result = generate_catalogue.main(
        [
            "--fixture",
            str(FIXTURE_PATH),
            "--native-out",
            str(output_path),
            "--retrieved-at",
            "2026-08-02T00:14:31Z",
        ]
    )

    assert result == 0
    pl_testing.assert_frame_equal(
        read_native_table(output_path).data,
        _expected_native_frame(),
        check_exact=True,
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["--fixture", str(FIXTURE_PATH), "--native-out", "native.parquet"],
        [
            "--fixture",
            str(FIXTURE_PATH),
            "--native-out",
            "native.parquet",
            "--retrieved-at",
            "2026-08-02T00:14:31Z",
            "--catalogue-date",
            "2026-08-02",
        ],
        [
            "--fixture",
            str(FIXTURE_PATH),
            "--out",
            "catalogue",
            "--retrieved-at",
            "2026-08-02T00:14:31Z",
        ],
    ],
)
def test_cli_rejects_cross_mode_combinations(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        generate_catalogue.main(argv)

    assert exc_info.value.code != 0


def test_committed_native_table_matches_attested_rematerialization() -> None:
    committed = read_native_table(NATIVE_PATH).data

    assert committed.schema == NATIVE_SCHEMA
    pl_testing.assert_frame_equal(committed, _expected_native_frame(), check_exact=True)
