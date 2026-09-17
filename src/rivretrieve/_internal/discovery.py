"""public retrieval : Selection × WindowInputs × CacheMode × CredentialSources → ObservationResult(s); provider discovery : ProviderDeclarations × CredentialSources → ProviderAccessFrame."""

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
from rivretrieve._internal.selection import _EmptyReason, _require_selection, _Selection, _Series
from rivretrieve._internal.selection import _find as _selection_find
from rivretrieve._internal.selection import _from_frame as _selection_from_frame
from rivretrieve._internal.selection import _pick as _selection_pick
from rivretrieve._internal.selection import _station_frame as _selection_station_frame
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
    product: str | None = None,
) -> _Selection:
    """Select station-product series from packaged catalogues.

    Parameters
    ----------
    provider : str or None, default None
        Exact provider identifier. None includes every provider.
    station : str or None, default None
        Exact station identifier, including leading zeros. With provider=None,
        the same identifier can select stations from several providers.
    product : str or None, default None
        Exact canonical product identifier. None includes every product.

    Returns
    -------
    _Selection
        Immutable, sorted, unique (provider_id, station_id, product_id) series
        with catalogue metadata and acquisition evidence. Available and unknown
        availability remain selectable. Unavailable pairs are excluded. A valid
        query without a selectable pair returns an empty selection with a reason.

    Raises
    ------
    UnknownProviderError
        If provider is not registered.
    UnknownStationError
        If station is absent from the requested provider scope.
    UnknownProductError
        If product is absent from the global vocabulary.
    FatalContractError
        If shipped catalogue contracts fail.
    """
    _ensure_default_providers_registered()
    return _selection_find(_registry.iter_records(), provider=provider, station=station, product=product)


def pick(
    selection: _Selection,
    *,
    provider: str | Sequence[str] | None = None,
    station: str | Sequence[str] | None = None,
    product: str | Sequence[str] | None = None,
) -> _Selection:
    """Narrow an existing selection without changing it.

    Parameters
    ----------
    selection : _Selection
        Selection returned by find, pick or from_frame.
    provider : str, sequence of str or None, default None
        Provider identifiers to retain. None or an empty sequence adds no filter.
    station : str, sequence of str or None, default None
        Station identifiers to retain. Provider scopes vocabulary validation.
        None or an empty sequence adds no filter.
    product : str, sequence of str or None, default None
        Product identifiers to retain. None or an empty sequence adds no filter.

    Returns
    -------
    _Selection
        Intersection of the selection with the requested identifiers. A new
        empty answer carries not_in_selection. An already empty selection
        keeps its original reason.

    Raises
    ------
    TypeError
        If selection is not a RivRetrieve selection.
    UnknownProviderError, UnknownStationError, UnknownProductError
        If an identifier is outside catalogue vocabulary, even when the input
        selection is empty.
    FatalContractError
        If shipped catalogue contracts fail.
    """
    _ensure_default_providers_registered()
    return _selection_pick(_registry.iter_records(), selection, provider=provider, station=station, product=product)


def as_frame(selection: _Selection) -> pl.DataFrame:
    """Copy a selection into a Polars frame for inspection or filtering.

    Parameters
    ----------
    selection : _Selection
        Selection returned by find, pick or from_frame.

    Returns
    -------
    polars.DataFrame
        One row per series in SELECTION_FRAME_SCHEMA order. Identity, geometry,
        product semantics, canonical unit, native product identifier, availability,
        published record dates and catalogue check date travel together. Empty
        selections retain the schema. Acquisition evidence and the empty reason
        stay on selection rather than becoming frame columns.

    Raises
    ------
    TypeError
        If selection is not a RivRetrieve selection.
    """
    return _selection_as_frame(selection)


