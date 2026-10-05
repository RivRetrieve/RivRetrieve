"""Current acquisition support and scoped diagnostic supersession.

Records remain only while they support interval coverage, retained snapshot keys,
latest applicable inventory knowledge, or an unresolved diagnosis. This is not an
acquisition-history archive. Unknown diagnostic scope is retained conservatively.
"""

from __future__ import annotations

from dataclasses import dataclass

from rivretrieve._internal.coverage import CoverageInterval, RequestedInterval, remainder
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    RestrictionKind,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    stable_id,
)
from rivretrieve._internal.time_axis import timestamp_on_axis

_SUCCESS = (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY)


@dataclass(frozen=True, slots=True)
class CurrentEvidence:
    """Evidence needed to explain retained rows, reuse and active diagnoses."""

    outcomes: tuple[RetrievalOutcome, ...]
    inventories: tuple[InventorySnapshot, ...]
    issues: tuple[Issue, ...]
    source_calls: tuple[dict[str, object], ...]
    supporting_outcomes: tuple[RetrievalOutcome, ...] = ()


def _same_scope(first: RetrievalOutcome, second: RetrievalOutcome) -> bool:
    return (
        first.station_id == second.station_id
        and first.product_id == second.product_id
        and first.series_id == second.series_id
        and first.requested_selector == second.requested_selector
        and first.window.axis == second.window.axis
    )


def _interval(item: RetrievalOutcome) -> RequestedInterval:
    return RequestedInterval(item.window.start, item.window.end, axis=item.window.axis)


def _snapshot_keys(item: RetrievalOutcome, later: list[RetrievalOutcome]) -> tuple:
    keys = set(item.observation_keys)
    for new in later:
        if new.series_id != item.series_id or new.status not in _SUCCESS:
            continue
        if new.coverage == "observations":
            keys.difference_update(new.observation_keys)
        else:
            keys = {
                key
                for key in keys
                if key[0] not in new.facts_ids
                or (stamp := timestamp_on_axis(key[1], key[2], new.window.axis)) is None
                or not new.window.start <= stamp <= new.window.end
            }
    return tuple(key for key in item.observation_keys if key in keys)


def _inventory_recovery(
    item: RetrievalOutcome,
    later: list[RetrievalOutcome],
    inventories: tuple[InventorySnapshot, ...],
    diagnostic_scope: SeriesScope | None,
) -> tuple[RequestedInterval, ...]:
    """Require acquired complete membership before recovering an unknown scope."""
    recovered = []
    later_ids = {"retrieval-outcome:" + new.outcome_id for new in later}
    for inventory in inventories:
        scope = inventory.scope
        if (
            inventory.origin == "catalogue"
            or inventory.completeness is not InventoryCompleteness.COMPLETE
            or inventory.window is None
            or inventory.window.axis != item.window.axis
            or (scope.predicates and (diagnostic_scope is None or scope.predicates != diagnostic_scope.predicates))
            or scope.station_ids != (item.station_id,)
            or scope.product_ids != (item.product_id,)
        ):
            continue
        if diagnostic_scope is not None:
            if scope != diagnostic_scope:
                continue
        elif scope.restriction is not RestrictionKind.ALL:
            selector = item.requested_selector
            if selector is None or (
                (scope.series_ids != (selector.value,) or scope.variants)
                if selector.kind == "series_id"
                else (scope.variants != (selector.value,) or scope.series_ids)
            ):
                continue
        if (
            not later_ids.intersection(inventory.evidence)
            and not (
                inventory.acquired_at is not None
                and item.retrieved_at is not None
                and inventory.acquired_at > item.retrieved_at
            )
            and not any(
                inventory.acquired_at is not None and new.retrieved_at == inventory.acquired_at
                for new in later
                if new.status in _SUCCESS
            )
        ):
            continue
        members = inventory.members
        if item.series_id is not None:
            if item.series_id not in members:
                continue
            members = (item.series_id,)
        facts_by_member = dict(inventory.member_facts)
        interval = RequestedInterval(inventory.window.start, inventory.window.end, axis=inventory.window.axis)
        if all(
            member in facts_by_member
            and all(
                not remainder(
                    interval,
                    tuple(
                        _interval(new)
                        for new in later
                        if new.series_id == member
                        and fact in new.facts_ids
                        and new.status in _SUCCESS
                        and new.coverage == "interval"
                        and new.window.axis == interval.axis
                    ),
                )
                for fact in facts_by_member[member]
            )
            for member in members
        ):
            recovered.append(interval)
    return tuple(recovered)


