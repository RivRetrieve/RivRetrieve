"""Independent source facts agree across public results, persistence and reuse."""

import json
from dataclasses import replace
from datetime import UTC, datetime

import polars as pl
import polars.testing as pt
import pytest

import rivretrieve as rr
from rivretrieve._internal import bulk, discovery
from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
from rivretrieve._internal.engine import RowsSchema, SourceAcquisition, UnknownOriginFact, WithIssues
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.registry import ProviderRegistry
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    RetrievalOutcome,
    SeriesWindow,
    known,
)
from tests.test_fetch import _RecordingStages, _test_definition

PROVIDER = "independent_facts"
OLD = datetime(2026, 2, 1, tzinfo=UTC)
NEW = datetime(2026, 2, 2, tzinfo=UTC)
ROW_TIME = datetime(2026, 1, 1, 12)


class _FactStages(_RecordingStages):
    def __init__(self):
        super().__init__(PROVIDER)
        base = _test_definition(PROVIDER, "station-1", "level")
        self.definition = base.model_copy(
            update={
                "facts": tuple(
                    base.facts[0].model_copy(
                        update={"facts_id": statistic, "statistic": known(statistic, "invented fact definition")}
                    )
                    for statistic in ("mean", "max")
                )
            }
        )
        self.status = {"mean": OutcomeStatus.SUCCESS, "max": OutcomeStatus.SUCCESS}
        self.value = 1.0
        self.stamps = {"mean": OLD, "max": OLD}
        self.reverse = False
        self.complete = True
        self.members = ("mean", "max")
        self.forbid_fetch = False
        self.bad_axis = False
        self.duplicate_rows = False
        self.acquired_inventory = False
        self.route_status = None
        self.snapshot = False
        self.row_times = (ROW_TIME,)
        self.incomplete_dependency = False
        self.unknown_failure_facts = False
        self.inventory_facts = None

    def fetch(self, *args, **kwargs):
        assert not self.forbid_fetch, "covered facts must reuse without a source call"
        fetched = super().fetch(*args, **kwargs)
        base = fetched.value[0]
        payloads = tuple(
            replace(
                base,
                content=fact.encode(),
                acquisition_id=f"{len(self.calls)}-{fact}",
                origin=replace(base.origin, retrieved_at=self.stamps[fact] or UnknownOriginFact()),
            )
            for fact in self.members
        )
        payloads = tuple(reversed(payloads)) if self.reverse else payloads
        if not self.acquired_inventory and self.route_status is None:
            return WithIssues(payloads)
        window = SeriesWindow(
            start=datetime.fromisoformat(base.fetch_window.start.isoformat()),
            end=datetime.fromisoformat(base.fetch_window.end.isoformat()),
        )
        inventory = InventorySnapshot(
            snapshot_id=f"{len(self.calls)}-acquired-inventory",
            scope=base.scope,
            members=(self.definition.series_id,),
            member_facts=((self.definition.series_id, self.inventory_facts or self.members),),
            completeness=InventoryCompleteness.COMPLETE,
            access="invented fact service",
            origin="response",
            window=window,
            evidence=("invented complete response membership",),
            acquired_at=NEW,
        )
        outcomes = (
            ()
            if self.route_status is None
            else (
                RetrievalOutcome(
                    outcome_id=f"{len(self.calls)}-route",
                    series_id=None,
                    station_id="station-1",
                    product_id="level",
                    window=window,
                    status=self.route_status,
                    facts_ids=(),
                    reason="invented route uncertainty",
                    retrieved_at=NEW,
                ),
            )
        )
        return SourceAcquisition(
            payloads,
            series=(self.definition,),
            inventories=(inventory,) if self.acquired_inventory else (),
            outcomes=outcomes,
        )

    def parse(self, payload, config):
        fact = payload.content.decode()
        status = self.status[fact]
        window = SeriesWindow(
            start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
            end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
        )
        rows = pl.DataFrame(
            {
                "station_id": ["station-1"],
                "product_id": ["level"],
                "series_id": [self.definition.series_id],
                "facts_id": [fact],
                "source_unit": ["m"],
                "time": [ROW_TIME],
                "value": [self.value],
                "time_zone": ["+00:00"],
            },
            schema=RowsSchema.polars_schema,
        )
        rows = pl.concat(tuple(rows.with_columns(pl.lit(stamp).alias("time")) for stamp in self.row_times))
        if self.duplicate_rows:
            rows = pl.concat((rows, rows))
        if status is not OutcomeStatus.SUCCESS:
            rows = rows.clear()
        outcome = RetrievalOutcome(
            outcome_id=payload.acquisition_id + "-outcome",
            series_id=self.definition.series_id,
            station_id="station-1",
            product_id="level",
            window=window,
            status=status,
            facts_ids=() if self.unknown_failure_facts and status is OutcomeStatus.FAILED else (fact,),
            retrieved_at=self.stamps[fact],
            calls=(payload.acquisition_id,),
            coverage="observations" if self.snapshot else "interval",
            reason="invented max failure" if status is OutcomeStatus.FAILED else None,
        )
        if self.bad_axis and fact == "max":
            from rivretrieve._internal.time_axis import TimeAxis

            outcome = outcome.model_copy(update={"window": window.model_copy(update={"axis": TimeAxis.UTC})})
            rows = rows.with_columns(pl.lit("unknown").alias("time_zone"))
        inventory = InventorySnapshot(
            snapshot_id=payload.acquisition_id + "-inventory",
            scope=payload.scope,
            members=(self.definition.series_id,),
            member_facts=((self.definition.series_id, self.inventory_facts or self.members),),
            completeness=InventoryCompleteness.COMPLETE if self.complete else InventoryCompleteness.INCOMPLETE,
            access="invented fact service",
            origin="response",
            window=window,
            evidence=("retrieval-outcome:" + outcome.outcome_id,),
            reason=None if self.complete else "Only requested fact membership was supplied",
        )
        issues = (
            ()
            if status is not OutcomeStatus.FAILED
            else (
                Issue(
                    severity="error",
                    code="source.request_failed",
                    message=outcome.reason,
                    details={
                        "outcome_id": outcome.outcome_id,
                        "series_id": self.definition.series_id,
                        "station_id": "station-1",
                        "product_id": "level",
                        "facts_ids": list(outcome.facts_ids),
                    },
                ),
            )
        )
        definition = self.definition.model_copy(
            update={"facts": tuple(item for item in self.definition.facts if item.facts_id in self.members)}
        )
        inventories = () if self.acquired_inventory else (inventory,)
        if self.incomplete_dependency:
            dependency = inventory.model_copy(
                update={
                    "snapshot_id": inventory.snapshot_id + "-incomplete",
                    "completeness": InventoryCompleteness.INCOMPLETE,
                    "reason": "The membership prerequisite is incomplete",
                }
            )
            dependent = inventory.model_copy(update={"evidence": ("source-inventory:" + dependency.snapshot_id,)})
            inventories = (dependency, dependent)
        return ParsedSeries(rows, (definition,), inventories, (outcome,), issues)


