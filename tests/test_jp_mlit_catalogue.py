"""Tests for the jp_mlit packaged catalogue and native refresh."""

from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.request
from datetime import UTC, date, datetime, timedelta
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
from rivretrieve._internal.providers.jp_mlit.origins import STATION_CATALOGUE_ORIGINS
from tests._catalogue_projection import copy_catalogue_projection

CATALOGUE_PATH = Path("src/rivretrieve/_internal/providers/jp_mlit/catalogue")
FIXTURE_PATH = Path("tests/test_data/jp_mlit_metadata.json")
REJECTED_PATH = Path("tests/test_data/jp_mlit_site_info_detail_rejected_307051287711040.html")
NATIVE_PATH = CATALOGUE_PATH / "native.parquet"
LICENSE_RECORDING = Path("tests/test_data/jp_mlit_terms_licence_euc_jp.html")
CITATION_RECORDING = Path("tests/test_data/jp_mlit_terms_citation.pdf")
FIXTURE_IDS = ["301011281104010", "303051283310060", "309191289913130"]
ACCEPTED_SOURCE_FIXTURES = {
    "301011281104310": (
        Path("tests/test_data/jp_mlit_site_info_detail_accepted_301011281104310.html"),
        3199,
        "2727f485592f5cbf0fa31538a150c5ca2a6a571d12f224658629c821d27a9dd7",
        datetime(2026, 8, 2, 19, 35, 54, tzinfo=UTC),
    ),
    "301031281101220": (
        Path("tests/test_data/jp_mlit_site_info_detail_accepted_301031281101220.html"),
        3175,
        "bb9caa28f43a8c94f9c65c4929f6677b85266a4c0140ba2082254361f4954da3",
        datetime(2026, 8, 2, 19, 36, 18, tzinfo=UTC),
    ),
}
FIXTURE_DIGEST = "5002cbc510e9dc4946e740286011b0c4d7bb76fe6d115c5fed715816c6144926"
BASE_ID_DIGEST = "e7930a7c374c5b3efe1f066eb4ccf511c0c7690c30afc2f7b2583d26d2b6981e"
PUBLISHED_ID_DIGEST = "9016935eea6c6c7b3c56ee280a1467f74b4d7b60f2fc10f17e1ed3baa0fb42bd"
TIMESTAMP_PAIR_DIGEST = "0f742e2f37bb9c6bfffb7e0d109f8025e5350e6416175c983e79bf8fb8b6fdd0"
NATIVE_FRAME_DIGEST = "f3c42f03fc0280c14910dc4203fc8031b9d5cddcc0cc8a6431c3c9268602aec0"
CANONICAL_CONTENT_DIGESTS = {
    "products.parquet": "38aa480240734831a3fdb2e4b1a570c917054c8e6afd64a23eb5c2c6786195ad",
    "stations.parquet": "43f0369f650ec971fa49d507998f3e4e6104e4644a21204c43cef85e2227f1cb",
    "station_products.parquet": "7bdc3c07ac4e79fabcdf131bc7d2a2122bd254f488f227f533f942f3aac3948f",
    "provider.json": "104fe86853da0260c2556aff94253878cd51b60e5cacc8cdf5dee997e4d79fb9",
}
NATIVE_SCHEMA = generate_catalogue.NATIVE_SCHEMA


def _canonical_digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _normalized_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _frame_content_digest(frame: pl.DataFrame) -> str:
    return _canonical_digest(
        {
            "columns": frame.columns,
            "rows": [[_normalized_value(value) for value in row] for row in frame.iter_rows()],
        }
    )


@pytest.fixture(scope="module")
def _pristine_projection(retained_evidence_root):
    built = generate_catalogue.build_catalogue(
        read_native_table(retained_evidence_root / NATIVE_PATH), STATION_CATALOGUE_ORIGINS
    )
    return copy_catalogue_projection(built)


@pytest.fixture
def catalogue(_pristine_projection):
    return copy_catalogue_projection(_pristine_projection)


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