def _recovered_inventory_intervals(
    item: RetrievalOutcome,
    inventories: tuple[InventorySnapshot, ...],
    new_inventory_ids: frozenset[str],
    issues: tuple[Issue, ...],
    new_outcome_ids: frozenset[str],
) -> tuple[RequestedInterval, ...]:
    if item.status is not OutcomeStatus.UNRESOLVED or not item.calls or item.outcome_id in new_outcome_ids:
        return ()
    codes = {
        issue.code
        for issue in issues
        for details in (issue.details or {},)
        if (
            details.get("outcome_id") == item.outcome_id
            if details.get("outcome_id") is not None
            else issue.message == item.reason
            and all(
                details.get(key) is None or details[key] == getattr(item, key)
                for key in ("station_id", "product_id", "series_id")
            )
        )
    }
    if "source.inventory_unresolved" not in codes or "source.request_failed" in codes:
        return ()
    failed_inventories = tuple(
        inventory
        for inventory in inventories
        if inventory.reason == item.reason
        and inventory.origin == "response"
        and inventory.completeness is not InventoryCompleteness.COMPLETE
        and set(item.calls).intersection(
            reference.removeprefix("source-call:")
            for reference in inventory.evidence
            if reference.startswith("source-call:")
        )
    )
    return tuple(
        RequestedInterval(new.window.start, new.window.end, axis=new.window.axis)
        for new in inventories
        if new.snapshot_id in new_inventory_ids
        and new.completeness is InventoryCompleteness.COMPLETE
        and new.window is not None
        and new.window.axis == item.window.axis
        and any(
            new.scope == old.scope and new.access == old.access and new.origin == old.origin
            for old in failed_inventories
        )
    )


def _diagnosis_parts(
    item: RetrievalOutcome,
    later: list[RetrievalOutcome],
    inventories: tuple[InventorySnapshot, ...],
    diagnostic_scope: SeriesScope | None,
    new_outcome_ids: frozenset[str],
    recovered_inventory: tuple[RequestedInterval, ...],
) -> tuple[RetrievalOutcome, ...]:
    pieces = []
    # Facts are independent replacement scopes. Unspecified facts cannot be
    # inferred from whichever successful series happens to be present.
    for fact in item.facts_ids or (None,):
        superseding = tuple(
            _interval(new)
            for new in later
            if _same_scope(item, new)
            and (
                new.status in _SUCCESS
                or (
                    new.status is item.status
                    and item.outcome_id not in new_outcome_ids
                    and new.outcome_id in new_outcome_ids
                )
            )
            and new.coverage == "interval"
            and (fact in new.facts_ids if fact is not None else not new.facts_ids)
        )
        superseding += recovered_inventory
        if item.series_id is None or fact is None:
            superseding += _inventory_recovery(item, later, inventories, diagnostic_scope)
        for interval in remainder(_interval(item), superseding):
            facts = (fact,) if fact is not None else ()
            if interval == _interval(item) and facts == item.facts_ids:
                pieces.append(item)
            else:
                window = SeriesWindow(start=interval.start, end=interval.end, axis=interval.axis)
                pieces.append(
                    item.model_copy(
                        update={
                            "outcome_id": stable_id(item.outcome_id, window.model_dump_json(), str(facts)),
                            "window": window,
                            "facts_ids": facts,
                        }
                    )
                )
    if (
        pieces
        and all(part.window == item.window for part in pieces)
        and {fact for part in pieces for fact in part.facts_ids} == set(item.facts_ids)
    ):
        return (item,)
    return tuple(pieces)


