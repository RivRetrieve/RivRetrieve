"""Export an offline browser snapshot from approved packaged catalogue products.

The wire format stores station and series tuples and shared physical-fact
profiles. Profiles retain knowledge states and segment boundaries, but omit
private evidence and per-segment identifiers. Coordinates are not rounded or
reprojected. A listed station does not establish observation availability.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path
from time import perf_counter

import polars as pl

from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.catalogues.source_series import catalogue_series
from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS
from rivretrieve._internal.providers.registration import BulkStore, CatalogueOnly, load_manifest
from rivretrieve._internal.source_series import SourceSeries, admission
from rivretrieve._internal.station_metadata import source_metadata_frame, station_metadata_frame

FACT_FIELDS = (
    "quantity",
    "frequency",
    "statistic",
    "temporal_support",
    "day_definition",
    "timestamp_anchor",
    "time_zone",
    "vertical_reference",
    "vertical_datum",
    "source_unit",
)


def encode_catalogue(providers: list[dict], stations: pl.DataFrame, series: Iterable[SourceSeries]) -> dict:
    """Compact metadata without changing identities, facts, unknowns or geometry.

    Parameters
    ----------
    providers
        Public capability records containing credential names, never values.
    stations
        Station summaries, including stations with no admitted observation series.
    series
        All catalogue series, including unsupported fact segments.

    Returns
    -------
    dict
        Version 2 wire data. Station tuples contain provider index, station ID,
        name, latitude, longitude, CRS and distinct nonblank water-body names in
        metadata order. Name spelling is unchanged. Series tuples contain station index,
        series ID, variant, published ID and physical-profile indices.
    """
    provider_indexes = {item["provider_id"]: index for index, item in enumerate(providers)}
    records = []
    station_indexes: dict[tuple[str, str], int] = {}
    if stations.height:
        s_cols = stations.select(
            "provider_id",
            "station_id",
            "station_name",
            "latitude",
            "longitude",
            "crs",
            "water_body_name_value",
        ).to_dict(as_series=False)
        for prov, sid, s_name, lat, lon, crs, wb_names in zip(
            s_cols["provider_id"],
            s_cols["station_id"],
            s_cols["station_name"],
            s_cols["latitude"],
            s_cols["longitude"],
            s_cols["crs"],
            s_cols["water_body_name_value"],
            strict=True,
        ):
            key = (prov, sid)
            if key in station_indexes:
                raise ValueError(f"Duplicate station identity: {key}")
            station_indexes[key] = len(records)
            records.append(
                [
                    provider_indexes[prov],
                    sid,
                    s_name,
                    lat,
                    lon,
                    crs,
                    list(dict.fromkeys(name for name in (wb_names or ()) if name and name.strip())),
                ]
            )
    facts = []
    fact_indexes: dict[str, int] = {}
    segment_index_cache: dict[int, tuple[object, int]] = {}
    series_records = []
    for item in series:
        references = []
        for segment in item.facts:
            seg_key = id(segment)
            cached_seg = segment_index_cache.get(seg_key)
            if cached_seg is None:
                profile = {
                    field: {"value": getattr(segment, field).value, "state": getattr(segment, field).state.value}
                    for field in FACT_FIELDS
                }
                profile["normalized_unit"] = segment.normalized_unit
                profile["admission"] = admission(segment).status
                key = json.dumps(profile, ensure_ascii=False, separators=(",", ":"))
                idx = fact_indexes.get(key)
                if idx is None:
                    idx = len(facts)
                    fact_indexes[key] = idx
                    facts.append(profile)
                segment_index_cache[seg_key] = (segment, idx)
            else:
                idx = cached_seg[1]
            references.append(idx)
        series_records.append(
            [
                station_indexes[(item.provider_id, item.station_id)],
                item.series_id,
                item.variant,
                item.identity.published_id,
                references,
            ]
        )
    return {"version": 2, "providers": providers, "stations": records, "facts": facts, "series": series_records}


def build_catalogue(output_path: Path) -> None:
    """Write public catalogue JSON offline, without resolving credentials or caches."""
    started = perf_counter()
    providers = []
    frames = []
    series = []
    for declared in load_manifest(BUILTIN_PROVIDER_IDS):
        declaration = declared.declaration
        artifact = load_packaged_catalogue_artifact(declaration.catalogue, on_issue="raise")
        if artifact.provider_info["provider_id"] != declared.provider_id:
            raise ValueError("Manifest and catalogue provider identities differ")
        providers.append(
            {
                "provider_id": declared.provider_id,
                "name": artifact.provider_info["name"],
                "retrieval": not isinstance(declaration.observations, CatalogueOnly),
                "bulk": isinstance(declaration.observations, BulkStore),
                "credentials": list(declaration.required_credentials),
            }
        )
        keys = artifact.stations.select("provider_id", "station_id")
        source = source_metadata_frame(keys, pl.read_parquet(declaration.catalogue / "station_metadata.parquet"))
        frames.append(station_metadata_frame(keys, source, artifact.stations))
        members, _ = catalogue_series(artifact)
        series.extend(members)
    payload = encode_catalogue(providers, pl.concat(frames), series)
    content = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    print(
        f"Exported {len(payload['stations']):,} stations, {len(series):,} series, "
        f"{len(payload['facts']):,} fact profiles; {output_path.stat().st_size:,} bytes "
        f"in {perf_counter() - started:.2f}s to {output_path}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "web/station-explorer/public/catalogue.json",
    )
    build_catalogue(parser.parse_args().output)
