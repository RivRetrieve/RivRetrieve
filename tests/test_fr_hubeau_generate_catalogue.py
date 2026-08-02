from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.native import RetrievedAt, read_native_table
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.fr_hubeau import generate_catalogue as generator
from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import (
    NATIVE_SCHEMA,
    NATIVE_SOURCE_COLUMNS,
    generate_catalogue_from_fixture,
    native_table_content_digest,
    refresh_native_table,
    refresh_native_table_from_fixtures,
)

_TEST_DATA_DIR = Path(__file__).parent / "test_data"
_HYDRO_FIXTURE = _TEST_DATA_DIR / "fr_hubeau_metadata.json"
_TEMP_FIXTURE = _TEST_DATA_DIR / "fr_hubeau_temp_stations.json"
_HYDRO_FULL_FIXTURE = _TEST_DATA_DIR / "fr_hubeau_referentiel_stations_full.json"
_TEMP_FULL_FIXTURE = _TEST_DATA_DIR / "fr_hubeau_temperature_stations_full.json"
_GEOJSON_EVIDENCE = _TEST_DATA_DIR / "fr_hubeau_geojson_crs_evidence.json"
_OPENAPI_EVIDENCE = _TEST_DATA_DIR / "fr_hubeau_openapi_v2.json"
_HYDRO_RETRIEVED_AT = RetrievedAt(datetime(2026, 8, 2, 17, 32, 58, tzinfo=UTC))
_TEMP_RETRIEVED_AT = RetrievedAt(datetime(2026, 8, 2, 17, 33, 34, tzinfo=UTC))
_PINNED_NATIVE_DIGEST = "f5c3d84a4e6674a1aa5e6b951576edf6bcbdf77867ab0e5c3ffe2f09adbf7322"


def _full_payload(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text())
    assert isinstance(value, dict)
    return value


def _sample_payloads() -> tuple[dict[str, object], dict[str, object]]:
    hydro_full = _full_payload(_HYDRO_FULL_FIXTURE)
    temp_full = _full_payload(_TEMP_FULL_FIXTURE)
    hydro_rows = hydro_full["data"]
    temp_rows = temp_full["data"]
    assert isinstance(hydro_rows, list)
    assert isinstance(temp_rows, list)
    return (
        {"count": 2, "data": [dict(hydro_rows[0]), dict(hydro_rows[1])]},
        {"count": 2, "data": [dict(temp_rows[0]), dict(temp_rows[1])]},
    )


def _refresh(hydro: object, temperature: object):
    return refresh_native_table(
        hydro,
        temperature,
        hydro_retrieved_at=_HYDRO_RETRIEVED_AT,
        temperature_retrieved_at=_TEMP_RETRIEVED_AT,
    )


def _assert_issue(result: object, message: str) -> None:
    issues = result.issues
    assert [issue.message for issue in issues] == [message]
    assert all(issue.provider_id == ProviderId("fr_hubeau") for issue in issues)
    assert result.value.data.height == 0


def test_generate_catalogue_station_count() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    # 2 hydro (with valid coords) + 1 temp (with valid coords) = 3
    assert cat.stations.height == 3


def test_generate_catalogue_product_count() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    assert cat.products.height == 6


def test_generate_catalogue_station_products_cross() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    # 2 hydro × 5 products + 1 temp × 1 product = 11
    assert cat.station_products.height == 11


def test_generate_catalogue_hydro_station_fields() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    station = cat.stations.filter(pl.col("station_id") == "O0050010")
    assert station.height == 1
    assert station["crs"][0] == "unknown"


def test_generate_catalogue_temp_station_fields() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    station = cat.stations.filter(pl.col("station_id") == "T123456001")
    assert station.height == 1
    assert station["crs"][0] == "unknown"


def test_generate_catalogue_filters_no_coord_stations() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    station_ids = set(cat.stations["station_id"].to_list())
    assert "K123456001" not in station_ids  # hydro no-coord
    assert "T999999001" not in station_ids  # temp no-coord


def test_generate_catalogue_hydro_station_products() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    hydro_sp = cat.station_products.filter(pl.col("station_id") == "O0050010")
    hydro_products = set(hydro_sp["product_id"].to_list())
    assert hydro_products == {
        "discharge_instantaneous",
        "discharge_daily_mean",
        "discharge_daily_max",
        "stage_instantaneous",
        "stage_daily_max",
    }


