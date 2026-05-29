from __future__ import annotations

from datetime import datetime

import polars as pl
import polars.testing as pl_testing

import rivretrieve as rr
from rivretrieve._internal.observations import (
    AnnotationTable,
    ObservationDataSchema,
    ObservationProvenance,
    ObservationResult,
    RowAnnotationTableSchema,
    SeriesAnnotationTableSchema,
)
from rivretrieve._internal.primitives import ProviderId


def test_v1_deferred_wide_form_helpers_remain_absent() -> None:
    data = pl.DataFrame(
        {
            "time": [datetime(2026, 1, 1)],
            "station_id": ["station-1"],
            "product_id": ["discharge_instantaneous"],
            "value": [1.2],
        },
        schema=ObservationDataSchema.polars_schema,
    )
    result = ObservationResult(
        data=data,
        row_annotations=AnnotationTable(
            pl.DataFrame(schema=RowAnnotationTableSchema.polars_schema),
            RowAnnotationTableSchema,
        ),
        series_annotations=AnnotationTable(
            pl.DataFrame(schema=SeriesAnnotationTableSchema.polars_schema),
            SeriesAnnotationTableSchema,
        ),
        provenance=ObservationProvenance(source="live", provider_id=ProviderId("ch_foen")),
    )

    pl_testing.assert_frame_equal(result.to_polars(), data)
    assert list(result.to_pandas().columns) == ["time", "station_id", "product_id", "value"]
    for helper_name in ("to_wide", "to_wide_pandas", "to_pivot", "to_dataframe_wide"):
        assert not hasattr(result, helper_name)


def test_v1_products_are_not_rivretrieve_derived() -> None:
    products = rr.products().data

    assert products["derived"].to_list() == [False] * products.height
    assert products["derivation_method"].null_count() == products.height


def test_v1_observed_property_vocabulary_remains_river_gauge_scope() -> None:
    products = rr.products().data

    observed_properties = set(products["observed_property"].unique().to_list())
    assert observed_properties <= {"discharge", "stage", "water_temperature"}
    assert observed_properties.isdisjoint(
        {
            "precipitation",
            "rainfall",
            "catchment_rainfall",
            "air_temperature",
            "wind_speed",
            "humidity",
        }
    )
