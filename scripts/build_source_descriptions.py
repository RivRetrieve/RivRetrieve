"""Rebuild packaged source descriptions from retained catalogue inputs (offline)."""

from __future__ import annotations

import argparse
import importlib
import json
from hashlib import sha256
from pathlib import Path

import polars as pl

from rivretrieve._internal.catalogues.artifact import _read_provenance_json, packaged_catalogue_artifact_from_components
from rivretrieve._internal.catalogues.schemas import CATALOGUE_SERIES_CLAIMS_SCHEMA
from rivretrieve._internal.catalogues.source_descriptions import (
    build_source_descriptions,
    content_identified_descriptions,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("src/rivretrieve/_internal/providers"))
    parser.add_argument(
        "--evidence-root", type=Path, required=True, help="External retained inputs in repository-relative layout"
    )
    args = parser.parse_args()
    for directory in sorted(args.root.glob("*/catalogue")):
        provider = directory.parent.name
        try:
            module = importlib.import_module(f"rivretrieve._internal.providers.{provider}.config")
        except ModuleNotFoundError as error:
            if error.name != f"rivretrieve._internal.providers.{provider}.config":
                raise
            module = None
        config = (module.config() if callable(module.config) else module.config) if module is not None else None
        artifact = packaged_catalogue_artifact_from_components(
            json.loads((directory / "provider.json").read_bytes()),
            pl.read_parquet(directory / "products.parquet"),
            pl.read_parquet(directory / "stations.parquet"),
            pl.read_parquet(directory / "station_products.parquet"),
            acquisition_provenance=_read_provenance_json(directory / "provenance.json"),
            withheld_rows_already_applied=True,
        )
        if provider in ("no_nve", "br_ana", "ch_foen", "ca_eccc", "pl_imgw", "usgs_nwis"):
            builder = importlib.import_module(
                f"rivretrieve._internal.providers.{provider}.catalogue_series"
            ).describe_catalogue
            if provider == "no_nve":
                descriptions = builder(
                    artifact,
                    native=pl.read_parquet(
                        args.evidence_root
                        / "src/rivretrieve/_internal/providers"
                        / provider
                        / "catalogue/native.parquet"
                    ),
                )
            elif provider in ("br_ana", "usgs_nwis"):
                descriptions = builder(artifact, config=config)
            else:
                descriptions = builder(artifact)
            descriptions = content_identified_descriptions(descriptions)
        else:
            descriptions = build_source_descriptions(
                artifact, config, mappings=getattr(module, "SERIES_MAPPINGS", None)
            )
        claims = pl.DataFrame(schema=CATALOGUE_SERIES_CLAIMS_SCHEMA.polars_schema)
        if provider == "usgs_nwis":
            from rivretrieve._internal.providers.usgs_nwis.catalogue_series import catalogue_claims
            from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import PRODUCT_DEFINITIONS

            claims = catalogue_claims(
                pl.read_parquet(
                    args.evidence_root / "src/rivretrieve/_internal/providers" / provider / "catalogue/native.parquet"
                ),
                {item.series_key: item.product_id for item in PRODUCT_DEFINITIONS},
            )
        claims.write_parquet(directory / "series_claims.parquet", compression="zstd", statistics=True)
        (directory / "source_series.json").write_text(descriptions.model_dump_json() + "\n")
        (directory / "format.json").write_text('{"catalogue_format_version":2}\n')
        descriptor_path = directory / "croissant.json"
        descriptor = json.loads(descriptor_path.read_bytes())
        descriptor["distribution"] = [
            item
            for item in descriptor["distribution"]
            if item["@id"] not in ("format.json", "source_series.json", "series_claims.parquet")
        ]
        for name in ("format.json", "source_series.json", "series_claims.parquet"):
            content = (directory / name).read_bytes()
            descriptor["distribution"].append(
                {
                    "@id": name,
                    "@type": "cr:FileObject",
                    "contentUrl": name,
                    "encodingFormat": "application/json" if name.endswith(".json") else "application/x-parquet",
                    "sha256": sha256(content).hexdigest(),
                    "contentSize": f"{len(content)} B",
                }
            )
        descriptor_path.write_text(json.dumps(descriptor, ensure_ascii=False, indent=2) + "\n")
        print(provider, len(descriptions.descriptions))


if __name__ == "__main__":
    main()
