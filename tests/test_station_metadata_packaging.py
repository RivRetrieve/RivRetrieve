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
            assert not any(name.endswith("/src/" + _OBSOLETE_PROJECTION) for name in names)
            for projection in _PROJECTIONS:
                assert any(name.endswith("/src/" + projection) for name in names)
    with ZipFile(installed_distribution.wheel) as wheel:
        assert _OBSOLETE_PROJECTION not in wheel.namelist()
        assert set(_PROJECTIONS) <= set(wheel.namelist())
        assert not any(name.endswith("/native.parquet") for name in wheel.namelist())
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

actual = pl.concat(frames)
schema = pl.Schema({
    "provider_id": pl.String,
    "station_id": pl.String,
    "source_field": pl.String,
    "source_value": pl.String,
    "source_dtype": pl.String,
    "source_unit": pl.String,
    "state": pl.Enum(["value", "source_null", "no_metadata"]),
    "attribute_role": pl.Enum(["station_name", "river_name", "drainage_area"]),
    "support_fact": pl.String,
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
empty = rr.pick(rr.pick(selection, quantity="discharge"), quantity="stage")
assert_frame_equal(rr.metadata(empty, view="source"), pl.DataFrame(schema=schema))
"""
