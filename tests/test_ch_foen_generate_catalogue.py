from __future__ import annotations

import copy
import hashlib
import io
import json
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import cast

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogue_origins import (
    Authored,
    AuthoredValue,
    Evidence,
    Field,
    FieldTransform,
    NativeColumn,
    NotPublished,
)
from rivretrieve._internal.catalogues.artifact import packaged_catalogue_artifact_from_components
from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, read_native_table
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
    validate_catalogue,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ch_foen import generate_catalogue
from rivretrieve._internal.providers.ch_foen.origins import build_acquisition_provenance

FIXTURE_PATH = Path("tests/test_data/switzerland_metadata_locations.json")
NATIVE_PATH = Path("src/rivretrieve/_internal/providers/ch_foen/catalogue/native.parquet")
CATALOGUE_PATH = NATIVE_PATH.parent
ATTESTED_DATETIME = datetime(2026, 8, 2, 0, 14, 31, tzinfo=UTC)
ATTESTED_RETRIEVED_AT = RetrievedAt(ATTESTED_DATETIME)
ATTESTED_DIGEST = "7471e85de4f4a6d1e0968a9fe35a962c98729a4bb3b244e0991818f3038ce24a"
NATIVE_FRAME_DIGEST = "5ceb95706d653ca3cf18632156cccea54b768712cd2e7d81b32876a11f62426a"
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
ENVELOPE = {
    "source": "Swiss Federal Office for the Environment FOEN / BAFU, Hydrology",
    "apiurl": "https://api.existenz.ch#hydro",
    "opendata": "https://opendata.swiss/en/dataset/wassertemperatur-der-flusse",
    "license": (
        "https://www.bafu.admin.ch/dam/bafu/de/dokumente/wasser/fachinfo-daten/"
        "liefer-nutzungsbedingungen-hydrologische-daten.pdf.download.pdf/"
        "Liefer-%20und%20Nutzungsbedingungen%20hydrologische%20Daten%20BAFU%202020.pdf"
    ),
}

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


def test_publisher_crs_evidence_names_hydro_but_no_reference_system() -> None:
    capture = CRS_EVIDENCE_PATH.read_bytes()
    parser = _TextParser()
    parser.feed(capture.decode("utf-8"))
    text = " ".join(" ".join(parser.parts).split()).casefold()

    assert len(capture) == 15_737
    assert hashlib.sha256(capture).hexdigest() == ("488b25d24651aafb520d7cf69c1d36ac9f4384fa096b9cab77b44c6b669f82df")
    assert text
    assert "hydro" in text
    assert all(token.casefold() not in text for token in CRS_ABSENCE_TOKENS)


def _fixture_response() -> dict[str, object]:
    value = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast("dict[str, object]", value)


def _expected_native_frame(response: dict[str, object] | None = None) -> pl.DataFrame:
    source = _fixture_response() if response is None else response
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
        pl.DataFrame(rows, schema=generate_catalogue.NATIVE_SOURCE_SCHEMA)
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


def _native_with_rows(rows: list[dict[str, object]]) -> NativeTable:
    return NativeTable(pl.DataFrame(rows, schema=NATIVE_SCHEMA))


def _sample_native_rows() -> list[dict[str, object]]:
    committed = read_native_table(NATIVE_PATH).data
    return [dict(row) for row in committed.head(2).iter_rows(named=True)]


def _json_objects(values: pl.Series) -> list[dict[str, object]]:
    decoded = [json.loads(value) for value in values]
    assert all(isinstance(value, dict) for value in decoded)
    return decoded


class _FixtureResponse(io.BytesIO):
    status = 200


