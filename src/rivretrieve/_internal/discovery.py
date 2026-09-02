from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.issues import FatalContractError, Issue, apply_on_issue
from rivretrieve._internal.observations import ObservationResult, ReceiptMode, Receipts
from rivretrieve._internal.registry import UnknownProviderError, _registry
from rivretrieve._internal.selection import _as_frame as _selection_as_frame
from rivretrieve._internal.selection import _EmptyReason, _require_selection, _Selection, _Series
from rivretrieve._internal.selection import _find as _selection_find
from rivretrieve._internal.selection import _from_frame as _selection_from_frame
from rivretrieve._internal.selection import _pick as _selection_pick
from rivretrieve._internal.selection import _station_frame as _selection_station_frame
from rivretrieve._internal.station_map import StationMap

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rivretrieve._internal.primitives import OnIssue

_DEFAULT_PROVIDER_REGISTRATION_ENABLED = True


def providers() -> list[str]:
    _ensure_default_providers_registered()
    return _registry.list_provider_ids()


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
    start: object,
    end: object,
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

    provider_id = provider_ids[0]
    receipt_mode = ReceiptMode.INCLUDE if receipts else ReceiptMode.OMIT
    return _fetch_provider_series(
        provider_id,
        partitions[provider_id],
        start=start,
        end=end,
        receipts=receipt_mode,
        on_issue=on_issue,
    )


def fetch_by_provider(
    selection: _Selection,
    *,
    start: object,
    end: object,
    receipts: bool = False,
    on_issue: OnIssue = "warn",
) -> dict[str, ObservationResult]:
    _require_selection(selection)
    partitions = _partition_by_provider(selection.series)
    receipt_mode = ReceiptMode.INCLUDE if receipts else ReceiptMode.OMIT
    return {
        provider_id: _fetch_provider_series(
            provider_id,
            series,
            start=start,
            end=end,
            receipts=receipt_mode,
            on_issue=on_issue,
        )
        for provider_id, series in partitions.items()
    }


def _partition_by_provider(series: tuple[_Series, ...]) -> dict[str, tuple[_Series, ...]]:
    partitions: dict[str, list[_Series]] = {}
    for selected_series in series:
        partitions.setdefault(selected_series.provider_id, []).append(selected_series)
    return {provider_id: tuple(rows) for provider_id, rows in partitions.items()}


def _fetch_provider_series(
    provider_id: str,
    series: tuple[_Series, ...],
    *,
    start: object,
    end: object,
    receipts: ReceiptMode,
    on_issue: OnIssue,
) -> ObservationResult:
    handle = _provider_lookup(provider_id)
    by_station: dict[str, list[str]] = {}
    for selected_series in series:
        by_station.setdefault(selected_series.station_id, []).append(selected_series.product_id)
    results = tuple(
        handle.observations(
            stations=station_id,
            products=tuple(product_ids),
            start=start,
            end=end,
            on_issue="ignore",
            receipts=receipts,
        )
        for station_id, product_ids in by_station.items()
    )
    result = _merge_provider_results(results, series)
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
    return ObservationResult(
        data=_canonical_observation_order(pl.concat([result.data for result in results])),
        provenance=first.provenance.model_copy(update={"request": merged_request}),
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
    """Delete the compiled observation store for one bulk provider."""
    from rivretrieve._internal.bulk import clear_cache as bulk_clear_cache

    return bulk_clear_cache(provider)
