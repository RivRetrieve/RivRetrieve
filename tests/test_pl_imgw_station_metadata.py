"""Synthetic checks for Poland's station-specific gauge-zero metadata."""

import math
from dataclasses import replace
from datetime import UTC, datetime

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, stamp_native_table
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.pl_imgw.origins import STATION_METADATA_FIELDS
from rivretrieve._internal.providers.pl_imgw.station_metadata import GaugeZeroElevation, build_station_metadata
from rivretrieve._internal.station_metadata import SOURCE_METADATA_SCHEMA, station_metadata_frame


@pytest.fixture
def gauge_metadata():
    native = stamp_native_table(
        pl.DataFrame(
            {
                "gauge_id": ["900000001", "900000002", "900000003"],
                "gauge_altitude": ["1.2300", "2.50", "ND"],
                "area": ["10.00", "20", "ND"],
            }
        ),
        RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    stations = pl.DataFrame({"provider_id": ["pl_imgw"] * 3, "station_id": ["900000002", "900000003", "900000001"]})
    # Deliberately use a third order to detect positional joins.
    elevations = (
        GaugeZeroElevation("900000003", "ND", "ND"),
        GaugeZeroElevation("900000001", 1.23, "Kronsztadt"),
        GaugeZeroElevation("900000002", 2.5, "EVRF2007"),
    )
    return native, stations, elevations


def test_station_references_preserve_native_strings_and_aligned_lists(gauge_metadata):
    native, stations, elevations = gauge_metadata
    before = native.data.clone()
    source = build_station_metadata(native, stations, elevations)
    actual = source.filter(pl.col("attribute_role") == "elevation").select(
        "station_id",
        "source_field",
        "source_value",
        "source_dtype",
        "source_unit",
        "state",
        "source_datum",
        "source_datum_field",
        "source_datum_dtype",
        "support_fact",
        "datum_support_fact",
    )
    expected = pl.DataFrame(
        {
            "station_id": ["900000001", "900000002", "900000003"],
            "source_field": ["gauge_altitude"] * 3,
            "source_value": ['"1.2300"', '"2.50"', '"ND"'],
            "source_dtype": ["String"] * 3,
            "source_unit": ["m"] * 3,
            "state": ["value"] * 3,
            "source_datum": ["Kronsztadt", "EVRF2007", "ND"],
            "source_datum_field": ["Vertical reference system"] * 3,
            "source_datum_dtype": ["String"] * 3,
            "support_fact": ["metadata.elevation.gauge_altitude"] * 3,
            "datum_support_fact": ["metadata.elevation.gauge_altitude.datum"] * 3,
        }
    )
    assert_frame_equal(actual, expected.cast({"state": SOURCE_METADATA_SCHEMA["state"]}))
    summary = station_metadata_frame(stations, source, pl.DataFrame()).sort("station_id")
    assert_frame_equal(
        summary.select("station_id", "elevation_field", "elevation_value", "elevation_unit", "elevation_datum"),
        pl.DataFrame(
            {
                "station_id": ["900000001", "900000002", "900000003"],
                "elevation_field": [["gauge_altitude"]] * 3,
                "elevation_value": [['"1.2300"'], ['"2.50"'], ['"ND"']],
                "elevation_unit": [["m"]] * 3,
                "elevation_datum": [["Kronsztadt"], ["EVRF2007"], ["ND"]],
            }
        ),
    )
    assert_frame_equal(native.data, before)
    areas = source.filter(pl.col("attribute_role") == "drainage_area")
    assert areas["source_value"].to_list() == ['"10.00"', '"20"', '"ND"']
    assert areas["source_unit"].to_list() == ["square kilometre"] * 3
    (field,) = (field for field in STATION_METADATA_FIELDS if field.attribute_role == "elevation")
    assert field.source_facts == ("native.gauge_altitude",)
    assert field.support_facts == ("source.grdc.gauge_zero_height_unit",)
    assert field.datum_support == ("source.grdc.vertical_reference",)


@pytest.mark.parametrize("height", [math.nextafter(1.23, math.inf), "1.23", True, None, float("nan")])
def test_reconciliation_requires_exact_decoded_number(gauge_metadata, height):
    native, stations, elevations = gauge_metadata
    altered = (elevations[0], replace(elevations[1], height=height), elevations[2])
    with pytest.raises(FatalContractError, match="height"):
        build_station_metadata(native, stations, altered)


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "extra",
        "duplicate",
        "wrong_station",
        "native_duplicate",
        "native_scalar",
        "native_null",
        "unpaired_height",
        "unpaired_reference",
    ],
)
def test_reconciliation_rejects_invalid_coverage_and_placeholders(gauge_metadata, fault):
    native, stations, elevations = gauge_metadata
    if fault == "missing":
        elevations = elevations[1:]
    elif fault == "extra":
        elevations += (GaugeZeroElevation("900000004", 4, "EVRF2007"),)
    elif fault == "duplicate":
        elevations += (elevations[0],)
    elif fault == "wrong_station":
        elevations = (elevations[0], replace(elevations[1], station_id="900000004"), elevations[2])
    elif fault == "native_duplicate":
        native = NativeTable(pl.concat([native.data, native.data.head(1)]))
    elif fault == "native_scalar":
        native = NativeTable(native.data.with_columns(pl.lit(1.23).alias("gauge_altitude")))
    elif fault == "native_null":
        native = NativeTable(native.data.with_columns(pl.lit(None, dtype=pl.String).alias("gauge_altitude")))
    elif fault == "unpaired_height":
        elevations = (replace(elevations[0], vertical_reference="EVRF2007"), *elevations[1:])
    else:
        elevations = (elevations[0], replace(elevations[1], vertical_reference="ND"), elevations[2])
    with pytest.raises(FatalContractError):
        build_station_metadata(native, stations, elevations)


@pytest.mark.parametrize("header_fault", [None, "missing", "duplicate"])
def test_workbook_reader_decodes_numbers_and_requires_exact_headers(tmp_path, monkeypatch, header_fault):
    import hashlib

    import openpyxl

    from rivretrieve._internal.providers.pl_imgw import origins
    from rivretrieve._internal.providers.pl_imgw.station_metadata import read_workbook_elevations

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "List1"
    reference = "Vertical reference system"
    if header_fault == "missing":
        reference = "Unrelated reference"
    headers = ["Station code", origins.GAUGE_ZERO_HEADER, reference]
    if header_fault == "duplicate":
        headers.append(reference)
    sheet.append(headers)
    sheet.append([900000001, 1.23, "Kronsztadt"])
    sheet.append(["900000002", 2, "EVRF2007"])
    sheet.append(["900000003", "ND", "ND"])
    path = tmp_path / "synthetic.xlsx"
    book.save(path)
    book.close()
    body = path.read_bytes()
    # This tests reader mechanics only, not the genuine workbook's identity.
    monkeypatch.setattr(origins, "WORKBOOK_SHA256", hashlib.sha256(body).hexdigest())
    monkeypatch.setattr(origins, "WORKBOOK_BYTE_SIZE", len(body))
    if header_fault:
        with pytest.raises(FatalContractError, match="headers"):
            read_workbook_elevations(path)
    else:
        assert read_workbook_elevations(path) == (
            GaugeZeroElevation("900000001", 1.23, "Kronsztadt"),
            GaugeZeroElevation("900000002", 2, "EVRF2007"),
            GaugeZeroElevation("900000003", "ND", "ND"),
        )
