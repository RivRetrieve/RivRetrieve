from __future__ import annotations

import json
import lzma
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from urllib.parse import parse_qsl, urlsplit

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, read_native_table
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.fr_hubeau import generate_catalogue as generator
from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import (
    HYDRO_PRODUCT_DEFS,
    NATIVE_SCHEMA,
    NATIVE_SOURCE_COLUMNS,
    TEMP_PRODUCT_DEFS,
    build_catalogue,
    decode_availability,
    native_table_content_digest,
    refresh_native_table,
)
from rivretrieve._internal.providers.fr_hubeau.origins import (
    CODE_PROJECTION_31_AXIS_TRANSPOSITION,
    CODE_PROJECTION_31_METROPOLITAN_BOUNDS,
    CRS_EVIDENCE_URL,
    FRANCE_ORIGIN_DECLARATIONS,
    HYDROMETRY_STATION_CATALOGUE_ORIGINS,
    TEMPERATURE_CRS_EVIDENCE_URL,
    TEMPERATURE_STATION_CATALOGUE_ORIGINS,
)
from tests._catalogue_projection import copy_catalogue_projection
from tests.test_catalogue_origin_certification import _catalogue_recording_paths

_TEST_DATA_DIR = Path("tests/test_data")
_HYDRO_FIXTURE = _TEST_DATA_DIR / "fr_hubeau_metadata.json"
_TEMP_FIXTURE = _TEST_DATA_DIR / "fr_hubeau_temp_stations.json"
_HYDRO_FULL_FIXTURE = _TEST_DATA_DIR / "fr_hubeau_referentiel_stations_full.json"
_TEMP_FULL_FIXTURE = _TEST_DATA_DIR / "fr_hubeau_temperature_stations_full.json"
_GEOJSON_EVIDENCE = _TEST_DATA_DIR / "fr_hubeau_geojson_crs_evidence.json"
_OPENAPI_EVIDENCE = _TEST_DATA_DIR / "fr_hubeau_openapi_v2.json"
_HYDRO_RETRIEVED_AT = RetrievedAt(datetime(2026, 8, 2, 17, 32, 58, tzinfo=UTC))
_TEMP_RETRIEVED_AT = RetrievedAt(datetime(2026, 8, 2, 17, 33, 34, tzinfo=UTC))
_PINNED_NATIVE_DIGEST = "f5c3d84a4e6674a1aa5e6b951576edf6bcbdf77867ab0e5c3ffe2f09adbf7322"
NATIVE_PATH = Path("maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet")
CURRENT_NATIVE_PATH = Path("src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet")


def _availability(retained_evidence_root):
    path = retained_evidence_root / "maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz"
    return decode_availability(lzma.decompress(path.read_bytes()))


def _full_payload(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text())
    assert isinstance(value, dict)
    return value


def _sample_payloads(retained_evidence_root) -> tuple[dict[str, object], dict[str, object]]:
    hydro_full = _full_payload(retained_evidence_root / _HYDRO_FULL_FIXTURE)
    temp_full = _full_payload(retained_evidence_root / _TEMP_FULL_FIXTURE)
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


@pytest.fixture(scope="module")
def _pristine_projection(retained_evidence_root):
    built = build_catalogue(
        read_native_table(retained_evidence_root / NATIVE_PATH),
        FRANCE_ORIGIN_DECLARATIONS,
        _availability(retained_evidence_root),
    )
    return copy_catalogue_projection(built)


@pytest.fixture
def catalogue(_pristine_projection):
    return copy_catalogue_projection(_pristine_projection)


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")
@pytest.mark.parametrize(
    ("endpoint", "endpoint_origins"),
    [
        ("hydrometrie/referentiel/stations", HYDROMETRY_STATION_CATALOGUE_ORIGINS),
        ("temperature/station", TEMPERATURE_STATION_CATALOGUE_ORIGINS),
    ],
    ids=["hydrometry", "temperature"],
)
@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet")
def test_native_build_enforces_each_endpoint_origin_declaration(
    retained_evidence_root,
    endpoint: str,
    endpoint_origins: dict[str, object],
) -> None:
    broken = dict(endpoint_origins)
    del broken["longitude"]
    origins = {
        "hydrometrie/referentiel/stations": HYDROMETRY_STATION_CATALOGUE_ORIGINS,
        "temperature/station": TEMPERATURE_STATION_CATALOGUE_ORIGINS,
        endpoint: broken,
    }

    with pytest.raises(
        FatalContractError,
        match=r"^fr_hubeau\.longitude: canonical column has no origin declaration$",
    ):
        build_catalogue(
            read_native_table(retained_evidence_root / NATIVE_PATH), origins, _availability(retained_evidence_root)
        )


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")
@pytest.mark.parametrize(
    ("endpoint", "partition", "remaining", "expected"),
    [
        ("hydrometrie/referentiel/stations", "hydrometry", 6453, 6454),
        ("temperature/station", "temperature", 868, 869),
    ],
    ids=["hydrometry", "temperature"],
)
@pytest.mark.governing(
    "maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet",
    full_verification=("fr_hubeau",),
)
def test_native_build_rejects_unattested_partition_changes(
    retained_evidence_root,
    endpoint: str,
    partition: str,
    remaining: int,
    expected: int,
) -> None:
    native = read_native_table(retained_evidence_root / NATIVE_PATH)
    row_to_remove = native.data.filter(pl.col("source_endpoint") == endpoint).row(0, named=True)
    shortened = NativeTable(
        native.data.filter(
            ~((pl.col("source_endpoint") == endpoint) & (pl.col("code_station") == row_to_remove["code_station"]))
        )
    )

    with pytest.raises(FatalContractError) as raised:
        build_catalogue(shortened, FRANCE_ORIGIN_DECLARATIONS, _availability(retained_evidence_root))
    assert str(raised.value) == "Hub’Eau native content does not match its acquisition identity"


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")
@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet")
def test_generate_catalogue_station_count(catalogue) -> None:
    assert catalogue.stations.height == 7323


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")
@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet")
def test_generate_catalogue_product_count(catalogue) -> None:
    cat = catalogue
    assert cat.products.height == 4


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")
@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet")
def test_generate_catalogue_station_products_cross(catalogue) -> None:
    cat = catalogue
    assert cat.station_products.height == 20231


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")
@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet")
def test_generate_catalogue_hydro_station_fields(catalogue) -> None:
    cat = catalogue
    station = cat.stations.filter(pl.col("station_id") == "1011000101")
    assert station.height == 1
    assert station["crs"][0] == "EPSG:4326"


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")
@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet")
def test_generate_catalogue_temp_station_fields(catalogue) -> None:
    cat = catalogue
    station = cat.stations.filter(pl.col("station_id") == "01001336")
    assert station.height == 1
    assert station["crs"][0] == "EPSG:4326"


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")
@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet")
def test_generate_catalogue_filters_no_stations(retained_evidence_root, catalogue) -> None:
    assert catalogue.stations.height == read_native_table(retained_evidence_root / NATIVE_PATH).data.height


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")
@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet")
def test_generate_catalogue_hydro_station_products(catalogue) -> None:
    cat = catalogue
    hydro_sp = cat.station_products.filter(pl.col("station_id") == "1011000101")
    hydro_products = set(hydro_sp["product_id"].to_list())
    assert hydro_products == {
        "discharge_daily_mean",
        "discharge_daily_max",
        "stage_daily_max",
    }


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")
@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet")
def test_generate_catalogue_temp_station_products(catalogue) -> None:
    cat = catalogue
    temp_sp = cat.station_products.filter(pl.col("station_id") == "01001336")
    assert temp_sp["product_id"].to_list() == ["water_temperature_reported"]


