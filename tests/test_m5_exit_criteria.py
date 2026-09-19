from __future__ import annotations

from pathlib import Path

import polars.testing as pl_testing

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.observations import ObservationDataSchema
from rivretrieve._internal.recordings import ReplayTransport, read_recording


def test_v1_deferred_wide_form_helpers_remain_absent(monkeypatch) -> None:
    recording = read_recording(
        Path(__file__).parent / "test_data/usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json"
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    result = rr.fetch(selection, start="2023-01-01", end="2023-01-01")

    assert result.data.height == 1
    pl_testing.assert_frame_equal(result.to_polars(), result.data)
    assert list(result.to_pandas().columns) == list(ObservationDataSchema.polars_schema)
    for helper_name in ("to_wide", "to_wide_pandas", "to_pivot", "to_dataframe_wide"):
        assert not hasattr(result, helper_name)
