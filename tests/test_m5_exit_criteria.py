from __future__ import annotations

from datetime import datetime

import polars as pl
import polars.testing as pl_testing

from rivretrieve._internal.observations import (
    ObservationDataSchema,
    ObservationProvenance,
    ObservationResult,
    Receipts,
)
from rivretrieve._internal.primitives import ProviderId


def test_v1_deferred_wide_form_helpers_remain_absent() -> None:
    data = pl.DataFrame(
        {
            "time": [datetime(2026, 1, 1)],
            "time_zone": ["unknown"],
            "station_id": ["station-1"],
            "product_id": ["discharge_instantaneous"],
            "value": [1.2],
        },
        schema=ObservationDataSchema.polars_schema,
    )
    result = ObservationResult(
        data=data,
        provenance=ObservationProvenance(source="live", provider_id=ProviderId("ch_foen")),
        receipts=Receipts(provider_id=ProviderId("ch_foen")),
    )

    pl_testing.assert_frame_equal(result.to_polars(), data)
    assert list(result.to_pandas().columns) == [
        "time",
        "time_zone",
        "station_id",
        "product_id",
        "value",
    ]
    for helper_name in ("to_wide", "to_wide_pandas", "to_pivot", "to_dataframe_wide"):
        assert not hasattr(result, helper_name)
