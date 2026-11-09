"""Synthetic controls for modern names and agency-qualified legacy enrichment."""

from datetime import UTC, datetime

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.native import RetrievedAt, stamp_native_table
from rivretrieve._internal.catalogues.station_metadata import MetadataField
from rivretrieve._internal.providers.usgs_nwis.station_metadata import project_modern_station_metadata

FIELDS = (
    MetadataField("station_name", "monitoring_location_name"),
    MetadataField("drainage_area", "drain_area_va", source_unit="mi2"),
    MetadataField("elevation", "alt_va", source_unit="ft"),
)


def native(data):
    return stamp_native_table(pl.DataFrame(data), RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC)))


def test_modern_name_is_authoritative_with_legacy_quantities():
    modern = native(
        {
            "agency_code": ["USGS"],
            "monitoring_location_number": ["001"],
            "station_id": ["001"],
            "monitoring_location_id": ["USGS-001"],
            "monitoring_location_name": ["Modern name"],
        }
    )
    legacy = native(
        {
            "agency_cd": ["USGS"],
            "site_no": ["001"],
            "station_nm": ["Old name"],
            "drain_area_va": ["12.5"],
            "alt_va": ["100"],
        }
    )
    result = project_modern_station_metadata(modern, legacy, pl.DataFrame({"station_id": ["001"]}), FIELDS)
    pl_testing.assert_frame_equal(
        result.select("attribute_role", "source_field", "source_value", "source_unit", "state").with_columns(
            pl.col("attribute_role", "state").cast(pl.String)
        ),
        pl.DataFrame(
            {
                "attribute_role": ["drainage_area", "elevation", "station_name", "water_body_name"],
                "source_field": ["drain_area_va", "alt_va", "monitoring_location_name", None],
                "source_value": ['"12.5"', '"100"', '"Modern name"', None],
                "source_unit": ["mi2", "ft", None, None],
                "state": ["value", "value", "value", "no_metadata"],
            }
        ),
        check_row_order=False,
    )


def test_enrichment_requires_matching_agency_and_elevation_requires_usgs():
    modern = native(
        {
            "agency_code": ["USGS", "OTHER", "USGS"],
            "monitoring_location_number": ["001", "002", "003"],
            "station_id": ["001", "002", "003"],
            "monitoring_location_id": ["USGS-001", "OTHER-002", "USGS-003"],
            "monitoring_location_name": [None, "Other gauge", "Modern only"],
        }
    )
    legacy = native(
        {
            "agency_cd": ["OTHER", "OTHER"],
            "site_no": ["001", "002"],
            "station_nm": ["Wrong agency name", "Old other name"],
            "drain_area_va": ["999", None],
            "alt_va": ["999", "200"],
        }
    )
    result = project_modern_station_metadata(
        modern, legacy, pl.DataFrame({"station_id": ["001", "002", "003"]}), FIELDS
    )
    pl_testing.assert_frame_equal(
        result.select("station_id", "attribute_role", "state").with_columns(
            pl.col("attribute_role", "state").cast(pl.String)
        ),
        pl.DataFrame(
            {
                "station_id": ["001"] * 4 + ["002"] * 4 + ["003"] * 4,
                "attribute_role": ["drainage_area", "elevation", "station_name", "water_body_name"] * 3,
                "state": [
                    "no_metadata",
                    "no_metadata",
                    "source_null",
                    "no_metadata",
                    "source_null",
                    "no_metadata",
                    "value",
                    "no_metadata",
                    "no_metadata",
                    "no_metadata",
                    "value",
                    "no_metadata",
                ],
            }
        ),
        check_row_order=False,
    )
    area = result.filter((pl.col("station_id") == "002") & (pl.col("attribute_role") == "drainage_area"))
    assert area["source_field"].item() == "drain_area_va"
    assert area["source_unit"].item() == "mi2"


def test_colliding_agency_metadata_stays_with_canonical_identity():
    modern = native(
        {
            "agency_code": ["CA574", "USGS"],
            "monitoring_location_number": ["001", "001"],
            "station_id": ["001", "USGS-001"],
            "monitoring_location_id": ["CA574-001", "USGS-001"],
            "monitoring_location_name": ["Other", "USGS"],
        }
    )
    legacy = native(
        {
            "agency_cd": ["CA574", "USGS"],
            "site_no": ["001", "001"],
            "drain_area_va": ["12", "34"],
            "alt_va": ["99", "56"],
        }
    )
    result = project_modern_station_metadata(modern, legacy, pl.DataFrame({"station_id": ["001", "USGS-001"]}), FIELDS)
    assert result.filter(pl.col("attribute_role") == "drainage_area").select("station_id", "source_value").sort(
        "station_id"
    ).rows() == [("001", '"12"'), ("USGS-001", '"34"')]
    assert (
        result.filter((pl.col("attribute_role") == "elevation") & (pl.col("station_id") == "001"))["state"].item()
        == "no_metadata"
    )
    assert (
        result.filter((pl.col("attribute_role") == "elevation") & (pl.col("station_id") == "USGS-001"))[
            "source_value"
        ].item()
        == '"56"'
    )


@pytest.mark.parametrize("datum", ["NAVD88", "NGVD29"])
def test_conflicting_quantity_spelling_is_omitted_without_losing_exact_agreement(datum):
    modern = native(
        {
            "agency_code": ["USGS"],
            "monitoring_location_number": ["09372200"],
            "station_id": ["09372200"],
            "monitoring_location_name": ["Modern"],
        }
    )
    legacy = native(
        {
            "agency_cd": ["USGS", "USGS"],
            "site_no": ["09372200", "09372200"],
            "drain_area_va": ["720.00", "720.0"],
            "contrib_drain_area_va": ["700", "700"],
            "alt_va": ["100", "100"],
            "alt_datum_cd": ["NAVD88", datum],
            "dec_lat_va": ["1", "2"],
        }
    )
    fields = (
        *FIELDS[:2],
        MetadataField(
            "elevation", "alt_va", source_unit="ft", datum_field="alt_datum_cd", datum_support=("source.datum",)
        ),
        MetadataField("drainage_area", "contrib_drain_area_va", source_unit="mi2"),
    )
    result = project_modern_station_metadata(modern, legacy, pl.DataFrame({"station_id": ["09372200"]}), fields)
    expected = [("contrib_drain_area_va", '"700"'), ("monitoring_location_name", '"Modern"')]
    if datum == "NAVD88":
        expected.insert(0, ("alt_va", '"100"'))
        assert result.filter(pl.col("source_field") == "alt_va")["source_datum"].item() == "NAVD88"
    assert (
        result.filter(pl.col("state") != "no_metadata")
        .select("source_field", "source_value")
        .sort("source_field")
        .rows()
        == expected
    )
    assert legacy.data["drain_area_va"].to_list() == ["720.00", "720.0"]
