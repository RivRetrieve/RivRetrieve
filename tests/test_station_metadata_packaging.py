"""Installed station metadata remains offline and excludes native source tables."""

from __future__ import annotations

from tarfile import open as open_tar
from zipfile import ZipFile

import pytest

from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS
from tests._distribution import InstalledDistribution

_PROJECTIONS = tuple(
    f"rivretrieve/_internal/providers/{provider}/catalogue/station_metadata.parquet"
    for provider in BUILTIN_PROVIDER_IDS
)
_OBSOLETE_PROJECTION = "rivretrieve/_internal/catalogues/drainage_areas.parquet"


@pytest.mark.parametrize("installed_distribution", ["wheel", "sdist-wheel"], indirect=True)
def test_installed_station_metadata_offline(installed_distribution: InstalledDistribution) -> None:
    if installed_distribution.sdist is not None:
        with open_tar(installed_distribution.sdist, "r:gz") as archive:
            names = archive.getnames()
            assert not any(name.endswith("/native.parquet") for name in names)
            assert not any(name.endswith((".xlsx", ".eml")) for name in names)
            assert not any(name.endswith("/src/" + _OBSOLETE_PROJECTION) for name in names)
            for projection in _PROJECTIONS:
                assert any(name.endswith("/src/" + projection) for name in names)
    with ZipFile(installed_distribution.wheel) as wheel:
        assert _OBSOLETE_PROJECTION not in wheel.namelist()
        assert set(_PROJECTIONS) <= set(wheel.namelist())
        assert not any(name.endswith("/native.parquet") for name in wheel.namelist())
        assert not any(name.endswith((".xlsx", ".eml")) for name in wheel.namelist())
    installed_distribution.verify(_VERIFICATION)