def _assert_fatal_issue(retained_evidence_root, table: NativeTable, code: str, message: str) -> None:
    with pytest.raises(FatalContractError) as raised:
        build_catalogue(table, FRANCE_ORIGIN_DECLARATIONS, _availability(retained_evidence_root))
    assert [(issue.provider_id, issue.code, issue.message) for issue in raised.value.issues] == [
        (ProviderId("fr_hubeau"), code, message)
    ]


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")
@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet")
def test_native_builder_rejects_one_unknown_endpoint_row(retained_evidence_root) -> None:
    native = read_native_table(retained_evidence_root / NATIVE_PATH)
    station_id = native.data["code_station"][0]
    bad = NativeTable(
        native.data.with_columns(
            pl.when(pl.col("code_station") == station_id)
            .then(pl.lit("third/endpoint"))
            .otherwise(pl.col("source_endpoint"))
            .alias("source_endpoint")
        )
    )
    _assert_fatal_issue(
        retained_evidence_root,
        bad,
        "catalogue_native.unknown_source_endpoint",
        "fr_hubeau native table contains unknown source_endpoint third/endpoint",
    )


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")
@pytest.mark.parametrize(
    ("column", "message"),
    [
        ("longitude_station", "fr_hubeau.longitude: native column 'longitude_station' does not exist"),
        ("latitude", "fr_hubeau.latitude: native column 'latitude' does not exist"),
    ],
)
@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet")
def test_native_builder_rejects_each_absent_endpoint_coordinate(
    retained_evidence_root, column: str, message: str
) -> None:
    native = read_native_table(retained_evidence_root / NATIVE_PATH)
    _assert_fatal_issue(
        retained_evidence_root,
        NativeTable(native.data.drop(column)),
        "catalogue_origin.absent_native_column",
        message,
    )


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")
@pytest.mark.parametrize("signature_column", ["coordonnee_x_station", "coordonnee_y_station"])
@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet")
def test_code_31_correction_requires_each_signature_half(retained_evidence_root, signature_column: str) -> None:
    native = read_native_table(retained_evidence_root / NATIVE_PATH)
    station_id = "H000000201"
    bad = NativeTable(
        native.data.with_columns(
            pl.when(pl.col("code_station") == station_id)
            .then(pl.col(signature_column) + 0.001)
            .otherwise(pl.col(signature_column))
            .alias(signature_column)
        )
    )
    _assert_fatal_issue(
        retained_evidence_root,
        bad,
        "catalogue_coordinate.correction_precondition_failed",
        f"fr_hubeau station {station_id} code_projection=31 does not match the documented transposition signature",
    )


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")
@pytest.mark.parametrize(
    ("source_column", "signature_column", "value"),
    [
        ("longitude_station", "coordonnee_y_station", 42.4173),
        ("longitude_station", "coordonnee_y_station", 49.989436),
        ("latitude_station", "coordonnee_x_station", -0.616425),
        ("latitude_station", "coordonnee_x_station", 5.593354),
    ],
)
@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet")
def test_code_31_correction_checks_each_inclusive_bound(
    retained_evidence_root, source_column: str, signature_column: str, value: float
) -> None:
    native = read_native_table(retained_evidence_root / NATIVE_PATH)
    station_id = "H000000201"
    condition = pl.col("code_station") == station_id
    bad = NativeTable(
        native.data.with_columns(
            pl.when(condition).then(pl.lit(value)).otherwise(pl.col(source_column)).alias(source_column),
            pl.when(condition).then(pl.lit(value)).otherwise(pl.col(signature_column)).alias(signature_column),
        )
    )
    _assert_fatal_issue(
        retained_evidence_root,
        bad,
        "catalogue_coordinate.outside_metropolitan_bounds",
        f"fr_hubeau station {station_id} remains outside the evidenced metropolitan bounds after code_projection=31 correction",
    )


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")
@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet")
def test_only_code_31_coordinates_are_transposed(retained_evidence_root, catalogue) -> None:
    native = read_native_table(retained_evidence_root / NATIVE_PATH).data
    stations = catalogue.stations
    code_31 = native.filter(pl.col("code_projection") == 31)
    assert code_31.height == 54
    corrected = stations.join(
        code_31.select(
            pl.col("code_station").alias("station_id"),
            pl.col("longitude_station").alias("expected_latitude"),
            pl.col("latitude_station").alias("expected_longitude"),
        ),
        on="station_id",
    )
    assert corrected["latitude"].to_list() == corrected["expected_latitude"].to_list()
    assert corrected["longitude"].to_list() == corrected["expected_longitude"].to_list()
    lat_bounds = CODE_PROJECTION_31_METROPOLITAN_BOUNDS["latitude"]
    lon_bounds = CODE_PROJECTION_31_METROPOLITAN_BOUNDS["longitude"]
    assert corrected["latitude"].is_between(*lat_bounds, closed="both").all()
    assert corrected["longitude"].is_between(*lon_bounds, closed="both").all()
    assert CODE_PROJECTION_31_AXIS_TRANSPOSITION == {
        "latitude": "longitude_station",
        "longitude": "latitude_station",
    }
    sample = stations.filter(pl.col("station_id") == "H000000201").row(0, named=True)
    assert (sample["latitude"], sample["longitude"]) == (49.989435, 4.099322)
    control = stations.filter(pl.col("station_id") == "1011000101").row(0, named=True)
    assert (control["latitude"], control["longitude"]) == (16.189402471, -61.658989597)

    formerly_shipped = {
        "H001000301",
        "H002001101",
        "H003000201",
        "H004000101",
        "H004000201",
        "H010002201",
        "H010002301",
        "H012000201",
        "H013000101",
        "H124000301",
        "H125000201",
        "H125000202",
        "H127000101",
        "H143000201",
        "K451000101",
        "K455000201",
        "K462000101",
        "K465000101",
        "K467000301",
        "K468000201",
        "K469000201",
        "K469000202",
        "K471000201",
        "K476000101",
        "K476000102",
        "K478000301",
        "K478000401",
        "O312102101",
        "O821000101",
        "O821000201",
        "O822000101",
        "O823153101",
        "O825501101",
        "O826401101",
        "O831000201",
        "O831000301",
        "Y021401101",
        "Y043642201",
        "Y060401201",
        "Y111201201",
        "Y122502201",
        "Y142203401",
        "Y200002801",
        "Y345402401",
        "Y401202101",
        "Y402201401",
        "Y412541101",
    }
    newly_affected = {
        "H000000201",
        "H000000301",
        "H001000401",
        "H003000301",
        "R423001101",
        "R423001201",
        "R521001101",
    }
    assert formerly_shipped | newly_affected == set(code_31["code_station"])
    old_orientation = code_31.filter(pl.col("code_station").is_in(formerly_shipped)).select(
        pl.col("code_station").alias("station_id"), "latitude_station", "longitude_station"
    )
    old_vs_new = stations.join(old_orientation, on="station_id")
    assert (
        (old_vs_new["latitude"] != old_vs_new["latitude_station"])
        & (old_vs_new["longitude"] != old_vs_new["longitude_station"])
    ).all()
    assert old_orientation["latitude_station"].min() == 1.4279124
    assert old_orientation["latitude_station"].max() == 5.593353
    assert old_orientation["longitude_station"].min() == 42.4174
    assert old_orientation["longitude_station"].max() == 49.9048593


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")
@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet")
def test_code_26_changed_ids_pass_through_exactly(retained_evidence_root, catalogue) -> None:
    ids = [
        "F462000701",
        "K040301001",
        "K040302002",
        "K041031001",
        "K480001001",
        "L001061101",
        "L440000101",
        "O017402901",
        "O773000101",
        "P011501101",
        "P036000101",
        "P089000101",
        "P115000101",
        "P177000101",
        "P302000101",
        "U321401001",
    ]
    native = read_native_table(retained_evidence_root / NATIVE_PATH).data
    expected = (
        native.filter(pl.col("code_station").is_in(ids))
        .select(
            pl.lit("fr_hubeau").alias("provider_id"),
            pl.col("code_station").alias("station_id"),
            pl.col("latitude_station").alias("latitude"),
            pl.col("longitude_station").alias("longitude"),
            pl.lit("EPSG:4326").alias("crs"),
        )
        .sort("station_id")
    )
    actual = catalogue.stations.filter(pl.col("station_id").is_in(ids)).sort("station_id")
    pl_testing.assert_frame_equal(actual, expected, check_exact=True)


