"""public retrieval : Selection × WindowInputs × CacheMode × CredentialSources → ObservationResult(s); provider discovery : ProviderDeclarations × CredentialSources → ProviderAccessFrame; drainage metadata : Selection → SourceAreaFrame."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, time
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, cast

import polars as pl
from dotenv import dotenv_values
from platformdirs import user_cache_dir

from rivretrieve._internal.authentication import CredentialExchangeTransport
from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.issues import FatalContractError, Issue, MissingCredentialError, apply_on_issue
from rivretrieve._internal.observations import ObservationRequest, ObservationResult, ReceiptMode, Receipts
from rivretrieve._internal.primitives import CacheMode
from rivretrieve._internal.registry import UnknownProviderError, _registry
from rivretrieve._internal.selection import _as_frame as _selection_as_frame
from rivretrieve._internal.selection import _EmptyReason, _require_selection, _Selection
from rivretrieve._internal.selection import _find as _selection_find
from rivretrieve._internal.selection import _from_frame as _selection_from_frame
from rivretrieve._internal.selection import _pick as _selection_pick
from rivretrieve._internal.selection import _station_frame as _selection_station_frame
from rivretrieve._internal.selection import _station_keys as _selection_station_keys
from rivretrieve._internal.source_series import SourceSeries
from rivretrieve._internal.station_map import StationMap
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.transport import (
    AuthenticatedTransport,
    CredentialHeader,
    HttpClient,
    Transport,
    _SystemClock,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rivretrieve._internal.primitives import OnIssue

_DEFAULT_PROVIDER_REGISTRATION_ENABLED = True


def describe(provider: str) -> dict[str, object]:
    """Read one provider's packaged Croissant JSON-LD descriptor offline.

    Parameters
    ----------
    provider : str
        Built-in provider identifier.

    Returns
    -------
    dict[str, object]
        Parsed descriptor with catalogue file identities, extraction rules,
        evidence relations and recorded absences. This is not an observation
        descriptor or a live inventory.

    Raises
    ------
    UnknownProviderError
        If provider is not in the built-in manifest.
    FatalContractError
        If the JSON document is not an object.
    OSError
        If the packaged descriptor cannot be read.
    json.JSONDecodeError
        If its JSON is malformed.
    """
    from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS

    if provider not in BUILTIN_PROVIDER_IDS:
        raise UnknownProviderError(provider)
    descriptor = files("rivretrieve._internal.providers").joinpath(provider, "catalogue", "croissant.json")
    document = json.loads(descriptor.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise FatalContractError(f"Catalogue descriptor for {provider} must be a JSON object")
    return document


def providers() -> pl.DataFrame:
    """List registered providers and local credential readiness.

    Returns
    -------
    polars.DataFrame
        Columns are provider_id (String), credentials (List(String)) and access
        (String). Rows are sorted by provider_id. Access is "open", "ready",
        or "missing <variable names>". It does not test source access.

    Raises
    ------
    FatalContractError
        If a shipped declaration or catalogue cannot be loaded.

    Notes
    -----
    Reads credential names from declarations and values from the process
    environment or the working directory .env file. A present environment
    variable takes precedence, including a blank value. Values are not returned.
    No source request is made.
    """
    _ensure_default_providers_registered()
    resolved = _resolve_credentials(_registry.list_provider_ids(), require_all=False)
    rows = []
    for record in _registry.iter_records():
        names = record.handle.required_credentials
        missing = tuple(name for name in names if name not in resolved[record.provider_id])
        access = "open" if not names else f"missing {', '.join(missing)}" if missing else "ready"
        rows.append((str(record.provider_id), list(names), access))
    return pl.DataFrame(
        rows,
        schema={"provider_id": pl.Utf8, "credentials": pl.List(pl.Utf8), "access": pl.Utf8},
        orient="row",
    )


def find(
    *,
    provider: str | None = None,
    station: str | None = None,
    quantity: str | None = None,
    frequency: str | None = None,
    statistic: str | None = None,
    temporal_support: str | None = None,
    day_definition: str | None = None,
    timestamp_anchor: str | None = None,
    time_zone: str | None = None,
    vertical_reference: str | None = None,
    vertical_datum: str | None = None,
    variant: str | None = None,
    series_id: str | None = None,
    on_issue: OnIssue = "warn",
) -> _Selection:
    """Find all supported series matching established physical facts, using offline catalogue evidence.

    Source alternatives remain distinct. Unknown facts cannot satisfy precise
    predicates. An incomplete inventory retains explicit unresolved restrictions;
    observation services are contacted only by fetch.
    """
    _ensure_default_providers_registered()
    _validate_issue_policy(on_issue)
    return _selection_find(
        _registry.iter_records(),
        provider=provider,
        station=station,
        quantity=quantity,
        frequency=frequency,
        statistic=statistic,
        temporal_support=temporal_support,
        day_definition=day_definition,
        timestamp_anchor=timestamp_anchor,
        time_zone=time_zone,
        vertical_reference=vertical_reference,
        vertical_datum=vertical_datum,
        variant=variant,
        series_id=series_id,
        on_issue=on_issue,
    )


def pick(
    selection: _Selection | ObservationResult,
    *,
    provider: str | Sequence[str] | None = None,
    station: str | Sequence[str] | None = None,
    quantity: str | None = None,
    frequency: str | None = None,
    statistic: str | None = None,
    temporal_support: str | None = None,
    day_definition: str | None = None,
    timestamp_anchor: str | None = None,
    time_zone: str | None = None,
    vertical_reference: str | None = None,
    vertical_datum: str | None = None,
    variant: str | Sequence[str] | None = None,
    series_id: str | Sequence[str] | None = None,
    on_issue: OnIssue = "warn",
) -> _Selection | ObservationResult:
    """Narrow immutable intent or a retrieved view without another source request.

    Result provenance and receipts remain unchanged. Original receipts can contain
    source rows outside the narrowed view; ``view_scope`` records the restriction.
    """
    from rivretrieve._internal.selection import _intersect_scope, _selection_scope

    _validate_issue_policy(on_issue)
    filters = {
        "provider": provider,
        "station": station,
        "quantity": quantity,
        "frequency": frequency,
        "statistic": statistic,
        "temporal_support": temporal_support,
        "day_definition": day_definition,
        "timestamp_anchor": timestamp_anchor,
        "time_zone": time_zone,
        "vertical_reference": vertical_reference,
        "vertical_datum": vertical_datum,
        "variant": variant,
        "series_id": series_id,
    }
    if isinstance(selection, ObservationResult):
        scope = _intersect_scope(selection.view_scope or selection.scope, _selection_scope(**filters))
        pairs = [
            (item.series_id, facts.facts_id)
            for item in selection.source_series
            if scope.matches(item)
            for facts in item.facts
            if scope.matches_facts(facts)
        ]
        predicate = (
            pl.any_horizontal(
                [
                    (pl.col("series_id") == identifier) & (pl.col("facts_id") == facts_id)
                    for identifier, facts_id in pairs
                ]
            )
            if pairs
            else pl.lit(False)
        )
        selected = _Selection(scope=scope, known_series=selection.source_series, inventories=selection.inventories)
        from rivretrieve._internal.selection import _with_selection_diagnostics

        selected = _with_selection_diagnostics(selected, "ignore")
        result = ObservationResult(
            data=selection.data.filter(predicate),
            provenance=selection.provenance,
            receipts=selection.receipts,
            source_series=selection.source_series,
            inventories=selection.inventories,
            outcomes=selection.outcomes,
            scope=selection.scope,
            view_scope=scope,
            issues=(*selection.issues, *selected.issues),
        )
        apply_on_issue(result.issues, on_issue)
        return result
    return _selection_pick(_registry.iter_records(), selection, on_issue=on_issue, **filters)


def series(value: _Selection | ObservationResult) -> pl.DataFrame:
    """Inspect source identities, independent physical facts, inventory and empty/failed outcomes."""
    from rivretrieve._internal.selection import _series_frame

    if isinstance(value, ObservationResult):
        return _series_frame(
            value.source_series,
            value.view_scope or value.scope,
            value.inventories,
            value.outcomes,
            provider_id=str(value.provenance.provider_id),
        )
    return _selection_as_frame(value)


def as_frame(selection: _Selection) -> pl.DataFrame:
    """Return an inspection frame. Use to_bundle for a durable, lossless round trip."""
    return _selection_as_frame(selection)


def from_frame(frame: pl.DataFrame) -> _Selection:
    """Refuse obsolete triple-only imports; use a validated versioned export bundle."""
    return _selection_from_frame((), frame)


def to_bundle(value: _Selection | ObservationResult) -> bytes:
    """Export a self-contained, explicitly versioned selection or result bundle."""
    from rivretrieve._internal.export_bundle import encode_bundle

    return encode_bundle(value)


def from_bundle(content: bytes) -> _Selection | ObservationResult:
    """Validate and import a bundle without rebuilding identity from today's catalogue."""
    from rivretrieve._internal.export_bundle import decode_bundle

    return decode_bundle(content)


