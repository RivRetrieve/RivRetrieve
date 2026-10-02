"""Brazil catalogue : NativeTable × OriginDeclarations × AcquisitionProvenance → GeneratedBrAnaCatalogue."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import polars as pl

from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance, verified_provider_terms
from rivretrieve._internal.catalogue_origins import OriginDeclarations, enforce_catalogue_origins
from rivretrieve._internal.catalogues.artifact import (
    PackagedCatalogArtifact,
    packaged_catalogue_artifact_from_components,
)
from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
    ProductCatalog,
    StationCatalog,
    StationProductCatalog,
    validate_catalogue,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.br_ana.capture import AdoptedTelemetryEvidence, ConventionalDailyEvidence
from rivretrieve._internal.providers.br_ana.config import BrAnaDailySourceCoordinates, BrAnaSourceCoordinates, config

PROVIDER_ID = ProviderId("br_ana")
PROVIDER_NAME = "ANA Hidroweb — Brazilian National Water and Sanitation Agency"


@dataclass(frozen=True, slots=True)
class GeneratedBrAnaCatalogue:
    provider_info: dict[str, object]
    products: ProductCatalog
    stations: StationCatalog
    station_products: StationProductCatalog
    acquisition_provenance: AcquisitionProvenance
    public_artifact: PackagedCatalogArtifact
    origins: OriginDeclarations
    acquired_station_count: int
    pluviometric_station_count: int


def project_stations(native_table: NativeTable) -> NativeTable:
    """Select the river-gauge scope without altering the retained acquired inventory."""
    data = native_table.data
    if "Tipo_Estacao" not in data.columns:
        raise FatalContractError("br_ana native inventory lacks Tipo_Estacao")
    kinds = data["Tipo_Estacao"]
    if kinds.dtype != pl.String or kinds.null_count() or not set(kinds.to_list()) <= {"Fluviometrica", "Pluviometrica"}:
        raise FatalContractError("br_ana native inventory has an unexpected Tipo_Estacao")
    return NativeTable(data.filter(pl.col("Tipo_Estacao") == "Fluviometrica"))


def build_stations(native_table: NativeTable) -> StationCatalog:
    projected = project_stations(native_table)
    try:
        return projected.data.select(
            pl.lit(PROVIDER_ID).cast(pl.String).alias("provider_id"),
            pl.col("codigoestacao").cast(pl.String, strict=True).alias("station_id"),
            pl.col("Latitude").cast(pl.Float64, strict=True).alias("latitude"),
            pl.col("Longitude").cast(pl.Float64, strict=True).alias("longitude"),
            pl.lit("unknown").cast(pl.String).alias("crs"),
        ).sort("station_id")
    except pl.exceptions.PolarsError as exc:
        raise FatalContractError("br_ana native station identity or coordinates are invalid") from exc


def build_products(daily: ConventionalDailyEvidence | None = None) -> ProductCatalog:
    """Project established adopted-field and daily-mean facts at access-route grain."""
    rows = []
    for product, definition in config().products.items():
        coordinates = definition.coordinates.value
        if isinstance(coordinates, BrAnaDailySourceCoordinates):
            if daily is None:
                continue
            stage = coordinates.field_prefix == "Cota"
            native_id = (
                f"{coordinates.endpoint}/v1:{coordinates.field_prefix}_01..31;Mediadiaria=1;"
                f"{'nivelconsistencia' if stage else 'Nivel_Consistencia'}={coordinates.consistency}"
            )
        elif isinstance(coordinates, BrAnaSourceCoordinates):
            stage = coordinates.field == "Cota_Adotada"
            native_id = f"HidroinfoanaSerieTelemetricaAdotada/v1:{coordinates.field}"
        else:
            raise FatalContractError("ANA catalogue source coordinates are unsupported")
        daily_product = isinstance(coordinates, BrAnaDailySourceCoordinates)
        rows.append(
            {
                "provider_id": PROVIDER_ID,
                "product_id": product,
                "observed_property": "stage" if stage else "discharge",
                "frequency": "daily" if daily_product else "unknown",
                "statistic": "mean" if daily_product else "unknown",
                "period_type": "daily" if daily_product else "unknown",
                "period_anchor": "unknown",
                "unit": "m" if stage else "m3/s",
                "native_id": native_id,
            }
        )
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_station_products(
    native: NativeTable, telemetry: AdoptedTelemetryEvidence, daily: ConventionalDailyEvidence | None = None
) -> StationProductCatalog:
    """Fluviometric inventory candidates × observed evidence → truthful availability rows."""
    rows = []
    for station, retrieved_at in native.data.select("codigoestacao", "retrieved_at").iter_rows():
        if not isinstance(station, str) or not isinstance(retrieved_at, datetime):
            raise FatalContractError("ANA station-product candidate identity or acquisition time is invalid")
        for product, definition in config().products.items():
            is_telemetry = isinstance(definition.coordinates.value, BrAnaSourceCoordinates)
            if not is_telemetry and daily is None:
                continue
            observed = (
                (station, product) in telemetry.available_pairs
                if is_telemetry
                else daily is not None and (station, product) in daily.available_pairs
            )
            checked_at = telemetry.observations.retrieved_at
            if not is_telemetry and daily is not None and observed:
                checked_at = max(ref.retrieved_at for ref, pairs in daily.observations if (station, product) in pairs)
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station,
                    "product_id": product,
                    "availability": "available" if observed else "unknown",
                    "availability_reason": (
                        (
                            "Non-null numbered day slot with Mediadiaria=1 and exact source consistency variant; no other variant, continuity or complete record implied"
                            if observed
                            else "Fluviometrica inventory candidate; exact daily source variant availability is unacquired, not source silence"
                        )
                        if not is_telemetry
                        else (
                            "Non-null adopted measurements present in the retained source request; this establishes neither continuous nor complete record"
                            if observed
                            else "Fluviometrica inventory candidate; inventory membership does not establish adopted-endpoint product availability; per-station endpoint evidence is not acquired"
                        )
                    ),
                    "published_record_start_date": None,
                    "published_record_end_date": None,
                    "last_catalogue_check": max(retrieved_at, checked_at).date() if observed else retrieved_at.date(),
                }
            )
    return pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).sort("station_id", "product_id")


def build_catalogue(
    native_table: NativeTable,
    origins: OriginDeclarations,
    provenance: AcquisitionProvenance,
    telemetry: AdoptedTelemetryEvidence | None = None,
    daily: ConventionalDailyEvidence | None = None,
) -> GeneratedBrAnaCatalogue:
    """Build attested identity and geometry, plus products with supplied reviewed source evidence."""
    if daily is not None and telemetry is None:
        raise FatalContractError("ANA daily catalogue extension requires the certified telemetry evidence")
    projected = project_stations(native_table)
    stations = build_stations(native_table)
    enforce_catalogue_origins(PROVIDER_ID, origins, projected, stations)
    maximum = native_table.data["retrieved_at"].max()
    if not isinstance(maximum, datetime):
        raise FatalContractError("br_ana native inventory has no retrieval instant")
    terms = verified_provider_terms(provenance.source_records, provenance.fact_bindings, provenance.withheld_facts)
    provider_info: dict[str, object] = {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": (
            "false: authenticated adopted telemetry and conventional daily Bruto/Consistido means; temperature unsupported"
            if daily is not None
            else "false: authenticated adopted telemetry; conventional daily and temperature unsupported pending source semantics"
            if telemetry is not None
            else "false: catalogue-only; observation product semantics remain withheld"
        ),
        "catalogue_version": maximum.date().isoformat(),
        "license": terms.get("license"),
        "citation": terms.get("citation"),
    }
    products = pl.DataFrame(schema=PRODUCT_CATALOG_SCHEMA.polars_schema)
    station_products = pl.DataFrame(schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema)
    if telemetry is not None:
        products = build_products(daily)
        station_products = build_station_products(projected, telemetry, daily)
    for frame, schema in (
        (
            pl.DataFrame([provider_info], schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema),
            PROVIDER_INFO_CATALOG_SCHEMA,
        ),
        (stations, STATION_CATALOG_SCHEMA),
        (products, PRODUCT_CATALOG_SCHEMA),
        (station_products, STATION_PRODUCT_CATALOG_SCHEMA),
    ):
        validate_catalogue(frame, schema, on_issue="raise")
    artifact = packaged_catalogue_artifact_from_components(
        provider_info, products, stations, station_products, acquisition_provenance=provenance, on_issue="raise"
    )
    return GeneratedBrAnaCatalogue(
        provider_info,
        products,
        stations,
        station_products,
        provenance,
        artifact,
        origins,
        native_table.data.height,
        native_table.data.height - projected.data.height,
    )


def write_catalogue(catalogue: GeneratedBrAnaCatalogue, out_dir: Path) -> None:
    from functools import partial

    from rivretrieve._internal.catalogues.artifact import REQUIRED_ARTIFACT_FILES
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.br_ana.catalogue_series import describe_catalogue
    from rivretrieve._internal.providers.br_ana.config import config as source_config

    out_dir.mkdir(parents=True, exist_ok=True)
    artifact = catalogue.public_artifact
    (out_dir / "provider.json").write_text(
        json.dumps(artifact.provider_info, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    artifact.products.write_parquet(out_dir / "products.parquet")
    artifact.stations.write_parquet(out_dir / "stations.parquet")
    artifact.station_products.write_parquet(out_dir / "station_products.parquet")
    metadata = build_catalogue_metadata(
        catalogue.acquisition_provenance,
        (catalogue.origins,),
        {name: (out_dir / name).read_bytes() for name in REQUIRED_ARTIFACT_FILES},
        source_config=source_config(),
        source_describer=partial(describe_catalogue, config=source_config()),
    )
    for name, content in metadata.items():
        (out_dir / name).write_bytes(content)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the ANA catalogue offline from its attested native inventory.", allow_abbrev=False
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--native", type=Path)
    source.add_argument("--materialize-record", type=Path)
    parser.add_argument("--capture-record", type=Path)
    parser.add_argument("--native-out", type=Path)
    parser.add_argument(
        "--evidence-root",
        "--repository-root",
        dest="evidence_root",
        type=Path,
        required=True,
        help="External retained inputs in repository-relative layout",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.materialize_record is not None:
        from rivretrieve._internal.catalogues.native import write_native_table
        from rivretrieve._internal.providers.br_ana.capture import (
            materialize_captured_native_table,
            read_capture_record,
        )

        if args.native_out is None or args.out is not None or args.capture_record is not None:
            parser.error("--materialize-record requires --native-out and cannot use --out or --capture-record")
        capture = read_capture_record(args.materialize_record)
        native = materialize_captured_native_table(capture, args.evidence_root)
        write_native_table(native, args.native_out)
        return 0
    if args.out is None or args.native_out is not None:
        parser.error("--native requires --out and cannot use --native-out")
    from rivretrieve._internal.catalogues.native import read_native_table
    from rivretrieve._internal.providers.br_ana.capture import read_capture_record, verify_native_identity
    from rivretrieve._internal.providers.br_ana.origins import STATION_CATALOGUE_ORIGINS, build_acquisition_provenance

    capture_path = args.capture_record or args.evidence_root / "tests/test_data/br_ana_inventory/capture.json"
    capture = read_capture_record(capture_path)
    native = read_native_table(
        args.native,
        expected_sha256=capture.native_table.sha256,
        expected_byte_size=capture.native_table.byte_size,
    )
    verify_native_identity(capture, args.native.read_bytes(), native)
    from rivretrieve._internal.providers.br_ana.capture import parse_adopted_telemetry_evidence
    from rivretrieve._internal.providers.br_ana.origins import with_observation_products
    from rivretrieve._internal.recordings import read_recording

    evidence_root = args.evidence_root / "tests/recordings/br_ana"
    recording_path = evidence_root / "telemetry_15400000_2024-01-04_DIAS_30.recording.json"
    telemetry = parse_adopted_telemetry_evidence(
        (evidence_root / "manual-page11-acquisition.json").read_bytes(),
        (evidence_root / "manual-page11-derived.txt").read_bytes(),
        read_recording(recording_path),
        str(recording_path.relative_to(args.evidence_root)),
    )
    from rivretrieve._internal.providers.br_ana.capture import parse_conventional_daily_evidence

    daily = parse_conventional_daily_evidence(
        {
            name: (evidence_root / name).read_bytes()
            for name in (
                "hidro-1.4-conventional-dictionary-derived.json",
                "hidro-sqlserver-selected-views-derived.json",
                "hidro-extraction-manifest.json",
                "daily-source-comparison-report.md",
                "daily-correspondence-identities.json",
                "paired-stage-2020-comparison.json",
                "paired-stage-2024-comparison.json",
                "paired-discharge-2020-comparison.json",
                "paired-discharge-2024-comparison.json",
            )
        },
        tuple(
            (str(path.relative_to(args.evidence_root)), read_recording(path))
            for path in (
                evidence_root / f"{endpoint}_15400000_{start}_{stop}.recording.json"
                for endpoint in ("HidroSerieCotas", "HidroSerieVazao")
                for start, stop in (
                    ("2020-01-01", "2020-01-31"),
                    ("2024-01-01", "2024-01-31"),
                    ("2024-02-01", "2024-02-29"),
                )
            )
        ),
        tuple(
            (str(path.relative_to(args.evidence_root)), read_recording(path))
            for path in sorted((evidence_root / "correspondence").glob("*.recording.json"))
        ),
    )
    provenance = with_observation_products(
        build_acquisition_provenance(capture), capture, project_stations(native).data, telemetry, daily
    )
    catalogue = build_catalogue(native, STATION_CATALOGUE_ORIGINS, provenance, telemetry, daily)
    write_catalogue(catalogue, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
