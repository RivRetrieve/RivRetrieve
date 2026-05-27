from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import polars as pl

from rivretrieve._internal.catalogues.schemas import (
    AvailabilityDtype,
    ProductCatalog,
    ProviderInfoCatalog,
    StationCatalog,
    StationProductCatalog,
    validate_catalogue,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import OnIssue

REQUIRED_ARTIFACT_FILES = (
    "provider.json",
    "products.parquet",
    "stations.parquet",
    "station_products.parquet",
)


class CorruptCatalogArtifactError(FatalContractError):
    """Raised when a packaged catalogue artifact cannot satisfy its contract."""


@dataclass(frozen=True)
class PackagedCatalogArtifact:
    provider_info: dict[str, object]
    products: pl.DataFrame
    stations: pl.DataFrame
    station_products: pl.DataFrame


def load_packaged_catalogue_artifact(
    path: Path | str,
    *,
    on_issue: OnIssue = "warn",
) -> PackagedCatalogArtifact:
    artifact_path = Path(path)
    _ensure_artifact_path(artifact_path)

    provider_info = _read_provider_json(artifact_path / "provider.json")
    products = _read_parquet(artifact_path / "products.parquet")
    stations = _read_parquet(artifact_path / "stations.parquet")
    station_products = _read_parquet(artifact_path / "station_products.parquet")

    return packaged_catalogue_artifact_from_components(
        provider_info,
        products,
        stations,
        station_products,
        on_issue=on_issue,
    )


def packaged_catalogue_artifact_from_components(
    provider_info: Mapping[str, object],
    products: pl.DataFrame,
    stations: pl.DataFrame,
    station_products: pl.DataFrame,
    *,
    on_issue: OnIssue = "warn",
) -> PackagedCatalogArtifact:
    try:
        provider_info_df = _provider_info_to_df(provider_info)
        station_products = _normalize_availability(station_products)

        validate_catalogue(provider_info_df, ProviderInfoCatalog, on_issue=on_issue)
        validate_catalogue(products, ProductCatalog, on_issue=on_issue)
        validate_catalogue(stations, StationCatalog, on_issue=on_issue)
        validate_catalogue(station_products, StationProductCatalog, on_issue=on_issue)
        _validate_artifact_provider_ids(provider_info_df, products, stations, station_products)
        _validate_station_product_references(products, stations, station_products)
    except FatalContractError as exc:
        raise CorruptCatalogArtifactError(str(exc)) from exc
    except pl.exceptions.PolarsError as exc:
        raise CorruptCatalogArtifactError("Packaged catalogue artifact has invalid data") from exc

    return PackagedCatalogArtifact(
        provider_info=provider_info_df.row(0, named=True),
        products=products,
        stations=stations,
        station_products=station_products,
    )


def _ensure_artifact_path(path: Path) -> None:
    if not path.exists():
        raise CorruptCatalogArtifactError(f"Packaged catalogue directory does not exist: {path}")
    if not path.is_dir():
        raise CorruptCatalogArtifactError(f"Packaged catalogue path is not a directory: {path}")

    missing_files = [file_name for file_name in REQUIRED_ARTIFACT_FILES if not (path / file_name).is_file()]
    if missing_files:
        raise CorruptCatalogArtifactError(
            f"Packaged catalogue artifact is missing required files: {', '.join(missing_files)}"
        )


def _read_provider_json(path: Path) -> Mapping[str, object]:
    try:
        with path.open(encoding="utf-8") as file:
            value = json.load(file)
    except OSError as exc:
        raise CorruptCatalogArtifactError(f"Unable to read provider info file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CorruptCatalogArtifactError(f"Provider info file is not valid JSON: {path}") from exc

    if not isinstance(value, dict):
        raise CorruptCatalogArtifactError("Provider info file must contain a JSON object")
    return value


def _read_parquet(path: Path) -> pl.DataFrame:
    try:
        return pl.read_parquet(path)
    except pl.exceptions.PolarsError as exc:
        raise CorruptCatalogArtifactError(f"Unable to read parquet catalogue file: {path}") from exc


def _provider_info_to_df(provider_info: Mapping[str, object]) -> pl.DataFrame:
    normalized = dict(provider_info)
    metadata = normalized.get("metadata")
    if _is_row_sequence(metadata):
        normalized["metadata"] = [_canonical_metadata_value(value) for value in cast(Sequence[object], metadata)]
    else:
        normalized["metadata"] = _canonical_metadata_value(metadata)

    try:
        if any(_is_row_sequence(value) for value in normalized.values()):
            return pl.DataFrame(normalized, schema=ProviderInfoCatalog.polars_schema)
        return pl.DataFrame([normalized], schema=ProviderInfoCatalog.polars_schema)
    except pl.exceptions.PolarsError as exc:
        raise FatalContractError("Provider info cannot be converted to the catalogue schema") from exc


def _canonical_metadata_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        raise FatalContractError("Provider info metadata must be a JSON object or JSON object string")
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _is_row_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)


def _normalize_availability(station_products: pl.DataFrame) -> pl.DataFrame:
    if "availability" not in station_products.columns:
        return station_products

    dtype = station_products.schema["availability"]
    if dtype == AvailabilityDtype:
        return station_products
    if dtype == pl.Utf8:
        try:
            return station_products.with_columns(pl.col("availability").cast(AvailabilityDtype))
        except pl.exceptions.PolarsError as exc:
            raise CorruptCatalogArtifactError(
                "station_products.availability contains values outside the allowed vocabulary"
            ) from exc
    return station_products


def _validate_artifact_provider_ids(
    provider_info: pl.DataFrame,
    products: pl.DataFrame,
    stations: pl.DataFrame,
    station_products: pl.DataFrame,
) -> None:
    provider_ids = _unique_values(provider_info, "provider_id")
    if len(provider_ids) != 1:
        raise FatalContractError("Provider info must contain exactly one provider_id")

    expected_provider_id = next(iter(provider_ids))
    for table_name, table in (
        ("products", products),
        ("stations", stations),
        ("station_products", station_products),
    ):
        table_provider_ids = _unique_values(table, "provider_id")
        if table_provider_ids != {expected_provider_id}:
            raise FatalContractError(f"{table_name}.provider_id does not match provider.json provider_id")


def _validate_station_product_references(
    products: pl.DataFrame,
    stations: pl.DataFrame,
    station_products: pl.DataFrame,
) -> None:
    station_keys = set(stations.select("provider_id", "station_id").iter_rows())
    product_keys = set(products.select("provider_id", "product_id").iter_rows())

    missing_station_keys = [
        (provider_id, station_id)
        for provider_id, station_id in station_products.select("provider_id", "station_id").iter_rows()
        if (provider_id, station_id) not in station_keys
    ]
    if missing_station_keys:
        raise FatalContractError("station_products references stations absent from stations")

    missing_product_keys = [
        (provider_id, product_id)
        for provider_id, product_id in station_products.select("provider_id", "product_id").iter_rows()
        if (provider_id, product_id) not in product_keys
    ]
    if missing_product_keys:
        raise FatalContractError("station_products references products absent from products")


def _unique_values(df: pl.DataFrame, column_name: str) -> set[object]:
    return set(df[column_name].drop_nulls().unique().to_list())