@pytest.mark.parametrize("endpoint", ["hydrometry", "temperature"])
@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_native_envelope_must_be_object(retained_evidence_root, endpoint: str) -> None:
    hydro, temperature = _sample_payloads(retained_evidence_root)
    if endpoint == "hydrometry":
        hydro = []
    else:
        temperature = []
    _assert_issue(_refresh(hydro, temperature), f"fr_hubeau {endpoint} response must be an object")


@pytest.mark.parametrize("endpoint", ["hydrometry", "temperature"])
@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_native_data_must_be_list(retained_evidence_root, endpoint: str) -> None:
    hydro, temperature = _sample_payloads(retained_evidence_root)
    target = hydro if endpoint == "hydrometry" else temperature
    target["data"] = {}
    _assert_issue(_refresh(hydro, temperature), f"fr_hubeau {endpoint} response data must be a list")


@pytest.mark.parametrize("endpoint", ["hydrometry", "temperature"])
@pytest.mark.parametrize("invalid_count", [True, "2"])
@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_native_count_must_be_non_boolean_integer(retained_evidence_root, endpoint: str, invalid_count: object) -> None:
    hydro, temperature = _sample_payloads(retained_evidence_root)
    target = hydro if endpoint == "hydrometry" else temperature
    target["count"] = invalid_count
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau {endpoint} response count must be a non-boolean integer",
    )


