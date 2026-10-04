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


def source_frame(rows):
    columns = [
        "provider_id",
        "station_id",
        "source_field",
        "source_value",
        "source_dtype",
        "source_unit",
        "state",
        "attribute_role",
        "support_fact",
    ]
    return pl.DataFrame([dict(zip(columns, row, strict=True)) for row in rows], schema=SOURCE_METADATA_SCHEMA)


def attributes(provider="ca_eccc", station="02GA010"):
    rows = [
        (provider, station, "label", json.dumps(" Gauge "), "String", None, "value", "station_name", "station.label"),
        (provider, station, "river", json.dumps("River"), "String", None, "value", "water_body_name", "station.river"),
        (
            provider,
            station,
            "area",
            json.dumps("633.00 km²", ensure_ascii=False),
            "String",
            None,
            "value",
            "drainage_area",
            "station.area",
        ),
    ]
    rows.append((provider, station, None, None, None, None, "no_metadata", "elevation", None))
    return source_frame(rows)


def test_source_scalar_states_and_name_alternatives():
    source = attributes()
    extra = source_frame(
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
            ("ca_eccc", "02GA010", "blank", '"\u00a0"', "String", None, "value", "water_body_name", "station.blank"),
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
        [
            {
                "provider_id": "ca_eccc",
                "station_id": "02GA010",
                "station_name": None,
                "latitude": 1.0,
                "longitude": 2.0,
                "crs": "source CRS",
                "water_body_name_field": ["blank", "river"],
                "water_body_name_value": ["\u00a0", "River"],
                "drainage_area_field": ["area", "null_area"],
                "drainage_area_value": ['"633.00 km²"', None],
                "drainage_area_unit": [None, "km²"],
            }
        ],
        schema=STATION_METADATA_SCHEMA,
    )
    assert_frame_equal(summary, expected)


def test_no_metadata_and_missing_geometry():
    source = source_frame(
        [("p", "001", None, None, None, None, "no_metadata", role, None) for role in ATTRIBUTE_ROLES],
    )
    keys = source.select("provider_id", "station_id").unique()
    actual = station_metadata_frame(keys, source_metadata_frame(keys, source), pl.DataFrame())
    expected = pl.DataFrame([{"provider_id": "p", "station_id": "001"}], schema=STATION_METADATA_SCHEMA)
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
        source_metadata_frame(keys, source.filter(pl.col("attribute_role") != "water_body_name"))
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
    assert "station_name_alternatives" not in summary.columns
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
    assert "station_name_alternatives" not in rr.metadata(empty).columns
    assert_frame_equal(rr.metadata(empty), pl.DataFrame(schema=STATION_METADATA_SCHEMA))
    assert_frame_equal(rr.metadata(empty, view="source"), pl.DataFrame(schema=SOURCE_METADATA_SCHEMA))
    with pytest.raises(ValueError, match="view"):
        rr.metadata(selected, view="invalid")
    with pytest.raises(TypeError, match="RivRetrieve selection"):
        rr.metadata(pl.DataFrame())


@pytest.mark.parametrize(
    "values,expected",
    [
        (["", "\u00a0"], None),
        (["Name", "Name", ""], "Name"),
        ([" Rivière ", ""], " Rivière "),
        (["Name", "Other"], None),
    ],
)
def test_blank_names_and_repeated_equal_names(values, expected):
    source = attributes().filter(pl.col("attribute_role") != "station_name")
    names = source_frame(
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
    )
    source = pl.concat([source, names])
    keys = source.select("provider_id", "station_id").unique()
    result = station_metadata_frame(keys, source_metadata_frame(keys, source), pl.DataFrame())
    assert result["station_name"].item() == expected
    assert "station_name_alternatives" not in result.columns
    assert_frame_equal(source_metadata_frame(keys, source).filter(pl.col("attribute_role") == "station_name"), names)


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
@pytest.mark.parametrize("role", ["drainage_area", "elevation"])
def test_projector_preserves_native_scalar_types(dtype, values, role):
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
        (MetadataField(role, "area", "source unit"),),
    )
    areas = result.filter(pl.col("attribute_role") == role)
    decoded = [None if item is None else json.loads(item) for item in areas["source_value"]]
    restored = pl.DataFrame({"id": areas["station_id"], "area": pl.Series(decoded, dtype=dtype)})
    assert_frame_equal(restored, native.data.select("id", "area").filter(pl.col("id") != "outside"))
    assert areas["source_dtype"].to_list() == [str(dtype)] * 4
    assert areas["source_unit"].to_list() == ["source unit"] * 4
    assert areas["support_fact"].to_list() == [f"metadata.{role}.area"] * 4
    assert areas["state"].to_list() == ["value"] * 3 + ["source_null"]
    assert result.filter(pl.col("state") == "no_metadata").height == 12
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
        origins = import_module(f"rivretrieve._internal.providers.{provider}.origins")
        fields = origins.STATION_METADATA_FIELDS
        assert ("maintenance/catalogue/station_metadata/review.json", None) in origins.CATALOGUE_BUILD_DECLARATIONS
        assert isinstance(fields, tuple)
        assert all(isinstance(field, MetadataField) for field in fields)
        if provider in ("ba_fhmzbih", "fr_hydroportail", "th_thaiwater", "pl_imgw", "za_dws"):
            assert all(field.attribute_role == "drainage_area" for field in fields)