def test_generate_catalogue_temp_station_products() -> None:
    cat = generate_catalogue_from_fixture(_HYDRO_FIXTURE, _TEMP_FIXTURE)
    temp_sp = cat.station_products.filter(pl.col("station_id") == "T123456001")
    assert temp_sp["product_id"].to_list() == ["water_temperature_instantaneous"]


@pytest.mark.parametrize("endpoint", ["hydrometry", "temperature"])
def test_native_envelope_must_be_object(endpoint: str) -> None:
    hydro, temperature = _sample_payloads()
    if endpoint == "hydrometry":
        hydro = []
    else:
        temperature = []
    _assert_issue(_refresh(hydro, temperature), f"fr_hubeau {endpoint} response must be an object")


@pytest.mark.parametrize("endpoint", ["hydrometry", "temperature"])
def test_native_data_must_be_list(endpoint: str) -> None:
    hydro, temperature = _sample_payloads()
    target = hydro if endpoint == "hydrometry" else temperature
    target["data"] = {}
    _assert_issue(_refresh(hydro, temperature), f"fr_hubeau {endpoint} response data must be a list")


@pytest.mark.parametrize("endpoint", ["hydrometry", "temperature"])
@pytest.mark.parametrize("invalid_count", [True, "2"])
def test_native_count_must_be_non_boolean_integer(endpoint: str, invalid_count: object) -> None:
    hydro, temperature = _sample_payloads()
    target = hydro if endpoint == "hydrometry" else temperature
    target["count"] = invalid_count
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau {endpoint} response count must be a non-boolean integer",
    )


@pytest.mark.parametrize("endpoint", ["hydrometry", "temperature"])
def test_native_count_must_match_rows(endpoint: str) -> None:
    hydro, temperature = _sample_payloads()
    target = hydro if endpoint == "hydrometry" else temperature
    target["count"] = 3
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau {endpoint} response count 3 does not match 2 rows",
    )


@pytest.mark.parametrize("endpoint", ["hydrometry", "temperature"])
def test_native_row_must_be_object(endpoint: str) -> None:
    hydro, temperature = _sample_payloads()
    target = hydro if endpoint == "hydrometry" else temperature
    target["data"][0] = []
    _assert_issue(_refresh(hydro, temperature), f"fr_hubeau {endpoint} station 0 must be an object")


@pytest.mark.parametrize("endpoint", ["hydrometry", "temperature"])
def test_native_row_requires_complete_endpoint_key_set(endpoint: str) -> None:
    hydro, temperature = _sample_payloads()
    target = hydro if endpoint == "hydrometry" else temperature
    row = target["data"][0]
    station_id = row["code_station"]
    del row[next(key for key in row if key != "code_station")]
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau {endpoint} station {station_id} is missing required source fields",
    )


@pytest.mark.parametrize("endpoint", ["hydrometry", "temperature"])
def test_native_scalar_value_must_inhabit_schema(endpoint: str) -> None:
    hydro, temperature = _sample_payloads()
    target = hydro if endpoint == "hydrometry" else temperature
    row = target["data"][0]
    station_id = row["code_station"]
    row["libelle_station"] = {"invalid": "scalar"}
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau {endpoint} station {station_id} has source values outside the native schema",
    )


def test_native_list_value_must_inhabit_schema() -> None:
    hydro, temperature = _sample_payloads()
    station_id = hydro["data"][0]["code_station"]
    hydro["data"][0]["code_sandre_reseau_station"] = ["valid", 3]
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau hydrometry station {station_id} has source values outside the native schema",
    )


def test_native_float_value_must_be_finite() -> None:
    for invalid_value in (float("nan"), float("inf")):
        hydro, temperature = _sample_payloads()
        station_id = hydro["data"][0]["code_station"]
        hydro["data"][0]["longitude_station"] = invalid_value
        _assert_issue(
            _refresh(hydro, temperature),
            f"fr_hubeau hydrometry station {station_id} has source values outside the native schema",
        )


def test_native_float_value_must_not_be_boolean() -> None:
    hydro, temperature = _sample_payloads()
    station_id = hydro["data"][0]["code_station"]
    hydro["data"][0]["longitude_station"] = True
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau hydrometry station {station_id} has source values outside the native schema",
    )


def test_native_integer_value_must_not_be_boolean() -> None:
    hydro, temperature = _sample_payloads()
    station_id = hydro["data"][0]["code_station"]
    hydro["data"][0]["code_projection"] = True
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau hydrometry station {station_id} has source values outside the native schema",
    )


