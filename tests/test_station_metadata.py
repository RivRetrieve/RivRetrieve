"""Synthetic station metadata contracts, independent of retained provider inputs."""

import json
import socket
from dataclasses import replace

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.station_metadata import (
    ATTRIBUTE_ROLES,
    SOURCE_METADATA_SCHEMA,
    STATION_METADATA_SCHEMA,
    source_metadata_frame,
    station_metadata_frame,
)


def attributes(provider="ca_eccc", station="02GA010"):
    rows = [
        (provider, station, "label", json.dumps(" Gauge "), "String", None, "value", "station_name", "station.label"),
        (provider, station, "river", json.dumps("River"), "String", None, "value", "river_name", "station.river"),
        (provider, station, "area", json.dumps("633.00 km²"), "String", None, "value", "drainage_area", "station.area"),
    ]
    return pl.DataFrame(rows, schema=SOURCE_METADATA_SCHEMA, orient="row")


def test_source_scalar_states_and_name_alternatives():
    source = attributes()
    extra = pl.DataFrame(
        [
            (
                "ca_eccc",
                "02GA010",
                "other_label",
                '"Gauge B"',
                "String",
                None,
                "value",
                "station_name",
                "station.other_label",
            ),
            ("ca_eccc", "02GA010", "blank", '"\u00a0"', "String", None, "value", "river_name", "station.blank"),
            (
                "ca_eccc",
                "02GA010",
                "null_area",
                None,
                "Float64",
                "km²",
                "source_null",
                "drainage_area",
                "station.null_area",
            ),
        ],
        schema=SOURCE_METADATA_SCHEMA,
        orient="row",
    )
    source = pl.concat([source, extra])
    keys = source.select("provider_id", "station_id").unique()
    actual = source_metadata_frame(pl.concat([keys, keys]), source)
    assert_frame_equal(
        actual,
        source.sort("provider_id", "station_id", "attribute_role", "source_field", "source_value", "support_fact"),
    )
    locations = pl.DataFrame(
        {
            "provider_id": ["ca_eccc"],
            "station_id": ["02GA010"],
            "latitude": [1.0],
            "longitude": [2.0],
            "crs": ["source CRS"],
        }
    )
    summary = station_metadata_frame(keys, actual, locations)
    expected = pl.DataFrame(
        [("ca_eccc", "02GA010", None, "River", 1.0, 2.0, "source CRS", True, False)],
        schema=STATION_METADATA_SCHEMA,
        orient="row",
    )
    assert_frame_equal(summary, expected)


def test_no_metadata_and_missing_geometry():
    source = pl.DataFrame(
        [("p", "001", None, None, None, None, "no_metadata", role, None) for role in ATTRIBUTE_ROLES],
        schema=SOURCE_METADATA_SCHEMA,
        orient="row",
    )
    keys = source.select("provider_id", "station_id").unique()
    actual = station_metadata_frame(keys, source_metadata_frame(keys, source), pl.DataFrame())
    expected = pl.DataFrame(
        [("p", "001", None, None, None, None, None, False, False)], schema=STATION_METADATA_SCHEMA, orient="row"
    )
    assert_frame_equal(actual, expected)


@pytest.mark.parametrize(
    "column,value",
    [
        ("source_value", "{}"),
        ("source_value", "null"),
        ("source_value", "NaN"),
        ("source_value", "invalid"),
        ("support_fact", None),
        ("state", "source_null"),
        ("state", "no_metadata"),
        ("source_value", "42"),
    ],
)
def test_invalid_projection_is_fatal(column, value):
    source = (
        attributes()
        .with_columns(
            pl.when(pl.col("attribute_role") == "station_name")
            .then(pl.lit(value))
            .otherwise(pl.col(column))
            .alias(column)
        )
        .cast(SOURCE_METADATA_SCHEMA)
    )
    with pytest.raises(FatalContractError):
        source_metadata_frame(source.select("provider_id", "station_id").unique(), source)