def test_rejected_response_fixture_identity(retained_evidence_root) -> None:
    body = (retained_evidence_root / REJECTED_PATH).read_bytes()
    assert len(body) == 489
    assert hashlib.sha256(body).hexdigest() == "2e83eed5a64cf91d9351f2abc28c151dec420a24265dd9db194fd7132bd31faf"
    assert body.count(generate_catalogue._SOURCE_MARKER) == 0


def test_products_count(catalogue) -> None:
    assert catalogue.products.height == 4


def test_products_ids(catalogue) -> None:
    assert set(catalogue.products["product_id"]) == {
        "stage_daily",
        "discharge_daily",
        "stage_hourly",
        "discharge_hourly",
    }


def test_canonical_products_have_correct_units(catalogue) -> None:
    products = catalogue.products
    assert products.filter(pl.col("product_id") == "stage_daily")["unit"][0] == "m"
    assert products.filter(pl.col("product_id") == "discharge_daily")["unit"][0] == "m3/s"


def test_provider_specific_products_have_correct_frequency(catalogue) -> None:
    row = catalogue.products.filter(pl.col("product_id") == "stage_hourly")
    assert row["frequency"][0] == "hourly"
    assert row["statistic"][0] == "unknown"
    assert catalogue.products["period_type"].unique().to_list() == ["unknown"]
    assert catalogue.products.filter(pl.col("product_id").str.ends_with("_daily"))["frequency"].to_list() == [
        "daily",
        "daily",
    ]


def test_product_native_ids_preserve_integer_kind_identity(catalogue) -> None:
    assert set(catalogue.products["native_id"]) == {"2", "3", "6", "7"}


def test_stations_count(catalogue) -> None:
    assert catalogue.stations.height == 1023


def test_stations_have_unknown_crs(catalogue) -> None:
    assert catalogue.stations["crs"].unique().to_list() == ["unknown"]


def test_stations_have_exact_schema(catalogue) -> None:
    assert catalogue.stations.schema == STATION_CATALOG_SCHEMA.polars_schema


def test_known_station_present(catalogue) -> None:
    assert "301011281104010" in catalogue.stations["station_id"].to_list()


def test_stations_have_valid_coordinates(catalogue) -> None:
    stations = catalogue.stations
    assert stations["latitude"].null_count() == stations["longitude"].null_count() == 0
    assert stations["latitude"].min() >= 20.0 and stations["latitude"].max() <= 50.0
    assert stations["longitude"].min() >= 120.0 and stations["longitude"].max() <= 155.0


def test_station_products_count(catalogue) -> None:
    assert catalogue.station_products.height == 4092


def test_station_products_availability_unknown(catalogue) -> None:
    assert catalogue.station_products["availability"].cast(pl.Utf8).unique().to_list() == ["unknown"]


def test_provider_info_id(catalogue) -> None:
    assert catalogue.provider_info["provider_id"] == "jp_mlit"


def test_provider_info_catalogue_version(catalogue) -> None:
    assert catalogue.provider_info["catalogue_version"] == "2026-08-02"


def test_provider_info_live_flags_false(catalogue) -> None:
    provider = catalogue.provider_info
    assert provider["live_stations"] is provider["live_products"] is provider["live_station_products"] is False


def test_provider_info_name_and_bulk_observation_description(catalogue) -> None:
    provider = catalogue.provider_info
    assert provider["name"] == "MLIT Water Information System — Japan national hydrometric network"
    assert provider["bulk_observations"] == (
        "true: monthly-window decomposition for hourly products (KINDs 2,6), "
        "yearly-window decomposition for daily products (KINDs 3,7); "
        "HTML request + one publisher-minted Shift-JIS DAT download per source window"
    )


