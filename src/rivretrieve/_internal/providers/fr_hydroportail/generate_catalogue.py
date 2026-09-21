"""Build the station-own HydroPortail catalogue from its public entity search."""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import math
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Literal

import polars as pl

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    EvidenceReference,
    NativeTableIdentity,
    RecordingReference,
    verify_provenance_recordings,
)
from rivretrieve._internal.catalogue_origins import OriginDeclarations, enforce_catalogue_origins
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, stamp_native_table
from rivretrieve._internal.catalogues.products import product_row
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
)
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import AvailabilityAcquisition, FranceAvailability

PROVIDER_ID = ProviderId("fr_hydroportail")
PRODUCTS = ("discharge_instantaneous", "stage_instantaneous")


@dataclass(frozen=True)
class StationProductAvailability:
    station_id: str
    product_id: str
    status: Literal["history_unchecked", "available", "empty_in_both_history_windows", "history_check_failed"]
    acquisitions: tuple[AvailabilityAcquisition, ...] = ()
    witness_points: int | None = None

    def __post_init__(self) -> None:
        if not self.station_id or self.product_id not in PRODUCTS:
            raise ValueError("invalid HydroPortail station/product")
        if any(a.role != "historical_check" for a in self.acquisitions):
            raise ValueError("HydroPortail availability cannot use Hub’Eau counts")
        if self.status == "history_unchecked":
            if self.acquisitions or self.witness_points is not None:
                raise ValueError("unchecked history cannot carry observation conclusions")
        elif not self.acquisitions:
            raise ValueError("checked history requires acquisitions")
        if self.status == "available" and (self.witness_points is None or self.witness_points <= 0):
            raise ValueError("availability requires positive native witness")

    @property
    def reason(self) -> str:
        return {
            "history_unchecked": "HydroPortail public station membership; raw Q/H observation history unchecked.",
            "available": "HydroPortail raw station series has a dated positive historical witness; no continuity assertion.",
            "empty_in_both_history_windows": "HydroPortail raw station series was empty in the two recorded request windows; other history unknown.",
            "history_check_failed": "HydroPortail raw station history request failed; retained successful empty scopes do not establish absence.",
        }[self.status]


def project_availability(
    station_ids: tuple[str, ...], historical: FranceAvailability
) -> tuple[StationProductAvailability, ...]:
    prior = {(p.code_station, p.product_id): p for p in historical.pairs if p.product_id in PRODUCTS}
    result = []
    for station in station_ids:
        for product in PRODUCTS:
            old = prior.get((station, product))
            history = tuple(a for a in old.acquisitions if a.role == "historical_check") if old else ()
            if not history:
                result.append(StationProductAvailability(station, product, "history_unchecked"))
            elif old is not None and old.basis == "historical_positive_witness":
                result.append(
                    StationProductAvailability(
                        station, product, "available", history, old.published_count_or_new_witness_points
                    )
                )
            else:
                status = (
                    "history_check_failed"
                    if any(a.http_status != 200 for a in history)
                    else "empty_in_both_history_windows"
                )
                result.append(StationProductAvailability(station, product, status, history))
    return tuple(result)


