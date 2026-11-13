"""Source-independent tests for engine pipeline, partitioned v9/v10 stores, S3 remote, and v4 bundles."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.coverage import CoverageInterval, RequestedInterval
from rivretrieve._internal.driver import drive, drive_store
from rivretrieve._internal.engine import (
    Instant,
    ObservationRequest,
    Payload,
    ProductConfig,
    ProductWindowDeclarations,
    ProviderConfig,
    RequestedWindow,
    RowsSchema,
    SourceCallOrigin,
    SourceCoordinates,
    StopConvention,
    Unit,
    UnknownOriginFact,
    WindowDeclaration,
    WindowEndpoint,
    WindowGranularity,
    WindowRenderingVocabulary,
    WithIssues,
    ZoneValue,
)
from rivretrieve._internal.observations import ObservationProvenance, ObservationResult
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.selection import _Selection
from rivretrieve._internal.source_annotations import (
    AnnotationBundle,
    AnnotationField,
    AnnotationSchema,
    AnnotationScope,
    ObservationAnnotationTable,
    SeriesAnnotationTable,
    with_annotations,
)
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    PhysicalFacts,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceIdentity,
    SourceSeries,
    known,
    stable_id,
)
from rivretrieve._internal.store import (
    NativeObservationBatch,
    ObservationBatchStream,
    ObservationStoreRefusedError,
    SourceUnitContribution,
    SourceUnitCount,
    StoreQuery,
    StoreReader,
    StoreRoot,
    certify_store,
    certify_store_batches,
    source_unit_inventory_fingerprint,
)
from rivretrieve._internal.store.accumulation import StoreUpdate, SuccessfulReplacement, accumulate
from rivretrieve._internal.store.integrity import audit_store
from rivretrieve._internal.store.remote import RemoteStoreRoot, audit_remote_store
from rivretrieve._internal.time_axis import TimeAxis
from rivretrieve._internal.transport import (
    HttpMethod,
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
)
from tests.store.certification_support import (
    COLUMNS,
    artifact_and_request,
    complete,
    fixture_series,
)
from tests.store.certification_support import (
    rows as cert_rows,
)
from tests.store.test_remote_store import S3TestServer, s3_server  # noqa: F401

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_PROVIDER = ProviderId("synth_ann")
_OBS_SCHEMA = AnnotationSchema(
    schema_id="synth_ann.obs",
    provider_id="synth_ann",
    scope=AnnotationScope.OBSERVATION,
    fields=(
        AnnotationField(
            name="tag",
            dtype="String",
            description="Synthetic observation quality tag.",
            reference_url="https://example.org/synth/tag",
        ),
        AnnotationField(
            name="flags",
            dtype="List(String)",
            description="Synthetic qualifier list.",
        ),
    ),
)
_SER_SCHEMA = AnnotationSchema(
    schema_id="synth_ann.meta",
    provider_id="synth_ann",
    scope=AnnotationScope.SERIES,
    fields=(
        AnnotationField(
            name="gauge_note",
            dtype="String",
            description="Synthetic series-level attribute.",
        ),
    ),
)


def _series_def(station: str = "station-1", product: str = "level") -> SourceSeries:
    return SourceSeries(
        series_id=stable_id("synth_ann", station, product),
        provider_id="synth_ann",
        station_id=station,
        product_id=product,
        identity=SourceIdentity(
            namespace="synth_ann",
            published_id=f"{station}-{product}",
            origin="response",
            evidence=("synthetic fixture",),
        ),
        facts=(
            PhysicalFacts(
                facts_id="synth-facts-m",
                quantity=known("stage", "synthetic fixture"),
                source_unit=known("m", "synthetic fixture"),
                normalized_unit="m",
                frequency=known("daily", "synthetic fixture"),
                temporal_support=known("instantaneous", "synthetic fixture"),
                time_zone=known("UTC", "synthetic fixture"),
            ),
        ),
    )


def _provider_config(product_id: str = "level", unit: Unit = Unit.M) -> ProviderConfig:
    zone = ZoneValue("+00:00")
    return ProviderConfig(
        zone=zone,
        products={
            ProductId(product_id): ProductConfig(
                coordinates=SourceCoordinates(product_id),
                unit=unit,
                semantics=Instant(),
            )
        },
        cache=None,
    )


def _window_declarations(product_id: str = "level") -> ProductWindowDeclarations:
    return ProductWindowDeclarations(
        {
            ProductId(product_id): WindowDeclaration(
                WindowGranularity("date"),
                WindowRenderingVocabulary.DATE,
                StopConvention.INCLUSIVE,
            )
        }
    )


def _make_obs_table(
    series: SourceSeries,
    times: list[datetime],
    measured: list[bool],
    tags: list[str],
    flags_list: list[list[str] | None],
    measurement_indices: list[int | None],
) -> ObservationAnnotationTable:
    frame = pl.DataFrame(
        {
            "series_id": [series.series_id] * len(times),
            "facts_id": [series.facts[0].facts_id] * len(times),
            "station_id": [series.station_id] * len(times),
            "product_id": [series.product_id] * len(times),
            "time": times,
            "time_zone": ["+00:00"] * len(times),
            "measured": measured,
            "tag": tags,
            "flags": flags_list,
        },
        schema={
            "series_id": pl.String,
            "facts_id": pl.String,
            "station_id": pl.String,
            "product_id": pl.String,
            "time": pl.Datetime("us"),
            "time_zone": pl.String,
            "measured": pl.Boolean,
            **_OBS_SCHEMA.polars_schema(),
        },
    )
    return ObservationAnnotationTable.from_rows(
        schema=_OBS_SCHEMA,
        rows=frame,
        measurement_indices=measurement_indices,
    )


def _make_series_table(series: SourceSeries, note: str) -> SeriesAnnotationTable:
    frame = pl.DataFrame(
        {"series_id": [series.series_id], "gauge_note": [note]},
        schema={"series_id": pl.String, **_SER_SCHEMA.polars_schema()},
    )
    return SeriesAnnotationTable.from_rows(schema=_SER_SCHEMA, rows=frame)


class _AnnotatedLiveStages:
    def __init__(self, series: SourceSeries) -> None:
        self.series = series
        self.config = _provider_config("level", Unit.M)
        self.window_declarations = _window_declarations("level")
        self.calls: list[RequestedWindow] = []
        self.forbid_fetch = False
        self.fail_fetch = False
        self.snapshot = False
        self.tag_override = "Provisional"
        self.unmeasured_times: dict[int, tuple[datetime, str]] = {}
        self.entries_by_year: dict[int, list[tuple[datetime, float, str, list[str] | None]]] = {}
        self.fail_series = False
        self.stamp = datetime(2026, 9, 1, tzinfo=UTC)

    def fetch(self, stations, products, rendered, fetch_window, config, transport, *, scope=None, known_series=()):
        assert not self.forbid_fetch, "cache='reuse' should serve covered request without fetching"
        if self.fail_fetch:
            req = TransportRequest(HttpMethod.GET, "https://example.org/synth/items")
            raise TransportFailure(req, TransportFailureReason.HTTP_STATUS, 1, status_code=503)
        self.calls.append(fetch_window)
        start = datetime.fromisoformat(fetch_window.start.isoformat())
        end = datetime.fromisoformat(fetch_window.end.isoformat())
        spec = {
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        payload = Payload(
            SourceCoordinates("level"),
            ((stations[0], products[0]),),
            fetch_window,
            json.dumps(spec).encode("utf-8"),
            SourceCallOrigin(
                "https://example.org/synth/items",
                {},
                200,
                self.stamp,
                "application/json",
                UnknownOriginFact(),
                UnknownOriginFact(),
            ),
            prerequisite_calls=(),
            acquisition_id=f"acq-{len(self.calls)}",
            known_series=(self.series,),
            acquisition_axis=TimeAxis.UTC,
        )
        return WithIssues((payload,))

    def parse(self, payload: Payload, config: ProviderConfig) -> ParsedSeries:
        start = datetime.fromisoformat(payload.fetch_window.start.isoformat())
        end = datetime.fromisoformat(payload.fetch_window.end.isoformat())
        years = range(start.year, end.year + 1)
        row_dicts: list[dict[str, object]] = []
        ann_times: list[datetime] = []
        ann_measured: list[bool] = []
        ann_tags: list[str] = []
        ann_flags: list[list[str] | None] = []
        meas_indices: list[int | None] = []
        for yr in sorted(years):
            for ts, val, tag, flags in self.entries_by_year.get(yr, ()):
                if start <= ts <= end:
                    idx = len(row_dicts)
                    row_dicts.append(
                        {
                            "station_id": self.series.station_id,
                            "product_id": self.series.product_id,
                            "time": ts,
                            "value": val,
                            "time_zone": "+00:00",
                            "series_id": self.series.series_id,
                            "facts_id": self.series.facts[0].facts_id,
                            "source_unit": "m",
                        }
                    )
                    ann_times.append(ts)
                    ann_measured.append(True)
                    ann_tags.append(self.tag_override if tag == "Provisional" else tag)
                    ann_flags.append(flags)
                    meas_indices.append(idx)
            if yr in self.unmeasured_times:
                u_ts, u_tag = self.unmeasured_times[yr]
                if start <= u_ts <= end:
                    ann_times.append(u_ts)
                    ann_measured.append(False)
                    ann_tags.append(u_tag)
                    ann_flags.append(None)
                    meas_indices.append(None)
        frame = pl.DataFrame(row_dicts, schema=RowsSchema.polars_schema)
        window = SeriesWindow(start=start, end=end, axis=TimeAxis.UTC)
        obs_table = _make_obs_table(self.series, ann_times, ann_measured, ann_tags, ann_flags, meas_indices)
        ser_table = _make_series_table(self.series, "site-alpha")
        bundle = AnnotationBundle(
            observation_tables={_OBS_SCHEMA.schema_id: obs_table} if ann_times else {},
            series_tables={_SER_SCHEMA.schema_id: ser_table},
        )
        if self.fail_series:
            outcome = RetrievalOutcome(
                outcome_id=f"out-fail-{payload.acquisition_id}",
                series_id=self.series.series_id,
                station_id=self.series.station_id,
                product_id=self.series.product_id,
                window=window,
                status=OutcomeStatus.UNSUPPORTED,
                facts_ids=(self.series.facts[0].facts_id,),
                reason="malformed synthetic field",
                retrieved_at=self.stamp,
                calls=(payload.acquisition_id,),
            )
            return ParsedSeries(
                pl.DataFrame(schema=RowsSchema.polars_schema), (self.series,), (), (outcome,), (), annotations=bundle
            )
        obs_keys = tuple((r["facts_id"], r["time"], r["time_zone"]) for r in row_dicts) if self.snapshot else ()
        outcome = RetrievalOutcome(
            outcome_id=f"out-{payload.acquisition_id}",
            series_id=self.series.series_id,
            station_id=self.series.station_id,
            product_id=self.series.product_id,
            window=window,
            status=OutcomeStatus.SUCCESS if row_dicts else OutcomeStatus.EMPTY,
            facts_ids=(self.series.facts[0].facts_id,),
            coverage="observations" if self.snapshot else "interval",
            observation_keys=obs_keys,
            retrieved_at=self.stamp,
            calls=(payload.acquisition_id,),
        )
        inventory = InventorySnapshot(
            snapshot_id=f"inv-{payload.acquisition_id}",
            scope=payload.scope
            or SeriesScope(
                provider_ids=(_PROVIDER,),
                station_ids=(self.series.station_id,),
                product_ids=(self.series.product_id,),
            ),
            members=(self.series.series_id,),
            completeness=InventoryCompleteness.COMPLETE,
            access="Synthetic live annotation endpoint",
            origin="response",
            acquired_at=self.stamp,
            window=window,
            evidence=(f"test-response:{payload.acquisition_id}",),
        )
        return ParsedSeries(frame, (self.series,), (inventory,), (outcome,), (), annotations=bundle)


def _as_observation_result(assembled, series: SourceSeries) -> ObservationResult:
    base = ObservationResult(
        data=assembled.canonical_rows,
        source_series=assembled.source_series,
        inventories=assembled.inventories,
        outcomes=assembled.outcomes,
        supporting_outcomes=assembled.supporting_outcomes,
        scope=assembled.scope,
        provenance=assembled.provenance,
        issues=assembled.issues,
        receipts=assembled.receipts,
    )
    return with_annotations(base, assembled.annotations)


def _drive_req(start: datetime, end: datetime, series: SourceSeries) -> ObservationRequest:
    return ObservationRequest(
        _PROVIDER,
        (series.station_id,),
        (ProductId(series.product_id),),
        RequestedWindow(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end)),
        known_series=(series,),
    )


def test_drive_accumulated_store_v9_partitioned_parquet_reuse_refresh_and_selective_read(tmp_path: Path) -> None:
    series = _series_def()
    stages = _AnnotatedLiveStages(series)
    # 2022: two measured rows sharing identical timestamp with distinct annotations
    stages.entries_by_year[2022] = [
        (datetime(2022, 6, 1, 0, 0), 10.0, "Provisional", ["EST"]),
        (datetime(2022, 6, 1, 0, 0), 10.0, "second-duplicate", ["ICE", "EST"]),
    ]
    # 2026: unmeasured slot ONLY (zero observation rows in 2026)
    stages.unmeasured_times[2026] = (datetime(2026, 3, 1, 0, 0), "unmeasured-gap")
    store = StoreRoot(tmp_path / "store")
    prov = ObservationProvenance(source="Synthetic", provider_id=_PROVIDER)

    fresh_2022_2026 = drive(
        _drive_req(datetime(2022, 1, 1), datetime(2026, 12, 31), series),
        stages,
        provenance=prov,
        transport=object(),
        cache="reuse",
        store=store,
    )
    res_fresh = _as_observation_result(fresh_2022_2026, series)
    assert res_fresh.to_polars(annotations="tag")["tag"].to_list() == ["Provisional", "second-duplicate"]
    assert res_fresh.to_polars(annotations="flags")["flags"].to_list() == [["EST"], ["ICE", "EST"]]
    unm = rr.annotations(res_fresh, schema="synth_ann.obs").filter(~pl.col("measured"))
    assert unm["tag"].to_list() == ["unmeasured-gap"]
    assert rr.series(res_fresh, annotations="gauge_note")["gauge_note"].to_list() == ["site-alpha"]

    manifest_raw = json.loads((store / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_raw["format_version"] == 9
    assert "annotation_schemas" in manifest_raw
    assert "annotation_partition_row_counts" in manifest_raw
    assert "series_annotations" in manifest_raw
    assert (store / "product=level/year=2022/rows.parquet").is_file()
    assert (store / "product=level/year=2022/annotations=synth_ann.obs/rows.parquet").is_file()
    assert not (store / "product=level/year=2026/rows.parquet").exists()
    assert (store / "product=level/year=2026/annotations=synth_ann.obs/rows.parquet").is_file()
    audited = audit_store(store, _PROVIDER)
    assert audited.rows_checked == 2
    assert audited.partitions_checked == 1

    # Offline reuse serves exact annotations without calling fetch
    stages.forbid_fetch = True
    reused_2022_2026 = drive(
        _drive_req(datetime(2022, 1, 1), datetime(2026, 12, 31), series),
        stages,
        provenance=prov,
        transport=object(),
        cache="reuse",
        store=store,
    )
    res_reused = _as_observation_result(reused_2022_2026, series)
    pl_testing.assert_frame_equal(res_reused.to_polars(annotations=True), res_fresh.to_polars(annotations=True))
    pl_testing.assert_frame_equal(
        rr.annotations(res_reused, schema="synth_ann.obs"),
        rr.annotations(res_fresh, schema="synth_ann.obs"),
    )
    pl_testing.assert_frame_equal(rr.series(res_reused, annotations=True), rr.series(res_fresh, annotations=True))

    # Incremental update touching 2024 preserves 2022 + 2026 inodes (hardlink reuse; UTC margin=1 touches 2023..2025)
    obs_2022_ino = (store / "product=level/year=2022/rows.parquet").stat().st_ino
    ann_2022_ino = (store / "product=level/year=2022/annotations=synth_ann.obs/rows.parquet").stat().st_ino
    ann_2026_ino = (store / "product=level/year=2026/annotations=synth_ann.obs/rows.parquet").stat().st_ino
    stages.forbid_fetch = False
    stages.stamp = datetime(2026, 9, 2, tzinfo=UTC)
    stages.entries_by_year[2024] = [(datetime(2024, 7, 1, 0, 0), 25.0, "year-2024", None)]
    drive(
        _drive_req(datetime(2024, 6, 1), datetime(2024, 7, 31), series),
        stages,
        provenance=prov,
        transport=object(),
        cache="refresh",
        store=store,
    )
    assert (store / "product=level/year=2022/rows.parquet").stat().st_ino == obs_2022_ino
    assert (store / "product=level/year=2022/annotations=synth_ann.obs/rows.parquet").stat().st_ino == ann_2022_ino
    assert (store / "product=level/year=2026/annotations=synth_ann.obs/rows.parquet").stat().st_ino == ann_2026_ino

    # Selective query for 2024 only verifies 2024 partitions and never opens 2022 or 2026 annotation partitions
    reader = StoreReader()
    sel_2024 = reader.query(
        StoreQuery(
            store, _PROVIDER, (series.station_id,), (ProductId("level"),), datetime(2024, 1, 1), datetime(2024, 12, 31)
        )
    )
    assert sel_2024.annotations.observation_tables["synth_ann.obs"].rows["tag"].to_list() == ["year-2024"]
    verified_ids = {str(item) for item in reader._verified[(store, _PROVIDER)]}
    assert "product=level/year=2024/rows.parquet" not in verified_ids  # identifiers omit filename
    assert any("year=2024" in item and "annotations=synth_ann.obs" in item for item in verified_ids)
    assert not any("year=2022" in item or "year=2026" in item for item in verified_ids)

    # Annotation-only manual refresh (unchanged numeric value 10.0, tag Provisional -> Approved)
    stages.tag_override = "Approved"
    stages.stamp = datetime(2026, 9, 3, tzinfo=UTC)
    refreshed = drive(
        _drive_req(datetime(2022, 1, 1), datetime(2022, 12, 31), series),
        stages,
        provenance=prov,
        transport=object(),
        cache="refresh",
        store=store,
    )
    assert _as_observation_result(refreshed, series).to_polars(annotations="tag")["tag"].to_list() == [
        "Approved",
        "second-duplicate",
    ]
    stages.forbid_fetch = True
    after_refresh = drive(
        _drive_req(datetime(2022, 1, 1), datetime(2022, 12, 31), series),
        stages,
        provenance=prov,
        transport=object(),
        cache="reuse",
        store=store,
    )
    assert _as_observation_result(after_refresh, series).to_polars(annotations="tag")["tag"].to_list() == [
        "Approved",
        "second-duplicate",
    ]

    # Failed refresh preserves held data and Approved annotations
    stages.forbid_fetch = False
    stages.fail_fetch = True
    stages.stamp = datetime(2026, 9, 4, tzinfo=UTC)
    failed_refresh = drive(
        _drive_req(datetime(2022, 1, 1), datetime(2022, 12, 31), series),
        stages,
        provenance=prov,
        transport=object(),
        cache="refresh",
        store=store,
    )
    assert any(item.status is OutcomeStatus.FAILED for item in failed_refresh.outcomes)
    assert _as_observation_result(failed_refresh, series).to_polars(annotations="tag")["tag"].to_list() == [
        "Approved",
        "second-duplicate",
    ]


def test_rolling_observations_snapshot_preserves_and_replaces_annotations(tmp_path: Path) -> None:
    series = _series_def()
    stages = _AnnotatedLiveStages(series)
    stages.snapshot = True
    stages.entries_by_year[2024] = [
        (datetime(2024, 1, 1, 0, 0), 1.0, "d1", None),
        (datetime(2024, 1, 2, 0, 0), 2.0, "d2", ["P"]),
    ]
    store = StoreRoot(tmp_path / "store")
    prov = ObservationProvenance(source="Synthetic", provider_id=_PROVIDER)
    drive(
        _drive_req(datetime(2024, 1, 1), datetime(2024, 1, 5), series),
        stages,
        provenance=prov,
        transport=object(),
        cache="refresh",
        store=store,
    )

    stages.stamp = datetime(2026, 9, 2, tzinfo=UTC)
    stages.entries_by_year[2024] = [
        (datetime(2024, 1, 2, 0, 0), 2.0, "d2-updated", ["A"]),
        (datetime(2024, 1, 3, 0, 0), 3.0, "d3", ["A"]),
    ]
    updated = drive(
        _drive_req(datetime(2024, 1, 1), datetime(2024, 1, 5), series),
        stages,
        provenance=prov,
        transport=object(),
        cache="refresh",
        store=store,
    )
    assert _as_observation_result(updated, series).to_polars(annotations="tag").select("time", "tag").sort(
        "time"
    ).rows() == [
        (datetime(2024, 1, 1, 0, 0), "d1"),
        (datetime(2024, 1, 2, 0, 0), "d2-updated"),
        (datetime(2024, 1, 3, 0, 0), "d3"),
    ]


def test_failed_series_excludes_unmeasured_annotations_from_store(tmp_path: Path) -> None:
    series = _series_def()
    stages = _AnnotatedLiveStages(series)
    stages.unmeasured_times[2024] = (datetime(2024, 3, 1, 0, 0), "must-not-persist")
    stages.fail_series = True
    store = StoreRoot(tmp_path / "store")
    result = drive(
        _drive_req(datetime(2024, 1, 1), datetime(2024, 12, 31), series),
        stages,
        provenance=ObservationProvenance(source="Synthetic", provider_id=_PROVIDER),
        transport=object(),
        cache="reuse",
        store=store,
    )
    assert result.annotations.is_empty
    assert not list(Path(store).rglob("*.parquet"))


def test_compiled_store_v10_with_and_without_annotations(tmp_path: Path) -> None:
    # 1. Without annotations
    (tmp_path / "plain").mkdir()
    artifact_plain, req_plain = artifact_and_request(tmp_path / "plain")
    certified_plain = certify_store(req_plain, artifact_plain, lambda _p: complete(cert_rows(value=4.0)))
    assert certified_plain.manifest.format_version == 10
    assert audit_store(req_plain.destination, req_plain.provider_id).rows_checked == 1

    # 2. With observation rows, unmeasured-only year, and series annotations via certify_store and drive_store
    series = fixture_series()
    compiled_schema = AnnotationSchema(
        schema_id="fixture_bulk.obs",
        provider_id="fixture_bulk",
        scope=AnnotationScope.OBSERVATION,
        fields=(AnnotationField(name="qc", dtype="String", description="Bulk quality flag."),),
    )
    compiled_ser_schema = AnnotationSchema(
        schema_id="fixture_bulk.meta",
        provider_id="fixture_bulk",
        scope=AnnotationScope.SERIES,
        fields=(AnnotationField(name="basin", dtype="String", description="Gauge basin name."),),
    )
    obs_frame = pl.DataFrame(
        {
            "series_id": [series.series_id, series.series_id],
            "facts_id": [series.facts[0].facts_id, series.facts[0].facts_id],
            "station_id": [series.station_id, series.station_id],
            "product_id": [series.product_id, series.product_id],
            "time": [datetime(1998, 1, 2), datetime(1999, 5, 1)],
            "time_zone": ["Europe/Warsaw", "Europe/Warsaw"],
            "measured": [True, False],
            "qc": ["good", "ice-affected-gap"],
        },
        schema={
            "series_id": pl.String,
            "facts_id": pl.String,
            "station_id": pl.String,
            "product_id": pl.String,
            "time": pl.Datetime("us"),
            "time_zone": pl.String,
            "measured": pl.Boolean,
            **compiled_schema.polars_schema(),
        },
    )
    bundle = AnnotationBundle(
        observation_tables={
            "fixture_bulk.obs": ObservationAnnotationTable.from_rows(
                schema=compiled_schema, rows=obs_frame, measurement_indices=[0, None]
            )
        },
        series_tables={
            "fixture_bulk.meta": SeriesAnnotationTable.from_rows(
                schema=compiled_ser_schema,
                rows=pl.DataFrame(
                    {"series_id": [series.series_id], "basin": ["Vistula"]},
                    schema={"series_id": pl.String, **compiled_ser_schema.polars_schema()},
                ),
            )
        },
    )
    (tmp_path / "ann").mkdir()
    artifact_ann, req_ann = artifact_and_request(tmp_path / "ann")
    mat = complete(cert_rows(year=1998, value=12.4))
    certified_ann = certify_store(req_ann, artifact_ann, lambda _p: replace(mat, annotations=bundle))
    assert certified_ann.manifest.format_version == 10
    assert (req_ann.destination / "product=discharge/year=1998/annotations=fixture_bulk.obs/rows.parquet").is_file()
    assert not (req_ann.destination / "product=discharge/year=1999/part-0.parquet").exists()
    assert (req_ann.destination / "product=discharge/year=1999/annotations=fixture_bulk.obs/rows.parquet").is_file()
    assert audit_store(req_ann.destination, req_ann.provider_id).rows_checked == 1

    prov_cfg = _provider_config("discharge", Unit.M3_S)
    assembled = drive_store(
        ObservationRequest(
            ProviderId("fixture_bulk"),
            (series.station_id,),
            (ProductId("discharge"),),
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(1998, 1, 1)),
                WindowEndpoint.from_datetime(datetime(1999, 12, 31)),
            ),
        ),
        prov_cfg,
        req_ann.destination,
        provenance=ObservationProvenance(source="Bulk", provider_id=ProviderId("fixture_bulk")),
    )
    res_bulk = _as_observation_result(assembled, series)
    assert res_bulk.to_polars(annotations="qc")["qc"].to_list() == ["good"]
    assert rr.annotations(res_bulk, schema="fixture_bulk.obs").filter(~pl.col("measured"))["qc"].to_list() == [
        "ice-affected-gap"
    ]
    assert rr.series(res_bulk, annotations="basin")["basin"].to_list() == ["Vistula"]

    # 3. Streaming compile + certify_store_batches with annotations
    (tmp_path / "stream").mkdir()
    artifact_stream, req_stream = artifact_and_request(tmp_path / "stream")
    batch1 = NativeObservationBatch(
        cert_rows(year=1998, value=5.0),
        (SourceUnitCount("u1", 1, 1),),
        (SourceUnitContribution("u1", 1),),
        annotations=AnnotationBundle(
            observation_tables={
                "fixture_bulk.obs": ObservationAnnotationTable.from_rows(
                    schema=compiled_schema,
                    rows=obs_frame.slice(0, 1),
                    measurement_indices=[0],
                )
            }
        ),
    )
    batch2 = NativeObservationBatch(
        cert_rows(year=1999, value=6.0),
        (SourceUnitCount("u2", 1, 1),),
        (SourceUnitContribution("u2", 1),),
        annotations=AnnotationBundle(
            observation_tables={
                "fixture_bulk.obs": ObservationAnnotationTable.from_rows(
                    schema=compiled_schema,
                    rows=obs_frame.slice(0, 1).with_columns(
                        pl.lit(datetime(1999, 1, 2)).alias("time"), pl.lit("ok-1999").alias("qc")
                    ),
                    measurement_indices=[0],
                )
            }
        ),
    )
    certified_stream = certify_store_batches(
        req_stream,
        artifact_stream,
        lambda _p: ObservationBatchStream(
            COLUMNS,
            (batch1, batch2),
            2,
            2,
            source_unit_inventory_fingerprint((("u1", 1, 1), ("u2", 1, 1))),
            series_annotations=(bundle.series_tables["fixture_bulk.meta"],),
        ),
    )
    assert certified_stream.manifest.format_version == 10
    assert audit_store(req_stream.destination, req_stream.provider_id).rows_checked == 2


def test_remote_store_preserves_and_reads_annotations_selectively(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    s3_server: S3TestServer,  # noqa: F811
) -> None:
    monkeypatch.chdir(tmp_path)
    s3_server.configure_env(monkeypatch, bucket="hydro-bucket", prefix="archive")
    store = discovery._resolve_store_root("synth_ann", None)
    assert isinstance(store, RemoteStoreRoot)
    series = _series_def()

    def _outcome(oid: str, year: int) -> RetrievalOutcome:
        return RetrievalOutcome(
            outcome_id=oid,
            series_id=series.series_id,
            station_id=series.station_id,
            product_id=series.product_id,
            window=SeriesWindow(start=datetime(year, 1, 1), end=datetime(year, 12, 31, 23, 59, 59)),
            status=OutcomeStatus.SUCCESS,
            facts_ids=(series.facts[0].facts_id,),
            retrieved_at=datetime(2026, 9, 1, tzinfo=UTC),
        )

    def _rep(oid: str, year: int, val: float, tag: str) -> SuccessfulReplacement:
        out = _outcome(oid, year)
        ts = datetime(year, 2, 1)
        rows = pl.DataFrame(
            {
                "station_id": [series.station_id],
                "product_id": [series.product_id],
                "time": [ts],
                "value": [val],
                "time_zone": ["+00:00"],
                "series_id": [series.series_id],
                "facts_id": [series.facts[0].facts_id],
                "source_unit": ["m"],
            },
            schema=RowsSchema.polars_schema,
        )
        bundle = AnnotationBundle(
            observation_tables={_OBS_SCHEMA.schema_id: _make_obs_table(series, [ts], [True], [tag], [["EST"]], [0])},
            series_tables={_SER_SCHEMA.schema_id: _make_series_table(series, "remote-site")},
        )
        return SuccessfulReplacement(
            CoverageInterval(
                series.series_id, RequestedInterval(out.window.start, out.window.end), out.retrieved_at, oid
            ),
            rows,
            annotations=bundle,
        )

    accumulate(
        store,
        _PROVIDER,
        StoreUpdate(
            (series,),
            (),
            (_outcome("o-2024", 2024),),
            (_rep("o-2024", 2024, 1.0, "remote-2024"),),
            series_annotations=(_make_series_table(series, "remote-site"),),
        ),
    )
    accumulate(
        store,
        _PROVIDER,
        StoreUpdate(
            (series,),
            (),
            (_outcome("o-2025", 2025),),
            (_rep("o-2025", 2025, 2.0, "remote-2025"),),
        ),
    )

    s3_server.requests.clear()
    read_2025 = StoreReader().query(
        StoreQuery(
            store, _PROVIDER, (series.station_id,), (ProductId("level"),), datetime(2025, 1, 1), datetime(2025, 12, 31)
        )
    )
    assert read_2025.annotations.observation_tables["synth_ann.obs"].rows["tag"].to_list() == ["remote-2025"]
    assert read_2025.annotations.series_tables["synth_ann.meta"].rows["gauge_note"].to_list() == ["remote-site"]
    assert s3_server.get_requests_for("GET", "year=2025/annotations=synth_ann.obs/rows.parquet") != []
    assert s3_server.get_requests_for("GET", "year=2024/annotations=synth_ann.obs/rows.parquet") == []

    audited = audit_remote_store(store, _PROVIDER)
    assert audited.rows_checked == 2


def test_annotation_tamper_and_retired_versions_refused(tmp_path: Path) -> None:
    series = _series_def()
    stages = _AnnotatedLiveStages(series)
    stages.entries_by_year[2024] = [(datetime(2024, 6, 1, 0, 0), 10.0, "Provisional", ["EST"])]
    store = StoreRoot(tmp_path / "store")
    drive(
        _drive_req(datetime(2024, 1, 1), datetime(2024, 12, 31), series),
        stages,
        provenance=ObservationProvenance(source="Synthetic", provider_id=_PROVIDER),
        transport=object(),
        cache="reuse",
        store=store,
    )

    # Corrupt annotation parquet bytes -> integrity refusal
    ann_path = store / "product=level/year=2024/annotations=synth_ann.obs/rows.parquet"
    ann_path.write_bytes(b"corrupted-parquet-bytes")
    with pytest.raises(ObservationStoreRefusedError):
        StoreReader().query(
            StoreQuery(
                store,
                _PROVIDER,
                (series.station_id,),
                (ProductId("level"),),
                datetime(2024, 1, 1),
                datetime(2024, 12, 31),
            )
        )
    with pytest.raises(ObservationStoreRefusedError):
        audit_store(store, _PROVIDER)

    # Retired format versions (8 accumulated, 5/6 compiled) refuse with clear_cache / download guidance
    manifest_path = store / "manifest.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["format_version"] = 8
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ObservationStoreRefusedError, match="clear_cache"):
        StoreReader().status(store, _PROVIDER)

    (tmp_path / "compiled").mkdir()
    artifact_plain, req_plain = artifact_and_request(tmp_path / "compiled")
    certify_store(req_plain, artifact_plain, lambda _p: complete(cert_rows(value=4.0)))
    c_manifest = req_plain.destination / "manifest.json"
    for retired in (5, 6):
        craw = json.loads(c_manifest.read_text(encoding="utf-8"))
        craw["format_version"] = retired
        c_manifest.write_text(json.dumps(craw), encoding="utf-8")
        with pytest.raises(ObservationStoreRefusedError, match="download"):
            StoreReader().status(req_plain.destination, req_plain.provider_id)


def test_rrbundle_v4_roundtrip_and_version_or_tamper_refusal(tmp_path: Path) -> None:
    series = _series_def()
    ser_table = _make_series_table(series, "bundle-site")
    sel = _Selection(
        scope=SeriesScope(provider_ids=("synth_ann",), station_ids=(series.station_id,)),
        known_series=(series,),
        series_annotations=AnnotationBundle(series_tables={_SER_SCHEMA.schema_id: ser_table}),
    )
    sel_restored = rr.from_bundle(rr.to_bundle(sel))
    pl_testing.assert_frame_equal(rr.as_frame(sel_restored, annotations=True), rr.as_frame(sel, annotations=True))

    stages = _AnnotatedLiveStages(series)
    stages.entries_by_year[2024] = [
        (datetime(2024, 6, 1, 0, 0), 10.0, "first-dup", ["EST"]),
        (datetime(2024, 6, 1, 0, 0), 10.0, "second-dup", None),
    ]
    stages.unmeasured_times[2024] = (datetime(2024, 6, 2, 0, 0), "gap-slot")
    assembled = drive(
        _drive_req(datetime(2024, 1, 1), datetime(2024, 12, 31), series),
        stages,
        provenance=ObservationProvenance(source="Synthetic", provider_id=_PROVIDER),
        transport=object(),
        cache="bypass",
    )
    res = _as_observation_result(assembled, series)
    bundle_bytes = rr.to_bundle(res)
    restored = rr.from_bundle(bundle_bytes)
    pl_testing.assert_frame_equal(restored.to_polars(annotations=True), res.to_polars(annotations=True))
    pl_testing.assert_frame_equal(
        rr.annotations(restored, schema="synth_ann.obs"),
        rr.annotations(res, schema="synth_ann.obs"),
    )
    pl_testing.assert_frame_equal(rr.series(restored, annotations=True), rr.series(res, annotations=True))

    # Version 3 bundle is refused
    v3_buf = BytesIO()
    with ZipFile(BytesIO(bundle_bytes), "r") as src, ZipFile(v3_buf, "w", compression=ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "manifest.json":
                m = json.loads(data.decode("utf-8"))
                m["version"] = 3
                data = json.dumps(m).encode("utf-8")
            dst.writestr(info.filename, data)
    with pytest.raises(ValueError, match="Unsupported source-series bundle format version"):
        rr.from_bundle(v3_buf.getvalue())

    # Tampered annotation parquet in bundle is refused
    tampered_buf = BytesIO()
    with ZipFile(BytesIO(bundle_bytes), "r") as src, ZipFile(tampered_buf, "w", compression=ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename.startswith("annotations/"):
                data = b"tampered"
            dst.writestr(info.filename, data)
    with pytest.raises(ValueError):
        rr.from_bundle(tampered_buf.getvalue())
