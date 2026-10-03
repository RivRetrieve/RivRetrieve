from __future__ import annotations

from dataclasses import fields
from datetime import datetime

import pytest

from rivretrieve._internal import engine, window_planning
from rivretrieve._internal.primitives import ProductId


def _fetch(start: datetime, end: datetime) -> engine.FetchWindow:
    return engine._make_fetch_window(
        engine.WindowEndpoint.from_datetime(start), engine.WindowEndpoint.from_datetime(end)
    )


def _declaration(
    granularity: str,
    rendering: engine.WindowRenderingVocabulary,
    stop: engine.StopConvention = engine.StopConvention.INCLUSIVE,
    size: int | None = None,
) -> engine.WindowDeclaration:
    return engine.WindowDeclaration(engine.WindowGranularity(granularity), rendering, stop, size)


def _pairs(windows: tuple[engine.RenderedWindow, ...]) -> tuple[tuple[str, str | None], ...]:
    return tuple((window.start, window.stop) for window in windows)


@pytest.mark.parametrize(
    ("case", "start", "end", "declaration", "expected"),
    [
        (
            "ba_fhmzbih",
            datetime(2020, 7, 1, 0, 30),
            datetime(2020, 7, 1, 23),
            _declaration("none", engine.WindowRenderingVocabulary.NONE),
            (),
        ),
        (
            "ch_foen",
            datetime(2020, 1, 1, 12, 34, 56),
            datetime(2021, 1, 1, 23, 45),
            _declaration(
                "capped-span", engine.WindowRenderingVocabulary.ISO_INSTANT, engine.StopConvention.EXCLUSIVE, 366
            ),
            (("2020-01-01T00:00:00Z", "2021-01-01T00:00:00Z"), ("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")),
        ),
        (
            "cz_chmi",
            datetime(2019, 12, 20),
            datetime(2021, 1, 10),
            _declaration("year", engine.WindowRenderingVocabulary.YEAR),
            (("2019", None), ("2020", None), ("2021", None)),
        ),
        (
            "fr_hubeau",
            datetime(2021, 1, 1, 12),
            datetime(2022, 1, 1, 13),
            _declaration("capped-span", engine.WindowRenderingVocabulary.DATE, size=365),
            (("2021-01-01", "2021-12-31"), ("2022-01-01", "2022-01-01")),
        ),
        (
            "jp_mlit_hourly",
            datetime(2019, 12, 20),
            datetime(2020, 1, 10),
            _declaration("year-month", engine.WindowRenderingVocabulary.DATE),
            (("2019-12-01", "2019-12-31"), ("2020-01-01", "2020-01-31")),
        ),
        (
            "jp_mlit_daily",
            datetime(2019, 12, 20),
            datetime(2020, 1, 10),
            _declaration("year", engine.WindowRenderingVocabulary.DATE),
            (("2019-01-01", "2019-12-31"), ("2020-01-01", "2020-12-31")),
        ),
        (
            "lt_lhmt",
            datetime(2019, 12, 20),
            datetime(2020, 1, 10),
            _declaration("year-month", engine.WindowRenderingVocabulary.YEAR_MONTH),
            (("2019-12", None), ("2020-01", None)),
        ),
        (
            "pl_imgw",
            datetime(2020, 7, 1, 0, 30),
            datetime(2020, 7, 1, 23),
            _declaration("none", engine.WindowRenderingVocabulary.NONE),
            (),
        ),
        (
            "th_thaiwater",
            datetime(2021, 1, 1, 12),
            datetime(2022, 1, 1, 13),
            _declaration("capped-span", engine.WindowRenderingVocabulary.DATE, size=365),
            (("2021-01-01", "2021-12-31"), ("2022-01-01", "2022-01-01")),
        ),
        (
            "za_dws_daily",
            datetime(2010, 7, 15),
            datetime(2031, 2, 3),
            _declaration("n-year-chunk", engine.WindowRenderingVocabulary.DATE, size=20),
            (("2010-07-15", "2029-12-31"), ("2030-01-01", "2031-02-03")),
        ),
        (
            "za_dws_point",
            datetime(2010, 7, 15),
            datetime(2012, 2, 3),
            _declaration("n-year-chunk", engine.WindowRenderingVocabulary.DATE, size=1),
            (("2010-07-15", "2010-12-31"), ("2011-01-01", "2011-12-31"), ("2012-01-01", "2012-02-03")),
        ),
    ],
)
def test_surveyed_provider_window_renderings_are_byte_exact(
    case: str,
    start: datetime,
    end: datetime,
    declaration: engine.WindowDeclaration,
    expected: tuple[tuple[str, str | None], ...],
) -> None:
    windows = window_planning.plan_windows(_fetch(start, end), declaration)
    assert _pairs(windows) == expected


