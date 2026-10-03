"""Source-fidelity and legacy-catalogue tests for ThaiWater maintenance."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, read_native_table, stamp_native_table
from rivretrieve._internal.engine import UnknownTemporalSupport, WithIssues
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.providers.th_thaiwater import generate_catalogue
from rivretrieve._internal.providers.th_thaiwater.config import config
from rivretrieve._internal.providers.th_thaiwater.generate_catalogue import GraphAvailabilityEvidence
from rivretrieve._internal.providers.th_thaiwater.origins import STATION_CATALOGUE_ORIGINS

FIXTURE_PATH = Path("tests/test_data/th_thaiwater_metadata.json")
CATALOGUE_PATH = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/th_thaiwater/catalogue"
LEDGER_PATH = (
    Path(__file__).parents[1] / "maintenance/catalogue/th_thaiwater/inventory/governing_station_product_evidence.csv"
)


def _availability_evidence() -> GraphAvailabilityEvidence:
    return GraphAvailabilityEvidence(LEDGER_PATH.read_bytes())


NATIVE_PATH = Path("src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
ATTESTED_DATETIME = datetime(2026, 8, 2, 12, 42, 3, tzinfo=UTC)
ATTESTED_RETRIEVED_AT = RetrievedAt(ATTESTED_DATETIME)
FIXTURE_DIGEST = "afb6481ab844d39fb08874b0eaec310401f1a601afe0155a5311b52193cad827"
NATIVE_FRAME_DIGEST = "3e2085ce51e3714d35feb053973c5074a0994278943b51c620c862be1f281cfd"
RETAINED_PRODUCT_IDS = {"discharge_reported", "stage_reported"}
WITHDRAWN_PRODUCT_IDS = {"discharge_instantaneous", "stage_instantaneous"}

ADDITIONS = {
    "3",
    "319",
    "393",
    "475",
    "482",
    "653",
    "2808",
    "2809",
    "2828",
    "2863",
    "2867",
    "2874",
    "2888",
    "2905",
    "2918",
    "2920",
    "2925",
    "2948",
    "2957",
    "2964",
    "2975",
    "2976",
    "3000",
    "3002",
    "3032",
    "3085",
    "3122",
    "3525",
    "12475",
    "479237",
    "508035",
    "558654",
    "558658",
    "558661",
    "700551",
    "700552",
    "700553",
    "700555",
    "700556",
    "700559",
    "700584",
    "700585",
    "700586",
    "700587",
    "700588",
    "700589",
    "700591",
    "700592",
    "786010",
    "1109493",
    "1119776",
    "1119916",
    "1197957",
    "1225529",
    "1396860",
    "1422304",
    "1422361",
    "1422364",
    "1422365",
    "1422366",
    "1422367",
    "1422368",
    "1422369",
    "1422371",
    "1422372",
    "1422373",
    "1422374",
    "9822342",
    "9930854",
    "9930856",
    "9931002",
    "9931004",
    "9931006",
    "9931008",
    "11568367",
    "11688546",
    "11688685",
    "11688715",
    "11688749",
    "11688817",
    "11688823",
    "11688849",
    "11689002",
    "11689003",
    "11689067",
    "11689072",
    "11689150",
}
REMOVALS = {
    "563",
    "821",
    "2753",
    "2784",
    "3277",
    "471584",
    "505014",
    "527882",
    "726651",
    "740539",
    "832056",
    "1085209",
    "1106453",
    "1197836",
    "1422300",
    "1475116",
}


def _fixture_payload(retained_evidence_root: Path) -> dict[str, object]:
    return cast("dict[str, object]", json.loads((retained_evidence_root / FIXTURE_PATH).read_text(encoding="utf-8")))


def _fixture_rows(retained_evidence_root: Path) -> list[dict[str, Any]]:
    payload = cast("dict[str, Any]", _fixture_payload(retained_evidence_root))
    return cast("list[dict[str, Any]]", payload["waterlevel_data"]["data"])


def _two_row_payload(retained_evidence_root: Path) -> dict[str, object]:
    payload = copy.deepcopy(_fixture_payload(retained_evidence_root))
    waterlevel = cast("dict[str, Any]", payload["waterlevel_data"])
    waterlevel["data"] = cast("list[dict[str, Any]]", waterlevel["data"])[:2]
    return payload


def _nested(row: dict[str, Any], path: str) -> Any:
    value: Any = row
    for component in path.split("."):
        value = value[component]
    return value


def _set_nested(row: dict[str, Any], path: str, value: object) -> None:
    target: dict[str, Any] = row
    components = path.split(".")
    for component in components[:-1]:
        target = target[component]
    target[components[-1]] = value


def _delete_nested(row: dict[str, Any], path: str) -> None:
    target: dict[str, Any] = row
    components = path.split(".")
    for component in components[:-1]:
        target = target[component]
    del target[components[-1]]


def _expected_fixture_native_frame(retained_evidence_root: Path) -> pl.DataFrame:
    records: list[dict[str, object]] = []
    for source in _fixture_rows(retained_evidence_root):
        flattened: dict[str, object] = {}
        for path, dtype in generate_catalogue.NATIVE_SOURCE_SCHEMA.items():
            try:
                value = _nested(source, path)
            except KeyError:
                value = None
            if path == "station.id":
                value = str(value)
            elif dtype == pl.Float64 and value is not None:
                value = float(cast("int | float", value))
            flattened[path] = value
        records.append(flattened)
    source = pl.DataFrame(records, schema=generate_catalogue.NATIVE_SOURCE_SCHEMA).sort("station.id")
    return stamp_native_table(source, ATTESTED_RETRIEVED_AT).data


def _committed_native_table(retained_evidence_root: Path) -> NativeTable:
    return read_native_table(retained_evidence_root / NATIVE_PATH)


def _build(
    retained_evidence_root: Path, table: NativeTable | None = None
) -> generate_catalogue.GeneratedThThaiWaterCatalogue:
    return generate_catalogue.build_catalogue(
        table or _committed_native_table(retained_evidence_root), STATION_CATALOGUE_ORIGINS, _availability_evidence()
    )


def _expected_station_projection(table: NativeTable) -> pl.DataFrame:
    return table.data.select(
        pl.lit(str(generate_catalogue.PROVIDER_ID)).alias("provider_id"),
        pl.col("station.id").alias("station_id"),
        pl.col("station.tele_station_lat").cast(pl.Float64).alias("latitude"),
        pl.col("station.tele_station_long").cast(pl.Float64).alias("longitude"),
        pl.lit("unknown").alias("crs"),
    ).sort("station_id")


def _assert_cli_error(argv: list[str], substring: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        generate_catalogue.main(argv)
    assert exc_info.value.code != 0


class _FixtureResponse:
    status = 200

    def __init__(self, content: bytes) -> None:
        self._content = content

    def __enter__(self) -> _FixtureResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._content


@pytest.mark.derived("tests/test_data/th_thaiwater_metadata.json")
def test_fixture_digest_and_independent_contract(retained_evidence_root: Path) -> None:
    payload = _fixture_payload(retained_evidence_root)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    rows = _fixture_rows(retained_evidence_root)

    assert hashlib.sha256(canonical).hexdigest() == FIXTURE_DIGEST
    assert [row["station"]["id"] for row in rows] == [575568, 1117894, 2583, 1121258]
    assert all(row["station_type"] == "tele_waterlevel" for row in rows)
    assert [set(row["station"]["tele_station_name"]) for row in rows] == [
        {"en", "th"},
        {"th"},
        {"en", "jp", "th"},
        {"en", "th"},
    ]
    assert [row["station"]["id"] for row in rows if "sponsor_by" in row["station"]] == [1121258]
    assert rows[2]["station"]["tele_station_name"]["en"] == " "
    assert rows[2]["station"]["tele_station_name"]["jp"] == " "


@pytest.mark.derived("tests/test_data/th_thaiwater_metadata.json")
def test_refresh_fixture_is_network_free_and_exact(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        generate_catalogue,
        "_read_live_json",
        lambda url: (_ for _ in ()).throw(AssertionError(f"unexpected live request to {url}")),
    )
    outcome = generate_catalogue.refresh_native_table_from_fixture(
        (retained_evidence_root / FIXTURE_PATH), retrieved_at=ATTESTED_RETRIEVED_AT
    )

    assert outcome.issues == ()
    assert outcome.value.data.schema == generate_catalogue.NATIVE_SCHEMA
    assert outcome.value.data.columns == list(generate_catalogue.NATIVE_SCHEMA)
    assert outcome.value.data["station.id"].to_list() == sorted(
        [str(row["station"]["id"]) for row in _fixture_rows(retained_evidence_root)]
    )
    pl_testing.assert_frame_equal(
        outcome.value.data, _expected_fixture_native_frame(retained_evidence_root), check_exact=True
    )


@pytest.mark.derived("tests/test_data/th_thaiwater_metadata.json")
def test_native_identity_and_colliding_fields_remain_distinct(retained_evidence_root: Path) -> None:
    source_rows = _fixture_rows(retained_evidence_root)
    table = generate_catalogue.refresh_native_table(
        _fixture_payload(retained_evidence_root), retrieved_at=ATTESTED_RETRIEVED_AT
    ).value.data

    assert table.schema["station.id"] == pl.String
    assert table.schema["id"] == pl.Int64
    assert table.schema["station.tele_station_oldcode"] == pl.String
    assert all(type(row["station"]["id"]) is int for row in source_rows)
    for row in source_rows:
        stored = table.filter(pl.col("station.id") == str(row["station"]["id"])).row(0, named=True)
        assert int(stored["station.id"]) == row["station"]["id"]
        assert stored["id"] == row["id"]
        assert stored["station.tele_station_oldcode"] == row["station"]["tele_station_oldcode"]


@pytest.mark.derived("tests/test_data/th_thaiwater_metadata.json")
def test_language_maps_flatten_without_stringification(retained_evidence_root: Path) -> None:
    table = generate_catalogue.refresh_native_table(
        _fixture_payload(retained_evidence_root), retrieved_at=ATTESTED_RETRIEVED_AT
    ).value.data
    language_columns = [
        "station.tele_station_name.en",
        "station.tele_station_name.jp",
        "station.tele_station_name.th",
        "agency.agency_name.en",
        "agency.agency_name.jp",
        "agency.agency_name.th",
        "agency.agency_shortname.en",
        "agency.agency_shortname.jp",
        "agency.agency_shortname.th",
    ]
    assert all(table.schema[column] == pl.String for column in language_columns)
    for source in _fixture_rows(retained_evidence_root):
        stored = table.filter(pl.col("station.id") == str(source["station"]["id"])).row(0, named=True)
        for column in language_columns:
            try:
                expected = _nested(source, column)
            except KeyError:
                expected = None
            assert stored[column] == expected


@pytest.mark.derived("tests/test_data/th_thaiwater_metadata.json")
def test_unexpected_language_key_names_map_and_key(retained_evidence_root: Path) -> None:
    payload = _two_row_payload(retained_evidence_root)
    rows = cast("list[dict[str, Any]]", cast("dict[str, Any]", payload["waterlevel_data"])["data"])
    rows[1]["agency"]["agency_name"]["fr"] = "interdit"
    expected = "ThaiWater row 1 language map 'agency.agency_name' contains unexpected key 'fr'"
    with pytest.raises(FatalContractError, match=re.escape(expected)):
        generate_catalogue.refresh_native_table(payload, retrieved_at=ATTESTED_RETRIEVED_AT)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("missing_envelope", "ThaiWater payload missing required object 'waterlevel_data'"),
        ("invalid_envelope", "ThaiWater payload field 'waterlevel_data' must be an object"),
        ("missing_data", "ThaiWater payload missing required list 'waterlevel_data.data'"),
        ("invalid_data", "ThaiWater payload field 'waterlevel_data.data' must be a list"),
    ],
)
@pytest.mark.derived("tests/test_data/th_thaiwater_metadata.json")
def test_envelope_guards(retained_evidence_root: Path, mutation: str, expected: str) -> None:
    payload = _two_row_payload(retained_evidence_root)
    if mutation == "missing_envelope":
        del payload["waterlevel_data"]
    elif mutation == "invalid_envelope":
        payload["waterlevel_data"] = []
    elif mutation == "missing_data":
        del cast("dict[str, object]", payload["waterlevel_data"])["data"]
    else:
        cast("dict[str, object]", payload["waterlevel_data"])["data"] = {}
    with pytest.raises(FatalContractError, match=re.escape(expected)):
        generate_catalogue.refresh_native_table(payload, retrieved_at=ATTESTED_RETRIEVED_AT)


@pytest.mark.derived("tests/test_data/th_thaiwater_metadata.json")
def test_non_object_row_guard(retained_evidence_root: Path) -> None:
    payload = _two_row_payload(retained_evidence_root)
    cast("dict[str, Any]", payload["waterlevel_data"])["data"][1] = []
    with pytest.raises(FatalContractError, match=re.escape("ThaiWater row 1 must be an object")):
        generate_catalogue.refresh_native_table(payload, retrieved_at=ATTESTED_RETRIEVED_AT)


@pytest.mark.parametrize("kind", ["missing", "invalid"])
@pytest.mark.derived("tests/test_data/th_thaiwater_metadata.json")
def test_nested_object_guards(retained_evidence_root: Path, kind: str) -> None:
    payload = _two_row_payload(retained_evidence_root)
    row = cast("dict[str, Any]", payload["waterlevel_data"])["data"][1]
    if kind == "missing":
        del row["station"]["tele_station_name"]
        expected = "ThaiWater row 1 missing required object 'station.tele_station_name'"
    else:
        row["station"]["tele_station_name"] = "not an object"
        expected = "ThaiWater row 1 field 'station.tele_station_name' must be an object"
    with pytest.raises(FatalContractError, match=re.escape(expected)):
        generate_catalogue.refresh_native_table(payload, retrieved_at=ATTESTED_RETRIEVED_AT)


@pytest.mark.derived("tests/test_data/th_thaiwater_metadata.json")
def test_required_leaf_guard(retained_evidence_root: Path) -> None:
    payload = _two_row_payload(retained_evidence_root)
    row = cast("dict[str, Any]", payload["waterlevel_data"])["data"][1]
    del row["station"]["tele_station_lat"]
    expected = "ThaiWater row 1 missing required leaf 'station.tele_station_lat'"
    with pytest.raises(FatalContractError, match=re.escape(expected)):
        generate_catalogue.refresh_native_table(payload, retrieved_at=ATTESTED_RETRIEVED_AT)


@pytest.mark.parametrize("invalid", ["123", True])
@pytest.mark.derived("tests/test_data/th_thaiwater_metadata.json")
def test_station_id_requires_exact_integer(retained_evidence_root: Path, invalid: object) -> None:
    payload = _two_row_payload(retained_evidence_root)
    row = cast("dict[str, Any]", payload["waterlevel_data"])["data"][1]
    row["station"]["id"] = invalid
    expected = "ThaiWater row 1 station.id must be a JSON integer; Boolean is invalid"
    with pytest.raises(FatalContractError, match=re.escape(expected)):
        generate_catalogue.refresh_native_table(payload, retrieved_at=ATTESTED_RETRIEVED_AT)


@pytest.mark.derived("tests/test_data/th_thaiwater_metadata.json")
def test_duplicate_station_id_guard(retained_evidence_root: Path) -> None:
    payload = _two_row_payload(retained_evidence_root)
    rows = cast("list[dict[str, Any]]", cast("dict[str, Any]", payload["waterlevel_data"])["data"])
    duplicate = rows[0]["station"]["id"]
    rows[1]["station"]["id"] = duplicate
    with pytest.raises(FatalContractError, match=re.escape(f"ThaiWater duplicate station.id {duplicate}")):
        generate_catalogue.refresh_native_table(payload, retrieved_at=ATTESTED_RETRIEVED_AT)


@pytest.mark.parametrize("invalid", ["not numeric", True])
@pytest.mark.derived("tests/test_data/th_thaiwater_metadata.json")
def test_numeric_family_rejects_nonnumeric_and_boolean(retained_evidence_root: Path, invalid: object) -> None:
    payload = _two_row_payload(retained_evidence_root)
    row = cast("dict[str, Any]", payload["waterlevel_data"])["data"][1]
    row["station"]["tele_station_lat"] = invalid
    expected = (
        "ThaiWater row 1 leaf 'station.tele_station_lat' must be a JSON number or null; "
        "Boolean is invalid for numeric families"
    )
    with pytest.raises(FatalContractError, match=re.escape(expected)):
        generate_catalogue.refresh_native_table(payload, retrieved_at=ATTESTED_RETRIEVED_AT)


@pytest.mark.parametrize(
    ("path", "source_index"),
    [
        ("river_gid", 0),
        ("river_name", 0),
        ("situation_level", 0),
        ("station.ground_level", 0),
        ("station.sponsor_by", 3),
        ("station.tele_station_name.en", 0),
        ("station.tele_station_name.jp", 2),
    ],
)
@pytest.mark.derived("tests/test_data/th_thaiwater_metadata.json")
def test_permitted_absence_projects_to_null(retained_evidence_root: Path, path: str, source_index: int) -> None:
    payload = copy.deepcopy(_fixture_payload(retained_evidence_root))
    all_rows = cast("list[dict[str, Any]]", cast("dict[str, Any]", payload["waterlevel_data"])["data"])
    selected = [all_rows[source_index], all_rows[1 if source_index != 1 else 0]]
    cast("dict[str, Any]", payload["waterlevel_data"])["data"] = selected
    station_id = str(selected[0]["station"]["id"])
    _delete_nested(selected[0], path)
    table = generate_catalogue.refresh_native_table(payload, retrieved_at=ATTESTED_RETRIEVED_AT).value.data
    assert table.filter(pl.col("station.id") == station_id)[path].item() is None


@pytest.mark.derived("src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
def test_complete_native_table_shape_census_and_membership(retained_evidence_root: Path) -> None:
    committed = read_native_table(retained_evidence_root / NATIVE_PATH).data
    native_ids = set(committed["station.id"].to_list())
    former_canonical_ids = (native_ids - ADDITIONS) | REMOVALS

    assert committed.height == committed["station.id"].n_unique() == 825
    assert committed.schema == generate_catalogue.NATIVE_SCHEMA
    assert committed["station.id"].to_list() == sorted(committed["station.id"].to_list())
    assert committed["retrieved_at"].n_unique() == 1
    assert committed["retrieved_at"].item(0) == ATTESTED_DATETIME
    assert set(committed["station_type"]) == {"tele_waterlevel"}
    assert set(committed["station.tele_station_type"]) == {"tele_waterlevel"}
    assert committed.select(
        pl.col("station.tele_station_lat").is_between(-90, 90).all()
        & pl.col("station.tele_station_long").is_between(-180, 180).all()
    ).item()
    census = Counter(
        (
            row[0] is not None,
            row[1] is not None,
            row[2] is not None,
        )
        for row in committed.select(
            "station.tele_station_name.en", "station.tele_station_name.jp", "station.tele_station_name.th"
        ).iter_rows()
    )
    assert census == Counter({(True, False, True): 425, (False, False, True): 399, (True, True, True): 1})
    for prefix in ("agency.agency_name", "agency.agency_shortname"):
        assert all(committed[f"{prefix}.{language}"].null_count() == 0 for language in ("en", "jp", "th"))
    assert {
        path: committed[path].null_count()
        for path in (
            "river_gid",
            "river_name",
            "situation_level",
            "station.ground_level",
            "station.sponsor_by",
            "station.tele_station_name.en",
            "station.tele_station_name.jp",
        )
    } == {
        "river_gid": 88,
        "river_name": 88,
        "situation_level": 27,
        "station.ground_level": 9,
        "station.sponsor_by": 711,
        "station.tele_station_name.en": 399,
        "station.tele_station_name.jp": 824,
    }
    assert len(former_canonical_ids) == 754
    assert len(ADDITIONS) == 87
    assert len(REMOVALS) == 16
    assert 825 - 754 == 71


@pytest.mark.derived("src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
def test_complete_native_table_has_pinned_full_content(retained_evidence_root: Path) -> None:
    assert (
        generate_catalogue.native_table_content_sha256(read_native_table(retained_evidence_root / NATIVE_PATH))
        == NATIVE_FRAME_DIGEST
    )


@pytest.mark.derived("tests/test_data/th_thaiwater_metadata.json")
def test_live_native_cli_uses_exact_transport_seam(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, int]] = []

    def fake_urlopen(url: str, *, timeout: int) -> _FixtureResponse:
        calls.append((url, timeout))
        return _FixtureResponse((retained_evidence_root / FIXTURE_PATH).read_bytes())

    monkeypatch.setattr(generate_catalogue.urllib.request, "urlopen", fake_urlopen)
    output_path = tmp_path / "native.parquet"
    result = generate_catalogue.main(
        [
            "--live",
            "--native-out",
            str(output_path),
            "--retrieved-at",
            "2026-08-02T12:42:03Z",
        ]
    )
    assert result == 0
    assert calls == [(generate_catalogue.METADATA_URL, 60)]
    pl_testing.assert_frame_equal(
        read_native_table(output_path).data,
        _expected_fixture_native_frame(retained_evidence_root),
        check_exact=True,
    )


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--out", "catalogue"], "--out requires --native"),
        (
            ["--native", "native.parquet", "--availability-evidence", "ledger.csv", "--out", "catalogue"],
            "--out requires --evidence-root",
        ),
        (
            ["--fixture", str(FIXTURE_PATH), "--live", "--out", "catalogue"],
            "--fixture/--live cannot be used with --out",
        ),
        (["--fixture", str(FIXTURE_PATH)], "choose exactly one ThaiWater destination: --out or --native-out"),
        (
            ["--fixture", str(FIXTURE_PATH), "--out", "catalogue", "--native-out", "native.parquet"],
            "choose exactly one ThaiWater destination: --out or --native-out",
        ),
        (
            ["--fixture", str(FIXTURE_PATH), "--native-out", "native.parquet"],
            "--retrieved-at is required with --native-out",
        ),
        (
            ["--fixture", str(FIXTURE_PATH), "--out", "catalogue", "--retrieved-at", "2026-08-02T12:42:03Z"],
            "--fixture/--live cannot be used with --out",
        ),
        (["--native", str(NATIVE_PATH), "--native-out", "native.parquet"], "--native cannot be used with --native-out"),
        (
            ["--native", str(NATIVE_PATH), "--out", "catalogue", "--retrieved-at", "2026-08-02T12:42:03Z"],
            "--retrieved-at is only valid with refresh mode",
        ),
        (
            [
                "--fixture",
                str(FIXTURE_PATH),
                "--native-out",
                "native.parquet",
                "--retrieved-at",
                "2026-08-02T12:42:03+00:00",
            ],
            "ThaiWater --retrieved-at must be UTC in YYYY-MM-DDTHH:MM:SSZ form",
        ),
    ],
)
def test_cli_contract_errors_precede_io(
    argv: list[str], message: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(generate_catalogue, "_read_fixture_json", lambda path: pytest.fail("file seam reached"))
    monkeypatch.setattr(generate_catalogue, "_read_live_json", lambda url: pytest.fail("network seam reached"))
    _assert_cli_error(argv, message)
    assert message in capsys.readouterr().err


@pytest.mark.derived("tests/test_data/th_thaiwater_metadata.json")
def test_native_cli_writes_only_native_and_preserves_canonical_sentinel(
    retained_evidence_root: Path, tmp_path: Path
) -> None:
    native_path = tmp_path / "native.parquet"
    canonical_dir = tmp_path / "catalogue"
    canonical_dir.mkdir()
    sentinel = canonical_dir / "provider.json"
    sentinel.write_text("sentinel", encoding="utf-8")
    result = generate_catalogue.main(
        [
            "--fixture",
            str(retained_evidence_root / FIXTURE_PATH),
            "--native-out",
            str(native_path),
            "--retrieved-at",
            "2026-08-02T12:42:03Z",
        ]
    )
    assert result == 0
    assert native_path.exists()
    assert sentinel.read_text(encoding="utf-8") == "sentinel"


@pytest.mark.derived("tests/test_data/th_thaiwater_metadata.json")
def test_native_cli_refuses_error_issues(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    outcome = generate_catalogue.refresh_native_table(
        _fixture_payload(retained_evidence_root), retrieved_at=ATTESTED_RETRIEVED_AT
    )
    error = Issue(severity="error", code="broken", message="broken")
    monkeypatch.setattr(
        generate_catalogue,
        "refresh_native_table_from_fixture",
        lambda path, *, retrieved_at: WithIssues(value=outcome.value, issues=(error,)),
    )
    called = False

    def fail_writer(table: NativeTable, path: Path) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(generate_catalogue, "write_native_table", fail_writer)
    _assert_cli_error(
        [
            "--fixture",
            str(retained_evidence_root / FIXTURE_PATH),
            "--native-out",
            str(tmp_path / "native.parquet"),
            "--retrieved-at",
            "2026-08-02T12:42:03Z",
        ],
        "ThaiWater native refresh returned issues; refusing to write",
    )
    assert "ThaiWater native refresh returned issues; refusing to write" in capsys.readouterr().err
    assert called is False


@pytest.mark.derived("src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
def test_native_build_counts_and_identity_station_fields(retained_evidence_root: Path) -> None:
    catalogue = _build(retained_evidence_root)
    assert all(isinstance(product.semantics, UnknownTemporalSupport) for product in config().products.values())
    committed = _committed_native_table(retained_evidence_root).data
    source_id = committed["station.id"].item(0)
    station = catalogue.stations.filter(pl.col("station_id") == source_id)

    assert catalogue.stations.height == 825
    assert catalogue.products.height == 2
    assert catalogue.station_products.height == 1650
    assert set(catalogue.products["product_id"]) == RETAINED_PRODUCT_IDS
    assert set(catalogue.products["frequency"]) == {"unknown"}
    assert set(catalogue.products["statistic"]) == {"unknown"}
    assert set(catalogue.products["period_type"]) == {"unknown"}
    assert set(catalogue.products["period_anchor"]) == {"unknown"}
    assert set(catalogue.station_products["product_id"]) == RETAINED_PRODUCT_IDS
    assert set(catalogue.station_products["station_id"]) == set(committed["station.id"])
    assert set(catalogue.station_products["availability"].cast(str)) == {"available", "unknown"}
    assert catalogue.station_products["published_record_start_date"].null_count() == 1650
    assert catalogue.station_products["published_record_end_date"].null_count() == 1650
    assert set(catalogue.station_products["last_catalogue_check"]) == {date(2026, 9, 11), date(2026, 9, 13)}
    assert catalogue.station_products.group_by("product_id").len().sort("product_id").to_dicts() == [
        {"product_id": "discharge_reported", "len": 825},
        {"product_id": "stage_reported", "len": 825},
    ]
    assert set(catalogue.products["product_id"]).isdisjoint(WITHDRAWN_PRODUCT_IDS)
    assert set(catalogue.station_products["product_id"]).isdisjoint(WITHDRAWN_PRODUCT_IDS)
    assert station.height == 1
    assert station["station_id"].dtype == committed["station.id"].dtype == pl.String
    assert station["station_id"].item() == source_id
    assert station["crs"].item() == "unknown"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("empty", "ThaiWater native table contains no stations"),
        ("station_type", "ThaiWater station 100 has station_type 'tele_rainfall'; expected 'tele_waterlevel'"),
        ("latitude", "ThaiWater station 100 has null station.tele_station_lat"),
        ("longitude", "ThaiWater station 100 has null station.tele_station_long"),
        ("duplicate", "ThaiWater native table contains duplicate station.id 100"),
    ],
)
@pytest.mark.derived("src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
def test_native_build_contracts_fail_loud(retained_evidence_root: Path, mutation: str, message: str) -> None:
    base = (
        _committed_native_table(retained_evidence_root)
        .data.head(2)
        .with_columns(pl.Series("station.id", ["100", "200"], dtype=pl.String))
    )
    if mutation == "empty":
        data = base.clear()
    elif mutation == "station_type":
        data = base.with_columns(
            pl.when(pl.col("station.id") == "100")
            .then(pl.lit("tele_rainfall"))
            .otherwise(pl.col("station_type"))
            .alias("station_type")
        )
    elif mutation == "latitude":
        data = base.with_columns(
            pl.when(pl.col("station.id") == "100")
            .then(None)
            .otherwise(pl.col("station.tele_station_lat"))
            .alias("station.tele_station_lat")
        )
    elif mutation == "longitude":
        data = base.with_columns(
            pl.when(pl.col("station.id") == "100")
            .then(None)
            .otherwise(pl.col("station.tele_station_long"))
            .alias("station.tele_station_long")
        )
    else:
        data = base.with_columns(pl.lit("100").alias("station.id"))

    with pytest.raises(FatalContractError, match=re.escape(message)):
        _build(retained_evidence_root, NativeTable(data))


@pytest.mark.derived("src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
def test_native_build_rejects_non_string_station_id(retained_evidence_root: Path) -> None:
    data = (
        _committed_native_table(retained_evidence_root).data.head(2).with_columns(pl.col("station.id").cast(pl.Int64))
    )

    with pytest.raises(FatalContractError, match="ThaiWater native station.id must have String dtype"):
        _build(retained_evidence_root, NativeTable(data))


@pytest.mark.derived("src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
def test_generated_station_projection_matches_native_exactly(retained_evidence_root: Path) -> None:
    native = _committed_native_table(retained_evidence_root)
    generated = _build(retained_evidence_root, native)

    assert native.data.schema["station.id"] == generated.stations.schema["station_id"] == pl.String
    pl_testing.assert_frame_equal(generated.stations, _expected_station_projection(native), check_exact=True)


@pytest.mark.derived("src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
def test_native_preserves_displaced_source_fields(retained_evidence_root: Path) -> None:
    native = _committed_native_table(retained_evidence_root).data
    displaced = native.select(
        "station.tele_station_name.en",
        "station.tele_station_name.th",
        "river_name",
        "station_type",
        "agency.agency_name.en",
        "basin.basin_name.en",
        "geocode.province_name.en",
        "station.tele_station_oldcode",
    )

    assert displaced.height == 825
    assert displaced["station_type"].null_count() == 0
    assert displaced["station.tele_station_name.th"].null_count() == 0
    assert displaced["agency.agency_name.en"].null_count() == 0
    assert displaced["station.tele_station_oldcode"].null_count() == 0


@pytest.mark.derived("src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
def test_origin_enforcement_is_part_of_native_build(retained_evidence_root: Path) -> None:
    declarations = dict(STATION_CATALOGUE_ORIGINS)
    del declarations["longitude"]

    with pytest.raises(FatalContractError, match="th_thaiwater.longitude: canonical column has no origin declaration"):
        generate_catalogue.build_catalogue(
            _committed_native_table(retained_evidence_root), declarations, _availability_evidence()
        )


@pytest.mark.derived("src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
def test_station_product_check_uses_own_acquisition_date_and_provider_uses_native_date(
    retained_evidence_root: Path,
) -> None:
    catalogue = _build(retained_evidence_root)
    expected = {
        (pair.station_id, pair.product_id): pair.acquisition.retrieved_at_start.date()
        for pair in _availability_evidence().pairs
        if pair.acquisition.retrieved_at_start is not None
    }
    assert {
        (station, product): checked
        for station, product, checked in catalogue.station_products.select(
            "station_id", "product_id", "last_catalogue_check"
        ).iter_rows()
    } == expected
    assert catalogue.provider_info["catalogue_version"] == "2026-08-02"


@pytest.mark.derived("src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
def test_committed_catalogue_station_projection_matches_native(retained_evidence_root: Path) -> None:
    native = _committed_native_table(retained_evidence_root)
    committed = pl.read_parquet(CATALOGUE_PATH / "stations.parquet")

    pl_testing.assert_frame_equal(committed, _expected_station_projection(native), check_exact=True)


@pytest.mark.derived("src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
def test_governing_acquisitions_expose_all_baseline_pairs(retained_evidence_root: Path) -> None:
    catalogue = _build(retained_evidence_root)
    pairs = catalogue.station_products
    assert pairs.height == 1650
    assert Counter(pairs.select("product_id", "availability").iter_rows()) == {
        ("stage_reported", "available"): 813,
        ("stage_reported", "unknown"): 12,
        ("discharge_reported", "available"): 283,
        ("discharge_reported", "unknown"): 542,
    }
    assert set(pairs["station_id"]) == set(_committed_native_table(retained_evidence_root).data["station.id"])
    assert catalogue.acquisition_provenance.withheld_facts == ()


@pytest.mark.derived("src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
def test_build_cli_requires_explicit_reviewed_availability_evidence(
    retained_evidence_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        generate_catalogue.main(["--native", str(retained_evidence_root / NATIVE_PATH), "--out", str(tmp_path)])
    assert "--out requires --availability-evidence" in capsys.readouterr().err


@pytest.mark.derived("src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
def test_each_governing_product_uses_the_official_graph_field(retained_evidence_root: Path) -> None:
    catalogue = _build(retained_evidence_root)
    fields = dict(catalogue.products.select("product_id", "native_id").iter_rows())
    assert fields == {"stage_reported": "value", "discharge_reported": "discharge"}
    assert all(fields[pair.product_id] == pair.native_field for pair in _availability_evidence().pairs)
