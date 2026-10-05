"""Authored padding evidence stays structural, never active store authority."""

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import polars.testing as pl_testing
import pytest

from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import SourceAcquisition, SourceCoordinates, WithIssues
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.source_series import OutcomeStatus, SeriesWindow
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.store.accumulation import StoreUpdate, accumulate
from rivretrieve._internal.store.integrity import inspect_integrity
from tests.test_internal_driver import (
    _LEVEL_WINDOW_DECLARATIONS,
    _config,
    _parsed,
    _payload,
    _provenance,
    _request,
    _rows,
    _windows,
)


class _PaddingProvider:
    window_declarations = _LEVEL_WINDOW_DECLARATIONS

    def __init__(self, status=OutcomeStatus.EMPTY, *, mixed=False):
        self.coordinates = SourceCoordinates({"parameter": "height"})
        self.config = _config(self.coordinates)
        self.status = status
        self.mixed = mixed
        self.padding = True
        self.attempt = 0

    def fetch(self, *args, **kwargs):
        self.attempt += 1
        return WithIssues((_payload("station-1", self.coordinates, _windows()[1]),))

    def parse(self, payload, config):
        rows = _rows("station-1", 12, 10.0)
        parsed = _parsed(rows if self.mixed else rows.clear(), payload, config)
        base = parsed.outcomes[0]
        outcomes = []
        issues = ()
        if self.padding:
            padding = base.model_copy(
                update={
                    "outcome_id": f"padding-{self.attempt}",
                    "window": SeriesWindow(start=datetime(2026, 1, 1), end=datetime(2026, 1, 1, 23)),
                    "status": self.status,
                    "reason": "padding failed" if self.status is not OutcomeStatus.EMPTY else None,
                }
            )
            outcomes.append(padding)
            if self.status is not OutcomeStatus.EMPTY:
                issues = (
                    Issue(
                        provider_id=ProviderId("throwaway"),
                        severity="warning",
                        code="source.request_failed",
                        message="padding failed",
                        details={"outcome_id": padding.outcome_id},
                    ),
                )
        if self.mixed:
            outcomes.append(
                base.model_copy(
                    update={
                        "outcome_id": f"admitted-{self.attempt}",
                        "window": SeriesWindow(start=datetime(2026, 1, 2), end=datetime(2026, 1, 2, 23)),
                    }
                )
            )
        snapshot = parsed.inventories[0].model_copy(
            update={
                "snapshot_id": f"inventory-{self.attempt}",
                "evidence": tuple("retrieval-outcome:" + item.outcome_id for item in outcomes),
            }
        )
        return replace(parsed, outcomes=tuple(outcomes), inventories=(snapshot,), issues=issues)


def _drive(provider, store, mode="refresh"):
    request = _request(_windows()[0], ("station-1",))
    return drive(request, provider, provenance=_provenance(request), cache=mode, store=store)


