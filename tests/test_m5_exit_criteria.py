from __future__ import annotations

import polars.testing as pl_testing

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.observations import ObservationDataSchema
from tests.usgs_modern_recordings import ModernReplay


def test_v1_deferred_wide_form_helpers_remain_absent(monkeypatch) -> None:
    monkeypatch.setattr(discovery, "HttpClient", lambda: ModernReplay("daily-07374000-docs-2023"))
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    result = rr.fetch(selection, start="2023-01-01", end="2023-01-01", cache="bypass")

    assert result.data.height == 1
    pl_testing.assert_frame_equal(result.to_polars(), result.data)
    assert list(result.to_pandas().columns) == list(ObservationDataSchema.polars_schema)
    for helper_name in ("to_wide", "to_wide_pandas", "to_pivot", "to_dataframe_wide"):
        assert not hasattr(result, helper_name)
