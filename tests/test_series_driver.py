"""Real parser/driver checks for concrete interval accumulation."""

from datetime import datetime
from pathlib import Path

import polars.testing as pt

from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import ObservationRequest, RequestedWindow, WindowEndpoint, WithIssues
from rivretrieve._internal.observations import ObservationProvenance
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.usgs_nwis.declaration import declaration
from rivretrieve._internal.recordings import ReplayTransport
from rivretrieve._internal.store import StoreRoot


def test_multiple_real_payloads_preserve_all_native_rows_on_reuse(tmp_path):
    stages = declaration.observations.stages

    class RepeatedPayloads:
        config = stages.config
        window_declarations = stages.window_declarations
        parse = staticmethod(stages.parse)

        @staticmethod
        def fetch(*args, **kwargs):
            acquired = stages.fetch(*args, **kwargs)
            return WithIssues(acquired.value + acquired.value, acquired.issues)

    request = ObservationRequest(
        ProviderId("usgs_nwis"),
        ("07374000",),
        (ProductId("discharge_daily_mean"),),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2023, 1, 1)), WindowEndpoint.from_datetime(datetime(2023, 1, 1))
        ),
    )
    replay = ReplayTransport(
        (Path("tests/test_data/usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json"),)
    )

    def run():
        return drive(
            request,
            RepeatedPayloads(),
            provenance=ObservationProvenance(source="USGS", provider_id=ProviderId("usgs_nwis")),
            transport=replay,
            cache="reuse",
            store=StoreRoot(tmp_path / "store"),
        )

    fresh = run()
    assert fresh.canonical_rows.height == 2
    reused = run()
    pt.assert_frame_equal(reused.canonical_rows, fresh.canonical_rows)


def test_partial_success_only_covers_its_reported_interval(tmp_path):
    from dataclasses import replace

    from rivretrieve._internal.source_series import SeriesWindow
    from rivretrieve._internal.store import StoreReader

    stages = declaration.observations.stages

    class PartialWindow:
        config = stages.config
        window_declarations = stages.window_declarations
        fetch = staticmethod(stages.fetch)

        @staticmethod
        def parse(payload, config):
            parsed = stages.parse(payload, config)
            window = SeriesWindow(start=datetime(2023, 1, 1), end=datetime(2023, 1, 1, 12))
            return replace(
                parsed, outcomes=tuple(item.model_copy(update={"window": window}) for item in parsed.outcomes)
            )

    request = ObservationRequest(
        ProviderId("usgs_nwis"),
        ("07374000",),
        (ProductId("discharge_daily_mean"),),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2023, 1, 1)), WindowEndpoint.from_datetime(datetime(2023, 1, 1))
        ),
    )
    replay = ReplayTransport(
        (Path("tests/test_data/usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json"),)
    )
    store = StoreRoot(tmp_path / "store")
    result = drive(
        request,
        PartialWindow(),
        provenance=ObservationProvenance(source="USGS", provider_id=ProviderId("usgs_nwis")),
        transport=replay,
        cache="reuse",
        store=store,
    )
    assert result.canonical_rows.height == 1
    assert StoreReader().status(store, ProviderId("usgs_nwis")).coverage[0].interval.end == datetime(2023, 1, 1, 12)


def test_driver_refuses_converted_rows_outside_fact_defined_window(monkeypatch, tmp_path):
    import polars as pl
    import pytest

    import rivretrieve._internal.driver as driver
    from rivretrieve._internal.issues import FatalContractError

    original = driver.convert

    def leaking(*args, **kwargs):
        result = original(*args, **kwargs)
        return WithIssues(result.value.with_columns(pl.lit(datetime(2023, 1, 2)).alias("time")), result.issues)

    monkeypatch.setattr(driver, "convert", leaking)
    request = ObservationRequest(
        ProviderId("usgs_nwis"),
        ("07374000",),
        (ProductId("discharge_daily_mean"),),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2023, 1, 1)), WindowEndpoint.from_datetime(datetime(2023, 1, 1))
        ),
    )
    replay = ReplayTransport(
        (Path("tests/test_data/usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json"),)
    )
    with pytest.raises(FatalContractError, match="outside.*requested|outside.*Requested"):
        drive(
            request,
            declaration.observations.stages,
            provenance=ObservationProvenance(source="USGS", provider_id=ProviderId("usgs_nwis")),
            transport=replay,
        )