def test_catalogue_validates_without_error(catalogue) -> None:
    validate_catalogue(
        pl.DataFrame([catalogue.provider_info], schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema),
        PROVIDER_INFO_CATALOG_SCHEMA,
        on_issue="raise",
    )
    validate_catalogue(catalogue.products, PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(catalogue.stations, STATION_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(catalogue.station_products, STATION_PRODUCT_CATALOG_SCHEMA, on_issue="raise")


def test_packaged_catalogue_loads() -> None:
    assert json.loads((CATALOGUE_PATH / "provider.json").read_text())["provider_id"] == "jp_mlit"


def test_packaged_stations_count() -> None:
    assert pl.read_parquet(CATALOGUE_PATH / "stations.parquet").height == 1023


def test_packaged_products_count() -> None:
    assert pl.read_parquet(CATALOGUE_PATH / "products.parquet").height == 4


def test_packaged_station_products_count() -> None:
    assert pl.read_parquet(CATALOGUE_PATH / "station_products.parquet").height == 4092


def test_retained_fixture_is_exact_native_subset(retained_evidence_root) -> None:
    fixture = json.loads((retained_evidence_root / FIXTURE_PATH).read_text())
    assert len(fixture) == 3
    assert [row["観測所記号"] for row in fixture] == FIXTURE_IDS
    assert all(set(row) == set(generate_catalogue.NATIVE_COLUMNS) for row in fixture)
    assert all("gauge_id" not in row and "retrieved_at" not in row for row in fixture)
    assert _canonical_digest(fixture) == FIXTURE_DIGEST


def test_base_packaged_ids_are_pinned(retained_evidence_root) -> None:
    published_ids = read_native_table(retained_evidence_root / NATIVE_PATH).data["観測所記号"].to_list()
    seed = sorted([*published_ids, "307051287711040"])
    assert len(seed) == len(set(seed)) == 1024 and seed == sorted(seed)
    assert all(isinstance(station_id, str) and len(station_id) == 15 and station_id.isdigit() for station_id in seed)
    assert _canonical_digest(seed) == BASE_ID_DIGEST


def test_catalogue_generation_surface_is_native_only() -> None:
    assert hasattr(generate_catalogue, "GeneratedJpMlitCatalogue")
    assert hasattr(generate_catalogue, "build_catalogue")
    for name in (
        "generate_catalogue_from_fixture",
        "generate_catalogue",
        "generate_catalogue_from_live",
        "validate_generated_catalogue",
    ):
        assert not hasattr(generate_catalogue, name)


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


FATAL_FAMILIES = ["uncarryable", "malformed"]


@pytest.mark.parametrize("family", FATAL_FAMILIES)
def test_fatal_message_family(family: str) -> None:
    if family == "uncarryable":
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
]


@pytest.mark.parametrize("code", ISSUE_CODES)
def test_refresh_issue_code(retained_evidence_root, code: str) -> None:
    station_id = "100000000000001"
    prior = _native_for([station_id])
    if code == "station_not_published":
        body = (retained_evidence_root / REJECTED_PATH).read_bytes().replace(b"307051287711040", station_id.encode())
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


def test_absence_response_for_different_station_is_rejected(retained_evidence_root) -> None:
    station_id = "100000000000001"
    prior = _native_for([station_id])
    outcome = generate_catalogue.refresh_native_table(
        {station_id: (retained_evidence_root / REJECTED_PATH).read_bytes()},
        station_ids=[station_id],
        retrieved_at_by_station=_timestamps([station_id]),
        prior=prior,
    )
    pl_testing.assert_frame_equal(outcome.value.data, prior.data, check_exact=True)
    assert [issue.code for issue in outcome.issues] == ["refresh_response_rejected"]
    assert station_id in outcome.issues[0].message


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
    "manifest-entry-marker-absent",
    "manifest-rejection",
    "manifest-rejection-marker-present",
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
    elif token == "manifest-entry-marker-absent":
        body = b"HTTP 200 response without the accepted source marker"
        (responses / manifest["entries"][0]["file"]).write_bytes(body)
        manifest["entries"][0]["bytes"] = len(body)
        manifest["entries"][0]["sha256"] = hashlib.sha256(body).hexdigest()
    elif token == "manifest-rejection":
        manifest["failures"][0]["has_marker"] = True
    elif token == "manifest-rejection-marker-present":
        body = _page(manifest["failures"][0]["station_id"])
        (tmp_path / manifest["failures"][0]["file"]).write_bytes(body)
        manifest["failures"][0]["bytes"] = len(body)
        manifest["failures"][0]["sha256"] = hashlib.sha256(body).hexdigest()
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
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: pytest.fail("network"))
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


