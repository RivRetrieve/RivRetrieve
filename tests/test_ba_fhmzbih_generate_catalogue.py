from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.native import RetrievedAt, read_native_table
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ba_fhmzbih import generate_catalogue

_TEST_DATA_DIR = Path(__file__).parent / "test_data"
_METADATA_FIXTURE = _TEST_DATA_DIR / "ba_fhmzbih_metadata.json"
_NATIVE_TABLE = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet"
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


def test_generate_catalogue_station_count() -> None:
    cat = generate_catalogue.generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.stations.height == 2


def test_generate_catalogue_product_count() -> None:
    cat = generate_catalogue.generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.products.height == 6


def test_generate_catalogue_station_products_count() -> None:
    cat = generate_catalogue.generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.station_products.height == 12


def test_generate_catalogue_station_fields() -> None:
    cat = generate_catalogue.generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == "4510")
    assert row.height == 1
    assert row["latitude"].item() == 44.64680728070949
    assert row["longitude"].item() == 17.90406242892678
    assert row["crs"].item() == "unknown"


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
            ["--native-payload", "payload.json", "--fixture", "fixture.json"],
            "--native-payload cannot be combined with --fixture or --live",
        ),
        (
            ["--native-payload", "payload.json", "--live"],
            "--native-payload cannot be combined with --fixture or --live",
        ),
        (
            ["--native-payload", "payload.json", "--out", "catalogue"],
            "--native-payload cannot be combined with --out",
        ),
        (
            ["--native-payload", "payload.json", "--catalogue-date", "2026-08-02"],
            "--catalogue-date cannot be used with --native-payload",
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
        ([], "one of --fixture, --live, or --native-payload is required"),
        (["--fixture", "fixture.json"], "--out is required with --fixture or --live"),
        (["--live"], "--out is required with --fixture or --live"),
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


def test_canonical_main_retains_default_catalogue_date(tmp_path: Path) -> None:
    output = tmp_path / "catalogue"
    assert generate_catalogue.main(["--fixture", str(_METADATA_FIXTURE), "--out", str(output)]) == 0
    provider = json.loads((output / "provider.json").read_text(encoding="utf-8"))
    assert provider["catalogue_version"] == date.today().isoformat()
