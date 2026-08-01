from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    ProductCatalog,
    ProviderInfoCatalog,
    StationCatalog,
    validate_catalogue,
)
from rivretrieve._internal.handle import ProviderHandle
from rivretrieve._internal.registry import _registry
from rivretrieve._internal.results import CatalogProvenance, CatalogResult
from rivretrieve._internal.station_map import StationMap, _filter_stations

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rivretrieve._internal.observations import ObservationResult
    from rivretrieve._internal.primitives import OnIssue

_DEFAULT_PROVIDER_REGISTRATION_ENABLED = True


def providers() -> list[str]:
    _ensure_default_providers_registered()
    return _registry.list_provider_ids()


def provider(provider_id: str) -> ProviderHandle:
    _ensure_default_providers_registered()
    return _registry.get(provider_id)


_provider_lookup = provider


def observations(
    *,
    provider: str,
    stations: str | Sequence[str],
    products: str | Sequence[str],
    start: object,
    end: object,
    on_issue: OnIssue = "warn",
) -> ObservationResult:
    provider_handle = _provider_lookup(provider)
    return provider_handle.observations(
        stations=stations,
        products=products,
        start=start,
        end=end,
        on_issue=on_issue,
    )


def provider_info() -> CatalogResult[ProviderInfoCatalog]:
    from rivretrieve import __version__

    _ensure_default_providers_registered()
    rows = [record.artifact.provider_info for record in _registry.iter_records()]
    if rows:
        data = pl.DataFrame(rows, schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema).sort("provider_id")
    else:
        data = pl.DataFrame(schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema)

    issues = validate_catalogue(data, PROVIDER_INFO_CATALOG_SCHEMA, on_issue="raise")
    provenance = CatalogProvenance(
        source="packaged",
        provider_id=None,
        rivretrieve_version=__version__,
        catalogue_version=None,
        artifact_id=None,
        artifact_path=None,
        artifact_hash=None,
        generated_at=None,
        retrieved_at=None,
        endpoints=(),
        query=None,
        response_version=None,
    )
    return CatalogResult(data=data, provenance=provenance, issues=tuple(issues))


def stations() -> CatalogResult[StationCatalog]:
    _ensure_default_providers_registered()
    frames = [
        CatalogueReader(record.artifact, record.provider_id).read_stations().data for record in _registry.iter_records()
    ]
    data = _concat_or_empty(frames, STATION_CATALOG_SCHEMA.polars_schema)
    if data.height:
        data = data.sort("provider_id", "station_id")
    issues = validate_catalogue(data, STATION_CATALOG_SCHEMA, on_issue="raise")
    return CatalogResult(data=data, provenance=_global_provenance(), issues=tuple(issues))


def map_stations(
    *,
    providers: str | Sequence[str] | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> object:
    """Render packaged stations on a map.

    ``bbox`` uses inclusive ``(min_lon, min_lat, max_lon, max_lat)`` order.
    """
    station_data = stations().data
    filtered = _filter_stations(station_data, providers=providers, bbox=bbox)
    return StationMap(filtered).render()


def products() -> CatalogResult[ProductCatalog]:
    return _global_products()


def product_info() -> CatalogResult[ProductCatalog]:
    return _global_products()


def _global_products() -> CatalogResult[ProductCatalog]:
    _ensure_default_providers_registered()
    frames = [
        CatalogueReader(record.artifact, record.provider_id).read_products().data for record in _registry.iter_records()
    ]
    data = _concat_or_empty(frames, PRODUCT_CATALOG_SCHEMA.polars_schema)
    if data.height:
        data = data.sort("provider_id", "product_id")
    issues = validate_catalogue(data, PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    return CatalogResult(data=data, provenance=_global_provenance(), issues=tuple(issues))


def _concat_or_empty(frames: list[pl.DataFrame], schema: pl.Schema) -> pl.DataFrame:
    if not frames:
        return pl.DataFrame(schema=schema)
    return pl.concat(frames)


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


def _global_provenance() -> CatalogProvenance:
    from rivretrieve import __version__

    return CatalogProvenance(
        source="packaged",
        provider_id=None,
        rivretrieve_version=__version__,
        catalogue_version=None,
        artifact_id=None,
        artifact_path=None,
        artifact_hash=None,
        generated_at=None,
        retrieved_at=None,
        endpoints=(),
        query=None,
        response_version=None,
    )