def decode_inventory(body: bytes, retrieved_at: RetrievedAt) -> NativeTable:
    """Preserve full codes, published parent relationship and station coordinates."""
    sites = json.loads(body)
    if not isinstance(sites, list) or not sites:
        raise ValueError("HydroPortail search must contain a nonempty site array")
    rows = []
    sites_seen: set[str] = set()
    stations_seen: set[str] = set()
    for site in sites:
        if not isinstance(site, dict) or site.get("entityType") != "site":
            raise ValueError("invalid native site")
        site_id = site.get("bookmarkCode")
        if not isinstance(site_id, str) or not site_id.strip() or site_id in sites_seen:
            raise ValueError("missing or duplicate native site code")
        sites_seen.add(site_id)
        stations = site.get("stations")
        if not isinstance(stations, list):
            raise ValueError("native site stations must be an array")
        for station in stations:
            if not isinstance(station, dict) or station.get("entityType") != "station":
                raise ValueError("invalid native station")
            station_id = station.get("bookmarkCode")
            if not isinstance(station_id, str) or not station_id.strip() or station_id in stations_seen:
                raise ValueError("missing or duplicate native station code")
            stations_seen.add(station_id)
            if (
                not isinstance(station.get("label"), str)
                or station.get("entityStatus") not in {"active", "closed", "inactive"}
                or type(station.get("isEntityAccessLimited")) is not bool
            ):
                raise ValueError("invalid native station metadata")
            coordinates = station.get("coordinates")
            if not isinstance(coordinates, dict) or not {"x", "y"} <= coordinates.keys():
                raise ValueError("native station coordinates must be an object")
            x, y = coordinates.get("x"), coordinates.get("y")
            for value, bound in ((x, 180), (y, 90)):
                if value is not None and (
                    type(value) not in (int, float) or not math.isfinite(value) or abs(value) > bound
                ):
                    raise ValueError("invalid native geographic coordinate")
            rows.append(
                {
                    "bookmarkCode": station_id,
                    "site_code": site_id,
                    "label": station.get("label"),
                    "entityStatus": station.get("entityStatus"),
                    "x": x,
                    "y": y,
                    "station_json": json.dumps(station, ensure_ascii=False, separators=(",", ":")),
                    "site_json": json.dumps(
                        {k: v for k, v in site.items() if k != "stations"}, ensure_ascii=False, separators=(",", ":")
                    ),
                }
            )
    if not rows:
        raise ValueError("native inventory has no stations")
    return stamp_native_table(
        pl.DataFrame(rows).with_columns(pl.col("x", "y").cast(pl.Float64)).sort("bookmarkCode"), retrieved_at
    )


def read_inventory(body_path: Path, receipt_path: Path) -> tuple[NativeTable, dict]:
    body = body_path.read_bytes()
    receipt = json.loads(receipt_path.read_bytes())
    if (
        receipt["status"] != 200
        or receipt["bytes"] != len(body)
        or receipt["sha256"] != hashlib.sha256(body).hexdigest()
    ):
        raise ValueError("native inventory acquisition identity mismatch")
    return decode_inventory(body, RetrievedAt(datetime.fromisoformat(receipt["retrieved_at"]))), receipt


@dataclass(frozen=True)
class GeneratedHydroportailCatalogue:
    provider_info: dict[str, object]
    products: pl.DataFrame
    stations: pl.DataFrame
    station_products: pl.DataFrame
    acquisition_provenance: AcquisitionProvenance
    public_artifact: PackagedCatalogArtifact
    origins: OriginDeclarations


def build_products() -> pl.DataFrame:
    from rivretrieve._internal.providers.fr_hydroportail.config import SERIES_MAPPINGS

    return pl.DataFrame(
        [
            product_row(PROVIDER_ID, p, "Q" if p.startswith("discharge") else "H", SERIES_MAPPINGS[p].physical_facts())
            for p in PRODUCTS
        ],
        schema=PRODUCT_CATALOG_SCHEMA.polars_schema,
    )


def build_stations(native: NativeTable) -> pl.DataFrame:
    return native.data.select(
        pl.lit(PROVIDER_ID).alias("provider_id"),
        pl.col("bookmarkCode").alias("station_id"),
        pl.col("y").alias("latitude"),
        pl.col("x").alias("longitude"),
        pl.lit("EPSG:4326").alias("crs"),
    ).cast(STATION_CATALOG_SCHEMA.polars_schema)