def test_reuse_filters_rows_by_their_actual_fact_segment(tmp_path):
    from dataclasses import replace

    import polars as pl

    from rivretrieve._internal.source_series import PhysicalPredicate, SeriesScope, known

    stages = declaration.observations.stages

    class RevisedStatistic:
        config = stages.config
        window_declarations = stages.window_declarations
        fetch = staticmethod(stages.fetch)

        @staticmethod
        def parse(payload, config):
            parsed = stages.parse(payload, config)
            revised = tuple(
                item.model_copy(
                    update={
                        "facts": tuple(
                            fact.model_copy(
                                update={
                                    "facts_id": fact.facts_id + "/minimum",
                                    "statistic": known("minimum", "authored source-fact revision"),
                                }
                            )
                            for fact in item.facts
                        )
                    }
                )
                for item in parsed.series
            )
            return replace(
                parsed,
                series=revised,
                rows=parsed.rows.with_columns((pl.col("facts_id") + "/minimum").alias("facts_id")),
                outcomes=tuple(
                    item.model_copy(
                        update={
                            "outcome_id": item.outcome_id + "/minimum",
                            "facts_ids": tuple(key + "/minimum" for key in item.facts_ids),
                        }
                    )
                    for item in parsed.outcomes
                ),
            )

    request = ObservationRequest(
        ProviderId("usgs_nwis"),
        ("07374000",),
        (ProductId("discharge_daily_mean"),),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2023, 1, 1)), WindowEndpoint.from_datetime(datetime(2023, 1, 1))
        ),
    )
    replay = ReplayTransport(
        (Path("tests/test_data/usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json"),)
    )

    def run(req, provider, cache):
        return drive(
            req,
            provider,
            provenance=ObservationProvenance(source="USGS", provider_id=ProviderId("usgs_nwis")),
            transport=replay,
            cache=cache,
            store=StoreRoot(tmp_path / "store"),
        )

    run(request, stages, "reuse")
    run(request, RevisedStatistic(), "refresh")
    precise = replace(
        request,
        scope=SeriesScope(
            provider_ids=("usgs_nwis",),
            station_ids=("07374000",),
            product_ids=("discharge_daily_mean",),
            predicates=(PhysicalPredicate(field="statistic", value="mean"),),
        ),
    )
    result = run(precise, stages, "reuse")
    assert result.canonical_rows.is_empty()
    assert any(item.status.value == "no_match" for item in result.outcomes)
    assert not result.provenance.served_intervals


def test_explicit_failed_unknown_facts_do_not_satisfy_cache_reuse(tmp_path):
    from rivretrieve._internal.driver import _reusable_snapshot
    from rivretrieve._internal.source_series import (
        EvidenceFact,
        InventoryCompleteness,
        InventorySnapshot,
        RestrictionKind,
        SeriesScope,
        SeriesWindow,
    )
    from rivretrieve._internal.store.accumulation import StoreUpdate, accumulate
    from tests.test_source_series_store import _definition

    definition = _definition("unsupported")
    fact = definition.facts[0].model_copy(update={"source_unit": EvidenceFact(), "normalized_unit": None})
    definition = definition.model_copy(update={"facts": (fact,)})
    scope = SeriesScope(
        provider_ids=("fixture_live",),
        station_ids=("a",),
        product_ids=("level",),
        restriction=RestrictionKind.EXPLICIT,
        series_ids=(definition.series_id,),
    )
    window = SeriesWindow(start=datetime(2023, 1, 1), end=datetime(2023, 1, 2))
    snapshot = InventorySnapshot(
        snapshot_id="unsupported",
        scope=scope,
        members=(definition.series_id,),
        completeness=InventoryCompleteness.INCOMPLETE,
        access="authored source answer",
        origin="response",
        window=window,
        evidence=("source unit remains unknown",),
        reason="Inventory is incomplete",
    )
    manifest = accumulate(
        StoreRoot(tmp_path / "store"), ProviderId("fixture_live"), StoreUpdate((definition,), (snapshot,), (), ())
    )
    assert _reusable_snapshot(manifest, scope, window) is None