@pytest.mark.parametrize(
    "dtype,value",
    [
        ("Float64", '"633.00 km²"'),
        ("String", "633.0"),
        ("Boolean", "1"),
        ("Int64", "true"),
        ("Float64", "1"),
        ("Int32", "1.0"),
        ("Int8", "128"),
        ("UInt8", "-1"),
        ("List(Float64)", "1.0"),
        ("Unknown", "1.0"),
        ("Unknown", None),
        ("Date", None),
    ],
)
def test_source_dtype_mismatch_is_fatal(dtype, value):
    source = (
        attributes()
        .with_columns(
            pl.when(pl.col("attribute_role") == "drainage_area")
            .then(pl.lit(dtype))
            .otherwise(pl.col("source_dtype"))
            .alias("source_dtype"),
            pl.when(pl.col("attribute_role") == "drainage_area")
            .then(pl.lit(value))
            .otherwise(pl.col("source_value"))
            .alias("source_value"),
            pl.when(pl.col("attribute_role") == "drainage_area")
            .then(pl.lit("source_null" if value is None else "value"))
            .otherwise(pl.col("state"))
            .alias("state"),
        )
        .cast(SOURCE_METADATA_SCHEMA)
    )
    with pytest.raises(FatalContractError, match="dtype"):
        source_metadata_frame(source.select("provider_id", "station_id").unique(), source)


def test_source_null_name_requires_string_dtype():
    source = (
        attributes()
        .with_columns(
            pl.when(pl.col("attribute_role") == "station_name")
            .then(pl.lit("Float64"))
            .otherwise(pl.col("source_dtype"))
            .alias("source_dtype"),
            pl.when(pl.col("attribute_role") == "station_name")
            .then(pl.lit(None))
            .otherwise(pl.col("source_value"))
            .alias("source_value"),
            pl.when(pl.col("attribute_role") == "station_name")
            .then(pl.lit("source_null"))
            .otherwise(pl.col("state"))
            .alias("state"),
        )
        .cast(SOURCE_METADATA_SCHEMA)
    )
    with pytest.raises(FatalContractError, match="name requires String"):
        source_metadata_frame(source.select("provider_id", "station_id").unique(), source)


