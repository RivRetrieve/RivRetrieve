"""Tests for the jp_mlit packaged catalogue and native refresh."""

from __future__ import annotations

import ast
import hashlib
import io
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, read_native_table
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
    validate_catalogue,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.jp_mlit import generate_catalogue

CATALOGUE_PATH = Path("src/rivretrieve/_internal/providers/jp_mlit/catalogue")
FIXTURE_PATH = Path("tests/test_data/jp_mlit_metadata.json")
REJECTED_PATH = Path("tests/test_data/jp_mlit_site_info_detail_rejected_307051287711040.html")
NATIVE_PATH = CATALOGUE_PATH / "native.parquet"
FIXTURE_IDS = ["301011281104010", "303051283310060", "309191289913130"]
FIXTURE_DIGEST = "5002cbc510e9dc4946e740286011b0c4d7bb76fe6d115c5fed715816c6144926"
BASE_ID_DIGEST = "e7930a7c374c5b3efe1f066eb4ccf511c0c7690c30afc2f7b2583d26d2b6981e"
PUBLISHED_ID_DIGEST = "9016935eea6c6c7b3c56ee280a1467f74b4d7b60f2fc10f17e1ed3baa0fb42bd"
TIMESTAMP_PAIR_DIGEST = "0f742e2f37bb9c6bfffb7e0d109f8025e5350e6416175c983e79bf8fb8b6fdd0"
NATIVE_FRAME_DIGEST = "f3c42f03fc0280c14910dc4203fc8031b9d5cddcc0cc8a6431c3c9268602aec0"
NATIVE_SCHEMA = generate_catalogue.NATIVE_SCHEMA


def _canonical_digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _products() -> pl.DataFrame:
    return pl.read_parquet(CATALOGUE_PATH / "products.parquet")


def _stations() -> pl.DataFrame:
    return pl.read_parquet(CATALOGUE_PATH / "stations.parquet")


def _station_products() -> pl.DataFrame:
    return pl.read_parquet(CATALOGUE_PATH / "station_products.parquet")


def _provider() -> dict[str, object]:
    return json.loads((CATALOGUE_PATH / "provider.json").read_text())


def _page(station_id: str, *, coordinate: str = "北緯 35度41分04秒 東経 139度24分47秒") -> bytes:
    values = {
        "観測所名": f"name-{station_id}",
        "観測項目": "水位流量",
        "観測所記号": station_id,
        "水系名": "水系",
        "河川名": "河川",
        "観測所管理者名": "管理者",
        "観測所種別": "",
        "観測開始時期": "1962年01月01日",
        "所在地": "所在地&nbsp;",
        "河口または合流点からの距離": "1.00km",
        "世界測地系": coordinate,
        "日本測地系": "",
        "流域面積": "2.00km2",
        "零点高": "0.000m",
    }
    rows = "".join(
        f"<TR><TD>{key}</TD><TD>{'<BR>' if value == '' else value}</TD></TR>" for key, value in values.items()
    )
    return f"<HTML><TABLE>{rows}</TABLE></HTML>".encode("euc-jp")


def _timestamps(ids: list[str]) -> dict[str, RetrievedAt]:
    return {
        station_id: RetrievedAt(datetime(2026, 8, 2, 19, 35, 42, tzinfo=UTC) + timedelta(seconds=index))
        for index, station_id in enumerate(ids)
    }


def _native_for(ids: list[str]) -> NativeTable:
    return generate_catalogue.refresh_native_table(
        {station_id: _page(station_id) for station_id in ids},
        station_ids=ids,
        retrieved_at_by_station=_timestamps(ids),
    ).value


def test_legacy_parser_rejects_source_confirmed_absence() -> None:
    html = REJECTED_PATH.read_bytes().decode("euc-jp", errors="replace")
    with pytest.raises(FatalContractError, match="307051287711040"):
        generate_catalogue._parse_site_detail_html(html)


def test_products_count() -> None:
    assert _products().height == 4


def test_products_ids() -> None:
    assert set(_products()["product_id"]) == {
        "stage_daily_mean",
        "discharge_daily_mean",
        "stage_hourly_mean",
        "discharge_hourly_mean",
    }


def test_canonical_products_have_correct_units() -> None:
    products = _products()
    assert products.filter(pl.col("product_id") == "stage_daily_mean")["unit"][0] == "m"
    assert products.filter(pl.col("product_id") == "discharge_daily_mean")["unit"][0] == "m3/s"


