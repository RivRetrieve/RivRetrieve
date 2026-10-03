"""Modern source limits govern complete, gap-free multi-year request plans."""

from datetime import datetime, timedelta

import pytest

from rivretrieve._internal.engine import RenderedWindow, WindowEndpoint, _make_fetch_window
from rivretrieve._internal.providers.usgs_nwis.config import config, window_declarations
from rivretrieve._internal.window_planning import plan_windows


@pytest.mark.parametrize("product_id", tuple(config().products))
def test_multiyear_windows_cover_exact_source_bounds_without_gaps(product_id) -> None:
    start, end = datetime(2020, 1, 1), datetime(2023, 12, 31, 23, 59, 59, 999999)
    window = _make_fetch_window(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end))
    declaration = window_declarations().products[product_id]
    planned = plan_windows(window, declaration)
    if config().products[product_id].coordinates.value.endpoint == "daily":
        assert planned == (RenderedWindow("2020-01-01", "2023-12-31"),)
        assert declaration.size is None
    else:
        assert planned == (
            RenderedWindow("2020-01-01T00:00:00Z", "2023-01-04T23:59:59.999999Z"),
            RenderedWindow("2023-01-05T00:00:00Z", "2023-12-31T23:59:59.999999Z"),
        )
        bounds = [
            (datetime.fromisoformat(item.start.removesuffix("Z")), datetime.fromisoformat(item.stop.removesuffix("Z")))
            for item in planned
        ]
        assert bounds[0][0] == start
        assert bounds[-1][1] == end
        tick = timedelta(microseconds=1)
        assert all(right - left + tick <= timedelta(days=1100) for left, right in bounds)
        assert all(
            left_stop + tick == right_start
            for (_, left_stop), (right_start, _) in zip(bounds, bounds[1:], strict=False)
        )


@pytest.mark.parametrize("product_id", ["discharge_instantaneous", "stage_instantaneous"])
@pytest.mark.parametrize("extra", [timedelta(0), timedelta(microseconds=1)])
def test_continuous_cap_keeps_subdaily_precision_and_exact_inclusive_endpoint(product_id, extra):
    start = datetime(2010, 6, 1, 5, 12, 34, 123456)
    end = start + timedelta(days=1100) - timedelta(microseconds=1) + extra
    window = _make_fetch_window(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end))
    planned = plan_windows(window, window_declarations().products[product_id])
    assert len(planned) == (1 if extra == timedelta(0) else 2)
    assert planned[0].start == start.isoformat() + "Z"
    assert planned[-1].stop == end.isoformat() + "Z"
    if extra:
        assert planned[-1] == RenderedWindow(end.isoformat() + "Z", end.isoformat() + "Z")
