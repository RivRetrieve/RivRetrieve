"""public retrieval : Selection × WindowInputs × CredentialSources → ObservationResult(s); provider discovery : ProviderDeclarations × CredentialSources → ProviderAccessFrame."""

from __future__ import annotations

import os
from datetime import date, datetime, time
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
from dotenv import dotenv_values

from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.issues import FatalContractError, Issue, MissingCredentialError, apply_on_issue
from rivretrieve._internal.observations import ObservationRequest, ObservationResult, ReceiptMode, Receipts
from rivretrieve._internal.registry import UnknownProviderError, _registry
from rivretrieve._internal.selection import _as_frame as _selection_as_frame
from rivretrieve._internal.selection import _EmptyReason, _require_selection, _Selection, _Series
from rivretrieve._internal.selection import _find as _selection_find
from rivretrieve._internal.selection import _from_frame as _selection_from_frame
from rivretrieve._internal.selection import _pick as _selection_pick
from rivretrieve._internal.selection import _station_frame as _selection_station_frame
from rivretrieve._internal.station_map import StationMap
from rivretrieve._internal.transport import AuthenticatedTransport, CredentialHeader, HttpClient, Transport

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rivretrieve._internal.primitives import OnIssue

_DEFAULT_PROVIDER_REGISTRATION_ENABLED = True


def providers() -> pl.DataFrame:
    """providers : BuiltInProviderDeclarations × CredentialSources → ProviderAccessFrame."""
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
    _ensure_default_providers_registered()
    return _selection_find(_registry.iter_records(), provider=provider, station=station, product=product)


def pick(
    selection: _Selection,
    *,
    provider: str | Sequence[str] | None = None,
    station: str | Sequence[str] | None = None,
    product: str | Sequence[str] | None = None,
) -> _Selection:
    _ensure_default_providers_registered()
    return _selection_pick(_registry.iter_records(), selection, provider=provider, station=station, product=product)


def as_frame(selection: _Selection) -> pl.DataFrame:
    return _selection_as_frame(selection)


def from_frame(frame: pl.DataFrame) -> _Selection:
    _ensure_default_providers_registered()
    return _selection_from_frame(_registry.iter_records(), frame)


def map(selection: _Selection) -> object:
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
    on_issue: OnIssue = "warn",
) -> ObservationResult:
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
        on_issue=on_issue,
    )


def fetch_by_provider(
    selection: _Selection,
    *,
    start: object = None,
    end: object = None,
    receipts: bool = False,
    on_issue: OnIssue = "warn",
) -> dict[str, ObservationResult]:
    _require_selection(selection)
    partitions = _partition_by_provider(selection.series)
    if not partitions:
        return {}
    normalized_start, normalized_end, future_local_date = _normalize_window(selection.series, start=start, end=end)
    provider_ids = tuple(partitions)
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
    """credential transport : ProviderCredentialValues × HeaderBindings → Transport."""
    base = HttpClient()
    bindings = _registry.get(provider_id).credential_headers
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
    """products : PackagedProductCatalogues × (ProviderId ∪ {None}) → list[ProductId]."""
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
    """Download and compile observations for one bulk provider by explicit consent."""
    from rivretrieve._internal.bulk import download as bulk_download

    return bulk_download(provider)


def cache_status(provider: str):
    """Return the local compiled-store status for one bulk provider."""
    from rivretrieve._internal.bulk import cache_status as bulk_cache_status

    return bulk_cache_status(provider)


def clear_cache(provider: str):
    """Delete the compiled observation store and preserved pending publisher downloads.

    Use this explicit destructive recovery action to permit a retry after failed bulk compilation.
    """
    from rivretrieve._internal.bulk import clear_cache as bulk_clear_cache

    return bulk_clear_cache(provider)