def test_recorded_rejection_retains_source_absence(retained_evidence_root, capsys: pytest.CaptureFixture[str]) -> None:
    fetched = (retained_evidence_root / REJECTED_PATH).read_bytes()
    assert generate_catalogue._SOURCE_MARKER not in fetched
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


def test_retained_native_table_contract(retained_evidence_root) -> None:
    native = read_native_table(retained_evidence_root / NATIVE_PATH)
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


def test_retained_native_source_states_and_fixture_records(retained_evidence_root) -> None:
    native = read_native_table(retained_evidence_root / NATIVE_PATH).data
    fixture = pl.DataFrame(
        json.loads((retained_evidence_root / FIXTURE_PATH).read_text()),
        schema=dict.fromkeys(generate_catalogue.NATIVE_COLUMNS, pl.Utf8),
    )
    actual = native.filter(pl.col("観測所記号").is_in(FIXTURE_IDS)).select(generate_catalogue.NATIVE_COLUMNS)
    pl_testing.assert_frame_equal(actual, fixture, check_exact=True)
    assert native.filter(pl.col("観測所種別") == "").height == 3
    assert native.filter(pl.col("日本測地系") == "").height == 89
    assert (
        native.filter(
            pl.any_horizontal([pl.col(column).str.contains("BR") for column in generate_catalogue.NATIVE_COLUMNS])
        ).height
        == 0
    )
    assert (
        native.filter(
            pl.any_horizontal([pl.col(column).str.contains("\u00a0") for column in generate_catalogue.NATIVE_COLUMNS])
        ).height
        > 0
    )
    missing = native.filter(pl.col("観測所記号") == "302011282228100")
    assert missing["流域面積"][0] is None and missing["零点高"][0] is None


def test_retained_accepted_responses_rematerialize_exact_native_rows(retained_evidence_root) -> None:
    responses: dict[str, bytes] = {}
    retrieved_at_by_station: dict[str, RetrievedAt] = {}
    for station_id, (path, size, digest, instant) in ACCEPTED_SOURCE_FIXTURES.items():
        body = (retained_evidence_root / path).read_bytes()
        assert len(body) == size
        assert hashlib.sha256(body).hexdigest() == digest
        assert body.count(generate_catalogue._SOURCE_MARKER) == 1
        responses[station_id] = body
        retrieved_at_by_station[station_id] = RetrievedAt(instant)
    actual = generate_catalogue.refresh_native_table(
        responses,
        station_ids=list(ACCEPTED_SOURCE_FIXTURES),
        retrieved_at_by_station=retrieved_at_by_station,
    ).value.data
    expected = read_native_table(retained_evidence_root / NATIVE_PATH).data.filter(
        pl.col("観測所記号").is_in(list(ACCEPTED_SOURCE_FIXTURES))
    )
    pl_testing.assert_frame_equal(actual, expected, check_exact=True)
    assert actual.filter(pl.col("観測所記号") == "301031281101220")["日本測地系"].item() == ""
    assert actual.filter(pl.col("観測所記号") == "301011281104310")["流域面積"].item() == "\u00a0"