@pytest.fixture
def fact_cache(monkeypatch, tmp_path, stub_packaged_catalogue_artifact):
    stages = _FactStages()
    artifact = stub_packaged_catalogue_artifact(PROVIDER)
    artifact = replace(
        artifact,
        source_descriptions=SourceDescriptions(
            provider_id=PROVIDER,
            descriptions=(
                SourceDescription(
                    product_id="level", identity=stages.definition.identity, facts=stages.definition.facts
                ),
            ),
        ),
    )
    registry = ProviderRegistry()
    registry.register(PROVIDER, artifact, engine_provider_module=stages)
    monkeypatch.setattr(discovery, "_registry", registry)
    monkeypatch.setattr(bulk, "_registry", registry)
    monkeypatch.setattr(bulk, "_ensure_default_providers_registered", lambda: None)
    monkeypatch.setattr(discovery, "_provider_lookup", registry.get)
    monkeypatch.setattr(discovery, "_ensure_default_providers_registered", lambda: None)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    selection = rr.find(provider=PROVIDER, station="station-1", quantity="stage")
    return stages, selection, tmp_path


def _fetch(selection, cache="refresh"):
    return rr.fetch(selection, start="2026-01-01", end="2026-01-01", cache=cache, on_issue="ignore")


def _assert_rows(frame, expected):
    columns = ["series_id", "facts_id", "time", "value", "time_zone", "source_unit"]
    definition = _test_definition(PROVIDER, "station-1", "level")
    wanted = pl.DataFrame(
        {
            "series_id": [definition.series_id] * len(expected),
            "facts_id": list(expected),
            "time": [ROW_TIME] * len(expected),
            "value": list(expected.values()),
            "time_zone": ["+00:00"] * len(expected),
            "source_unit": ["m"] * len(expected),
        },
        schema={key: frame.schema[key] for key in columns},
    )
    pt.assert_frame_equal(frame.select(columns).sort("facts_id"), wanted.sort("facts_id"))


