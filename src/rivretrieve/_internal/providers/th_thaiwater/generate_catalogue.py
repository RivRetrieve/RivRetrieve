"""ThaiWater catalogue maintenance : admit(ReviewedLedgerBytes) → GraphAvailabilityEvidence; refresh(ThaiWaterWaterlevelEnvelope, RetrievedAt) → WithIssues[NativeTable]; build(NativeTable, OriginDeclarations, GraphAvailabilityEvidence) → GeneratedThThaiWaterCatalogue.

The pinned availability ledger was accepted after private full-body verification.
Parsing it checks metadata identity, not source bodies. Updating the pin requires
renewed source-body acceptance. No controlled review corpus is a public recording.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import urllib.request
from collections.abc import Sequence
from dataclasses import InitVar, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Literal, cast

import polars as pl

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    AcquisitionRecord,
    MaterialIdentity,
    verify_provenance_recordings,
)
from rivretrieve._internal.catalogue_origins import OriginDeclarations, enforce_catalogue_origins
from rivretrieve._internal.catalogues.artifact import (
    PackagedCatalogArtifact,
    packaged_catalogue_artifact_from_components,
)
from rivretrieve._internal.catalogues.native import (
    NativeTable,
    RetrievedAt,
    read_native_table,
    stamp_native_table,
    write_native_table,
)
from rivretrieve._internal.catalogues.products import product_row
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
    AvailabilityDtype,
    ProductCatalog,
    StationCatalog,
    StationProductCatalog,
    validate_catalogue,
)
from rivretrieve._internal.engine import WithIssues
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.th_thaiwater.config import SERIES_MAPPINGS, ThThaiWaterSourceCoordinates
from rivretrieve._internal.providers.th_thaiwater.config import config as source_config

PROVIDER_ID = ProviderId("th_thaiwater")
PROVIDER_NAME = "ThaiWater public API / Hydro-Informatics Institute (HII)"
METADATA_URL = "https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_load"
STATION_TYPE_FILTER = "tele_waterlevel"

# Accepted governing station/product ledger, September 11 and 13, 2026.
REVIEWED_LEDGER_SHA256 = "f96e89c7fa62380ff24bc32bceda8a1075e804b29d004f0c33c6f8d013c23fed"


@dataclass(frozen=True)
class GraphProductEvidence:
    station_id: str
    product_id: ProductId
    source_id: str
    native_field: str
    window_start: date
    window_end: date
    nonnull_observations: int
    availability: Literal["available", "unknown"]
    acquisition: AcquisitionRecord

    @property
    def availability_reason(self) -> str:
        conclusion = (
            f"{self.nonnull_observations} non-null {self.native_field} measurements"
            if self.availability == "available"
            else f"null-only {self.native_field}; availability outside the tested window is unknown"
        )
        return (
            f"ThaiWater graph {self.acquisition.acquisition_id}: {conclusion}; "
            f"tested {self.window_start} through {self.window_end} inclusive"
        )


@dataclass(frozen=True)
class GraphAvailabilityEvidence:
    reviewed_ledger: InitVar[bytes]
    pairs: tuple[GraphProductEvidence, ...] = field(init=False)

    def __post_init__(self, reviewed_ledger: bytes) -> None:
        if hashlib.sha256(reviewed_ledger).hexdigest() != REVIEWED_LEDGER_SHA256:
            raise FatalContractError("ThaiWater availability evidence digest mismatch: not the reviewed ledger")
        pairs = []
        for row in csv.DictReader(io.StringIO(reviewed_ledger.decode("utf-8"))):
            acquisition = AcquisitionRecord(
                acquisition_id=row["request_id"],
                method="http_request",
                instant_type="retrieval",
                description=(
                    f"Complete ThaiWater graph for station {row['station_id']}, "
                    f"{row['window_start']} through {row['window_end']} inclusive; "
                    "supplied through HII's platform by the native station agency. "
                    "This does not identify every historical original measurement producer. "
                    "Private source bytes verified at research acceptance; metadata binding only in public CI."
                ),
                requested_from=(row["request_url"],),
                retrieved_at_start=datetime.fromisoformat(row["retrieved_at"]),
                material=MaterialIdentity(
                    filename=PurePosixPath(row["evidence_body"]).name,
                    byte_count=int(row["response_bytes"]),
                    sha256=row["response_sha256"],
                ),
            )
            pairs.append(
                GraphProductEvidence(
                    station_id=row["station_id"],
                    product_id=ProductId(row["product_id"]),
                    source_id=row["source_id"],
                    native_field=row["native_field"],
                    window_start=date.fromisoformat(row["window_start"]),
                    window_end=date.fromisoformat(row["window_end"]),
                    nonnull_observations=int(row["nonnull_observations"]),
                    availability=cast('Literal["available", "unknown"]', row["availability"]),
                    acquisition=acquisition,
                )
            )
        object.__setattr__(self, "pairs", tuple(pairs))


NATIVE_SOURCE_SCHEMA = pl.Schema(
    {
        "agency.agency_name.en": pl.String,
        "agency.agency_name.jp": pl.String,
        "agency.agency_name.th": pl.String,
        "agency.agency_shortname.en": pl.String,
        "agency.agency_shortname.jp": pl.String,
        "agency.agency_shortname.th": pl.String,
        "agency.id": pl.Int64,
        "basin.basin_code": pl.Int64,
        "basin.basin_name.en": pl.String,
        "basin.basin_name.th": pl.String,
        "basin.id": pl.Int64,
        "diff_wl_bank": pl.String,
        "diff_wl_bank_text": pl.String,
        "discharge": pl.String,
        "flow_rate": pl.String,
        "geocode.amphoe_code": pl.String,
        "geocode.amphoe_name.en": pl.String,
        "geocode.amphoe_name.th": pl.String,
        "geocode.area_code": pl.String,
        "geocode.area_name.en": pl.String,
        "geocode.area_name.th": pl.String,
        "geocode.province_code": pl.String,
        "geocode.province_name.en": pl.String,
        "geocode.province_name.th": pl.String,
        "geocode.tumbon_code": pl.String,
        "geocode.tumbon_name.en": pl.String,
        "geocode.tumbon_name.th": pl.String,
        "id": pl.Int64,
        "river_gid": pl.Int64,
        "river_name": pl.String,
        "situation_level": pl.Int64,
        "sort_order": pl.Null,
        "station.agency_id": pl.Int64,
        "station.critical_level_m": pl.Float64,
        "station.critical_level_msl": pl.Float64,
        "station.geocode_id": pl.Int64,
        "station.ground_level": pl.Float64,
        "station.hydro_id": pl.Int64,
        "station.id": pl.String,
        "station.is_key_station": pl.Boolean,
        "station.left_bank": pl.Float64,
        "station.min_bank": pl.Float64,
        "station.offset": pl.Float64,
        "station.qmax": pl.Float64,
        "station.right_bank": pl.Float64,
        "station.sponsor_by": pl.String,
        "station.sub_basin_id": pl.Int64,
        "station.tele_station_lat": pl.Float64,
        "station.tele_station_long": pl.Float64,
        "station.tele_station_name.en": pl.String,
        "station.tele_station_name.jp": pl.String,
        "station.tele_station_name.th": pl.String,
        "station.tele_station_oldcode": pl.String,
        "station.tele_station_type": pl.String,
        "station.warning_level_m": pl.Float64,
        "station_type": pl.String,
        "storage_percent": pl.String,
        "waterlevel_datetime": pl.String,
        "waterlevel_m": pl.Null,
        "waterlevel_msl": pl.String,
        "waterlevel_msl_previous": pl.String,
    }
)
NATIVE_SCHEMA = pl.Schema(
    {
        **dict(NATIVE_SOURCE_SCHEMA.items()),
        "retrieved_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    }
)

_PERMITTED_ABSENT_LEAVES = frozenset(
    {
        "river_gid",
        "river_name",
        "situation_level",
        "station.ground_level",
        "station.sponsor_by",
        "station.tele_station_name.en",
        "station.tele_station_name.jp",
    }
)
_REQUIRED_OBJECTS = (
    "station",
    "agency",
    "basin",
    "geocode",
    "station.tele_station_name",
    "agency.agency_name",
    "agency.agency_shortname",
    "basin.basin_name",
    "geocode.amphoe_name",
    "geocode.area_name",
    "geocode.province_name",
    "geocode.tumbon_name",
)
_LANGUAGE_MAP_KEYS = {
    "station.tele_station_name": frozenset({"en", "jp", "th"}),
    "agency.agency_name": frozenset({"en", "jp", "th"}),
    "agency.agency_shortname": frozenset({"en", "jp", "th"}),
    "basin.basin_name": frozenset({"en", "th"}),
    "geocode.amphoe_name": frozenset({"en", "th"}),
    "geocode.area_name": frozenset({"en", "th"}),
    "geocode.province_name": frozenset({"en", "th"}),
    "geocode.tumbon_name": frozenset({"en", "th"}),
}


@dataclass(frozen=True)
class GeneratedThThaiWaterCatalogue:
    provider_info: dict[str, object]
    products: ProductCatalog
    stations: StationCatalog
    station_products: StationProductCatalog
    acquisition_provenance: AcquisitionProvenance
    public_artifact: PackagedCatalogArtifact


def refresh_native_table(
    payload: dict[str, object],
    *,
    retrieved_at: RetrievedAt,
) -> WithIssues[NativeTable]:
    """Project a strict ThaiWater water-level envelope into its native dotted schema."""
    if "waterlevel_data" not in payload:
        raise FatalContractError("ThaiWater payload missing required object 'waterlevel_data'")
    waterlevel_data = payload["waterlevel_data"]
    if not isinstance(waterlevel_data, dict):
        raise FatalContractError("ThaiWater payload field 'waterlevel_data' must be an object")
    waterlevel_object = cast("dict[str, object]", waterlevel_data)
    if "data" not in waterlevel_object:
        raise FatalContractError("ThaiWater payload missing required list 'waterlevel_data.data'")
    raw_rows = waterlevel_object["data"]
    if not isinstance(raw_rows, list):
        raise FatalContractError("ThaiWater payload field 'waterlevel_data.data' must be a list")

    rows: list[dict[str, object]] = []
    seen_ids: set[int] = set()
    for index, raw_row in enumerate(raw_rows):
        if not isinstance(raw_row, dict):
            raise FatalContractError(f"ThaiWater row {index} must be an object")
        row = cast("dict[str, object]", raw_row)
        _validate_required_objects(row, index)
        _validate_language_maps(row, index)
        station_id = _source_leaf(row, "station.id", index=index)
        if type(station_id) is not int:
            raise FatalContractError(f"ThaiWater row {index} station.id must be a JSON integer; Boolean is invalid")
        if station_id in seen_ids:
            raise FatalContractError(f"ThaiWater duplicate station.id {station_id}")
        seen_ids.add(station_id)
        for path, dtype in NATIVE_SOURCE_SCHEMA.items():
            if path == "station.id":
                continue
            value = _source_leaf(
                row,
                path,
                index=index,
                absent_ok=path in _PERMITTED_ABSENT_LEAVES,
            )
            _validate_scalar(value, dtype, index=index, path=path)
        rows.append(row)

    flattened_rows = [_flatten_native_row(row) for row in rows]
    source_rows = pl.DataFrame(flattened_rows, schema=NATIVE_SOURCE_SCHEMA).sort("station.id")
    return WithIssues(value=stamp_native_table(source_rows, retrieved_at), issues=())


def refresh_native_table_from_fixture(
    fixture_path: Path | str,
    *,
    retrieved_at: RetrievedAt,
) -> WithIssues[NativeTable]:
    return refresh_native_table(_read_fixture_json(Path(fixture_path)), retrieved_at=retrieved_at)


def refresh_native_table_from_live(*, retrieved_at: RetrievedAt) -> WithIssues[NativeTable]:
    return refresh_native_table(_read_live_json(METADATA_URL), retrieved_at=retrieved_at)


def native_table_content_sha256(table: NativeTable) -> str:
    """Hash the exact native table as canonical aligned JSON values."""
    if table.data.schema != NATIVE_SCHEMA:
        raise FatalContractError("ThaiWater native table does not have the exact required schema")
    rows = [
        [
            value.isoformat(timespec="microseconds").replace("+00:00", "Z") if isinstance(value, datetime) else value
            for value in row
        ]
        for row in table.data.sort("station.id").iter_rows()
    ]
    canonical = json.dumps(
        {"columns": table.data.columns, "rows": rows},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_required_objects(row: dict[str, object], index: int) -> None:
    for path in _REQUIRED_OBJECTS:
        present, value = _find_source_value(row, path)
        if not present:
            raise FatalContractError(f"ThaiWater row {index} missing required object '{path}'")
        if not isinstance(value, dict):
            raise FatalContractError(f"ThaiWater row {index} field '{path}' must be an object")


def _validate_language_maps(row: dict[str, object], index: int) -> None:
    for path, expected_keys in _LANGUAGE_MAP_KEYS.items():
        language_map = _source_leaf(row, path, index=index)
        if not isinstance(language_map, dict):
            raise FatalContractError(f"ThaiWater row {index} field '{path}' must be an object")
        for key in language_map:
            if key not in expected_keys:
                raise FatalContractError(f"ThaiWater row {index} language map '{path}' contains unexpected key '{key}'")


def _find_source_value(row: dict[str, object], path: str) -> tuple[bool, object]:
    value: object = row
    for component in path.split("."):
        if not isinstance(value, dict) or component not in value:
            return False, None
        value = cast("dict[str, object]", value)[component]
    return True, value


def _source_leaf(
    row: dict[str, object],
    path: str,
    *,
    index: int = 0,
    absent_ok: bool = False,
) -> object:
    present, value = _find_source_value(row, path)
    if present:
        return value
    if absent_ok:
        return None
    raise FatalContractError(f"ThaiWater row {index} missing required leaf '{path}'")


def _validate_scalar(value: object, dtype: pl.DataType, *, index: int, path: str) -> None:
    if value is None:
        return
    valid: bool
    family: str
    if dtype == pl.String:
        valid = isinstance(value, str)
        family = "a JSON string"
    elif dtype == pl.Int64:
        valid = type(value) is int
        family = "a JSON integer"
    elif dtype == pl.Float64:
        valid = type(value) in (int, float)
        family = "a JSON number"
    elif dtype == pl.Boolean:
        valid = type(value) is bool
        family = "a JSON Boolean"
    elif dtype == pl.Null:
        valid = False
        family = "JSON null"
    else:
        raise FatalContractError(f"ThaiWater native schema has unsupported dtype for '{path}'")
    if not valid:
        raise FatalContractError(
            f"ThaiWater row {index} leaf '{path}' must be {family} or null; Boolean is invalid for numeric families"
        )


def _flatten_native_row(row: dict[str, object]) -> dict[str, object]:
    flattened: dict[str, object] = {}
    for path, dtype in NATIVE_SOURCE_SCHEMA.items():
        value = _source_leaf(row, path, absent_ok=path in _PERMITTED_ABSENT_LEAVES)
        if path == "station.id":
            value = str(value)
        elif dtype == pl.Float64 and value is not None:
            value = float(cast("int | float", value))
        flattened[path] = value
    return flattened


def build_catalogue(
    native_table: NativeTable,
    origins: OriginDeclarations,
    availability_evidence: GraphAvailabilityEvidence,
) -> GeneratedThThaiWaterCatalogue:
    _validate_canonical_native_table(native_table)
    products = build_products()
    stations = build_stations(native_table)
    enforce_catalogue_origins(PROVIDER_ID, origins, native_table, stations)
    station_products = build_station_products(stations, availability_evidence)
    maximum_retrieved_at = native_table.data["retrieved_at"].max()
    if not isinstance(maximum_retrieved_at, datetime):
        raise FatalContractError("ThaiWater native table has no valid retrieved_at values")
    provider_info = build_provider_info(maximum_retrieved_at.date())

    from rivretrieve._internal.providers.th_thaiwater.origins import build_acquisition_provenance

    acquisition_provenance = build_acquisition_provenance(native_table, availability_evidence)
    artifact = validate_generated_catalogue(provider_info, products, stations, station_products, acquisition_provenance)
    return GeneratedThThaiWaterCatalogue(
        provider_info,
        products,
        stations,
        station_products,
        acquisition_provenance,
        artifact,
    )


def _validate_canonical_native_table(native_table: NativeTable) -> None:
    data = native_table.data
    if data.is_empty():
        raise FatalContractError("ThaiWater native table contains no stations")
    if data.schema.get("station.id") != pl.String:
        raise FatalContractError("ThaiWater native station.id must have String dtype")

    invalid_types = data.filter(pl.col("station_type") != STATION_TYPE_FILTER)
    if not invalid_types.is_empty():
        station_id, station_type = invalid_types.select("station.id", "station_type").row(0)
        raise FatalContractError(
            f"ThaiWater station {station_id} has station_type {station_type!r}; expected {STATION_TYPE_FILTER!r}"
        )
    for coordinate_column in ("station.tele_station_lat", "station.tele_station_long"):
        null_coordinates = data.filter(pl.col(coordinate_column).is_null())
        if not null_coordinates.is_empty():
            station_id = null_coordinates["station.id"].item(0)
            raise FatalContractError(f"ThaiWater station {station_id} has null {coordinate_column}")
    duplicates = data.filter(pl.col("station.id").is_duplicated())
    if not duplicates.is_empty():
        duplicate_id = duplicates["station.id"].item(0)
        raise FatalContractError(f"ThaiWater native table contains duplicate station.id {duplicate_id}")


def build_products() -> ProductCatalog:
    rows = []
    for product_id, declared in source_config().products.items():
        coordinates = declared.coordinates.value
        if not isinstance(coordinates, ThThaiWaterSourceCoordinates):
            raise FatalContractError("th_thaiwater product has invalid source coordinates")
        rows.append(
            product_row(
                str(PROVIDER_ID),
                str(product_id),
                str(coordinates.native_field),
                SERIES_MAPPINGS[product_id].physical_facts(),
            )
        )
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(native_table: NativeTable) -> StationCatalog:
    return native_table.data.select(
        pl.lit(str(PROVIDER_ID)).alias("provider_id"),
        pl.col("station.id").alias("station_id"),
        pl.col("station.tele_station_lat").cast(STATION_CATALOG_SCHEMA.polars_schema["latitude"]).alias("latitude"),
        pl.col("station.tele_station_long").cast(STATION_CATALOG_SCHEMA.polars_schema["longitude"]).alias("longitude"),
        pl.lit("unknown").alias("crs"),
    ).sort("station_id")


def build_station_products(
    stations: StationCatalog,
    availability_evidence: GraphAvailabilityEvidence,
) -> StationProductCatalog:
    if {pair.station_id for pair in availability_evidence.pairs} != set(stations["station_id"]):
        raise FatalContractError("ThaiWater availability evidence station population differs from native table")
    rows = []
    for pair in availability_evidence.pairs:
        retrieved_at = pair.acquisition.retrieved_at_start
        if retrieved_at is None:
            raise FatalContractError("ThaiWater graph acquisition has no retrieval instant")
        rows.append(
            {
                "provider_id": PROVIDER_ID,
                "station_id": pair.station_id,
                "product_id": pair.product_id,
                "availability": pair.availability,
                "availability_reason": pair.availability_reason,
                "published_record_start_date": None,
                "published_record_end_date": None,
                "last_catalogue_check": retrieved_at.date(),
            }
        )
    return (
        pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema)
        .with_columns(pl.col("availability").cast(AvailabilityDtype))
        .sort("station_id", "product_id")
    )


def build_provider_info(
    catalogue_date: date,
) -> dict[str, object]:
    return {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": (
            "true: graph responses co-publish stage and discharge fields; "
            "public retrieval requests each product and source sub-window separately, "
            "with at most 365 inclusive calendar dates per source request"
        ),
        "catalogue_version": catalogue_date.isoformat(),
        "license": None,
        "citation": None,
    }


def validate_generated_catalogue(
    provider_info: dict[str, object],
    products: ProductCatalog,
    stations: StationCatalog,
    station_products: StationProductCatalog,
    acquisition_provenance: AcquisitionProvenance,
) -> PackagedCatalogArtifact:
    provider_info_df = pl.DataFrame([provider_info], schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema)
    validate_catalogue(provider_info_df, PROVIDER_INFO_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(products, PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(stations, STATION_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(station_products, STATION_PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    return packaged_catalogue_artifact_from_components(
        provider_info,
        products,
        stations,
        station_products,
        acquisition_provenance=acquisition_provenance,
        on_issue="raise",
        withheld_rows_already_applied=True,
    )


def write_catalogue(catalogue: GeneratedThThaiWaterCatalogue, out_dir: Path | str) -> None:
    from rivretrieve._internal.catalogues.artifact import REQUIRED_ARTIFACT_FILES
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.th_thaiwater.origins import STATION_CATALOGUE_ORIGINS

    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as f:
        json.dump(catalogue.public_artifact.provider_info, f, sort_keys=True, separators=(",", ":"))
        f.write("\n")
    catalogue.public_artifact.products.write_parquet(output_path / "products.parquet")
    catalogue.public_artifact.stations.write_parquet(output_path / "stations.parquet")
    catalogue.public_artifact.station_products.write_parquet(output_path / "station_products.parquet")
    metadata = build_catalogue_metadata(
        catalogue.acquisition_provenance,
        (STATION_CATALOGUE_ORIGINS,),
        {name: (output_path / name).read_bytes() for name in REQUIRED_ARTIFACT_FILES},
        source_config=source_config(),
        source_mappings=SERIES_MAPPINGS,
    )
    for name, content in metadata.items():
        (output_path / name).write_bytes(content)


def _read_fixture_json(path: Path) -> dict[str, object]:
    try:
        with path.open(encoding="utf-8") as f:
            value = json.load(f)
    except OSError as exc:
        raise FatalContractError(f"Unable to read ThaiWater metadata fixture: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError(f"ThaiWater metadata fixture is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FatalContractError("ThaiWater metadata fixture must contain a JSON object")
    return cast("dict[str, object]", value)


def _read_live_json(url: str) -> dict[str, object]:
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            if response.status < 200 or response.status >= 300:
                raise FatalContractError(f"ThaiWater metadata live request failed with HTTP {response.status}")
            value = json.load(response)
    except OSError as exc:
        raise FatalContractError("ThaiWater metadata live request failed") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError("ThaiWater metadata live response is not valid JSON") from exc
    if not isinstance(value, dict):
        raise FatalContractError("ThaiWater metadata live response must contain a JSON object")
    return cast("dict[str, object]", value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh or build the packaged th_thaiwater catalogue.")
    parser.add_argument("--fixture", type=Path, help="Path to a ThaiWater waterlevel_load JSON fixture.")
    parser.add_argument("--live", action="store_true", help="Fetch the live ThaiWater metadata endpoint.")
    parser.add_argument(
        "--availability-evidence", type=Path, help="Required reviewed graph availability ledger for build mode."
    )
    parser.add_argument("--native", type=Path, help="Path to the committed native Parquet table.")
    parser.add_argument("--out", type=Path, help="Output directory for provider.json and parquet files.")
    parser.add_argument("--native-out", type=Path, help="Output path for the native Parquet table.")
    parser.add_argument("--retrieved-at")
    args = parser.parse_args(argv)

    if args.out is not None and args.native_out is not None:
        parser.error("choose exactly one ThaiWater destination: --out or --native-out")
    if args.out is None and args.native_out is None:
        parser.error("choose exactly one ThaiWater destination: --out or --native-out")

    if args.out is not None:
        if args.fixture is not None or args.live:
            parser.error("--fixture/--live cannot be used with --out")
        if args.native is None:
            parser.error("--out requires --native")
        if args.retrieved_at is not None:
            parser.error("--retrieved-at is only valid with refresh mode")
        if args.availability_evidence is None:
            parser.error("--out requires --availability-evidence")
        from rivretrieve._internal.providers.th_thaiwater.origins import (
            NATIVE_TABLE_BYTE_SIZE,
            NATIVE_TABLE_SHA256,
            STATION_CATALOGUE_ORIGINS,
        )

        native_table = read_native_table(
            args.native,
            expected_sha256=NATIVE_TABLE_SHA256,
            expected_byte_size=NATIVE_TABLE_BYTE_SIZE,
        )
        availability_evidence = GraphAvailabilityEvidence(args.availability_evidence.read_bytes())
        catalogue = build_catalogue(native_table, STATION_CATALOGUE_ORIGINS, availability_evidence)
        verify_provenance_recordings(catalogue.acquisition_provenance, Path(__file__).resolve().parents[5])
        write_catalogue(catalogue, args.out)
        return 0

    if args.availability_evidence is not None:
        parser.error("--availability-evidence is only valid with build mode")
    if args.native is not None:
        parser.error("--native cannot be used with --native-out")
    if (args.fixture is None) == (not args.live):
        parser.error("choose exactly one ThaiWater source: --fixture or --live")
    if args.native_out is not None and args.retrieved_at is None:
        parser.error("--retrieved-at is required with --native-out")

    retrieved_at = _parse_retrieved_at(args.retrieved_at, parser)
    if args.live:
        native_outcome = refresh_native_table_from_live(retrieved_at=retrieved_at)
    else:
        native_outcome = refresh_native_table_from_fixture(args.fixture, retrieved_at=retrieved_at)
    if any(issue.severity == "error" for issue in native_outcome.issues):
        parser.error("ThaiWater native refresh returned issues; refusing to write")
    write_native_table(native_outcome.value, args.native_out)
    return 0


def _parse_retrieved_at(value: str, parser: argparse.ArgumentParser) -> RetrievedAt:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value) is None:
        parser.error("ThaiWater --retrieved-at must be UTC in YYYY-MM-DDTHH:MM:SSZ form")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        parser.error("ThaiWater --retrieved-at must be UTC in YYYY-MM-DDTHH:MM:SSZ form")
    return RetrievedAt(parsed)


if __name__ == "__main__":
    raise SystemExit(main())