def build_catalogue(
    native: NativeTable,
    origins: OriginDeclarations,
    historical: FranceAvailability,
    receipt: dict,
    documents: tuple[EvidenceReference, ...],
    native_identity: NativeTableIdentity,
) -> GeneratedHydroportailCatalogue:
    from rivretrieve._internal.catalogues.artifact import packaged_catalogue_artifact_from_components
    from rivretrieve._internal.providers.fr_hydroportail.origins import (
        build_acquisition_provenance,
    )

    pairs = project_availability(tuple(native.data["bookmarkCode"].to_list()), historical)
    stations = build_stations(native)
    enforce_catalogue_origins(PROVIDER_ID, origins, native, stations)
    buffer = BytesIO()
    native.data.write_parquet(buffer)
    material = buffer.getvalue()
    if hashlib.sha256(material).hexdigest() != native_identity.sha256 or len(material) != native_identity.byte_size:
        raise ValueError("native table differs from committed acquisition identity")

    products = build_products()
    acquired = datetime.fromisoformat(receipt["retrieved_at"])
    station_products = pl.DataFrame(
        [
            {
                "provider_id": PROVIDER_ID,
                "station_id": p.station_id,
                "product_id": p.product_id,
                "availability": "available" if p.status == "available" else "unknown",
                "availability_reason": p.reason,
                "published_record_start_date": None,
                "published_record_end_date": None,
                "last_catalogue_check": max((a.retrieved_at_start for a in p.acquisitions), default=acquired).date(),
            }
            for p in pairs
        ],
        schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema,
    )
    provider: dict[str, object] = {
        "provider_id": PROVIDER_ID,
        "name": "HydroPortail",
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "true: station-own raw Q/H queries; independent source failures retained",
        "catalogue_version": acquired.date().isoformat(),
        "license": None,
        "citation": None,
    }
    provenance = build_acquisition_provenance(native, pairs, receipt, documents, native_identity)
    artifact = packaged_catalogue_artifact_from_components(
        provider, products, stations, station_products, acquisition_provenance=provenance, on_issue="raise"
    )
    return GeneratedHydroportailCatalogue(provider, products, stations, station_products, provenance, artifact, origins)


def write_catalogue(catalogue: GeneratedHydroportailCatalogue, out: Path) -> None:
    from rivretrieve._internal.catalogues.artifact import REQUIRED_ARTIFACT_FILES
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.fr_hydroportail.config import SERIES_MAPPINGS, config

    out.mkdir(parents=True, exist_ok=True)
    artifact = catalogue.public_artifact
    (out / "provider.json").write_text(json.dumps(artifact.provider_info, ensure_ascii=False) + "\n")
    for name in ("stations", "products", "station_products"):
        getattr(artifact, name).write_parquet(out / f"{name}.parquet")
    metadata = build_catalogue_metadata(
        catalogue.acquisition_provenance,
        (catalogue.origins,),
        {name: (out / name).read_bytes() for name in REQUIRED_ARTIFACT_FILES},
        source_config=config(),
        source_mappings=SERIES_MAPPINGS,
    )
    for name, content in metadata.items():
        (out / name).write_bytes(content)


def main(argv: list[str] | None = None) -> int:
    from rivretrieve._internal.catalogues.native import read_native_table
    from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import decode_availability
    from rivretrieve._internal.providers.fr_hydroportail.origins import STATION_CATALOGUE_ORIGINS

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--native-revision", required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--availability-ledger", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    native = read_native_table(args.native)
    captured, receipt = read_inventory(
        args.evidence / "national-tests.body", args.evidence / "national-tests.receipt.json"
    )
    if not native.data.equals(captured.data):
        raise ValueError("committed native table differs from captured publisher inventory")
    material = args.native.read_bytes()
    identity = NativeTableIdentity(
        repository_path=args.native.resolve().relative_to(args.repository_root.resolve()).as_posix(),
        revision=args.native_revision,
        sha256=hashlib.sha256(material).hexdigest(),
        byte_size=len(material),
    )
    historical = decode_availability(lzma.decompress(args.availability_ledger.read_bytes()))
    documents = []
    for name, description in (
        ("about", "HydroPortail publication and PHyC platform"),
        ("legal", "HydroPortail public access and operator; reuse licence not established"),
        ("chunk-8529.fdb00780.js", "Module 71324 emits station x/y directly as GeoJSON longitude/latitude"),
    ):
        record = json.loads((args.evidence / f"{name}.receipt.json").read_bytes())
        documents.append(
            EvidenceReference(
                evidence_id=name,
                description=description,
                recording=RecordingReference(
                    recording_id=name,
                    repository_path=(args.evidence / f"{name}.body")
                    .resolve()
                    .relative_to(args.repository_root.resolve())
                    .as_posix(),
                    source_url=record["url"],
                    retrieved_at=datetime.fromisoformat(record["retrieved_at"]),
                    media_type=record["content_type"],
                    sha256=record["sha256"],
                ),
            )
        )
    catalogue = build_catalogue(native, STATION_CATALOGUE_ORIGINS, historical, receipt, tuple(documents), identity)
    verify_provenance_recordings(catalogue.acquisition_provenance, args.repository_root)
    write_catalogue(catalogue, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