def test_public_aligned_lists_preserve_every_source_entry(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from rivretrieve._internal.catalogue_origins import Field, NativeColumn
    from rivretrieve._internal.catalogues.native import RetrievedAt, stamp_native_table
    from rivretrieve._internal.catalogues.station_metadata import MetadataField, build_station_metadata

    selected = rr.find(provider="ca_eccc", station="02GA010")
    assert len(selected.series) > 1
    native = stamp_native_table(
        pl.DataFrame(
            {
                "id": ["02GA010"],
                "station": [" Gauge "],
                "riverName": ["Mår"],
                "lakeName": ["Mår"],
                "blankName": [""],
                "nullName": pl.Series([None], dtype=pl.String),
                "spaceName": [" \u00a0"],
                "numericArea": [0],
                "stringArea": ["0"],
                "inlineArea": ["633.00 km²"],
                "height": [10000000.0],
                "zero": [0],
                "formatted": [" 001.20 m"],
                "placeholder": ["ND"],
                "blank": [""],
                "space": [" \u00a0"],
                "missing": pl.Series([None], dtype=pl.Float64),
                "code": [3],
                "codeText": ["03"],
                "nullCode": pl.Series([None], dtype=pl.String),
            }
        ),
        RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    fields = (
        MetadataField("station_name", "station"),
        *(
            MetadataField("water_body_name", name)
            for name in ("riverName", "lakeName", "blankName", "nullName", "spaceName")
        ),
        MetadataField("drainage_area", "numericArea", "km²"),
        MetadataField("drainage_area", "stringArea"),
        MetadataField("drainage_area", "inlineArea"),
        MetadataField("elevation", "height", "m", datum_field="code", datum_support=("source.datum",)),
        MetadataField("elevation", "zero", "m", datum_field="codeText", datum_support=("source.datum",)),
        MetadataField("elevation", "formatted", datum="Published datum", datum_support=("source.datum",)),
        MetadataField("elevation", "missing", datum_field="nullCode", datum_support=("source.datum",)),
        *(MetadataField("elevation", name) for name in ("placeholder", "blank", "space")),
    )
    source = build_station_metadata(
        "ca_eccc",
        native,
        pl.DataFrame({"station_id": ["02GA010"]}),
        Field(NativeColumn("id")),
        fields,
    )
    directory = tmp_path / "ca_eccc" / "catalogue"
    directory.mkdir(parents=True)
    source.write_parquet(directory / "station_metadata.parquet")
    pl.DataFrame(
        {
            "provider_id": ["ca_eccc"],
            "station_id": ["02GA010"],
            "latitude": [1.0],
            "longitude": [2.0],
            "crs": ["source CRS"],
        }
    ).write_parquet(directory / "stations.parquet")
    monkeypatch.setattr(discovery, "files", lambda package: tmp_path)
    actual = rr.metadata(selected)
    expected = pl.DataFrame(
        [
            {
                "provider_id": "ca_eccc",
                "station_id": "02GA010",
                "station_name": " Gauge ",
                "latitude": 1.0,
                "longitude": 2.0,
                "crs": "source CRS",
                "water_body_name_field": ["blankName", "lakeName", "nullName", "riverName", "spaceName"],
                "water_body_name_value": ["", "Mår", None, "Mår", " \u00a0"],
                "drainage_area_field": ["inlineArea", "numericArea", "stringArea"],
                "drainage_area_value": ['"633.00 km²"', "0", '"0"'],
                "drainage_area_unit": [None, "km²", None],
                "elevation_field": ["blank", "formatted", "height", "missing", "placeholder", "space", "zero"],
                "elevation_value": ['""', '" 001.20 m"', "10000000.0", None, '"ND"', '" \u00a0"', "0"],
                "elevation_unit": [None, None, "m", None, None, None, "m"],
                "elevation_datum": [None, "Published datum", "3", None, None, None, "03"],
            }
        ],
        schema=STATION_METADATA_SCHEMA,
    )
    assert_frame_equal(actual, expected)
    detailed = rr.metadata(selected, view="source")
    assert_frame_equal(detailed, source)
    elevation = detailed.filter(pl.col("attribute_role") == "elevation")
    assert elevation["source_datum_dtype"].to_list() == [None, None, "Int64", "String", None, None, "String"]
    assert elevation.filter(pl.col("source_field") == "missing").select(
        "source_datum", "source_datum_field", "datum_support_fact"
    ).row(0) == (None, "nullCode", "metadata.elevation.missing.datum")
    exploded = actual.select("elevation_field", "elevation_value", "elevation_unit", "elevation_datum").explode(
        "elevation_field", "elevation_value", "elevation_unit", "elevation_datum"
    )
    assert_frame_equal(
        exploded,
        elevation.select(
            pl.col("source_field").alias("elevation_field"),
            pl.col("source_value").alias("elevation_value"),
            pl.col("source_unit").alias("elevation_unit"),
            pl.col("source_datum").alias("elevation_datum"),
        ),
    )


@pytest.mark.parametrize("difference", [{}, {"source_value": '"Different"'}, {"support_fact": "different.support"}])
def test_duplicate_source_field_is_fatal_even_when_values_or_support_differ(difference):
    source = attributes()
    duplicate = source.filter(pl.col("attribute_role") == "station_name").with_columns(
        *(pl.lit(value).alias(column) for column, value in difference.items())
    )
    with pytest.raises(FatalContractError, match="duplicate source fields"):
        source_metadata_frame(source.select("provider_id", "station_id").unique(), pl.concat([source, duplicate]))


@pytest.mark.parametrize(
    "changes",
    [
        {"source_datum": "datum"},
        {"source_datum_field": "code"},
        {"source_datum_dtype": "String"},
        {"datum_support_fact": "metadata.elevation.height.datum"},
        {"source_datum": "datum", "datum_support_fact": "other"},
        {
            "source_datum": "3",
            "source_datum_field": "code",
            "source_datum_dtype": "Float64",
            "datum_support_fact": "metadata.elevation.height.datum",
        },
        {
            "source_datum": "03",
            "source_datum_field": "code",
            "source_datum_dtype": "Int64",
            "datum_support_fact": "metadata.elevation.height.datum",
        },
        {
            "source_datum": "256",
            "source_datum_field": "code",
            "source_datum_dtype": "UInt8",
            "datum_support_fact": "metadata.elevation.height.datum",
        },
    ],
)
def test_invalid_datum_associations_are_fatal(changes):
    source = attributes().filter(pl.col("attribute_role") != "elevation")
    elevation = pl.DataFrame(
        [
            {
                "provider_id": "ca_eccc",
                "station_id": "02GA010",
                "attribute_role": "elevation",
                "source_field": "height",
                "source_value": "1.0",
                "source_dtype": "Float64",
                "state": "value",
                "support_fact": "metadata.elevation.height",
                **changes,
            }
        ],
        schema=SOURCE_METADATA_SCHEMA,
    )
    with pytest.raises(FatalContractError):
        source_metadata_frame(source.select("provider_id", "station_id").unique(), pl.concat([source, elevation]))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"datum": "datum"},
        {"datum_field": "code"},
        {"datum_support": ("source.datum",)},
        {"datum": "datum", "datum_field": "code", "datum_support": ("source.datum",)},
        {"datum": "datum", "datum_support": ("source.datum", "source.datum")},
        {"datum": 3, "datum_support": ("source.datum",)},
        {"datum_field": " ", "datum_support": ("source.datum",)},
        {"support_facts": ("",)},
    ],
)
def test_invalid_datum_declarations_are_rejected(kwargs):
    from rivretrieve._internal.catalogues.station_metadata import MetadataField

    with pytest.raises((ValueError, TypeError)):
        MetadataField("elevation", "height", **kwargs)


def test_datum_associations_are_elevation_only():
    from rivretrieve._internal.catalogues.station_metadata import MetadataField

    with pytest.raises(ValueError, match="Only elevation"):
        MetadataField("drainage_area", "area", datum="datum", datum_support=("source.datum",))
    source = attributes().with_columns(pl.lit("datum").alias("source_datum"))
    with pytest.raises(FatalContractError, match="elevation"):
        source_metadata_frame(source.select("provider_id", "station_id").unique(), source)