def _validate_issue_policy(on_issue: OnIssue) -> None:
    if on_issue not in ("raise", "warn", "ignore"):
        raise ValueError("on_issue must be raise, warn or ignore")


def drainage_areas(selection: _Selection) -> pl.DataFrame:
    """Read selected gauges' packaged drainage-area metadata offline.

    Parameters
    ----------
    selection : _Selection
        Selection returned by find, pick or from_bundle. Multiple providers and
        products are accepted; each provider-station pair appears once per
        source field, regardless of the number of selected products.

    Returns
    -------
    polars.DataFrame
        Columns: provider_id, station_id, source_field, source_value,
        source_dtype, source_unit (String), and state (Enum). Rows sort by
        provider, station and source field. Empty selections retain this schema.
        source_value is JSON scalar text: json.loads decodes a non-null cell
        to its original string or number. source_dtype names the native Polars
        dtype. Formatted strings, blanks and numerical values are not converted.
        source_unit preserves an already established unit, otherwise null;
        units embedded in source fields or values remain there unchanged.
        state is value, source_null (a known field holding null), or no_metadata
        (no eligible field exposed for this gauge). The latter has null source
        columns. A source_null row retains its field, dtype and established unit.

    Raises
    ------
    TypeError
        If selection is not a RivRetrieve selection.
    FatalContractError
        If the packaged projection has an invalid schema or omits a station.
    OSError
        If the packaged projection cannot be read.

    Notes
    -----
    Reads only packaged metadata, without observations, credentials or network
    access. Gauge identity does not require numeric observation admission or map
    coordinates. Coverage is limited to drainage/watershed-size fields established
    by existing repository evidence. Distinct source fields remain separate;
    no area is preferred, inferred, converted or scientifically harmonized.
    Neither absence state means zero or that an agency publishes no area
    elsewhere. See docs/drainage-areas.md for an example and field coverage.
    """
    from rivretrieve._internal.drainage_areas import DRAINAGE_AREA_SCHEMA, drainage_area_frame

    stations = _selection_station_keys(selection)
    if stations.is_empty():
        return pl.DataFrame(schema=DRAINAGE_AREA_SCHEMA)
    resource = files("rivretrieve._internal.catalogues").joinpath("drainage_areas.parquet")
    with resource.open("rb") as stream:
        metadata = pl.read_parquet(stream)
    return drainage_area_frame(stations, metadata)