@pytest.mark.parametrize("endpoint", ["hydrometry", "temperature"])
@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_native_count_must_match_rows(retained_evidence_root, endpoint: str) -> None:
    hydro, temperature = _sample_payloads(retained_evidence_root)
    target = hydro if endpoint == "hydrometry" else temperature
    target["count"] = 3
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau {endpoint} response count 3 does not match 2 rows",
    )


@pytest.mark.parametrize("endpoint", ["hydrometry", "temperature"])
@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_native_row_must_be_object(retained_evidence_root, endpoint: str) -> None:
    hydro, temperature = _sample_payloads(retained_evidence_root)
    target = hydro if endpoint == "hydrometry" else temperature
    target["data"][0] = []
    _assert_issue(_refresh(hydro, temperature), f"fr_hubeau {endpoint} station 0 must be an object")


@pytest.mark.parametrize("endpoint", ["hydrometry", "temperature"])
@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_native_row_requires_complete_endpoint_key_set(retained_evidence_root, endpoint: str) -> None:
    hydro, temperature = _sample_payloads(retained_evidence_root)
    target = hydro if endpoint == "hydrometry" else temperature
    row = target["data"][0]
    station_id = row["code_station"]
    del row[next(key for key in row if key != "code_station")]
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau {endpoint} station {station_id} is missing required source fields",
    )


@pytest.mark.parametrize("endpoint", ["hydrometry", "temperature"])
@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_native_scalar_value_must_inhabit_schema(retained_evidence_root, endpoint: str) -> None:
    hydro, temperature = _sample_payloads(retained_evidence_root)
    target = hydro if endpoint == "hydrometry" else temperature
    row = target["data"][0]
    station_id = row["code_station"]
    row["libelle_station"] = {"invalid": "scalar"}
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau {endpoint} station {station_id} has source values outside the native schema",
    )


@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_native_list_value_must_inhabit_schema(retained_evidence_root) -> None:
    hydro, temperature = _sample_payloads(retained_evidence_root)
    station_id = hydro["data"][0]["code_station"]
    hydro["data"][0]["code_sandre_reseau_station"] = ["valid", 3]
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau hydrometry station {station_id} has source values outside the native schema",
    )


@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_native_list_value_must_be_a_list(retained_evidence_root) -> None:
    hydro, temperature = _sample_payloads(retained_evidence_root)
    station_id = hydro["data"][0]["code_station"]
    hydro["data"][0]["code_sandre_reseau_station"] = "BSH164"
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau hydrometry station {station_id} has source values outside the native schema",
    )


@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_native_float_value_must_be_finite(retained_evidence_root) -> None:
    for invalid_value in (float("nan"), float("inf")):
        hydro, temperature = _sample_payloads(retained_evidence_root)
        station_id = hydro["data"][0]["code_station"]
        hydro["data"][0]["longitude_station"] = invalid_value
        _assert_issue(
            _refresh(hydro, temperature),
            f"fr_hubeau hydrometry station {station_id} has source values outside the native schema",
        )


@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_native_float_value_must_not_be_boolean(retained_evidence_root) -> None:
    hydro, temperature = _sample_payloads(retained_evidence_root)
    station_id = hydro["data"][0]["code_station"]
    hydro["data"][0]["longitude_station"] = True
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau hydrometry station {station_id} has source values outside the native schema",
    )


@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_native_integer_value_must_not_be_boolean(retained_evidence_root) -> None:
    hydro, temperature = _sample_payloads(retained_evidence_root)
    station_id = hydro["data"][0]["code_station"]
    hydro["data"][0]["code_projection"] = True
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau hydrometry station {station_id} has source values outside the native schema",
    )


@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_native_en_service_value_must_be_boolean(retained_evidence_root) -> None:
    hydro, temperature = _sample_payloads(retained_evidence_root)
    station_id = hydro["data"][0]["code_station"]
    hydro["data"][0]["en_service"] = 1
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau hydrometry station {station_id} has source values outside the native schema",
    )


@pytest.mark.parametrize(
    ("endpoint", "injected_field"),
    [
        ("hydrometry", "upstream_new_field"),
        ("temperature", "descriptif_station"),
        ("hydrometry", "nature_station"),
    ],
)
@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_native_upstream_field_addition_changes_nothing(
    retained_evidence_root, endpoint: str, injected_field: str
) -> None:
    hydro = _full_payload(retained_evidence_root / _HYDRO_FULL_FIXTURE)
    temperature = _full_payload(retained_evidence_root / _TEMP_FULL_FIXTURE)
    target = hydro if endpoint == "hydrometry" else temperature
    target["data"][0][injected_field] = "ignored"

    result = _refresh(hydro, temperature)

    assert result.issues == ()
    if injected_field in NATIVE_SOURCE_COLUMNS:
        source_endpoint = "hydrometrie/referentiel/stations" if endpoint == "hydrometry" else "temperature/station"
        injected_endpoint = result.value.data.filter(pl.col("source_endpoint") == source_endpoint)
        assert injected_endpoint[injected_field].null_count() == injected_endpoint.height
    else:
        assert injected_field not in result.value.data.columns
    assert native_table_content_digest(result.value) == _PINNED_NATIVE_DIGEST


