"""drainage metadata build : PackagedNativeTables × StationCatalogues → PackagedDrainageMetadata.

Offline composition root. No catalogue acquisition or canonical-table changes.
"""

from __future__ import annotations

import argparse
import json
from importlib import import_module
from pathlib import Path

import polars as pl
from polars.testing import assert_frame_equal

from rivretrieve._internal.catalogue_origins import Field
from rivretrieve._internal.drainage_areas import DRAINAGE_AREA_SCHEMA
from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS

# Exact source fields and established units. Repository evidence and exclusions
# are recorded in docs/drainage-areas.md. None means no separate unit established;
# text embedded in a field name or value is retained, never parsed out.
AREA_FIELDS: dict[str, tuple[tuple[str, str | None], ...]] = {
    "ba_fhmzbih": (("metadata_CATCHMENT_SIZE", None),),
    "br_ana": (("Area_Drenagem", None),),
    "ca_eccc": (("DRAINAGE_AREA_GROSS", None), ("DRAINAGE_AREA_EFFECT", None)),
    "ch_foen": (),
    "cz_chmi": (("PLO_STA", "km²"),),
    "fr_hubeau": (("superficie_topo", None), ("superficie_reelle", None)),
    "jp_mlit": (("流域面積", None),),
    "lt_lhmt": (),
    "no_nve": (("drainageBasinArea", "km2"), ("drainageBasinAreaNorway", "km2")),
    "pl_imgw": (("area", None),),
    "th_thaiwater": (),
    "usgs_nwis": (("drain_area_va", "sq mi"), ("contrib_drain_area_va", None)),
    "za_dws": (("Catchment Area km**2", "km**2"),),
}


def main() -> None:
    """Read repository inputs and write or check the sole derived projection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Fail when the packaged projection differs from native inputs"
    )
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    provider_root = repository / "src/rivretrieve/_internal/providers"
    destination = repository / "src/rivretrieve/_internal/catalogues/drainage_areas.parquet"
    if set(AREA_FIELDS) != set(BUILTIN_PROVIDER_IDS):
        raise ValueError("Every built-in provider needs an explicit drainage-field review")
    rows: list[dict[str, object]] = []
    for provider in BUILTIN_PROVIDER_IDS:
        catalogue = provider_root / provider / "catalogue"
        stations = pl.read_parquet(catalogue / "stations.parquet")["station_id"].to_list()
        fields = AREA_FIELDS[provider]
        native = pl.read_parquet(catalogue / "native.parquet")
        origins = import_module(f"rivretrieve._internal.providers.{provider}.origins")
        # France has two station partitions, both keyed by code_station.
        if provider == "fr_hubeau":
            origin = origins.HYDROMETRY_STATION_CATALOGUE_ORIGINS["station_id"]
            if origin != origins.TEMPERATURE_STATION_CATALOGUE_ORIGINS["station_id"]:
                raise ValueError("France station partitions no longer share their native identity")
        else:
            origin = origins.STATION_CATALOGUE_ORIGINS["station_id"]
        if not isinstance(origin, Field):
            raise TypeError(f"{provider}: station identity must come from a native field")
        native_rows = {}
        for row in native.iter_rows(named=True):
            identity = origin.conversion.apply("station_id", origin.native_column, row)
            if not isinstance(identity, str) or identity in native_rows:
                raise ValueError(f"{provider}: invalid or duplicate native station identity {identity!r}")
            native_rows[identity] = row
        if not set(stations) <= set(native_rows):
            raise ValueError(f"{provider}: canonical station has no native identity")
        for station in stations:
            if not fields:
                rows.append({"provider_id": provider, "station_id": station, "state": "no_metadata"})
            for field, unit in fields:
                dtype = native.schema[field]
                if dtype not in (pl.String, pl.Float64):
                    raise TypeError(f"{provider}.{field}: unsupported source scalar type {dtype}")
                value = native_rows[station][field]
                rows.append(
                    {
                        "provider_id": provider,
                        "station_id": station,
                        "source_field": field,
                        "source_value": None
                        if value is None
                        else json.dumps(value, ensure_ascii=False, allow_nan=False),
                        "source_dtype": str(dtype),
                        "source_unit": unit,
                        "state": "source_null" if value is None else "value",
                    }
                )
    result = pl.DataFrame(rows, schema=DRAINAGE_AREA_SCHEMA).sort("provider_id", "station_id", "source_field")
    if args.check:
        assert_frame_equal(pl.read_parquet(destination), result)
        print(f"Drainage metadata matches native inputs: {result.height} rows")
    else:
        result.write_parquet(destination)
        print(f"Wrote {result.height} source metadata rows to {destination.relative_to(repository)}")


if __name__ == "__main__":
    main()