def test_provider_specific_products_have_correct_frequency() -> None:
    row = _products().filter(pl.col("product_id") == "stage_hourly_mean")
    assert row["frequency"][0] == "hourly"
    assert row["statistic"][0] == "mean"


def test_product_metadata_contains_kind() -> None:
    for row in _products().iter_rows(named=True):
        assert isinstance(json.loads(row["metadata"])["kind"], int)


def test_stations_count() -> None:
    assert _stations().height == 1024


def test_stations_have_unknown_crs() -> None:
    assert _stations()["crs"].unique().to_list() == ["unknown"]


def test_stations_have_exact_schema() -> None:
    assert _stations().schema == STATION_CATALOG_SCHEMA.polars_schema


def test_known_station_present() -> None:
    assert "301011281104010" in _stations()["station_id"].to_list()


def test_stations_have_valid_coordinates() -> None:
    stations = _stations()
    assert stations["latitude"].null_count() == stations["longitude"].null_count() == 0
    assert stations["latitude"].min() >= 20.0 and stations["latitude"].max() <= 50.0
    assert stations["longitude"].min() >= 120.0 and stations["longitude"].max() <= 155.0


def test_station_products_count() -> None:
    assert _station_products().height == 4096


def test_station_products_availability_unknown() -> None:
    assert _station_products()["availability"].cast(pl.Utf8).unique().to_list() == ["unknown"]


def test_provider_info_id() -> None:
    assert _provider()["provider_id"] == "jp_mlit"


def test_provider_info_catalogue_version() -> None:
    assert _provider()["catalogue_version"] == "2026-06-03"


def test_provider_info_live_flags_false() -> None:
    provider = _provider()
    assert provider["live_stations"] is provider["live_products"] is provider["live_station_products"] is False


