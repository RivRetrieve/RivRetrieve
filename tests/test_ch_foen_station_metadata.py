"""Synthetic FOEN source structure and exposure contracts, without retained bodies."""

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.catalogues.station_metadata import MetadataField
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ch_foen.station_metadata import (
    parse_station_directory,
    parse_station_page,
    project_station_metadata,
)


def directory_row(station="001", name=" Gauge &amp; name ", water=""):
    return (
        f'<tr class="station-row discharge_{station}" data-key="{station}" data-name="{name}" '
        f'data-hydro-body="{water}"><td><a href="/en/seen-und-fluesse/stations/{station}">Display title</a></td></tr>'
    )


def station_page(
    station="001", fields="<dt>Station altitude</dt><dd> 1,234.0 m a.s.l.</dd><dt>Catchment size</dt><dd>0 km2</dd>"
):
    return (
        f"<h1>General site heading</h1><h1><span>Display title</span><small>{station}</small></h1>"
        f"<div><h2>Station information</h2></div><div><dl>{fields}"
        "<dt>Mean catchment altitude</dt><dd>Excluded</dd></dl></div>"
        "<h3>Data availability</h3><dl><dt>Station altitude</dt><dd>Unrelated</dd></dl>"
    ).encode()


FIELDS = (
    MetadataField("station_name", "data-name", source_scope="station_directory", source_facts=("source.directory",)),
    MetadataField(
        "water_body_name", "data-hydro-body", source_scope="station_directory", source_facts=("source.directory",)
    ),
    MetadataField(
        "drainage_area", "Catchment size", "km2", source_scope="station_page", source_facts=("source.pages",)
    ),
    MetadataField(
        "elevation",
        "Station altitude",
        "m",
        datum="LN02",
        datum_support=("source.reference",),
        source_scope="station_page",
        source_facts=("source.pages",),
    ),
)


def test_directory_decodes_attributes_and_agrees_across_repeated_measurements():
    row = directory_row()
    assert parse_station_directory((row + row.replace("discharge_", "temperature_")).encode()) == {
        "001": {"data-name": " Gauge & name ", "data-hydro-body": ""},
    }
    with pytest.raises(FatalContractError, match="disagree"):
        parse_station_directory((row + directory_row(water="Other water")).encode())


@pytest.mark.parametrize(
    "source",
    [
        directory_row().replace('data-key="001"', 'data-key=""'),
        directory_row().replace('data-name=" Gauge &amp; name "', ""),
        directory_row().replace('data-name=" Gauge &amp; name "', "data-name"),
        directory_row().replace('data-key="001"', 'data-key="001" data-key="002"'),
        directory_row().replace("/stations/001", "/stations/002"),
    ],
)
def test_directory_rejects_missing_or_contradictory_source_identity(source):
    with pytest.raises(FatalContractError):
        parse_station_directory(source.encode())


def test_station_page_keeps_entire_decoded_text_and_excludes_other_sections():
    body = station_page(fields="<dt>Station altitude</dt><dd> 0&nbsp;m a.s.l. </dd><dt>Catchment size</dt><dd></dd>")
    assert parse_station_page(body, "001") == {"Station altitude": " 0\u00a0m a.s.l. ", "Catchment size": ""}
    assert parse_station_page(station_page(fields=""), "001") == {}


@pytest.mark.parametrize(
    "body",
    [
        station_page(station="other"),
        station_page().replace(b"<small>001</small>", b"<small>001</small><small>001</small>"),
        station_page().replace(b"<h2>Station information</h2>", b"<h2>Other information</h2>"),
        station_page(fields="<dt>Station altitude</dt><dd><span>1 m</span></dd>"),
        station_page(fields="<dt>Station altitude</dt><dd>1<br>m</dd>"),
        station_page(fields="<dt>Station altitude</dt><dd>1 m</dd><dt>Station altitude</dt><dd>2 m</dd>"),
        station_page(fields="<dt>Station altitude</dt><span></span><dd>1 m</dd>"),
        b"\xff",
    ],
)
def test_station_page_rejects_invalid_identity_or_ambiguous_scalar_structure(body):
    with pytest.raises(FatalContractError):
        parse_station_page(body, "001")


def test_projection_keeps_unmatched_gauges_and_distinguishes_absent_from_blank_fields():
    stations = pl.DataFrame({"station_id": ["001", "002"], "latitude": [1.0, None], "longitude": [2.0, None]})
    before = stations.clone()
    source = project_station_metadata(
        stations,
        directory_row().encode(),
        {
            "001": station_page(fields="<dt>Station altitude</dt><dd></dd>"),
        },
        FIELDS,
    )
    assert source.filter(pl.col("station_id") == "002")["state"].to_list() == ["no_metadata"] * 4
    exposed = source.filter(pl.col("station_id") == "001")
    assert exposed.filter(pl.col("attribute_role") == "drainage_area")["state"].item() == "no_metadata"
    elevation = exposed.filter(pl.col("attribute_role") == "elevation")
    assert elevation.select("source_value", "source_unit", "source_datum", "state").row(0) == (
        '""',
        "m",
        "LN02",
        "value",
    )
    assert elevation["source_field"].item() == "Station altitude"
    assert elevation["source_scope"].item() == "station_page"
    assert exposed.filter(pl.col("attribute_role") == "water_body_name")["source_value"].item() == '""'
    assert_frame_equal(stations, before)


@pytest.mark.parametrize("pages", [{}, {"001": station_page(), "outside": station_page("outside")}])
def test_projection_does_not_replace_missing_or_extra_adopted_pages_with_absence(pages):
    with pytest.raises(FatalContractError, match="scope"):
        project_station_metadata(pl.DataFrame({"station_id": ["001"]}), directory_row().encode(), pages, FIELDS)
