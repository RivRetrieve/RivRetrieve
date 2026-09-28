from __future__ import annotations

import copy
import hashlib
import json
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest
from pydantic import TypeAdapter

from rivretrieve._internal.catalogue_origins import Evidence, NotPublished
from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, read_native_table
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ba_fhmzbih import generate_catalogue
from rivretrieve._internal.providers.ba_fhmzbih.origins import WorkbookAccessLedger

_TEST_DATA_DIR = Path(__file__).parent / "test_data"
_METADATA_FIXTURE = _TEST_DATA_DIR / "ba_fhmzbih_metadata.json"
_NATIVE_TABLE = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet"
_LEDGER = Path(__file__).parents[1] / "maintenance/catalogue/ba_fhmzbih/inventory/baseline_workbook_access.json"
_CATALOGUE_DIR = _NATIVE_TABLE.parent
_CRS_EVIDENCE = _TEST_DATA_DIR / "ba_fhmzbih_crs_evidence_stations.json"
_RETRIEVED_AT = RetrievedAt(datetime(2026, 8, 2, 12, 42, 3, tzinfo=UTC))
_METADATA_COLUMNS = (
    "metadata_CATCHMENT_SIZE",
    "metadata_WTO_OBJECT",
    "metadata_catchment_name",
    "metadata_object_type",
    "metadata_river_name",
    "metadata_site_name",
    "metadata_site_no",
    "metadata_station_carteasting",
    "metadata_station_cartnorthing",
    "metadata_station_elevation",
    "metadata_station_id",
    "metadata_station_latitude",
    "metadata_station_local_x",
    "metadata_station_local_y",
    "metadata_station_longitude",
    "metadata_station_longname",
    "metadata_station_name",
    "metadata_station_no",
)
_VOLATILE_COLUMNS = (
    "L1_label",
    "L1_req_timestamp",
    "L1_station_longname",
    "L1_stationparameter_name",
    "L1_stationparameter_no",
    "L1_timestamp",
    "L1_ts_id",
    "L1_ts_name",
    "L1_ts_precision",
    "L1_ts_unitsymbol",
    "L1_ts_value",
    "L1_web_flow_class",
)
_EXPECTED_NATIVE_SCHEMA = pl.Schema(
    {
        **dict.fromkeys(_METADATA_COLUMNS, pl.String),
        "retrieved_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    }
)


def _fixture_payload() -> list[object]:
    return json.loads(_METADATA_FIXTURE.read_text(encoding="utf-8"))


def _assert_materialization_issue(
    payload: object,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    *,
    code: str,
    message: str,
    input_kind: object | None = None,
) -> None:
    native_out = tmp_path / "native.parquet"
    outcome = generate_catalogue.materialize_native_table(
        payload,
        native_out,
        retrieved_at=_RETRIEVED_AT,
        input_kind=input_kind or generate_catalogue.RefreshInputKind.FIXTURE,
    )
    assert len(outcome.issues) == 1
    issue = outcome.issues[0]
    assert issue.severity == "error"
    assert issue.code == code
    assert issue.message == message
    assert not native_out.exists()
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def _origins():
    from rivretrieve._internal.providers.ba_fhmzbih.origins import STATION_CATALOGUE_ORIGINS

    return STATION_CATALOGUE_ORIGINS


def _access():
    return TypeAdapter(WorkbookAccessLedger).validate_json(_LEDGER.read_bytes())


def _catalogue():
    return generate_catalogue.build_catalogue(read_native_table(_NATIVE_TABLE), _origins(), _access())


def _json_objects(values: pl.Series) -> list[dict[str, object]]:
    objects = [json.loads(value) for value in values]
    assert all(isinstance(value, dict) for value in objects)
    return objects


def _frame_content_digest(frame: pl.DataFrame) -> str:
    def canonical_value(value: object) -> object:
        if isinstance(value, datetime):
            return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
        if isinstance(value, date):
            return value.isoformat()
        return value

    payload = {
        "columns": frame.columns,
        "rows": [[canonical_value(value) for value in row] for row in frame.iter_rows()],
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def test_native_build_has_exact_counts_dates_and_schemas() -> None:
    catalogue = _catalogue()

    assert (catalogue.stations.height, catalogue.products.height, catalogue.station_products.height) == (60, 3, 180)
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
    assert set(catalogue.products["product_id"]) == retained_product_ids
    assert set(catalogue.station_products["product_id"]) == retained_product_ids
    assert set(catalogue.products["product_id"]).isdisjoint(withdrawn_product_ids)
    assert set(catalogue.station_products["product_id"]).isdisjoint(withdrawn_product_ids)
    assert catalogue.provider_info["catalogue_version"] == "2026-08-02"
    assert set(catalogue.station_products["last_catalogue_check"]) == {
        date(2026, 9, 2),
        date(2026, 9, 7),
        date(2026, 9, 9),
        date(2026, 9, 13),
    }
    assert catalogue.stations.schema == STATION_CATALOG_SCHEMA.polars_schema
    assert catalogue.products.schema == PRODUCT_CATALOG_SCHEMA.polars_schema
    assert catalogue.station_products.schema == STATION_PRODUCT_CATALOG_SCHEMA.polars_schema
    assert pl.DataFrame([catalogue.provider_info], schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema).schema == (
        PROVIDER_INFO_CATALOG_SCHEMA.polars_schema
    )


def test_native_build_is_exact_source_projection_and_preserves_native_material() -> None:
    native = read_native_table(_NATIVE_TABLE)
    actual = generate_catalogue.build_catalogue(native, _origins(), _access()).stations
    expected = native.data.select(
        pl.lit("ba_fhmzbih").cast(pl.String).alias("provider_id"),
        pl.col("metadata_station_no").cast(pl.String).alias("station_id"),
        pl.col("metadata_station_latitude").cast(pl.Float64, strict=True).alias("latitude"),
        pl.col("metadata_station_longitude").cast(pl.Float64, strict=True).alias("longitude"),
        pl.lit("unknown").cast(pl.String).alias("crs"),
    ).sort("station_id")
    pl_testing.assert_frame_equal(actual, expected, check_exact=True)

    source = native.data.filter(pl.col("metadata_station_no") == "4510")
    canonical = actual.filter(pl.col("station_id") == "4510")
    assert source["metadata_station_id"].item() == "12191"
    assert source["metadata_station_no"].item() != source["metadata_station_id"].item()
    assert source["metadata_station_latitude"].item() == "44.64680728070949"
    assert source["metadata_station_longitude"].item() == "17.90406242892678"
    assert canonical.row(0, named=True) == {
        "provider_id": "ba_fhmzbih",
        "station_id": "4510",
        "latitude": 44.64680728070949,
        "longitude": 17.90406242892678,
        "crs": "unknown",
    }
    assert source.select(
        "metadata_station_name",
        "metadata_station_longname",
        "metadata_river_name",
        "metadata_catchment_name",
        "metadata_station_elevation",
        "metadata_station_carteasting",
        "metadata_station_cartnorthing",
        "metadata_station_local_x",
        "metadata_station_local_y",
        "retrieved_at",
    ).row(0, named=True) == {
        "metadata_station_name": "HS Kaloševići",
        "metadata_station_longname": "PODRUČJA NA SLIVU RIJEKE BOSNE",
        "metadata_river_name": "Usora",
        "metadata_catchment_name": "Bosna",
        "metadata_station_elevation": "",
        "metadata_station_carteasting": "6492481.45",
        "metadata_station_cartnorthing": "4944707.34",
        "metadata_station_local_x": "6492481.45",
        "metadata_station_local_y": "4944707.34",
        "retrieved_at": _RETRIEVED_AT.value,
    }


def test_publisher_capture_and_attestation_support_not_published_crs() -> None:
    crs_origin = _origins()["crs"]
    assert crs_origin == NotPublished(Evidence("https://vodostaji.voda.ba/data/internet/stations/stations.json"))
    assert isinstance(crs_origin, NotPublished)
    document = json.loads(_CRS_EVIDENCE.read_text(encoding="utf-8"))
    assert isinstance(document, list) and len(document) == 230
    keysets = {frozenset(row) for row in document}
    assert len(keysets) == 1 and len(next(iter(keysets))) == 24
    coordinate_fields = {
        "station_latitude",
        "station_longitude",
        "station_carteasting",
        "station_cartnorthing",
        "station_local_x",
        "station_local_y",
    }
    assert coordinate_fields <= next(iter(keysets))
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == "c78bd3b3aee2859eaef3c4373029fe7619a7d8e40b53fa0eab7f989ade3524bc"
    searchable = canonical.decode().lower()
    assert all(token not in searchable for token in ("epsg", "wgs", "4326", "projection", "srid"))
    for field, minimum, maximum in (
        ("station_gauge_datum", 74.36, 999.99),
        ("GAUGE_DATUM", 74.36, 999.99),
        ("GWREF_DATUM", 85.36, 514.98),
    ):
        values = [float(row[field]) for row in document if row[field] != ""]
        assert values and min(values) == minimum and max(values) == maximum


def test_committed_canonical_artifact_content_digests_are_pinned() -> None:
    assert hashlib.sha256((_CATALOGUE_DIR / "provider.json").read_bytes()).hexdigest() == (
        "8318095cfc19d2fa67dece6c2ce2a0313032870ffa9c290fc8ec9dae110382be"
    )
    assert _frame_content_digest(pl.read_parquet(_CATALOGUE_DIR / "products.parquet")) == (
        "6f4c7541f4bfd4bef499fb29e4ac83ca8c32196dba4dd92f812e850ea65a1a6b"
    )
    assert _frame_content_digest(pl.read_parquet(_CATALOGUE_DIR / "stations.parquet")) == (
        "761a93315a093b1cad5a4ce1e0480a6e36430a32d28467c9fe689f0257c053a4"
    )
    assert _frame_content_digest(pl.read_parquet(_CATALOGUE_DIR / "station_products.parquet")) == (
        "28edacb26f29db827d746eef084c53592f7c33e2a93f018a9297aba08296a51b"
    )


def test_native_build_enforces_origins_before_writing(tmp_path: Path) -> None:
    broken = dict(_origins())
    del broken["longitude"]
    with pytest.raises(FatalContractError, match=r"ba_fhmzbih\.longitude: canonical column has no origin declaration"):
        generate_catalogue.build_catalogue(read_native_table(_NATIVE_TABLE), broken, _access())
    assert list(tmp_path.iterdir()) == []


def test_native_build_rejects_empty_and_malformed_retrieval_timestamps() -> None:
    native = read_native_table(_NATIVE_TABLE)
    with pytest.raises(FatalContractError, match="native table must not be empty"):
        generate_catalogue.build_catalogue(NativeTable(native.data.clear()), _origins(), _access())
    malformed = object.__new__(NativeTable)
    object.__setattr__(
        malformed,
        "data",
        native.data.with_columns(pl.lit(None).cast(pl.Datetime("us", "UTC")).alias("retrieved_at")),
    )
    with pytest.raises(FatalContractError, match="retrieved_at"):
        generate_catalogue.build_catalogue(malformed, _origins(), _access())


def test_native_build_uses_workbook_dates_and_maximum_metadata_provider_date() -> None:
    native = read_native_table(_NATIVE_TABLE)
    mixed = native.data.head(2).with_columns(
        pl.Series(
            "retrieved_at",
            [datetime(2026, 7, 31, 23, 59, tzinfo=UTC), datetime(2026, 8, 2, 1, 2, tzinfo=UTC)],
            dtype=pl.Datetime("us", "UTC"),
        )
    )
    catalogue = generate_catalogue.build_catalogue(
        NativeTable(mixed),
        _origins(),
        TypeAdapter(WorkbookAccessLedger).validate_python(
            {
                **json.loads(_LEDGER.read_bytes()),
                "pairs": [
                    pair
                    for pair in json.loads(_LEDGER.read_bytes())["pairs"]
                    if pair["station_no"] in mixed["metadata_station_no"]
                ],
            }
        ),
    )
    station_dates = {
        station_id: set(group["last_catalogue_check"])
        for (station_id,), group in catalogue.station_products.group_by("station_id", maintain_order=True)
    }
    assert station_dates == {
        mixed["metadata_station_no"].item(0): {date(2026, 9, 9), date(2026, 9, 13)},
        mixed["metadata_station_no"].item(1): {date(2026, 9, 7), date(2026, 9, 13)},
    }
    assert catalogue.provider_info["catalogue_version"] == "2026-08-02"


def test_fixture_digest_is_pinned() -> None:
    payload = _fixture_payload()
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert hashlib.sha256(encoded).hexdigest() == "f607055b8abb079649aab739f7b54fd171de91f508efbae793bbd28bd1e933c1"


def test_refresh_rejects_non_list_envelope(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_materialization_issue(
        {},
        tmp_path,
        capsys,
        code="refresh_invalid_envelope",
        message="ba_fhmzbih station payload must be a JSON array",
    )


def test_refresh_rejects_missing_required_field(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = copy.deepcopy(_fixture_payload())
    del payload[0]["metadata_station_name"]  # type: ignore[index]
    _assert_materialization_issue(
        payload,
        tmp_path,
        capsys,
        code="refresh_missing_required_fields",
        message=("ba_fhmzbih station row at index 0 is missing required source fields: metadata_station_name"),
    )


def test_refresh_rejects_non_object_row(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = copy.deepcopy(_fixture_payload())
    payload.append("not-an-object")
    _assert_materialization_issue(
        payload,
        tmp_path,
        capsys,
        code="refresh_invalid_row",
        message="ba_fhmzbih station row at index 2 must be an object",
    )


@pytest.mark.parametrize("invalid_id", [None, "", "nan", "none", "null"])
def test_refresh_rejects_missing_or_blank_station_id(
    invalid_id: str | None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = copy.deepcopy(_fixture_payload())
    if invalid_id is None:
        del payload[0]["metadata_station_no"]  # type: ignore[index]
    else:
        payload[0]["metadata_station_no"] = invalid_id  # type: ignore[index]
    _assert_materialization_issue(
        payload,
        tmp_path,
        capsys,
        code="invalid_station_id",
        message="ba_fhmzbih station row at index 0 has missing or blank metadata_station_no",
    )


def test_refresh_rejects_duplicate_station_id(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = copy.deepcopy(_fixture_payload())
    payload[1]["metadata_station_no"] = "4510"  # type: ignore[index]
    _assert_materialization_issue(
        payload,
        tmp_path,
        capsys,
        code="duplicate_station_id",
        message="ba_fhmzbih duplicate metadata_station_no 4510",
    )


@pytest.mark.parametrize(
    "coordinate",
    ["metadata_station_latitude", "metadata_station_longitude"],
)
def test_refresh_rejects_unparseable_coordinates(
    coordinate: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = copy.deepcopy(_fixture_payload())
    payload[0][coordinate] = "not-a-coordinate"  # type: ignore[index]
    _assert_materialization_issue(
        payload,
        tmp_path,
        capsys,
        code="invalid_station_coordinates",
        message=("ba_fhmzbih station 4510 has unparseable metadata_station_latitude or metadata_station_longitude"),
    )


def test_live_refresh_enforces_minimum_after_parsing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_materialization_issue(
        _fixture_payload(),
        tmp_path,
        capsys,
        input_kind=generate_catalogue.RefreshInputKind.LIVE,
        code="refresh_below_minimum",
        message=("ba_fhmzbih: live catalogue returned only 2 stations (expected >= 30); possible fetch failure"),
    )


def test_fixture_refresh_preserves_stable_source_fields() -> None:
    outcome = generate_catalogue.refresh_native_table(
        _fixture_payload(),
        retrieved_at=_RETRIEVED_AT,
        input_kind=generate_catalogue.RefreshInputKind.FIXTURE,
    )
    assert outcome.issues == ()
    native = outcome.value.data
    assert generate_catalogue.METADATA_COLUMNS == _METADATA_COLUMNS
    assert generate_catalogue.VOLATILE_L1_COLUMNS == _VOLATILE_COLUMNS
    assert native.schema == _EXPECTED_NATIVE_SCHEMA
    assert native["metadata_station_no"].to_list() == ["4121", "4510"]
    assert native["metadata_station_elevation"].to_list() == ["", ""]
    row_4510 = native.filter(pl.col("metadata_station_no") == "4510")
    assert row_4510["metadata_CATCHMENT_SIZE"].item() == "633.00 km²"
    assert row_4510["metadata_WTO_OBJECT"].item() == "Usora"
    assert row_4510["metadata_station_id"].item() == "12191"
    assert row_4510["metadata_station_carteasting"].item() == "6492481.45"
    assert row_4510["metadata_station_local_x"].item() == "6492481.45"
    assert not any(name.startswith("L1_") for name in native.columns)


def test_fixture_refresh_frame_equals_committed_rows() -> None:
    outcome = generate_catalogue.refresh_native_table(
        _fixture_payload(),
        retrieved_at=_RETRIEVED_AT,
        input_kind=generate_catalogue.RefreshInputKind.FIXTURE,
    )
    assert outcome.issues == ()
    committed = read_native_table(_NATIVE_TABLE).data.filter(pl.col("metadata_station_no").is_in(["4510", "4121"]))
    pl_testing.assert_frame_equal(outcome.value.data, committed, check_exact=True)


def test_committed_native_table_contract() -> None:
    native = read_native_table(_NATIVE_TABLE)
    frame = native.data
    assert frame.schema == _EXPECTED_NATIVE_SCHEMA
    assert frame.height == 60
    station_ids = frame["metadata_station_no"].to_list()
    assert station_ids == sorted(station_ids)
    assert len(set(station_ids)) == 60
    assert frame["retrieved_at"].n_unique() == 1
    assert frame["retrieved_at"].item(0) == _RETRIEVED_AT.value
    assert not any(name.startswith("L1_") for name in frame.columns)
    row_4510 = frame.filter(pl.col("metadata_station_no") == "4510")
    row_4121 = frame.filter(pl.col("metadata_station_no") == "4121")
    assert row_4510["metadata_station_elevation"].item() == ""
    assert row_4510["metadata_station_name"].item() == "HS Kaloševići"
    assert row_4510["metadata_station_longname"].item() == "PODRUČJA NA SLIVU RIJEKE BOSNE"
    assert row_4510["metadata_station_cartnorthing"].item() == "4944707.34"
    assert row_4121["metadata_station_name"].item() == "HS Blažuj"
    assert row_4121["metadata_station_carteasting"].item() == "6520724.16"


def test_committed_native_table_digests() -> None:
    native = read_native_table(_NATIVE_TABLE)
    stable = native.data.select(_METADATA_COLUMNS).to_dicts()
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert hashlib.sha256(encoded).hexdigest() == "14ab47126fe40f16f23ddc66620fc8ae30910cd812c69806f867a851e659b23d"
    assert (
        generate_catalogue.native_table_content_digest(native)
        == "dd915e4a3d9598ff47c6f3fc972db24c7e03dd5b8b957a4eb597c28545634140"
    )


def test_main_raises_returned_issue_without_writing(tmp_path: Path) -> None:
    payload = copy.deepcopy(_fixture_payload())
    del payload[0]["metadata_station_name"]  # type: ignore[index]
    payload_path = tmp_path / "defective.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    native_out = tmp_path / "native.parquet"
    with pytest.raises(FatalContractError) as caught:
        generate_catalogue.main(
            [
                "--native-payload",
                str(payload_path),
                "--native-out",
                str(native_out),
                "--retrieved-at",
                "2026-08-02T12:42:03Z",
                "--native-input-kind",
                "fixture",
            ]
        )
    assert len(caught.value.issues) == 1
    issue = caught.value.issues[0]
    assert issue.code == "refresh_missing_required_fields"
    assert issue.message == (
        "ba_fhmzbih station row at index 0 is missing required source fields: metadata_station_name"
    )
    assert str(caught.value) == issue.message
    assert not native_out.exists()


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (
            ["--native-payload", "payload.json", "--native", "native.parquet"],
            "--native-payload cannot be combined with --native or --out",
        ),
        (
            ["--native-payload", "payload.json", "--out", "catalogue"],
            "--native-payload cannot be combined with --native or --out",
        ),
        (
            [
                "--native-payload",
                "payload.json",
                "--retrieved-at",
                "2026-08-02T12:42:03Z",
                "--native-input-kind",
                "fixture",
            ],
            "--native-payload requires --native-out",
        ),
        (
            [
                "--native-payload",
                "payload.json",
                "--native-out",
                "native.parquet",
                "--native-input-kind",
                "fixture",
            ],
            "--native-payload requires --retrieved-at",
        ),
        (
            [
                "--native-payload",
                "payload.json",
                "--native-out",
                "native.parquet",
                "--retrieved-at",
                "2026-08-02T12:42:03Z",
            ],
            "--native-payload requires --native-input-kind",
        ),
        (["--native-out", "native.parquet"], "--native-out requires --native-payload"),
        (
            ["--retrieved-at", "2026-08-02T12:42:03Z"],
            "--retrieved-at requires --native-payload",
        ),
        (
            ["--native-input-kind", "fixture"],
            "--native-input-kind requires --native-payload",
        ),
        (["--native", "native.parquet"], "--native requires --workbook-access-ledger"),
        (["--out", "catalogue"], "--out requires --native"),
        ([], "one of --native or --native-payload is required"),
    ],
)
def test_main_rejects_incoherent_modes(
    argv: list[str],
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as caught:
        generate_catalogue.main(argv)
    assert caught.value.code != 0
    captured = capsys.readouterr()
    assert message in captured.err


def test_native_cli_is_offline_deterministic_and_matches_committed_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert hasattr(urllib.request, "urlopen")
    calls: list[object] = []

    def fail_network(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        raise AssertionError("network call during native catalogue build")

    monkeypatch.setattr(urllib.request, "urlopen", fail_network)
    first = tmp_path / "first"
    second = tmp_path / "second"
    argv = [
        "--native",
        str(_NATIVE_TABLE),
        "--workbook-access-ledger",
        str(_LEDGER),
        "--series-recording",
        str(_TEST_DATA_DIR / "ba_fhmzbih_metadata_index.recording.json"),
        "--out",
    ]
    assert generate_catalogue.main([*argv, str(first)]) == 0
    assert generate_catalogue.main([*argv, str(second)]) == 0
    assert calls == []
    for artifact in ("provider.json", "products.parquet", "stations.parquet", "station_products.parquet"):
        assert (first / artifact).read_bytes() == (second / artifact).read_bytes()
        assert (first / artifact).read_bytes() == (_CATALOGUE_DIR / artifact).read_bytes()


def test_public_artifact_exposes_evidenced_baseline() -> None:
    artifact = _catalogue().public_artifact
    assert artifact.stations.height == 60
    assert artifact.station_products.height == 180
    assert artifact.station_products.filter(pl.col("availability") == "available").height == 132
    assert artifact.station_products.filter(pl.col("availability") == "unknown").height == 48


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("station_no", 1010),
        ("site_no", 1),
        ("source_code", "WT"),
        ("source_unit", "cm"),
        ("workbook", "H_1Y.xlsx"),
        ("url", "https://vodostaji.voda.ba/wrong.xlsx"),
        ("http_status", 404),
        ("method", "POST"),
        ("parameters", {"date": "2000"}),
        ("numerical_rows", 0),
        ("blank_rows", 1),
        ("availability", "unknown"),
        ("status", "no_data_rows"),
        ("observed_window_start", None),
        ("response_sha256", "bad"),
        ("byte_size", 0),
    ],
)
def test_workbook_ledger_rejects_inconsistent_pair(field, value) -> None:
    from pydantic import ValidationError

    document = json.loads(_LEDGER.read_bytes())
    document["pairs"][0][field] = value
    with pytest.raises(ValidationError):
        TypeAdapter(WorkbookAccessLedger).validate_python(document)


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "extra", "site", "native_hash", "empty_status"])
def test_workbook_build_rejects_unmatched_or_inconsistent_ledger(mutation) -> None:
    from pydantic import ValidationError

    document = json.loads(_LEDGER.read_bytes())
    if mutation == "duplicate":
        document["pairs"].append(document["pairs"][0])
    elif mutation == "missing":
        document["pairs"].pop()
    elif mutation == "native_hash":
        document["baseline_native_sha256"] = "0" * 64
    elif mutation == "empty_status":
        pair = next(pair for pair in document["pairs"] if pair["status"] == "no_data_rows")
        pair["availability"] = "available"
    else:
        pair = document["pairs"][0]
        if mutation == "extra":
            pair["station_no"] = "not-a-baseline-station"
        else:
            pair["site_no"] = "999"
        pair["url"] = (
            f"https://vodostaji.voda.ba/data/internet/stations/{pair['site_no']}/{pair['station_no']}/{pair['source_code']}/{pair['workbook']}"
        )
    with pytest.raises((ValidationError, FatalContractError)):
        generate_catalogue.build_catalogue(
            read_native_table(_NATIVE_TABLE), _origins(), TypeAdapter(WorkbookAccessLedger).validate_python(document)
        )


def test_workbook_dates_reasons_and_unknown_published_bounds_are_preserved() -> None:
    catalogue = _catalogue()
    expected = _access()
    for pair in expected.pairs:
        row = catalogue.station_products.filter(
            (pl.col("station_id") == pair.station_no) & (pl.col("product_id") == pair.product_id)
        ).row(0, named=True)
        assert row["availability"] == pair.availability
        assert row["last_catalogue_check"] == pair.retrieved_at.date()
        assert pair.retrieved_at.isoformat() in row["availability_reason"]
        assert row["published_record_start_date"] is None
        assert row["published_record_end_date"] is None
        if pair.status == "no_data_rows":
            assert "zero data rows" in row["availability_reason"]
    assert catalogue.stations.filter(pl.col("station_id") == "2101-B").height == 1


@pytest.mark.parametrize("field", ["observed_window_start", "observed_window_end"])
def test_workbook_ledger_rejects_zoned_source_wall_clock(field) -> None:
    from pydantic import ValidationError

    document = json.loads(_LEDGER.read_bytes())
    document["pairs"][0][field] += "+00:00"
    with pytest.raises(ValidationError, match="timezone"):
        TypeAdapter(WorkbookAccessLedger).validate_python(document)


def test_workbook_ledger_requires_utc_retrieval_instant() -> None:
    from pydantic import ValidationError

    document = json.loads(_LEDGER.read_bytes())
    document["pairs"][0]["retrieved_at"] = "2026-09-13T23:57:40+05:00"
    with pytest.raises(ValidationError, match="UTC"):
        TypeAdapter(WorkbookAccessLedger).validate_python(document)
