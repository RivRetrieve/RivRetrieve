"""Synthetic controls for modern names and agency-qualified legacy enrichment."""

from datetime import UTC, datetime

import polars as pl
import polars.testing as pl_testing

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