def test_swiss_fixture_matches_attested_complete_response() -> None:
    response = _fixture_response()
    canonical = json.dumps(response, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    payload = response["payload"]

    assert isinstance(payload, dict)
    assert len(payload) == 246
    assert hashlib.sha256(canonical).hexdigest() == ATTESTED_DIGEST
    assert set(response) == {"source", "apiurl", "opendata", "license", "payload"}


def test_refresh_native_table_has_exact_ordered_schema_and_preserves_source() -> None:
    outcome = generate_catalogue.refresh_native_table(_fixture_response(), retrieved_at=ATTESTED_RETRIEVED_AT)

    assert outcome.value.data.schema == NATIVE_SCHEMA
    assert outcome.issues == ()
    pl_testing.assert_frame_equal(outcome.value.data, _expected_native_frame(), check_exact=True)


def test_refresh_native_table_normalizes_only_integer_details_id() -> None:
    response = _fixture_response()
    payload_value = response["payload"]
    assert isinstance(payload_value, dict)
    payload = cast("dict[str, object]", payload_value)
    integer_detail_ids: list[str] = []
    for payload_key, station_value in payload.items():
        assert isinstance(station_value, dict)
        station = cast("dict[str, object]", station_value)
        details_value = station["details"]
        assert isinstance(details_value, dict)
        details = cast("dict[str, object]", details_value)
        if type(details["id"]) is int:
            integer_detail_ids.append(payload_key)

    table = generate_catalogue.refresh_native_table(response, retrieved_at=ATTESTED_RETRIEVED_AT).value.data

    station_2071_value = payload["2071"]
    assert isinstance(station_2071_value, dict)
    station_2071 = cast("dict[str, object]", station_2071_value)
    details_2071_value = station_2071["details"]
    assert isinstance(details_2071_value, dict)
    details_2071 = cast("dict[str, object]", details_2071_value)
    assert integer_detail_ids == ["2071"]
    assert details_2071["id"] == 2071
    assert table.schema["details.id"] == pl.String
    assert table.filter(pl.col("payload_key") == "2071").select("details.id").item() == "2071"


def test_refresh_native_table_stamps_all_rows_with_attested_retrieval_instant() -> None:
    table = generate_catalogue.refresh_native_table(_fixture_response(), retrieved_at=ATTESTED_RETRIEVED_AT).value.data

    assert table.height == 246
    assert table["retrieved_at"].n_unique() == 1
    assert table["retrieved_at"].item(0) == ATTESTED_DATETIME


def test_refresh_native_table_from_fixture_is_network_free(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        generate_catalogue,
        "_read_live_json",
        lambda url: (_ for _ in ()).throw(AssertionError(f"unexpected live request to {url}")),
    )

    outcome = generate_catalogue.refresh_native_table_from_fixture(FIXTURE_PATH, retrieved_at=ATTESTED_RETRIEVED_AT)

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


def test_live_refresh_rejects_implausibly_small_station_count(monkeypatch: pytest.MonkeyPatch) -> None:
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

    outcome = generate_catalogue.refresh_native_table_from_fixture(fixture_path, retrieved_at=ATTESTED_RETRIEVED_AT)

    assert outcome.value.data.height == 1


@pytest.mark.parametrize(
    ("scope", "field"),
    [
        *(("envelope", field) for field in ("source", "apiurl", "opendata", "license")),
        *(("station", field) for field in ("id", "name", "details")),
        *(
            ("details", field)
            for field in ("id", "name", "water-body-name", "water-body-type", "chx", "chy", "lat", "lon")
        ),
    ],
)
def test_refresh_native_table_rejects_each_absent_required_field(scope: str, field: str) -> None:
    response = copy.deepcopy(_fixture_response())
    payload_value = response["payload"]
    assert isinstance(payload_value, dict)
    payload = cast("dict[str, object]", payload_value)
    station_value = payload["2004"]
    assert isinstance(station_value, dict)
    station = cast("dict[str, object]", station_value)
    details_value = station["details"]
    assert isinstance(details_value, dict)
    details = cast("dict[str, object]", details_value)
    target: dict[str, object] = response if scope == "envelope" else station if scope == "station" else details
    target.pop(field)

    with pytest.raises(FatalContractError, match=field):
        generate_catalogue.refresh_native_table(response, retrieved_at=ATTESTED_RETRIEVED_AT)


@pytest.mark.parametrize(
    ("scope", "field"),
    [("station", "id"), ("details", "chx"), ("details", "chy"), ("details", "lat"), ("details", "lon")],
)
def test_refresh_native_table_rejects_boolean_numeric_fields(scope: str, field: str) -> None:
    response = copy.deepcopy(_fixture_response())
    payload_value = response["payload"]
    assert isinstance(payload_value, dict)
    payload = cast("dict[str, object]", payload_value)
    station_value = payload["2004"]
    assert isinstance(station_value, dict)
    station = cast("dict[str, object]", station_value)
    details_value = station["details"]
    assert isinstance(details_value, dict)
    details = cast("dict[str, object]", details_value)
    target: dict[str, object] = station if scope == "station" else details
    target[field] = True

    with pytest.raises(FatalContractError, match=field):
        generate_catalogue.refresh_native_table(response, retrieved_at=ATTESTED_RETRIEVED_AT)


def test_native_output_cli_writes_expected_table(tmp_path: Path) -> None:
    output_path = tmp_path / "native.parquet"

    result = generate_catalogue.main(
        ["--fixture", str(FIXTURE_PATH), "--native-out", str(output_path), "--retrieved-at", "2026-08-02T00:14:31Z"]
    )

    assert result == 0
    pl_testing.assert_frame_equal(read_native_table(output_path).data, _expected_native_frame(), check_exact=True)


def test_committed_native_table_matches_attested_rematerialization() -> None:
    committed = read_native_table(NATIVE_PATH).data

    assert committed.schema == NATIVE_SCHEMA
    pl_testing.assert_frame_equal(committed, _expected_native_frame(), check_exact=True)


def test_committed_native_table_has_pinned_full_content() -> None:
    committed = read_native_table(NATIVE_PATH).data

    assert committed.height == 246
    assert committed.columns == list(NATIVE_SCHEMA)
    assert _canonical_native_digest(committed) == NATIVE_FRAME_DIGEST


def test_swiss_origins_match_canonical_schema_order_and_values() -> None:
    from rivretrieve._internal.providers.ch_foen.origins import STATION_CATALOGUE_ORIGINS

    assert tuple(STATION_CATALOGUE_ORIGINS) == tuple(column.name for column in STATION_CATALOG_SCHEMA.columns)
    assert {
        "provider_id": Authored(AuthoredValue("ch_foen")),
        "station_id": Field(NativeColumn("name")),
        "latitude": Field(NativeColumn("details.lat"), FieldTransform.FLOAT),
        "longitude": Field(NativeColumn("details.lon"), FieldTransform.FLOAT),
        "crs": NotPublished(Evidence("https://api.existenz.ch/#hydro")),
    } == STATION_CATALOGUE_ORIGINS


def test_native_build_has_exact_projection_counts_dates_and_schemas() -> None:
    from rivretrieve._internal.providers.ch_foen.origins import STATION_CATALOGUE_ORIGINS

    catalogue = generate_catalogue.build_catalogue(read_native_table(NATIVE_PATH), STATION_CATALOGUE_ORIGINS)

    retained_product_ids = {
        "discharge_reported",
        "stage_reported",
        "water_temperature_reported",
    }
    withdrawn_product_ids = {
        "discharge_daily_mean",
        "stage_daily_mean",
        "water_temperature_daily_mean",
    }

    assert catalogue.stations.height == 246
    assert catalogue.products.height == 3
    assert set(catalogue.products["product_id"]) == retained_product_ids
    assert set(catalogue.products["product_id"]).isdisjoint(withdrawn_product_ids)
    for column in ("frequency", "statistic", "period_type", "period_anchor"):
        assert set(catalogue.products[column]) == {"unknown"}
    assert catalogue.station_products.height == 738
    assert set(catalogue.station_products["product_id"]) == retained_product_ids
    assert set(catalogue.station_products["product_id"]).isdisjoint(withdrawn_product_ids)
    assert catalogue.station_products.group_by("product_id").len().sort("product_id").rows() == [
        ("discharge_reported", 246),
        ("stage_reported", 246),
        ("water_temperature_reported", 246),
    ]
    assert set(catalogue.stations["crs"]) == {"unknown"}
    assert catalogue.provider_info["catalogue_version"] == "2026-08-02"
    assert set(catalogue.station_products["last_catalogue_check"]) == {date(2026, 8, 2)}
    assert set(catalogue.station_products["provider_id"]) == {"ch_foen"}
    assert set(catalogue.station_products["availability"].cast(str)) == {"unknown"}
    assert set(catalogue.station_products["availability_reason"]) == {
        "Existenz.ch locations catalogue does not expose per-variable station availability"
    }
    assert catalogue.station_products["published_record_start_date"].null_count() == 738
    assert catalogue.station_products["published_record_end_date"].null_count() == 738
    assert set(catalogue.station_products["station_id"]) == set(catalogue.stations["station_id"])
    assert catalogue.station_products.group_by("station_id").len()["len"].unique().to_list() == [3]
    provider_frame = pl.DataFrame([catalogue.provider_info], schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema)
    validate_catalogue(provider_frame, PROVIDER_INFO_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(catalogue.products, PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(catalogue.stations, STATION_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(catalogue.station_products, STATION_PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    packaged_catalogue_artifact_from_components(
        catalogue.provider_info,
        catalogue.products,
        catalogue.stations,
        catalogue.station_products,
        acquisition_provenance=build_acquisition_provenance(),
        on_issue="raise",
    )


def test_native_build_uses_top_level_name_and_exact_native_coordinates() -> None:
    from rivretrieve._internal.providers.ch_foen.origins import STATION_CATALOGUE_ORIGINS

    rows = _sample_native_rows()
    rows[0].update(
        {
            "payload_key": "payload-A",
            "id": 11,
            "name": "canonical-A",
            "details.id": "detail-A",
            "details.lat": 46.123456789,
            "details.lon": 7.987654321,
        }
    )
    rows[1].update(
        {
            "payload_key": "payload-B",
            "id": 22,
            "name": "canonical-B",
            "details.id": "detail-B",
            "details.lat": 47.000000001,
            "details.lon": 8.000000001,
        }
    )
    native = _native_with_rows(rows)

    actual = generate_catalogue.build_catalogue(native, STATION_CATALOGUE_ORIGINS).stations
    expected = native.data.select(
        pl.lit("ch_foen").cast(pl.String).alias("provider_id"),
        pl.col("name").cast(pl.String).alias("station_id"),
        pl.col("details.lat").cast(pl.Float64).alias("latitude"),
        pl.col("details.lon").cast(pl.Float64).alias("longitude"),
        pl.lit("unknown").cast(pl.String).alias("crs"),
    ).sort("station_id")

    pl_testing.assert_frame_equal(actual, expected, check_exact=True)
    assert actual["station_id"].to_list() == ["canonical-A", "canonical-B"]


def test_native_build_enforces_every_origin_declaration() -> None:
    from rivretrieve._internal.providers.ch_foen.origins import STATION_CATALOGUE_ORIGINS

    declarations = dict(STATION_CATALOGUE_ORIGINS)
    del declarations["longitude"]

    with pytest.raises(
        FatalContractError,
        match=r"ch_foen\.longitude: canonical column has no origin declaration",
    ):
        generate_catalogue.build_catalogue(read_native_table(NATIVE_PATH), declarations)


def test_native_build_uses_per_station_retrieval_dates_and_maximum_provider_date() -> None:
    from rivretrieve._internal.providers.ch_foen.origins import STATION_CATALOGUE_ORIGINS

    rows = _sample_native_rows()
    rows[0]["retrieved_at"] = datetime(2026, 7, 31, 23, 59, tzinfo=UTC)
    rows[1]["retrieved_at"] = datetime(2026, 8, 2, 1, 2, tzinfo=UTC)
    native = _native_with_rows(rows)

    catalogue = generate_catalogue.build_catalogue(native, STATION_CATALOGUE_ORIGINS)

    station_dates = {
        station_id: set(group["last_catalogue_check"])
        for (station_id,), group in catalogue.station_products.group_by("station_id", maintain_order=True)
    }
    assert station_dates == {rows[0]["name"]: {date(2026, 7, 31)}, rows[1]["name"]: {date(2026, 8, 2)}}
    assert catalogue.provider_info["catalogue_version"] == "2026-08-02"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda rows: rows[1].__setitem__("name", None), r"name"),
        (lambda rows: rows[1].__setitem__("name", ""), r"name"),
        (lambda rows: rows[1].__setitem__("details.lat", None), r"details\.lat"),
        (lambda rows: rows[1].__setitem__("details.lon", None), r"details\.lon"),
        (lambda rows: rows[1].__setitem__("name", rows[0]["name"]), r"duplicate station identity"),
    ],
)
def test_native_build_rejects_bad_station_rows(mutation, message: str) -> None:
    from rivretrieve._internal.providers.ch_foen.origins import STATION_CATALOGUE_ORIGINS

    rows = _sample_native_rows()
    bad_payload_key = rows[1]["payload_key"]
    mutation(rows)
    native = object.__new__(NativeTable)
    object.__setattr__(native, "data", pl.DataFrame(rows, schema=NATIVE_SCHEMA, strict=False))

    with pytest.raises(FatalContractError, match=rf"payload_key {bad_payload_key}.*{message}"):
        generate_catalogue.build_catalogue(native, STATION_CATALOGUE_ORIGINS)


@pytest.mark.parametrize("payload_key", [None, ""])
def test_native_build_rejects_invalid_payload_key(payload_key: object) -> None:
    from rivretrieve._internal.providers.ch_foen.origins import STATION_CATALOGUE_ORIGINS

    rows = _sample_native_rows()
    rows[1]["payload_key"] = payload_key
    native = object.__new__(NativeTable)
    object.__setattr__(native, "data", pl.DataFrame(rows, schema=NATIVE_SCHEMA, strict=False))

    with pytest.raises(FatalContractError, match="Swiss native table row has invalid payload_key"):
        generate_catalogue.build_catalogue(native, STATION_CATALOGUE_ORIGINS)


def test_native_build_rejects_empty_table() -> None:
    from rivretrieve._internal.providers.ch_foen.origins import STATION_CATALOGUE_ORIGINS

    native = NativeTable(pl.DataFrame(schema=NATIVE_SCHEMA))

    with pytest.raises(FatalContractError, match="Swiss native table must not be empty"):
        generate_catalogue.build_catalogue(native, STATION_CATALOGUE_ORIGINS)


def test_native_build_rejects_null_retrieved_at_with_row_identity() -> None:
    from rivretrieve._internal.providers.ch_foen.origins import STATION_CATALOGUE_ORIGINS

    rows = _sample_native_rows()
    bad_payload_key = rows[1]["payload_key"]
    rows[1]["retrieved_at"] = None
    native = object.__new__(NativeTable)
    object.__setattr__(native, "data", pl.DataFrame(rows, schema=NATIVE_SCHEMA))

    with pytest.raises(FatalContractError, match=rf"{bad_payload_key}.*retrieved_at"):
        generate_catalogue.build_catalogue(native, STATION_CATALOGUE_ORIGINS)


def test_native_build_rejects_inconsistent_document_metadata() -> None:
    from rivretrieve._internal.providers.ch_foen.origins import STATION_CATALOGUE_ORIGINS

    rows = _sample_native_rows()
    bad_payload_key = rows[1]["payload_key"]
    rows[1]["source"] = "different source"

    with pytest.raises(FatalContractError, match=rf"{bad_payload_key}.*source"):
        generate_catalogue.build_catalogue(_native_with_rows(rows), STATION_CATALOGUE_ORIGINS)


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--fixture", str(FIXTURE_PATH), "--out", "catalogue"], "--out requires --native"),
        (["--live", "--out", "catalogue"], "--out requires --native"),
        (["--native", str(NATIVE_PATH), "--native-out", "native.parquet"], "--native cannot be used with --native-out"),
        (
            ["--fixture", str(FIXTURE_PATH), "--native-out", "native.parquet"],
            "--retrieved-at is required with --native-out",
        ),
        (
            ["--native", str(NATIVE_PATH), "--out", "catalogue", "--retrieved-at", "2026-08-02T00:14:31Z"],
            "--retrieved-at is only valid with refresh mode",
        ),
    ],
)
def test_cli_rejects_cross_mode_combinations(argv: list[str], message: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        generate_catalogue.main(argv)

    assert exc_info.value.code != 0
    assert message in capsys.readouterr().err


def test_cli_source_modes_are_mutually_exclusive(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        generate_catalogue.main(
            [
                "--fixture",
                str(FIXTURE_PATH),
                "--live",
                "--native-out",
                str(tmp_path / "native.parquet"),
                "--retrieved-at",
                "2026-08-02T00:14:31Z",
            ]
        )

    assert exc_info.value.code != 0


def test_native_build_matches_committed_catalogue_byte_for_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    native_before = NATIVE_PATH.read_bytes()

    def fail_network(*args, **kwargs):
        calls.append(str(args[0]) if args else "unknown")
        raise AssertionError("network call during native build")

    monkeypatch.setattr(generate_catalogue, "_read_live_json", fail_network)
    monkeypatch.setattr(generate_catalogue.urllib.request, "urlopen", fail_network)
    output = tmp_path / "catalogue"

    assert generate_catalogue.main(["--native", str(NATIVE_PATH), "--out", str(output)]) == 0
    assert calls == []
    assert NATIVE_PATH.read_bytes() == native_before
    for artifact in ("provider.json", "products.parquet", "stations.parquet", "station_products.parquet"):
        assert (output / artifact).read_bytes() == (CATALOGUE_PATH / artifact).read_bytes()