def compact_inventories(inventories: tuple[InventorySnapshot, ...]) -> tuple[InventorySnapshot, ...]:
    """Retain latest applicable scopes and transitive inventory dependencies."""
    retained: list[InventorySnapshot] = []
    by_scope: dict[tuple[str, str, str], list[InventorySnapshot]] = {}
    for item in reversed(inventories):
        scoped = by_scope.setdefault((item.scope.model_dump_json(), item.access, item.origin), [])
        if any(
            (
                new.window is None
                or item.window is not None
                and new.window.axis == item.window.axis
                and new.window.start <= item.window.start
                and new.window.end >= item.window.end
            )
            for new in scoped
        ):
            continue
        retained.append(item)
        scoped.append(item)
    by_id = {item.snapshot_id: item for item in inventories}
    needed = {item.snapshot_id for item in retained}
    pending = list(retained)
    while pending:
        for reference in pending.pop().evidence:
            if reference.startswith("source-inventory:"):
                key = reference.removeprefix("source-inventory:")
                if key in by_id and key not in needed:
                    needed.add(key)
                    pending.append(by_id[key])
    return tuple(item for item in inventories if item.snapshot_id in needed)


def compact_evidence(
    coverage: tuple[CoverageInterval, ...],
    outcomes: tuple[RetrievalOutcome, ...],
    inventories: tuple[InventorySnapshot, ...],
    issues: tuple[Issue, ...],
    source_calls: tuple[dict[str, object], ...],
    *,
    supporting_outcomes: tuple[RetrievalOutcome, ...] = (),
    new_outcome_ids: frozenset[str] = frozenset(),
    new_inventory_ids: frozenset[str] = frozenset(),
) -> CurrentEvidence:
    """Keep current support and subtract only later established matching scopes.

    Outcomes are in acquisition arrival order. The new-ID sets identify this
    update; sibling failures in that update do not replace each other. A failed
    refresh never supersedes successful row support. Earlier failures retain
    exact uncovered intervals and facts with their original reason and calls.
    Supporting outcomes resolve inventory links only and never become active
    diagnostics merely because their acquisition remains relevant.
    """
    if any(
        not any(isinstance(call.get(key), str) and call[key] for key in ("call_id", "acquisition_id"))
        for call in source_calls
    ):
        raise FatalContractError("Persisted source calls require explicit call or acquisition identity")
    acquisitions_by_id: dict[str, RetrievalOutcome] = {}
    for item in (*supporting_outcomes, *outcomes):
        prior = acquisitions_by_id.setdefault(item.outcome_id, item)
        if prior != item:
            raise FatalContractError("Conflicting current and inventory-support acquisition identities")
    inventory_recoveries = {
        item.outcome_id: _recovered_inventory_intervals(item, inventories, new_inventory_ids, issues, new_outcome_ids)
        for item in outcomes
    }
    inventories = compact_inventories(inventories)
    supported = {item.outcome_id for item in coverage}
    coverage_by_outcome: dict[str, list[CoverageInterval]] = {}
    for interval in coverage:
        coverage_by_outcome.setdefault(interval.outcome_id, []).append(interval)
    inventory_support = {
        reference.removeprefix("retrieval-outcome:")
        for item in inventories
        for reference in item.evidence
        if reference.startswith("retrieval-outcome:")
    }
    diagnostic_scopes: dict[str, SeriesScope] = {}
    for issue in issues:
        details = issue.details or {}
        if details.get("inventory_scope") is None:
            continue
        try:
            scope = SeriesScope.model_validate(details["inventory_scope"])
        except ValueError as error:
            raise FatalContractError("Stored diagnostic inventory scope is malformed") from error
        for item in outcomes:
            explicit = details.get("outcome_id")
            if (
                item.outcome_id == explicit
                if explicit is not None
                else item.reason == issue.message
                and all(
                    details.get(key) is None or details[key] == getattr(item, key)
                    for key in ("station_id", "product_id", "series_id")
                )
            ):
                prior = diagnostic_scopes.setdefault(item.outcome_id, scope)
                if prior != scope:
                    raise FatalContractError("One diagnostic outcome has conflicting acquisition scopes")
    later_by_route: dict[tuple[str, str], list[RetrievalOutcome]] = {}
    retained: list[RetrievalOutcome] = []
    fragments: dict[str, tuple[RetrievalOutcome, ...]] = {}
    for item in reversed(outcomes):
        later = later_by_route.setdefault((item.station_id, item.product_id), [])
        if item.status in _SUCCESS:
            if item.coverage == "observations":
                keys = _snapshot_keys(item, later)
                parts = (
                    (
                        item.model_copy(
                            update={
                                "observation_keys": keys,
                                "outcome_id": item.outcome_id
                                if keys == item.observation_keys
                                else stable_id(item.outcome_id, "retained-observation-keys", repr(keys)),
                            }
                        ),
                    )
                    if keys
                    else ()
                )
            else:
                parts = (item,) if item.outcome_id in supported else ()
        else:
            parts = _diagnosis_parts(
                item,
                later,
                inventories,
                diagnostic_scopes.get(item.outcome_id),
                new_outcome_ids,
                inventory_recoveries[item.outcome_id],
            )
        fragments[item.outcome_id] = parts
        retained.extend(reversed(parts))
        if item.status not in _SUCCESS:
            later.append(item)
        elif item.coverage == "observations":
            later.extend(parts)
        else:
            later.extend(
                item.model_copy(
                    update={
                        "window": SeriesWindow(
                            start=interval.interval.start, end=interval.interval.end, axis=interval.interval.axis
                        ),
                        "facts_ids": interval.facts_ids,
                    }
                )
                for interval in coverage_by_outcome.get(item.outcome_id, ())
            )
    current = tuple(reversed(retained))
    active_ids = {item.outcome_id for item in current}
    missing_support = inventory_support - acquisitions_by_id.keys()
    if missing_support:
        raise FatalContractError("Inventory references an unknown acquisition outcome")
    support = tuple(
        item
        for identity, item in acquisitions_by_id.items()
        if identity in inventory_support and identity not in active_ids
    )
    kept_issues: list[Issue] = []
    for issue in issues:
        details = issue.details or {}
        explicit = details.get("outcome_id")
        associated = tuple(
            item
            for item in outcomes
            if (
                item.outcome_id == explicit
                if explicit is not None
                else item.reason == issue.message
                and all(
                    details.get(key) is None or details[key] == getattr(item, key)
                    for key in ("station_id", "product_id", "series_id")
                )
            )
        )
        if not associated:
            # Inventory-support history is not an active diagnostic.
            if isinstance(explicit, str) and explicit in acquisitions_by_id:
                continue
            kept_issues.append(issue)
            continue
        for original in associated:
            for part in fragments[original.outcome_id]:
                if part == original:
                    kept_issues.append(issue)
                else:
                    kept_issues.append(
                        issue.model_copy(
                            update={
                                "details": {
                                    **details,
                                    "outcome_id": part.outcome_id,
                                    "original_outcome_id": details.get("original_outcome_id", original.outcome_id),
                                    "window": part.window.model_dump(mode="json"),
                                    **({"facts_ids": list(part.facts_ids)} if part.facts_ids else {}),
                                }
                            }
                        )
                    )
    active_references = {call for item in current for call in item.calls}
    references = active_references | {call for item in support for call in item.calls}
    references.update(reference.removeprefix("source-call:") for item in inventories for reference in item.evidence)
    # A referenced attempt also depends on its payload acquisition, including
    # credential prerequisites and earlier retry attempts from that acquisition.
    aliases: dict[str, set[str]] = {}
    for call in source_calls:
        identity, acquisition = call.get("call_id"), call.get("acquisition_id")
        if isinstance(identity, str) and isinstance(acquisition, str):
            aliases.setdefault(identity, set()).add(acquisition)
            aliases.setdefault(acquisition, set()).add(identity)
    for needed in (active_references, references):
        pending = list(needed)
        while pending:
            for identity in aliases.get(pending.pop(), ()):
                if identity not in needed:
                    needed.add(identity)
                    pending.append(identity)

    calls = tuple(
        call for call in source_calls if call.get("call_id") in references or call.get("acquisition_id") in references
    )
    unique_issues: dict[str, Issue] = {}
    for issue in kept_issues:
        details = issue.details or {}
        linked = details.get("acquisition_ids")
        if linked is not None:
            if (
                not isinstance(linked, (tuple, list))
                or not linked
                or any(not isinstance(identity, str) or not identity for identity in linked)
                or len(set(linked)) != len(linked)
            ):
                raise FatalContractError("Issue acquisition identities must be nonempty unique strings")
            surviving = tuple(identity for identity in linked if identity in active_references)
            if not surviving:
                continue
            issue = issue.model_copy(update={"details": {**details, "acquisition_ids": surviving}})
        unique_issues[issue.model_dump_json()] = issue
    return CurrentEvidence(current, inventories, tuple(unique_issues.values()), calls, support)