def map(selection: _Selection) -> object:
    """Render selected stations without narrowing the selection.

    Parameters
    ----------
    selection : _Selection
        Selection whose stations will be shown once each.

    Returns
    -------
    folium.Map
        Station markers with identity, coordinates and CRS in their popups.
        Unknown CRS markers are orange and drawn as if EPSG:4326. Established
        CRS markers are blue. The rendering does not rewrite catalogue facts.

    Raises
    ------
    TypeError
        If selection is not a RivRetrieve selection.
    MissingOptionalDependencyError
        If folium is not installed. Install the rivretrieve[map] extra.
    """
    return StationMap(_selection_station_frame(selection)).render()


_provider_lookup = _registry.get


class EmptySelectionError(FatalContractError):
    def __init__(self, reason: _EmptyReason) -> None:
        self.reason = reason
        super().__init__(
            "fetch() cannot retrieve an empty selection: "
            f"code={reason.code!r}, provider_ids={reason.provider_ids!r}, "
            f"station_ids={reason.station_ids!r}, product_ids={reason.product_ids!r}, "
            f"published_products={reason.published_products!r}"
        )


class MultiProviderSelectionError(FatalContractError):
    def __init__(self, provider_ids: tuple[str, ...]) -> None:
        self.provider_ids = provider_ids
        super().__init__(
            f"fetch() requires one provider; selection contains providers {provider_ids!r}. "
            "Use fetch_by_provider() for multi-provider selections."
        )