_VERIFICATION = r"""
import json
import socket
import sys
from importlib import import_module
from importlib.resources import files
from pathlib import Path


def forbid_network(*args, **kwargs):
    raise AssertionError("Installed station metadata lookup attempted network access")


socket.socket.connect = forbid_network
socket.socket.connect_ex = forbid_network
socket.create_connection = forbid_network
socket.getaddrinfo = forbid_network

import polars as pl
from polars.testing import assert_frame_equal
import rivretrieve as rr

assert Path(rr.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), rr.__file__
assert "site-packages" in Path(rr.__file__).parts
catalogues = files("rivretrieve._internal.catalogues")
assert not catalogues.joinpath("drainage_areas.parquet").is_file()
assert not hasattr(rr, "drainage_areas")
provider_root = files("rivretrieve._internal.providers")
provider_ids = rr.providers()["provider_id"].to_list()
frames = []
selections = []
for provider_id in provider_ids:
    catalogue = provider_root.joinpath(provider_id, "catalogue")
    assert not catalogue.joinpath("native.parquet").is_file()
    assert catalogue.joinpath("station_metadata.parquet").is_file()
    stations = pl.read_parquet(catalogue.joinpath("stations.parquet"))
    station_id = "02GA010" if provider_id == "ca_eccc" else stations["station_id"][0]
    selection = rr.find(provider=provider_id, station=station_id)
    selections.append(rr.from_bundle(rr.to_bundle(selection)))
    frames.append(rr.metadata(selections[-1], view="source"))
    if provider_id in {"br_ana", "ca_eccc", "cz_chmi", "fr_hubeau", "jp_mlit", "lt_lhmt", "no_nve", "usgs_nwis"}:
        expected_notice = import_module(f"rivretrieve._internal.providers.{provider_id}.origins").STATION_METADATA_NOTICE
        assert isinstance(expected_notice, str) and expected_notice.strip()
        descriptor = rr.describe(provider_id)
        metadata_record = next(record for record in descriptor["recordSet"] if record["@id"] == "station_metadata")
        assert metadata_record["description"] == expected_notice

poland = rr.from_bundle(rr.to_bundle(rr.find(provider="pl_imgw")))
poland_source = rr.metadata(poland, view="source").filter(pl.col("attribute_role") == "drainage_area")
assert poland_source.height == 1301
assert set(poland_source["source_unit"]) == {"square kilometre"}
poland_summary = rr.metadata(poland)
assert poland_summary["drainage_area_unit"].to_list() == [["square kilometre"]] * 1301
assert_frame_equal(
    poland_summary.select("station_id", "drainage_area_field", "drainage_area_value", "drainage_area_unit")
    .explode("drainage_area_field", "drainage_area_value", "drainage_area_unit")
    .rename({"drainage_area_field": "source_field", "drainage_area_value": "source_value", "drainage_area_unit": "source_unit"})
    .sort("station_id"),
    poland_source.select("station_id", "source_field", "source_value", "source_unit").sort("station_id"),
)
elevations = rr.metadata(poland, view="source").filter(pl.col("attribute_role") == "elevation")
assert elevations.height == elevations["station_id"].n_unique() == 1301
assert set(elevations["source_field"]) == {"gauge_altitude"}
assert set(elevations["source_dtype"]) == {"String"}
assert set(elevations["source_unit"]) == {"m"}
assert set(elevations["state"]) == {"value"}
assert set(elevations["source_datum_dtype"]) == {"String"}
assert set(elevations["source_datum_field"]) == {"Vertical reference system"}
assert set(elevations["support_fact"]) == {"metadata.elevation.gauge_altitude"}
assert set(elevations["datum_support_fact"]) == {"metadata.elevation.gauge_altitude.datum"}
assert dict(elevations.group_by("source_datum").len().iter_rows()) == {
    "EVRF2007": 851, "Kronsztadt": 390, "ND": 60,
}
assert all(isinstance(json.loads(value), str) for value in elevations["source_value"])
assert elevations.filter(pl.col("source_value") == '"ND"').height == 60
assert elevations.filter((pl.col("source_value") == '"ND"') != (pl.col("source_datum") == "ND")).is_empty()
assert_frame_equal(
    poland_summary.select("station_id", "elevation_field", "elevation_value", "elevation_unit", "elevation_datum")
    .explode("elevation_field", "elevation_value", "elevation_unit", "elevation_datum")
    .rename({"elevation_field": "source_field", "elevation_value": "source_value",
             "elevation_unit": "source_unit", "elevation_datum": "source_datum"})
    .sort("station_id"),
    elevations.select("station_id", "source_field", "source_value", "source_unit", "source_datum").sort("station_id"),
)
actual = pl.concat(frames)
schema = pl.Schema({
    "provider_id": pl.String,
    "station_id": pl.String,
    "source_field": pl.String,
    "source_scope": pl.String,
    "source_value": pl.String,
    "source_dtype": pl.String,
    "source_unit": pl.String,
    "state": pl.Enum(["value", "source_null", "no_metadata"]),
    "attribute_role": pl.Enum(["station_name", "water_body_name", "drainage_area", "elevation"]),
    "support_fact": pl.String,
    "source_datum": pl.String,
    "source_datum_field": pl.String,
    "source_datum_dtype": pl.String,
    "datum_support_fact": pl.String,
})
assert actual.schema == schema
assert set(actual["provider_id"]) == set(provider_ids)
keys = ["provider_id", "station_id", "attribute_role", "source_field", "source_value", "support_fact"]
assert actual.unique(subset=keys).height == actual.height
assert_frame_equal(actual, pl.concat([rr.metadata(item, view="source") for item in selections]))
for value in actual["source_value"].drop_nulls():
    assert isinstance(json.loads(value), (str, int, float, bool))
assert actual.filter(pl.col("state") != "value")["source_value"].null_count() == actual.filter(
    pl.col("state") != "value"
).height
canada = actual.filter((pl.col("provider_id") == "ca_eccc") & (pl.col("attribute_role") == "drainage_area"))
gross = canada.filter(pl.col("source_field") == "DRAINAGE_AREA_GROSS").row(0, named=True)
assert gross["station_id"] == "02GA010"
assert gross["source_value"] == "1035.0"
assert json.loads(gross["source_value"]) == 1035.0
assert gross["source_dtype"] == "Float64"
assert gross["state"] == "value"
effective = canada.filter(pl.col("source_field") == "DRAINAGE_AREA_EFFECT").row(0, named=True)
assert effective["source_dtype"] == "Float64"
assert effective["source_value"] is None
assert effective["state"] == "source_null"
for provider, station, role, field, raw, numeric, unit, datum in [
    ("usgs_nwis", "07374000", "elevation", "alt_va", " 0.00", "0.00", "feet", "NAVD88"),
    ("jp_mlit", "301011281104010", "drainage_area", "流域面積", "142.00km2", "142.00", "km2", None),
    ("jp_mlit", "301011281104010", "elevation", "零点高", "0.000m", "0.000", "m", None),
    ("ba_fhmzbih", "4024", "drainage_area", "metadata_CATCHMENT_SIZE", "1600.00 km²", "1600.00", "km²", None),
    ("ch_foen", "2004", "drainage_area", "Catchment size", "713 km2", "713", "km2", None),
    ("ch_foen", "2004", "elevation", "Station altitude", "432 m a.s.l.", "432", "m", "LN02"),
]:
    gauge = rr.find(provider=provider, station=station)
    source = rr.metadata(gauge, view="source").filter(pl.col("source_field") == field).row(0, named=True)
    summary = rr.metadata(gauge).row(0, named=True)
    assert "station_name_alternatives" not in summary
    index = summary[f"{role}_field"].index(field)
    assert json.loads(source["source_value"]) == raw
    assert source["source_dtype"] == "String"
    assert summary[f"{role}_value"][index] == json.dumps(numeric)
    assert summary[f"{role}_unit"][index] == source["source_unit"] == unit
    if role == "elevation":
        assert summary["elevation_datum"][index] == source["source_datum"] == datum

empty = rr.pick(rr.pick(selection, quantity="discharge"), quantity="stage")
assert_frame_equal(rr.metadata(empty, view="source"), pl.DataFrame(schema=schema))
assert rr.metadata(empty).is_empty()
assert "station_name_alternatives" not in rr.metadata(empty).columns
"""