def test_native_en_service_value_must_be_boolean() -> None:
    hydro, temperature = _sample_payloads()
    station_id = hydro["data"][0]["code_station"]
    hydro["data"][0]["en_service"] = 1
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau hydrometry station {station_id} has source values outside the native schema",
    )


def test_native_upstream_field_addition_changes_nothing() -> None:
    hydro = _full_payload(_HYDRO_FULL_FIXTURE)
    temperature = _full_payload(_TEMP_FULL_FIXTURE)
    hydro["data"][0]["upstream_new_field"] = "ignored"

    result = _refresh(hydro, temperature)

    assert result.issues == ()
    assert "upstream_new_field" not in result.value.data.columns
    assert result.value.data.shape == (7323, 73)


@pytest.mark.parametrize(
    "geometry",
    [[], {"coordinates": [1.0, 2.0], "crs": {"properties": {"name": 3}, "type": "name"}, "type": "Point"}],
)
def test_native_geometry_container_and_nested_members_are_strict(geometry: object) -> None:
    hydro, temperature = _sample_payloads()
    station_id = hydro["data"][0]["code_station"]
    hydro["data"][0]["geometry"] = geometry
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau hydrometry station {station_id} has source values outside the native schema",
    )


@pytest.mark.parametrize("endpoint", ["hydrometry", "temperature"])
@pytest.mark.parametrize("invalid_id", [7, "   "])
def test_native_ids_are_nonempty_strings_without_normalization(endpoint: str, invalid_id: object) -> None:
    hydro, temperature = _sample_payloads()
    target = hydro if endpoint == "hydrometry" else temperature
    target["data"][0]["code_station"] = invalid_id
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau {endpoint} station 0 has invalid code_station",
    )


@pytest.mark.parametrize("endpoint", ["hydrometry", "temperature"])
def test_native_endpoint_duplicate_is_an_issue(endpoint: str) -> None:
    hydro, temperature = _sample_payloads()
    target = hydro if endpoint == "hydrometry" else temperature
    station_id = target["data"][0]["code_station"]
    target["data"][1]["code_station"] = station_id
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau {endpoint} repeats code_station {station_id}",
    )


def test_native_cross_endpoint_collision_is_an_issue() -> None:
    hydro, temperature = _sample_payloads()
    station_id = hydro["data"][0]["code_station"]
    temperature["data"][0]["code_station"] = station_id
    _assert_issue(_refresh(hydro, temperature), f"fr_hubeau station {station_id} occurs in both station endpoints")


def test_native_hydrometry_station_count_is_exact() -> None:
    hydro, temperature = _sample_payloads()
    _assert_issue(
        _refresh(hydro, temperature),
        "fr_hubeau hydrometry response contains 2 stations; expected 6454",
    )


def test_native_temperature_station_count_is_exact() -> None:
    hydro = _full_payload(_HYDRO_FULL_FIXTURE)
    _, temperature = _sample_payloads()
    _assert_issue(
        _refresh(hydro, temperature),
        "fr_hubeau temperature response contains 2 stations; expected 869",
    )


