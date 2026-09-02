from datetime import datetime

from rivretrieve._internal.engine import (
    StopConvention,
    WindowDeclaration,
    WindowEndpoint,
    WindowGranularity,
    WindowRenderingVocabulary,
    _make_fetch_window,
)
from rivretrieve._internal.window_planning import plan_windows


def test_hydroportail_date_windows_render_dmy_in_shared_planner():
    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2020, 1, 1)), WindowEndpoint.from_datetime(datetime(2020, 1, 2))
    )
    declaration = WindowDeclaration(
        WindowGranularity("date"), WindowRenderingVocabulary.DATE_DMY, StopConvention.INCLUSIVE
    )
    assert tuple((item.start, item.stop) for item in plan_windows(window, declaration)) == (
        ("01/01/2020", "02/01/2020"),
    )