def _saved(root):
    paths = list((root / PROVIDER / "store").rglob("*.parquet"))
    return (
        pl.concat([pl.read_parquet(path) for path in paths]) if paths else pl.DataFrame(schema=RowsSchema.polars_schema)
    )


def _assert_support(manifest, fact, stamp, call, status=OutcomeStatus.SUCCESS):
    coverage = [item for item in manifest.coverage if fact in item.facts_ids]
    assert len(coverage) == 1
    assert coverage[0].retrieved_at == stamp
    active = next(item for item in manifest.outcomes if item.outcome_id == coverage[0].outcome_id)
    assert active.status is status
    assert active.retrieved_at == stamp
    assert active.calls == (call,)
    assert any(item.get("call_id") == call for item in manifest.source_calls)


@pytest.mark.parametrize("seeded", [False, True])
@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_independent_success_and_failed_sibling_agree_in_result_store_and_reuse(fact_cache, seeded, empty, reverse):
    stages, selection, root = fact_cache
    if seeded:
        _fetch(selection)
    stages.status = {"mean": OutcomeStatus.EMPTY if empty else OutcomeStatus.SUCCESS, "max": OutcomeStatus.FAILED}
    stages.value = 2.0
    stages.stamps = {"mean": NEW, "max": NEW}
    stages.reverse = reverse
    result = _fetch(selection)
    expected = {} if empty else {"mean": 2.0}
    if seeded:
        expected["max"] = 1.0
    _assert_rows(result.data, expected)
    _assert_rows(_saved(root), expected)
    manifest = rr.cache_status(PROVIDER).manifest
    call_number = 2 if seeded else 1
    _assert_support(manifest, "mean", NEW, f"{call_number}-mean", stages.status["mean"])
    if seeded:
        _assert_support(manifest, "max", OLD, "1-max")
    else:
        assert not any("max" in item.facts_ids for item in manifest.coverage)
    for outcomes in (result.outcomes, manifest.outcomes):
        mean_success = [
            item
            for item in outcomes
            if "mean" in item.facts_ids and item.status in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY)
        ]
        assert len(mean_success) == 1
        assert mean_success[0].retrieved_at == NEW
        assert mean_success[0].calls == (f"{call_number}-mean",)
        if seeded:
            max_success = [
                item for item in outcomes if "max" in item.facts_ids and item.status is OutcomeStatus.SUCCESS
            ]
            assert len(max_success) == 1
            assert max_success[0].retrieved_at == OLD
            assert max_success[0].calls == ("1-max",)
        failures = [item for item in outcomes if item.status is OutcomeStatus.FAILED]
        assert len(failures) == 1
        assert failures[0].facts_ids == ("max",)
        assert failures[0].reason == "invented max failure"
        assert failures[0].retrieved_at == NEW
        assert failures[0].calls == (f"{call_number}-max",)
    for evidence in (result, manifest):
        failed_id = next(item.outcome_id for item in evidence.outcomes if item.status is OutcomeStatus.FAILED)
        assert any(
            issue.code == "source.request_failed" and (issue.details or {}).get("outcome_id") == failed_id
            for issue in evidence.issues
        )
    stages.forbid_fetch = True
    mean_only = rr.pick(selection, statistic="mean")
    reused = _fetch(mean_only, cache="reuse")
    _assert_rows(reused.data, {} if empty else {"mean": 2.0})
    if seeded:
        reused = _fetch(selection, cache="reuse")
        _assert_rows(reused.data, expected)
        assert any(item.status is OutcomeStatus.FAILED for item in reused.outcomes)
    else:
        stages.forbid_fetch = False
        for selected in (rr.pick(selection, statistic="max"), selection):
            before = len(stages.calls)
            _fetch(selected, cache="reuse")
            assert len(stages.calls) > before