def from_frame(frame: pl.DataFrame) -> _Selection:
    """Rebuild a selection from frame identities and packaged catalogue facts.

    Parameters
    ----------
    frame : polars.DataFrame
        Contains provider_id, station_id and product_id String columns in that
        relative order. Identities must be non-null and unique. Other columns
        are ignored, including caller-edited catalogue metadata.

    Returns
    -------
    _Selection
        Sorted series with current packaged metadata and acquisition evidence.
        An empty identity frame produces the empty_frame reason.

    Raises
    ------
    TypeError
        If frame is not a Polars DataFrame.
    UnknownProviderError, UnknownStationError, UnknownProductError
        If an identity is outside catalogue vocabulary.
    FatalContractError
        If columns, dtypes, nulls or duplicates violate the identity contract,
        or a triple has no selectable catalogue pair.
    """
    _ensure_default_providers_registered()
    return _selection_from_frame(_registry.iter_records(), frame)


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
    """Retrieve selected observations from one provider.

    Parameters
    ----------
    selection : _Selection
        Series to retrieve. fetch requires a nonempty selection from one provider.
    start : str or datetime, default None
        Required naive wall-clock endpoint in each source calendar. ISO date
        strings begin at midnight. None and datetime.date objects are refused.
    end : str, datetime or None, default None
        Inclusive naive wall-clock endpoint. A bare ISO date includes that whole
        date. None uses the caller machine's local date through its last instant.
        A future end stays unchanged and adds one informational issue per provider.
    receipts : bool, default False
        Retain publisher payloads and store excerpts when True. Otherwise the
        returned receipts.entries tuple is empty.
    cache : {"bypass", "reuse", "refresh"}, default "bypass"
        For live providers, bypass leaves the cache untouched, reuse serves held
        coverage and fetches the remainder, and refresh replaces the requested
        interval after successful retrieval. Bulk providers always read their
        compiled store. They accept bypass and reuse, but refuse refresh.
    on_issue : {"warn", "raise", "ignore"}, default "warn"
        Handling for warning and error issues. Warn emits RuntimeWarning and
        returns results. Raise raises IssuePolicyError. Ignore suppresses
        notifications, not retained issues. Info does not activate this policy.

    Returns
    -------
    ObservationResult
        Five-column observation frame with native wall-clock time, per-row zone,
        station_id, product_id and canonical value. Provenance, issues and optional
        receipts accompany it. Source failures can yield partial or empty data
        with issues. Successful retrieval does not establish continuous coverage.

    Raises
    ------
    EmptySelectionError
        If the selection is empty. The exception carries its reason.
    MultiProviderSelectionError
        If the selection contains more than one provider.
    TypeError
        If selection is not a RivRetrieve selection.
    ValueError
        If cache is not one of the supported modes.
    InvalidObservationRequestError
        If start is omitted, an endpoint is invalid or zone-aware, or start > end.
    MissingCredentialError
        If a selected provider lacks required credentials before source access.
    ObservationsUnavailableError
        If a provider has no observation stages.
    ObservationStoreRefusedError
        If an existing store cannot be validated.
    IssuePolicyError
        If on_issue="raise" and results carry warning or error issues.
    FatalContractError
        If a stage contract fails or refresh is requested for a bulk provider.
        These errors are independent of on_issue.

    Notes
    -----
    Daily products clip on native calendar dates. Other products clip on their
    wall-clock labels. The engine pads source requests by two days at each end
    and clips returned rows to the requested window. Unit conversion does not
    compute a new hydrological product. Supplied credentials come from the
    process environment or working directory .env file, not function arguments.
    A missing compiled store returns an empty frame with bulk.store_missing,
    a warning issue. No implicit download starts.
    """
    cache = _parse_cache_mode(cache)
    _require_selection(selection)
    if not selection.series:
        reason = selection.empty_reason
        if reason is None:
            raise FatalContractError("Empty selection has no retained reason")
        raise EmptySelectionError(reason)

    partitions = _partition_by_provider(selection.series)
    provider_ids = tuple(partitions)
    if len(provider_ids) != 1:
        raise MultiProviderSelectionError(provider_ids)

    normalized_start, normalized_end, future_local_date = _normalize_window(selection.series, start=start, end=end)
    _require_cache_mode_available(provider_ids, cache)
    credential_values = _resolve_credentials(provider_ids, require_all=True)
    provider_id = provider_ids[0]
    receipt_mode = ReceiptMode.INCLUDE if receipts else ReceiptMode.OMIT
    return _fetch_provider_series(
        provider_id,
        partitions[provider_id],
        start=normalized_start,
        end=normalized_end,
        future_local_date=future_local_date,
        credentials=credential_values[provider_id],
        receipts=receipt_mode,
        cache=cache,
        store=_resolve_store_root(provider_id, _registry.get(provider_id)._store_root),
        on_issue=on_issue,
    )


