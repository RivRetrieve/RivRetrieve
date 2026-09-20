from datetime import date, datetime

from rivretrieve._internal.engine import RenderedWindow, WindowEndpoint, _make_fetch_window
from rivretrieve._internal.providers.usgs_nwis.config import window_declarations
from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import build_provider_info
from rivretrieve._internal.window_planning import plan_windows


def test_provider_metadata_matches_multiyear_window_planning() -> None:
    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2020, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2023, 12, 31)),
    )
    for declaration in window_declarations().products.values():
        assert plan_windows(window, declaration) == (RenderedWindow("2020-01-01", "2023-12-31"),)
    assert build_provider_info(date(2026, 8, 2))["bulk_observations"] == (
        "true: requests per station-product pair; "
        "DV and IV endpoints selected by product; "
        "partial failures reported as recoverable issues"
    )