def fetch(
    selection: _Selection,
    *,
    start: object = None,
    end: object = None,
    receipts: bool = False,
    cache: CacheMode = "bypass",
    on_issue: OnIssue = "warn",
) -> ObservationResult:
    """Retrieve every admitted source series matching one provider's retained request scope.

    Unrestricted intent includes response-discovered matches. Reuse serves an
    identified inventory vintage; refresh reacquires scope. Source failures remain
    inspectable alongside independent successes. Receipts retain exact parse bytes.
    """
    cache = _parse_cache_mode(cache)
    _validate_issue_policy(on_issue)
    _require_selection(selection)
    partitions = _selection_routes(selection)
    if not partitions:
        if selection.empty_reason is None:
            raise FatalContractError("Selection has no executable source scope")
        raise EmptySelectionError(selection.empty_reason)
    provider_ids = tuple(partitions)
    if len(provider_ids) != 1:
        raise MultiProviderSelectionError(provider_ids)
    routes = tuple(item for values in partitions.values() for item in values)
    normalized_start, normalized_end, future_local_date = _normalize_window(routes, start=start, end=end)
    _require_cache_mode_available(provider_ids, cache)
    credentials = _resolve_credentials(provider_ids, require_all=True)
    provider_id = provider_ids[0]
    result = _fetch_provider_series(
        provider_id,
        partitions[provider_id],
        selection=selection,
        start=normalized_start,
        end=normalized_end,
        future_local_date=future_local_date,
        credentials=credentials[provider_id],
        receipts=ReceiptMode.INCLUDE if receipts else ReceiptMode.OMIT,
        cache=cache,
        store=_resolve_store_root(provider_id, _registry.get(provider_id)._store_root),
        on_issue="ignore",
    )
    result = result.model_copy(update={"issues": (*_selection_issues_for_result(selection, result), *result.issues)})
    apply_on_issue(result.issues, on_issue)
    return result


def fetch_by_provider(
    selection: _Selection,
    *,
    start: object = None,
    end: object = None,
    receipts: bool = False,
    cache: CacheMode = "bypass",
    on_issue: OnIssue = "warn",
) -> dict[str, ObservationResult]:
    """Retrieve each provider separately, preserving its identity, source terms and outcomes."""
    cache = _parse_cache_mode(cache)
    _validate_issue_policy(on_issue)
    _require_selection(selection)
    partitions = _selection_routes(selection)
    if not partitions:
        apply_on_issue(selection.issues, on_issue)
        return {}
    routes = tuple(item for values in partitions.values() for item in values)
    normalized_start, normalized_end, future_local_date = _normalize_window(routes, start=start, end=end)
    provider_ids = tuple(partitions)
    _require_cache_mode_available(provider_ids, cache)
    credentials = _resolve_credentials(provider_ids, require_all=True)
    results = {}
    for provider_id, members in partitions.items():
        result = _fetch_provider_series(
            provider_id,
            members,
            selection=selection,
            start=normalized_start,
            end=normalized_end,
            future_local_date=future_local_date,
            credentials=credentials[provider_id],
            receipts=ReceiptMode.INCLUDE if receipts else ReceiptMode.OMIT,
            cache=cache,
            store=_resolve_store_root(provider_id, _registry.get(provider_id)._store_root),
            on_issue="ignore",
        )
        results[provider_id] = result.model_copy(
            update={"issues": (*_selection_issues_for_result(selection, result), *result.issues)}
        )
    apply_on_issue(tuple(issue for result in results.values() for issue in result.issues), on_issue)
    return results


def _selection_issues_for_result(selection: _Selection, result: ObservationResult) -> tuple[Issue, ...]:
    """Retain discovery diagnostics without reporting a settled uncertainty as a new failure."""
    settled = any(selection.scope.matches(item) for item in result.source_series) or any(
        item.status.value == "no_match" for item in result.outcomes
    )
    return tuple(
        issue.model_copy(
            update={
                "severity": "info",
                "code": "selection.inventory_resolved",
                "message": "The explicit source restriction was unresolved during offline discovery and was settled by acquisition.",
                "details": {"discovery_issue": issue.model_dump(mode="json")},
            }
        )
        if settled and issue.code == "selection.unresolved_inventory"
        else issue
        for issue in selection.issues
    )