def test_catalogue_validates_without_error() -> None:
    validate_catalogue(
        pl.DataFrame([_provider()], schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema),
        PROVIDER_INFO_CATALOG_SCHEMA,
        on_issue="raise",
    )
    validate_catalogue(_products(), PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(_stations(), STATION_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(_station_products(), STATION_PRODUCT_CATALOG_SCHEMA, on_issue="raise")


def test_packaged_catalogue_loads() -> None:
    from rivretrieve._internal.providers.jp_mlit import module

    assert module._artifact() is not None


def test_packaged_stations_count() -> None:
    from rivretrieve._internal.providers.jp_mlit import module

    assert module.stations().data.height == 1024


def test_packaged_products_count() -> None:
    from rivretrieve._internal.providers.jp_mlit import module

    assert module.products().data.height == 4


def test_packaged_station_products_count() -> None:
    from rivretrieve._internal.providers.jp_mlit import module

    assert module.station_products().data.height == 4096


def test_tracked_fixture_is_exact_native_subset() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text())
    assert len(fixture) == 3
    assert [row["観測所記号"] for row in fixture] == FIXTURE_IDS
    assert all(set(row) == set(generate_catalogue.NATIVE_COLUMNS) for row in fixture)
    assert all("gauge_id" not in row and "retrieved_at" not in row for row in fixture)
    assert _canonical_digest(fixture) == FIXTURE_DIGEST


def test_base_packaged_ids_are_pinned() -> None:
    ids = _stations()["station_id"].to_list()
    assert len(ids) == len(set(ids)) == 1024 and ids == sorted(ids)
    assert _canonical_digest(ids) == BASE_ID_DIGEST


def test_legacy_api_presence() -> None:
    for name in (
        "GeneratedJpMlitCatalogue",
        "generate_catalogue_from_fixture",
        "generate_catalogue",
        "generate_catalogue_from_live",
        "validate_generated_catalogue",
    ):
        assert hasattr(generate_catalogue, name)


def test_module_docstring_contains_native_denotation() -> None:
    assert (
        "refresh_native_table : Responses × StationIds × RetrievedAtByStation × PriorNativeTable? → WithIssues[NativeTable]"
        in (generate_catalogue.__doc__ or "")
    )


def test_urlopen_call_sites_and_native_reachability() -> None:
    tree = ast.parse(Path(generate_catalogue.__file__).read_text())
    owners: list[str] = []
    calls_by_function: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            calls_by_function[node.name] = {
                call.func.id
                for call in ast.walk(node)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            }
            if any(
                isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "urlopen"
                for call in ast.walk(node)
            ):
                owners.append(node.name)
    assert sorted(owners) == ["_fetch_site_detail", "_fetch_site_detail_response"]
    assert "_fetch_site_detail_response" in calls_by_function["refresh_native_table_from_live"]
    assert "_fetch_site_detail" not in calls_by_function["refresh_native_table_from_live"]


CORE_TOKENS = [
    "station-id-type",
    "station-id-blank",
    "station-id-duplicate",
    "response-keys-missing",
    "response-keys-extra",
    "timestamp-keys-missing",
    "timestamp-keys-extra",
    "retrieved-at-utc",
    "prior-id-duplicate",
    "prior-schema",
    "station-id-disagreement",
]


@pytest.mark.parametrize("token", CORE_TOKENS)
def test_refresh_contract_guard_message(token: str) -> None:
    ids: list[object] = ["100000000000001", "100000000000002"]
    responses = {station_id: _page(station_id) for station_id in ids if isinstance(station_id, str)}
    timestamps = _timestamps([station_id for station_id in ids if isinstance(station_id, str)])
    prior: NativeTable | None = None
    if token == "station-id-type":
        ids[1] = 2
    elif token == "station-id-blank":
        ids[1] = ""
    elif token == "station-id-duplicate":
        ids[1] = ids[0]
    elif token == "response-keys-missing":
        responses.pop("100000000000002")
    elif token == "response-keys-extra":
        responses["100000000000003"] = _page("100000000000003")
    elif token == "timestamp-keys-missing":
        timestamps.pop("100000000000002")
    elif token == "timestamp-keys-extra":
        timestamps["100000000000003"] = next(iter(timestamps.values()))
    elif token == "retrieved-at-utc":
        forged = object.__new__(RetrievedAt)
        object.__setattr__(forged, "value", datetime(2026, 8, 2))
        timestamps["100000000000002"] = forged
    elif token == "prior-id-duplicate":
        base = _native_for(["100000000000001", "100000000000002"])
        prior = NativeTable(pl.concat([base.data, base.data.head(1)]))
    elif token == "prior-schema":
        base = _native_for(["100000000000001", "100000000000002"])
        prior = NativeTable(base.data.drop("観測所名"))
    elif token == "station-id-disagreement":
        responses["100000000000002"] = _page("100000000000003")
    with pytest.raises(FatalContractError, match=token):
        generate_catalogue.refresh_native_table(
            responses,
            station_ids=ids,
            retrieved_at_by_station=timestamps,
            prior=prior,
        )


FATAL_FAMILIES = ["minimum", "uncarryable", "malformed"]


@pytest.mark.parametrize("family", FATAL_FAMILIES)
def test_fatal_message_family(family: str, monkeypatch: pytest.MonkeyPatch) -> None:
    if family == "minimum":
        monkeypatch.setattr(
            generate_catalogue, "_fetch_site_detail_response", lambda station_id: pytest.fail(station_id)
        )
        with pytest.raises(FatalContractError) as caught:
            generate_catalogue.refresh_native_table_from_live(["100000000000001", "100000000000002"])
        assert all(token in str(caught.value) for token in ("jp_mlit", "2", "minimum 500"))
    elif family == "uncarryable":
        station_id = "100000000000001"
        with pytest.raises(FatalContractError) as caught:
            generate_catalogue.refresh_native_table(
                {station_id: b"not a station page"},
                station_ids=[station_id],
                retrieved_at_by_station=_timestamps([station_id]),
            )
        assert all(
            token in str(caught.value) for token in ("jp_mlit", station_id, "refresh_response_rejected", "no prior row")
        )
    else:
        with pytest.raises(FatalContractError) as caught:
            generate_catalogue.refresh_native_table({}, station_ids=[2], retrieved_at_by_station={})
        assert "jp_mlit" in str(caught.value) and "station-id-type" in str(caught.value)


ISSUE_CODES = [
    "station_not_published",
    "refresh_response_rejected",
    "refresh_decode_failed",
    "invalid_station_coordinates",
    "refresh_request_failed",
    "refresh_http_failed",
]


@pytest.mark.parametrize("code", ISSUE_CODES)
def test_refresh_issue_code(code: str, monkeypatch: pytest.MonkeyPatch) -> None:
    station_id = "100000000000001"
    if code in {"refresh_request_failed", "refresh_http_failed"}:
        ids = [f"{index:015d}" for index in range(500)]
        prior = _native_for(ids)
        monkeypatch.setattr(generate_catalogue.time, "sleep", lambda value: None)

        def fetch(requested: str) -> tuple[int, bytes]:
            if requested == ids[0]:
                if code == "refresh_request_failed":
                    raise OSError("request boom")
                raise generate_catalogue.urllib.error.HTTPError(
                    f"{generate_catalogue.SITE_INFO_DETAIL_URL}?ID={requested}",
                    503,
                    "http boom",
                    None,
                    None,
                )
            return 200, _page(requested)

        monkeypatch.setattr(generate_catalogue, "_fetch_site_detail_response", fetch)
        outcome = generate_catalogue.refresh_native_table_from_live(ids, prior=prior)
        issue = outcome.issues[0]
        station_id = ids[0]
    else:
        prior = _native_for([station_id])
        if code == "station_not_published":
            body = REJECTED_PATH.read_bytes().replace(b"307051287711040", station_id.encode())
            prior_arg = prior
        elif code == "refresh_response_rejected":
            body = b"generic HTTP 200 body"
            prior_arg = prior
        elif code == "refresh_decode_failed":
            body = generate_catalogue._SOURCE_MARKER + b"\xff"
            prior_arg = prior
        else:
            body = _page(station_id, coordinate="not DMS")
            prior_arg = prior
        outcome = generate_catalogue.refresh_native_table(
            {station_id: body},
            station_ids=[station_id],
            retrieved_at_by_station=_timestamps([station_id]),
            prior=prior_arg,
        )
        issue = outcome.issues[0]
    assert issue.code == code
    assert issue.provider_id == "jp_mlit" and issue.severity == "warning"
    assert station_id in issue.message and code in issue.message
    assert issue.details is not None and issue.details["station_id"] == station_id and issue.details["reason"]


def test_failures_carry_whole_prior_row_and_fresh_rows() -> None:
    ids = ["100000000000001", "100000000000002"]
    prior = _native_for(ids)
    new_times = {station_id: RetrievedAt(datetime(2026, 8, 3, tzinfo=UTC)) for station_id in ids}
    outcome = generate_catalogue.refresh_native_table(
        {ids[0]: b"bad", ids[1]: _page(ids[1])},
        station_ids=ids,
        retrieved_at_by_station=new_times,
        prior=prior,
    )
    pl_testing.assert_frame_equal(
        outcome.value.data.filter(pl.col("観測所記号") == ids[0]),
        prior.data.filter(pl.col("観測所記号") == ids[0]),
        check_exact=True,
    )
    assert outcome.value.data.filter(pl.col("観測所記号") == ids[1])["retrieved_at"][0] == new_times[ids[1]].value


def _write_synthetic_capture(root: Path) -> tuple[Path, Path, Path, Path, dict[str, Any]]:
    ids = ["100000000000001", "100000000000002"]
    station_catalogue = root / "stations.parquet"
    pl.DataFrame({"station_id": ids}).write_parquet(station_catalogue)
    responses = root / "responses"
    responses.mkdir()
    accepted = _page(ids[0])
    (responses / f"{ids[0]}.html").write_bytes(accepted)
    rejected_name = "rejected.html"
    rejected = f"指定された観測所記号({ids[1]})の観測所諸元は存在しません。".encode("euc-jp")
    (root / rejected_name).write_bytes(rejected)
    url = generate_catalogue.SITE_INFO_DETAIL_URL
    manifest: dict[str, Any] = {
        "campaign_started_utc": "2026-08-02T19:35:42Z",
        "campaign_ended_utc": "2026-08-02T19:50:45Z",
        "requested": 2,
        "stored": 1,
        "rejected": 1,
        "request_url_template": f"{url}?ID=<station_id>",
        "encoding": "EUC-JP",
        "acceptance_rule": "HTTP 200 AND response body contains EUC-JP bytes for 世界測地系",
        "entries": [
            {
                "station_id": ids[0],
                "url": f"{url}?ID={ids[0]}",
                "file": f"{ids[0]}.html",
                "bytes": len(accepted),
                "sha256": hashlib.sha256(accepted).hexdigest(),
                "http_status": 200,
                "retrieved_at": "2026-08-02T19:35:42Z",
            }
        ],
        "failures": [
            {
                "station_id": ids[1],
                "url": f"{url}?ID={ids[1]}",
                "file": rejected_name,
                "bytes": len(rejected),
                "sha256": hashlib.sha256(rejected).hexdigest(),
                "http_status": 200,
                "retrieved_at": "2026-08-02T22:52:24Z",
                "has_marker": False,
            }
        ],
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    return station_catalogue, responses, manifest_path, root / "native.parquet", manifest


MANIFEST_TOKENS = [
    "manifest-missing",
    "manifest-not-object",
    "manifest-counts",
    "manifest-entry-missing-field",
    "manifest-binding-type",
    "manifest-binding-blank",
    "manifest-duplicate-station",
    "manifest-duplicate-file",
    "manifest-request-set",
    "manifest-url",
    "manifest-filename",
    "manifest-http-status",
    "manifest-payload-missing",
    "manifest-payload-extra",
    "manifest-byte-count",
    "manifest-sha256",
    "manifest-retrieved-at",
    "manifest-acceptance-marker",
    "manifest-rejection",
]


@pytest.mark.parametrize("token", MANIFEST_TOKENS)
def test_manifest_guard_message(token: str, tmp_path: Path) -> None:
    station_catalogue, responses, manifest_path, output, manifest = _write_synthetic_capture(tmp_path)
    if token == "manifest-missing":
        manifest_path.unlink()
    elif token == "manifest-not-object":
        manifest = []
    elif token == "manifest-counts":
        manifest["requested"] = 3
    elif token == "manifest-entry-missing-field":
        manifest["entries"][0].pop("bytes")
    elif token == "manifest-binding-type":
        manifest["entries"][0]["station_id"] = 1
    elif token == "manifest-binding-blank":
        manifest["entries"][0]["station_id"] = ""
    elif token == "manifest-duplicate-station":
        manifest["failures"][0]["station_id"] = manifest["entries"][0]["station_id"]
    elif token == "manifest-duplicate-file":
        manifest["failures"][0]["file"] = manifest["entries"][0]["file"]
    elif token == "manifest-request-set":
        manifest["failures"][0]["station_id"] = "100000000000003"
        manifest["failures"][0]["url"] = f"{generate_catalogue.SITE_INFO_DETAIL_URL}?ID=100000000000003"
    elif token == "manifest-url":
        manifest["entries"][0]["url"] = "wrong"
    elif token == "manifest-filename":
        manifest["entries"][0]["file"] = "wrong.html"
    elif token == "manifest-http-status":
        manifest["entries"][0]["http_status"] = 500
    elif token == "manifest-payload-missing":
        (responses / manifest["entries"][0]["file"]).unlink()
    elif token == "manifest-payload-extra":
        (responses / "extra.html").write_bytes(b"extra")
    elif token == "manifest-byte-count":
        manifest["entries"][0]["bytes"] += 1
    elif token == "manifest-sha256":
        manifest["entries"][0]["sha256"] = "0" * 64
    elif token == "manifest-retrieved-at":
        manifest["entries"][0]["retrieved_at"] = "not-an-instant"
    elif token == "manifest-acceptance-marker":
        manifest["encoding"] = "UTF-8"
    elif token == "manifest-rejection":
        manifest["failures"][0]["has_marker"] = True
    if token != "manifest-missing":
        manifest_path.write_text(json.dumps(manifest))
    output.write_bytes(b"sentinel")
    with pytest.raises(FatalContractError, match=token):
        generate_catalogue.main(
            [
                "--station-catalogue",
                str(station_catalogue),
                "--responses-dir",
                str(responses),
                "--manifest",
                str(manifest_path),
                "--native-out",
                str(output),
            ]
        )
    assert output.read_bytes() == b"sentinel"


def test_supplied_capture_cli_is_atomic_and_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    station_catalogue, responses, manifest_path, output, _ = _write_synthetic_capture(tmp_path)
    monkeypatch.setattr(generate_catalogue.urllib.request, "urlopen", lambda *args, **kwargs: pytest.fail("network"))
    assert (
        generate_catalogue.main(
            [
                "--station-catalogue",
                str(station_catalogue),
                "--responses-dir",
                str(responses),
                "--manifest",
                str(manifest_path),
                "--native-out",
                str(output),
            ]
        )
        == 0
    )
    table = read_native_table(output)
    assert table.data.height == 1


def test_rejected_response_transport_and_absence_issue(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    body = REJECTED_PATH.read_bytes()

    class Response(io.BytesIO):
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(generate_catalogue.urllib.request, "urlopen", lambda request, timeout: Response(body))
    status, fetched = generate_catalogue._fetch_site_detail_response("307051287711040")
    assert status == 200 and fetched == body and generate_catalogue._SOURCE_MARKER not in body
    outcome = generate_catalogue.refresh_native_table(
        {"307051287711040": fetched},
        station_ids=["307051287711040"],
        retrieved_at_by_station=_timestamps(["307051287711040"]),
        prior=_native_for(["307051287711040"]),
    )
    assert outcome.value.data.height == 0 and outcome.issues[0].code == "station_not_published"
    assert "source-confirmed absence" in outcome.issues[0].message
    assert "307051287711040" in fetched.decode("euc-jp")
    assert capsys.readouterr() == ("", "")


def test_committed_native_table_contract() -> None:
    native = read_native_table(NATIVE_PATH)
    assert native.data.schema == NATIVE_SCHEMA and native.data.schema["観測所記号"] == pl.Utf8
    ids = native.data["観測所記号"].to_list()
    assert len(ids) == len(set(ids)) == 1023 and ids == sorted(ids)
    assert "307051287711040" not in ids and _canonical_digest(ids) == PUBLISHED_ID_DIGEST
    times = native.data["retrieved_at"].to_list()
    assert len(set(times)) == 902
    assert min(times) == datetime(2026, 8, 2, 19, 35, 42, tzinfo=UTC)
    assert max(times) == datetime(2026, 8, 2, 19, 50, 44, tzinfo=UTC)
    assert all(
        datetime(2026, 8, 2, 19, 35, 42, tzinfo=UTC) <= value <= datetime(2026, 8, 2, 19, 50, 45, tzinfo=UTC)
        for value in times
    )
    pairs = [
        [row[0], row[1].strftime("%Y-%m-%dT%H:%M:%SZ")]
        for row in native.data.select("観測所記号", "retrieved_at").iter_rows()
    ]
    assert _canonical_digest(pairs) == TIMESTAMP_PAIR_DIGEST
    assert generate_catalogue.native_table_content_digest(native) == NATIVE_FRAME_DIGEST


def test_committed_native_source_states_and_fixture_records() -> None:
    native = read_native_table(NATIVE_PATH).data
    fixture = pl.DataFrame(
        json.loads(FIXTURE_PATH.read_text()), schema=dict.fromkeys(generate_catalogue.NATIVE_COLUMNS, pl.Utf8)
    )
    actual = native.filter(pl.col("観測所記号").is_in(FIXTURE_IDS)).select(generate_catalogue.NATIVE_COLUMNS)
    pl_testing.assert_frame_equal(actual, fixture, check_exact=True)
    assert native.filter(pl.col("観測所種別") == "").height == 3
    assert native.filter(pl.col("日本測地系") == "").height == 89
    assert (
        native.filter(
            pl.any_horizontal([pl.col(column).str.contains("\u00a0") for column in generate_catalogue.NATIVE_COLUMNS])
        ).height
        > 0
    )
    missing = native.filter(pl.col("観測所記号") == "302011282228100")
    assert missing["流域面積"][0] is None and missing["零点高"][0] is None


def test_native_coordinates_rematerialize_source_with_three_pinned_changes() -> None:
    native = read_native_table(NATIVE_PATH).data.select("観測所記号", "世界測地系")
    pattern = re.compile(r"北緯\s*(\d+)度(\d+)分(\d+)秒\s*東経\s*(\d+)度(\d+)分(\d+)秒")
    rows = []
    for station_id, text in native.iter_rows():
        match = pattern.fullmatch(text)
        assert match is not None
        lat_d, lat_m, lat_s, lon_d, lon_m, lon_s = map(int, match.groups())
        rows.append(
            {
                "station_id": station_id,
                "source_latitude": lat_d + lat_m / 60 + lat_s / 3600,
                "source_longitude": lon_d + lon_m / 60 + lon_s / 3600,
            }
        )
    joined = _stations().join(pl.DataFrame(rows), on="station_id")
    matches = joined.filter(
        (pl.col("latitude") - pl.col("source_latitude")).abs() < 1e-9,
        (pl.col("longitude") - pl.col("source_longitude")).abs() < 1e-9,
    )
    assert matches.height == 1020 and joined.height == 1023
    expected = {
        "302011282228100": (37.424166666666665, 140.52472222222224, 37.415277777777774, 140.48333333333332),
        "302011282218050": (37.81055555555555, 140.49499999999998, 37.81111111111111, 140.4958333333333),
        "308011288805010": (33.78361111111111, 132.87416666666667, 33.78333333333333, 132.8738888888889),
    }
    changed = joined.filter(pl.col("station_id").is_in(expected))
    assert changed.height == 3
    for row in changed.iter_rows(named=True):
        assert (row["latitude"], row["longitude"], row["source_latitude"], row["source_longitude"]) == expected[
            row["station_id"]
        ]
    assert "307051287711040" not in joined["station_id"].to_list()
