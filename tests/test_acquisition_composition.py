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
