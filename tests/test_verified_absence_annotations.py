"""Regression checks for the six verified-absence providers (#823-#828)."""

from __future__ import annotations

import json
import shutil
import zipfile
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import openpyxl
import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.observations import ObservationDataSchema
from rivretrieve._internal.providers.pl_imgw.bulk import MONTHLY_URL_TEMPLATE, ImgwCompileRequest, compile_imgw
from rivretrieve._internal.providers.pl_imgw.config import config as imgw_config
from rivretrieve._internal.providers.pl_imgw.declaration import declaration as imgw_declaration
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from rivretrieve._internal.registry import ProviderRegistry
from rivretrieve._internal.source_annotations import CATALOG_SCHEMA
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.transport import TransportRequest, TransportResponse

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_TEST_DATA = Path("tests/test_data")
_RETRIEVED_AT = datetime(2026, 9, 28, tzinfo=UTC)
_QC_ISSUE_TOKENS = ("status", "quality", "flag", "annotation")


def _assert_verified_absence_result(result: object, *, bundle_path: Path) -> None:
    catalog = rr.annotations(result)
    assert catalog.is_empty()
    assert catalog.schema == CATALOG_SCHEMA
    projected = result.to_polars(annotations=True)
    assert list(projected.columns) == list(ObservationDataSchema.polars_schema)
    pl_testing.assert_frame_equal(projected, result.data)
    series_plain = rr.series(result)
    series_ann = rr.series(result, annotations=True)
    assert list(series_ann.columns) == list(series_plain.columns)
    pl_testing.assert_frame_equal(series_ann, series_plain)
    assert not any(any(token in issue.code.lower() for token in _QC_ISSUE_TOKENS) for issue in result.issues)

    bundle_path.write_bytes(rr.to_bundle(result))
    restored = rr.from_bundle(bundle_path.read_bytes())
    assert rr.annotations(restored).is_empty()
    assert list(restored.to_polars(annotations=True).columns) == list(ObservationDataSchema.polars_schema)
    assert list(rr.series(restored, annotations=True).columns) == list(series_plain.columns)


def _register_imgw_store(monkeypatch: pytest.MonkeyPatch, store_dir: Path) -> None:
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact

    registry = ProviderRegistry()
    registry.register(
        "pl_imgw",
        load_packaged_catalogue_artifact(imgw_declaration.catalogue, on_issue="raise"),
        bulk_config=imgw_config,
        observation_store=StoreRoot(store_dir),
    )
    monkeypatch.setattr(discovery, "_registry", registry)
    monkeypatch.setattr(discovery, "_provider_lookup", registry.get)
    monkeypatch.setattr(discovery, "_ensure_default_providers_registered", lambda: None)

    class _NoNetwork:
        def send(self, request: TransportRequest) -> TransportResponse:
            raise AssertionError("Compiled store retrieval must not contact network")

    monkeypatch.setattr(discovery, "HttpClient", _NoNetwork)


def _ba_workbook_bytes(rows: list[tuple[datetime, float | None]]) -> bytes:
    document = openpyxl.Workbook()
    sheet = document.active
    for row in [
        ("#Station Name", "Authored station"),
        ("#Station Number", "4024"),
        ("#Station Parameter Name", "Vodostaj"),
        ("#Timeseries Name", "81 Web Kontinuirani"),
        ("#Unit Symbol", "cm"),
        ("#Rows", len(rows)),
        ("#", None),
        ("#Timestamp", "Value"),
        *rows,
    ]:
        sheet.append(row)
    stream = BytesIO()
    document.save(stream)
    document.close()
    return stream.getvalue()


def test_pl_imgw_compiled_store_emits_no_annotations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    zip_path = tmp_path / "codz_2024_03.zip"
    record = (" 152140020", "GORZOW", "Warta (18)", "2024", "03", "15", "120", "1.500", "5.2", "01")
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("codz_2024_03.csv", (";".join(record) + "\r\n").encode("cp1250"))

    store_dir = tmp_path / "store"
    compile_imgw(
        ImgwCompileRequest(
            zip_path,
            StoreRoot(store_dir),
            MONTHLY_URL_TEMPLATE.format(year=2024, month=3),
            date(2024, 1, 31),
            _RETRIEVED_AT,
            "0.1.49",
        )
    )
    _register_imgw_store(monkeypatch, store_dir)

    selection = rr.find(provider="pl_imgw", station="152140020")
    result = rr.fetch(selection, start="2024-01-15", end="2024-01-15", on_issue="ignore")
    assert result.data.height == 3
    _assert_verified_absence_result(result, bundle_path=tmp_path / "pl_imgw.rr")


