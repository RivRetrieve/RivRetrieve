"""BoM catalogue maintenance : build(NativeTable × OriginDeclarations) -> GeneratedAuBomCatalogue."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    CatalogueBuildInputs,
)
from rivretrieve._internal.catalogue_origins import OriginDeclarations, enforce_catalogue_origins
from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, stamp_native_table
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
    AvailabilityDtype,
    ProductCatalog,
    StationCatalog,
    StationProductCatalog,
    validate_catalogue,
)
from rivretrieve._internal.catalogues.source_series import SourceDescriptions
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId

PROVIDER_ID = ProviderId("au_bom")
PROVIDER_NAME = "Bureau of Meteorology (BoM) Water Data Online"

NATIVE_SOURCE_SCHEMA = pl.Schema(
    {
        "station_no": pl.String,
        "station_name": pl.String,
        "station_longname": pl.String,
        "station_latitude": pl.Float64,
        "station_longitude": pl.Float64,
        "station_georefsystem": pl.String,
    }
)
NATIVE_SCHEMA = pl.Schema({**NATIVE_SOURCE_SCHEMA, "retrieved_at": pl.Datetime(time_unit="us", time_zone="UTC")})

ASSOCIATION_SCHEMA = pl.Schema({"station_no": pl.String, "product_id": pl.String})


@dataclass(frozen=True)
class ProductDefinition:
    product_id: str
    observed_property: str
    quantity: str
    frequency: str
    statistic: str
    canonical_unit: str
    native_id: str
    timeseries_list_kind: str


PRODUCT_DEFINITIONS: tuple[ProductDefinition, ...] = (
    ProductDefinition(
        "discharge_hourly_mean",
        "discharge",
        "discharge",
        "hourly",
        "mean",
        "m3/s",
        "DMQaQc.Merged.HourlyMean.HR",
        "timeseries_list_discharge_HourlyMean_HR",
    ),
    ProductDefinition(
        "discharge_daily_mean_24hr",
        "discharge",
        "discharge",
        "daily",
        "mean",
        "m3/s",
        "DMQaQc.Merged.DailyMean.24HR",
        "timeseries_list_discharge_DailyMean_24HR",
    ),
    ProductDefinition(
        "discharge_daily_mean_09hr",
        "discharge",
        "discharge",
        "daily",
        "mean",
        "m3/s",
        "DMQaQc.Merged.DailyMean.09HR",
        "timeseries_list_discharge_DailyMean_09HR",
    ),
    ProductDefinition(
        "discharge_daily_max",
        "discharge",
        "discharge",
        "daily",
        "max",
        "m3/s",
        "DMQaQc.Merged.DailyMax.24HR",
        "timeseries_list_discharge_DailyMax_24HR",
    ),
    ProductDefinition(
        "discharge_daily_min",
        "discharge",
        "discharge",
        "daily",
        "min",
        "m3/s",
        "DMQaQc.Merged.DailyMin.24HR",
        "timeseries_list_discharge_DailyMin_24HR",
    ),
    ProductDefinition(
        "discharge_monthly_mean",
        "discharge",
        "discharge",
        "monthly",
        "mean",
        "m3/s",
        "DMQaQc.Merged.MonthlyMean.CalMonth",
        "timeseries_list_discharge_MonthlyMean_CalMonth",
    ),
    ProductDefinition(
        "discharge_yearly_mean",
        "discharge",
        "discharge",
        "yearly",
        "mean",
        "m3/s",
        "DMQaQc.Merged.YearlyMean.CalYear",
        "timeseries_list_discharge_YearlyMean_CalYear",
    ),
    ProductDefinition(
        "stage_hourly_mean",
        "stage",
        "stage",
        "hourly",
        "mean",
        "m",
        "DMQaQc.Merged.HourlyMean.HR",
        "timeseries_list_stage_HourlyMean_HR",
    ),
    ProductDefinition(
        "stage_daily_mean",
        "stage",
        "stage",
        "daily",
        "mean",
        "m",
        "DMQaQc.Merged.DailyMean.24HR",
        "timeseries_list_stage_DailyMean_24HR",
    ),
    ProductDefinition(
        "stage_daily_max",
        "stage",
        "stage",
        "daily",
        "max",
        "m",
        "DMQaQc.Merged.DailyMax.24HR",
        "timeseries_list_stage_DailyMax_24HR",
    ),
    ProductDefinition(
        "stage_daily_min",
        "stage",
        "stage",
        "daily",
        "min",
        "m",
        "DMQaQc.Merged.DailyMin.24HR",
        "timeseries_list_stage_DailyMin_24HR",
    ),
    ProductDefinition(
        "stage_monthly_mean",
        "stage",
        "stage",
        "monthly",
        "mean",
        "m",
        "DMQaQc.Merged.MonthlyMean.CalMonth",
        "timeseries_list_stage_MonthlyMean_CalMonth",
    ),
    ProductDefinition(
        "stage_yearly_mean",
        "stage",
        "stage",
        "yearly",
        "mean",
        "m",
        "DMQaQc.Merged.YearlyMean.CalYear",
        "timeseries_list_stage_YearlyMean_CalYear",
    ),
    ProductDefinition(
        "water_temperature_daily_mean",
        "water_temperature",
        "temperature",
        "daily",
        "mean",
        "degC",
        "DMQaQc.Merged.DailyMean.24HR",
        "timeseries_list_temperature_DailyMean_24HR",
    ),
    ProductDefinition(
        "water_temperature_daily_max",
        "water_temperature",
        "temperature",
        "daily",
        "max",
        "degC",
        "DMQaQc.Merged.DailyMax.24HR",
        "timeseries_list_temperature_DailyMax_24HR",
    ),
    ProductDefinition(
        "water_temperature_daily_min",
        "water_temperature",
        "temperature",
        "daily",
        "min",
        "degC",
        "DMQaQc.Merged.DailyMin.24HR",
        "timeseries_list_temperature_DailyMin_24HR",
    ),
    ProductDefinition(
        "water_temperature_monthly_mean",
        "water_temperature",
        "temperature",
        "monthly",
        "mean",
        "degC",
        "DMQaQc.Merged.MonthlyMean.CalMonth",
        "timeseries_list_temperature_MonthlyMean_CalMonth",
    ),
    ProductDefinition(
        "water_temperature_yearly_mean",
        "water_temperature",
        "temperature",
        "yearly",
        "mean",
        "degC",
        "DMQaQc.Merged.YearlyMean.CalYear",
        "timeseries_list_temperature_YearlyMean_CalYear",
    ),
)

STATION_LIST_KINDS = ("station_list_discharge", "station_list_stage", "station_list_temperature")


@dataclass(frozen=True)
class GeneratedAuBomCatalogue:
    provider_info: dict[str, object]
    products: ProductCatalog
    stations: StationCatalog
    station_products: StationProductCatalog
    acquisition_provenance: AcquisitionProvenance
    source_descriptions: SourceDescriptions


def station_native_table(
    station_list_docs: dict[str, list], *, retrieved_at: RetrievedAt
) -> tuple[NativeTable, tuple[str, ...]]:
    """Merge BoM's discharge/stage/temperature-filtered station lists into one native table.

    Confirmed live on 2026-11-02/03: about 1.2% of station_no values (102 of
    8,765) carry more than one distinct name/coordinate/georefsystem record,
    either duplicated within a single getStationList response or disagreeing
    between the discharge-, stage- and temperature-filtered lists -- an
    uncorrected source duplicate, not evidence of distinct stations sharing
    an identifier. This keeps the first record encountered in a fixed
    traversal order (discharge list, then stage, then temperature; file
    order within each), the same "take the first" rule both legacy reference
    clients already apply to duplicate series (#334), and returns the
    affected station_no values rather than silently dropping the finding.
    """
    rows_by_station: dict[str, dict[str, object]] = {}
    ambiguous: set[str] = set()
    for kind in ("station_list_discharge", "station_list_stage", "station_list_temperature"):
        doc = station_list_docs[kind]
        header = doc[0]
        for raw_row in doc[1:]:
            record = dict(zip(header, raw_row, strict=True))
            station_no = record["station_no"]
            row = {
                "station_no": station_no,
                "station_name": record["station_name"] or None,
                "station_longname": record.get("station_longname") or None,
                "station_latitude": float(record["station_latitude"]) if record.get("station_latitude") else None,
                "station_longitude": float(record["station_longitude"]) if record.get("station_longitude") else None,
                "station_georefsystem": record.get("station_georefsystem") or None,
            }
            existing = rows_by_station.get(station_no)
            if existing is None:
                rows_by_station[station_no] = row
            elif existing != row:
                ambiguous.add(station_no)
    if not rows_by_station:
        raise FatalContractError("au_bom station lists produced no stations")
    source = pl.DataFrame(
        sorted(rows_by_station.values(), key=lambda row: row["station_no"]),
        schema=NATIVE_SOURCE_SCHEMA,
    )
    return stamp_native_table(source, retrieved_at), tuple(sorted(ambiguous))


def river_gauge_native_table(all_stations: NativeTable, witnessed_station_ids: set[str]) -> NativeTable:
    """Scope the retained station-list rows to the river-gauge subset.

    BoM's getStationList filtered by parameter type proves parameter
    *association*, not that an admitted series actually exists there (#334,
    confirmed again on 2026-11-02: 8,765 parameter-associated stations vs.
    8,120 actually witnessed in a network-wide getTimeseriesList response).
    The catalogue's native table is this witnessed subset, analogous to
    at_ehyd's lake exclusion: a provider's native table is its established
    scope, not every raw row a broader request happened to return.
    """
    filtered = all_stations.data.filter(pl.col("station_no").is_in(witnessed_station_ids))
    if filtered.height != len(witnessed_station_ids):
        raise FatalContractError("au_bom: a witnessed station_no is absent from the retained station lists")
    return NativeTable(filtered)


def timeseries_list_associations(doc: list, *, product_id: str, station_ids: set[str]) -> pl.DataFrame:
    """One association row per station witnessed in a network-wide getTimeseriesList response."""
    header = doc[0]
    station_index = header.index("station_no")
    witnessed = {row[station_index] for row in doc[1:]}
    unexpected = witnessed - station_ids
    if unexpected:
        raise FatalContractError(
            f"au_bom timeseries list for {product_id} witnesses stations outside the native table: "
            f"{sorted(unexpected)[:5]!r}"
        )
    return pl.DataFrame(
        {"station_no": sorted(witnessed), "product_id": [product_id] * len(witnessed)},
        schema=ASSOCIATION_SCHEMA,
    )


def build_products() -> ProductCatalog:
    rows = [
        {
            "provider_id": PROVIDER_ID,
            "product_id": d.product_id,
            "observed_property": d.observed_property,
            "frequency": d.frequency,
            "statistic": d.statistic,
            "period_type": "interval",
            "period_anchor": "unknown",
            "unit": d.canonical_unit,
            "native_id": d.native_id,
        }
        for d in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(native_table: NativeTable) -> StationCatalog:
    from rivretrieve._internal.providers.au_bom.origins import _epsg_for_georefsystem

    rows = [
        {
            "provider_id": PROVIDER_ID,
            "station_id": row["station_no"],
            "latitude": row["station_latitude"],
            "longitude": row["station_longitude"],
            "crs": _epsg_for_georefsystem(row["station_georefsystem"]) if row["station_georefsystem"] else "unknown",
        }
        for row in native_table.data.iter_rows(named=True)
    ]
    return pl.DataFrame(rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


def build_station_products(
    *,
    station_ids: list[str],
    associations: pl.DataFrame,
    catalogue_date: date,
) -> StationProductCatalog:
    witnessed = {(row["station_no"], row["product_id"]) for row in associations.iter_rows(named=True)}
    rows = [
        {
            "provider_id": PROVIDER_ID,
            "station_id": station_id,
            "product_id": d.product_id,
            "availability": "available" if (station_id, d.product_id) in witnessed else "unknown",
            "availability_reason": None
            if (station_id, d.product_id) in witnessed
            else "Not witnessed in BoM's network-wide getTimeseriesList response for this series",
            "published_record_start_date": None,
            "published_record_end_date": None,
            "last_catalogue_check": catalogue_date,
        }
        for station_id in station_ids
        for d in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).with_columns(
        pl.col("availability").cast(AvailabilityDtype)
    )


def build_provider_info(
    catalogue_date: date, *, license_text: str | None, citation_text: str | None
) -> dict[str, object]:
    return {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "false: catalogue-only station discovery; observation retrieval is unavailable",
        "catalogue_version": catalogue_date.isoformat(),
        "license": license_text,
        "citation": citation_text,
    }


def catalogue_tables(
    native_table: NativeTable, associations: pl.DataFrame, *, checked_on: date
) -> tuple[ProductCatalog, StationCatalog, StationProductCatalog]:
    products = build_products()
    stations = build_stations(native_table)
    station_products = build_station_products(
        station_ids=stations["station_id"].to_list(), associations=associations, catalogue_date=checked_on
    )
    for frame, schema in (
        (products, PRODUCT_CATALOG_SCHEMA),
        (stations, STATION_CATALOG_SCHEMA),
        (station_products, STATION_PRODUCT_CATALOG_SCHEMA),
    ):
        validate_catalogue(frame, schema, on_issue="raise")
    return products, stations, station_products


def build_catalogue(
    native_table: NativeTable,
    origins: OriginDeclarations,
    *,
    associations: pl.DataFrame,
    checked_on: date,
    provenance: AcquisitionProvenance,
) -> GeneratedAuBomCatalogue:
    """Assemble the official Australia BoM offline station and product catalogue."""
    from rivretrieve._internal.providers.au_bom.catalogue_series import describe_catalogue

    if native_table.data.schema != NATIVE_SCHEMA:
        raise FatalContractError("au_bom native table does not have the exact required schema")
    if native_table.data.is_empty():
        raise FatalContractError("au_bom native table must not be empty")
    products, stations, station_products = catalogue_tables(native_table, associations, checked_on=checked_on)
    enforce_catalogue_origins(PROVIDER_ID, origins, native_table, stations)
    if provenance is None or provenance.provider_id != "au_bom":
        raise FatalContractError("Official au_bom catalogue requires its selected acquisition provenance")
    statements = {
        statement.kind: statement.exact_text for source in provenance.source_records for statement in source.statements
    }
    provider_info = build_provider_info(
        checked_on, license_text=statements.get("license"), citation_text=statements.get("citation")
    )
    from rivretrieve._internal.catalogues.artifact import packaged_catalogue_artifact_from_components

    artifact = packaged_catalogue_artifact_from_components(
        provider_info, products, stations, station_products, acquisition_provenance=provenance, on_issue="raise"
    )
    return GeneratedAuBomCatalogue(
        provider_info, products, stations, station_products, provenance, describe_catalogue(artifact)
    )


def write_catalogue(
    catalogue: GeneratedAuBomCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs,
    native_table: NativeTable,
) -> None:
    """Publish candidate runtime tables through the shared evidence-aware publication path."""
    from io import BytesIO

    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.au_bom.origins import STATION_CATALOGUE_ORIGINS, STATION_METADATA_FIELDS

    files = {
        "provider.json": (json.dumps(catalogue.provider_info, sort_keys=True, separators=(",", ":")) + "\n").encode()
    }
    for name, frame in (
        ("products", catalogue.products),
        ("stations", catalogue.stations),
        ("station_products", catalogue.station_products),
    ):
        buffer = BytesIO()
        frame.write_parquet(buffer)
        files[f"{name}.parquet"] = buffer.getvalue()
    metadata = build_catalogue_metadata(
        catalogue.acquisition_provenance,
        (STATION_CATALOGUE_ORIGINS,),
        files,
        build_inputs=build_inputs,
        native_table=native_table,
        metadata_fields=STATION_METADATA_FIELDS,
        source_descriptions=catalogue.source_descriptions,
    )
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    for name, content in {**files, **metadata}.items():
        (output / name).write_bytes(content)


@dataclass(frozen=True)
class CatalogueSources:
    native_table: NativeTable
    associations: pl.DataFrame
    checked_on: date


def read_catalogue_sources(evidence_root: Path) -> CatalogueSources:
    """Derive the native table and station-product associations from retained captures.

    ``evidence_root`` holds the retained files named by
    ``maintenance/catalogue/au_bom/official/catalogue.json``'s captures, laid
    out at their declared ``body`` paths (for example by running the
    archive's ``fetch`` command against collections
    ``au_bom-catalogue-2026-11-02-v1`` and
    ``au_bom-catalogue-native-2026-11-03-v1``). This reads those bytes
    directly; it does not perform the coordinator's exact-pin
    ``RetainedInputReceipt`` verification -- that full-check wiring belongs
    to Effort #648 (verification), not this catalogue step.
    """
    selection_path = evidence_root / "maintenance/catalogue/au_bom/official/catalogue.json"
    selection = json.loads(selection_path.read_bytes())
    captures = {capture["kind"]: capture for capture in selection["captures"]}

    station_docs = {
        kind: json.loads((evidence_root / captures[kind]["body"]).read_bytes())
        for kind in ("station_list_discharge", "station_list_stage", "station_list_temperature")
    }
    checked_on_date = date.fromisoformat(selection["checked_on"])
    all_stations, _ambiguous = station_native_table(
        station_docs,
        retrieved_at=RetrievedAt(
            datetime(checked_on_date.year, checked_on_date.month, checked_on_date.day, tzinfo=UTC)
        ),
    )
    provisional_ids = set(all_stations.data["station_no"].to_list())
    assoc_frames = [
        timeseries_list_associations(
            json.loads((evidence_root / captures[d.timeseries_list_kind]["body"]).read_bytes()),
            product_id=d.product_id,
            station_ids=provisional_ids,
        )
        for d in PRODUCT_DEFINITIONS
    ]
    associations = pl.concat(assoc_frames)
    witnessed = set(associations["station_no"].to_list())
    native = river_gauge_native_table(all_stations, witnessed)
    return CatalogueSources(native, associations, checked_on_date)