def test_product_window_declarations_keep_product_variants_separate_from_product_config() -> None:
    hourly = _declaration("year-month", engine.WindowRenderingVocabulary.DATE)
    daily = _declaration("year", engine.WindowRenderingVocabulary.DATE)
    point = _declaration("n-year-chunk", engine.WindowRenderingVocabulary.DATE, size=1)
    daily_chunks = _declaration("n-year-chunk", engine.WindowRenderingVocabulary.DATE, size=20)
    jp = engine.ProductWindowDeclarations(
        {ProductId("stage_hourly_mean"): hourly, ProductId("discharge_daily_mean"): daily}
    )
    za = engine.ProductWindowDeclarations(
        {
            ProductId("discharge_instantaneous"): point,
            ProductId("discharge_daily_mean"): daily_chunks,
        }
    )

    assert jp.products[ProductId("stage_hourly_mean")] is hourly
    assert jp.products[ProductId("discharge_daily_mean")] is daily
    assert za.products[ProductId("discharge_instantaneous")] is point
    assert za.products[ProductId("discharge_daily_mean")] is daily_chunks
    assert _pairs(window_planning.plan_windows(_fetch(datetime(2019, 12, 20), datetime(2020, 1, 10)), hourly)) == (
        ("2019-12-01", "2019-12-31"),
        ("2020-01-01", "2020-01-31"),
    )
    assert _pairs(window_planning.plan_windows(_fetch(datetime(2010, 7, 15), datetime(2012, 2, 3)), point)) == (
        ("2010-07-15", "2010-12-31"),
        ("2011-01-01", "2011-12-31"),
        ("2012-01-01", "2012-02-03"),
    )
    with pytest.raises(TypeError):
        jp.products[ProductId("new")] = hourly  # type: ignore[index]
    assert tuple(field.name for field in fields(engine.ProductConfig)) == (
        "coordinates",
        "unit",
        "semantics",
    )


def test_inclusive_and_exclusive_stop_rendering_are_exact() -> None:
    day = _fetch(datetime(2020, 2, 29, 12), datetime(2020, 2, 29, 12))
    assert _pairs(window_planning.plan_windows(day, _declaration("date", engine.WindowRenderingVocabulary.DATE))) == (
        ("2020-02-29", "2020-02-29"),
    )
    assert _pairs(
        window_planning.plan_windows(
            day,
            _declaration("date", engine.WindowRenderingVocabulary.DATE, engine.StopConvention.EXCLUSIVE),
        )
    ) == (("2020-02-29", "2020-03-01"),)
    instant = _fetch(datetime(2020, 2, 29, 12), datetime(2020, 2, 29, 12, 0, 0, 1))
    assert _pairs(
        window_planning.plan_windows(instant, _declaration("iso-instant", engine.WindowRenderingVocabulary.ISO_INSTANT))
    ) == (("2020-02-29T12:00:00Z", "2020-02-29T12:00:00.000001Z"),)
    assert _pairs(
        window_planning.plan_windows(
            instant,
            _declaration(
                "iso-instant",
                engine.WindowRenderingVocabulary.ISO_INSTANT,
                engine.StopConvention.EXCLUSIVE,
            ),
        )
    ) == (("2020-02-29T12:00:00Z", "2020-02-29T12:00:00.000002Z"),)


def test_unknown_window_granularity_is_refused() -> None:
    declaration = _declaration("fortnightly", engine.WindowRenderingVocabulary.DATE)
    with pytest.raises(ValueError, match="unknown window granularity 'fortnightly'"):
        window_planning.plan_windows(_fetch(datetime(2020, 1, 1), datetime(2020, 1, 2)), declaration)