@pytest.mark.parametrize(
    "geometries",
    [
        pytest.param(
            [
                MappingProxyType(
                    {
                        "coordinates": [1.0, 2.0],
                        "crs": {"properties": {"name": "CRS84"}, "type": "name"},
                        "type": "Point",
                    }
                )
            ],
            id="container-must-be-dict",
        ),
        pytest.param(
            [
                {"coordinates": [1.0, 2.0], "type": "Point"},
                {"coordinates": [1.0, 2.0], "srs": {}, "type": "Point"},
            ],
            id="container-key-set",
        ),
        pytest.param(
            [{"coordinates": [1.0, 2.0], "crs": None, "type": "Point"}],
            id="crs-must-be-dict",
        ),
        pytest.param(
            [
                {"coordinates": [1.0, 2.0], "crs": {"properties": {"name": "CRS84"}}, "type": "Point"},
                {
                    "coordinates": [1.0, 2.0],
                    "crs": {"properties": {"name": "CRS84"}, "type": "name", "extra": None},
                    "type": "Point",
                },
            ],
            id="crs-key-set",
        ),
        pytest.param(
            [{"coordinates": [1.0, 2.0], "crs": {"properties": {"name": "CRS84"}, "type": 7}, "type": "Point"}],
            id="crs-type-must-be-string",
        ),
        pytest.param(
            [{"coordinates": [1.0, 2.0], "crs": {"properties": None, "type": "name"}, "type": "Point"}],
            id="crs-properties-must-be-dict",
        ),
        pytest.param(
            [
                {"coordinates": [1.0, 2.0], "crs": {"properties": {}, "type": "name"}, "type": "Point"},
                {
                    "coordinates": [1.0, 2.0],
                    "crs": {"properties": {"name": "CRS84", "extra": None}, "type": "name"},
                    "type": "Point",
                },
            ],
            id="crs-properties-key-set",
        ),
        pytest.param(
            [{"coordinates": [1.0, 2.0], "crs": {"properties": {"name": 3}, "type": "name"}, "type": "Point"}],
            id="crs-name-must-be-string",
        ),
        pytest.param(
            [{"coordinates": [1.0, 2.0], "crs": {"properties": {"name": "CRS84"}, "type": "name"}, "type": 7}],
            id="geometry-type-must-be-string",
        ),
        pytest.param(
            [{"coordinates": (1.0, 2.0), "crs": {"properties": {"name": "CRS84"}, "type": "name"}, "type": "Point"}],
            id="coordinates-must-be-list",
        ),
        pytest.param(
            [{"coordinates": [True, 2.0], "crs": {"properties": {"name": "CRS84"}, "type": "name"}, "type": "Point"}],
            id="coordinates-must-not-contain-booleans",
        ),
        pytest.param(
            [{"coordinates": ["1.0", 2.0], "crs": {"properties": {"name": "CRS84"}, "type": "name"}, "type": "Point"}],
            id="coordinates-must-be-numeric",
        ),
        pytest.param(
            [
                {
                    "coordinates": [float("inf"), 2.0],
                    "crs": {"properties": {"name": "CRS84"}, "type": "name"},
                    "type": "Point",
                }
            ],
            id="coordinates-must-be-finite",
        ),
    ],
)
@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_native_geometry_container_and_nested_members_are_strict(
    retained_evidence_root, geometries: list[object]
) -> None:
    for geometry in geometries:
        hydro, temperature = _sample_payloads(retained_evidence_root)
        station_id = hydro["data"][0]["code_station"]
        hydro["data"][0]["geometry"] = geometry
        message = f"fr_hubeau hydrometry station {station_id} has source values outside the native schema"
        _assert_issue(_refresh(hydro, temperature), message)


@pytest.mark.parametrize("endpoint", ["hydrometry", "temperature"])
@pytest.mark.parametrize("invalid_id", [7, "   "])
@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_native_ids_are_nonempty_strings_without_normalization(
    retained_evidence_root, endpoint: str, invalid_id: object
) -> None:
    hydro, temperature = _sample_payloads(retained_evidence_root)
    target = hydro if endpoint == "hydrometry" else temperature
    target["data"][0]["code_station"] = invalid_id
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau {endpoint} station 0 has invalid code_station",
    )


@pytest.mark.parametrize("endpoint", ["hydrometry", "temperature"])
@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_native_endpoint_duplicate_is_an_issue(retained_evidence_root, endpoint: str) -> None:
    hydro, temperature = _sample_payloads(retained_evidence_root)
    target = hydro if endpoint == "hydrometry" else temperature
    station_id = target["data"][0]["code_station"]
    target["data"][1]["code_station"] = station_id
    _assert_issue(
        _refresh(hydro, temperature),
        f"fr_hubeau {endpoint} repeats code_station {station_id}",
    )


@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_native_cross_endpoint_collision_is_an_issue(retained_evidence_root) -> None:
    hydro, temperature = _sample_payloads(retained_evidence_root)
    station_id = hydro["data"][0]["code_station"]
    temperature["data"][0]["code_station"] = station_id
    _assert_issue(_refresh(hydro, temperature), f"fr_hubeau station {station_id} occurs in both station endpoints")