@pytest.mark.parametrize("mixed", [False, True])
def test_padding_inventory_links_are_support_only(tmp_path: Path, mixed):
    status = OutcomeStatus.EMPTY
    provider = _PaddingProvider(status, mixed=mixed)
    store = StoreRoot(tmp_path / "store")
    bypass = _drive(provider, store, "bypass")
    refreshed = _drive(provider, store)
    pl_testing.assert_frame_equal(refreshed.canonical_rows, bypass.canonical_rows)
    sealed = inspect_integrity(store, ProviderId("throwaway"))
    manifest = sealed.store.manifest
    assert len(sealed.supporting_outcomes) == 1
    support = sealed.supporting_outcomes[0]
    assert support.status is status
    assert not any(item.message == "padding failed" for item in refreshed.issues)
    assert not any(item.message == "padding failed" for item in bypass.issues)
    assert support.window.start == datetime(2026, 1, 1)
    assert support.window.end == datetime(2026, 1, 1, 23)
    assert all(item.outcome_id != support.outcome_id for item in manifest.outcomes)
    assert all(item.outcome_id != support.outcome_id for item in refreshed.outcomes)
    assert all((item.details or {}).get("outcome_id") != support.outcome_id for item in manifest.issues)
    linked = {
        reference.removeprefix("retrieval-outcome:")
        for snapshot in manifest.inventories
        for reference in snapshot.evidence
        if reference.startswith("retrieval-outcome:")
    }
    assert linked == {support.outcome_id, *(item.outcome_id for item in manifest.outcomes)}
    assert len(manifest.coverage) == int(mixed)
    assert all(item.interval.start == datetime(2026, 1, 2) for item in manifest.coverage)
    if not mixed:
        assert not manifest.outcomes
        assert not manifest.partition_row_counts
        assert refreshed.canonical_rows.is_empty()
    for _ in range(3):
        _drive(provider, store)
        current = inspect_integrity(store, ProviderId("throwaway"))
        assert len(current.supporting_outcomes) == 1
        assert len(current.store.manifest.outcomes) == int(mixed)
        assert len(current.store.manifest.inventories) == len(manifest.inventories)
        assert len(current.store.manifest.source_calls) == len(manifest.source_calls)
    provider.padding = False
    provider.mixed = True
    _drive(provider, store)
    retired = inspect_integrity(store, ProviderId("throwaway"))
    assert not retired.supporting_outcomes
    assert support.outcome_id not in {item.outcome_id for item in retired.store.manifest.outcomes}


def test_malformed_padding_support_is_validated_before_retirement(tmp_path: Path):
    provider = _PaddingProvider()
    store = StoreRoot(tmp_path / "store")
    _drive(provider, store)
    sealed = inspect_integrity(store, ProviderId("throwaway"))
    bad = sealed.supporting_outcomes[0].model_copy(update={"outcome_id": "bad", "facts_ids": ("unknown",)})
    before = (Path(store) / "manifest.json").read_bytes()
    with pytest.raises(FatalContractError, match="outcome.facts"):
        accumulate(store, ProviderId("throwaway"), StoreUpdate((), (), (), (), supporting_outcomes=(bad,)))
    assert (Path(store) / "manifest.json").read_bytes() == before


def test_support_only_observation_keys_remain_immutable_without_rows(tmp_path: Path):
    provider = _PaddingProvider()
    store = StoreRoot(tmp_path / "store")
    _drive(provider, store)
    sealed = inspect_integrity(store, ProviderId("throwaway"))
    original = sealed.supporting_outcomes[0]
    support = original.model_copy(
        update={
            "outcome_id": "unadmitted-observations",
            "status": OutcomeStatus.SUCCESS,
            "coverage": "observations",
            "observation_keys": ((original.facts_ids[0], datetime(2026, 1, 1, 12), "+00:00"),),
        }
    )
    inventory = sealed.store.manifest.inventories[0].model_copy(
        update={
            "snapshot_id": "new-inventory",
            "evidence": ("retrieval-outcome:" + support.outcome_id,),
        }
    )
    accumulate(
        store,
        ProviderId("throwaway"),
        StoreUpdate(
            (),
            (inventory,),
            (),
            (),
            supporting_outcomes=(support,),
        ),
    )
    current = inspect_integrity(store, ProviderId("throwaway"))
    assert current.supporting_outcomes == (support,)
    assert not current.store.manifest.outcomes
    assert not current.store.manifest.coverage
    assert not current.store.manifest.partition_row_counts


@pytest.mark.parametrize("foreign", [False, True])
def test_support_only_or_unknown_outcome_cannot_authorize_active_issue(tmp_path: Path, foreign):
    provider = _PaddingProvider()
    store = StoreRoot(tmp_path / "store")
    _drive(provider, store)
    support = inspect_integrity(store, ProviderId("throwaway")).supporting_outcomes[0]
    issue = Issue(
        provider_id=ProviderId("throwaway"),
        severity="warning",
        code="source.request_failed",
        message="padding failed",
        details={"outcome_id": "foreign" if foreign else support.outcome_id},
    )
    before = (Path(store) / "manifest.json").read_bytes()
    with pytest.raises(FatalContractError, match="issue.outcome"):
        accumulate(store, ProviderId("throwaway"), StoreUpdate((), (), (), (), issues=(issue,)))
    assert (Path(store) / "manifest.json").read_bytes() == before