def test_missing_role_and_bad_schema_are_fatal():
    source = attributes()
    keys = source.select("provider_id", "station_id").unique()
    with pytest.raises(FatalContractError, match="absent"):
        source_metadata_frame(keys, source.filter(pl.col("attribute_role") != "river_name"))
    with pytest.raises(FatalContractError, match="schema"):
        source_metadata_frame(keys, pl.DataFrame())


def test_offline_public_api_mixed_scope(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("metadata must stay offline")

    selected = rr.pick(rr.find(), provider=["ca_eccc", "usgs_nwis"], station=["02GA010", "07374000"])
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(discovery, "_resolve_credentials", forbidden)
    monkeypatch.setattr(discovery, "dotenv_values", forbidden)
    keys = discovery._selection_station_keys(selected)
    frames = []
    for provider, station in keys.iter_rows():
        frame = attributes(provider, station)
        directory = tmp_path / provider / "catalogue"
        directory.mkdir(parents=True)
        frame.write_parquet(directory / "station_metadata.parquet")
        pl.DataFrame(
            {
                "provider_id": [provider, provider],
                "station_id": [station, "unselected"],
                "latitude": [None, 99.0],
                "longitude": [2.5, 100.0],
                "crs": ["source CRS", "other CRS"],
            },
            schema={
                "provider_id": pl.String,
                "station_id": pl.String,
                "latitude": pl.Float64,
                "longitude": pl.Float64,
                "crs": pl.String,
            },
        ).write_parquet(directory / "stations.parquet")
        frames.append(frame)
    monkeypatch.setattr(discovery, "files", lambda package: tmp_path)
    expected = pl.concat(frames).sort(
        "provider_id", "station_id", "attribute_role", "source_field", "source_value", "support_fact"
    )
    assert_frame_equal(rr.metadata(selected, view="source"), expected)
    summary = rr.metadata(selected)
    assert summary.height == keys.height == 2
    assert summary["station_name"].to_list() == [" Gauge "] * 2
    assert_frame_equal(rr.metadata(replace(selected, locations=()), view="source"), expected)
    expected_geometry = pl.DataFrame(
        {
            "latitude": [None, None],
            "longitude": [2.5, 2.5],
            "crs": ["source CRS", "source CRS"],
        },
        schema={"latitude": pl.Float64, "longitude": pl.Float64, "crs": pl.String},
    )
    assert_frame_equal(summary.select("latitude", "longitude", "crs"), expected_geometry)
    assert_frame_equal(rr.metadata(replace(selected, locations=())), summary)
    for provider in keys["provider_id"]:
        (tmp_path / provider / "catalogue" / "stations.parquet").unlink()
    assert_frame_equal(rr.metadata(selected, view="source"), expected)
    empty = rr.pick(selected, quantity="not-a-quantity")
    assert_frame_equal(rr.metadata(empty), pl.DataFrame(schema=STATION_METADATA_SCHEMA))
    assert_frame_equal(rr.metadata(empty, view="source"), pl.DataFrame(schema=SOURCE_METADATA_SCHEMA))
    with pytest.raises(ValueError, match="view"):
        rr.metadata(selected, view="invalid")
    with pytest.raises(TypeError, match="RivRetrieve selection"):
        rr.metadata(pl.DataFrame())


@pytest.mark.parametrize("values,expected", [(["", "\u00a0"], None), (["Name", "Name", ""], "Name")])
def test_blank_names_and_repeated_equal_names(values, expected):
    source = attributes().filter(pl.col("attribute_role") != "station_name")
    names = pl.DataFrame(
        [
            (
                "ca_eccc",
                "02GA010",
                f"label_{index}",
                json.dumps(value),
                "String",
                None,
                "value",
                "station_name",
                f"station.label_{index}",
            )
            for index, value in enumerate(values)
        ],
        schema=SOURCE_METADATA_SCHEMA,
        orient="row",
    )
    source = pl.concat([source, names])
    keys = source.select("provider_id", "station_id").unique()
    result = station_metadata_frame(keys, source_metadata_frame(keys, source), pl.DataFrame())
    assert result["station_name"].item() == expected
    assert result["station_name_alternatives"].item() is False


@pytest.mark.parametrize(
    "dtype,values",
    [
        (pl.String, ["633.00 km²", "", "\u00a0", None]),
        (pl.Int32, [1, 0, -3, None]),
        (pl.Int64, [9007199254740993, 0, -3, None]),
        (pl.UInt64, [18446744073709551615, 0, 3, None]),
        (pl.Float32, [1.25, 0.0, -3.5, None]),
        (pl.Float64, [1.25, 0.0, -3.5, None]),
        (pl.Boolean, [True, False, True, None]),
    ],
)
def test_projector_preserves_native_scalar_types(dtype, values):
    from datetime import UTC, datetime

    from rivretrieve._internal.catalogue_origins import Field, NativeColumn
    from rivretrieve._internal.catalogues.native import RetrievedAt, stamp_native_table
    from rivretrieve._internal.catalogues.station_metadata import MetadataField, build_station_metadata

    native = stamp_native_table(
        pl.DataFrame(
            {
                "id": ["001", "002", "003", "004", "outside"],
                "area": pl.Series(values + [None], dtype=dtype),
            }
        ),
        RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    stations = pl.DataFrame({"station_id": ["001", "002", "003", "004"]})
    result = build_station_metadata(
        "synthetic",
        native,
        stations,
        Field(NativeColumn("id")),
        (MetadataField("drainage_area", "area", "source unit"),),
    )
    areas = result.filter(pl.col("attribute_role") == "drainage_area")
    decoded = [None if item is None else json.loads(item) for item in areas["source_value"]]
    restored = pl.DataFrame({"id": areas["station_id"], "area": pl.Series(decoded, dtype=dtype)})
    assert_frame_equal(restored, native.data.select("id", "area").filter(pl.col("id") != "outside"))
    assert areas["source_dtype"].to_list() == [str(dtype)] * 4
    assert areas["source_unit"].to_list() == ["source unit"] * 4
    assert areas["support_fact"].to_list() == ["metadata.drainage_area.area"] * 4
    assert areas["state"].to_list() == ["value"] * 3 + ["source_null"]
    assert result.filter(pl.col("state") == "no_metadata").height == 8
    empty = build_station_metadata("synthetic", native, stations.clear(), Field(NativeColumn("id")), ())
    assert_frame_equal(empty, pl.DataFrame(schema=SOURCE_METADATA_SCHEMA))


@pytest.mark.parametrize("fault", ["duplicate_native", "missing_native", "nested", "nonfinite", "duplicate_field"])
def test_projector_rejects_invalid_inputs(fault):
    from datetime import UTC, datetime

    from rivretrieve._internal.catalogue_origins import Field, NativeColumn
    from rivretrieve._internal.catalogues.native import RetrievedAt, stamp_native_table
    from rivretrieve._internal.catalogues.station_metadata import MetadataField, build_station_metadata

    source = pl.DataFrame({"id": ["001"], "area": [1.0]})
    fields = (MetadataField("drainage_area", "area"),)
    if fault == "duplicate_native":
        source = pl.concat([source, source])
    elif fault == "missing_native":
        source = source.with_columns(pl.lit("other").alias("id"))
    elif fault == "nested":
        source = source.with_columns(pl.lit([1.0]).alias("area"))
    elif fault == "nonfinite":
        source = source.with_columns(pl.lit(float("nan")).alias("area"))
    else:
        fields = fields * 2
    native = stamp_native_table(source, RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC)))
    with pytest.raises(FatalContractError):
        build_station_metadata(
            "synthetic", native, pl.DataFrame({"station_id": ["001"]}), Field(NativeColumn("id")), fields
        )


def test_metadata_declarations_cover_providers_without_unreviewed_names():
    from importlib import import_module

    from rivretrieve._internal.catalogues.station_metadata import MetadataField
    from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS

    for provider in BUILTIN_PROVIDER_IDS:
        fields = import_module(f"rivretrieve._internal.providers.{provider}.origins").STATION_METADATA_FIELDS
        assert isinstance(fields, tuple)
        assert all(isinstance(field, MetadataField) for field in fields)
        if provider in ("ba_fhmzbih", "fr_hydroportail", "th_thaiwater", "ch_foen", "pl_imgw", "za_dws"):
            assert all(field.attribute_role == "drainage_area" for field in fields)
