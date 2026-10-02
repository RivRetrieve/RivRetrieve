"""Modern publisher rows with authored stage controls for shared driver contracts."""

from datetime import datetime
from pathlib import Path

import polars.testing as pt
import pytest

from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import ObservationRequest, RequestedWindow, WindowEndpoint, WithIssues
from rivretrieve._internal.observations import ObservationProvenance
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.usgs_nwis.declaration import declaration
from rivretrieve._internal.store import StoreRoot
from tests.usgs_modern_recordings import ModernReplay


@pytest.mark.recorded("tests/test_data/usgs_modern")
def test_multiple_real_payloads_preserve_all_native_rows_on_reuse(tmp_path, retained_evidence_root: Path):
    stages = declaration.observations.stages

    class RepeatedPayloads:
        config = stages.config
        window_declarations = stages.window_declarations
        parse = staticmethod(stages.parse)

        @staticmethod
        def fetch(*args, **kwargs):
            acquired = stages.fetch(*args, **kwargs)
            from dataclasses import replace

            return replace(acquired, value=acquired.value + acquired.value)

    request = ObservationRequest(
        ProviderId("usgs_nwis"),
        ("07374000",),
        (ProductId("discharge_daily_mean"),),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1)), WindowEndpoint.from_datetime(datetime(2024, 1, 7))
        ),
    )
    replay = ModernReplay("daily-07374000-discharge-mean", evidence_root=retained_evidence_root)

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
    assert fresh.canonical_rows.height == 14
    calls = len(replay.calls)
    reused = run()
    pt.assert_frame_equal(reused.canonical_rows, fresh.canonical_rows)
    assert len(replay.calls) == calls


@pytest.mark.recorded("tests/test_data/usgs_modern")
def test_partial_success_only_covers_its_reported_interval(tmp_path, retained_evidence_root: Path):
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
            window = SeriesWindow(start=datetime(2024, 1, 1), end=datetime(2024, 1, 1, 12))
            return replace(
                parsed, outcomes=tuple(item.model_copy(update={"window": window}) for item in parsed.outcomes)
            )

    request = ObservationRequest(
        ProviderId("usgs_nwis"),
        ("07374000",),
        (ProductId("discharge_daily_mean"),),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1)), WindowEndpoint.from_datetime(datetime(2024, 1, 7))
        ),
    )
    replay = ModernReplay("daily-07374000-discharge-mean", evidence_root=retained_evidence_root)
    store = StoreRoot(tmp_path / "store")
    result = drive(
        request,
        PartialWindow(),
        provenance=ObservationProvenance(source="USGS", provider_id=ProviderId("usgs_nwis")),
        transport=replay,
        cache="reuse",
        store=store,
    )
    assert result.canonical_rows.height == 7
    assert StoreReader().status(store, ProviderId("usgs_nwis")).coverage[0].interval.end == datetime(2024, 1, 1, 12)


@pytest.mark.recorded("tests/test_data/usgs_modern")
def test_driver_refuses_converted_rows_outside_fact_defined_window(monkeypatch, tmp_path, retained_evidence_root: Path):
    import polars as pl
    import pytest

    import rivretrieve._internal.driver as driver
    from rivretrieve._internal.issues import FatalContractError

    original = driver.convert

    def leaking(*args, **kwargs):
        result = original(*args, **kwargs)
        return WithIssues(result.value.with_columns(pl.lit(datetime(2024, 1, 8)).alias("time")), result.issues)

    monkeypatch.setattr(driver, "convert", leaking)
    request = ObservationRequest(
        ProviderId("usgs_nwis"),
        ("07374000",),
        (ProductId("discharge_daily_mean"),),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1)), WindowEndpoint.from_datetime(datetime(2024, 1, 7))
        ),
    )
    replay = ModernReplay("daily-07374000-discharge-mean", evidence_root=retained_evidence_root)
    with pytest.raises(FatalContractError, match="outside.*requested|outside.*Requested"):
        drive(
            request,
            declaration.observations.stages,
            provenance=ObservationProvenance(source="USGS", provider_id=ProviderId("usgs_nwis")),
            transport=replay,
        )