def _selection_routes(selection: _Selection) -> dict[str, tuple[SourceSeries, ...]]:
    from rivretrieve._internal.source_series import RestrictionKind, ScopeState

    if selection.scope.state is ScopeState.EMPTY:
        return {}
    # Physical and station scope route acquisition. Explicit response-owned IDs may
    # be absent from the catalogue and therefore cannot remove their acquisition route.
    route_scope = selection.scope.model_copy(
        update={"restriction": RestrictionKind.ALL, "variants": (), "series_ids": ()}
    )
    candidates = tuple(item for item in selection.known_series if route_scope.matches(item))
    if selection.scope.restriction is RestrictionKind.EXPLICIT:
        identities_resolved = all(
            any(item.series_id == identifier for item in candidates) for identifier in selection.scope.series_ids
        ) and all(
            any(item.variant == variant or item.identity.published_id == variant for item in candidates)
            for variant in selection.scope.variants
        )
        if identities_resolved:
            candidates = tuple(item for item in candidates if selection.scope.matches(item))
    return _partition_by_provider(candidates)


def _normalize_window(
    series: tuple[SourceSeries, ...],
    *,
    start: object,
    end: object,
) -> tuple[datetime, datetime, date | None]:
    """public window normalization : InputEndpoints × LocalDate → RequestedWindow × FutureFlag."""
    local_date = date.today()
    normalized_end_input = local_date.isoformat() if end is None else end
    representative = series[0]
    request = ObservationRequest.from_inputs(
        provider_id=representative.provider_id,
        stations=(representative.station_id,),
        products=(representative.product_id,),
        start=start,
        end=normalized_end_input,
    )
    local_day_end = datetime.combine(local_date, time.max)
    future_local_date = local_date if datetime.fromisoformat(request.end.isoformat()) > local_day_end else None
    return (
        datetime.fromisoformat(request.start.isoformat()),
        datetime.fromisoformat(request.end.isoformat()),
        future_local_date,
    )


def _parse_cache_mode(value: object) -> CacheMode:
    if not isinstance(value, str) or value not in ("bypass", "reuse", "refresh"):
        raise ValueError("cache must be 'bypass', 'reuse', or 'refresh'")
    return cast(CacheMode, value)


def _require_cache_mode_available(provider_ids: tuple[str, ...], cache: CacheMode) -> None:
    if cache == "refresh":
        for provider_id in provider_ids:
            if _registry.get(provider_id)._store_config is not None:
                raise FatalContractError(
                    f"Provider {provider_id} uses a compiled store; refresh requires "
                    f'rivretrieve.download("{provider_id}"). No transfer was started.'
                )


def _resolve_store_root(provider_id: str, registered: StoreRoot | None) -> StoreRoot:
    """store location : ProviderId × RegisteredStore × Environment × WorkingDotenv → StoreRoot."""
    name = "RIVRETRIEVE_CACHE_DIR"
    dotenv = dotenv_values(Path.cwd() / ".env")
    value = os.environ[name] if name in os.environ else dotenv.get(name)
    if value is not None:
        if not value.strip():
            raise ValueError("RIVRETRIEVE_CACHE_DIR must name a non-empty cache directory")
        root = Path(value).expanduser().absolute()
        return StoreRoot(root / provider_id / "store")
    if registered is not None:
        return registered
    return StoreRoot(Path(user_cache_dir("rivretrieve")) / provider_id / "store")


def _resolve_credentials(
    provider_ids: tuple[str, ...] | list[str],
    *,
    require_all: bool,
) -> dict[str, dict[str, str]]:
    """credential resolution : ProviderDeclarations × Environment × WorkingDotenv → ProviderCredentialValues."""
    dotenv = dotenv_values(Path.cwd() / ".env")
    resolved: dict[str, dict[str, str]] = {}
    missing: dict[str, tuple[str, ...]] = {}
    for provider_id in provider_ids:
        names = _registry.get(provider_id).required_credentials
        provider_values: dict[str, str] = {}
        for name in names:
            environment_value = os.environ.get(name)
            file_value = dotenv.get(name)
            value: str | None = None
            if name in os.environ:
                if environment_value is not None and environment_value.strip():
                    value = environment_value
            elif isinstance(file_value, str) and file_value.strip():
                value = file_value
            if value is not None:
                provider_values[name] = value
        resolved[provider_id] = provider_values
        absent = tuple(name for name in names if name not in provider_values)
        if absent:
            missing[provider_id] = absent
    if require_all and missing:
        raise MissingCredentialError(missing)
    return resolved