@pytest.mark.governing(
    "tests/test_data/fr_hubeau_geojson_crs_evidence.json",
    "tests/test_data/fr_hubeau_openapi_v2.json",
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_capture_boundaries_and_documentation_evidence(retained_evidence_root) -> None:
    hydro = _full_payload(retained_evidence_root / _HYDRO_FULL_FIXTURE)
    temperature = _full_payload(retained_evidence_root / _TEMP_FULL_FIXTURE)
    assert hydro["count"] == len(hydro["data"]) == 6454
    assert temperature["count"] == len(temperature["data"]) == 869

    geojson = _full_payload(retained_evidence_root / _GEOJSON_EVIDENCE)
    crs_name = "urn:ogc:def:crs:OGC:1.3:CRS84"
    assert geojson["crs"]["properties"]["name"] == crs_name
    feature = geojson["features"][0]
    assert feature["properties"]["code_station"] == "1011000101"
    assert feature["geometry"]["crs"]["properties"]["name"] == crs_name
    assert feature["geometry"]["coordinates"] == [-61.65898959694908, 16.18940247103205]
    assert feature["properties"]["longitude_station"] == -61.65898959694908
    assert feature["properties"]["latitude_station"] == 16.18940247103205

    hydro_station = next(row for row in hydro["data"] if row["code_station"] == "1011000101")
    geojson_longitude, geojson_latitude = feature["geometry"]["coordinates"]
    assert round(geojson_longitude, 9) == hydro_station["longitude_station"]
    assert round(geojson_latitude, 9) == hydro_station["latitude_station"]
    assert geojson_longitude != hydro_station["longitude_station"]
    assert geojson_latitude != hydro_station["latitude_station"]

    hydro_agreeing = {
        row["code_station"]
        for row in hydro["data"]
        if row["geometry"]["coordinates"] == [row["longitude_station"], row["latitude_station"]]
    }
    hydro_projection_31 = {row["code_station"] for row in hydro["data"] if row["code_projection"] == 31}
    assert hydro_agreeing == hydro_projection_31
    assert len(hydro_agreeing) == 54
    assert (
        sum(
            row["geometry"]["coordinates"] != [row["longitude_station"], row["latitude_station"]]
            for row in hydro["data"]
        )
        == 6400
    )
    assert all(
        round(row["geometry"]["coordinates"][0], 9) == row["longitude_station"]
        and round(row["geometry"]["coordinates"][1], 9) == row["latitude_station"]
        for row in hydro["data"]
    )
    assert (
        sum(row["geometry"]["coordinates"] != [row["longitude"], row["latitude"]] for row in temperature["data"]) == 869
    )
    assert all(
        round(row["geometry"]["coordinates"][0], 9) == row["longitude"]
        and round(row["geometry"]["coordinates"][1], 9) == row["latitude"]
        for row in temperature["data"]
    )
    coordinate_discrepancies = [
        abs(row["geometry"]["coordinates"][axis] - row[field])
        for rows, coordinate_fields in (
            (hydro["data"], ("longitude_station", "latitude_station")),
            (temperature["data"], ("longitude", "latitude")),
        )
        for row in rows
        for axis, field in enumerate(coordinate_fields)
    ]
    assert max(coordinate_discrepancies) <= 5.0e-10
    assert all(row["geometry"]["crs"] is not None for row in temperature["data"])
    assert {row["geometry"]["crs"]["properties"]["name"] for row in temperature["data"]} == {crs_name}

    for declaration_url, capture, pagination_parameters in (
        (CRS_EVIDENCE_URL, geojson, [("page", "1"), ("size", "1000")]),
        (TEMPERATURE_CRS_EVIDENCE_URL, temperature, [("page", "1")]),
    ):
        declared = urlsplit(declaration_url)
        captured = urlsplit(capture["first"])
        assert (declared.scheme, declared.netloc, declared.path) == (
            captured.scheme,
            captured.netloc,
            captured.path,
        )
        declared_query = Counter(parse_qsl(declared.query, keep_blank_values=True))
        captured_query = Counter(parse_qsl(captured.query, keep_blank_values=True))
        assert captured_query == declared_query + Counter(pagination_parameters)

    openapi = _full_payload(retained_evidence_root / _OPENAPI_EVIDENCE)
    station_properties = openapi["definitions"]["Station hydrométrique"]["properties"]
    for coordinate_name in (
        "latitude_station",
        "longitude_station",
        "coordonnee_x_station",
        "coordonnee_y_station",
    ):
        assert station_properties[coordinate_name]["type"] == "number"
        assert station_properties[coordinate_name]["format"] == "double"
    assert "WGS84" in station_properties["latitude_station"]["description"]
    assert "WGS84" in station_properties["longitude_station"]["description"]
    assert station_properties["coordonnee_x_station"]["description"] == "Coordonnée X de la station hydrométrique"
    assert station_properties["coordonnee_y_station"]["description"] == "Coordonnée Y de la station hydrométrique"
    description = station_properties["code_projection"]["description"]
    assert description == "Type de projection de la station hydrométrique. Voir ProjCoordSiteHydro"
    assert (hydro_station["coordonnee_x_station"], hydro_station["coordonnee_y_station"]) == (
        643352.0,
        1790354.0,
    )
    assert Counter(row["code_projection"] for row in hydro["data"]) == {
        26: 6059,
        39: 142,
        5: 74,
        38: 54,
        31: 54,
        40: 48,
        41: 23,
    }


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--out", "out"], "--native is required for canonical build"),
        (
            ["--native", "native.parquet", "--out", "out", "--availability-ledger", "ledger.json.xz"],
            "--evidence-root is required for canonical build",
        ),
        (["--native", str(NATIVE_PATH)], "--out is required for canonical build"),
        (
            [
                "--native",
                str(NATIVE_PATH),
                "--availability-ledger",
                "ledger.json.xz",
                "--out",
                "out",
                "--hydro-fixture",
                str(_HYDRO_FIXTURE),
            ],
            "--native build mode cannot be combined with refresh sources or retrieval instants",
        ),
        (
            [
                "--native",
                str(NATIVE_PATH),
                "--availability-ledger",
                "ledger.json.xz",
                "--out",
                "out",
                "--temp-fixture",
                str(_TEMP_FIXTURE),
            ],
            "--native build mode cannot be combined with refresh sources or retrieval instants",
        ),
        (
            [
                "--native",
                str(NATIVE_PATH),
                "--availability-ledger",
                "ledger.json.xz",
                "--out",
                "out",
                "--native-out",
                "native.parquet",
            ],
            "--native build mode cannot be combined with refresh sources or retrieval instants",
        ),
        (
            [
                "--native",
                str(NATIVE_PATH),
                "--availability-ledger",
                "ledger.json.xz",
                "--out",
                "out",
                "--hydro-retrieved-at",
                "2026-08-02T17:32:58+00:00",
            ],
            "--native build mode cannot be combined with refresh sources or retrieval instants",
        ),
        (
            [
                "--native",
                str(NATIVE_PATH),
                "--availability-ledger",
                "ledger.json.xz",
                "--out",
                "out",
                "--temperature-retrieved-at",
                "2026-08-02T17:33:34+00:00",
            ],
            "--native build mode cannot be combined with refresh sources or retrieval instants",
        ),
    ],
)
def test_native_cli_rejections(argv: list[str], message: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="2"):
        generator.main(argv)
    assert message in capsys.readouterr().err


