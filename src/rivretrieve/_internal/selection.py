"""Offline source-series discovery and immutable physical/identity selection."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

import polars as pl

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.evidence import CatalogueEvidence
from rivretrieve._internal.catalogues.schemas import STATION_CATALOG_SCHEMA, StationCatalog
from rivretrieve._internal.issues import FatalContractError, Issue, apply_on_issue
from rivretrieve._internal.primitives import OnIssue, ProviderId
from rivretrieve._internal.registry import UnknownProviderError
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    PhysicalPredicate,
    RestrictionKind,
    RetrievalOutcome,
    SeriesScope,
    SourceSeries,
    admission,
)


class _CatalogueRecord(Protocol):
    provider_id: ProviderId
    artifact: PackagedCatalogArtifact


class UnknownProductError(FatalContractError):
    def __init__(self, product_id: str) -> None:
        self.product_id = product_id
        super().__init__(f"Product route is not registered: {product_id!r}")


class UnknownStationError(FatalContractError):
    def __init__(self, station_id: str, provider_ids: tuple[str, ...]) -> None:
        self.station_id = station_id
        self.provider_ids = provider_ids
        super().__init__(f"Station is not registered for providers {provider_ids!r}: {station_id!r}")


@dataclass(frozen=True, slots=True)
class _EmptyReason:
    code: Literal["no_match", "unresolved_inventory", "not_in_selection"]
    provider_ids: tuple[str, ...]
    station_ids: tuple[str, ...]
    product_ids: tuple[str, ...]
    published_products: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StationLocation:
    provider_id: str
    station_id: str
    latitude: float
    longitude: float
    crs: str


@dataclass(frozen=True, slots=True)
class _Selection:
    """Requested scope and acquired evidence; known members never freeze all-matching intent."""

    scope: SeriesScope
    known_series: tuple[SourceSeries, ...] = ()
    inventories: tuple[InventorySnapshot, ...] = ()
    issues: tuple[Issue, ...] = ()
    locations: tuple[StationLocation, ...] = ()
    acquisition_provenance: tuple[CatalogueEvidence, ...] = ()
    empty_reason: _EmptyReason | None = None

    def __post_init__(self) -> None:
        keys = tuple(item.series_id for item in self.known_series)
        if len(keys) != len(set(keys)):
            raise FatalContractError("Selection contains duplicate source-series definitions")
        if any(not isinstance(item, SourceSeries) for item in self.known_series):
            raise TypeError("Selection requires validated source-series definitions")

    @property
    def series(self) -> tuple[SourceSeries, ...]:
        return tuple(
            item
            for item in self.known_series
            if self.scope.matches(item)
            and any(self.scope.matches_facts(facts) and admission(facts).status == "supported" for facts in item.facts)
        )


_PHYSICAL_FIELDS = (
    "quantity",
    "frequency",
    "statistic",
    "temporal_support",
    "day_definition",
    "timestamp_anchor",
    "time_zone",
    "vertical_reference",
    "vertical_datum",
)


def _normalize(value: str | Sequence[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    values = (value,) if isinstance(value, str) else tuple(value)
    if any(not isinstance(item, str) or not item for item in values):
        raise ValueError("Filters require nonempty string identifiers")
    return tuple(dict.fromkeys(values))


def _predicates(values: dict[str, str | None]) -> tuple[PhysicalPredicate, ...]:
    return tuple(
        PhysicalPredicate.model_validate({"field": field, "value": value})
        for field, value in values.items()
        if value is not None
    )


def _intersect_scope(scope: SeriesScope, requested: SeriesScope) -> SeriesScope:
    """Intersect constraints without turning an empty intersection into unrestricted intent."""
    from rivretrieve._internal.source_series import ScopeState

    empty = scope.state is ScopeState.EMPTY or requested.state is ScopeState.EMPTY
    coordinates: dict[str, tuple[str, ...]] = {}
    for name in ("provider_ids", "station_ids", "product_ids", "variants", "series_ids"):
        left, right = getattr(scope, name), getattr(requested, name)
        values = tuple(value for value in left if value in right) if left and right else left or right
        if left and right and not values:
            empty = True
        coordinates[name] = values
    predicates = tuple(dict.fromkeys((*scope.predicates, *requested.predicates)))
    for field in _PHYSICAL_FIELDS:
        if len({predicate.value for predicate in predicates if predicate.field == field}) > 1:
            empty = True
    return SeriesScope(
        **coordinates,
        predicates=predicates,
        restriction=RestrictionKind.EXPLICIT
        if RestrictionKind.EXPLICIT in (scope.restriction, requested.restriction)
        else RestrictionKind.ALL,
        state=ScopeState.EMPTY if empty else ScopeState.ACTIVE,
    )


def _selection_scope(
    *,
    provider=None,
    station=None,
    product=None,
    variant=None,
    series_id=None,
    **physical,
) -> SeriesScope:
    from rivretrieve._internal.source_series import ScopeState

    no_identity = (variant is not None and not _normalize(variant)) or (
        series_id is not None and not _normalize(series_id)
    )
    return SeriesScope(
        state=ScopeState.EMPTY if no_identity else ScopeState.ACTIVE,
        provider_ids=_normalize(provider),
        station_ids=_normalize(station),
        product_ids=_normalize(product),
        predicates=_predicates(physical),
        restriction=RestrictionKind.EXPLICIT if variant is not None or series_id is not None else RestrictionKind.ALL,
        variants=_normalize(variant),
        series_ids=_normalize(series_id),
    )


def _validate_vocabulary(records: Sequence[_CatalogueRecord], scope: SeriesScope) -> None:
    providers = {str(record.provider_id) for record in records}
    for provider in scope.provider_ids:
        if provider not in providers:
            raise UnknownProviderError(provider)
    relevant = tuple(record for record in records if not scope.provider_ids or record.provider_id in scope.provider_ids)
    products = {value for record in relevant for value in record.artifact.products["product_id"].to_list()}
    for product in scope.product_ids:
        if product not in products:
            raise UnknownProductError(product)
    stations = {value for record in relevant for value in record.artifact.stations["station_id"].to_list()}
    for station in scope.station_ids:
        if station not in stations:
            raise UnknownStationError(station, scope.provider_ids)


def _find(records: Sequence[_CatalogueRecord], *, on_issue: OnIssue = "warn", **filters) -> _Selection:
    from rivretrieve._internal.catalogues.source_series import catalogue_series

    scope = _selection_scope(**filters)
    _validate_vocabulary(records, scope)
    definitions: list[SourceSeries] = []
    inventories: list[InventorySnapshot] = []
    locations: list[StationLocation] = []
    evidence: list[CatalogueEvidence] = []
    for record in records:
        if scope.provider_ids and record.provider_id not in scope.provider_ids:
            continue
        inventory_scope = scope.model_copy(
            update={"predicates": (), "restriction": RestrictionKind.ALL, "variants": (), "series_ids": ()}
        )
        members, snapshots = catalogue_series(record.artifact, scope=inventory_scope)
        # Keep acquired evidence for the routed stations/products. Physical and
        # source-identity filters remain intent, not a frozen inventory member list.
        routed = tuple(
            item
            for item in members
            if (not scope.station_ids or item.station_id in scope.station_ids)
            and (not scope.product_ids or item.product_id in scope.product_ids)
        )
        routed_ids = {item.series_id for item in routed}
        retained_inventory = tuple(
            item
            for item in snapshots
            if (
                not scope.station_ids
                or not item.scope.station_ids
                or set(scope.station_ids).intersection(item.scope.station_ids)
            )
            and (
                not scope.product_ids
                or not item.scope.product_ids
                or set(scope.product_ids).intersection(item.scope.product_ids)
            )
        )
        # A broader recorded snapshot is retained whole, with its referenced descriptions.
        evidence_ids = routed_ids | {member for item in retained_inventory for member in item.members}
        definitions.extend(item for item in members if item.series_id in evidence_ids)
        inventories.extend(retained_inventory)
        locations.extend(
            StationLocation(**row)
            for row in record.artifact.stations.iter_rows(named=True)
            if not scope.station_ids or row["station_id"] in scope.station_ids
        )
        if record.artifact.acquisition_provenance is not None:
            evidence.append(record.artifact.acquisition_provenance)
    selected = _Selection(
        scope=scope,
        known_series=tuple(definitions),
        inventories=tuple(inventories),
        locations=tuple(locations),
        acquisition_provenance=tuple(evidence),
    )
    return _with_selection_diagnostics(selected, on_issue)


def _pick(
    records: Sequence[_CatalogueRecord], selection: _Selection, *, on_issue: OnIssue = "warn", **filters
) -> _Selection:
    _require_selection(selection)
    requested = _selection_scope(**filters)
    # Runtime identities are validated from retained evidence, not reconstructed from catalogue triples.
    providers = {str(record.provider_id) for record in records} | {item.provider_id for item in selection.known_series}
    for provider in requested.provider_ids:
        if provider not in providers:
            raise UnknownProviderError(provider)
    products = {item.product_id for item in selection.known_series} | {
        value for record in records for value in record.artifact.products["product_id"].to_list()
    }
    for product in requested.product_ids:
        if product not in products:
            raise UnknownProductError(product)
    station_providers = requested.provider_ids or selection.scope.provider_ids
    stations = {
        item.station_id
        for item in selection.known_series
        if not station_providers or item.provider_id in station_providers
    }
    stations.update(
        value
        for record in records
        if not station_providers or record.provider_id in station_providers
        for value in record.artifact.stations["station_id"].to_list()
    )
    for station in requested.station_ids:
        if station not in stations:
            raise UnknownStationError(station, station_providers)
    narrowed = _coordinate_selection(selection, _intersect_scope(selection.scope, requested))
    return _with_selection_diagnostics(narrowed, on_issue)


def _coordinate_selection(selection: _Selection, scope: SeriesScope) -> _Selection:
    """Retain coordinate-relevant prefetch evidence without rewriting acquired snapshots."""
    from rivretrieve._internal.source_series import ScopeState

    def overlaps(snapshot: InventorySnapshot) -> bool:
        if scope.state is ScopeState.EMPTY:
            return False
        return all(
            not getattr(scope, name)
            or not getattr(snapshot.scope, name)
            or bool(set(getattr(scope, name)).intersection(getattr(snapshot.scope, name)))
            for name in ("provider_ids", "station_ids", "product_ids")
        )

    inventories = tuple(item for item in selection.inventories if overlaps(item))
    referenced_ids = {member for inventory in inventories for member in inventory.members}
    coordinate_scope = scope.model_copy(
        update={"predicates": (), "restriction": RestrictionKind.ALL, "variants": (), "series_ids": ()}
    )
    definitions = tuple(
        item for item in selection.known_series if item.series_id in referenced_ids or coordinate_scope.matches(item)
    )
    referenced_stations = {(item.provider_id, item.station_id) for item in definitions}
    locations = tuple(
        item
        for item in selection.locations
        if (item.provider_id, item.station_id) in referenced_stations
        or (
            scope.state is not ScopeState.EMPTY
            and (not scope.provider_ids or item.provider_id in scope.provider_ids)
            and (not scope.station_ids or item.station_id in scope.station_ids)
        )
    )
    providers = {item.provider_id for item in definitions} | set(scope.provider_ids)
    providers.update(provider for inventory in inventories for provider in inventory.scope.provider_ids)
    evidence = tuple(item for item in selection.acquisition_provenance if item.header.provider_id in providers)
    return _Selection(
        scope=scope,
        known_series=definitions,
        inventories=inventories,
        issues=selection.issues,
        locations=locations,
        acquisition_provenance=evidence,
    )


def _with_selection_diagnostics(selection: _Selection, on_issue: OnIssue) -> _Selection:
    from dataclasses import replace

    from rivretrieve._internal.source_series import ScopeState

    issues = list(selection.issues)
    reason = None
    if not selection.series:
        complete = selection.scope.state is ScopeState.EMPTY or _complete_inventory(selection)
        reason = _EmptyReason(
            "no_match" if complete else "unresolved_inventory",
            selection.scope.provider_ids,
            selection.scope.station_ids,
            selection.scope.product_ids,
        )
        if selection.scope.restriction is RestrictionKind.EXPLICIT:
            issue = Issue(
                severity="warning",
                code="selection.no_match" if complete else "selection.unresolved_inventory",
                message="No source series matches the explicit restriction."
                if complete
                else "The acquired inventory cannot settle the explicit source restriction.",
                details={"scope": selection.scope.model_dump(mode="json")},
            )
            if issue not in issues:
                issues.append(issue)
    result = replace(selection, issues=tuple(issues), empty_reason=reason)
    apply_on_issue(result.issues, on_issue)
    return result


def _complete_inventory(selection: _Selection) -> bool:
    """A complete acquired scope can settle its own scope or an explicit narrower predicate."""
    requested = selection.scope
    for inventory in selection.inventories:
        if inventory.completeness is not InventoryCompleteness.COMPLETE:
            continue
        acquired = inventory.scope
        if acquired.restriction is not RestrictionKind.ALL:
            continue
        covers_coordinates = all(
            not getattr(acquired, name)
            or (bool(getattr(requested, name)) and set(getattr(requested, name)).issubset(getattr(acquired, name)))
            for name in ("provider_ids", "station_ids", "product_ids")
        )
        if covers_coordinates and set(acquired.predicates).issubset(requested.predicates):
            return True
    return False


def _inventory_vintage(inventory: InventorySnapshot) -> str | None:
    if inventory.acquired_at is not None:
        return inventory.acquired_at.isoformat()
    if inventory.catalogue_check_date is not None:
        return inventory.catalogue_check_date.isoformat()
    return None


def _inventory_contains_facts(inventory: InventorySnapshot, series_id: str, facts_id: str) -> bool:
    if series_id not in inventory.members:
        return False
    membership = dict(inventory.member_facts)
    return series_id not in membership or facts_id in membership[series_id]


def _series_frame(
    definitions: tuple[SourceSeries, ...],
    scope: SeriesScope,
    inventories: tuple[InventorySnapshot, ...] = (),
    outcomes: tuple[RetrievalOutcome, ...] = (),
    *,
    provider_id: str | None = None,
) -> pl.DataFrame:
    schema = {
        "provider_id": pl.String,
        "station_id": pl.String,
        "product_id": pl.String,
        "series_id": pl.String,
        "facts_id": pl.String,
        "identity_namespace": pl.String,
        "published_id": pl.String,
        "description": pl.String,
        "identity_origin": pl.String,
        "variant": pl.String,
        "requested_variants": pl.List(pl.String),
        "requested_series_ids": pl.List(pl.String),
        "physical_match": pl.String,
        "admission": pl.String,
        "admission_reason": pl.String,
        "source_unit": pl.String,
        "source_unit_state": pl.String,
        "source_unit_evidence": pl.List(pl.String),
        "normalized_unit": pl.String,
        "identity_evidence": pl.List(pl.String),
        "unit": pl.String,
        **dict.fromkeys(_PHYSICAL_FIELDS, pl.String),
        **{f"{field}_state": pl.String for field in _PHYSICAL_FIELDS},
        **{f"{field}_evidence": pl.List(pl.String) for field in _PHYSICAL_FIELDS},
        "inventory_ids": pl.List(pl.String),
        "inventory_scope": pl.List(pl.String),
        "inventory_windows": pl.List(pl.String),
        "outcome_windows": pl.List(pl.String),
        "inventory_vintage": pl.List(pl.String),
        "inventory_status": pl.List(pl.String),
        "outcomes": pl.List(pl.String),
        "outcome_reasons": pl.List(pl.String),
    }
    inventory_by_series: dict[str, list[InventorySnapshot]] = {}
    for inventory in inventories:
        for member in inventory.members:
            inventory_by_series.setdefault(member, []).append(inventory)
    outcomes_by_series: dict[str, list[RetrievalOutcome]] = {}
    for outcome in outcomes:
        if outcome.series_id is not None:
            outcomes_by_series.setdefault(outcome.series_id, []).append(outcome)
    identity_scope = scope.model_copy(update={"predicates": ()})

    def described_rows() -> Iterator[dict[str, object]]:
        for definition in sorted(
            definitions, key=lambda item: (item.provider_id, item.station_id, item.product_id, item.series_id)
        ):
            series_inventory = inventory_by_series.get(definition.series_id, ())
            series_outcomes = outcomes_by_series.get(definition.series_id, ())
            failures = tuple(
                item for item in series_outcomes if item.status.value in ("failed", "unsupported", "unresolved")
            )
            if not scope.matches(definition) and not (failures and identity_scope.matches(definition)):
                continue
            for facts in sorted(definition.facts, key=lambda item: item.facts_id):
                matches = scope.matches_facts(facts)
                failed_facts = any(not outcome.facts_ids or facts.facts_id in outcome.facts_ids for outcome in failures)
                if not matches and not failed_facts:
                    continue
                decision = admission(facts)
                selected_outcomes = tuple(
                    item
                    for item in series_outcomes
                    if item.series_id == definition.series_id
                    and (not item.facts_ids or facts.facts_id in item.facts_ids)
                )
                row: dict[str, object] = {
                    "provider_id": definition.provider_id,
                    "station_id": definition.station_id,
                    "product_id": definition.product_id,
                    "series_id": definition.series_id,
                    "facts_id": facts.facts_id,
                    "identity_namespace": definition.identity.namespace,
                    "published_id": definition.identity.published_id,
                    "description": definition.identity.description,
                    "identity_origin": definition.identity.origin,
                    "variant": definition.variant,
                    "requested_variants": list(scope.variants),
                    "requested_series_ids": list(scope.series_ids),
                    "physical_match": "matched"
                    if matches
                    else (
                        "unestablished"
                        if any(getattr(facts, predicate.field).value is None for predicate in scope.predicates)
                        else "not_matched"
                    ),
                    "admission": decision.status,
                    "admission_reason": decision.reason,
                    "source_unit": facts.source_unit.value,
                    "source_unit_state": facts.source_unit.state.value,
                    "source_unit_evidence": list(facts.source_unit.evidence),
                    "normalized_unit": facts.normalized_unit,
                    "identity_evidence": list(definition.identity.evidence),
                    "unit": decision.target_unit,
                    "inventory_ids": [
                        item.snapshot_id
                        for item in series_inventory
                        if _inventory_contains_facts(item, definition.series_id, facts.facts_id)
                    ],
                    "inventory_scope": [
                        item.scope.model_dump_json()
                        for item in series_inventory
                        if _inventory_contains_facts(item, definition.series_id, facts.facts_id)
                    ],
                    "inventory_windows": [
                        item.window.model_dump_json()
                        for item in series_inventory
                        if _inventory_contains_facts(item, definition.series_id, facts.facts_id)
                        and item.window is not None
                    ],
                    "outcome_windows": [item.window.model_dump_json() for item in selected_outcomes],
                    "inventory_vintage": [
                        vintage
                        for item in series_inventory
                        if _inventory_contains_facts(item, definition.series_id, facts.facts_id)
                        and (vintage := _inventory_vintage(item)) is not None
                    ],
                    "inventory_status": sorted(
                        {
                            item.completeness.value
                            for item in series_inventory
                            if _inventory_contains_facts(item, definition.series_id, facts.facts_id)
                        }
                    ),
                    "outcomes": [item.status.value for item in selected_outcomes],
                    "outcome_reasons": [item.reason for item in selected_outcomes if item.reason is not None],
                }
                row.update({field: getattr(facts, field).value for field in _PHYSICAL_FIELDS})
                row.update({f"{field}_state": getattr(facts, field).state.value for field in _PHYSICAL_FIELDS})
                row.update({f"{field}_evidence": list(getattr(facts, field).evidence) for field in _PHYSICAL_FIELDS})
                yield row

    def unresolved_rows() -> Iterator[dict[str, object]]:
        for outcome in sorted(outcomes, key=lambda item: (item.station_id, item.product_id)):
            if outcome.series_id is not None:
                continue
            if scope.station_ids and outcome.station_id not in scope.station_ids:
                continue
            if scope.product_ids and outcome.product_id not in scope.product_ids:
                continue
            from rivretrieve._internal.source_series import ScopeState

            if scope.state is ScopeState.EMPTY:
                continue
            row: dict[str, object] = dict.fromkeys(schema)
            row.update(
                {
                    "provider_id": provider_id or (scope.provider_ids[0] if len(scope.provider_ids) == 1 else None),
                    "station_id": outcome.station_id,
                    "product_id": outcome.product_id,
                    "requested_variants": list(scope.variants),
                    "requested_series_ids": list(scope.series_ids),
                    "physical_match": "unestablished",
                    "outcomes": [outcome.status.value],
                    "outcome_windows": [outcome.window.model_dump_json()],
                    "outcome_reasons": [outcome.reason] if outcome.reason is not None else [],
                }
            )
            yield row

    def row_order(row: dict[str, object]) -> tuple[tuple[bool, str], ...]:
        # Null identities sort first, matching Polars' canonical ordering.
        return tuple(
            (row[name] is not None, str(row[name]) if row[name] is not None else "")
            for name in ("provider_id", "station_id", "product_id", "series_id", "facts_id")
        )

    from heapq import merge

    frames: list[pl.DataFrame] = []
    rows: list[dict[str, object]] = []
    for row in merge(described_rows(), unresolved_rows(), key=row_order):
        rows.append(row)
        if len(rows) >= 512:
            frames.append(pl.DataFrame(rows, schema=schema))
            rows.clear()
    if rows:
        frames.append(pl.DataFrame(rows, schema=schema))
    if not frames:
        return pl.DataFrame(schema=schema)
    return pl.concat(frames)


def _as_frame(selection: _Selection) -> pl.DataFrame:
    _require_selection(selection)
    return _series_frame(selection.known_series, selection.scope, selection.inventories)


def _station_keys(selection: _Selection) -> pl.DataFrame:
    """Project selected gauge identities independently of numeric admission or geometry."""
    _require_selection(selection)
    keys = sorted(
        {(item.provider_id, item.station_id) for item in selection.known_series if selection.scope.matches(item)}
    )
    return pl.DataFrame(keys, schema={"provider_id": pl.String, "station_id": pl.String}, orient="row")


def _station_frame(selection: _Selection) -> StationCatalog:
    _require_selection(selection)
    from dataclasses import asdict

    selected = set(_station_keys(selection).iter_rows())
    return pl.DataFrame(
        [asdict(item) for item in selection.locations if (item.provider_id, item.station_id) in selected],
        schema=STATION_CATALOG_SCHEMA.polars_schema,
    ).unique(subset=["provider_id", "station_id"], maintain_order=True)


def _from_frame(records: Sequence[_CatalogueRecord], frame: pl.DataFrame) -> _Selection:
    raise ValueError("Bare selection frames are not a durable format. Use from_bundle with a versioned export bundle.")


def _require_selection(selection: object) -> None:
    if not isinstance(selection, _Selection):
        raise TypeError("selection must be a RivRetrieve selection")