def test_native_coordinates_are_an_independent_exact_projection(retained_evidence_root, catalogue) -> None:
    native = read_native_table(retained_evidence_root / NATIVE_PATH).data.select("観測所記号", "世界測地系")
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
    stations = catalogue.stations
    assert stations.schema == STATION_CATALOG_SCHEMA.polars_schema
    assert stations["station_id"].dtype == pl.Utf8
    assert stations["crs"].unique().to_list() == ["unknown"]
    joined = stations.join(pl.DataFrame(rows), on="station_id")
    assert joined.height == 1023
    for row in joined.iter_rows(named=True):
        assert math.isclose(row["latitude"], row["source_latitude"], rel_tol=0, abs_tol=1e-12)
        assert math.isclose(row["longitude"], row["source_longitude"], rel_tol=0, abs_tol=1e-12)
    expected = {
        "302011282228100": (37.415277777777774, 140.48333333333332),
        "302011282218050": (37.81111111111111, 140.4958333333333),
        "308011288805010": (33.78333333333333, 132.8738888888889),
    }
    adopted = joined.filter(pl.col("station_id").is_in(expected))
    assert adopted.height == 3
    for row in adopted.iter_rows(named=True):
        assert (row["latitude"], row["longitude"]) == expected[row["station_id"]]
    assert "307051287711040" not in joined["station_id"].to_list()


def test_committed_canonical_components_have_pinned_full_content() -> None:
    for name in ("products.parquet", "stations.parquet", "station_products.parquet"):
        assert _frame_content_digest(pl.read_parquet(CATALOGUE_PATH / name)) == CANONICAL_CONTENT_DIGESTS[name]
    provider = json.loads((CATALOGUE_PATH / "provider.json").read_text())
    assert _canonical_digest(provider) == CANONICAL_CONTENT_DIGESTS["provider.json"]


def test_empty_native_table_fails_with_specific_message() -> None:
    empty = NativeTable(pl.DataFrame(schema=NATIVE_SCHEMA))
    with pytest.raises(FatalContractError) as caught:
        generate_catalogue.build_catalogue(empty, STATION_CATALOGUE_ORIGINS)
    assert str(caught.value) == "jp_mlit native table must not be empty"


def test_invalid_native_schema_fails_with_specific_message() -> None:
    native = _native_for(["100000000000001", "100000000000002"])
    invalid = NativeTable(native.data.with_columns(pl.col("観測所名").cast(pl.Int64, strict=False)))
    with pytest.raises(FatalContractError) as caught:
        generate_catalogue.build_catalogue(invalid, STATION_CATALOGUE_ORIGINS)
    assert str(caught.value) == "jp_mlit native table schema does not match NATIVE_SCHEMA"


def test_unparseable_dms_fails_with_station_specific_message() -> None:
    native = _native_for(["100000000000001", "100000000000002"])
    invalid = NativeTable(
        native.data.with_columns(
            pl.when(pl.col("観測所記号") == "100000000000002")
            .then(pl.lit("not a coordinate"))
            .otherwise(pl.col("世界測地系"))
            .alias("世界測地系")
        )
    )
    with pytest.raises(FatalContractError) as caught:
        generate_catalogue.build_catalogue(invalid, STATION_CATALOGUE_ORIGINS)
    assert str(caught.value) == (
        "jp_mlit station 100000000000002: 世界測地系 has no parseable whole-number DMS coordinate"
    )


def test_impossible_dms_fails_with_station_specific_message() -> None:
    native = _native_for(["100000000000001", "100000000000002"])
    invalid = NativeTable(
        native.data.with_columns(
            pl.when(pl.col("観測所記号") == "100000000000002")
            .then(pl.lit("北緯 35度41分61秒 東経 139度24分47秒"))
            .otherwise(pl.col("世界測地系"))
            .alias("世界測地系")
        )
    )
    with pytest.raises(FatalContractError) as caught:
        generate_catalogue.build_catalogue(invalid, STATION_CATALOGUE_ORIGINS)
    assert str(caught.value) == "jp_mlit station 100000000000002: 世界測地系 contains an impossible DMS coordinate"


