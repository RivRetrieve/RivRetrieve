"""Installed drainage lookup : BuiltDistribution × StationSelection → DrainageAreaMetadata."""

from __future__ import annotations

from tarfile import open as open_tar
from zipfile import ZipFile

import pytest

from tests._distribution import InstalledDistribution

_PROJECTION = "rivretrieve/_internal/catalogues/drainage_areas.parquet"


@pytest.mark.parametrize("installed_distribution", ["wheel", "sdist-wheel"], indirect=True)
def test_installed_drainage_areas_offline(installed_distribution: InstalledDistribution) -> None:
    if installed_distribution.sdist is not None:
        with open_tar(installed_distribution.sdist, "r:gz") as archive:
            names = archive.getnames()
            assert not any(name.endswith("/native.parquet") for name in names)
            assert any(name.endswith("/src/" + _PROJECTION) for name in names)
    with ZipFile(installed_distribution.wheel) as wheel:
        assert _PROJECTION in wheel.namelist()
        assert not any(name.endswith("/native.parquet") for name in wheel.namelist())
    installed_distribution.verify(_VERIFICATION)


_VERIFICATION = r"""
import json
import socket
import sys
from importlib.resources import files
from pathlib import Path


def forbid_network(*args, **kwargs):
    raise AssertionError("Installed drainage-area lookup attempted network access")


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
assert catalogues.joinpath("drainage_areas.parquet").is_file()
provider_root = files("rivretrieve._internal.providers")
provider_ids = rr.providers()["provider_id"].to_list()
frames = []
selections = []
for provider_id in provider_ids:
    catalogue = provider_root.joinpath(provider_id, "catalogue")
    assert not catalogue.joinpath("native.parquet").is_file()
    stations = pl.read_parquet(catalogue.joinpath("stations.parquet"))
    station_id = "02GA010" if provider_id == "ca_eccc" else stations["station_id"][0]
    selection = rr.find(provider=provider_id, station=station_id)
    selections.append(rr.from_bundle(rr.to_bundle(selection)))
    frames.append(rr.drainage_areas(selections[-1]))

actual = pl.concat(frames)
schema = pl.Schema({
    "provider_id": pl.String,
    "station_id": pl.String,
    "source_field": pl.String,
    "source_value": pl.String,
    "source_dtype": pl.String,
    "source_unit": pl.String,
    "state": pl.Enum(["value", "source_null", "no_metadata"]),
})
assert actual.schema == schema
assert set(actual["provider_id"]) == set(provider_ids)
keys = ["provider_id", "station_id", "source_field"]
assert actual.unique(subset=keys).height == actual.height
assert_frame_equal(actual, pl.concat([rr.drainage_areas(item) for item in selections]))
for value in actual["source_value"].drop_nulls():
    assert isinstance(json.loads(value), (str, int, float, bool))
assert actual.filter(pl.col("state") != "value")["source_value"].null_count() == actual.filter(
    pl.col("state") != "value"
).height
canada = actual.filter(pl.col("provider_id") == "ca_eccc")
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
assert_frame_equal(rr.drainage_areas(empty), pl.DataFrame(schema=schema))
"""
