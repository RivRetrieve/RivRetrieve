"""Genuine retained ZIP verification and manifest boundary probes for Chile DGA (cl_dga)."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.boundary_probes import (
    FIRST_WALL_CLOCK_TIME,
    LAST_WALL_CLOCK_TIME,
    READING_COUNT,
    StoreBoundaryProbe,
    WallClockExpectation,
    run_manifest_boundary_probes,
)
from rivretrieve._internal.discovery import EmptySelectionError
from rivretrieve._internal.observations import ReceiptAuthorship, StoreExcerptReceipt
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.cl_dga.bulk import (
    CL_DGA_COMPILER_VERSION,
    CL_DGA_DAILY_FILENAME,
    CL_DGA_DAILY_MEMBER,
    CL_DGA_DAILY_URL,
    CL_DGA_MONTHLY_FILENAME,
    CL_DGA_MONTHLY_MEMBER,
    CL_DGA_MONTHLY_URL,
    ClDgaCompileRequest,
    compile_cl_dga,
)
from rivretrieve._internal.providers.cl_dga.declaration import declaration
from rivretrieve._internal.providers.registration import DeclaredProvider, DownloadedBulkArtifact
from rivretrieve._internal.source_series import ClippingAxis, EvidenceState, OutcomeStatus
from rivretrieve._internal.store import (
    Disposition,
    StorePresence,
    StoreQuery,
    StoreRoot,
    validate_store,
)
from rivretrieve._internal.store.integrity import audit_store

RETRIEVAL_SCOPE = "maintenance/observations/cl_dga/retrieval"
_DAILY_WEB_STEM = "mapas2-caudal-diario-nacional-zip"
_MONTHLY_WEB_STEM = "mapas2-caudal-medio-mensual-nacional-zip"
_WITNESS_STATIONS = frozenset({"01020002", "01050002", "01201001", "04515002"})
_TOTAL_DAILY_ROWS = 6_838_571
_TOTAL_MONTHLY_ROWS = 235_185


@dataclass(frozen=True, slots=True)
class RawDailyWitness:
    station_id: str
    time: datetime
    value: float
    raw_fecha: str
    raw_value: str
    raw_lat: str


@dataclass(frozen=True, slots=True)
class RawMonthlyWitness:
    station_id: str
    time: datetime
    value: float
    raw_year: str
    raw_month: str
    raw_value: str
    raw_lat: str


@dataclass(frozen=True, slots=True)
class GenuineClDgaFixture:
    cache_root: Path
    store_root: StoreRoot
    daily_sha256: str
    monthly_sha256: str
    daily_rows: tuple[RawDailyWitness, ...]
    monthly_rows: tuple[RawMonthlyWitness, ...]


def _verify_capture(web_root: Path, stem: str, expected_url: str) -> tuple[Path, str]:
    body_path = web_root / f"{stem}.zip"
    receipt = json.loads((web_root / f"{stem}.receipt.json").read_text(encoding="utf-8"))
    raw = body_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert len(raw) == receipt["byte_size"]
    assert digest == receipt["sha256"]
    assert receipt["url"] == expected_url
    assert receipt["http_status"] == 200
    return body_path, digest


def _read_raw_daily_witnesses(zip_path: Path) -> tuple[RawDailyWitness, ...]:
    rows: list[RawDailyWitness] = []
    with zipfile.ZipFile(zip_path) as archive, archive.open(CL_DGA_DAILY_MEMBER) as stream:
        reader = csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8", newline=""))
        for record in reader:
            station_id = record["CODIGO ESTACION"]
            if station_id not in _WITNESS_STATIONS:
                continue
            assert record["Unidad"] == "m3/s"
            raw_fecha = record["FECHA"]
            day_s, month_s, year_s = raw_fecha.split("/")
            rows.append(
                RawDailyWitness(
                    station_id=station_id,
                    time=datetime(int(year_s), int(month_s), int(day_s)),
                    value=float(record["Caudal_diario"]),
                    raw_fecha=raw_fecha,
                    raw_value=record["Caudal_diario"],
                    raw_lat=record["LAT"],
                )
            )
    return tuple(rows)


def _read_raw_monthly_witnesses(zip_path: Path) -> tuple[RawMonthlyWitness, ...]:
    rows: list[RawMonthlyWitness] = []
    with zipfile.ZipFile(zip_path) as archive, archive.open(CL_DGA_MONTHLY_MEMBER) as stream:
        reader = csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8", newline=""))
        for record in reader:
            station_id = record["CODIGO ESTACION"]
            if station_id not in _WITNESS_STATIONS:
                continue
            assert record["Unidad"] == "m3/s"
            raw_year = record["Año"]
            raw_month = record["Mes"]
            rows.append(
                RawMonthlyWitness(
                    station_id=station_id,
                    time=datetime(int(raw_year), int(raw_month), 1),
                    value=float(record["Caudal_Medio_mensual"]),
                    raw_year=raw_year,
                    raw_month=raw_month,
                    raw_value=record["Caudal_Medio_mensual"],
                    raw_lat=record["LAT"],
                )
            )
    return tuple(rows)


def _expected_daily_frame(
    witnesses: tuple[RawDailyWitness, ...],
    *,
    station_id: str,
    start: datetime,
    end: datetime,
    series_id: str,
) -> pl.DataFrame:
    matched = [
        {"station_id": w.station_id, "series_id": series_id, "time": w.time, "value": w.value}
        for w in witnesses
        if w.station_id == station_id and start <= w.time <= end
    ]
    return pl.DataFrame(
        matched,
        schema={
            "station_id": pl.String,
            "series_id": pl.String,
            "time": pl.Datetime("us"),
            "value": pl.Float64,
        },
    ).sort("station_id", "series_id", "time", "value")


def _expected_monthly_frame(
    witnesses: tuple[RawMonthlyWitness, ...],
    *,
    station_id: str,
    months: tuple[datetime, ...],
    series_id: str,
) -> pl.DataFrame:
    month_set = set(months)
    matched = [
        {"station_id": w.station_id, "series_id": series_id, "time": w.time, "value": w.value}
        for w in witnesses
        if w.station_id == station_id and w.time in month_set
    ]
    return pl.DataFrame(
        matched,
        schema={
            "station_id": pl.String,
            "series_id": pl.String,
            "time": pl.Datetime("us"),
            "value": pl.Float64,
        },
    ).sort("station_id", "series_id", "time", "value")


@pytest.fixture(scope="module")
def genuine_cl_dga_store(
    retained_evidence_root: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> GenuineClDgaFixture:
    web_root = retained_evidence_root / RETRIEVAL_SCOPE / "web"
    daily_src, daily_sha256 = _verify_capture(web_root, _DAILY_WEB_STEM, CL_DGA_DAILY_URL)
    monthly_src, monthly_sha256 = _verify_capture(web_root, _MONTHLY_WEB_STEM, CL_DGA_MONTHLY_URL)

    daily_rows = _read_raw_daily_witnesses(daily_src)
    monthly_rows = _read_raw_monthly_witnesses(monthly_src)

    work = tmp_path_factory.mktemp("cl_dga_genuine_store")
    inputs_dir = work / "inputs"
    inputs_dir.mkdir()
    daily_copy = inputs_dir / CL_DGA_DAILY_FILENAME
    monthly_copy = inputs_dir / CL_DGA_MONTHLY_FILENAME
    shutil.copyfile(daily_src, daily_copy)
    shutil.copyfile(monthly_src, monthly_copy)

    cache_root = work / "cache"
    store_root = StoreRoot(cache_root / "cl_dga" / "store")
    compiled = compile_cl_dga(
        ClDgaCompileRequest(
            publisher_artifacts=(
                DownloadedBulkArtifact(daily_copy, CL_DGA_DAILY_URL, None),
                DownloadedBulkArtifact(monthly_copy, CL_DGA_MONTHLY_URL, None),
            ),
            destination=store_root,
            built_at=datetime(2026, 11, 19, 17, 0, tzinfo=UTC),
            compiler_version=CL_DGA_COMPILER_VERSION,
        )
    )
    assert compiled.manifest.source_vintage is None
    assert len(compiled.manifest.source_schema.columns) == 27
    assert (
        sum(
            1
            for item in compiled.manifest.source_column_dispositions
            if item.disposition is Disposition.DELIBERATELY_DISCARDED
        )
        == 0
    )
    assert [(item.url, str(item.sha256)) for item in compiled.manifest.publisher_artifacts] == [
        (CL_DGA_DAILY_URL, f"sha256:{daily_sha256}"),
        (CL_DGA_MONTHLY_URL, f"sha256:{monthly_sha256}"),
    ]

    validated = validate_store(store_root, ProviderId("cl_dga"))
    assert validated.manifest == compiled.manifest
    assert audit_store(store_root, ProviderId("cl_dga")).rows_checked == _TOTAL_DAILY_ROWS + _TOTAL_MONTHLY_ROWS

    return GenuineClDgaFixture(
        cache_root=cache_root,
        store_root=store_root,
        daily_sha256=daily_sha256,
        monthly_sha256=monthly_sha256,
        daily_rows=daily_rows,
        monthly_rows=monthly_rows,
    )


@pytest.mark.recorded(RETRIEVAL_SCOPE)
def test_cl_dga_manifest_boundary_probes_match_raw_zips(genuine_cl_dga_store: GenuineClDgaFixture) -> None:
    store_root = genuine_cl_dga_store.store_root
    daily_expected = [
        w
        for w in genuine_cl_dga_store.daily_rows
        if w.station_id == "01050002" and datetime(2023, 12, 31) <= w.time <= datetime(2024, 1, 2)
    ]
    daily_times = sorted(w.time for w in daily_expected)
    assert len(daily_times) == 3

    monthly_expected = [
        w
        for w in genuine_cl_dga_store.monthly_rows
        if w.station_id == "01050002" and datetime(2023, 12, 1) <= w.time <= datetime(2024, 2, 1)
    ]
    monthly_times = sorted(w.time for w in monthly_expected)
    assert len(monthly_times) == 3

    probes = (
        StoreBoundaryProbe(
            ProviderId("cl_dga"),
            ProductId("discharge_daily"),
            StoreQuery(
                store_root,
                ProviderId("cl_dga"),
                ("01050002",),
                (ProductId("discharge_daily"),),
                datetime(2023, 12, 31),
                datetime(2024, 1, 2),
            ),
            {
                READING_COUNT: len(daily_times),
                FIRST_WALL_CLOCK_TIME: WallClockExpectation(daily_times[0].isoformat(), "unknown"),
                LAST_WALL_CLOCK_TIME: WallClockExpectation(daily_times[-1].isoformat(), "unknown"),
            },
        ),
        StoreBoundaryProbe(
            ProviderId("cl_dga"),
            ProductId("discharge_monthly_mean"),
            StoreQuery(
                store_root,
                ProviderId("cl_dga"),
                ("01050002",),
                (ProductId("discharge_monthly_mean"),),
                datetime(2023, 12, 1),
                datetime(2024, 2, 1),
            ),
            {
                READING_COUNT: len(monthly_times),
                FIRST_WALL_CLOCK_TIME: WallClockExpectation(monthly_times[0].isoformat(), "unknown"),
                LAST_WALL_CLOCK_TIME: WallClockExpectation(monthly_times[-1].isoformat(), "unknown"),
            },
        ),
    )
    results = run_manifest_boundary_probes((DeclaredProvider("cl_dga", declaration),), probes)
    assert len(results) == 2


@pytest.mark.recorded(RETRIEVAL_SCOPE)
def test_cl_dga_public_api_matches_genuine_source_identities_values_and_edges(
    genuine_cl_dga_store: GenuineClDgaFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ForbidNetwork:
        def send(self, request):
            raise AssertionError(f"Offline bulk retrieval attempted network request to {request.url}")

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(genuine_cl_dga_store.cache_root))
    monkeypatch.setattr(discovery, "HttpClient", ForbidNetwork)

    status = rr.cache_status("cl_dga")
    assert status.presence is StorePresence.PRESENT
    assert status.source_vintage is None
    assert rr.audit_cache("cl_dga").rows_checked == _TOTAL_DAILY_ROWS + _TOTAL_MONTHLY_ROWS

    # Daily year boundary, leap day, 1960 historical edge, and internal gap.
    daily_sel = rr.find(provider="cl_dga", station="01050002", frequency="P1D")
    assert len(daily_sel.series) == 1
    daily_series = daily_sel.series[0]
    assert (daily_series.identity.namespace, daily_series.identity.published_id) == (
        "cl_dga.mapas2.caudal_diario",
        "Caudal_diario",
    )
    daily_facts = daily_series.facts[0]
    assert daily_facts.quantity.value == "discharge"
    assert daily_facts.source_unit.value == "m3/s"
    assert daily_facts.normalized_unit == "m3/s"
    assert daily_facts.frequency.value == "P1D"
    assert daily_facts.statistic.state is EvidenceState.NOT_ESTABLISHED
    assert daily_facts.clipping_axis is ClippingAxis.CALENDAR_DATE
    assert daily_facts.label_time is None
    for unknown_field in ("temporal_support", "day_definition", "timestamp_anchor", "time_zone"):
        assert getattr(daily_facts, unknown_field).state is EvidenceState.NOT_ESTABLISHED

    # Unknown daily statistic refuses statistic="mean" filtering via EmptySelectionError.
    empty_stat_sel = rr.find(provider="cl_dga", station="01050002", frequency="P1D", statistic="mean")
    with pytest.raises(EmptySelectionError):
        rr.fetch(empty_stat_sel, start="2024-01-01", end="2024-01-02")

    yb_res = rr.fetch(daily_sel, start="2023-12-31", end="2024-01-02", on_issue="raise")
    assert yb_res.data.height == 3
    assert set(yb_res.data["time_zone"].to_list()) == {"unknown"}
    assert set(yb_res.data["product_id"].to_list()) == {"discharge_daily"}
    assert set(yb_res.data["facts_id"].to_list()) == {daily_facts.facts_id}
    assert set(yb_res.data["quantity"].to_list()) == {"discharge"}
    assert set(yb_res.data["source_unit"].to_list()) == {"m3/s"}
    assert set(yb_res.data["unit"].to_list()) == {"m3/s"}
    pl_testing.assert_frame_equal(
        yb_res.data.select("station_id", "series_id", "time", "value").sort("station_id", "series_id", "time", "value"),
        _expected_daily_frame(
            genuine_cl_dga_store.daily_rows,
            station_id="01050002",
            start=datetime(2023, 12, 31),
            end=datetime(2024, 1, 2),
            series_id=daily_series.series_id,
        ),
    )

    leap_res = rr.fetch(daily_sel, start="2024-02-29", end="2024-02-29", on_issue="raise")
    assert leap_res.data.height == 1
    pl_testing.assert_frame_equal(
        leap_res.data.select("station_id", "series_id", "time", "value").sort(
            "station_id", "series_id", "time", "value"
        ),
        _expected_daily_frame(
            genuine_cl_dga_store.daily_rows,
            station_id="01050002",
            start=datetime(2024, 2, 29),
            end=datetime(2024, 2, 29),
            series_id=daily_series.series_id,
        ),
    )

    edge_1960_res = rr.fetch(daily_sel, start="1960-01-01", end="1960-01-10", on_issue="raise")
    assert edge_1960_res.data.height > 0
    pl_testing.assert_frame_equal(
        edge_1960_res.data.select("station_id", "series_id", "time", "value").sort(
            "station_id", "series_id", "time", "value"
        ),
        _expected_daily_frame(
            genuine_cl_dga_store.daily_rows,
            station_id="01050002",
            start=datetime(1960, 1, 1),
            end=datetime(1960, 1, 10),
            series_id=daily_series.series_id,
        ),
    )

    # Internal gap in 1960 (01050002 has no published row on 1960-01-09) and pre-history empty selection.
    internal_gap_res = rr.fetch(daily_sel, start="1960-01-09", end="1960-01-09", on_issue="ignore")
    assert internal_gap_res.data.is_empty()
    assert internal_gap_res.outcomes[0].status is OutcomeStatus.EMPTY
    pre_history_res = rr.fetch(daily_sel, start="1950-01-01", end="1950-01-31", on_issue="ignore")
    assert pre_history_res.data.is_empty()
    assert pre_history_res.outcomes[0].status is OutcomeStatus.EMPTY

    # Conflicting duplicate daily date preservation, verbatim receipt, and bundle round-trip.
    dup_sel = rr.find(provider="cl_dga", station="01201001", frequency="P1D")
    dup_series_id = dup_sel.series[0].series_id
    dup_res = rr.fetch(dup_sel, start="2020-02-12", end="2020-02-13", receipts=True, on_issue="raise")
    raw_dup = [
        w
        for w in genuine_cl_dga_store.daily_rows
        if w.station_id == "01201001" and datetime(2020, 2, 12) <= w.time <= datetime(2020, 2, 13)
    ]
    assert len(raw_dup) == 4
    assert len({w.value for w in raw_dup if w.time == datetime(2020, 2, 12)}) > 1
    assert dup_res.data.height == 4
    pl_testing.assert_frame_equal(
        dup_res.data.select("station_id", "series_id", "time", "value").sort(
            "station_id", "series_id", "time", "value"
        ),
        _expected_daily_frame(
            genuine_cl_dga_store.daily_rows,
            station_id="01201001",
            start=datetime(2020, 2, 12),
            end=datetime(2020, 2, 13),
            series_id=dup_series_id,
        ),
    )
    assert dup_res.provenance.source_vintage is None
    assert dup_res.provenance.publisher_artifact_urls == (CL_DGA_DAILY_URL, CL_DGA_MONTHLY_URL)
    assert dup_res.provenance.publisher_artifact_checksums == (
        f"sha256:{genuine_cl_dga_store.daily_sha256}",
        f"sha256:{genuine_cl_dga_store.monthly_sha256}",
    )
    (daily_receipt,) = dup_res.receipts.entries
    assert isinstance(daily_receipt, StoreExcerptReceipt)
    assert daily_receipt.authorship is ReceiptAuthorship.STORE_EXCERPT
    assert daily_receipt.source_vintage is None
    daily_excerpt = pl.read_parquet(io.BytesIO(daily_receipt.content))
    dup_excerpt_rows = daily_excerpt.filter(
        (pl.col("time") == datetime(2020, 2, 12)) | (pl.col("time") == datetime(2020, 2, 13))
    )
    assert dup_excerpt_rows.height == 4
    assert sorted(dup_excerpt_rows["caudal_diario.Caudal_diario"].to_list()) == sorted(w.raw_value for w in raw_dup)
    assert dup_excerpt_rows["caudal_diario.FECHA"].to_list().count("12/02/2020") == 2
    assert set(dup_excerpt_rows["caudal_diario.LAT"].to_list()) == {w.raw_lat for w in raw_dup}

    restored_daily = rr.from_bundle(rr.to_bundle(dup_res))
    pl_testing.assert_frame_equal(restored_daily.data, dup_res.data)
    assert restored_daily.provenance.source_vintage is None
    (restored_receipt,) = restored_daily.receipts.entries
    assert isinstance(restored_receipt, StoreExcerptReceipt)
    assert restored_receipt.source_vintage is None
    assert restored_receipt.content == daily_receipt.content

    # Genuine zero-flow daily + monthly values, and genuine scientific-notation daily value.
    zero_daily_sel = rr.find(provider="cl_dga", station="01020002", frequency="P1D")
    zero_daily_res = rr.fetch(zero_daily_sel, start="1966-02-22", end="1966-02-23", on_issue="raise")
    zero_daily_expected = _expected_daily_frame(
        genuine_cl_dga_store.daily_rows,
        station_id="01020002",
        start=datetime(1966, 2, 22),
        end=datetime(1966, 2, 23),
        series_id=zero_daily_sel.series[0].series_id,
    )
    assert zero_daily_res.data.height == 2
    assert zero_daily_expected["value"].to_list() == [0.0, 0.0]
    pl_testing.assert_frame_equal(
        zero_daily_res.data.select("station_id", "series_id", "time", "value").sort(
            "station_id", "series_id", "time", "value"
        ),
        zero_daily_expected,
    )

    sci_daily_sel = rr.find(provider="cl_dga", station="04515002", frequency="P1D")
    raw_sci = [
        w
        for w in genuine_cl_dga_store.daily_rows
        if w.station_id == "04515002" and datetime(2026, 6, 13) <= w.time <= datetime(2026, 6, 23)
    ]
    assert raw_sci and any("e" in w.raw_value.lower() for w in raw_sci)
    sci_daily_res = rr.fetch(sci_daily_sel, start="2026-06-13", end="2026-06-23", on_issue="raise")
    assert sci_daily_res.data.height == len(raw_sci)
    pl_testing.assert_frame_equal(
        sci_daily_res.data.select("station_id", "series_id", "time", "value").sort(
            "station_id", "series_id", "time", "value"
        ),
        _expected_daily_frame(
            genuine_cl_dga_store.daily_rows,
            station_id="04515002",
            start=datetime(2026, 6, 13),
            end=datetime(2026, 6, 23),
            series_id=sci_daily_sel.series[0].series_id,
        ),
    )

    # Monthly mean product: identity, facts, mid-month selection, year boundary, 1960 edge, zero, empty, receipt.
    monthly_sel = rr.find(provider="cl_dga", station="01050002", frequency="P1M")
    assert len(monthly_sel.series) == 1
    monthly_series = monthly_sel.series[0]
    assert (monthly_series.identity.namespace, monthly_series.identity.published_id) == (
        "cl_dga.mapas2.caudal_medio_mensual",
        "Caudal_Medio_mensual",
    )
    monthly_facts = monthly_series.facts[0]
    assert monthly_facts.quantity.value == "discharge"
    assert monthly_facts.source_unit.value == "m3/s"
    assert monthly_facts.normalized_unit == "m3/s"
    assert monthly_facts.frequency.value == "P1M"
    assert monthly_facts.statistic.value == "mean"
    assert monthly_facts.clipping_axis is ClippingAxis.CALENDAR_MONTH
    assert monthly_facts.label_time is None
    for unknown_field in ("temporal_support", "day_definition", "timestamp_anchor", "time_zone"):
        assert getattr(monthly_facts, unknown_field).state is EvidenceState.NOT_ESTABLISHED

    mid_month_res = rr.fetch(monthly_sel, start="2024-02-10", end="2024-02-20", receipts=True, on_issue="raise")
    assert mid_month_res.data.height == 1
    assert set(mid_month_res.data["time_zone"].to_list()) == {"unknown"}
    assert set(mid_month_res.data["product_id"].to_list()) == {"discharge_monthly_mean"}
    assert set(mid_month_res.data["facts_id"].to_list()) == {monthly_facts.facts_id}
    assert set(mid_month_res.data["quantity"].to_list()) == {"discharge"}
    assert set(mid_month_res.data["source_unit"].to_list()) == {"m3/s"}
    assert set(mid_month_res.data["unit"].to_list()) == {"m3/s"}
    pl_testing.assert_frame_equal(
        mid_month_res.data.select("station_id", "series_id", "time", "value").sort(
            "station_id", "series_id", "time", "value"
        ),
        _expected_monthly_frame(
            genuine_cl_dga_store.monthly_rows,
            station_id="01050002",
            months=(datetime(2024, 2, 1),),
            series_id=monthly_series.series_id,
        ),
    )
    (monthly_receipt,) = mid_month_res.receipts.entries
    assert isinstance(monthly_receipt, StoreExcerptReceipt)
    assert monthly_receipt.source_vintage is None
    monthly_excerpt = pl.read_parquet(io.BytesIO(monthly_receipt.content))
    feb_excerpt = monthly_excerpt.filter(pl.col("time") == datetime(2024, 2, 1))
    raw_feb = [
        w for w in genuine_cl_dga_store.monthly_rows if w.station_id == "01050002" and w.time == datetime(2024, 2, 1)
    ][0]
    assert feb_excerpt["caudal_medio_mensual.Año"].to_list() == [raw_feb.raw_year]
    assert feb_excerpt["caudal_medio_mensual.Mes"].to_list() == [raw_feb.raw_month]
    assert feb_excerpt["caudal_medio_mensual.Caudal_Medio_mensual"].to_list() == [raw_feb.raw_value]

    ym_month_res = rr.fetch(monthly_sel, start="2023-12-15", end="2024-01-10", on_issue="raise")
    assert ym_month_res.data.height == 2
    pl_testing.assert_frame_equal(
        ym_month_res.data.select("station_id", "series_id", "time", "value").sort(
            "station_id", "series_id", "time", "value"
        ),
        _expected_monthly_frame(
            genuine_cl_dga_store.monthly_rows,
            station_id="01050002",
            months=(datetime(2023, 12, 1), datetime(2024, 1, 1)),
            series_id=monthly_series.series_id,
        ),
    )

    m_1960_res = rr.fetch(monthly_sel, start="1960-01-15", end="1960-02-10", on_issue="raise")
    assert m_1960_res.data.height == 2
    pl_testing.assert_frame_equal(
        m_1960_res.data.select("station_id", "series_id", "time", "value").sort(
            "station_id", "series_id", "time", "value"
        ),
        _expected_monthly_frame(
            genuine_cl_dga_store.monthly_rows,
            station_id="01050002",
            months=(datetime(1960, 1, 1), datetime(1960, 2, 1)),
            series_id=monthly_series.series_id,
        ),
    )

    zero_monthly_sel = rr.find(provider="cl_dga", station="01020002", frequency="P1M")
    zero_monthly_res = rr.fetch(zero_monthly_sel, start="1967-01-05", end="1967-02-20", on_issue="raise")
    zero_monthly_expected = _expected_monthly_frame(
        genuine_cl_dga_store.monthly_rows,
        station_id="01020002",
        months=(datetime(1967, 1, 1), datetime(1967, 2, 1)),
        series_id=zero_monthly_sel.series[0].series_id,
    )
    assert zero_monthly_res.data.height == 2
    assert zero_monthly_expected["value"].to_list() == [0.0, 0.0]
    pl_testing.assert_frame_equal(
        zero_monthly_res.data.select("station_id", "series_id", "time", "value").sort(
            "station_id", "series_id", "time", "value"
        ),
        zero_monthly_expected,
    )

    empty_monthly_res = rr.fetch(monthly_sel, start="1950-01-10", end="1950-02-15", on_issue="ignore")
    assert empty_monthly_res.data.is_empty()
    assert empty_monthly_res.outcomes[0].status is OutcomeStatus.EMPTY
