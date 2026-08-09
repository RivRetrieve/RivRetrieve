from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.issues import FatalContractError, Issue, apply_on_issue
from rivretrieve._internal.observations import ObservationResult, RawMode, RawPayload
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
    raw: bool = False,
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
    raw_mode = RawMode.INCLUDE if raw else RawMode.OMIT
    return _fetch_provider_series(
        provider_id,
        partitions[provider_id],
        start=start,
        end=end,
        raw=raw_mode,
        on_issue=on_issue,
    )


def fetch_by_provider(
    selection: _Selection,
    *,
    start: object,
    end: object,
    raw: bool = False,
    on_issue: OnIssue = "warn",
) -> dict[str, ObservationResult]:
    _require_selection(selection)
    partitions = _partition_by_provider(selection.series)
    raw_mode = RawMode.INCLUDE if raw else RawMode.OMIT
    return {
        provider_id: _fetch_provider_series(
            provider_id,
            series,
            start=start,
            end=end,
            raw=raw_mode,
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
    raw: RawMode,
    on_issue: OnIssue,
) -> ObservationResult:
    handle = _provider_lookup(provider_id)
    results = tuple(
        handle.observations(
            stations=selected_series.station_id,
            products=selected_series.product_id,
            start=start,
            end=end,
            on_issue="ignore",
            raw=raw,
        )
        for selected_series in series
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
    raw_entries = tuple(entry for result in results for entry in result.raw.entries)
    return ObservationResult(
        data=pl.concat([result.data for result in results]),
        provenance=first.provenance.model_copy(update={"request": merged_request}),
        issues=issues,
        raw=RawPayload(provider_id=first.provenance.provider_id, entries=raw_entries),
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


def _ensure_default_providers_registered() -> None:
    if not _DEFAULT_PROVIDER_REGISTRATION_ENABLED:
        return
    registered = _registry.list_provider_ids()
    if (
        "ch_foen" in registered
        and "lt_lhmt" in registered
        and "usgs_nwis" in registered
        and "cz_chmi" in registered
        and "th_thaiwater" in registered
        and "fr_hubeau" in registered
        and "jp_mlit" in registered
        and "br_ana" in registered
        and "no_nve" in registered
        and "ca_eccc" in registered
        and "pl_imgw" in registered
        and "ba_fhmzbih" in registered
        and "za_dws" in registered
    ):
        return

    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact

    if "ch_foen" not in registered:
        from rivretrieve._internal.providers.ch_foen import module as ch_foen_module

        packaged_artifact = load_packaged_catalogue_artifact(ch_foen_module._CATALOGUE_PATH, on_issue="raise")
        _registry.register(
            "ch_foen",
            packaged_artifact,
            provider_module=None,
        )

    if "lt_lhmt" not in registered:
        from rivretrieve._internal.providers.lt_lhmt import module as lt_lhmt_module

        lt_lhmt_artifact = load_packaged_catalogue_artifact(lt_lhmt_module._CATALOGUE_PATH, on_issue="raise")
        _registry.register(
            "lt_lhmt",
            lt_lhmt_artifact,
            provider_module=None,
        )

    if "usgs_nwis" not in registered:
        from rivretrieve._internal.providers.usgs_nwis import module as usgs_nwis_module

        usgs_nwis_artifact = load_packaged_catalogue_artifact(usgs_nwis_module._CATALOGUE_PATH, on_issue="raise")
        _registry.register(
            "usgs_nwis",
            usgs_nwis_artifact,
            engine_provider_module=usgs_nwis_module,
        )

    if "cz_chmi" not in registered:
        from rivretrieve._internal.providers.cz_chmi import module as cz_chmi_module

        cz_chmi_artifact = load_packaged_catalogue_artifact(cz_chmi_module._CATALOGUE_PATH, on_issue="raise")
        _registry.register(
            "cz_chmi",
            cz_chmi_artifact,
            provider_module=None,
        )

    if "th_thaiwater" not in registered:
        from rivretrieve._internal.providers.th_thaiwater import module as th_thaiwater_module

        th_thaiwater_artifact = load_packaged_catalogue_artifact(th_thaiwater_module._CATALOGUE_PATH, on_issue="raise")
        _registry.register(
            "th_thaiwater",
            th_thaiwater_artifact,
            provider_module=None,
        )

    if "fr_hubeau" not in registered:
        from rivretrieve._internal.providers.fr_hubeau import module as fr_hubeau_module

        fr_hubeau_artifact = load_packaged_catalogue_artifact(fr_hubeau_module._CATALOGUE_PATH, on_issue="raise")
        _registry.register(
            "fr_hubeau",
            fr_hubeau_artifact,
            provider_module=None,
        )

    if "jp_mlit" not in registered:
        from rivretrieve._internal.providers.jp_mlit import module as jp_mlit_module

        jp_mlit_artifact = load_packaged_catalogue_artifact(jp_mlit_module._CATALOGUE_PATH, on_issue="raise")
        _registry.register(
            "jp_mlit",
            jp_mlit_artifact,
            provider_module=None,
        )

    if "br_ana" not in registered:
        from rivretrieve._internal.providers.br_ana import module as br_ana_module

        br_ana_artifact = load_packaged_catalogue_artifact(br_ana_module._CATALOGUE_PATH, on_issue="raise")
        _registry.register(
            "br_ana",
            br_ana_artifact,
            provider_module=None,
        )

    if "no_nve" not in registered:
        from rivretrieve._internal.providers.no_nve import module as no_nve_module

        no_nve_artifact = load_packaged_catalogue_artifact(no_nve_module._CATALOGUE_PATH, on_issue="raise")
        _registry.register(
            "no_nve",
            no_nve_artifact,
            provider_module=None,
        )

    if "ca_eccc" not in registered:
        from rivretrieve._internal.providers.ca_eccc import module as ca_eccc_module

        ca_eccc_artifact = load_packaged_catalogue_artifact(ca_eccc_module._CATALOGUE_PATH, on_issue="raise")
        _registry.register(
            "ca_eccc",
            ca_eccc_artifact,
            engine_provider_module=ca_eccc_module,
        )

    if "pl_imgw" not in registered:
        from rivretrieve._internal.providers.pl_imgw import module as pl_imgw_module

        pl_imgw_artifact = load_packaged_catalogue_artifact(pl_imgw_module._CATALOGUE_PATH, on_issue="raise")
        _registry.register(
            "pl_imgw",
            pl_imgw_artifact,
        )

    if "ba_fhmzbih" not in registered:
        from rivretrieve._internal.providers.ba_fhmzbih import module as ba_fhmzbih_module

        ba_fhmzbih_artifact = load_packaged_catalogue_artifact(ba_fhmzbih_module._CATALOGUE_PATH, on_issue="raise")
        _registry.register(
            "ba_fhmzbih",
            ba_fhmzbih_artifact,
        )

    if "za_dws" not in registered:
        from rivretrieve._internal.providers.za_dws import module as za_dws_module

        za_dws_artifact = load_packaged_catalogue_artifact(za_dws_module._CATALOGUE_PATH, on_issue="raise")
        _registry.register(
            "za_dws",
            za_dws_artifact,
        )