@pytest.mark.parametrize("role", ["water_body_name", "drainage_area", "elevation"])
def test_exposed_null_fields_are_lists_not_absence(role):
    source = pl.DataFrame(
        [
            {"provider_id": "p", "station_id": "001", "attribute_role": item, "state": "no_metadata"}
            for item in ATTRIBUTE_ROLES
            if item != role
        ]
        + [
            {
                "provider_id": "p",
                "station_id": "001",
                "attribute_role": role,
                "state": "source_null",
                "source_field": "field",
                "source_dtype": "String",
                "support_fact": f"metadata.{role}.field",
            }
        ],
        schema=SOURCE_METADATA_SCHEMA,
    )
    keys = source.select("provider_id", "station_id").unique()
    summary = station_metadata_frame(keys, source_metadata_frame(keys, source), pl.DataFrame())
    assert summary[f"{role}_field"].to_list() == [["field"]]
    assert summary[f"{role}_value"].to_list() == [[None]]
    for absent in {"water_body_name", "drainage_area", "elevation"} - {role}:
        assert summary[f"{absent}_field"].to_list() == [None]
        assert summary[f"{absent}_value"].to_list() == [None]


def test_duplicate_elevation_field_cannot_carry_conflicting_datums():
    source = pl.DataFrame(
        [
            {
                "provider_id": "p",
                "station_id": "001",
                "attribute_role": "elevation",
                "state": "value",
                "source_field": "height",
                "source_value": "1.0",
                "source_dtype": "Float64",
                "support_fact": "metadata.elevation.height",
                "source_datum": datum,
                "datum_support_fact": "metadata.elevation.height.datum",
            }
            for datum in ("datum A", "datum B")
        ],
        schema=SOURCE_METADATA_SCHEMA,
    )
    with pytest.raises(FatalContractError, match="duplicate source fields"):
        source_metadata_frame(source.select("provider_id", "station_id").unique(), source)


@pytest.mark.parametrize("site_value,exposed", [("Other river", True), ("River", True), (None, True), (None, False)])
def test_public_same_native_field_remains_distinct_between_source_scopes(tmp_path, monkeypatch, site_value, exposed):
    selected = rr.find(provider="ca_eccc", station="02GA010")
    source = attributes()
    station = source.filter(pl.col("attribute_role") == "water_body_name").with_columns(
        pl.lit("station").alias("source_scope"),
        pl.lit("metadata.water_body_name.station.river").alias("support_fact"),
    )
    frames = [source.filter(pl.col("attribute_role") != "water_body_name"), station]
    if exposed:
        frames.append(
            station.with_columns(
                pl.lit("site").alias("source_scope"),
                pl.lit("metadata.water_body_name.site.river").alias("support_fact"),
                pl.lit(None if site_value is None else json.dumps(site_value), dtype=pl.String).alias("source_value"),
                pl.lit("source_null" if site_value is None else "value")
                .cast(SOURCE_METADATA_SCHEMA["state"])
                .alias("state"),
            )
        )
    directory = tmp_path / "ca_eccc" / "catalogue"
    directory.mkdir(parents=True)
    pl.concat(frames).write_parquet(directory / "station_metadata.parquet")
    pl.DataFrame(
        {
            "provider_id": ["ca_eccc"],
            "station_id": ["02GA010"],
            "latitude": [1.0],
            "longitude": [2.0],
            "crs": ["source CRS"],
        }
    ).write_parquet(directory / "stations.parquet")
    monkeypatch.setattr(discovery, "files", lambda package: tmp_path)
    expected = pl.DataFrame(
        {
            "water_body_name_field": [["river", "river"] if exposed else ["river"]],
            "water_body_name_value": [[site_value, "River"] if exposed else ["River"]],
        },
        schema={"water_body_name_field": pl.List(pl.String), "water_body_name_value": pl.List(pl.String)},
    )
    assert_frame_equal(rr.metadata(selected).select(expected.columns), expected)
    detailed = rr.metadata(selected, view="source").filter(pl.col("attribute_role") == "water_body_name")
    assert detailed["source_scope"].to_list() == (["site", "station"] if exposed else ["station"])
    assert detailed["state"].to_list() == (
        ["source_null" if site_value is None else "value", "value"] if exposed else ["value"]
    )
    # A second fact inside one scope remains a conflict, unlike the two scopes.
    pl.concat([*frames, station]).write_parquet(directory / "station_metadata.parquet")
    with pytest.raises(FatalContractError, match="duplicate source fields"):
        rr.metadata(selected)