def test_capture_boundaries_and_documentation_evidence() -> None:
    hydro = _full_payload(_HYDRO_FULL_FIXTURE)
    temperature = _full_payload(_TEMP_FULL_FIXTURE)
    assert hydro["count"] == len(hydro["data"]) == 6454
    assert temperature["count"] == len(temperature["data"]) == 869

    geojson = _full_payload(_GEOJSON_EVIDENCE)
    crs_name = "urn:ogc:def:crs:OGC:1.3:CRS84"
    assert geojson["crs"]["properties"]["name"] == crs_name
    assert geojson["features"][0]["geometry"]["crs"]["properties"]["name"] == crs_name

    openapi = _full_payload(_OPENAPI_EVIDENCE)
    description = openapi["definitions"]["Station hydrométrique"]["properties"]["code_projection"]["description"]
    assert description == "Type de projection de la station hydrométrique. Voir ProjCoordSiteHydro"


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (
            ["--hydro-fixture", str(_HYDRO_FIXTURE), "--out", "out"],
            "--hydro-fixture and --temp-fixture must be supplied together",
        ),
        (
            ["--temp-fixture", str(_TEMP_FIXTURE), "--out", "out"],
            "--hydro-fixture and --temp-fixture must be supplied together",
        ),
        (
            [
                "--hydro-fixture",
                str(_HYDRO_FIXTURE),
                "--temp-fixture",
                str(_TEMP_FIXTURE),
                "--native-out",
                "native.parquet",
            ],
            "--hydro-retrieved-at and --temperature-retrieved-at are required for fixture-native materialization",
        ),
        (
            [
                "--hydro-fixture",
                str(_HYDRO_FIXTURE),
                "--temp-fixture",
                str(_TEMP_FIXTURE),
                "--native-out",
                "native.parquet",
                "--hydro-retrieved-at",
                "2026-08-02T17:32:58+00:00",
            ],
            "--hydro-retrieved-at and --temperature-retrieved-at are required for fixture-native materialization",
        ),
        (
            [
                "--hydro-fixture",
                str(_HYDRO_FIXTURE),
                "--temp-fixture",
                str(_TEMP_FIXTURE),
                "--native-out",
                "native.parquet",
                "--temperature-retrieved-at",
                "2026-08-02T17:33:34+00:00",
            ],
            "--hydro-retrieved-at and --temperature-retrieved-at are required for fixture-native materialization",
        ),
        (
            [
                "--hydro-fixture",
                str(_HYDRO_FIXTURE),
                "--temp-fixture",
                str(_TEMP_FIXTURE),
                "--hydro-retrieved-at",
                "2026-08-02T17:32:58+00:00",
                "--temperature-retrieved-at",
                "2026-08-02T17:33:34+00:00",
            ],
            "--native-out is required for fixture-native materialization",
        ),
        (
            [
                "--hydro-fixture",
                str(_HYDRO_FIXTURE),
                "--temp-fixture",
                str(_TEMP_FIXTURE),
                "--out",
                "out",
                "--native-out",
                "native.parquet",
            ],
            "--native-out cannot be combined with canonical --out",
        ),
        (["--live", "--native-out", "native.parquet"], "--live cannot be combined with --native-out"),
        (
            [
                "--live",
                "--hydro-fixture",
                str(_HYDRO_FIXTURE),
                "--temp-fixture",
                str(_TEMP_FIXTURE),
                "--out",
                "out",
            ],
            "--live cannot be combined with fixture input",
        ),
        (
            ["--hydro-fixture", str(_HYDRO_FIXTURE), "--temp-fixture", str(_TEMP_FIXTURE)],
            "canonical materialization requires --out",
        ),
        (["--out", "out"], "canonical materialization requires --live or both fixture paths"),
    ],
)
def test_native_cli_rejections(
    argv: list[str], message: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_live(*args: object, **kwargs: object) -> object:
        pytest.fail("rejected CLI arguments reached the live reader")

    monkeypatch.setattr(generator, "generate_catalogue_from_live", fail_live)
    with pytest.raises(SystemExit, match="2"):
        generator.main(argv)
    assert message in capsys.readouterr().err


def test_fixture_native_cli_is_offline_and_prints_only_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_live(*args: object, **kwargs: object) -> object:
        pytest.fail("fixture-native CLI called the live reader")

    monkeypatch.setattr(generator, "_read_live_stations", fail_live)
    native_path = tmp_path / "native.parquet"
    exit_code = generator.main(
        [
            "--hydro-fixture",
            str(_HYDRO_FULL_FIXTURE),
            "--temp-fixture",
            str(_TEMP_FULL_FIXTURE),
            "--native-out",
            str(native_path),
            "--hydro-retrieved-at",
            "2026-08-02T17:32:58+00:00",
            "--temperature-retrieved-at",
            "2026-08-02T17:33:34+00:00",
        ]
    )
    assert exit_code == 0
    committed = read_native_table(native_path)
    assert committed.data.shape == (7323, 73)
    assert capsys.readouterr().out == native_table_content_digest(committed) + "\n"


def test_complete_native_table_is_source_faithful() -> None:
    hydro = _full_payload(_HYDRO_FULL_FIXTURE)
    temperature = _full_payload(_TEMP_FULL_FIXTURE)
    rematerialized = refresh_native_table(
        hydro,
        temperature,
        hydro_retrieved_at=_HYDRO_RETRIEVED_AT,
        temperature_retrieved_at=_TEMP_RETRIEVED_AT,
    )
    assert rematerialized.issues == ()
    frame = rematerialized.value.data
    assert frame.shape == (7323, 73)
    assert frame.schema == NATIVE_SCHEMA
    assert frame["code_station"].dtype == pl.String
    ids = frame["code_station"].to_list()
    assert ids == sorted(ids)
    assert len(set(ids)) == 7323
    counts = dict(frame.group_by("source_endpoint").len().iter_rows())
    assert counts == {"hydrometrie/referentiel/stations": 6454, "temperature/station": 869}
    assert frame["source_endpoint"].null_count() == 0
    assert set(frame["source_endpoint"].unique()) == {
        "hydrometrie/referentiel/stations",
        "temperature/station",
    }
    assert frame["retrieved_at"].dtype == pl.Datetime(time_unit="us", time_zone="UTC")
    assert frame["retrieved_at"].null_count() == 0
    for endpoint, instant in [
        ("hydrometrie/referentiel/stations", _HYDRO_RETRIEVED_AT.value),
        ("temperature/station", _TEMP_RETRIEVED_AT.value),
    ]:
        assert frame.filter(pl.col("source_endpoint") == endpoint)["retrieved_at"].unique().to_list() == [instant]

    hydro_rows = hydro["data"]
    temp_rows = temperature["data"]
    native_by_id = {row["code_station"]: row for row in frame.iter_rows(named=True)}
    for source_rows in (hydro_rows, temp_rows):
        for source in source_rows:
            native = native_by_id[source["code_station"]]
            for column in NATIVE_SOURCE_COLUMNS:
                assert native[column] == source.get(column)
    hydro_sample = next(row for row in hydro_rows if row["code_station"] == "1011000101")
    temp_sample = next(row for row in temp_rows if row["code_station"] == "01001336")
    for sample in (hydro_sample, temp_sample):
        native = frame.filter(pl.col("code_station") == sample["code_station"]).row(0, named=True)
        for column in NATIVE_SOURCE_COLUMNS:
            if column in sample:
                assert native[column] == sample[column]
            else:
                assert native[column] is None

    assert hydro_sample["code_projection"] == 39
    assert hydro_sample["latitude_station"] == 16.189402471
    assert hydro_sample["longitude_station"] == -61.658989597
    assert hydro_sample["coordonnee_x_station"] == 643352.0
    assert hydro_sample["coordonnee_y_station"] == 1790354.0
    control = frame.filter(pl.col("code_station") == "1011000101").row(0, named=True)
    for column in (
        "code_projection",
        "latitude_station",
        "longitude_station",
        "coordonnee_x_station",
        "coordonnee_y_station",
    ):
        assert control[column] == hydro_sample[column]

    projection_31 = [row for row in hydro_rows if row["code_projection"] == 31]
    assert len(projection_31) == 54
    for source in projection_31:
        native = frame.filter(pl.col("code_station") == source["code_station"]).row(0, named=True)
        assert native["latitude_station"] == source["latitude_station"]
        assert native["longitude_station"] == source["longitude_station"]
        assert native["coordonnee_x_station"] == source["coordonnee_x_station"]
        assert native["coordonnee_y_station"] == source["coordonnee_y_station"]
    transposed = next(row for row in projection_31 if row["code_station"] == "H000000201")
    assert transposed["latitude_station"] == transposed["coordonnee_x_station"] == 4.099322
    assert transposed["longitude_station"] == transposed["coordonnee_y_station"] == 49.989435

    committed = read_native_table(Path(generator.__file__).parent / "catalogue" / "native.parquet")
    pl_testing.assert_frame_equal(committed.data, frame, check_exact=True)
    assert native_table_content_digest(committed) == _PINNED_NATIVE_DIGEST
    assert native_table_content_digest(rematerialized.value) == _PINNED_NATIVE_DIGEST


def test_fixture_wrapper_matches_direct_refresh() -> None:
    wrapped = refresh_native_table_from_fixtures(
        _HYDRO_FULL_FIXTURE,
        _TEMP_FULL_FIXTURE,
        hydro_retrieved_at=_HYDRO_RETRIEVED_AT,
        temperature_retrieved_at=_TEMP_RETRIEVED_AT,
    )
    direct = _refresh(_full_payload(_HYDRO_FULL_FIXTURE), _full_payload(_TEMP_FULL_FIXTURE))
    assert wrapped.issues == direct.issues == ()
    pl_testing.assert_frame_equal(wrapped.value.data, direct.value.data, check_exact=True)
