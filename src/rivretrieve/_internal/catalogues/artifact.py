"""packaged catalogue loading : ArtifactFiles → PackagedCatalogArtifact."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import polars as pl
from pydantic import ValidationError

from rivretrieve._internal.acquisition_provenance import AbsenceMarkerValue, AcquisitionProvenance
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
    AvailabilityDtype,
    CatalogueSchema,
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

ACQUISITION_PROVENANCE_ENROLLED_PROVIDERS = frozenset(
    {
        "ba_fhmzbih",
        "br_ana",
        "ca_eccc",
        "ch_foen",
        "cz_chmi",
        "fr_hubeau",
        "jp_mlit",
        "lt_lhmt",
        "no_nve",
        "pl_imgw",
        "th_thaiwater",
        "usgs_nwis",
        "za_dws",
    }
)

_CATALOGUE_FACT_SCHEMAS: tuple[tuple[str, CatalogueSchema], ...] = (
    ("provider", PROVIDER_INFO_CATALOG_SCHEMA),
    ("product", PRODUCT_CATALOG_SCHEMA),
    ("station", STATION_CATALOG_SCHEMA),
    ("station_product", STATION_PRODUCT_CATALOG_SCHEMA),
)
CATALOGUE_FACT_UNIVERSE = tuple(
    f"{prefix}.{column.name}" for prefix, schema in _CATALOGUE_FACT_SCHEMAS for column in schema.columns
)


class CorruptCatalogArtifactError(FatalContractError):
    """Raised when a packaged catalogue artifact cannot satisfy its contract."""


@dataclass(frozen=True)
class PackagedCatalogArtifact:
    """Validated canonical catalogue tables and shared acquisition provenance."""

    provider_info: dict[str, object]
    products: pl.DataFrame
    stations: pl.DataFrame
    station_products: pl.DataFrame
    acquisition_provenance: AcquisitionProvenance | None = None


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
    acquisition_provenance = _read_provenance_json(artifact_path / "provenance.json")

    return packaged_catalogue_artifact_from_components(
        provider_info,
        products,
        stations,
        station_products,
        acquisition_provenance=acquisition_provenance,
        withheld_rows_already_applied=True,
        on_issue=on_issue,
    )


def packaged_catalogue_artifact_from_components(
    provider_info: Mapping[str, object],
    products: pl.DataFrame,
    stations: pl.DataFrame,
    station_products: pl.DataFrame,
    *,
    acquisition_provenance: AcquisitionProvenance | None = None,
    withheld_rows_already_applied: bool = False,
    on_issue: OnIssue = "warn",
) -> PackagedCatalogArtifact:
    try:
        provider_info_df = _provider_info_to_df(provider_info)
        if provider_info_df.height != 1:
            raise FatalContractError("Provider info must contain exactly one row")
        provider_id = provider_info_df["provider_id"].item()
        if provider_id in ACQUISITION_PROVENANCE_ENROLLED_PROVIDERS and acquisition_provenance is None:
            raise FatalContractError(f"{provider_id} acquisition provenance is required")
        if acquisition_provenance is not None:
            if acquisition_provenance.provider_id != provider_id:
                raise FatalContractError("provenance.json provider_id does not match provider.json provider_id")
            _validate_catalogue_fact_universe(acquisition_provenance)
            provider_info, products, stations, station_products = _apply_withheld_facts(
                provider_info_df.row(0, named=True),
                products,
                stations,
                station_products,
                acquisition_provenance,
                allow_missing_rows=withheld_rows_already_applied,
            )
            provider_info_df = _provider_info_to_df(provider_info)
            _validate_absence_marker_values(
                provider_info_df,
                products,
                stations,
                station_products,
                acquisition_provenance,
            )
        station_products = _normalize_availability(station_products)

        validate_catalogue(provider_info_df, PROVIDER_INFO_CATALOG_SCHEMA, on_issue=on_issue)
        validate_catalogue(products, PRODUCT_CATALOG_SCHEMA, on_issue=on_issue)
        validate_catalogue(stations, STATION_CATALOG_SCHEMA, on_issue=on_issue)
        validate_catalogue(station_products, STATION_PRODUCT_CATALOG_SCHEMA, on_issue=on_issue)
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
        acquisition_provenance=acquisition_provenance,
    )


def _validate_catalogue_fact_universe(provenance: AcquisitionProvenance) -> None:
    expected = set(CATALOGUE_FACT_UNIVERSE)
    declared = set(provenance.fact_universe)
    missing = expected - declared
    if missing:
        raise FatalContractError(
            f"{provenance.provider_id} acquisition provenance does not declare catalogue facts: {sorted(missing)!r}"
        )
    catalogue_prefixes = {prefix for prefix, _ in _CATALOGUE_FACT_SCHEMAS}
    unsupported = {fact for fact in declared - expected if fact.partition(".")[0] in catalogue_prefixes}
    if unsupported:
        raise FatalContractError(
            f"{provenance.provider_id} acquisition provenance declares unknown catalogue facts: {sorted(unsupported)!r}"
        )


def _validate_absence_marker_values(
    provider_info: pl.DataFrame,
    products: pl.DataFrame,
    stations: pl.DataFrame,
    station_products: pl.DataFrame,
    provenance: AcquisitionProvenance,
) -> None:
    """Require declared absence markers to equal their canonical carrier values."""
    tables = {
        "provider": provider_info,
        "product": products,
        "station": stations,
        "station_product": station_products,
    }
    for binding in provenance.fact_bindings:
        transformation = binding.transformation
        if transformation is None or transformation.kind != "absence_marker":
            continue
        marker_value = transformation.marker_value
        if marker_value is None:  # pragma: no cover - rejected by the provenance model
            raise AssertionError("absence-marker transformation has no marker value")
        expected: object = None if marker_value == AbsenceMarkerValue.NULL else marker_value.value
        for fact in binding.facts:
            carrier, separator, column = fact.partition(".")
            if not separator or carrier not in tables or column not in tables[carrier].columns:
                raise FatalContractError(f"absence marker output {fact!r} does not resolve to a catalogue carrier")
            mismatch_expression = (
                pl.col(column).is_not_null() if marker_value == AbsenceMarkerValue.NULL else pl.col(column) != expected
            )
            mismatches = tables[carrier].filter(mismatch_expression).height
            if mismatches:
                raise FatalContractError(
                    f"absence marker output {fact} must be exactly {marker_value.value}; "
                    f"found {mismatches} mismatching rows"
                )


def _apply_withheld_facts(
    provider_info: Mapping[str, object],
    products: pl.DataFrame,
    stations: pl.DataFrame,
    station_products: pl.DataFrame,
    provenance: AcquisitionProvenance,
    *,
    allow_missing_rows: bool,
) -> tuple[dict[str, object], pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    normalized_provider = dict(provider_info)
    tables = {
        "product": products,
        "station": stations,
        "station_product": station_products,
    }
    schemas = dict(_CATALOGUE_FACT_SCHEMAS)
    station_row_ids: list[str] = []
    station_product_row_keys: list[tuple[str, str]] = []
    for withheld_group in provenance.withheld_facts:
        for locator in withheld_group.catalogue_rows:
            if locator.carrier == "station":
                matches = stations.filter(pl.col("station_id") == locator.station_id).height
                if matches != 1 and not (allow_missing_rows and matches == 0):
                    raise FatalContractError(
                        f"{provenance.provider_id} withheld station row {locator.station_id!r} "
                        f"matched {matches} catalogue rows"
                    )
                station_row_ids.append(locator.station_id)
            else:
                matches = station_products.filter(
                    (pl.col("station_id") == locator.station_id) & (pl.col("product_id") == locator.product_id)
                ).height
                if matches != 1 and not (allow_missing_rows and matches == 0):
                    raise FatalContractError(
                        f"{provenance.provider_id} withheld station-product row "
                        f"{locator.station_id!r}/{locator.product_id!r} matched {matches} catalogue rows"
                    )
                if locator.product_id is None:  # pragma: no cover - rejected by the model
                    raise AssertionError("station-product locator has no product id")
                station_product_row_keys.append((locator.station_id, locator.product_id))
    for withheld_group in provenance.withheld_facts:
        for withheld_fact in withheld_group.facts:
            prefix, separator, column_name = withheld_fact.partition(".")
            if not separator or prefix not in schemas:
                continue
            schema = schemas[prefix]
            column = next(item for item in schema.columns if item.name == column_name)
            if prefix == "provider":
                value = normalized_provider.get(column_name)
                if column.nullable:
                    normalized_provider[column_name] = None
                elif value is not None:
                    raise FatalContractError(
                        f"{provenance.provider_id} withheld provider.{column_name} remains exposed"
                    )
                continue
            table = tables[prefix]
            if column.nullable:
                tables[prefix] = table.with_columns(pl.lit(None).cast(column.dtype).alias(column_name))
            else:
                tables[prefix] = table.head(0)

    products = tables["product"]
    stations = tables["station"]
    station_products = tables["station_product"]
    if station_row_ids:
        stations = stations.filter(~pl.col("station_id").is_in(station_row_ids))
    if station_product_row_keys:
        withheld_keys = pl.DataFrame(
            station_product_row_keys,
            schema={"station_id": pl.String, "product_id": pl.String},
            orient="row",
        )
        station_products = station_products.join(withheld_keys, on=["station_id", "product_id"], how="anti")
    if station_products.height:
        station_products = station_products.join(
            stations.select("provider_id", "station_id"),
            on=["provider_id", "station_id"],
            how="semi",
        ).join(
            products.select("provider_id", "product_id"),
            on=["provider_id", "product_id"],
            how="semi",
        )
    return normalized_provider, products, stations, station_products


def _read_provenance_json(path: Path) -> AcquisitionProvenance | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return AcquisitionProvenance.model_validate(value)
    except OSError as exc:
        raise CorruptCatalogArtifactError(f"Unable to read acquisition provenance file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CorruptCatalogArtifactError(f"Acquisition provenance file is not valid JSON: {path}") from exc
    except ValidationError as exc:
        raise CorruptCatalogArtifactError(f"Acquisition provenance file is invalid: {exc}") from exc


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
    try:
        if any(_is_row_sequence(value) for value in normalized.values()):
            return pl.DataFrame(normalized, schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema)
        return pl.DataFrame([normalized], schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema)
    except pl.exceptions.PolarsError as exc:
        raise FatalContractError("Provider info cannot be converted to the catalogue schema") from exc


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
        if table_provider_ids and table_provider_ids != {expected_provider_id}:
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
