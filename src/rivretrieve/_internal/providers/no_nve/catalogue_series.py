"""Provider-owned catalogue source-series description mapping."""

from __future__ import annotations

import polars as pl

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions


def describe_catalogue(artifact: PackagedCatalogArtifact, *, native: pl.DataFrame) -> SourceDescriptions:
    provider = "no_nve"
    if artifact.products.is_empty():
        return SourceDescriptions(provider_id=provider, descriptions=())
    if native is None:
        raise ValueError("NVE source descriptions require the acquired native station inventory")
    from rivretrieve._internal.providers.no_nve.series import describe_series

    descriptions: dict[tuple, SourceDescription] = {}
    stations: dict[tuple, list[str]] = {}
    for row in native.select("stationId", "seriesList").iter_rows(named=True):
        for member in row["seriesList"] or ():
            if member["parameter"] not in (1000, 1001, 1003):
                continue
            for resolution in member["resolutionList"] or ():
                if resolution["resTime"] not in (0, 60, 1440):
                    continue
                key = (
                    member["parameter"],
                    member["versionNo"],
                    resolution["resTime"],
                    resolution["method"],
                    member["unit"],
                )
                stations.setdefault(key, []).append(row["stationId"])
                if key in descriptions:
                    continue
                item = describe_series("catalogue-template", *key, origin="catalogue")
                ref = "catalogue:no_nve:source.station_catalogue.series_parameter_resolution_unit"
                facts = item.facts[0]
                updates = {
                    name: getattr(facts, name).model_copy(update={"evidence": (ref,)})
                    for name in ("quantity", "source_unit", "frequency", "statistic")
                }
                descriptions[key] = SourceDescription(
                    product_id=item.product_id,
                    identity_key=(
                        "HydAPI.version",
                        str(member["parameter"]),
                        str(member["versionNo"]),
                        str(resolution["resTime"]),
                    ),
                    native_coordinate=f"{member['parameter']}:{resolution['resTime']}",
                    identity=item.identity.model_copy(update={"evidence": (ref,)}),
                    variant=item.variant,
                    facts=(facts.model_copy(update=updates),),
                )
    return SourceDescriptions(
        provider_id=provider,
        descriptions=tuple(
            item.model_copy(update={"station_ids": tuple(stations[key])}) for key, item in descriptions.items()
        ),
    )