def _credentialed_transport(provider_id: str, values: dict[str, str]) -> Transport:
    """credential transport : ProviderCredentialValues × (HeaderBindings | CredentialExchangeBinding) → Transport."""
    base = HttpClient()
    handle = _registry.get(provider_id)
    exchange = handle.credential_exchange
    if exchange is not None:
        return CredentialExchangeTransport(
            base,
            tuple(
                CredentialHeader(binding.header, values[binding.variable], binding.origins)
                for binding in exchange.credential_headers
            ),
            exchange.spec,
            _SystemClock(),
        )
    bindings = handle.credential_headers
    if not bindings:
        return base
    return AuthenticatedTransport(
        base,
        tuple(CredentialHeader(binding.header, values[binding.variable], binding.origins) for binding in bindings),
    )


def _partition_by_provider(series: tuple[SourceSeries, ...]) -> dict[str, tuple[SourceSeries, ...]]:
    partitions: dict[str, list[SourceSeries]] = {}
    for selected_series in series:
        partitions.setdefault(selected_series.provider_id, []).append(selected_series)
    return {provider_id: tuple(rows) for provider_id, rows in partitions.items()}


def _fetch_provider_series(
    provider_id: str,
    series: tuple[SourceSeries, ...],
    *,
    selection: _Selection,
    start: datetime,
    end: datetime,
    future_local_date: date | None,
    credentials: dict[str, str],
    receipts: ReceiptMode,
    cache: CacheMode,
    store: StoreRoot,
    on_issue: OnIssue,
) -> ObservationResult:
    handle = _provider_lookup(provider_id)
    by_station: dict[str, list[str]] = {}
    for selected_series in series:
        product_ids = by_station.setdefault(selected_series.station_id, [])
        if selected_series.product_id not in product_ids:
            product_ids.append(selected_series.product_id)
    transport = _credentialed_transport(provider_id, credentials)
    results = tuple(
        handle.observations(
            stations=station_id,
            products=tuple(product_ids),
            start=start,
            end=end,
            on_issue="ignore",
            receipts=receipts,
            transport=transport,
            cache=cache,
            store=store,
            scope=selection.scope.model_copy(update={"provider_ids": (provider_id,)}),
            known_series=tuple(item for item in selection.known_series if item.provider_id == provider_id),
            inventories=tuple(
                item
                for item in selection.inventories
                if not item.scope.provider_ids or provider_id in item.scope.provider_ids
            ),
        )
        for station_id, product_ids in by_station.items()
    )
    result = _merge_provider_results(results, series)
    if future_local_date is not None:
        future_issue = Issue(
            severity="info",
            code="request.future_end",
            message=(
                f"Requested window for provider {provider_id} extends past the caller's local date "
                f"{future_local_date.isoformat()}; the requested end was kept unchanged."
            ),
            details={"requested_end": end.isoformat(), "local_date": future_local_date.isoformat()},
            provider_id=handle.provider_id,
        )
        result = result.model_copy(update={"issues": (*result.issues, future_issue)})
    apply_on_issue(result.issues, on_issue)
    return result