def test_mixed_native_instants_drive_station_dates_and_maximum_version() -> None:
    native = _native_for(["100000000000001", "100000000000002"])
    native = NativeTable(
        native.data.with_columns(
            pl.when(pl.col("観測所記号") == "100000000000002")
            .then(pl.lit(datetime(2026, 8, 3, tzinfo=UTC)))
            .otherwise(pl.col("retrieved_at"))
            .cast(pl.Datetime("us", "UTC"))
            .alias("retrieved_at")
        )
    )
    catalogue = generate_catalogue.build_catalogue(native, STATION_CATALOGUE_ORIGINS)
    assert catalogue.stations["station_id"].dtype == pl.Utf8
    dates = dict(catalogue.station_products.select("station_id", "last_catalogue_check").unique().iter_rows())
    assert dates == {"100000000000001": datetime(2026, 8, 2).date(), "100000000000002": datetime(2026, 8, 3).date()}
    assert catalogue.provider_info["catalogue_version"] == "2026-08-03"


def test_each_station_product_date_is_its_native_station_date(retained_evidence_root, catalogue) -> None:
    native_dates = read_native_table(retained_evidence_root / NATIVE_PATH).data.select(
        pl.col("観測所記号").alias("station_id"), pl.col("retrieved_at").dt.date().alias("native_date")
    )
    joined = catalogue.station_products.join(native_dates, on="station_id")
    assert joined.filter(pl.col("last_catalogue_check") != pl.col("native_date")).is_empty()
    assert catalogue.provider_info["catalogue_version"] == "2026-08-02"


def test_provider_info_is_exactly_the_reduced_carrier(catalogue) -> None:
    fresh = catalogue.provider_info
    committed = json.loads((CATALOGUE_PATH / "provider.json").read_text())
    assert fresh == committed
    assert tuple(fresh) == (
        "provider_id",
        "name",
        "live_stations",
        "live_products",
        "live_station_products",
        "bulk_observations",
        "catalogue_version",
        "license",
        "citation",
    )


def test_broken_longitude_origin_fails_with_full_gate_message(retained_evidence_root) -> None:
    longitude_origin = STATION_CATALOGUE_ORIGINS["longitude"]
    broken = {
        **STATION_CATALOGUE_ORIGINS,
        "longitude": type(longitude_origin)(type(longitude_origin.native_column)("missing")),
    }
    with pytest.raises(FatalContractError) as caught:
        generate_catalogue.build_catalogue(read_native_table(retained_evidence_root / NATIVE_PATH), broken)
    assert str(caught.value) == "jp_mlit.longitude: native column 'missing' does not exist"


