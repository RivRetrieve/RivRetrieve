"""Offline source-series discovery and immutable physical/identity selection."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from operator import attrgetter
from typing import Literal, Protocol, cast

import polars as pl

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.evidence import CatalogueEvidence
from rivretrieve._internal.catalogues.schemas import STATION_CATALOG_SCHEMA, StationCatalog
from rivretrieve._internal.issues import FatalContractError, Issue, apply_on_issue
from rivretrieve._internal.primitives import OnIssue, ProviderId
from rivretrieve._internal.registry import UnknownProviderError
from rivretrieve._internal.source_series import (
    _PLAIN_JSON_ASCII_FULLMATCH,
    InventoryCompleteness,
    InventorySnapshot,
    PhysicalFacts,
    PhysicalPredicate,
    RestrictionKind,
    RetrievalOutcome,
    ScopeState,
    SeriesScope,
    SourceIdentity,
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
    physical_filters: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StationLocation:
    provider_id: str
    station_id: str
    latitude: float | None
    longitude: float | None
    crs: str


@dataclass(frozen=True, slots=True)
class _Selection:
    """A search to retrieve later: requested filters plus the catalogue evidence found.

    A selection is returned by ``find``, ``pick`` and ``from_bundle`` and cannot
    be changed in place. Pass it to the public functions rather than building
    one directly. The known series are evidence, and the filters remain the
    request, so retrieval can include series found later. ``series(selection)``
    shows their contents as a frame.

    Attributes
    ----------
    scope : SeriesScope
        Requested filters and source restrictions. ``fetch`` retrieves by this
        intent, not only by the known members below.
    known_series : tuple[SourceSeries, ...]
        Source-series definitions retained from packaged evidence for the
        selected stations and access routes. Some may not match the physical
        filters.
    inventories : tuple[InventorySnapshot, ...]
        Packaged inventory snapshots for the selected coordinates.
    issues : tuple[Issue, ...]
        Findings recorded during selection, such as ``selection.no_match`` or
        ``selection.unresolved_inventory``. ``fetch`` copies them into its
        result. An unresolved restriction that retrieval settles becomes an
        ``info`` issue with code ``selection.inventory_resolved``.
    locations : tuple[StationLocation, ...]
        Catalogue coordinates and CRS statements used by ``map``.
    acquisition_provenance : tuple[CatalogueEvidence, ...]
        Evidence describing how the packaged catalogues were acquired.
    empty_reason : empty-selection reason or None
        None when at least one known admitted series matches. Otherwise
        ``empty_reason.code`` is ``no_match`` or ``unresolved_inventory``.
    series : tuple[SourceSeries, ...]
        Property returning the known series that match ``scope`` and have at
        least one matching fact segment with supported admission.
    """

    scope: SeriesScope
    known_series: tuple[SourceSeries, ...] = ()
    inventories: tuple[InventorySnapshot, ...] = ()
    issues: tuple[Issue, ...] = ()
    locations: tuple[StationLocation, ...] = ()
    acquisition_provenance: tuple[CatalogueEvidence, ...] = ()
    empty_reason: _EmptyReason | None = None

    def __post_init__(self) -> None:
        seen: set[str] = set()
        seen_add = seen.add
        has_non_series = False
        for item in self.known_series:
            sid = item.series_id
            if sid in seen:
                raise FatalContractError("Selection contains duplicate source-series definitions")
            seen_add(sid)
            if not has_non_series and type(item) is not SourceSeries and not isinstance(item, SourceSeries):
                has_non_series = True
        if has_non_series:
            raise TypeError("Selection requires validated source-series definitions")

    @property
    def series(self) -> tuple[SourceSeries, ...]:
        return tuple(
            item
            for item in self.known_series
            if self.scope.matches(item)
            and any(self.scope.matches_facts(facts) and admission(facts).status == "supported" for facts in item.facts)
        )


# Supported query meanings, separate from open-ended publisher evidence.
QUERY_VOCABULARIES = {
    "quantity": ("discharge", "stage", "temperature"),
    "frequency": ("10min", "hourly", "daily", "monthly", "yearly"),
    "statistic": ("mean", "min", "max", "instantaneous"),
}


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
    predicates = tuple(
        PhysicalPredicate.model_validate({"field": field, "value": value})
        for field, value in values.items()
        if value is not None
    )
    for predicate in predicates:
        supported = QUERY_VOCABULARIES.get(predicate.field)
        if supported is not None and predicate.value not in supported:
            raise ValueError(
                f"Unsupported {predicate.field} filter {predicate.value!r}. Supported values: "
                + ", ".join(repr(value) for value in supported)
            )
    return predicates


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
    if not scope.provider_ids and not scope.product_ids and not scope.station_ids:
        return
    providers = {str(record.provider_id) for record in records}
    for provider in scope.provider_ids:
        if provider not in providers:
            raise UnknownProviderError(provider)
    if not scope.product_ids and not scope.station_ids:
        return
    provider_set = set(scope.provider_ids)
    relevant = tuple(record for record in records if not provider_set or record.provider_id in provider_set)
    if scope.product_ids:
        products = {value for record in relevant for value in record.artifact.products["product_id"].to_list()}
        for product in scope.product_ids:
            if product not in products:
                raise UnknownProductError(product)
    if scope.station_ids:
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
    provider_set = set(scope.provider_ids)
    station_set = set(scope.station_ids)
    product_set = set(scope.product_ids)
    inventory_scope = scope.model_copy(
        update={"predicates": (), "restriction": RestrictionKind.ALL, "variants": (), "series_ids": ()}
    )
    for record in records:
        if provider_set and record.provider_id not in provider_set:
            continue
        members, snapshots = catalogue_series(record.artifact, scope=inventory_scope)
        if not station_set and not product_set:
            definitions.extend(members)
            inventories.extend(snapshots)
        else:
            # Keep acquired evidence for the routed stations/products. Physical and
            # source-identity filters remain intent, not a frozen inventory member list.
            routed_ids = {
                item.series_id
                for item in members
                if (not station_set or item.station_id in station_set)
                and (not product_set or item.product_id in product_set)
            }
            retained_inventory = tuple(
                item
                for item in snapshots
                if (not station_set or not item.scope.station_ids or not station_set.isdisjoint(item.scope.station_ids))
                and (
                    not product_set or not item.scope.product_ids or not product_set.isdisjoint(item.scope.product_ids)
                )
            )
            # A broader recorded snapshot is retained whole, with its referenced descriptions.
            evidence_ids = routed_ids | {member for item in retained_inventory for member in item.members}
            definitions.extend(item for item in members if item.series_id in evidence_ids)
            inventories.extend(retained_inventory)
        stations_df = record.artifact.stations
        if station_set:
            stations_df = stations_df.filter(pl.col("station_id").is_in(station_set))
        if stations_df.height:
            s_cols = stations_df.to_dict(as_series=False)
            locations.extend(
                StationLocation(prov, sid, lat, lon, crs)
                for prov, sid, lat, lon, crs in zip(
                    s_cols["provider_id"],
                    s_cols["station_id"],
                    s_cols["latitude"],
                    s_cols["longitude"],
                    s_cols["crs"],
                    strict=True,
                )
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
    if requested.provider_ids:
        providers = {str(record.provider_id) for record in records} | {
            item.provider_id for item in selection.known_series
        }
        for provider in requested.provider_ids:
            if provider not in providers:
                raise UnknownProviderError(provider)
    if requested.product_ids:
        products = {item.product_id for item in selection.known_series} | {
            value for record in records for value in record.artifact.products["product_id"].to_list()
        }
        for product in requested.product_ids:
            if product not in products:
                raise UnknownProductError(product)
    if requested.station_ids:
        station_providers = requested.provider_ids or selection.scope.provider_ids
        station_provider_set = set(station_providers)
        stations = {
            item.station_id
            for item in selection.known_series
            if not station_provider_set or item.provider_id in station_provider_set
        }
        stations.update(
            value
            for record in records
            if not station_provider_set or record.provider_id in station_provider_set
            for value in record.artifact.stations["station_id"].to_list()
        )
        for station in requested.station_ids:
            if station not in stations:
                raise UnknownStationError(station, station_providers)
    narrowed = _coordinate_selection(selection, _intersect_scope(selection.scope, requested))
    return _with_selection_diagnostics(narrowed, on_issue)


def _coordinate_selection(selection: _Selection, scope: SeriesScope) -> _Selection:
    """Retain coordinate-relevant prefetch evidence without rewriting acquired snapshots."""
    is_empty = scope.state is ScopeState.EMPTY
    prov_set = set(scope.provider_ids)
    stat_set = set(scope.station_ids)
    prod_set = set(scope.product_ids)

    def overlaps(snapshot: InventorySnapshot) -> bool:
        if is_empty:
            return False
        snap_scope = snapshot.scope
        return (
            (not prov_set or not snap_scope.provider_ids or not prov_set.isdisjoint(snap_scope.provider_ids))
            and (not stat_set or not snap_scope.station_ids or not stat_set.isdisjoint(snap_scope.station_ids))
            and (not prod_set or not snap_scope.product_ids or not prod_set.isdisjoint(snap_scope.product_ids))
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
            not is_empty
            and (not prov_set or item.provider_id in prov_set)
            and (not stat_set or item.station_id in stat_set)
        )
    )
    providers = {item.provider_id for item in definitions} | prov_set
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


def _has_admitted_series(selection: _Selection) -> bool:
    scope = selection.scope
    for item in selection.known_series:
        if scope.matches(item):
            for facts in item.facts:
                if scope.matches_facts(facts) and admission(facts).status == "supported":
                    return True
    return False


def _with_selection_diagnostics(selection: _Selection, on_issue: OnIssue) -> _Selection:
    from dataclasses import replace

    # These findings describe the current view, not an earlier, broader selection.
    issues = [
        item for item in selection.issues if item.code not in ("selection.no_match", "selection.unresolved_inventory")
    ]
    reason = None
    if not _has_admitted_series(selection):
        complete = selection.scope.state is ScopeState.EMPTY or _complete_inventory(selection)
        reason = _EmptyReason(
            "no_match" if complete else "unresolved_inventory",
            selection.scope.provider_ids,
            selection.scope.station_ids,
            selection.scope.product_ids,
            physical_filters=tuple(f"{item.field}={item.value!r}" for item in selection.scope.predicates),
        )
    if selection.scope.restriction is RestrictionKind.EXPLICIT:
        members: list[tuple[str | None, str | None, SeriesScope]] = [
            (kind, value, selection.scope.model_copy(update={field: (value,)}))
            for kind, field in (("variant", "variants"), ("series_id", "series_ids"))
            for value in getattr(selection.scope, field)
        ]
        if selection.scope.state is ScopeState.EMPTY:
            members = [(None, None, selection.scope)]
        for kind, value, member_scope in members:
            if any(member_scope.matches(item) for item in selection.known_series):
                continue
            complete = member_scope.state is ScopeState.EMPTY or _complete_inventory(
                replace(selection, scope=member_scope)
            )
            details: dict[str, object] = {"scope": member_scope.model_dump(mode="json")}
            if kind is not None:
                details["requested_selector"] = {"kind": kind, "value": value}
            issues.append(
                Issue(
                    severity="warning",
                    code="selection.no_match" if complete else "selection.unresolved_inventory",
                    message=(
                        f"No source series matches the explicit restriction {value!r}."
                        if complete
                        else f"The acquired inventory cannot settle the explicit source restriction {value!r}."
                    ),
                    details=details,
                )
            )
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
    if not inventory.member_facts:
        return True
    for member, f_ids in inventory.member_facts:
        if member == series_id:
            return facts_id in f_ids
    return True


_SCOPE_PROBE = SeriesScope(
    provider_ids=("__PROV__",),
    station_ids=("__STAT__",),
    product_ids=("__PROD__",),
).model_dump_json()
_SCOPE_P0, _SCOPE_R1 = _SCOPE_PROBE.split("__PROV__")
_SCOPE_P1, _SCOPE_R2 = _SCOPE_R1.split("__STAT__")
_SCOPE_P2, _SCOPE_P3 = _SCOPE_R2.split("__PROD__")
del _SCOPE_PROBE, _SCOPE_R1, _SCOPE_R2


_SERIES_SORT_KEY = attrgetter("provider_id", "station_id", "product_id", "series_id")
_FACTS_SORT_KEY = attrgetter("facts_id")


def _is_plain_json_ascii(value: str) -> bool:
    return _PLAIN_JSON_ASCII_FULLMATCH(value) is not None


def _fast_scope_json(scope_obj: SeriesScope) -> str:
    if (
        scope_obj.state is ScopeState.ACTIVE
        and scope_obj.restriction is RestrictionKind.ALL
        and not scope_obj.predicates
        and not scope_obj.variants
        and not scope_obj.series_ids
        and len(scope_obj.provider_ids) == 1
        and len(scope_obj.station_ids) == 1
        and len(scope_obj.product_ids) == 1
    ):
        prov = scope_obj.provider_ids[0]
        stat = scope_obj.station_ids[0]
        prod = scope_obj.product_ids[0]
        if _is_plain_json_ascii(prov) and _is_plain_json_ascii(stat) and _is_plain_json_ascii(prod):
            return f"{_SCOPE_P0}{prov}{_SCOPE_P1}{stat}{_SCOPE_P2}{prod}{_SCOPE_P3}"
    return scope_obj.model_dump_json()


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
        "requested_selector_kind": pl.String,
        "requested_selector_value": pl.String,
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

    if not outcomes:
        if not definitions or scope.state is ScopeState.EMPTY:
            return pl.DataFrame(schema=schema)

        unrestricted_scope = (
            scope.state is ScopeState.ACTIVE
            and not scope.provider_ids
            and not scope.station_ids
            and not scope.product_ids
            and scope.restriction is RestrictionKind.ALL
            and not scope.predicates
        )

        # Deduplicate shared PhysicalFacts and SourceIdentity instances to compact indices
        # and expand in native Polars via .gather() after scanning definitions.
        unique_facts: list[PhysicalFacts] = []
        facts_idx_cache: dict[int, tuple[PhysicalFacts, int, str]] = {}
        unique_idents: list[SourceIdentity] = []
        ident_idx_cache: dict[int, tuple[SourceIdentity, int]] = {}
        inv_meta_cache: dict[int, tuple[InventorySnapshot, str, str | None, str | None]] = {}

        c_prov: list[str] = []
        c_stat: list[str] = []
        c_prod: list[str] = []
        c_sid: list[str] = []
        c_var: list[str | None] = []
        c_ident_idx: list[int] = []
        c_fact_idx: list[int] = []

        inv_offsets: list[int] = [0]
        flat_inv_ids: list[str] = []
        flat_inv_scope: list[str] = []
        win_offsets: list[int] = [0]
        flat_inv_win: list[str] = []
        vint_offsets: list[int] = [0]
        flat_inv_vint: list[str] = []
        stat_offsets: list[int] = [0]
        flat_inv_stat: list[str] = []

        sorted_defs = sorted(definitions, key=_SERIES_SORT_KEY)
        for definition in sorted_defs:
            if unrestricted_scope:
                if not definition.facts:
                    continue
            elif not scope.matches(definition):
                continue
            series_inventory = inventory_by_series.get(definition.series_id)
            ident = definition.identity
            ident_key = id(ident)
            cached_ident = ident_idx_cache.get(ident_key)
            if cached_ident is None:
                ident_idx = len(unique_idents)
                unique_idents.append(ident)
                ident_idx_cache[ident_key] = (ident, ident_idx)
            else:
                ident_idx = cached_ident[1]

            def_facts = (
                definition.facts if len(definition.facts) == 1 else sorted(definition.facts, key=_FACTS_SORT_KEY)
            )
            for facts in def_facts:
                fid_key = id(facts)
                cached_fact = facts_idx_cache.get(fid_key)
                if cached_fact is None:
                    if unrestricted_scope or scope.matches_facts(facts):
                        f_idx = len(unique_facts)
                        unique_facts.append(facts)
                        fid_str = facts.facts_id
                        facts_idx_cache[fid_key] = (facts, f_idx, fid_str)
                    else:
                        facts_idx_cache[fid_key] = (facts, -1, "")
                        continue
                else:
                    f_idx = cached_fact[1]
                    if f_idx < 0:
                        continue
                    fid_str = cached_fact[2]

                c_prov.append(definition.provider_id)
                c_stat.append(definition.station_id)
                c_prod.append(definition.product_id)
                c_sid.append(definition.series_id)
                c_var.append(definition.variant)
                c_ident_idx.append(ident_idx)
                c_fact_idx.append(f_idx)

                if not series_inventory:
                    inv_offsets.append(len(flat_inv_ids))
                    win_offsets.append(len(flat_inv_win))
                    vint_offsets.append(len(flat_inv_vint))
                    stat_offsets.append(len(flat_inv_stat))
                elif len(series_inventory) == 1:
                    inv = series_inventory[0]
                    if not inv.member_facts or _inventory_contains_facts(inv, definition.series_id, fid_str):
                        inv_key = id(inv)
                        cached_inv = inv_meta_cache.get(inv_key)
                        if cached_inv is None:
                            s_json = _fast_scope_json(inv.scope)
                            w_json = inv.window.model_dump_json() if inv.window is not None else None
                            v_str = _inventory_vintage(inv)
                            inv_meta_cache[inv_key] = (inv, s_json, w_json, v_str)
                        else:
                            _, s_json, w_json, v_str = cached_inv
                        flat_inv_ids.append(inv.snapshot_id)
                        flat_inv_scope.append(s_json)
                        inv_offsets.append(len(flat_inv_ids))
                        if w_json is not None:
                            flat_inv_win.append(w_json)
                        win_offsets.append(len(flat_inv_win))
                        if v_str is not None:
                            flat_inv_vint.append(v_str)
                        vint_offsets.append(len(flat_inv_vint))
                        flat_inv_stat.append(inv.completeness.value)
                        stat_offsets.append(len(flat_inv_stat))
                    else:
                        inv_offsets.append(len(flat_inv_ids))
                        win_offsets.append(len(flat_inv_win))
                        vint_offsets.append(len(flat_inv_vint))
                        stat_offsets.append(len(flat_inv_stat))
                else:
                    matched_inv = [
                        item
                        for item in series_inventory
                        if not item.member_facts or _inventory_contains_facts(item, definition.series_id, fid_str)
                    ]
                    for item in matched_inv:
                        flat_inv_ids.append(item.snapshot_id)
                        flat_inv_scope.append(_fast_scope_json(item.scope))
                        if item.window is not None:
                            flat_inv_win.append(item.window.model_dump_json())
                        vint = _inventory_vintage(item)
                        if vint is not None:
                            flat_inv_vint.append(vint)
                    inv_offsets.append(len(flat_inv_ids))
                    win_offsets.append(len(flat_inv_win))
                    vint_offsets.append(len(flat_inv_vint))
                    if matched_inv:
                        flat_inv_stat.extend(sorted({item.completeness.value for item in matched_inv}))
                    stat_offsets.append(len(flat_inv_stat))

        n_rows = len(c_prov)
        if not n_rows:
            return pl.DataFrame(schema=schema)
        import pyarrow as pa

        pa_str = pa.string()
        pa_i32 = pa.int32()
        pa_str_list = pa.list_(pa_str)

        def _list_series(name: str, values: list[list[str]]) -> pl.Series:
            return cast("pl.Series", pl.from_arrow(pa.array(values, type=pa_str_list))).rename(name)

        def _flat_list_series(name: str, offsets_arr: pa.Array, flat_values: list[str]) -> pl.Series:
            arr = pa.ListArray.from_arrays(offsets_arr, pa.array(flat_values, type=pa_str))
            return cast("pl.Series", pl.from_arrow(arr)).rename(name)

        empty_str_series = pl.repeat(None, n_rows, dtype=pl.String, eager=True)
        empty_list_series = pl.repeat([], n_rows, dtype=pl.List(pl.String), eager=True)

        # Build compact K-row PhysicalFacts table and gather to n_rows in Rust.
        f_decisions = [admission(f) for f in unique_facts]
        fact_cols: list[pl.Series] = [
            pl.Series("facts_id", [f.facts_id for f in unique_facts], dtype=pl.String),
            pl.Series("admission", [d.status for d in f_decisions], dtype=pl.String),
            pl.Series("admission_reason", [d.reason for d in f_decisions], dtype=pl.String),
            pl.Series("source_unit", [f.source_unit.value for f in unique_facts], dtype=pl.String),
            pl.Series("source_unit_state", [f.source_unit.state.value for f in unique_facts], dtype=pl.String),
            _list_series("source_unit_evidence", [list(f.source_unit.evidence) for f in unique_facts]),
            pl.Series("normalized_unit", [f.normalized_unit for f in unique_facts], dtype=pl.String),
            pl.Series("unit", [d.target_unit for d in f_decisions], dtype=pl.String),
        ]
        for field in _PHYSICAL_FIELDS:
            objs = [getattr(f, field) for f in unique_facts]
            fact_cols.append(pl.Series(field, [o.value for o in objs], dtype=pl.String))
            fact_cols.append(pl.Series(f"{field}_state", [o.state.value for o in objs], dtype=pl.String))
            fact_cols.append(_list_series(f"{field}_evidence", [list(o.evidence) for o in objs]))
        fact_idx_s = pl.Series("_f_idx", c_fact_idx, dtype=pl.UInt32)
        expanded_facts = pl.DataFrame(fact_cols).select(pl.all().gather(fact_idx_s))

        # Build compact M-row SourceIdentity table and gather to n_rows in Rust.
        ident_df = pl.DataFrame(
            [
                pl.Series("identity_namespace", [i.namespace for i in unique_idents], dtype=pl.String),
                pl.Series("published_id", [i.published_id for i in unique_idents], dtype=pl.String),
                pl.Series("description", [i.description for i in unique_idents], dtype=pl.String),
                pl.Series("identity_origin", [i.origin for i in unique_idents], dtype=pl.String),
                _list_series("identity_evidence", [list(i.evidence) for i in unique_idents]),
            ]
        )
        ident_idx_s = pl.Series("_i_idx", c_ident_idx, dtype=pl.UInt32)
        expanded_idents = ident_df.select(pl.all().gather(ident_idx_s))

        inv_offsets_pa = pa.array(inv_offsets, type=pa_i32)
        columns_map: dict[str, pl.Series] = {
            "provider_id": pl.Series("provider_id", c_prov, dtype=pl.String),
            "station_id": pl.Series("station_id", c_stat, dtype=pl.String),
            "product_id": pl.Series("product_id", c_prod, dtype=pl.String),
            "series_id": pl.Series("series_id", c_sid, dtype=pl.String),
            "variant": pl.Series("variant", c_var, dtype=pl.String),
            "requested_variants": pl.repeat(list(scope.variants), n_rows, dtype=pl.List(pl.String), eager=True).alias(
                "requested_variants"
            ),
            "requested_series_ids": pl.repeat(
                list(scope.series_ids), n_rows, dtype=pl.List(pl.String), eager=True
            ).alias("requested_series_ids"),
            "requested_selector_kind": empty_str_series.alias("requested_selector_kind"),
            "requested_selector_value": empty_str_series.alias("requested_selector_value"),
            "physical_match": pl.repeat("matched", n_rows, dtype=pl.String, eager=True).alias("physical_match"),
            "inventory_ids": (
                _flat_list_series("inventory_ids", inv_offsets_pa, flat_inv_ids)
                if flat_inv_ids
                else empty_list_series.alias("inventory_ids")
            ),
            "inventory_scope": (
                _flat_list_series("inventory_scope", inv_offsets_pa, flat_inv_scope)
                if flat_inv_scope
                else empty_list_series.alias("inventory_scope")
            ),
            "inventory_windows": (
                _flat_list_series("inventory_windows", pa.array(win_offsets, type=pa_i32), flat_inv_win)
                if flat_inv_win
                else empty_list_series.alias("inventory_windows")
            ),
            "outcome_windows": empty_list_series.alias("outcome_windows"),
            "inventory_vintage": (
                _flat_list_series("inventory_vintage", pa.array(vint_offsets, type=pa_i32), flat_inv_vint)
                if flat_inv_vint
                else empty_list_series.alias("inventory_vintage")
            ),
            "inventory_status": (
                _flat_list_series("inventory_status", pa.array(stat_offsets, type=pa_i32), flat_inv_stat)
                if flat_inv_stat
                else empty_list_series.alias("inventory_status")
            ),
            "outcomes": empty_list_series.alias("outcomes"),
            "outcome_reasons": empty_list_series.alias("outcome_reasons"),
        }
        for col in expanded_facts.get_columns():
            columns_map[col.name] = col
        for col in expanded_idents.get_columns():
            columns_map[col.name] = col
        return pl.DataFrame([columns_map[col_name] for col_name in schema])

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
                matched_inv = [
                    item
                    for item in series_inventory
                    if _inventory_contains_facts(item, definition.series_id, facts.facts_id)
                ]
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
                    "inventory_ids": [item.snapshot_id for item in matched_inv],
                    "inventory_scope": [_fast_scope_json(item.scope) for item in matched_inv],
                    "inventory_windows": [
                        item.window.model_dump_json() for item in matched_inv if item.window is not None
                    ],
                    "outcome_windows": [item.window.model_dump_json() for item in selected_outcomes],
                    "inventory_vintage": [
                        vintage for item in matched_inv if (vintage := _inventory_vintage(item)) is not None
                    ],
                    "inventory_status": sorted({item.completeness.value for item in matched_inv}),
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
            if scope.provider_ids and provider_id is not None and provider_id not in scope.provider_ids:
                continue
            requested = outcome.requested_selector
            if requested is not None:
                member_scope = _intersect_scope(scope, _selection_scope(**{requested.kind: requested.value}))
                if member_scope.state is ScopeState.EMPTY:
                    continue
                if scope.series_ids:
                    identified = {item.series_id: item for item in definitions}
                    if all(identifier in identified for identifier in scope.series_ids) and not any(
                        member_scope.model_copy(update={"predicates": ()}).matches(identified[identifier])
                        for identifier in scope.series_ids
                    ):
                        continue
            if scope.station_ids and outcome.station_id not in scope.station_ids:
                continue
            if scope.product_ids and outcome.product_id not in scope.product_ids:
                continue
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
                    "requested_selector_kind": requested.kind if requested is not None else None,
                    "requested_selector_value": requested.value if requested is not None else None,
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
    if not keys:
        return pl.DataFrame(schema={"provider_id": pl.String, "station_id": pl.String})
    provs, stats = zip(*keys, strict=True)
    return pl.DataFrame(
        {"provider_id": provs, "station_id": stats}, schema={"provider_id": pl.String, "station_id": pl.String}
    )


def _station_frame(selection: _Selection) -> StationCatalog:
    _require_selection(selection)
    selected = {(item.provider_id, item.station_id) for item in selection.known_series if selection.scope.matches(item)}
    if not selected or not selection.locations:
        return pl.DataFrame(schema=STATION_CATALOG_SCHEMA.polars_schema)
    seen: set[tuple[str, str]] = set()
    provs: list[str] = []
    stats: list[str] = []
    lats: list[float | None] = []
    lons: list[float | None] = []
    crs_list: list[str] = []
    for loc in selection.locations:
        key = (loc.provider_id, loc.station_id)
        if key in selected and key not in seen:
            seen.add(key)
            provs.append(loc.provider_id)
            stats.append(loc.station_id)
            lats.append(loc.latitude)
            lons.append(loc.longitude)
            crs_list.append(loc.crs)
    return pl.DataFrame(
        {
            "provider_id": provs,
            "station_id": stats,
            "latitude": lats,
            "longitude": lons,
            "crs": crs_list,
        },
        schema=STATION_CATALOG_SCHEMA.polars_schema,
    )


def _from_frame(records: Sequence[_CatalogueRecord], frame: pl.DataFrame) -> _Selection:
    raise ValueError("Bare selection frames are not a durable format. Use from_bundle with a versioned export bundle.")


def _require_selection(selection: object) -> None:
    if not isinstance(selection, _Selection):
        raise TypeError("selection must be a RivRetrieve selection")