def _merge_provider_results(
    results: tuple[ObservationResult, ...],
    series: tuple[SourceSeries, ...],
) -> ObservationResult:
    """provider result merge : NonEmptyTuple[ObservationResult] × SelectedSeries → ObservationResult"""
    if not results:
        raise FatalContractError("Provider result merge requires at least one result")

    first = results[0]
    request = first.provenance.request
    if request is None or "start" not in request or "end" not in request:
        raise FatalContractError("Observation provenance must retain the normalized requested window")
    merged_request = {
        "scope": first.scope.model_dump(mode="json"),
        "series": [
            {
                "station_id": selected_series.station_id,
                "product_id": selected_series.product_id,
                "series_id": selected_series.series_id,
            }
            for selected_series in series
        ],
        "start": request["start"],
        "end": request["end"],
    }
    issues = _merge_provider_issues(results)
    receipt_entries = tuple(entry for result in results for entry in result.receipts.entries)
    calls_made = tuple(call for result in results for call in result.provenance.calls_made)
    endpoints = tuple(dict.fromkeys(endpoint for result in results for endpoint in result.provenance.endpoints))
    retrieved = tuple(
        result.provenance.retrieved_at for result in results if result.provenance.retrieved_at is not None
    )
    queries: list[dict[str, object]] = []
    for result in results:
        query = result.provenance.query
        if query is not None and query not in queries:
            queries.append(query)
    merged_query = None if not queries else queries[0] if len(queries) == 1 else {"calls": tuple(queries)}
    return ObservationResult(
        data=_canonical_observation_order(pl.concat([result.data for result in results])),
        source_series=_merge_series_definitions(results),
        inventories=tuple({item.snapshot_id: item for result in results for item in result.inventories}.values()),
        outcomes=tuple({item.outcome_id: item for result in results for item in result.outcomes}.values()),
        scope=first.scope,
        provenance=first.provenance.model_copy(
            update={
                "request": merged_request,
                "calls_made": calls_made,
                "served_intervals": tuple(
                    interval for result in results for interval in result.provenance.served_intervals
                ),
                "endpoints": endpoints,
                "retrieved_at": max(retrieved) if retrieved else None,
                "query": merged_query,
                "time_windows": tuple(window for result in results for window in result.provenance.time_windows),
                "decomposition": tuple(
                    dict.fromkeys(value for result in results for value in result.provenance.decomposition)
                ),
            }
        ),
        issues=issues,
        receipts=Receipts(provider_id=first.provenance.provider_id, entries=receipt_entries),
    )


def _merge_series_definitions(results: tuple[ObservationResult, ...]) -> tuple[SourceSeries, ...]:
    definitions: dict[str, SourceSeries] = {}
    for result in results:
        for item in result.source_series:
            existing = definitions.get(item.series_id)
            if existing is None:
                definitions[item.series_id] = item
                continue
            if existing.model_dump(exclude={"facts"}) != item.model_dump(exclude={"facts"}):
                raise FatalContractError("Source-series identity changed while merging result partitions")
            facts = {fact.facts_id: fact for fact in existing.facts}
            for fact in item.facts:
                if fact.facts_id in facts and facts[fact.facts_id] != fact:
                    raise FatalContractError("Physical facts changed under the same fact-segment identity")
                facts[fact.facts_id] = fact
            definitions[item.series_id] = item.model_copy(update={"facts": tuple(facts.values())})
    return tuple(definitions.values())


def _canonical_observation_order(data: pl.DataFrame) -> pl.DataFrame:
    """canonical observation order : ObservationData → ObservationData (pure)."""
    return data.sort(
        ["station_id", "product_id", "series_id", "facts_id", "time", "time_zone", "value"], maintain_order=True
    )


def _merge_provider_issues(results: tuple[ObservationResult, ...]) -> tuple[Issue, ...]:
    merged: list[Issue] = []
    provider_provenance_issues: list[Issue] = []
    for result in results:
        for issue in result.issues:
            if issue.code.startswith("provenance."):
                if issue not in provider_provenance_issues:
                    provider_provenance_issues.append(issue)
                    merged.append(issue)
            else:
                merged.append(issue)
    return tuple(merged)


def products(provider: str | None = None) -> list[str]:
    """Inspect source access-coordinate names recorded in packaged catalogues.

    These internal routing names do not establish physical meaning. They are not
    accepted by find or pick; use quantity and established physical facts there.

    Parameters
    ----------
    provider : str or None, default None
        Registered provider identifier. None includes every provider.

    Returns
    -------
    list[str]
        Sorted, unique access-coordinate names. Neither a name nor its wording
        establishes a series statistic, temporal support or current availability.

    Raises
    ------
    UnknownProviderError
        If provider is not registered.
    FatalContractError
        If a shipped declaration or catalogue is invalid.
    """
    _ensure_default_providers_registered()
    provider_ids = _registry.list_provider_ids()
    if provider is not None and provider not in provider_ids:
        raise UnknownProviderError(provider)
    selected_provider_ids = set(provider_ids if provider is None else [provider])
    return sorted(
        {
            product_id
            for record in _registry.iter_records()
            if record.provider_id in selected_provider_ids
            for product_id in CatalogueReader(record.artifact, record.provider_id)
            .read_products()
            .data["product_id"]
            .to_list()
        }
    )