@pytest.mark.parametrize("mixed", [False, True])
@pytest.mark.parametrize("status", [OutcomeStatus.FAILED, OutcomeStatus.UNSUPPORTED, OutcomeStatus.UNRESOLVED])
def test_unusable_parsed_padding_keeps_public_issue_but_not_active_store_diagnostic(tmp_path: Path, mixed, status):
    provider = _PaddingProvider(status, mixed=mixed)
    store = StoreRoot(tmp_path / "store")
    for mode in ("bypass", "refresh"):
        result = _drive(provider, store, mode)
        assert not any(item.status is status for item in result.outcomes)
        assert any(issue.message == "padding failed" for issue in result.issues)
    sealed = inspect_integrity(store, ProviderId("throwaway"))
    assert len(sealed.supporting_outcomes) == 1
    support = sealed.supporting_outcomes[0]
    assert support.status is status
    assert support.reason == "padding failed"
    assert support.calls
    assert support.window.start == datetime(2026, 1, 1)
    assert support.window.end == datetime(2026, 1, 1, 23)
    assert not any(item.status is status for item in sealed.store.manifest.outcomes)
    assert not any(
        (issue.details or {}).get("outcome_id") == support.outcome_id for issue in sealed.store.manifest.issues
    )
    assert len(sealed.store.manifest.coverage) == int(mixed)
    assert all(item.interval.start == datetime(2026, 1, 2) for item in sealed.store.manifest.coverage)


@pytest.mark.parametrize("declared_empty", [False, True])
def test_failed_request_padding_preserves_existing_source_interval_diagnostic(tmp_path: Path, declared_empty):
    from rivretrieve._internal.source_acquisition import (
        FailedSourceRequest,
        SourceRequestTarget,
        SourceResponseMeaning,
    )
    from rivretrieve._internal.transport import TransportFailure, TransportFailureReason, TransportRequest

    class Provider(_PaddingProvider):
        def fetch(self, *args, **kwargs):
            payloads = super().fetch(*args, **kwargs)
            request = TransportRequest("GET", "https://example.test/padding")
            failure = TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=404)
            return SourceAcquisition(
                payloads.value,
                failed_requests=(
                    FailedSourceRequest(
                        "padding-request",
                        SourceRequestTarget("station-1", "level"),
                        SeriesWindow(start=datetime(2026, 1, 1), end=datetime(2026, 1, 1, 23)),
                        request,
                        failure,
                        SourceResponseMeaning.NO_OBSERVATIONS if declared_empty else SourceResponseMeaning.UNSPECIFIED,
                    ),
                ),
            )

    provider = Provider(mixed=True)
    provider.padding = False
    store = StoreRoot(tmp_path / "store")
    for mode in ("bypass", "refresh"):
        result = _drive(provider, store, mode)
        failed = [item for item in result.outcomes if item.status is OutcomeStatus.FAILED]
        linked = [issue for issue in result.issues if (issue.details or {}).get("outcome_id") == "padding-request"]
        if declared_empty:
            assert not failed
            assert not linked
        else:
            assert len(failed) == len(linked) == 1
            assert failed[0].outcome_id == "padding-request"
            assert failed[0].reason == linked[0].message
            assert failed[0].calls == ("padding-request",)
            assert failed[0].window.start == datetime(2026, 1, 1)
            assert failed[0].window.end == datetime(2026, 1, 1, 23)
    sealed = inspect_integrity(store, ProviderId("throwaway"))
    assert not sealed.supporting_outcomes
    assert len([item for item in sealed.store.manifest.outcomes if item.status is OutcomeStatus.FAILED]) == int(
        not declared_empty
    )
    assert all(item.interval.start == datetime(2026, 1, 2) for item in sealed.store.manifest.coverage)