def test_ba_fhmzbih_offline_emits_no_annotations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    workbook = _ba_workbook_bytes([(datetime(2025, 9, 4), 10.0), (datetime(2025, 9, 5), 20.0)])

    class _BaTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            is_meta = request.url.endswith("index.json")
            content = (
                json.dumps([{"metadata_station_no": "4024", "metadata_site_no": "test"}]).encode("utf-8")
                if is_meta
                else workbook
            )
            content_type = (
                "application/json" if is_meta else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            return TransportResponse(content, 200, _RETRIEVED_AT, content_type, request.url, dict(request.params or {}))

    monkeypatch.setattr(discovery, "HttpClient", lambda: _BaTransport())
    selection = rr.find(provider="ba_fhmzbih", station="4024", quantity="stage")
    result = rr.fetch(selection, start="2025-09-04", end="2025-09-05", cache="bypass", on_issue="ignore")
    assert result.data.height == 2
    _assert_verified_absence_result(result, bundle_path=tmp_path / "ba_fhmzbih.rr")


def test_cz_chmi_offline_emits_no_annotations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    doc = {
        "objID": "0-203-1-000400",
        "tsList": [
            {
                "tsConID": "QD",
                "unit": "M3_S",
                "tsData": {
                    "type": "DataCollection",
                    "data": {
                        "header": "DT,VAL",
                        "values": [["2023-06-01T00:00:00Z", 1.25], ["2023-06-02T00:00:00Z", 1.50]],
                    },
                },
            }
        ],
    }

    class _CzTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            return TransportResponse(
                json.dumps(doc).encode("utf-8"),
                200,
                _RETRIEVED_AT,
                "application/json",
                request.url,
                dict(request.params or {}),
            )

    monkeypatch.setattr(discovery, "HttpClient", lambda: _CzTransport())
    selection = rr.find(
        provider="cz_chmi",
        station="0-203-1-000400",
        quantity="discharge",
        frequency="P1D",
        statistic="mean",
    )
    result = rr.fetch(selection, start="2023-06-01", end="2023-06-02", cache="bypass", on_issue="ignore")
    assert result.data.height == 2
    _assert_verified_absence_result(result, bundle_path=tmp_path / "cz_chmi.rr")


def test_lt_lhmt_offline_emits_no_annotations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    doc = {
        "station": {"code": "anyksciu-vms"},
        "observations": [
            {"observationDateUtc": "2023-06-03", "waterDischarge": 12.5, "waterLevel": 140},
            {"observationDateUtc": "2023-06-04", "waterDischarge": 11.0, "waterLevel": 135},
        ],
    }

    class _LtTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            return TransportResponse(
                json.dumps(doc).encode("utf-8"),
                200,
                _RETRIEVED_AT,
                "application/json",
                request.url,
                dict(request.params or {}),
            )

    monkeypatch.setattr(discovery, "HttpClient", lambda: _LtTransport())
    selection = rr.find(provider="lt_lhmt", station="anyksciu-vms")
    result = rr.fetch(selection, start="2023-06-03", end="2023-06-04", cache="bypass", on_issue="ignore")
    assert result.data.height == 4
    _assert_verified_absence_result(result, bundle_path=tmp_path / "lt_lhmt.rr")


def test_pe_senamhi_offline_emits_no_annotations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    doc = {
        "status": True,
        "data": {
            "station": {"code": "47251282"},
            "type": "DAILY",
            "variable": "FLOW",
            "unit": "m3/s",
            "daily": [{"date": "2024-01-02", "current": 5.0, "minimum": 4.0, "maximum": 6.0}],
        },
    }

    class _PeTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            return TransportResponse(
                json.dumps(doc).encode("utf-8"),
                200,
                _RETRIEVED_AT,
                "application/json",
                request.url,
                dict(request.params or {}),
            )

    monkeypatch.setattr(discovery, "HttpClient", lambda: _PeTransport())
    selected = rr.find(provider="pe_senamhi", station="47251282")
    identities = rr.as_frame(selected).filter(pl.col("product_id") == "phisis_daily_flow")["series_id"].to_list()
    result = rr.fetch(
        rr.pick(selected, series_id=identities),
        start="2024-01-02",
        end="2024-01-02T23:59:59",
        cache="bypass",
        on_issue="ignore",
    )
    assert result.data.height == 3
    _assert_verified_absence_result(result, bundle_path=tmp_path / "pe_senamhi.rr")


def test_th_thaiwater_offline_emits_no_annotations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    doc = {
        "result": "OK",
        "data": {
            "graph_data": [
                {"datetime": "2026-08-01 00:00", "discharge": 8.5, "value": 2.1},
                {"datetime": "2026-08-01 01:00", "discharge": 9.0, "value": 2.2},
            ]
        },
    }

    class _ThTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            return TransportResponse(
                json.dumps(doc).encode("utf-8"),
                200,
                _RETRIEVED_AT,
                "application/json",
                request.url,
                dict(request.params or {}),
            )

    monkeypatch.setattr(discovery, "HttpClient", lambda: _ThTransport())
    selection = rr.find(provider="th_thaiwater", station="1373273")
    result = rr.fetch(selection, start="2026-08-01", end="2026-08-01T01:00:00", cache="bypass", on_issue="ignore")
    assert result.data.height == 4
    _assert_verified_absence_result(result, bundle_path=tmp_path / "th_thaiwater.rr")


@pytest.mark.recorded("tests/test_data/pl_imgw_annual")
def test_pl_imgw_recorded_emits_no_annotations(
    retained_evidence_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = retained_evidence_root / _TEST_DATA / "pl_imgw_annual" / "codz_2024.zip"
    artifact = tmp_path / source.name
    shutil.copyfile(source, artifact)
    store_dir = tmp_path / "store"
    compile_imgw(
        ImgwCompileRequest(
            artifact,
            StoreRoot(store_dir),
            "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/2024/codz_2024.zip",
            date(2024, 10, 31),
            datetime(2026, 9, 20, tzinfo=UTC),
            "0.1.49",
        )
    )
    _register_imgw_store(monkeypatch, store_dir)
    selection = rr.find(provider="pl_imgw", station="152140020", quantity="discharge")
    result = rr.fetch(selection, start="2024-01-01", end="2024-01-01", receipts=True)
    assert result.data.height == 1
    _assert_verified_absence_result(result, bundle_path=tmp_path / "pl_imgw_recorded.rr")


@pytest.mark.recorded(
    "tests/test_data/ba_fhmzbih_2010_Q_1Y.recording.json",
    "tests/test_data/ba_fhmzbih_metadata_index.recording.json",
)
def test_ba_fhmzbih_recorded_emits_no_annotations(
    retained_evidence_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    replay = ReplayTransport(
        [
            retained_evidence_root / _TEST_DATA / "ba_fhmzbih_metadata_index.recording.json",
            retained_evidence_root / _TEST_DATA / "ba_fhmzbih_2010_Q_1Y.recording.json",
        ]
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    selection = rr.find(provider="ba_fhmzbih", station="2010", quantity="discharge")
    result = rr.fetch(selection, start="2026-05-22", end="2026-05-24T23:59:59", receipts=True, on_issue="ignore")
    assert result.data.height == 70
    _assert_verified_absence_result(result, bundle_path=tmp_path / "ba_fhmzbih_recorded.rr")


@pytest.mark.recorded("tests/test_data/cz_chmi_0-203-1-000400_DQ_2023.recording.json")
def test_cz_chmi_recorded_emits_no_annotations(
    retained_evidence_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    replay = ReplayTransport([retained_evidence_root / _TEST_DATA / "cz_chmi_0-203-1-000400_DQ_2023.recording.json"])
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    selection = rr.find(
        provider="cz_chmi",
        station="0-203-1-000400",
        quantity="discharge",
        frequency="P1D",
        statistic="mean",
    )
    result = rr.fetch(selection, start="2023-06-01", end="2023-06-02", receipts=True, on_issue="ignore")
    assert result.data.height == 2
    _assert_verified_absence_result(result, bundle_path=tmp_path / "cz_chmi_recorded.rr")


@pytest.mark.recorded("tests/test_data/lt_lhmt_anyksciu-vms_2023-06.recording.json")
def test_lt_lhmt_recorded_emits_no_annotations(
    retained_evidence_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    envelope = read_recording(retained_evidence_root / _TEST_DATA / "lt_lhmt_anyksciu-vms_2023-06.recording.json")
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((envelope,)))
    selection = rr.find(provider="lt_lhmt", station="anyksciu-vms")
    result = rr.fetch(selection, start="2023-06-03", end="2023-06-28", receipts=True, on_issue="ignore")
    assert result.data.height == 52
    _assert_verified_absence_result(result, bundle_path=tmp_path / "lt_lhmt_recorded.rr")


@pytest.mark.parametrize(
    ("member", "station", "product", "start", "end"),
    [
        ("anchors/daily-ramis-05", "47251282", "phisis_daily_flow", "2024-02-28", "2024-03-01T23:59:59"),
        (
            "anchors/readings-47E0D438-202610",
            "47E0D438",
            "monthly_archive_n_nivelagua",
            "2026-10-03",
            "2026-10-29T23:59:59",
        ),
    ],
)
@pytest.mark.recorded("maintenance/observations/pe_senamhi/retrieval")
def test_pe_senamhi_recorded_emits_no_annotations(
    retained_evidence_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    member: str,
    station: str,
    product: str,
    start: str,
    end: str,
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    scope_root = retained_evidence_root / "maintenance/observations/pe_senamhi/retrieval"
    content = (scope_root / f"{member}.body").read_bytes()
    receipt = json.loads((scope_root / f"{member}.receipt.json").read_bytes())
    retrieved_at = datetime.fromisoformat(receipt["finished_at"])
    source = urlsplit(receipt["url"])
    headers = receipt["headers"]

    class _SenamhiReplay:
        def send(self, request: TransportRequest) -> TransportResponse:
            requested = urlsplit(request.url)
            assert (requested.scheme, requested.netloc, requested.path) == (
                source.scheme,
                source.netloc,
                source.path,
            )
            assert dict(request.params or {}) == dict(parse_qsl(source.query))
            return TransportResponse(
                content=content,
                status_code=receipt["http_status"],
                retrieved_at=retrieved_at,
                content_type=next((value for name, value in headers if name.lower() == "content-type"), None),
                url=receipt["url"],
                request_parameters=dict(parse_qsl(source.query)),
            )

    monkeypatch.setattr(discovery, "HttpClient", lambda: _SenamhiReplay())
    selected = rr.find(provider="pe_senamhi", station=station)
    identities = rr.as_frame(selected).filter(pl.col("product_id") == product)["series_id"].to_list()
    result = rr.fetch(
        rr.pick(selected, series_id=identities),
        start=start,
        end=end,
        cache="bypass",
        receipts=True,
        on_issue="ignore",
    )
    assert not result.data.is_empty()
    _assert_verified_absence_result(result, bundle_path=tmp_path / f"pe_senamhi_{station}.rr")


@pytest.mark.recorded("tests/test_data/th_thaiwater_1373273_2026-07-30_2026-08-04.recording.json")
def test_th_thaiwater_recorded_emits_no_annotations(
    retained_evidence_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    envelope = read_recording(
        retained_evidence_root / _TEST_DATA / "th_thaiwater_1373273_2026-07-30_2026-08-04.recording.json"
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((envelope,)))
    selection = rr.find(provider="th_thaiwater", station="1373273")
    result = rr.fetch(selection, start="2026-08-01", end="2026-08-02T23:50:00", receipts=True, on_issue="ignore")
    assert result.data.height == 576
    _assert_verified_absence_result(result, bundle_path=tmp_path / "th_thaiwater_recorded.rr")