@pytest.mark.parametrize("unknown_time", [False, True])
def test_all_success_control_reuses_each_fact_with_its_original_acquisition(fact_cache, unknown_time):
    stages, selection, _ = fact_cache
    stages.stamps = {"mean": None if unknown_time else OLD, "max": NEW}
    fresh = _fetch(selection)
    _assert_rows(fresh.data, {"mean": 1.0, "max": 1.0})
    manifest = rr.cache_status(PROVIDER).manifest
    _assert_support(manifest, "mean", stages.stamps["mean"], "1-mean")
    _assert_support(manifest, "max", NEW, "1-max")
    stages.forbid_fetch = True
    for selected, expected in (
        (selection, {"mean": 1.0, "max": 1.0}),
        (rr.pick(selection, statistic="mean"), {"mean": 1.0}),
        (rr.pick(selection, statistic="max"), {"max": 1.0}),
    ):
        _assert_rows(_fetch(selected, cache="reuse").data, expected)


def test_fatal_parsed_axis_contract_does_not_publish_any_update(fact_cache):
    stages, selection, root = fact_cache
    _fetch(selection)
    store = root / PROVIDER / "store"
    before = {path.relative_to(store): path.read_bytes() for path in store.rglob("*") if path.is_file()}
    stages.bad_axis = True
    stages.value = 2.0
    with pytest.raises(FatalContractError, match="UTC acquisition rows require published fixed offsets"):
        _fetch(selection)
    assert {path.relative_to(store): path.read_bytes() for path in store.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("complete", [False, True])
def test_only_complete_acquired_membership_can_retire_a_held_fact(fact_cache, complete):
    stages, selection, root = fact_cache
    _fetch(selection)
    stages.members = ("mean",)
    stages.complete = complete
    stages.value = 2.0
    stages.stamps["mean"] = NEW
    result = _fetch(selection)
    expected = {"mean": 2.0} if complete else {"mean": 2.0, "max": 1.0}
    _assert_rows(_saved(root), expected)
    # Broad caller selection is not a claim that an unreported sibling is obsolete.
    manifest = rr.cache_status(PROVIDER).manifest
    _assert_support(manifest, "mean", NEW, "2-mean")
    if complete:
        assert not any("max" in item.facts_ids for item in manifest.coverage)
    else:
        _assert_support(manifest, "max", OLD, "1-max")
    assert result.data.filter(pl.col("facts_id") == "mean")["value"].to_list() == [2.0]


@pytest.mark.parametrize("value", [None, 2.0])
def test_published_nulls_and_duplicate_rows_survive_independent_failure(fact_cache, value):
    stages, selection, root = fact_cache
    stages.value = value
    stages.duplicate_rows = True
    stages.status["max"] = OutcomeStatus.FAILED
    result = _fetch(selection)
    columns = ["facts_id", "time", "value"]
    expected = pl.DataFrame(
        {"facts_id": ["mean", "mean"], "time": [ROW_TIME, ROW_TIME], "value": [value, value]},
        schema={key: result.data.schema[key] for key in columns},
    )
    pt.assert_frame_equal(result.data.select(columns), expected)
    pt.assert_frame_equal(_saved(root).select(columns), expected)
    _assert_support(rr.cache_status(PROVIDER).manifest, "mean", OLD, "1-mean")


@pytest.mark.parametrize("failed", [False, True])
def test_complete_acquired_inventory_keeps_membership_separate_from_observation_failure(fact_cache, failed):
    stages, selection, root = fact_cache
    stages.acquired_inventory = True
    stages.status["max"] = OutcomeStatus.FAILED if failed else OutcomeStatus.SUCCESS
    fresh = _fetch(selection)
    expected = {"mean": 1.0} if failed else {"mean": 1.0, "max": 1.0}
    _assert_rows(fresh.data, expected)
    _assert_rows(_saved(root), expected)
    stages.forbid_fetch = True
    _assert_rows(_fetch(rr.pick(selection, statistic="mean"), cache="reuse").data, {"mean": 1.0})


@pytest.mark.parametrize("status", [OutcomeStatus.FAILED, OutcomeStatus.UNSUPPORTED, OutcomeStatus.UNRESOLVED])
@pytest.mark.parametrize("route_facts", [(), ("mean",)])
def test_identity_unknown_route_failure_vetoes_but_inventory_uncertainty_does_not(
    fact_cache, monkeypatch, status, route_facts
):
    stages, selection, root = fact_cache
    _fetch(selection)
    stages.value = 2.0
    stages.stamps = {"mean": NEW, "max": NEW}
    stages.route_status = status
    fetch = stages.fetch

    def route_with_facts(*args, **kwargs):
        acquired = fetch(*args, **kwargs)
        return replace(
            acquired, outcomes=tuple(item.model_copy(update={"facts_ids": route_facts}) for item in acquired.outcomes)
        )

    monkeypatch.setattr(stages, "fetch", route_with_facts)
    result = _fetch(selection)
    veto = status is not OutcomeStatus.UNRESOLVED
    expected = {"mean": 1.0, "max": 1.0} if veto else {"mean": 2.0, "max": 2.0}
    _assert_rows(result.data, expected)
    _assert_rows(_saved(root), expected)
    assert any(
        item.series_id is None and item.status is status and item.reason == "invented route uncertainty"
        for item in result.outcomes
    )
    manifest = rr.cache_status(PROVIDER).manifest
    for fact in ("mean", "max"):
        _assert_support(manifest, fact, OLD if veto else NEW, f"{1 if veto else 2}-{fact}")


def test_snapshot_refresh_replaces_only_published_keys_beside_failed_fact(fact_cache):
    stages, selection, root = fact_cache
    later = ROW_TIME.replace(hour=13)
    stages.row_times = (ROW_TIME, later)
    stages.snapshot = True
    _fetch(selection)
    stages.row_times = (ROW_TIME,)
    stages.value = 2.0
    stages.stamps = {"mean": NEW, "max": NEW}
    stages.status["max"] = OutcomeStatus.FAILED
    result = _fetch(selection)
    columns = ["facts_id", "time", "value"]
    expected = pl.DataFrame(
        {
            "facts_id": ["max", "max", "mean", "mean"],
            "time": [ROW_TIME, later, ROW_TIME, later],
            "value": [1.0, 1.0, 2.0, 1.0],
        },
        schema={key: result.data.schema[key] for key in columns},
    )
    pt.assert_frame_equal(result.data.select(columns).sort("facts_id", "time"), expected)
    pt.assert_frame_equal(_saved(root).select(columns).sort("facts_id", "time"), expected)
    manifest = rr.cache_status(PROVIDER).manifest
    assert manifest.coverage == ()
    support = {
        (fact, time): (item.retrieved_at, item.calls)
        for item in manifest.outcomes
        if item.status is OutcomeStatus.SUCCESS
        for fact, time, _ in item.observation_keys
    }
    assert support == {
        ("mean", ROW_TIME): (NEW, ("2-mean",)),
        ("mean", later): (OLD, ("1-mean",)),
        ("max", ROW_TIME): (OLD, ("1-max",)),
        ("max", later): (OLD, ("1-max",)),
    }


@pytest.mark.parametrize("seeded", [False, True])
def test_complete_membership_claim_cannot_outgrow_its_incomplete_dependency(fact_cache, seeded):
    stages, selection, root = fact_cache
    if seeded:
        _fetch(selection)
    stages.members = ("mean",)
    stages.incomplete_dependency = True
    stages.value = 2.0
    _fetch(selection)
    _assert_rows(_saved(root), {"mean": 2.0, "max": 1.0} if seeded else {"mean": 2.0})
    if not seeded:
        before = len(stages.calls)
        _fetch(rr.pick(selection, statistic="mean"), cache="reuse")
        assert len(stages.calls) > before, (
            "Dependent complete claims cannot turn incomplete membership into reuse proof"
        )


def test_unknown_failed_fact_scope_conservatively_preserves_both_held_facts(fact_cache):
    stages, selection, root = fact_cache
    _fetch(selection)
    stages.status["max"] = OutcomeStatus.FAILED
    stages.unknown_failure_facts = True
    stages.value = 2.0
    stages.stamps = {"mean": NEW, "max": NEW}
    result = _fetch(selection)
    _assert_rows(result.data, {"mean": 1.0, "max": 1.0})
    _assert_rows(_saved(root), {"mean": 1.0, "max": 1.0})
    manifest = rr.cache_status(PROVIDER).manifest
    for fact in ("mean", "max"):
        _assert_support(manifest, fact, OLD, "1-" + fact)
    assert any(item.status is OutcomeStatus.FAILED and item.facts_ids == () for item in manifest.outcomes)


def test_failed_fact_outside_declared_membership_cannot_be_retired(fact_cache):
    stages, selection, root = fact_cache
    _fetch(selection)
    stages.inventory_facts = ("mean",)
    stages.status["max"] = OutcomeStatus.FAILED
    stages.value = 2.0
    stages.stamps = {"mean": NEW, "max": NEW}
    result = _fetch(selection)
    _assert_rows(result.data, {"mean": 2.0, "max": 1.0})
    _assert_rows(_saved(root), {"mean": 2.0, "max": 1.0})
    manifest = rr.cache_status(PROVIDER).manifest
    _assert_support(manifest, "max", OLD, "1-max")
    assert any(item.status is OutcomeStatus.FAILED and item.facts_ids == ("max",) for item in manifest.outcomes)


def test_partial_failure_keeps_original_acquisition_as_support_not_active_coverage(fact_cache, monkeypatch):
    stages, selection, root = fact_cache
    before, after = ROW_TIME.replace(hour=11), ROW_TIME.replace(hour=13)
    stages.row_times = (before, ROW_TIME, after)
    stages.status["max"] = OutcomeStatus.FAILED
    parse = stages.parse
    failed_window = SeriesWindow(start=ROW_TIME, end=ROW_TIME.replace(minute=59, second=59, microsecond=999999))

    def partial_failure(payload, config):
        parsed = parse(payload, config)
        if payload.content == b"max":
            failed = parsed.outcomes[0].model_copy(update={"facts_ids": ("mean",), "window": failed_window})
            issues = tuple(
                issue.model_copy(update={"details": {**issue.details, "facts_ids": ["mean"]}})
                for issue in parsed.issues
            )
            return replace(parsed, inventories=(), outcomes=(failed,), issues=issues)
        return parsed

    monkeypatch.setattr(stages, "parse", partial_failure)
    result = _fetch(selection)
    columns = ["facts_id", "time", "value"]
    expected = pl.DataFrame(
        {"facts_id": ["mean", "mean"], "time": [before, after], "value": [1.0, 1.0]},
        schema={key: result.data.schema[key] for key in columns},
    )
    pt.assert_frame_equal(result.data.select(columns).sort("time"), expected)
    pt.assert_frame_equal(_saved(root).select(columns).sort("time"), expected)
    positives = [item for item in result.outcomes if item.status is OutcomeStatus.SUCCESS]
    original = next(
        item for item in positives if item.window.start < failed_window.start and item.window.end > failed_window.end
    )
    fragments = [item for item in positives if item.outcome_id != original.outcome_id]
    assert len(fragments) == 2
    assert sorted((item.window.start, item.window.end) for item in fragments) == [
        (original.window.start, ROW_TIME.replace(hour=11, minute=59, second=59, microsecond=999999)),
        (after, original.window.end),
    ]
    assert original.facts_ids == ("mean",)
    assert original.calls == ("1-mean",)
    assert original.retrieved_at == OLD
    manifest = rr.cache_status(PROVIDER).manifest
    assert {item.outcome_id for item in manifest.coverage} == {item.outcome_id for item in fragments}
    assert original.outcome_id not in {item.outcome_id for item in manifest.outcomes}
    document = json.loads((root / PROVIDER / "store" / "manifest.json").read_text())
    supporting = tuple(RetrievalOutcome.model_validate(item) for item in document["supporting_outcomes"])
    assert original in supporting
    assert all(item.calls == original.calls and item.retrieved_at == original.retrieved_at for item in fragments)
    assert any("retrieval-outcome:" + original.outcome_id in item.evidence for item in manifest.inventories)
    assert any(item.status is OutcomeStatus.FAILED and item.window == failed_window for item in manifest.outcomes)


def test_single_payload_independent_facts_can_have_different_acquisition_axes(fact_cache, monkeypatch):
    from rivretrieve._internal.time_axis import TimeAxis

    stages, selection, root = fact_cache
    stages.members = ("mean",)
    parse = stages.parse

    def mixed_axes(payload, config):
        parsed = parse(payload, config)
        mean = parsed.outcomes[0]
        maximum = mean.model_copy(
            update={
                "outcome_id": "utc-max",
                "facts_ids": ("max",),
                "window": mean.window.model_copy(update={"axis": TimeAxis.UTC}),
            }
        )
        native = parsed.rows.with_columns(pl.lit("unknown").alias("time_zone"))
        utc = parsed.rows.with_columns(pl.lit("max").alias("facts_id"))
        return replace(
            parsed, rows=pl.concat([native, utc]), series=(stages.definition,), outcomes=(mean, maximum), inventories=()
        )

    monkeypatch.setattr(stages, "parse", mixed_axes)
    result = _fetch(selection)
    expected = pl.DataFrame({"facts_id": ["max", "mean"], "time_zone": ["+00:00", "unknown"], "value": [1.0, 1.0]})
    columns = expected.columns
    pt.assert_frame_equal(result.data.select(columns).sort("facts_id"), expected)
    pt.assert_frame_equal(_saved(root).select(columns).sort("facts_id"), expected)
    manifest = rr.cache_status(PROVIDER).manifest
    assert {(fact, item.interval.axis) for item in manifest.coverage for fact in item.facts_ids} == {
        ("mean", TimeAxis.NATIVE),
        ("max", TimeAxis.UTC),
    }


@pytest.mark.parametrize("source_status", [OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY])
def test_failure_veto_preserves_nonempty_and_successful_empty_source_answers(fact_cache, source_status):
    stages, selection, root = fact_cache
    stages.status["mean"] = source_status
    stages.status["max"] = OutcomeStatus.FAILED
    stages.unknown_failure_facts = True
    result = _fetch(selection)
    assert result.data.is_empty()
    assert _saved(root).is_empty()
    source = next(item for item in result.outcomes if item.status in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY))
    assert source.status is source_status
    assert source.facts_ids == ("mean",)
    assert source.calls == ("1-mean",)
    assert source.retrieved_at == OLD
    manifest = rr.cache_status(PROVIDER).manifest
    assert manifest.coverage == ()
    assert all(item.status not in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY) for item in manifest.outcomes)


