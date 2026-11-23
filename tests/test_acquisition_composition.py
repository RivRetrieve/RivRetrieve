"""Acquisition identity and overlapping transaction composition through the driver."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.driver import _combine_replacements, drive
from rivretrieve._internal.engine import (
    ObservationRequest,
    RequestedWindow,
    SourceAcquisition,
    SourceCoordinates,
    WindowEndpoint,
    WithIssues,
    _make_fetch_window,
)
from rivretrieve._internal.observations import ObservationProvenance, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.cz_chmi.declaration import declaration
from rivretrieve._internal.providers.cz_chmi.parse import parse
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.store import StoreReader, StoreRoot
from rivretrieve._internal.time_axis import TimeAxis
from tests.test_chmi_source_boundary_isolation import _payload
from tests.test_source_series_store import _success


def single_payload(retained_evidence_root):
    payload = _payload(retained_evidence_root)
    return replace(
        payload,
        station_products=(("0-203-1-000400", ProductId("discharge_daily_mean")),),
        source_coordinates=SourceCoordinates(replace(payload.source_coordinates.value, ts_con_ids=("QD",))),
    )


def run(store, payloads):
    stages = declaration.observations.stages
    provider = SimpleNamespace(
        config=stages.config,
        window_declarations=stages.window_declarations,
        fetch=lambda *args, **kwargs: payloads if isinstance(payloads, SourceAcquisition) else WithIssues(payloads),
        parse=parse,
    )
    return drive(
        ObservationRequest(
            ProviderId("cz_chmi"),
            ("0-203-1-000400",),
            (ProductId("discharge_daily_mean"),),
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2023, 6, 1)), WindowEndpoint.from_datetime(datetime(2023, 6, 2))
            ),
        ),
        provider,
        provenance=ObservationProvenance(source="CHMI", provider_id=ProviderId("cz_chmi")),
        cache="refresh",
        store=StoreRoot(store),
        receipts=ReceiptMode.INCLUDE,
    )


@pytest.mark.parametrize("failed_first", [False, True])
@pytest.mark.recorded("tests/test_data/cz_chmi_0-203-1-000400_DQ_2023.recording.json")
def test_overlapping_failure_fallback_is_order_independent(retained_evidence_root, tmp_path, failed_first):
    payload = single_payload(retained_evidence_root)
    held = run(tmp_path / "store", (payload,))
    failed = replace(payload, content=b"{}", acquisition_id="failed")
    fresh = replace(payload, acquisition_id="fresh")
    result = run(tmp_path / "store", (failed, fresh) if failed_first else (fresh, failed))
    assert_frame_equal(result.canonical_rows, held.canonical_rows)
    manifest = StoreReader().status(StoreRoot(tmp_path / "store"), ProviderId("cz_chmi")).manifest
    assert len(manifest.coverage) == 1
    assert manifest.coverage[0].outcome_id == held.outcomes[0].outcome_id
    assert any(item.status is OutcomeStatus.UNSUPPORTED for item in result.outcomes)


@pytest.mark.recorded("tests/test_data/cz_chmi_0-203-1-000400_DQ_2023.recording.json")
def test_equal_failed_bytes_and_timestamps_keep_distinct_calls_and_inventories(retained_evidence_root, tmp_path):
    payload = replace(single_payload(retained_evidence_root), content=b"{}")
    result = run(
        tmp_path / "store", (replace(payload, acquisition_id="first"), replace(payload, acquisition_id="second"))
    )
    unsupported = [item for item in result.outcomes if item.status is OutcomeStatus.UNSUPPORTED]
    assert len(unsupported) == 2
    assert {item.calls for item in unsupported} == {("first",), ("second",)}
    assert len(result.receipts.entries) == 2
    assert len([item for item in result.inventories if item.origin == "response"]) == 2
    assert {item["call_id"] for item in result.provenance.calls_made} == {"first", "second"}


def test_unknown_series_failed_request_keeps_call_and_interval(tmp_path):
    from rivretrieve._internal.source_acquisition import FailedSourceRequest, SourceRequestTarget
    from rivretrieve._internal.source_series import SeriesWindow
    from rivretrieve._internal.transport import HttpMethod, TransportFailure, TransportFailureReason, TransportRequest

    request = TransportRequest(HttpMethod.GET, "https://example.test/observations")
    event = FailedSourceRequest(
        "unknown-failure",
        SourceRequestTarget("0-203-1-000400", "discharge_daily_mean"),
        SeriesWindow(start=datetime(2023, 6, 1), end=datetime(2023, 6, 2)),
        request,
        TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503),
    )
    result = run(tmp_path / "store", SourceAcquisition((), failed_requests=(event,)))
    assert result.canonical_rows.is_empty()
    assert result.outcomes[0].series_id is None
    assert result.outcomes[0].calls == ("unknown-failure",)
    assert result.provenance.calls_made[0]["status_code"] == 503


@pytest.mark.parametrize(("failure_kind", "failed_first"), [("unknown", False), ("partial", False), ("partial", True)])
@pytest.mark.recorded("tests/test_data/cz_chmi_0-203-1-000400_DQ_2023.recording.json")
def test_failed_overlap_returned_rows_agree_with_persisted_replacement(
    retained_evidence_root, tmp_path, failed_first, failure_kind
):
    from rivretrieve._internal.source_acquisition import FailedSourceRequest, SourceRequestTarget
    from rivretrieve._internal.source_series import SeriesWindow
    from rivretrieve._internal.transport import HttpMethod, TransportFailure, TransportFailureReason, TransportRequest

    payload = single_payload(retained_evidence_root)
    store = tmp_path / "store"
    held = run(store, (payload,))
    document = json.loads(payload.content)
    for member in document["tsList"]:
        for row in member["tsData"]["data"]["values"]:
            row[1] = 999
    fresh = replace(payload, content=json.dumps(document).encode(), acquisition_id="new-values")
    if failure_kind == "unknown":
        request = TransportRequest(HttpMethod.GET, "https://example.test/observations")
        event = FailedSourceRequest(
            "unknown-failure",
            SourceRequestTarget("0-203-1-000400", "discharge_daily_mean"),
            SeriesWindow(start=datetime(2023, 6, 1), end=datetime(2023, 6, 2, 23, 59, 59, 999999)),
            request,
            TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503),
        )
        acquired = SourceAcquisition((fresh,), failed_requests=(event,))
        expected = held.canonical_rows
    else:
        failed = replace(
            payload,
            content=b"{}",
            acquisition_id="failed-subinterval",
            fetch_window=_make_fetch_window(
                WindowEndpoint.from_datetime(datetime(2023, 6, 2)),
                WindowEndpoint.from_datetime(datetime(2023, 6, 2, 23, 59, 59, 999999)),
            ),
        )
        acquired = (failed, fresh) if failed_first else (fresh, failed)
        expected = held.canonical_rows.with_columns(
            pl.when(pl.col("time").dt.day() == 1).then(999.0).otherwise(pl.col("value")).alias("value")
        )
    result = run(store, acquired)
    assert_frame_equal(result.canonical_rows.sort("time"), expected.sort("time"))
    persisted = pl.concat([pl.read_parquet(path) for path in store.rglob("*.parquet")])
    assert_frame_equal(persisted.select("time", "value").sort("time"), expected.select("time", "value").sort("time"))


@pytest.mark.parametrize("overlap", [False, True])
@pytest.mark.recorded("tests/test_data/cz_chmi_0-203-1-000400_DQ_2023.recording.json")
def test_snapshot_contributions_keep_distinct_key_groups_and_acquisition_vintages(
    retained_evidence_root, tmp_path, monkeypatch, overlap
):
    from rivretrieve._internal.issues import FatalContractError

    original_parse = parse

    def snapshot_parse(payload, config):
        parsed = original_parse(payload, config)
        day = 1 if payload.acquisition_id == "first" or overlap else 2
        return replace(
            parsed,
            rows=parsed.rows.filter(pl.col("time").dt.day() == day),
            outcomes=tuple(item.model_copy(update={"coverage": "observations"}) for item in parsed.outcomes),
        )

    monkeypatch.setattr("tests.test_acquisition_composition.parse", snapshot_parse)
    payload = single_payload(retained_evidence_root)
    first_time = datetime(2026, 9, 28, tzinfo=UTC)
    second_time = datetime(2026, 9, 29, tzinfo=UTC)
    payloads = (
        replace(payload, acquisition_id="first", origin=replace(payload.origin, retrieved_at=first_time)),
        replace(payload, acquisition_id="second", origin=replace(payload.origin, retrieved_at=second_time)),
    )
    if overlap:
        with pytest.raises(FatalContractError, match="Independent snapshot acquisitions overlap"):
            run(tmp_path / "store", payloads)
        return
    result = run(tmp_path / "store", payloads)
    assert result.canonical_rows.height == 2
    manifest = StoreReader().status(StoreRoot(tmp_path / "store"), ProviderId("cz_chmi")).manifest
    assert manifest.coverage == ()
    assert {key[1].day: item.retrieved_at for item in manifest.outcomes for key in item.observation_keys} == {
        1: first_time,
        2: second_time,
    }


@pytest.mark.parametrize("defect", ["mixed_failure", "unknown_offset"])
@pytest.mark.recorded("tests/test_data/cz_chmi_0-203-1-000400_DQ_2023.recording.json")
def test_incompatible_axis_evidence_is_fatal_before_cache_mutation(
    retained_evidence_root, tmp_path, monkeypatch, defect
):
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.source_acquisition import FailedSourceRequest, SourceRequestTarget
    from rivretrieve._internal.source_series import SeriesWindow
    from rivretrieve._internal.time_axis import TimeAxis
    from rivretrieve._internal.transport import HttpMethod, TransportFailure, TransportFailureReason, TransportRequest

    store = tmp_path / "store"
    payload = single_payload(retained_evidence_root)
    run(store, (payload,))
    before = {path.relative_to(store): path.read_bytes() for path in store.rglob("*") if path.is_file()}
    original_parse = parse

    def axis_parse(received, config):
        parsed = original_parse(received, config)
        return replace(
            parsed,
            rows=parsed.rows.with_columns(
                pl.lit("unknown" if defect == "unknown_offset" else "+00:00").alias("time_zone")
            ),
            outcomes=tuple(
                item.model_copy(update={"window": item.window.model_copy(update={"axis": TimeAxis.UTC})})
                for item in parsed.outcomes
            ),
        )

    monkeypatch.setattr("tests.test_acquisition_composition.parse", axis_parse)
    if defect == "mixed_failure":
        request = TransportRequest(HttpMethod.GET, "https://example.test/observations")
        failure = FailedSourceRequest(
            "native-failure",
            SourceRequestTarget("0-203-1-000400", "discharge_daily_mean"),
            SeriesWindow(start=datetime(2023, 6, 1), end=datetime(2023, 6, 2)),
            request,
            TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503),
        )
        acquired = SourceAcquisition((payload,), failed_requests=(failure,))
        message = "cannot mix acquisition time axes"
    else:
        acquired = (payload,)
        message = "UTC acquisition rows require published fixed offsets"
    with pytest.raises(FatalContractError, match=message):
        run(store, acquired)
    assert {path.relative_to(store): path.read_bytes() for path in store.rglob("*") if path.is_file()} == before


@pytest.mark.recorded("tests/test_data/cz_chmi_0-203-1-000400_DQ_2023.recording.json")
def test_fresh_successful_payloads_cannot_mix_axes_for_one_series_fact(retained_evidence_root, tmp_path, monkeypatch):
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.time_axis import TimeAxis

    original_parse = parse

    def axis_parse(payload, config):
        parsed = original_parse(payload, config)
        return replace(
            parsed,
            rows=parsed.rows.with_columns(pl.lit("+00:00").alias("time_zone")),
            outcomes=tuple(
                item.model_copy(
                    update={
                        "window": item.window.model_copy(
                            update={"axis": TimeAxis.UTC if payload.acquisition_id == "utc" else TimeAxis.NATIVE}
                        )
                    }
                )
                for item in parsed.outcomes
            ),
        )

    monkeypatch.setattr("tests.test_acquisition_composition.parse", axis_parse)
    payload = single_payload(retained_evidence_root)
    with pytest.raises(FatalContractError, match="cannot mix acquisition time axes"):
        run(tmp_path / "store", (payload, replace(payload, acquisition_id="utc")))
    assert not (tmp_path / "store").exists()


def contribution(facts, *, name="success", instant=datetime(2026, 9, 1, tzinfo=UTC)):
    outcome, replacement = _success("series", name, [1.0, None, 1.0])
    outcome = outcome.model_copy(update={"facts_ids": facts, "retrieved_at": instant, "calls": (name,)})
    rows = pl.concat([replacement.rows.with_columns(pl.lit(fact).alias("facts_id")) for fact in facts])
    return outcome, replace(
        replacement,
        rows=rows,
        coverage=replace(replacement.coverage, facts_ids=facts, retrieved_at=instant),
    )


@pytest.mark.parametrize("status", [OutcomeStatus.FAILED, OutcomeStatus.UNSUPPORTED, OutcomeStatus.UNRESOLVED])
@pytest.mark.parametrize("facts", [("maximum",), ()])
def test_composition_subtracts_failure_by_facts_and_closed_time(status, facts):
    positive, replacement = contribution(("mean", "maximum"))
    boundary = datetime(2020, 1, 1, 12)
    failure = positive.model_copy(
        update={
            "outcome_id": "failure",
            "facts_ids": facts,
            "status": status,
            "reason": "unavailable",
            "window": positive.window.model_copy(update={"start": boundary}),
        }
    )
    results = _combine_replacements([replacement], [positive, failure], [])
    scopes = {
        (fact, part.coverage.interval.start, part.coverage.interval.end)
        for part in results
        for fact in part.coverage.facts_ids
    }
    end = datetime(2020, 1, 1, 11, 59, 59, 999999)
    assert scopes == {
        ("mean", positive.window.start, positive.window.end if facts else end),
        ("maximum", positive.window.start, end),
    }


@pytest.mark.parametrize("unknown", [False, True])
def test_independent_facts_keep_original_calls_times_and_multiplicity(unknown):
    first = contribution(("mean",), name="mean", instant=None if unknown else datetime(2026, 8, 1, tzinfo=UTC))
    second = contribution(("maximum",), name="maximum")
    fresh = [first[0], second[0]]
    results = _combine_replacements([first[1], second[1]], fresh, [])
    by_id = {item.outcome_id: item for item in fresh}
    assert len(results) == 2
    for result in results:
        expected = first if result.coverage.facts_ids == ("mean",) else second
        assert result.coverage.retrieved_at == expected[0].retrieved_at
        assert by_id[result.coverage.outcome_id].calls == expected[0].calls
        assert_frame_equal(result.rows, expected[1].rows)


@pytest.mark.parametrize("time_disjoint", [False, True])
def test_disjoint_failed_fact_does_not_compare_time_axes(time_disjoint):
    positive, replacement = contribution(("mean",))
    failure = positive.model_copy(
        update={
            "outcome_id": "failure",
            "facts_ids": ("maximum",),
            "status": OutcomeStatus.FAILED,
            "reason": "unavailable",
            "window": positive.window.model_copy(update={"axis": TimeAxis.UTC}),
        }
    )
    if time_disjoint:
        failure = failure.model_copy(
            update={
                "window": failure.window.model_copy(
                    update={
                        "start": datetime(2020, 1, 2),
                        "end": datetime(2020, 1, 3),
                    }
                )
            }
        )
    assert _combine_replacements([replacement], [positive, failure], []) == [replacement]


@pytest.mark.parametrize("status", list(OutcomeStatus))
@pytest.mark.parametrize("identity", ["series", "different-series", None])
def test_failure_domains_preserve_unrelated_series_and_inventory_uncertainty(status, identity):
    positive, replacement = contribution(("mean",))
    failure = positive.model_copy(
        update={
            "outcome_id": "other",
            "series_id": identity,
            "status": status,
            "reason": "invented scope",
        }
    )
    result = _combine_replacements([replacement], [positive, failure], [])
    veto = status in (OutcomeStatus.FAILED, OutcomeStatus.UNSUPPORTED) and identity in ("series", None)
    veto |= status is OutcomeStatus.UNRESOLVED and identity == "series"
    assert len(result) == (0 if veto else 1)


def test_partial_shared_facts_compose_pages_without_borrowing_sibling_evidence():
    broad = contribution(("mean", "maximum"), name="broad", instant=None)
    narrow = contribution(("mean",), name="page")
    fresh = [broad[0], narrow[0]]
    results = _combine_replacements([broad[1], narrow[1]], fresh, [])
    by_id = {item.outcome_id: item for item in fresh}
    assert len(results) == 2
    mean = next(item for item in results if item.coverage.facts_ids == ("mean",))
    maximum = next(item for item in results if item.coverage.facts_ids == ("maximum",))
    assert_frame_equal(mean.rows, pl.concat([broad[1].rows.filter(pl.col("facts_id") == "mean"), narrow[1].rows]))
    assert by_id[mean.coverage.outcome_id].calls == ("broad", "page")
    assert by_id[maximum.coverage.outcome_id].calls == ("broad",)
    assert maximum.coverage.retrieved_at is None


def test_same_fact_axis_mismatch_remains_fatal():
    from rivretrieve._internal.issues import FatalContractError

    positive, replacement = contribution(("mean",))
    failed = positive.model_copy(
        update={
            "outcome_id": "failed",
            "status": OutcomeStatus.FAILED,
            "reason": "invented failure",
            "window": positive.window.model_copy(update={"axis": TimeAxis.UTC}),
        }
    )
    with pytest.raises(FatalContractError, match="cannot mix acquisition time axes"):
        _combine_replacements([replacement], [positive, failed], [])


@pytest.mark.parametrize("overlap", [False, True])
def test_synthetic_snapshot_composition_preserves_exact_keys_and_overlap_guard(overlap):
    from rivretrieve._internal.issues import FatalContractError

    pairs = [contribution(("mean",), name="first"), contribution(("mean",), name="second")]
    if not overlap:
        pairs[1] = (
            pairs[1][0],
            replace(pairs[1][1], rows=pairs[1][1].rows.with_columns(pl.lit(datetime(2020, 1, 1, 12)).alias("time"))),
        )
    outcomes = [
        item.model_copy(
            update={
                "coverage": "observations",
                "observation_keys": tuple(dict.fromkeys(part.rows.select("facts_id", "time", "time_zone").iter_rows())),
            }
        )
        for item, part in pairs
    ]
    if overlap:
        with pytest.raises(FatalContractError, match="Independent snapshot acquisitions overlap"):
            _combine_replacements([part for _, part in pairs], outcomes, [])
    else:
        results = _combine_replacements([part for _, part in pairs], outcomes, [])
        assert len(results) == 2
        for part, (_, expected) in zip(results, pairs, strict=True):
            assert_frame_equal(part.rows, expected.rows)


def test_fact_failure_closed_endpoint_filters_rows_at_the_boundary():
    positive, replacement = contribution(("mean", "maximum"))
    stamps = [datetime(2020, 1, 1, 11, 59, 59, 999999), datetime(2020, 1, 1, 12), datetime(2020, 1, 1, 13)]
    rows = pl.concat(
        [
            replacement.rows.head(1).with_columns(
                pl.lit(fact).alias("facts_id"), pl.lit(stamp).alias("time"), pl.lit(2.0).alias("value")
            )
            for fact in ("mean", "maximum")
            for stamp in stamps
        ]
    )
    failed = positive.model_copy(
        update={
            "outcome_id": "failure",
            "status": OutcomeStatus.FAILED,
            "facts_ids": ("maximum",),
            "reason": "boundary failure",
            "window": positive.window.model_copy(update={"start": stamps[1]}),
        }
    )
    results = _combine_replacements([replace(replacement, rows=rows)], [positive, failed], [])
    accepted = pl.concat([item.rows for item in results])
    expected = rows.filter((pl.col("facts_id") == "mean") | (pl.col("time") < stamps[1]))
    assert_frame_equal(accepted.sort("facts_id", "time"), expected.sort("facts_id", "time"))


@pytest.mark.parametrize("failed_first", [False, True])
def test_failed_acquisition_follows_its_support_without_reordering_independent_payloads(failed_first):
    from rivretrieve._internal.driver import _calls_with_failed_acquisitions

    support = {"call_id": "html", "prerequisite_acquisition_ids": ()}
    healthy = ({"call_id": "other-html"}, {"call_id": "other-dat"})
    failure = {"call_id": "failed-dat", "prerequisite_acquisition_ids": ("html",)}
    payloads = (support, *healthy) if failed_first else (*healthy, support)
    expected = (support, failure, *healthy) if failed_first else (*healthy, support, failure)
    assert _calls_with_failed_acquisitions(payloads, (failure,)) == expected


@pytest.mark.parametrize("dependencies", [("missing",), ("failed",)])
def test_invalid_failed_dependency_is_fatal_before_store_publication(tmp_path, dependencies):
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.source_acquisition import FailedSourceRequest, SourceRequestTarget
    from rivretrieve._internal.source_series import SeriesWindow
    from rivretrieve._internal.transport import HttpMethod, TransportFailure, TransportFailureReason, TransportRequest

    request = TransportRequest(HttpMethod.GET, "https://example.test/observations")
    event = FailedSourceRequest(
        "failed",
        SourceRequestTarget("0-203-1-000400", "discharge_daily_mean"),
        SeriesWindow(start=datetime(2023, 6, 1), end=datetime(2023, 6, 2)),
        request,
        TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503),
        prerequisite_acquisition_ids=dependencies,
    )
    with pytest.raises(FatalContractError, match="Prerequisite"):
        run(tmp_path / "store", SourceAcquisition((), failed_requests=(event,)))
    assert not (tmp_path / "store" / "manifest.json").exists()


@pytest.mark.parametrize("with_independent", [False, True])
def test_failed_siblings_keep_original_call_group_order(with_independent):
    from rivretrieve._internal.driver import _calls_with_failed_acquisitions

    html = {"call_id": "html"}
    first = (
        {"call_id": "first-retry", "acquisition_id": "first-dat", "prerequisite_acquisition_ids": ("html",)},
        {"call_id": "first-final", "acquisition_id": "first-dat", "prerequisite_acquisition_ids": ("html",)},
    )
    second = {"call_id": "second-dat", "prerequisite_acquisition_ids": ("html",)}
    independent = ({"call_id": "independent-one"}, {"call_id": "independent-two"}) if with_independent else ()
    failures = (*independent[:1], *first, second, *independent[1:])
    assert _calls_with_failed_acquisitions((html,), failures) == (*independent, html, *first, second)


def test_bypass_skips_persistence_copies_and_preserves_outcome_and_axis_composition(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    import rivretrieve._internal.driver as drv_mod
    from rivretrieve._internal.engine import (
        Instant,
        Payload,
        ProductConfig,
        ProductWindowDeclarations,
        ProviderConfig,
        SourceCallOrigin,
        StopConvention,
        Unit,
        UnknownOriginFact,
        WindowDeclaration,
        WindowGranularity,
        WindowRenderingVocabulary,
        ZoneValue,
    )
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.source_annotations import (
        AnnotationBundle,
        AnnotationField,
        AnnotationSchema,
        AnnotationScope,
        ObservationAnnotationTable,
    )
    from rivretrieve._internal.source_series import (
        ParsedSeries,
        PhysicalFacts,
        RetrievalOutcome,
        SeriesWindow,
        SourceIdentity,
        SourceSeries,
        known,
    )

    product = ProductId("discharge_daily_mean")
    config = ProviderConfig(
        zone=ZoneValue("+00:00"),
        products={product: ProductConfig(SourceCoordinates({"p": "q"}), unit=Unit.M3_S, semantics=Instant())},
    )
    decls = ProductWindowDeclarations(
        {
            product: WindowDeclaration(
                WindowGranularity("date"), WindowRenderingVocabulary.DATE, StopConvention.INCLUSIVE
            )
        }
    )
    fact_nat = PhysicalFacts(
        facts_id="fact-native",
        quantity=known("discharge", "test"),
        source_unit=known("m3/s", "test"),
        normalized_unit="m3/s",
    )
    fact_utc = PhysicalFacts(
        facts_id="fact-utc",
        quantity=known("discharge", "test"),
        source_unit=known("ft3/s", "test"),
        normalized_unit="ft3/s",
    )
    series_def = SourceSeries(
        series_id="s-multi-axis",
        provider_id="throwaway",
        station_id="st-1",
        product_id=str(product),
        identity=SourceIdentity(namespace="test", published_id="s-multi-axis", origin="response", evidence=("test",)),
        facts=(fact_nat, fact_utc),
    )
    empty_series = SourceSeries(
        series_id="s-empty",
        provider_id="throwaway",
        station_id="st-1",
        product_id=str(product),
        identity=SourceIdentity(namespace="test", published_id="s-empty", origin="response", evidence=("test",)),
        facts=(fact_nat,),
    )
    ann_schema = AnnotationSchema(
        schema_id="throwaway.qc",
        provider_id="throwaway",
        scope=AnnotationScope.OBSERVATION,
        fields=(AnnotationField(name="flag", dtype="String", description="Flag"),),
    )
    win = RequestedWindow(
        WindowEndpoint.from_datetime(datetime(2023, 6, 1)),
        WindowEndpoint.from_datetime(datetime(2023, 6, 2, 23, 59, 59, 999999)),
    )
    req = ObservationRequest(ProviderId("throwaway"), ("st-1",), (product,), win)
    fw = _make_fetch_window(win.start, win.end)

    def _mk_payload(acq_id: str) -> Payload:
        return Payload(
            source_coordinates=SourceCoordinates({"p": "q"}),
            station_products=(("st-1", product),),
            fetch_window=fw,
            content=b"{}",
            origin=SourceCallOrigin(
                "https://example.invalid/obs",
                {"id": acq_id},
                200,
                datetime(2023, 6, 3, tzinfo=UTC),
                "application/json",
                UnknownOriginFact(),
                UnknownOriginFact(),
            ),
            prerequisite_calls=(),
            acquisition_id=acq_id,
        )

    def _mk_parsed(mode: str):
        rows = pl.DataFrame(
            {
                "station_id": ["st-1", "st-1"],
                "product_id": [str(product), str(product)],
                "time": [datetime(2023, 6, 1, 12, 0), datetime(2023, 6, 2, 12, 0)],
                "value": [10.0, 20.0],
                "time_zone": ["+00:00", "+00:00"],
                "series_id": ["s-multi-axis", "s-multi-axis"],
                "facts_id": ["fact-native", "fact-utc"],
                "source_unit": ["m3/s", "ft3/s"],
            },
            schema=drv_mod.RowsSchema.polars_schema,
        )
        ann = AnnotationBundle(
            observation_tables={
                "throwaway.qc": ObservationAnnotationTable.from_rows(
                    schema=ann_schema,
                    rows=pl.DataFrame(
                        {
                            "series_id": ["s-multi-axis", "s-multi-axis"],
                            "facts_id": ["fact-native", "fact-utc"],
                            "station_id": ["st-1", "st-1"],
                            "product_id": [str(product), str(product)],
                            "time": [datetime(2023, 6, 1, 12, 0), datetime(2023, 6, 2, 12, 0)],
                            "time_zone": ["+00:00", "+00:00"],
                            "measured": [True, True],
                            "flag": ["nat-ok", "utc-ok"],
                        },
                        schema={
                            "series_id": pl.String,
                            "facts_id": pl.String,
                            "station_id": pl.String,
                            "product_id": pl.String,
                            "time": pl.Datetime("us"),
                            "time_zone": pl.String,
                            "measured": pl.Boolean,
                            **ann_schema.polars_schema(),
                        },
                    ),
                    measurement_indices=(0, 1),
                )
            }
        )
        if mode == "independent_axes":
            sw_nat = SeriesWindow(
                start=datetime(2023, 6, 1), end=datetime(2023, 6, 2, 23, 59, 59, 999999), axis=TimeAxis.NATIVE
            )
            sw_utc = SeriesWindow(
                start=datetime(2023, 6, 1, tzinfo=None), end=datetime(2023, 6, 2, 23, 59, 59, 999999), axis=TimeAxis.UTC
            )
            outs = (
                RetrievalOutcome(
                    outcome_id="o-nat",
                    series_id="s-multi-axis",
                    station_id="st-1",
                    product_id=str(product),
                    window=sw_nat,
                    status=OutcomeStatus.SUCCESS,
                    facts_ids=("fact-native",),
                    coverage="observations",
                ),
                RetrievalOutcome(
                    outcome_id="o-utc",
                    series_id="s-multi-axis",
                    station_id="st-1",
                    product_id=str(product),
                    window=sw_utc,
                    status=OutcomeStatus.SUCCESS,
                    facts_ids=("fact-utc",),
                    coverage="observations",
                ),
                RetrievalOutcome(
                    outcome_id="o-empty",
                    series_id="s-empty",
                    station_id="st-1",
                    product_id=str(product),
                    window=sw_nat,
                    status=OutcomeStatus.SUCCESS,
                    facts_ids=("fact-native",),
                    coverage="interval",
                ),
            )
            return ParsedSeries(
                rows=rows,
                series=(series_def, empty_series),
                inventories=(),
                annotations=ann,
                outcomes=outs,
            )
        if mode == "mixed_same_fact":
            return "split"
        return "overlap"

    # 1. Verify bypass skips _authorize_fact_retirement and per-outcome annotation-copying slice, yet matches refresh!
    filter_expr_calls = 0
    orig_filter_expr = drv_mod.filter_native_with_annotations_by_expr

    def spy_filter_expr(rows, bundle, predicate, *, allowed_series_ids=None):
        nonlocal filter_expr_calls
        filter_expr_calls += 1
        return orig_filter_expr(rows, bundle, predicate, allowed_series_ids=allowed_series_ids)

    def _forbid_retirement(*a, **kw):
        raise AssertionError("_authorize_fact_retirement ran in bypass mode")

    def _run_case(cache_mode, parse_fn, payload_ids=("p1",)):
        prov = SimpleNamespace(
            config=config,
            window_declarations=decls,
            fetch=lambda *a, **k: WithIssues(tuple(_mk_payload(pid) for pid in payload_ids)),
            parse=parse_fn,
        )
        return drive(
            req,
            prov,
            provenance=ObservationProvenance(source="test", provider_id=ProviderId("throwaway")),
            cache=cache_mode,
            store=StoreRoot(tmp_path / f"store_{cache_mode}_{'_'.join(payload_ids)}")
            if cache_mode != "bypass"
            else None,
            receipts=ReceiptMode.OMIT,
        )

    parsed_independent = _mk_parsed("independent_axes")
    with monkeypatch.context() as mp:
        mp.setattr(drv_mod, "_authorize_fact_retirement", _forbid_retirement)
        mp.setattr(drv_mod, "filter_native_with_annotations_by_expr", spy_filter_expr)
        bypass_res = _run_case("bypass", lambda p, c: parsed_independent)
    bypass_filter_calls = filter_expr_calls
    filter_expr_calls = 0
    with monkeypatch.context() as mp:
        mp.setattr(drv_mod, "filter_native_with_annotations_by_expr", spy_filter_expr)
        refresh_res = _run_case("refresh", lambda p, c: parsed_independent)
    refresh_filter_calls = filter_expr_calls
    assert bypass_filter_calls <= 3
    assert bypass_filter_calls < refresh_filter_calls
    assert_frame_equal(bypass_res.canonical_rows, refresh_res.canonical_rows)
    assert_frame_equal(
        bypass_res.annotations.observation_tables["throwaway.qc"].rows,
        refresh_res.annotations.observation_tables["throwaway.qc"].rows,
    )
    assert (
        bypass_res.annotations.observation_tables["throwaway.qc"].measurement_indices
        == refresh_res.annotations.observation_tables["throwaway.qc"].measurement_indices
    )
    assert bypass_res.outcomes == refresh_res.outcomes
    assert any(o.series_id == "s-empty" and o.status is OutcomeStatus.EMPTY for o in bypass_res.outcomes)
    obs_o = next(o for o in bypass_res.outcomes if o.facts_ids == ("fact-native",) and o.coverage == "observations")
    assert len(obs_o.observation_keys) == 1

    # 2. Same (series_id, facts_id) mixing NATIVE & UTC fails in both bypass and refresh
    def _mix_axis_parse(payload, cfg):
        axis = TimeAxis.UTC if payload.acquisition_id == "utc" else TimeAxis.NATIVE
        sw = SeriesWindow(start=datetime(2023, 6, 1), end=datetime(2023, 6, 2, 23, 59, 59, 999999), axis=axis)
        return ParsedSeries(
            rows=parsed_independent.rows.head(1),
            series=(series_def,),
            inventories=(),
            outcomes=(
                RetrievalOutcome(
                    outcome_id=f"o-{payload.acquisition_id}",
                    series_id="s-multi-axis",
                    station_id="st-1",
                    product_id=str(product),
                    window=sw,
                    status=OutcomeStatus.SUCCESS,
                    facts_ids=("fact-native",),
                ),
            ),
        )

    with pytest.raises(FatalContractError, match="cannot mix acquisition time axes"):
        _run_case("bypass", _mix_axis_parse, ("nat", "utc"))
    with pytest.raises(FatalContractError, match="cannot mix acquisition time axes"):
        _run_case("refresh", _mix_axis_parse, ("nat", "utc"))

    # 3. Overlapping independent snapshot observation keys fails in both bypass and refresh
    def _overlap_snap_parse(payload, cfg):
        sw = SeriesWindow(
            start=datetime(2023, 6, 1), end=datetime(2023, 6, 2, 23, 59, 59, 999999), axis=TimeAxis.NATIVE
        )
        return ParsedSeries(
            rows=parsed_independent.rows.head(1),
            series=(series_def,),
            inventories=(),
            outcomes=(
                RetrievalOutcome(
                    outcome_id=f"snap-{payload.acquisition_id}",
                    series_id="s-multi-axis",
                    station_id="st-1",
                    product_id=str(product),
                    window=sw,
                    status=OutcomeStatus.SUCCESS,
                    facts_ids=("fact-native",),
                    coverage="observations",
                ),
            ),
        )

    with pytest.raises(FatalContractError, match="Independent snapshot acquisitions overlap observation keys"):
        _run_case("bypass", _overlap_snap_parse, ("s1", "s2"))
    with pytest.raises(FatalContractError, match="Independent snapshot acquisitions overlap observation keys"):
        _run_case("refresh", _overlap_snap_parse, ("s1", "s2"))


def test_late_page_refresh_failure_retains_held_data_and_independent_fact_outcomes(tmp_path):
    from rivretrieve._internal.driver import RowsSchema
    from rivretrieve._internal.engine import (
        Instant,
        Payload,
        ProductConfig,
        ProductWindowDeclarations,
        ProviderConfig,
        SourceCallOrigin,
        StopConvention,
        Unit,
        UnknownOriginFact,
        WindowDeclaration,
        WindowGranularity,
        WindowRenderingVocabulary,
        ZoneValue,
    )
    from rivretrieve._internal.source_series import (
        ParsedSeries,
        PhysicalFacts,
        RetrievalOutcome,
        SeriesWindow,
        SourceIdentity,
        SourceSeries,
        known,
    )

    product = ProductId("discharge_daily_mean")
    config = ProviderConfig(
        zone=ZoneValue("+00:00"),
        products={product: ProductConfig(SourceCoordinates({"p": "q"}), unit=Unit.M3_S, semantics=Instant())},
    )
    decls = ProductWindowDeclarations(
        {
            product: WindowDeclaration(
                WindowGranularity("date"), WindowRenderingVocabulary.DATE, StopConvention.INCLUSIVE
            )
        }
    )
    fact_a = PhysicalFacts(
        facts_id="fact-a", quantity=known("discharge", "t"), source_unit=known("m3/s", "t"), normalized_unit="m3/s"
    )
    fact_b = PhysicalFacts(
        facts_id="fact-b", quantity=known("discharge", "t"), source_unit=known("m3/s", "t"), normalized_unit="m3/s"
    )
    s_def = SourceSeries(
        series_id="s-two-facts",
        provider_id="throwaway",
        station_id="st-1",
        product_id=str(product),
        identity=SourceIdentity(namespace="t", published_id="s-two-facts", origin="response", evidence=("t",)),
        facts=(fact_a, fact_b),
    )
    win = RequestedWindow(
        WindowEndpoint.from_datetime(datetime(2023, 6, 1)),
        WindowEndpoint.from_datetime(datetime(2023, 6, 2, 23, 59, 59, 999999)),
    )
    sw = SeriesWindow(start=datetime(2023, 6, 1), end=datetime(2023, 6, 2, 23, 59, 59, 999999))
    req = ObservationRequest(ProviderId("throwaway"), ("st-1",), (product,), win)
    fw = _make_fetch_window(win.start, win.end)
    store = StoreRoot(tmp_path / "store")
    t_held = datetime(2023, 6, 3, 10, 0, tzinfo=UTC)
    t_fresh = datetime(2023, 6, 4, 12, 0, tzinfo=UTC)

    def _payload(acq_id: str, retrieved: datetime) -> Payload:
        return Payload(
            source_coordinates=SourceCoordinates({"p": "q"}),
            station_products=(("st-1", product),),
            fetch_window=fw,
            content=b"{}",
            origin=SourceCallOrigin(
                "https://example.invalid/obs",
                {"id": acq_id},
                200,
                retrieved,
                "application/json",
                UnknownOriginFact(),
                UnknownOriginFact(),
            ),
            prerequisite_calls=(),
            acquisition_id=acq_id,
        )

    def _run_refresh(payloads, parse_fn):
        prov = SimpleNamespace(
            config=config,
            window_declarations=decls,
            fetch=lambda *a, **k: WithIssues(payloads),
            parse=parse_fn,
        )
        return drive(
            req,
            prov,
            provenance=ObservationProvenance(source="t", provider_id=ProviderId("throwaway")),
            cache="refresh",
            store=store,
            receipts=ReceiptMode.OMIT,
        )

    def _parse_held(p, c):
        rows = pl.DataFrame(
            {
                "station_id": ["st-1", "st-1"],
                "product_id": [str(product), str(product)],
                "time": [datetime(2023, 6, 1, 12, 0), datetime(2023, 6, 2, 12, 0)],
                "value": [1.0, 2.0],
                "time_zone": ["+00:00", "+00:00"],
                "series_id": ["s-two-facts", "s-two-facts"],
                "facts_id": ["fact-a", "fact-b"],
                "source_unit": ["m3/s", "m3/s"],
            },
            schema=RowsSchema.polars_schema,
        )
        return ParsedSeries(
            rows=rows,
            series=(s_def,),
            inventories=(),
            outcomes=(
                RetrievalOutcome(
                    outcome_id="held-a",
                    series_id="s-two-facts",
                    station_id="st-1",
                    product_id=str(product),
                    window=sw,
                    status=OutcomeStatus.SUCCESS,
                    facts_ids=("fact-a",),
                    retrieved_at=t_held,
                ),
                RetrievalOutcome(
                    outcome_id="held-b",
                    series_id="s-two-facts",
                    station_id="st-1",
                    product_id=str(product),
                    window=sw,
                    status=OutcomeStatus.SUCCESS,
                    facts_ids=("fact-b",),
                    retrieved_at=t_held,
                ),
            ),
        )

    _run_refresh((_payload("init", t_held),), _parse_held)

    def _parse_late_partial_failure(p, c):
        if p.acquisition_id == "page1-b":
            rows = pl.DataFrame(
                {
                    "station_id": ["st-1"],
                    "product_id": [str(product)],
                    "time": [datetime(2023, 6, 2, 12, 0)],
                    "value": [22.0],
                    "time_zone": ["+00:00"],
                    "series_id": ["s-two-facts"],
                    "facts_id": ["fact-b"],
                    "source_unit": ["m3/s"],
                },
                schema=RowsSchema.polars_schema,
            )
            return ParsedSeries(
                rows=rows,
                series=(s_def,),
                inventories=(),
                outcomes=(
                    RetrievalOutcome(
                        outcome_id="fresh-b",
                        series_id="s-two-facts",
                        station_id="st-1",
                        product_id=str(product),
                        window=sw,
                        status=OutcomeStatus.SUCCESS,
                        facts_ids=("fact-b",),
                        retrieved_at=t_fresh,
                    ),
                ),
            )
        return ParsedSeries(
            rows=pl.DataFrame(schema=RowsSchema.polars_schema),
            series=(s_def,),
            inventories=(),
            outcomes=(
                RetrievalOutcome(
                    outcome_id="fail-a",
                    series_id="s-two-facts",
                    station_id="st-1",
                    product_id=str(product),
                    window=sw,
                    status=OutcomeStatus.FAILED,
                    facts_ids=("fact-a",),
                    reason="late page failed",
                ),
            ),
        )

    refreshed = _run_refresh(
        (_payload("page1-b", t_fresh), _payload("page2-fail-a", t_fresh)), _parse_late_partial_failure
    )
    df = refreshed.canonical_rows.sort("facts_id")
    assert df["facts_id"].to_list() == ["fact-a", "fact-b"]
    assert df["value"].to_list() == [1.0, 22.0]
    # note: fact-a has both the retained held SUCCESS (with original t_held) and the FAILED diagnostic outcome
    held_a = [o for o in refreshed.outcomes if o.facts_ids == ("fact-a",) and o.status is OutcomeStatus.SUCCESS]
    failed_a = [o for o in refreshed.outcomes if o.facts_ids == ("fact-a",) and o.status is OutcomeStatus.FAILED]
    fresh_b = [o for o in refreshed.outcomes if o.facts_ids == ("fact-b",) and o.status is OutcomeStatus.SUCCESS]
    assert len(held_a) == 1 and held_a[0].retrieved_at == t_held
    assert len(failed_a) == 1
    assert len(fresh_b) == 1 and fresh_b[0].retrieved_at == t_fresh


def test_failed_acquisition_chains_and_partial_missing_prerequisites():
    from rivretrieve._internal.driver import _calls_with_failed_acquisitions
    from rivretrieve._internal.issues import FatalContractError

    parent = {"call_id": "overflow-parent", "acquisition_id": "overflow-parent"}
    failed_child = {
        "call_id": "failed-child",
        "acquisition_id": "failed-child",
        "prerequisite_acquisition_ids": ("overflow-parent",),
    }
    failed_grandchild = {
        "call_id": "failed-grandchild",
        "acquisition_id": "failed-grandchild",
        "prerequisite_acquisition_ids": ("failed-child",),
    }
    assert _calls_with_failed_acquisitions((parent,), (failed_grandchild, failed_child)) == (
        parent,
        failed_child,
        failed_grandchild,
    )

    partial = {
        "call_id": "partial-missing",
        "acquisition_id": "partial-missing",
        "prerequisite_acquisition_ids": ("overflow-parent", "missing"),
    }
    with pytest.raises(FatalContractError, match="Failed acquisition lacks its prerequisite call evidence"):
        _calls_with_failed_acquisitions((parent,), (partial,))


def test_order_support_calls_handles_leading_deferred_and_missing_prerequisites():
    from rivretrieve._internal.driver import _order_support_calls
    from rivretrieve._internal.issues import FatalContractError

    leading = {"call_id": "overflow-parent", "acquisition_id": "overflow-parent"}
    payload = {
        "call_id": "payload-1",
        "acquisition_id": "payload-1",
        "prerequisite_acquisition_ids": ("overflow-parent",),
    }
    post_payload = {
        "call_id": "aux-after",
        "acquisition_id": "aux-after",
        "prerequisite_acquisition_ids": ("payload-1",),
    }
    chained = {"call_id": "aux-chain", "acquisition_id": "aux-chain", "prerequisite_acquisition_ids": ("aux-after",)}
    assert _order_support_calls((chained, leading, post_payload), (payload,)) == (
        leading,
        payload,
        post_payload,
        chained,
    )

    dangling = {"call_id": "aux-missing", "acquisition_id": "aux-missing", "prerequisite_acquisition_ids": ("missing",)}
    with pytest.raises(FatalContractError, match="Auxiliary acquisition lacks its prerequisite call evidence"):
        _order_support_calls((dangling,), (payload,))