def test_retired_live_argument_is_unrecognized(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="2"):
        generator.main(["--live"])
    assert "unrecognized arguments: --live" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--hydro-fixture", str(_HYDRO_FIXTURE)], "--hydro-fixture and --temp-fixture must be supplied together"),
        (["--temp-fixture", str(_TEMP_FIXTURE)], "--hydro-fixture and --temp-fixture must be supplied together"),
        (
            ["--hydro-fixture", str(_HYDRO_FIXTURE), "--temp-fixture", str(_TEMP_FIXTURE)],
            "--native-out is required for fixture-native materialization",
        ),
    ],
)
def test_fixture_refresh_cli_rejections(argv: list[str], message: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="2"):
        generator.main(argv)
    assert message in capsys.readouterr().err


@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_fixture_native_cli_is_offline_and_prints_only_digest(
    retained_evidence_root, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_live(*args: object, **kwargs: object) -> object:
        pytest.fail("fixture-native CLI called the live reader")

    monkeypatch.setattr("socket.create_connection", fail_live)
    native_path = tmp_path / "native.parquet"
    exit_code = generator.main(
        [
            "--hydro-fixture",
            str(retained_evidence_root / _HYDRO_FULL_FIXTURE),
            "--temp-fixture",
            str(retained_evidence_root / _TEMP_FULL_FIXTURE),
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


@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_fixture_native_cli_rejects_census_error_without_writing(retained_evidence_root, tmp_path: Path) -> None:
    hydro = _full_payload(retained_evidence_root / _HYDRO_FULL_FIXTURE)
    hydro["data"] = hydro["data"][:5]
    hydro["count"] = 6454
    hydro_path = tmp_path / "truncated-hydrometry.json"
    hydro_path.write_text(json.dumps(hydro))
    native_path = tmp_path / "native.parquet"

    with pytest.raises(FatalContractError) as raised:
        generator.main(
            [
                "--hydro-fixture",
                str(hydro_path),
                "--temp-fixture",
                str(retained_evidence_root / _TEMP_FULL_FIXTURE),
                "--native-out",
                str(native_path),
                "--hydro-retrieved-at",
                "2026-08-02T17:32:58+00:00",
                "--temperature-retrieved-at",
                "2026-08-02T17:33:34+00:00",
            ]
        )

    assert [issue.message for issue in raised.value.issues] == [
        "fr_hubeau hydrometry response count 6454 does not match 5 rows"
    ]
    assert not native_path.exists()


@pytest.mark.governing(
    "maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet",
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_complete_native_table_is_source_faithful(retained_evidence_root) -> None:
    hydro = _full_payload(retained_evidence_root / _HYDRO_FULL_FIXTURE)
    temperature = _full_payload(retained_evidence_root / _TEMP_FULL_FIXTURE)
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

    committed = read_native_table(retained_evidence_root / NATIVE_PATH)
    pl_testing.assert_frame_equal(committed.data, frame, check_exact=True)
    assert native_table_content_digest(committed) == _PINNED_NATIVE_DIGEST
    assert native_table_content_digest(rematerialized.value) == _PINNED_NATIVE_DIGEST


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")
@pytest.mark.governing(
    "maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet",
    full_verification=("fr_hubeau",),
)
def test_native_dates_cannot_change_without_new_acquisition(retained_evidence_root) -> None:
    native = read_native_table(retained_evidence_root / NATIVE_PATH)
    hydro_first = native.data.filter(pl.col("source_endpoint") == "hydrometrie/referentiel/stations")["code_station"][0]
    changed = NativeTable(
        native.data.with_columns(
            pl.when(pl.col("source_endpoint") == "temperature/station")
            .then(pl.lit(datetime(2026, 8, 3, 0, 1, tzinfo=UTC)))
            .when(pl.col("code_station") == hydro_first)
            .then(pl.lit(datetime(2026, 8, 1, 23, 59, tzinfo=UTC)))
            .otherwise(pl.lit(datetime(2026, 8, 1, 0, 1, tzinfo=UTC)))
            .alias("retrieved_at")
        )
    )
    availability = _availability(retained_evidence_root)
    with pytest.raises(FatalContractError, match="native content does not match its acquisition identity"):
        build_catalogue(changed, FRANCE_ORIGIN_DECLARATIONS, availability)


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")
@pytest.mark.derived("src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet")
def test_committed_catalogue_preserves_source_controls_and_catalogue_consistency(retained_evidence_root) -> None:
    # Literal source controls are independent; shared builder checks establish consistency.
    native = read_native_table(retained_evidence_root / CURRENT_NATIVE_PATH).data
    catalogue_dir = Path(__file__).parents[1] / CURRENT_NATIVE_PATH.parent
    committed_products = pl.read_parquet(catalogue_dir / "products.parquet")
    committed_stations = pl.read_parquet(catalogue_dir / "stations.parquet")
    committed_station_products = pl.read_parquet(catalogue_dir / "station_products.parquet")
    committed_provider = json.loads((catalogue_dir / "provider.json").read_text())

    hydro = native.filter(pl.col("source_endpoint") == "hydrometrie/referentiel/stations")
    temperature = native.filter(pl.col("source_endpoint") == "temperature/station")
    expected_stations = pl.concat(
        [
            hydro.select(
                pl.lit("fr_hubeau").alias("provider_id"),
                pl.col("code_station").alias("station_id"),
                pl.when(pl.col("code_projection") == 31)
                .then(pl.col("longitude_station"))
                .otherwise(pl.col("latitude_station"))
                .alias("latitude"),
                pl.when(pl.col("code_projection") == 31)
                .then(pl.col("latitude_station"))
                .otherwise(pl.col("longitude_station"))
                .alias("longitude"),
                pl.lit("EPSG:4326").alias("crs"),
            ),
            temperature.select(
                pl.lit("fr_hubeau").alias("provider_id"),
                pl.col("code_station").alias("station_id"),
                "latitude",
                "longitude",
                pl.lit("EPSG:4326").alias("crs"),
            ),
        ]
    ).sort("station_id")
    pl_testing.assert_frame_equal(
        committed_stations,
        expected_stations,
        check_exact=True,
    )

    # Physical labels follow the retained API definitions, not a second generator declaration.
    expected_products = pl.DataFrame(
        [
            ("fr_hubeau", "discharge_daily_mean", "discharge", "daily", "mean", "interval", "unknown", "m3/s", "QmnJ"),
            ("fr_hubeau", "discharge_daily_max", "discharge", "daily", "max", "unknown", "unknown", "m3/s", "QIXnJ"),
            ("fr_hubeau", "stage_daily_max", "stage", "daily", "max", "unknown", "unknown", "m", "HIXnJ"),
            (
                "fr_hubeau",
                "water_temperature_reported",
                "water_temperature",
                "unknown",
                "unknown",
                "unknown",
                "unknown",
                "degC",
                "temperature",
            ),
        ],
        schema=PRODUCT_CATALOG_SCHEMA.polars_schema,
        orient="row",
    ).sort("product_id")
    pl_testing.assert_frame_equal(committed_products, expected_products, check_exact=True)

    expected_pairs = {
        (row[0], d.product_id) for row in hydro.select("code_station").iter_rows() for d in HYDRO_PRODUCT_DEFS
    }
    expected_pairs.update(
        (row[0], d.product_id) for row in temperature.select("code_station").iter_rows() for d in TEMP_PRODUCT_DEFS
    )
    assert set(committed_station_products.select("station_id", "product_id").iter_rows()) == expected_pairs
    projected = generator.hubeau_availability(
        _availability(retained_evidence_root), expected_pairs, NativeTable(native)
    )
    pl_testing.assert_frame_equal(committed_station_products, generator.build_station_products(projected))
    assert committed_station_products["published_record_start_date"].null_count() == len(expected_pairs)
    assert committed_station_products["published_record_end_date"].null_count() == len(expected_pairs)
    assert committed_provider == generator.build_provider_info(native["retrieved_at"].max().date())


def test_source_response_rebuild_requires_explicit_reviewed_ledger(tmp_path):
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rivretrieve._internal.providers.fr_hubeau.rebuild_catalogue",
            "--evidence-root",
            str(tmp_path / "inputs"),
            "--build-inputs",
            str(tmp_path / "build-inputs.json"),
            "--out",
            str(tmp_path / "output"),
            "--capture-output",
            str(tmp_path / "capture.json"),
            "--revision",
            "a" * 40,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "--availability-ledger" in result.stderr
    assert not (tmp_path / "output").exists()


@pytest.mark.governing(
    *_catalogue_recording_paths("fr_hubeau"),
    "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet",
    "maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz",
    "maintenance/catalogue/fr_hubeau/inventory/native_capture.json",
    "maintenance/catalogue/fr_hubeau/inventory/hydrometry-stations-2026-09-21.json.xz",
    "maintenance/catalogue/fr_hubeau/inventory/temperature-stations-2026-09-21.json.xz",
    "maintenance/catalogue/fr_hubeau/inventory/hydrometry-stations-2026-09-21.receipt.json",
    "maintenance/catalogue/fr_hubeau/inventory/temperature-stations-2026-09-21.receipt.json",
    full_verification=("fr_hubeau",),
)
def test_retained_station_responses_rebuild_exact_native_capture(
    retained_evidence_root, catalogue_build_inputs, tmp_path, monkeypatch
):
    """Source-response materialization is separate from the shared native-table build."""
    from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import NativeInventoryCapture
    from rivretrieve._internal.providers.fr_hubeau.rebuild_catalogue import rebuild
    from rivretrieve._internal.transport import HttpClient

    def offline(*args, **kwargs):
        pytest.fail("Retained source-response rebuild attempted network access")

    monkeypatch.setattr(HttpClient, "send", offline)
    inventory = retained_evidence_root / "maintenance/catalogue/fr_hubeau/inventory"
    capture = NativeInventoryCapture.model_validate_json((inventory / "native_capture.json").read_bytes())
    native = read_native_table(retained_evidence_root / CURRENT_NATIVE_PATH)
    catalogue = build_catalogue(
        native, FRANCE_ORIGIN_DECLARATIONS, _availability(retained_evidence_root), native_capture=capture
    )
    selected = catalogue_build_inputs(catalogue.acquisition_provenance)
    output = tmp_path / "catalogue"
    capture_output = tmp_path / "native_capture.json"
    rebuild(
        retained_evidence_root,
        inventory / "governing_evidence.json.xz",
        output,
        capture_output,
        capture.native_table.revision,
        build_inputs=selected,
    )
    assert (output / "native.parquet").read_bytes() == (retained_evidence_root / CURRENT_NATIVE_PATH).read_bytes()
    assert NativeInventoryCapture.model_validate_json(capture_output.read_bytes()) == capture
    approved = Path(__file__).parents[1] / CURRENT_NATIVE_PATH.parent
    for name in ("stations.parquet", "products.parquet", "station_products.parquet", "station_metadata.parquet"):
        pl_testing.assert_frame_equal(pl.read_parquet(output / name), pl.read_parquet(approved / name))