@pytest.mark.parametrize("unrelated_failure", [False, True])
@pytest.mark.parametrize("on_issue", ["ignore", "raise"])
def test_partial_snapshot_keeps_original_source_note_despite_unrelated_diagnosis(
    fact_cache, monkeypatch, unrelated_failure, on_issue
):
    from rivretrieve._internal.issues import IssuePolicyError

    stages, selection, _ = fact_cache
    stages.members = ("mean",)
    stages.snapshot = True
    stages.row_times = (ROW_TIME, ROW_TIME.replace(hour=13))
    selected = rr.pick(selection, statistic="mean")
    parse = stages.parse

    def with_original_note(payload, config):
        parsed = parse(payload, config)
        if payload.acquisition_id == "1-mean":
            note = Issue(
                severity="warning",
                code="source.note",
                message="Original snapshot count",
                details={"count": 7, "outcome_id": parsed.outcomes[0].outcome_id},
            )
            return replace(parsed, issues=(note,))
        return parsed

    monkeypatch.setattr(stages, "parse", with_original_note)
    fresh = rr.fetch(selected, start="2026-01-01", end="2026-01-01", cache="refresh", on_issue="ignore")
    original_note = next(issue for issue in fresh.issues if issue.code == "source.note")
    original = next(outcome for outcome in fresh.outcomes if outcome.status is OutcomeStatus.SUCCESS)
    if unrelated_failure:
        stages.snapshot = False
        stages.status["mean"] = OutcomeStatus.FAILED
        rr.fetch(selected, start="2026-01-10", end="2026-01-10", cache="refresh", on_issue="ignore")
    stages.snapshot = True
    stages.status["mean"] = OutcomeStatus.SUCCESS
    stages.row_times = (ROW_TIME.replace(hour=13),)
    stages.value = 2.0
    if on_issue == "raise":
        with pytest.raises(IssuePolicyError) as caught:
            rr.fetch(selected, start="2026-01-01", end="2026-01-01", cache="refresh", on_issue="raise")
        assert original_note in caught.value.issues
        return
    mixed = rr.fetch(selected, start="2026-01-01", end="2026-01-01", cache="refresh", on_issue="ignore")
    assert original_note in mixed.issues
    assert original in mixed.outcomes
    expected = pl.DataFrame({"time": [ROW_TIME, ROW_TIME.replace(hour=13)], "value": [1.0, 2.0]})
    pt.assert_frame_equal(mixed.data.select("time", "value").sort("time"), expected)
    stored = rr.cache_status(PROVIDER).manifest
    current_note = next(issue for issue in stored.issues if issue.code == "source.note")
    assert current_note.details["original_outcome_id"] == original.outcome_id
    held = rr.fetch(selected, start="2026-01-01", end="2026-01-01", cache="reuse", on_issue="ignore")
    pt.assert_frame_equal(held.data, mixed.data)
    assert next(issue for issue in held.issues if issue.code == "source.note").details["count"] == 7