def test_usgs_elevation_scope_keeps_non_usgs_gauges_without_exposing_their_altitudes():
    from datetime import UTC, datetime

    from rivretrieve._internal.catalogue_origins import Field, NativeColumn
    from rivretrieve._internal.catalogues.native import RetrievedAt, stamp_native_table
    from rivretrieve._internal.providers.usgs_nwis.origins import STATION_METADATA_FIELDS
    from rivretrieve._internal.providers.usgs_nwis.station_metadata import project_station_metadata

    native = stamp_native_table(
        pl.DataFrame(
            {
                "site_no": ["001", "002", "003", "outside"],
                "agency_cd": ["USGS", "OTHER", "ANOTHER", "USGS"],
                "station_nm": ["One", "Two", "Three", "Outside"],
                "drain_area_va": ["1.0", "2.0", "3.0", "9.0"],
                "contrib_drain_area_va": ["0", "1.0", "2.0", "8.0"],
                "alt_va": [" 002.30", "forbidden altitude A", "forbidden altitude B", "outside altitude"],
                "alt_datum_cd": ["Published code", "forbidden datum A", "forbidden datum B", "outside datum"],
            }
        ),
        RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    stations = pl.DataFrame({"station_id": ["001", "002", "003"]})
    before = native.data.clone()
    result = project_station_metadata(native, stations, Field(NativeColumn("site_no")), STATION_METADATA_FIELDS)
    assert_frame_equal(result.select("station_id").unique().sort("station_id"), stations)
    expected = pl.DataFrame(
        [
            {
                "provider_id": "usgs_nwis",
                "station_id": "001",
                "attribute_role": "elevation",
                "state": "value",
                "source_field": "alt_va",
                "source_value": '" 002.30"',
                "source_dtype": "String",
                "source_unit": "feet",
                "support_fact": "metadata.elevation.alt_va",
                "source_datum": "Published code",
                "source_datum_field": "alt_datum_cd",
                "source_datum_dtype": "String",
                "datum_support_fact": "metadata.elevation.alt_va.datum",
            },
            *(
                {
                    "provider_id": "usgs_nwis",
                    "station_id": station,
                    "attribute_role": "elevation",
                    "state": "no_metadata",
                }
                for station in ("002", "003")
            ),
        ],
        schema=SOURCE_METADATA_SCHEMA,
    )
    assert_frame_equal(result.filter(pl.col("attribute_role") == "elevation"), expected)
    baseline = result.filter(pl.col("attribute_role") == "drainage_area")
    assert baseline["station_id"].to_list() == ["001", "001", "002", "002", "003", "003"]
    assert baseline["source_value"].to_list() == ['"0"', '"1.0"', '"1.0"', '"2.0"', '"2.0"', '"3.0"']
    assert baseline["source_unit"].to_list() == ["sq mi"] * 6
    assert result.filter(pl.col("attribute_role") == "station_name")["source_value"].to_list() == [
        '"One"',
        '"Two"',
        '"Three"',
    ]
    assert_frame_equal(native.data, before)


@pytest.mark.parametrize("provider", ["no_nve", "ca_eccc", "usgs_nwis", "jp_mlit"])
def test_metadata_definitions_resolve_adopted_nonruntime_source_support(provider):
    from importlib import import_module

    origins = import_module(f"rivretrieve._internal.providers.{provider}.origins")
    provenance = origins.build_acquisition_provenance()
    direct = {
        fact: binding
        for binding in provenance.fact_bindings
        if binding.transformation is None
        for fact in binding.facts
    }
    acquisitions = {
        (source.source_id, item.acquisition_id): item
        for source in provenance.source_records
        for item in source.acquisitions
    }
    facts = {fact for field in origins.STATION_METADATA_FIELDS for fact in (*field.support_facts, *field.datum_support)}
    assert facts
    for fact in facts:
        binding = direct[fact]
        acquisition = acquisitions[(binding.source_id, binding.acquisition_id)]
        assert acquisition.method != "runtime_http_request"
        assert acquisition.instant_type != "runtime"
        assert origins.CATALOGUE_SUPPORTING_INPUTS[fact]


def test_ana_elevation_context_keeps_its_existing_inventory_acquisition():
    from datetime import UTC, datetime

    from rivretrieve._internal.acquisition_provenance import NativeTableIdentity
    from rivretrieve._internal.providers.br_ana.capture import CapturedInventoryResponse, InventoryCapture
    from rivretrieve._internal.providers.br_ana.inventory import BRAZILIAN_UNITS, INVENTORY_URL
    from rivretrieve._internal.providers.br_ana.origins import STATION_METADATA_FIELDS, build_acquisition_provenance

    requests = [(f"inventory_UF_{unit}", {"Unidade Federativa": unit}) for unit in BRAZILIAN_UNITS]
    requests += [(f"inventory_basin_{basin}", {"Código da Bacia": basin}) for basin in range(1, 10)]
    responses = tuple(
        CapturedInventoryResponse(
            recording_id=identity,
            repository_path=f"synthetic/{identity}.json.xz",
            recording_sha256="a" * 64,
            recording_byte_size=1,
            requested_url=INVENTORY_URL,
            parameters=parameters,
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            media_type="application/json",
            payload_sha256="b" * 64,
            byte_size=1,
            row_count=1,
            distinct_station_count=1,
        )
        for identity, parameters in requests
    )
    capture = InventoryCapture(
        schema_version=1,
        responses=responses,
        native_table=NativeTableIdentity(
            repository_path="synthetic/native.parquet", revision="c" * 40, sha256="d" * 64
        ),
        response_row_count=36,
        distinct_station_count=1,
        fluviometric_station_count=1,
        pluviometric_station_count=0,
        canonicalization=("synthetic union",),
        population_scope="Synthetic inventory",
        attempt_record_paths=(),
        supporting_evidence=(),
    )
    provenance = build_acquisition_provenance(capture)
    fact = "source.ana.station_elevation_field_context"
    binding = next(binding for binding in provenance.fact_bindings if fact in binding.facts)
    assert binding.acquisition_id == "inventory_UF_AM"
    assert binding.source_id == "br_ana.hidro_inventory"
    field = next(field for field in STATION_METADATA_FIELDS if field.attribute_role == "elevation")
    assert (field.source_field, field.source_unit, field.datum, field.datum_field) == ("Altitude", None, None, None)
    assert field.support_facts == (fact,)
    assert all(
        reference.fact != fact
        for binding in provenance.fact_bindings
        if binding.transformation is not None
        for reference in binding.transformation.external_inputs
    )


def test_mlit_zero_point_semantics_use_one_known_original_without_campaign_inference():
    from datetime import datetime

    from rivretrieve._internal.providers.jp_mlit.origins import (
        CATALOGUE_SUPPORTING_INPUTS,
        NATIVE_TABLE_ACQUISITION_IDS,
        STATION_METADATA_FIELDS,
        ZERO_POINT_ELEVATION_FACT,
        build_acquisition_provenance,
    )

    provenance = build_acquisition_provenance()
    binding = next(binding for binding in provenance.fact_bindings if ZERO_POINT_ELEVATION_FACT in binding.facts)
    source = next(source for source in provenance.source_records if source.source_id == binding.source_id)
    acquisition = next(item for item in source.acquisitions if item.acquisition_id == binding.acquisition_id)
    assert acquisition.method == "http_request"
    assert acquisition.retrieved_at_start == datetime.fromisoformat("2026-08-02T19:35:42Z")
    assert acquisition.acquisition_id not in NATIVE_TABLE_ACQUISITION_IDS
    assert len(acquisition.recording_ids) == 1
    recording = next(
        item.recording
        for item in source.evidence
        if item.recording is not None and item.recording.recording_id in acquisition.recording_ids
    )
    assert recording.repository_path == "tests/test_data/jp_mlit_site_info_detail_301011281104010.html"
    assert recording.media_type == "text/html; charset=EUC-JP"
    assert recording.sha256 == "81e7269886397975867bf556c8d5b6659bd5f8d7318c4cf062cd0f47419418f9"
    assert CATALOGUE_SUPPORTING_INPUTS[ZERO_POINT_ELEVATION_FACT] == (recording.repository_path,)
    field = next(field for field in STATION_METADATA_FIELDS if field.source_field == "零点高")
    assert (field.attribute_role, field.source_unit, field.datum, field.datum_field) == ("elevation", None, None, None)
    assert field.support_facts == (ZERO_POINT_ELEVATION_FACT,)
    assert all(
        reference.fact != ZERO_POINT_ELEVATION_FACT
        for binding in provenance.fact_bindings
        if binding.transformation is not None
        for reference in binding.transformation.external_inputs
    )


@pytest.mark.parametrize("value", ["T.P. +1.230 m", " ", "", None])
def test_mlit_zero_point_keeps_inline_text_without_inventing_unit_or_datum(value):
    from datetime import UTC, datetime

    from rivretrieve._internal.catalogues.native import RetrievedAt, stamp_native_table
    from rivretrieve._internal.catalogues.station_metadata import build_station_metadata
    from rivretrieve._internal.providers.jp_mlit.origins import STATION_CATALOGUE_ORIGINS, STATION_METADATA_FIELDS

    fields = tuple(field for field in STATION_METADATA_FIELDS if field.source_field == "零点高")
    native = stamp_native_table(
        pl.DataFrame({"観測所記号": ["001"], "零点高": [value]}, schema={"観測所記号": pl.String, "零点高": pl.String}),
        RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    projected = build_station_metadata(
        "jp_mlit", native, pl.DataFrame({"station_id": ["001"]}), STATION_CATALOGUE_ORIGINS["station_id"], fields
    ).filter(pl.col("attribute_role") == "elevation")
    expected = pl.DataFrame(
        [
            {
                "provider_id": "jp_mlit",
                "station_id": "001",
                "attribute_role": "elevation",
                "source_field": "零点高",
                "source_dtype": "String",
                "source_value": None if value is None else json.dumps(value, ensure_ascii=False),
                "state": "source_null" if value is None else "value",
                "support_fact": "metadata.elevation.零点高",
            }
        ],
        schema=SOURCE_METADATA_SCHEMA,
    )
    assert_frame_equal(projected, expected)


_INLINE_FIELDS = [
    ("jp_mlit", "流域面積", "drainage_area", "km2", "km2", None),
    ("jp_mlit", "零点高", "elevation", "m", "m", None),
    ("ba_fhmzbih", "metadata_CATCHMENT_SIZE", "drainage_area", "km²", "km²", None),
    ("ch_foen", "Catchment size", "drainage_area", "km2", "km2", None),
    ("ch_foen", "Station altitude", "elevation", "m", "m a.s.l.", "LN02"),
]


@pytest.mark.parametrize("provider,name,role,unit,suffix,datum", _INLINE_FIELDS)
def test_inline_quantities_preserve_source_scalars_and_clean_only_complete_values(
    provider, name, role, unit, suffix, datum
):
    from datetime import UTC, datetime
    from importlib import import_module

    from rivretrieve._internal.catalogue_origins import Field, NativeColumn
    from rivretrieve._internal.catalogues.native import RetrievedAt, stamp_native_table
    from rivretrieve._internal.catalogues.station_metadata import build_station_metadata, validate_metadata_fields

    field = next(
        item
        for item in import_module(f"rivretrieve._internal.providers.{provider}.origins").STATION_METADATA_FIELDS
        if item.source_field == name
    )
    # Each pair is an independent expected spelling, not a second parser.
    pairs = [
        (f"142.00{suffix}", "142.00"),
        (f"0.000 {suffix}", "0.000"),
        (f"+1,719.00 {suffix}", "+1,719.00"),
        (f"-1,234,567.080\u00a0{suffix}", "-1,234,567.080"),
        (f" 001.20 {suffix}", " 001.20"),
        (f"-.5\t{suffix} \u00a0", "-.5"),
        (f"10000000 {suffix}", "10000000"),
    ]
    unchanged = [
        None,
        "",
        " \u00a0",
        "ND",
        "0",
        "1.20",
        f"T.P. +1.230 {suffix}",
        f"1 {suffix} estimated",
        f"about 1 {suffix}",
        f"1-2 {suffix}",
        f"1,71.00 {suffix}",
        f"1,2345 {suffix}",
        f"1.2.3 {suffix}",
        f"1e3 {suffix}",
        f"NaN {suffix}",
        f"inf {suffix}",
        f"1 {suffix}\n",
        f"1 {suffix}/{suffix}",
        "1 unknown",  # No partial stripping or guessed unit.
    ]
    values = [value for value, _ in pairs] + unchanged
    expected_values = [value for _, value in pairs] + unchanged
    ids = [f"{index:03}" for index in range(len(values))]
    native = stamp_native_table(
        pl.DataFrame({"id": ids, name: pl.Series(values, dtype=pl.String)}),
        RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    before = native.data.clone()
    projected = build_station_metadata(
        provider, native, pl.DataFrame({"station_id": ids}), Field(NativeColumn("id")), (field,)
    )
    validate_metadata_fields(projected, (field,))
    keys = projected.select("provider_id", "station_id").unique()
    source = source_metadata_frame(keys, projected)
    actual = source.filter(pl.col("attribute_role") == role)

    def encode(value):
        return None if value is None else json.dumps(value, ensure_ascii=False)

    assert actual["source_value"].to_list() == [encode(value) for value in values]
    assert actual["source_dtype"].to_list() == ["String"] * len(values)
    assert actual["state"].to_list() == ["source_null" if value is None else "value" for value in values]
    expected_units = [unit] * len(values) if provider == "ch_foen" else [unit] * len(pairs) + [None] * len(unchanged)
    assert actual["source_unit"].to_list() == expected_units
    summary = station_metadata_frame(keys, source, pl.DataFrame())
    assert summary[f"{role}_value"].to_list() == [[encode(value)] for value in expected_values]
    assert summary[f"{role}_unit"].to_list() == [[value] for value in expected_units]
    assert summary[f"{role}_field"].to_list() == [[name]] * len(values)
    if role == "elevation":
        assert summary["elevation_datum"].to_list() == [[datum]] * len(values)
    for absent in {"drainage_area", "elevation", "water_body_name"} - {role}:
        assert summary[f"{absent}_field"].to_list() == [None] * len(values)
    assert_frame_equal(native.data, before)
    assert_frame_equal(source_metadata_frame(keys, projected), source)
    # Corruption must be caught for a populated row, a blank and a named null.
    for index in (0, len(pairs), len(pairs) + 1):
        corrupt = projected.with_columns(
            pl.when((pl.col("station_id") == ids[index]) & (pl.col("attribute_role") == role))
            .then(pl.lit("invented"))
            .otherwise(pl.col("source_unit"))
            .alias("source_unit")
        )
        with pytest.raises(FatalContractError, match="declaration"):
            validate_metadata_fields(corrupt, (field,))


@pytest.mark.parametrize(
    "change",
    [
        {"provider_id": "other"},
        {"source_field": "other"},
        {"source_scope": "other"},
        {"attribute_role": "elevation"},
        {"source_unit": None},
        {"source_unit": "km²"},
        {"source_value": "142.0", "source_dtype": "Float64"},
    ],
)
def test_inline_summary_cleanup_does_not_expand_to_other_fields_or_scalars(change):
    item = {
        "provider_id": "jp_mlit",
        "station_id": "001",
        "attribute_role": "drainage_area",
        "source_field": "流域面積",
        "source_scope": None,
        "source_unit": "km2",
        "source_value": '"142.00km2"',
        "source_dtype": "String",
        "state": "value",
        "support_fact": "synthetic",
        **change,
    }
    source = pl.DataFrame([item], schema=SOURCE_METADATA_SCHEMA)
    keys = source.select("provider_id", "station_id")
    summary = station_metadata_frame(keys, source, pl.DataFrame())
    assert summary[f"{item['attribute_role']}_value"].to_list() == [[item["source_value"]]]
    assert summary[f"{item['attribute_role']}_unit"].to_list() == [[item["source_unit"]]]


@pytest.mark.parametrize(
    "role,kwargs",
    [
        ("drainage_area", {"inline_unit": "unknown"}),
        ("drainage_area", {"inline_unit": "km2", "source_unit": "km2"}),
        ("station_name", {"inline_unit": "m"}),
        ("water_body_name", {"inline_unit": "m"}),
    ],
)
def test_inline_unit_declarations_reject_conflicting_or_nonquantity_units(role, kwargs):
    from rivretrieve._internal.catalogues.station_metadata import MetadataField

    with pytest.raises(ValueError, match="inline unit"):
        MetadataField(role, "field", **kwargs)


@pytest.mark.parametrize(
    "provider,station,field,role,raw,numeric,unit,datum",
    [
        ("usgs_nwis", "07374000", "alt_va", "elevation", " 0.00", "0.00", "feet", "NAVD88"),
        ("jp_mlit", "301011281104010", "流域面積", "drainage_area", "142.00km2", "142.00", "km2", None),
        ("jp_mlit", "301011281104010", "零点高", "elevation", "0.000m", "0.000", "m", None),
        ("ba_fhmzbih", "4024", "metadata_CATCHMENT_SIZE", "drainage_area", "1600.00 km²", "1600.00", "km²", None),
        ("ch_foen", "2004", "Catchment size", "drainage_area", "713 km2", "713", "km2", None),
        ("ch_foen", "2004", "Station altitude", "elevation", "432 m a.s.l.", "432", "m", "LN02"),
    ],
)
def test_public_quantity_presentation_examples_are_offline(
    provider, station, field, role, raw, numeric, unit, datum, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Metadata must remain offline")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(discovery, "_resolve_credentials", forbidden)
    monkeypatch.setattr(discovery, "dotenv_values", forbidden)
    selected = rr.find(provider=provider, station=station)
    source = rr.metadata(selected, view="source").filter(pl.col("source_field") == field)
    assert source["source_value"].item() == json.dumps(raw, ensure_ascii=False)
    assert source["source_dtype"].item() == "String"
    assert source["source_unit"].item() == unit
    summary = rr.metadata(selected).row(0, named=True)
    index = summary[f"{role}_field"].index(field)
    assert summary[f"{role}_value"][index] == json.dumps(numeric)
    assert json.loads(summary[f"{role}_value"][index]) == numeric
    assert summary[f"{role}_unit"][index] == unit
    if role == "elevation":
        assert summary["elevation_datum"][index] == source["source_datum"].item() == datum


@pytest.mark.parametrize(
    "value,dtype,expected",
    [
        (" 0.00", "String", "0.00"),
        (" \t\u00a0+001.200", "String", "+001.200"),
        (" -1,234,567.080", "String", "-1,234,567.080"),
        (" -.50", "String", "-.50"),
        ("0.00", "String", "0.00"),
        (None, "String", None),
        *[
            (value, "String", value)
            for value in (
                "",
                " \t\u00a0",
                "ND",
                " 1.0 estimated",
                "about 1.0",
                " 1 m",
                " 1-2",
                " 1,23.0",
                " 1.2.3",
                " 1e3",
                " NaN",
                " inf",
                " 1.0 ",
                " 1.0\n",
                "\n1.0",
                " 1.0\t",
                " 1.0\u00a0",
            )
        ],
        (0, "Int64", 0),
        (0.0, "Float64", 0.0),
        (True, "Boolean", True),
    ],
)
def test_usgs_elevation_padding_preserves_complete_numeric_spelling_and_other_states(value, dtype, expected):
    source = attributes("usgs_nwis", "001").filter(pl.col("attribute_role") != "elevation")
    encoded = None if value is None else json.dumps(value, ensure_ascii=False)
    elevation = source_frame(
        [
            (
                "usgs_nwis",
                "001",
                "alt_va",
                encoded,
                dtype,
                "feet",
                "source_null" if value is None else "value",
                "elevation",
                "metadata.elevation.alt_va",
            ),
        ]
    ).with_columns(
        pl.lit("NAVD88").alias("source_datum"),
        pl.lit("metadata.elevation.alt_va.datum").alias("datum_support_fact"),
    )
    source = pl.concat([source, elevation])
    before = source.clone()
    keys = source.select("provider_id", "station_id").unique()
    detailed = source_metadata_frame(keys, source)
    summary = station_metadata_frame(keys, detailed, pl.DataFrame())
    expected_text = None if expected is None else json.dumps(expected, ensure_ascii=False)
    assert summary["elevation_value"].to_list() == [[expected_text]]
    assert summary["elevation_field"].to_list() == [["alt_va"]]
    assert summary["elevation_unit"].to_list() == [["feet"]]
    assert summary["elevation_datum"].to_list() == [["NAVD88"]]
    assert_frame_equal(detailed.filter(pl.col("attribute_role") == "elevation"), elevation)
    assert_frame_equal(source, before)


@pytest.mark.parametrize(
    "change",
    [
        {"provider_id": "other"},
        {"source_field": "other"},
        {"attribute_role": "drainage_area"},
        {"source_scope": "other"},
    ],
)
def test_usgs_padding_cleanup_does_not_expand_to_other_quantity_fields(change):
    item = {
        "provider_id": "usgs_nwis",
        "station_id": "001",
        "attribute_role": "elevation",
        "source_field": "alt_va",
        "source_value": '" 001.20"',
        "source_dtype": "String",
        "state": "value",
        "support_fact": "synthetic",
        **change,
    }
    source = pl.DataFrame([item], schema=SOURCE_METADATA_SCHEMA)
    keys = source.select("provider_id", "station_id")
    summary = station_metadata_frame(keys, source, pl.DataFrame())
    assert summary[f"{item['attribute_role']}_value"].to_list() == [['" 001.20"']]