def fetch_by_provider(
    selection: _Selection,
    *,
    start: object = None,
    end: object = None,
    receipts: bool = False,
    cache: CacheMode = "bypass",
    on_issue: OnIssue = "warn",
) -> dict[str, ObservationResult]:
    """Retrieve a selection as separate results keyed by provider.

    Parameters
    ----------
    selection : _Selection
        Series to retrieve from zero or more providers.
    start : str or datetime, default None
        Required naive wall-clock endpoint in each source calendar. ISO date
        strings begin at midnight. None and datetime.date objects are refused.
    end : str, datetime or None, default None
        Inclusive naive wall-clock endpoint. A bare ISO date includes that whole
        date. None uses the caller machine's local date through its last instant.
        A future end stays unchanged and adds one informational issue per provider.
    receipts : bool, default False
        Retain publisher payloads and store excerpts when True. Otherwise the
        returned receipts.entries tuple is empty.
    cache : {"bypass", "reuse", "refresh"}, default "bypass"
        For live providers, bypass leaves the cache untouched, reuse serves held
        coverage and fetches the remainder, and refresh replaces the requested
        interval after successful retrieval. Bulk providers always read their
        compiled store. They accept bypass and reuse, but refuse refresh.
    on_issue : {"warn", "raise", "ignore"}, default "warn"
        Handling for warning and error issues. Warn emits RuntimeWarning and
        returns results. Raise raises IssuePolicyError. Ignore suppresses
        notifications, not retained issues. Info does not activate this policy.

    Returns
    -------
    dict[str, ObservationResult]
        One result per selected provider, in provider-id order. An empty
        selection returns {} without validating its window or credentials.
        Each result uses the same schema and semantics as fetch.

    Raises
    ------
    TypeError
        If selection is not a RivRetrieve selection.
    ValueError
        If cache is not one of the supported modes.
    InvalidObservationRequestError
        If start is omitted, an endpoint is invalid or zone-aware, or start > end.
    MissingCredentialError
        If a selected provider lacks required credentials before source access.
    ObservationsUnavailableError
        If a provider has no observation stages.
    ObservationStoreRefusedError
        If an existing store cannot be validated.
    IssuePolicyError
        If on_issue="raise" and results carry warning or error issues.
    FatalContractError
        If a stage contract fails or refresh is requested for a bulk provider.
        These errors are independent of on_issue.

    Notes
    -----
    Credentials are checked for all selected providers before retrieval.
    The issue policy runs after all provider results have been assembled.
    A fatal contract error still aborts the call. This function does not
    merge provider frames, whose station identifiers need not be globally unique.
    """
    cache = _parse_cache_mode(cache)
    _require_selection(selection)
    partitions = _partition_by_provider(selection.series)
    if not partitions:
        return {}
    normalized_start, normalized_end, future_local_date = _normalize_window(selection.series, start=start, end=end)
    provider_ids = tuple(partitions)
    _require_cache_mode_available(provider_ids, cache)
    credential_values = _resolve_credentials(provider_ids, require_all=True)
    receipt_mode = ReceiptMode.INCLUDE if receipts else ReceiptMode.OMIT
    results = {
        provider_id: _fetch_provider_series(
            provider_id,
            series,
            start=normalized_start,
            end=normalized_end,
            future_local_date=future_local_date,
            credentials=credential_values[provider_id],
            receipts=receipt_mode,
            cache=cache,
            store=_resolve_store_root(provider_id, _registry.get(provider_id)._store_root),
            on_issue="ignore",
        )
        for provider_id, series in partitions.items()
    }
    apply_on_issue(
        tuple(issue for result in results.values() for issue in result.issues),
        on_issue,
    )
    return results


def _normalize_window(
    series: tuple[_Series, ...],
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


def _partition_by_provider(series: tuple[_Series, ...]) -> dict[str, tuple[_Series, ...]]:
    partitions: dict[str, list[_Series]] = {}
    for selected_series in series:
        partitions.setdefault(selected_series.provider_id, []).append(selected_series)
    return {provider_id: tuple(rows) for provider_id, rows in partitions.items()}


def _fetch_provider_series(
    provider_id: str,
    series: tuple[_Series, ...],
    *,
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
        by_station.setdefault(selected_series.station_id, []).append(selected_series.product_id)
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
    series: tuple[_Series, ...],
) -> ObservationResult:
    """provider result merge : NonEmptyTuple[ObservationResult] × SelectedSeries → ObservationResult"""
    if not results:
        raise FatalContractError("Provider result merge requires at least one result")

    first = results[0]
    request = first.provenance.request
    if request is None or "start" not in request or "end" not in request:
        raise FatalContractError("Observation provenance must retain the normalized requested window")
    merged_request = {
        "series": [
            {"station_id": selected_series.station_id, "product_id": selected_series.product_id}
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


def _canonical_observation_order(data: pl.DataFrame) -> pl.DataFrame:
    """canonical observation order : ObservationData → ObservationData (pure)."""
    return data.sort(["station_id", "product_id", "time", "time_zone", "value"], maintain_order=True)


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
    """List canonical product identifiers from packaged catalogues.

    Parameters
    ----------
    provider : str or None, default None
        Registered provider identifier. None includes every provider.

    Returns
    -------
    list[str]
        Sorted, unique product identifiers. These are catalogue vocabulary,
        not a guarantee that every station offers each product.

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