@pytest.mark.parametrize("on_issue", ["ignore", "raise"])
def test_repeated_snapshot_compaction_keeps_source_note_root_lineage(fact_cache, monkeypatch, on_issue):
    from rivretrieve._internal.issues import IssuePolicyError

    stages, selection, _ = fact_cache
    stages.members = ("mean",)
    stages.snapshot = True
    compactions = 2
    stages.row_times = tuple(ROW_TIME.replace(hour=12 + index) for index in range(compactions + 1))
    selected = rr.pick(selection, statistic="mean")
    parse = stages.parse

    def with_original_note(payload, config):
        parsed = parse(payload, config)
        if payload.acquisition_id == "1-mean":
            return replace(
                parsed,
                issues=(
                    Issue(
                        severity="warning",
                        code="source.note",
                        message="Original snapshot count",
                        details={"count": 7, "outcome_id": parsed.outcomes[0].outcome_id},
                    ),
                ),
            )
        return parsed

    monkeypatch.setattr(stages, "parse", with_original_note)
    fresh = rr.fetch(selected, start="2026-01-01", end="2026-01-01", cache="refresh", on_issue="ignore")
    root_id = next(issue for issue in fresh.issues if issue.code == "source.note").details["outcome_id"]
    stages.snapshot = False
    stages.status["mean"] = OutcomeStatus.FAILED
    rr.fetch(selected, start="2026-01-10", end="2026-01-10", cache="refresh", on_issue="ignore")
    stages.snapshot = True
    stages.status["mean"] = OutcomeStatus.SUCCESS
    for index in range(1, compactions + 1):
        prior = rr.cache_status(PROVIDER).manifest
        prior_note = next(issue for issue in prior.issues if issue.code == "source.note")
        prior_id = prior_note.details["outcome_id"]
        assert prior_id in {item.outcome_id for item in prior.outcomes if item.status is OutcomeStatus.SUCCESS}
        assert prior_note.details.get("original_outcome_id", prior_id) == root_id
        if index > 1:
            assert prior_id != root_id
        stages.row_times = (ROW_TIME.replace(hour=12 + index),)
        stages.value = float(index + 1)
        policy = on_issue if index == compactions else "ignore"
        if policy == "raise":
            with pytest.raises(IssuePolicyError) as caught:
                rr.fetch(selected, start="2026-01-01", end="2026-01-01", cache="refresh", on_issue=policy)
            assert prior_note in caught.value.issues
        else:
            mixed = rr.fetch(selected, start="2026-01-01", end="2026-01-01", cache="refresh", on_issue=policy)
            assert prior_note in mixed.issues
        current = rr.cache_status(PROVIDER).manifest
        current_note = next(issue for issue in current.issues if issue.code == "source.note")
        assert current_note.details["original_outcome_id"] == root_id
        assert current_note.details["count"] == 7
    held = rr.fetch(selected, start="2026-01-01", end="2026-01-01", cache="reuse", on_issue="ignore")
    expected = pl.DataFrame(
        {
            "time": [ROW_TIME.replace(hour=12 + index) for index in range(compactions + 1)],
            "value": [float(index + 1) for index in range(compactions + 1)],
        }
    )
    pt.assert_frame_equal(held.data.select("time", "value").sort("time"), expected)