@pytest.mark.recorded("tests/test_data/usgs_modern")
def test_reuse_filters_rows_by_their_actual_fact_segment(tmp_path, retained_evidence_root: Path):
    from dataclasses import replace

    import polars as pl

    from rivretrieve._internal.source_series import PhysicalPredicate, SeriesScope, known

    stages = declaration.observations.stages

    class RevisedStatistic:
        config = stages.config
        window_declarations = stages.window_declarations

        @staticmethod
        def fetch(*args, **kwargs):
            acquired = stages.fetch(*args, **kwargs)
            # Authored revision applies to the entire source answer, including
            # modern fetch's fact-scoped inventory, not only its parsed rows.
            return replace(
                acquired,
                series=tuple(
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
                            ),
                        }
                    )
                    for item in acquired.series
                ),
                inventories=tuple(
                    snapshot.model_copy(
                        update={
                            "member_facts": tuple(
                                (member, tuple(key + "/minimum" for key in facts))
                                for member, facts in snapshot.member_facts
                            ),
                        }
                    )
                    for snapshot in acquired.inventories
                ),
            )

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
            WindowEndpoint.from_datetime(datetime(2024, 1, 1)), WindowEndpoint.from_datetime(datetime(2024, 1, 7))
        ),
    )
    replay = ModernReplay("daily-07374000-discharge-mean", evidence_root=retained_evidence_root)

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
    calls = len(replay.calls)
    result = run(precise, stages, "reuse")
    assert len(replay.calls) == calls
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
    window = SeriesWindow(start=datetime(2024, 1, 1), end=datetime(2024, 1, 2))
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


@pytest.mark.parametrize(
    "defect",
    [
        "duplicate_id",
        "overlapping_success",
        "overlapping_empty",
        "touching_windows",
        "overlapping_failed",
        "overlapping_unsupported",
        "failed_before_success",
        "duplicate_unsuccessful_id",
    ],
)
@pytest.mark.recorded("tests/test_data/usgs_modern")
def test_driver_refuses_ambiguous_payload_outcomes_before_any_store_write(
    tmp_path, monkeypatch, defect, retained_evidence_root: Path
):
    from dataclasses import replace

    import rivretrieve._internal.driver as driver_module
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.source_series import OutcomeStatus, SeriesWindow

    stages = declaration.observations.stages
    parsed_counts = []
    writes = []
    real_accumulate = driver_module.accumulate

    def tracked_accumulate(*args, **kwargs):
        writes.append(True)
        return real_accumulate(*args, **kwargs)

    monkeypatch.setattr(driver_module, "accumulate", tracked_accumulate)

    class AmbiguousPayload:
        config = stages.config
        window_declarations = stages.window_declarations
        fetch = staticmethod(stages.fetch)

        @staticmethod
        def parse(payload, config):
            parsed = stages.parse(payload, config)
            parsed_counts.append(parsed.rows.height)
            original = parsed.outcomes[0]
            first = original.model_copy(
                update={
                    "window": SeriesWindow(start=datetime(2024, 1, 1), end=datetime(2024, 1, 1, 12)),
                }
            )
            if defect in ("failed_before_success", "duplicate_unsuccessful_id"):
                first = first.model_copy(update={"status": OutcomeStatus.FAILED, "reason": "Reported source failure"})
            second = first.model_copy(
                update={
                    "outcome_id": first.outcome_id
                    if defect in ("duplicate_id", "duplicate_unsuccessful_id")
                    else first.outcome_id + ":overlap",
                    "status": {
                        "overlapping_empty": OutcomeStatus.EMPTY,
                        "overlapping_failed": OutcomeStatus.FAILED,
                        "overlapping_unsupported": OutcomeStatus.UNSUPPORTED,
                        "duplicate_unsuccessful_id": OutcomeStatus.UNSUPPORTED,
                    }.get(defect, OutcomeStatus.SUCCESS),
                    "reason": "Conflicting source status"
                    if defect in ("overlapping_failed", "overlapping_unsupported", "duplicate_unsuccessful_id")
                    else None,
                    "window": SeriesWindow(
                        start=datetime(
                            2024,
                            1,
                            1,
                            13
                            if defect in ("duplicate_id", "duplicate_unsuccessful_id")
                            else 12
                            if defect == "touching_windows"
                            else 6,
                        ),
                        end=datetime(2024, 1, 1, 18),
                    ),
                }
            )
            return replace(parsed, outcomes=(first, second))

    request = ObservationRequest(
        ProviderId("usgs_nwis"),
        ("07374000",),
        (ProductId("discharge_daily_mean"),),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2024, 1, 7, 23, 59, 59, 999999)),
        ),
    )
    replay = ModernReplay("daily-07374000-discharge-mean", evidence_root=retained_evidence_root)
    with pytest.raises(FatalContractError, match="outcome|Outcome"):
        drive(
            request,
            AmbiguousPayload(),
            provenance=ObservationProvenance(source="USGS", provider_id=ProviderId("usgs_nwis")),
            transport=replay,
            cache="reuse",
            store=StoreRoot(tmp_path / "store"),
        )
    assert parsed_counts == [11], (
        "The eleven native rows in the original padded response must reach the provider parser"
    )
    assert writes == [], "Invalid parse metadata must be refused before the durable write path"
    assert not (tmp_path / "store").exists()