@pytest.mark.parametrize(
    ("declaration", "requirement"),
    [
        (_declaration("iso-instant", engine.WindowRenderingVocabulary.DATE), "size None and iso-instant rendering"),
        (_declaration("date", engine.WindowRenderingVocabulary.YEAR), "size None and date rendering"),
        (_declaration("year", engine.WindowRenderingVocabulary.YEAR_MONTH), "size None and year or date rendering"),
        (
            _declaration("year-month", engine.WindowRenderingVocabulary.YEAR),
            "size None and year-month or date rendering",
        ),
        (_declaration("n-year-chunk", engine.WindowRenderingVocabulary.DATE), "a positive size and date rendering"),
        (
            _declaration("capped-span", engine.WindowRenderingVocabulary.YEAR, size=2),
            "a positive size and date or iso-instant rendering",
        ),
        (_declaration("none", engine.WindowRenderingVocabulary.NONE, size=1), "size None and none rendering"),
    ],
)
def test_recognized_declarations_fail_loudly_on_wrong_shape(
    declaration: engine.WindowDeclaration, requirement: str
) -> None:
    with pytest.raises(ValueError) as exc:
        window_planning.plan_windows(_fetch(datetime(2020, 1, 1), datetime(2020, 1, 2)), declaration)
    assert str(exc.value) == f"window granularity '{declaration.granularity}' requires {requirement}"


def test_window_planning_carrier_type_diagnostics_are_exact() -> None:
    window = _fetch(datetime(2020, 1, 1), datetime(2020, 1, 2))
    declaration = _declaration("date", engine.WindowRenderingVocabulary.DATE)
    with pytest.raises(TypeError, match="^window planning requires a FetchWindow$"):
        window_planning.plan_windows(object(), declaration)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="^window planning requires a WindowDeclaration$"):
        window_planning.plan_windows(window, object())  # type: ignore[arg-type]

    invalid: list[tuple[object, str]] = [
        (
            lambda: engine.WindowDeclaration(
                "", engine.WindowRenderingVocabulary.DATE, engine.StopConvention.INCLUSIVE
            ),
            "window granularity must be a non-empty string",
        ),
        (
            lambda: engine.WindowDeclaration(engine.WindowGranularity("date"), "date", engine.StopConvention.INCLUSIVE),
            "window rendering must be WindowRenderingVocabulary",
        ),
        (
            lambda: engine.WindowDeclaration(
                engine.WindowGranularity("date"), engine.WindowRenderingVocabulary.DATE, "inclusive"
            ),
            "window stop convention must be StopConvention",
        ),
        (
            lambda: engine.WindowDeclaration(
                engine.WindowGranularity("date"),
                engine.WindowRenderingVocabulary.DATE,
                engine.StopConvention.INCLUSIVE,
                True,
            ),
            "window granularity size must be a positive integer or None",
        ),
        (lambda: engine.ProductWindowDeclarations([]), "product window declarations must be a mapping"),
        (
            lambda: engine.ProductWindowDeclarations({"": declaration}),
            "product window declaration keys must be non-empty ProductId values",
        ),
        (
            lambda: engine.ProductWindowDeclarations({ProductId("x"): object()}),
            "product window declaration values must be WindowDeclaration values",
        ),
        (lambda: engine.RenderedWindow("", None), "rendered window start must be a non-empty string"),
        (lambda: engine.RenderedWindow("start", ""), "rendered window stop must be a non-empty string or None"),
    ]
    for factory, message in invalid:
        with pytest.raises(TypeError) as exc:
            factory()  # type: ignore[operator]
        assert str(exc.value) == message


@pytest.mark.parametrize("days", [1, 2, 29, 30, 31, 59, 60, 61, 365, 366])
@pytest.mark.parametrize("end", [datetime(2024, 1, 4, 12, 30), datetime(2024, 3, 1), datetime(2025, 1, 1)])
@pytest.mark.parametrize("size", [1, 7, 30])
def test_fixed_backward_spans_cover_whole_fetch_dates_without_overlap(days: int, end: datetime, size: int) -> None:
    from datetime import timedelta

    start = end - timedelta(days=days - 1)
    windows = window_planning.plan_windows(
        _fetch(start, end),
        _declaration("fixed-backward-span", engine.WindowRenderingVocabulary.DATE, size=size),
    )
    bounds = [(datetime.fromisoformat(w.start), datetime.fromisoformat(w.stop)) for w in windows if w.stop]
    assert len(bounds) == (days + size - 1) // size
    assert bounds[-1][1].date() == end.date()
    assert 0 <= (start.date() - bounds[0][0].date()).days < size
    for left, right in bounds:
        assert (right - left).days == size - 1
    for previous, current in zip(bounds, bounds[1:], strict=False):
        assert current[0] - previous[1] == timedelta(days=1)


