"""plan_windows : FetchWindow × WindowDeclaration → tuple[RenderedWindow, ...]."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Callable
from datetime import datetime, time, timedelta

from rivretrieve._internal.engine import (
    FetchWindow,
    RenderedWindow,
    StopConvention,
    WindowDeclaration,
    WindowEndpoint,
    WindowRenderingVocabulary,
    _make_fetch_window,
)

__all__ = ("plan_windows",)

type _Planner = Callable[[FetchWindow, WindowDeclaration], tuple[RenderedWindow, ...]]


def _require(declaration: WindowDeclaration, valid: bool, requirement: str) -> None:
    if not valid:
        raise ValueError(f"window granularity '{declaration.granularity}' requires {requirement}")


def _datetime_from_endpoint(window: FetchWindow, endpoint: str) -> datetime:
    value = window.start if endpoint == "start" else window.end
    return datetime(
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond,
    )


def _iso_z(value: datetime) -> str:
    return f"{value.isoformat()}Z"


def _render_date_stop(value: datetime, convention: StopConvention) -> str:
    if convention is StopConvention.EXCLUSIVE:
        value += timedelta(days=1)
    return value.date().isoformat()


def _plan_iso_instant(fetch_window: FetchWindow, declaration: WindowDeclaration) -> tuple[RenderedWindow, ...]:
    _require(
        declaration,
        declaration.size is None and declaration.rendering is WindowRenderingVocabulary.ISO_INSTANT,
        "size None and iso-instant rendering",
    )
    start = _datetime_from_endpoint(fetch_window, "start")
    stop = _datetime_from_endpoint(fetch_window, "end")
    if declaration.stop_convention is StopConvention.EXCLUSIVE:
        stop += timedelta(microseconds=1)
    return (RenderedWindow(_iso_z(start), _iso_z(stop)),)


def _plan_date(fetch_window: FetchWindow, declaration: WindowDeclaration) -> tuple[RenderedWindow, ...]:
    _require(
        declaration,
        declaration.size is None
        and declaration.rendering in (WindowRenderingVocabulary.DATE, WindowRenderingVocabulary.DATE_DMY),
        "size None and date rendering",
    )
    start = _datetime_from_endpoint(fetch_window, "start").replace(hour=0, minute=0, second=0, microsecond=0)
    stop = _datetime_from_endpoint(fetch_window, "end").replace(hour=0, minute=0, second=0, microsecond=0)
    rendered_stop = _render_date_stop(stop, declaration.stop_convention)
    if declaration.rendering is WindowRenderingVocabulary.DATE_DMY:
        rendered_stop = datetime.fromisoformat(rendered_stop).strftime("%d/%m/%Y")
        return (RenderedWindow(start.strftime("%d/%m/%Y"), rendered_stop),)
    return (RenderedWindow(start.date().isoformat(), rendered_stop),)


def _plan_year(fetch_window: FetchWindow, declaration: WindowDeclaration) -> tuple[RenderedWindow, ...]:
    _require(
        declaration,
        declaration.size is None
        and declaration.rendering in (WindowRenderingVocabulary.YEAR, WindowRenderingVocabulary.DATE),
        "size None and year or date rendering",
    )
    start_year = _datetime_from_endpoint(fetch_window, "start").year
    end_year = _datetime_from_endpoint(fetch_window, "end").year
    if declaration.rendering is WindowRenderingVocabulary.YEAR:
        return tuple(RenderedWindow(str(year), None) for year in range(start_year, end_year + 1))
    windows = []
    for year in range(start_year, end_year + 1):
        start = datetime(year, 1, 1)
        stop = datetime(year, 12, 31)
        windows.append(RenderedWindow(start.date().isoformat(), _render_date_stop(stop, declaration.stop_convention)))
    return tuple(windows)


def _plan_year_month(fetch_window: FetchWindow, declaration: WindowDeclaration) -> tuple[RenderedWindow, ...]:
    _require(
        declaration,
        declaration.size is None
        and declaration.rendering in (WindowRenderingVocabulary.YEAR_MONTH, WindowRenderingVocabulary.DATE),
        "size None and year-month or date rendering",
    )
    cursor = _datetime_from_endpoint(fetch_window, "start").replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    final = _datetime_from_endpoint(fetch_window, "end").replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    windows = []
    while cursor <= final:
        stop = cursor.replace(day=monthrange(cursor.year, cursor.month)[1])
        bounds = _make_fetch_window(
            WindowEndpoint.from_datetime(cursor),
            WindowEndpoint.from_datetime(datetime.combine(stop.date(), time.max)),
        )
        if declaration.rendering is WindowRenderingVocabulary.YEAR_MONTH:
            windows.append(RenderedWindow(f"{cursor.year:04d}-{cursor.month:02d}", None, bounds))
        else:
            windows.append(
                RenderedWindow(
                    cursor.date().isoformat(),
                    _render_date_stop(stop, declaration.stop_convention),
                    bounds,
                )
            )
        if cursor.month == 12:
            cursor = cursor.replace(year=cursor.year + 1, month=1)
        else:
            cursor = cursor.replace(month=cursor.month + 1)
    return tuple(windows)


def _plan_n_year_chunk(fetch_window: FetchWindow, declaration: WindowDeclaration) -> tuple[RenderedWindow, ...]:
    _require(
        declaration,
        declaration.size is not None and declaration.rendering is WindowRenderingVocabulary.DATE,
        "a positive size and date rendering",
    )
    size = declaration.size
    assert size is not None
    cursor = _datetime_from_endpoint(fetch_window, "start").replace(hour=0, minute=0, second=0, microsecond=0)
    final = _datetime_from_endpoint(fetch_window, "end").replace(hour=0, minute=0, second=0, microsecond=0)
    windows = []
    while cursor <= final:
        stop = min(datetime(cursor.year + size - 1, 12, 31), final)
        windows.append(
            RenderedWindow(
                cursor.date().isoformat(),
                _render_date_stop(stop, declaration.stop_convention),
            )
        )
        cursor = stop + timedelta(days=1)
    return tuple(windows)


def _plan_capped_span(fetch_window: FetchWindow, declaration: WindowDeclaration) -> tuple[RenderedWindow, ...]:
    _require(
        declaration,
        declaration.size is not None
        and declaration.rendering in (WindowRenderingVocabulary.DATE, WindowRenderingVocabulary.ISO_INSTANT),
        "a positive size and date or iso-instant rendering",
    )
    size = declaration.size
    assert size is not None
    if (
        declaration.rendering is WindowRenderingVocabulary.ISO_INSTANT
        and declaration.stop_convention is StopConvention.INCLUSIVE
    ):
        cursor = _datetime_from_endpoint(fetch_window, "start")
        final = _datetime_from_endpoint(fetch_window, "end")
        windows = []
        tick = timedelta(microseconds=1)
        while cursor <= final:
            stop = min(cursor + timedelta(days=size) - tick, final)
            windows.append(RenderedWindow(_iso_z(cursor), _iso_z(stop)))
            cursor = stop + tick
        return tuple(windows)
    cursor = _datetime_from_endpoint(fetch_window, "start").replace(hour=0, minute=0, second=0, microsecond=0)
    final = _datetime_from_endpoint(fetch_window, "end").replace(hour=0, minute=0, second=0, microsecond=0)
    windows = []
    while cursor <= final:
        stop = min(cursor + timedelta(days=size - 1), final)
        rendered_stop = stop + timedelta(days=1) if declaration.stop_convention is StopConvention.EXCLUSIVE else stop
        if declaration.rendering is WindowRenderingVocabulary.ISO_INSTANT:
            windows.append(RenderedWindow(_iso_z(cursor), _iso_z(rendered_stop)))
        else:
            windows.append(RenderedWindow(cursor.date().isoformat(), rendered_stop.date().isoformat()))
        cursor = stop + timedelta(days=1)
    return tuple(windows)


def _plan_fixed_backward_span(fetch_window: FetchWindow, declaration: WindowDeclaration) -> tuple[RenderedWindow, ...]:
    """Cover fetch dates by disjoint, fixed-size inclusive spans ending at the final fetch date.

    Each rendered span contains exactly ``size`` whole calendar days. Only the earliest
    span may extend outward, by fewer than ``size`` days before the fetch start date.
    Stops are ``size`` days apart; chronological output never overlaps. The provider
    can use each stop as a backward-range anchor without computing or clipping dates.
    """
    _require(
        declaration,
        declaration.size is not None
        and declaration.rendering is WindowRenderingVocabulary.DATE
        and declaration.stop_convention is StopConvention.INCLUSIVE,
        "a positive size, date rendering and an inclusive stop",
    )
    size = declaration.size
    assert size is not None
    first = _datetime_from_endpoint(fetch_window, "start").replace(hour=0, minute=0, second=0, microsecond=0)
    stop = _datetime_from_endpoint(fetch_window, "end").replace(hour=0, minute=0, second=0, microsecond=0)
    windows = []
    while stop >= first:
        start = stop - timedelta(days=size - 1)
        windows.append(RenderedWindow(start.date().isoformat(), stop.date().isoformat()))
        if start <= first:
            break
        stop = start - timedelta(days=1)
    return tuple(reversed(windows))


def _plan_none(fetch_window: FetchWindow, declaration: WindowDeclaration) -> tuple[RenderedWindow, ...]:
    _require(
        declaration,
        declaration.size is None and declaration.rendering is WindowRenderingVocabulary.NONE,
        "size None and none rendering",
    )
    return ()


_GRANULARITY_PLANNERS: dict[str, _Planner] = {
    "iso-instant": _plan_iso_instant,
    "date": _plan_date,
    "year": _plan_year,
    "year-month": _plan_year_month,
    "n-year-chunk": _plan_n_year_chunk,
    "capped-span": _plan_capped_span,
    "fixed-backward-span": _plan_fixed_backward_span,
    "none": _plan_none,
}


def plan_windows(
    fetch_window: FetchWindow,
    declaration: WindowDeclaration,
) -> tuple[RenderedWindow, ...]:
    if not isinstance(fetch_window, FetchWindow):
        raise TypeError("window planning requires a FetchWindow")
    if not isinstance(declaration, WindowDeclaration):
        raise TypeError("window planning requires a WindowDeclaration")
    try:
        planner = _GRANULARITY_PLANNERS[declaration.granularity]
    except KeyError as error:
        raise ValueError(
            f"unknown window granularity '{declaration.granularity}'; the only extension point is "
            "src/rivretrieve/_internal/window_planning.py"
        ) from error
    return planner(fetch_window, declaration)