_DEFAULT_REGISTRATION_GENERATION: int | None = None


def _ensure_default_providers_registered() -> None:
    """Register the built-in manifest once for the registry's current lifetime."""
    global _DEFAULT_REGISTRATION_GENERATION

    if not _DEFAULT_PROVIDER_REGISTRATION_ENABLED:
        return
    if _registry.clear_generation == _DEFAULT_REGISTRATION_GENERATION:
        return

    from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS
    from rivretrieve._internal.providers.registration import register_manifest

    register_manifest(_registry, BUILTIN_PROVIDER_IDS)
    _DEFAULT_REGISTRATION_GENERATION = _registry.clear_generation


def download(provider: str):
    """Explicitly download and compile one bulk provider into the local cache.

    Parameters
    ----------
    provider : str
        Registered bulk provider identifier. Calling this function is consent
        to transfer the publisher artifacts and compile them locally.

    Returns
    -------
    ValidatedStore
        Validated compiled store with its root, manifest and partition paths.
        Successful certification replaces the previous store and deletes the
        downloaded publisher artifacts. Their identities remain in the manifest.

    Raises
    ------
    TypeError
        If provider is not a nonempty string.
    UnknownProviderError
        If provider is not registered.
    BulkOperationsUnavailableError
        If provider is not a bulk provider.
    InsufficientDiskSpaceError
        If free space is below the declared requirement before any transfer.
    FatalContractError
        If a source response or store validation violates a contract.
    StoreCertificationError
        If compilation certification fails before publication.
    StorePostCommitCleanupError
        If publication succeeded but cleanup left residue. The new store remains
        authoritative and the exception names the residue.
    OSError
        If local file operations fail.

    Notes
    -----
    This call can transfer a national dataset. It is not needed for live
    providers. Before publication, a failed compilation preserves the previous
    store and publisher inputs. Use clear_cache explicitly for recovery.
    Transport failures can also propagate rather than becoming result issues.
    """
    from rivretrieve._internal.bulk import download as bulk_download

    return bulk_download(provider)


def cache_status(provider: str):
    """Inspect one provider's local observation store without source access.

    Parameters
    ----------
    provider : str
        Registered provider identifier, for a live or bulk store.

    Returns
    -------
    StoreStatus
        Resolved path, presence, validated manifest and bytes on disk. Properties
        expose format version, partition row counts, bulk source identity and
        accumulated coverage where applicable. An absent store has no manifest,
        zero bytes and empty coverage. Coverage is retrieval history, not continuity.

    Raises
    ------
    TypeError
        If provider is not a nonempty string.
    UnknownProviderError
        If provider is not registered.
    ObservationStoreRefusedError
        If an existing store is invalid or interrupted publication needs recovery.
    OSError
        If local file operations fail.
    """
    from rivretrieve._internal.bulk import cache_status as bulk_cache_status

    return bulk_cache_status(provider)


def clear_cache(provider: str):
    """Delete one provider's compiled observation store or accumulated live store.

    Parameters
    ----------
    provider : str
        Registered provider identifier. This call is explicit destructive consent.

    Returns
    -------
    CacheClearResult
        Provider identifier, store path, whether anything existed, total bytes
        removed and every removed path. Includes recognized pending publisher
        downloads and accumulated-write staging or backup directories.

    Raises
    ------
    TypeError
        If provider is not a nonempty string.
    UnknownProviderError
        If provider is not registered.
    BulkArtifactCleanupRefusedError
        If the pending-download namespace is symlinked or contains an unsafe entry.
    OSError
        If deletion fails. This operation is not transactional.

    Notes
    -----
    This destructive action also removes preserved pending publisher downloads
    and accumulated-write staging or backup directories, allowing a retry after
    interrupted retrieval or failed compilation. It does not download replacement
    data. It removes symlinks themselves rather than following them.
    Unrelated sibling paths are not removed.
    """
    from rivretrieve._internal.bulk import clear_cache as bulk_clear_cache

    return bulk_clear_cache(provider)