@pytest.mark.parametrize(
    "case",
    [
        "duplicate_rows",
        "different_facts",
        "different_series",
        "disjoint_windows",
        "unknown_failure",
        "unsuccessful_overlap",
    ],
)
@pytest.mark.recorded("tests/test_data/usgs_modern")
def test_driver_preserves_independent_rows_and_nonconflicting_payload_outcomes(
    tmp_path, case, retained_evidence_root: Path
):
    from dataclasses import replace

    import polars as pl

    from rivretrieve._internal.source_series import OutcomeStatus, RetrievalOutcome, SeriesWindow

    stages = declaration.observations.stages

    class IndependentPayload:
        config = stages.config
        window_declarations = stages.window_declarations
        fetch = staticmethod(stages.fetch)

        @staticmethod
        def parse(payload, config):
            parsed = stages.parse(payload, config)
            outcome = parsed.outcomes[0]
            definition = parsed.series[0]
            if case == "unknown_failure":
                failure = RetrievalOutcome(
                    outcome_id="unknown-series-failure",
                    series_id=None,
                    station_id=outcome.station_id,
                    product_id=outcome.product_id,
                    window=outcome.window,
                    status=OutcomeStatus.FAILED,
                    reason="An unidentified independent source series failed",
                )
                return replace(parsed, outcomes=(outcome, failure))
            if case == "unsuccessful_overlap":
                first = outcome.model_copy(
                    update={"status": OutcomeStatus.UNSUPPORTED, "reason": "Mixed source definitions"}
                )
                second = outcome.model_copy(
                    update={
                        "outcome_id": outcome.outcome_id + ":failed",
                        "status": OutcomeStatus.FAILED,
                        "reason": "Independent failure report",
                    }
                )
                return replace(parsed, outcomes=(first, second))
            if case == "duplicate_rows":
                return replace(parsed, rows=pl.concat([parsed.rows, parsed.rows]))
            if case == "disjoint_windows":
                first = outcome.model_copy(
                    update={
                        "window": SeriesWindow(start=datetime(2024, 1, 1), end=datetime(2024, 1, 1, 12)),
                    }
                )
                second = outcome.model_copy(
                    update={
                        "outcome_id": outcome.outcome_id + ":later",
                        "window": SeriesWindow(
                            start=datetime(2024, 1, 1, 12, 0, 0, 1), end=datetime(2024, 1, 7, 23, 59, 59, 999999)
                        ),
                    }
                )
                return replace(parsed, outcomes=(first, second))
            if case == "different_facts":
                fact = definition.facts[0].model_copy(update={"facts_id": definition.facts[0].facts_id + ":revision"})
                definitions = (definition.model_copy(update={"facts": (*definition.facts, fact)}),)
                additional = parsed.rows.with_columns(pl.lit(fact.facts_id).alias("facts_id"))
                second = outcome.model_copy(
                    update={"outcome_id": outcome.outcome_id + ":revision", "facts_ids": (fact.facts_id,)}
                )
                inventories = parsed.inventories
            else:
                other = definition.model_copy(update={"series_id": definition.series_id + ":independent"})
                definitions = (*parsed.series, other)
                additional = parsed.rows.with_columns(pl.lit(other.series_id).alias("series_id"))
                second = outcome.model_copy(
                    update={"outcome_id": outcome.outcome_id + ":independent", "series_id": other.series_id}
                )
                inventories = tuple(
                    snapshot.model_copy(update={"members": (*snapshot.members, other.series_id)})
                    for snapshot in parsed.inventories
                )
            return replace(
                parsed,
                rows=pl.concat([parsed.rows, additional]),
                series=definitions,
                inventories=inventories,
                outcomes=(outcome, second),
            )

    request = ObservationRequest(
        ProviderId("usgs_nwis"),
        ("07374000",),
        (ProductId("discharge_daily_mean"),),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2024, 1, 7, 23, 59, 59, 999999)),
        ),
    )
    replay = ModernReplay("daily-07374000-discharge-mean", evidence_root=retained_evidence_root)
    store = StoreRoot(tmp_path / "store")
    result = drive(
        request,
        IndependentPayload(),
        provenance=ObservationProvenance(source="USGS", provider_id=ProviderId("usgs_nwis")),
        transport=replay,
        cache="reuse",
        store=store,
    )
    assert result.canonical_rows.height == (
        7 if case in ("disjoint_windows", "unknown_failure", "unsuccessful_overlap") else 14
    )
    assert store.exists()
    if case == "duplicate_rows":
        pt.assert_frame_equal(result.canonical_rows.head(7), result.canonical_rows.tail(7))