@pytest.mark.parametrize(
    "declaration",
    [
        _declaration("fixed-backward-span", engine.WindowRenderingVocabulary.DATE),
        _declaration("fixed-backward-span", engine.WindowRenderingVocabulary.ISO_INSTANT, size=30),
        _declaration("fixed-backward-span", engine.WindowRenderingVocabulary.DATE, engine.StopConvention.EXCLUSIVE, 30),
    ],
)
def test_fixed_backward_span_refuses_unsupported_declarations(declaration: engine.WindowDeclaration) -> None:
    with pytest.raises(ValueError, match="requires"):
        window_planning.plan_windows(_fetch(datetime(2024, 1, 1), datetime(2024, 1, 2)), declaration)


@pytest.mark.parametrize("rendering", [engine.WindowRenderingVocabulary.YEAR, engine.WindowRenderingVocabulary.DATE])
def test_annual_bounds_cover_closed_calendar_years(rendering):
    windows = window_planning.plan_windows(
        _fetch(datetime(2020, 6, 1), datetime(2021, 2, 1)), _declaration("year", rendering)
    )
    assert [window.bounds for window in windows] == [
        _fetch(datetime(year, 1, 1), datetime(year, 12, 31, 23, 59, 59, 999999)) for year in (2020, 2021)
    ]


@pytest.mark.parametrize("convention", list(engine.StopConvention))
def test_capped_date_bounds_do_not_include_exclusive_stop(convention):
    windows = window_planning.plan_windows(
        _fetch(datetime(2020, 2, 28), datetime(2020, 3, 2)),
        _declaration("capped-span", engine.WindowRenderingVocabulary.DATE, convention, 2),
    )
    assert [window.bounds for window in windows] == [
        _fetch(datetime(2020, 2, 28), datetime(2020, 2, 29, 23, 59, 59, 999999)),
        _fetch(datetime(2020, 3, 1), datetime(2020, 3, 2, 23, 59, 59, 999999)),
    ]


def test_inclusive_instant_bounds_preserve_microsecond_partition():
    windows = window_planning.plan_windows(
        _fetch(datetime(2020, 2, 28, 12), datetime(2020, 3, 1, 12)),
        _declaration("capped-span", engine.WindowRenderingVocabulary.ISO_INSTANT, size=2),
    )
    assert [window.bounds for window in windows] == [
        _fetch(datetime(2020, 2, 28, 12), datetime(2020, 3, 1, 11, 59, 59, 999999)),
        _fetch(datetime(2020, 3, 1, 12), datetime(2020, 3, 1, 12)),
    ]


def test_backward_bounds_include_outward_earliest_days():
    windows = window_planning.plan_windows(
        _fetch(datetime(2020, 2, 29), datetime(2020, 3, 2)),
        _declaration("fixed-backward-span", engine.WindowRenderingVocabulary.DATE, size=2),
    )
    assert [window.bounds for window in windows] == [
        _fetch(datetime(2020, 2, 28), datetime(2020, 2, 29, 23, 59, 59, 999999)),
        _fetch(datetime(2020, 3, 1), datetime(2020, 3, 2, 23, 59, 59, 999999)),
    ]


def test_published_hours_one_to_twenty_four_shift_only_monthly_label_bounds():
    declaration = engine.WindowDeclaration(
        engine.WindowGranularity("year-month"),
        engine.WindowRenderingVocabulary.DATE,
        engine.StopConvention.INCLUSIVE,
        calendar_labels=engine.CalendarLabelConvention.HOURS_1_TO_24,
    )
    windows = window_planning.plan_windows(_fetch(datetime(2020, 1, 3), datetime(2020, 2, 3)), declaration)
    assert _pairs(windows) == (("2020-01-01", "2020-01-31"), ("2020-02-01", "2020-02-29"))
    assert [window.bounds for window in windows] == [
        _fetch(datetime(2020, 1, 1, 0, 0, 0, 1), datetime(2020, 2, 1)),
        _fetch(datetime(2020, 2, 1, 0, 0, 0, 1), datetime(2020, 3, 1)),
    ]


def test_hourly_calendar_label_convention_requires_monthly_date_requests():
    with pytest.raises(ValueError, match="monthly date"):
        engine.WindowDeclaration(
            engine.WindowGranularity("year"),
            engine.WindowRenderingVocabulary.YEAR,
            engine.StopConvention.INCLUSIVE,
            calendar_labels=engine.CalendarLabelConvention.HOURS_1_TO_24,
        )