@pytest.mark.parametrize("argument", ["--fixture", "--live", "--catalogue-date", "--verbose"])
def test_removed_cli_mode_is_rejected(argument: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        generate_catalogue.main([argument, "unused"])
    assert f"unrecognized arguments: {argument} unused" in capsys.readouterr().err


@pytest.mark.parametrize("arguments", [["--native", str(NATIVE_PATH)], ["--out", "catalogue"]])
def test_native_cli_requires_partner(arguments: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        generate_catalogue.main(arguments)
    assert "jp_mlit native mode requires both --native and --out" in capsys.readouterr().err


def test_native_cli_requires_source_statement_recordings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        generate_catalogue.main(["--native", str(NATIVE_PATH), "--out", str(tmp_path)])
    assert "jp_mlit native mode requires license and citation recordings" in capsys.readouterr().err


@pytest.mark.parametrize(
    "arguments",
    [
        ["--responses-dir", "responses", "--manifest", "manifest.json", "--native-out", "native.parquet"],
        ["--station-catalogue", "stations.parquet", "--manifest", "manifest.json", "--native-out", "native.parquet"],
        ["--station-catalogue", "stations.parquet", "--responses-dir", "responses", "--native-out", "native.parquet"],
        ["--station-catalogue", "stations.parquet", "--responses-dir", "responses", "--manifest", "manifest.json"],
    ],
)
def test_capture_cli_requires_all_partners(arguments: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        generate_catalogue.main(arguments)
    assert (
        "jp_mlit supplied-capture mode requires --station-catalogue, --responses-dir, --manifest, and --native-out"
        in capsys.readouterr().err
    )


def test_cli_rejects_mixed_modes(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        generate_catalogue.main(["--native", str(NATIVE_PATH), "--station-catalogue", "stations.parquet"])
    assert "jp_mlit modes cannot mix native-build and supplied-capture arguments" in capsys.readouterr().err


def test_native_cli_is_offline_and_byte_deterministic(
    retained_evidence_root, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        calls.append("called")
        raise AssertionError((args, kwargs))

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    before = (retained_evidence_root / NATIVE_PATH).read_bytes()
    assert (
        generate_catalogue.main(
            [
                "--native",
                str(retained_evidence_root / NATIVE_PATH),
                "--out",
                str(tmp_path),
                "--license-recording",
                str(retained_evidence_root / LICENSE_RECORDING),
                "--citation-recording",
                str(retained_evidence_root / CITATION_RECORDING),
            ]
        )
        == 0
    )
    assert calls == [] and (retained_evidence_root / NATIVE_PATH).read_bytes() == before
    expected_names = {
        "croissant.json",
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
    }
    assert {item.name for item in tmp_path.iterdir()} == expected_names
    for name in expected_names:
        assert (tmp_path / name).read_bytes() == (CATALOGUE_PATH / name).read_bytes()


@pytest.mark.parametrize("statement_kind", ["license", "citation"])
def test_native_cli_rejects_statement_absent_from_recording(
    retained_evidence_root,
    statement_kind: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provenance = generate_catalogue.build_acquisition_provenance()
    source = provenance.source_records[0]
    statements = tuple(
        statement.model_copy(update={"exact_text": "この引用は記録に存在しません。"})
        if statement.kind == statement_kind
        else statement
        for statement in source.statements
    )
    changed = provenance.model_copy(update={"source_records": (source.model_copy(update={"statements": statements}),)})
    monkeypatch.setattr(generate_catalogue, "build_acquisition_provenance", lambda: changed)

    with pytest.raises(
        FatalContractError,
        match=rf"jp_mlit.{statement_kind}: quotation is absent from recorded bytes",
    ):
        generate_catalogue.main(
            [
                "--native",
                str(retained_evidence_root / NATIVE_PATH),
                "--out",
                str(tmp_path / "catalogue"),
                "--license-recording",
                str(retained_evidence_root / LICENSE_RECORDING),
                "--citation-recording",
                str(retained_evidence_root / CITATION_RECORDING),
            ]
        )


def test_native_build_removes_withheld_fact_before_writing(retained_evidence_root, tmp_path: Path) -> None:
    provenance = generate_catalogue.build_acquisition_provenance()
    payload = provenance.model_dump(mode="json")
    product_binding = next(item for item in payload["fact_bindings"] if item["fact_group"] == "product_catalogue")
    product_binding["facts"].remove("product.native_id")
    payload["withheld_facts"].append(
        {
            "fact_group": "withheld_product_native_id",
            "facts": ["product.native_id"],
            "reason": "no_acquisition_record_established",
        }
    )
    withheld = type(provenance).model_validate(payload)

    catalogue = generate_catalogue.build_catalogue(
        read_native_table(
            (retained_evidence_root / NATIVE_PATH), expected_sha256=generate_catalogue.NATIVE_TABLE_SHA256
        ),
        STATION_CATALOGUE_ORIGINS,
        withheld,
    )
    generate_catalogue.write_catalogue(catalogue, tmp_path)

    written = pl.read_parquet(tmp_path / "products.parquet")
    assert written["native_id"].null_count() == written.height
    written_provenance = json.loads((tmp_path / "provenance.json").read_text())
    assert written_provenance["withheld_facts"] == [
        {
            "fact_group": "withheld_product_native_id",
            "facts": ["product.native_id"],
            "reason": "no_acquisition_record_established",
        }
    ]


def test_catalogue_builder_has_no_automated_collection_seam() -> None:
    assert not hasattr(generate_catalogue, "refresh_native_table_from_live")
    assert not hasattr(generate_catalogue, "_fetch_site_detail_response")
