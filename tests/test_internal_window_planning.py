from __future__ import annotations

import ast
from dataclasses import fields
from datetime import datetime
from pathlib import Path

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


def _requests(case: str, windows: tuple[engine.RenderedWindow, ...]) -> tuple[str, ...]:
    if case in {"ba_fhmzbih", "pl_imgw"}:
        return ()
    if case == "ch_foen":
        return tuple(
            f'from(bucket: "existenzApi") |> range(start: {window.start}, stop: {window.stop}) '
            '|> filter(fn: (r) => r["_measurement"] == "hydro") '
            '|> filter(fn: (r) => r["loc"] == "2206") '
            '|> filter(fn: (r) => r["_field"] == "flow" or r["_field"] == "flow_ls")'
            for window in windows
        )
    if case == "cz_chmi":
        return tuple(
            f"https://opendata.chmi.cz/hydrology/historical/data/daily/H_0-203-1-016000_DQ_{window.start}.json"
            for window in windows
        )
    if case == "fr_hubeau":
        return tuple(
            "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab?"
            f"code_entite=O0050010&date_debut_obs={window.start}&date_fin_obs={window.stop}"
            "&grandeur_hydro=QmnJ&size=20000"
            for window in windows
        )
    if case.startswith("jp_mlit"):
        kind = "2" if case.endswith("hourly") else "7"
        return tuple(
            "http://www1.river.go.jp/cgi-bin/DspWaterData.exe?"
            f"KIND={kind}&ID=301011281104010&BGNDATE={window.start.replace('-', '')}"
            f"&ENDDATE={window.stop.replace('-', '')}&KAWABOU=NO"
            for window in windows
            if window.stop is not None
        )
    if case == "lt_lhmt":
        return tuple(
            f"https://api.meteo.lt/v1/hydro-stations/anyksciu-vms/observations/historical/{window.start}"
            for window in windows
        )
    if case == "th_thaiwater":
        return tuple(
            "https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_graph?"
            f"station_type=tele_waterlevel&station_id=S13A&start_date={window.start}"
            f"&end_date={window.stop}"
            for window in windows
        )
    data_type = "Daily" if case.endswith("daily") else "Point"
    return tuple(
        "https://www.dws.gov.za/Hydrology/Verified/HyData.aspx?"
        f"Station=X3H001100.00&DataType={data_type}&StartDT={window.start}"
        f"&EndDT={window.stop}&SiteType=RIV"
        for window in windows
    )


@pytest.mark.parametrize(
    ("case", "start", "end", "declaration", "expected", "expected_requests"),
    [
        (
            "ba_fhmzbih",
            datetime(2020, 7, 1, 0, 30),
            datetime(2020, 7, 1, 23),
            _declaration("none", engine.WindowRenderingVocabulary.NONE),
            (),
            (),
        ),
        (
            "ch_foen",
            datetime(2020, 1, 1, 12, 34, 56),
            datetime(2021, 1, 1, 23, 45),
            _declaration(
                "capped-span",
                engine.WindowRenderingVocabulary.ISO_INSTANT,
                engine.StopConvention.EXCLUSIVE,
                366,
            ),
            (
                ("2020-01-01T00:00:00Z", "2021-01-01T00:00:00Z"),
                ("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z"),
            ),
            (
                'from(bucket: "existenzApi") |> range(start: 2020-01-01T00:00:00Z, stop: 2021-01-01T00:00:00Z) |> filter(fn: (r) => r["_measurement"] == "hydro") |> filter(fn: (r) => r["loc"] == "2206") |> filter(fn: (r) => r["_field"] == "flow" or r["_field"] == "flow_ls")',
                'from(bucket: "existenzApi") |> range(start: 2021-01-01T00:00:00Z, stop: 2021-01-02T00:00:00Z) |> filter(fn: (r) => r["_measurement"] == "hydro") |> filter(fn: (r) => r["loc"] == "2206") |> filter(fn: (r) => r["_field"] == "flow" or r["_field"] == "flow_ls")',
            ),
        ),
        (
            "cz_chmi",
            datetime(2019, 12, 20),
            datetime(2021, 1, 10),
            _declaration("year", engine.WindowRenderingVocabulary.YEAR),
            (("2019", None), ("2020", None), ("2021", None)),
            tuple(
                f"https://opendata.chmi.cz/hydrology/historical/data/daily/H_0-203-1-016000_DQ_{year}.json"
                for year in (2019, 2020, 2021)
            ),
        ),
        (
            "fr_hubeau",
            datetime(2021, 1, 1, 12),
            datetime(2022, 1, 1, 13),
            _declaration("capped-span", engine.WindowRenderingVocabulary.DATE, size=365),
            (("2021-01-01", "2021-12-31"), ("2022-01-01", "2022-01-01")),
            (
                "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab?code_entite=O0050010&date_debut_obs=2021-01-01&date_fin_obs=2021-12-31&grandeur_hydro=QmnJ&size=20000",
                "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab?code_entite=O0050010&date_debut_obs=2022-01-01&date_fin_obs=2022-01-01&grandeur_hydro=QmnJ&size=20000",
            ),
        ),
        (
            "jp_mlit_hourly",
            datetime(2019, 12, 20),
            datetime(2020, 1, 10),
            _declaration("year-month", engine.WindowRenderingVocabulary.DATE),
            (("2019-12-01", "2019-12-31"), ("2020-01-01", "2020-01-31")),
            (
                "http://www1.river.go.jp/cgi-bin/DspWaterData.exe?KIND=2&ID=301011281104010&BGNDATE=20191201&ENDDATE=20191231&KAWABOU=NO",
                "http://www1.river.go.jp/cgi-bin/DspWaterData.exe?KIND=2&ID=301011281104010&BGNDATE=20200101&ENDDATE=20200131&KAWABOU=NO",
            ),
        ),
        (
            "jp_mlit_daily",
            datetime(2019, 12, 20),
            datetime(2020, 1, 10),
            _declaration("year", engine.WindowRenderingVocabulary.DATE),
            (("2019-01-01", "2019-12-31"), ("2020-01-01", "2020-12-31")),
            (
                "http://www1.river.go.jp/cgi-bin/DspWaterData.exe?KIND=7&ID=301011281104010&BGNDATE=20190101&ENDDATE=20191231&KAWABOU=NO",
                "http://www1.river.go.jp/cgi-bin/DspWaterData.exe?KIND=7&ID=301011281104010&BGNDATE=20200101&ENDDATE=20201231&KAWABOU=NO",
            ),
        ),
        (
            "lt_lhmt",
            datetime(2019, 12, 20),
            datetime(2020, 1, 10),
            _declaration("year-month", engine.WindowRenderingVocabulary.YEAR_MONTH),
            (("2019-12", None), ("2020-01", None)),
            (
                "https://api.meteo.lt/v1/hydro-stations/anyksciu-vms/observations/historical/2019-12",
                "https://api.meteo.lt/v1/hydro-stations/anyksciu-vms/observations/historical/2020-01",
            ),
        ),
        (
            "pl_imgw",
            datetime(2020, 7, 1, 0, 30),
            datetime(2020, 7, 1, 23),
            _declaration("none", engine.WindowRenderingVocabulary.NONE),
            (),
            (),
        ),
        (
            "th_thaiwater",
            datetime(2021, 1, 1, 12),
            datetime(2022, 1, 1, 13),
            _declaration("capped-span", engine.WindowRenderingVocabulary.DATE, size=365),
            (("2021-01-01", "2021-12-31"), ("2022-01-01", "2022-01-01")),
            (
                "https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_graph?station_type=tele_waterlevel&station_id=S13A&start_date=2021-01-01&end_date=2021-12-31",
                "https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_graph?station_type=tele_waterlevel&station_id=S13A&start_date=2022-01-01&end_date=2022-01-01",
            ),
        ),
        (
            "za_dws_daily",
            datetime(2010, 7, 15),
            datetime(2031, 2, 3),
            _declaration("n-year-chunk", engine.WindowRenderingVocabulary.DATE, size=20),
            (("2010-07-15", "2029-12-31"), ("2030-01-01", "2031-02-03")),
            (
                "https://www.dws.gov.za/Hydrology/Verified/HyData.aspx?Station=X3H001100.00&DataType=Daily&StartDT=2010-07-15&EndDT=2029-12-31&SiteType=RIV",
                "https://www.dws.gov.za/Hydrology/Verified/HyData.aspx?Station=X3H001100.00&DataType=Daily&StartDT=2030-01-01&EndDT=2031-02-03&SiteType=RIV",
            ),
        ),
        (
            "za_dws_point",
            datetime(2010, 7, 15),
            datetime(2012, 2, 3),
            _declaration("n-year-chunk", engine.WindowRenderingVocabulary.DATE, size=1),
            (
                ("2010-07-15", "2010-12-31"),
                ("2011-01-01", "2011-12-31"),
                ("2012-01-01", "2012-02-03"),
            ),
            (
                "https://www.dws.gov.za/Hydrology/Verified/HyData.aspx?Station=X3H001100.00&DataType=Point&StartDT=2010-07-15&EndDT=2010-12-31&SiteType=RIV",
                "https://www.dws.gov.za/Hydrology/Verified/HyData.aspx?Station=X3H001100.00&DataType=Point&StartDT=2011-01-01&EndDT=2011-12-31&SiteType=RIV",
                "https://www.dws.gov.za/Hydrology/Verified/HyData.aspx?Station=X3H001100.00&DataType=Point&StartDT=2012-01-01&EndDT=2012-02-03&SiteType=RIV",
            ),
        ),
    ],
)
def test_surveyed_provider_window_renderings_are_byte_exact(
    case: str,
    start: datetime,
    end: datetime,
    declaration: engine.WindowDeclaration,
    expected: tuple[tuple[str, str | None], ...],
    expected_requests: tuple[str, ...],
) -> None:
    windows = window_planning.plan_windows(_fetch(start, end), declaration)

    assert _pairs(windows) == expected
    assert _requests(case, windows) == expected_requests


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


def test_unknown_fortnightly_names_the_only_extension_module() -> None:
    declaration = _declaration("fortnightly", engine.WindowRenderingVocabulary.DATE)
    with pytest.raises(ValueError) as exc:
        window_planning.plan_windows(_fetch(datetime(2020, 1, 1), datetime(2020, 1, 2)), declaration)
    message = str(exc.value)
    assert message == (
        "unknown window granularity 'fortnightly'; the only extension point is "
        "src/rivretrieve/_internal/window_planning.py"
    )
    assert sum(part.endswith(".py") for part in message.split()) == 1


def test_registering_a_granularity_does_not_widen_the_public_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public = {
        name
        for name, value in vars(window_planning).items()
        if not name.startswith("_") and getattr(value, "__module__", None) == window_planning.__name__
    }
    assert window_planning.__all__ == ("plan_windows",)
    assert public == {"plan_windows"}

    def _plan_fortnightly(
        fetch_window: engine.FetchWindow, declaration: engine.WindowDeclaration
    ) -> tuple[engine.RenderedWindow, ...]:
        return (engine.RenderedWindow("2020-01", None),)

    monkeypatch.setitem(window_planning._GRANULARITY_PLANNERS, "fortnightly", _plan_fortnightly)
    result = window_planning.plan_windows(
        _fetch(datetime(2020, 1, 1), datetime(2020, 1, 2)),
        _declaration("fortnightly", engine.WindowRenderingVocabulary.DATE),
    )
    assert result == (engine.RenderedWindow("2020-01", None),)
    assert {
        name
        for name, value in vars(window_planning).items()
        if not name.startswith("_") and getattr(value, "__module__", None) == window_planning.__name__
    } == {"plan_windows"}


def test_granularity_registry_and_decomposition_arithmetic_have_one_home() -> None:
    internal = Path(__file__).parents[1] / "src" / "rivretrieve" / "_internal"
    assignments: list[Path] = []
    handler_locations: dict[str, list[Path]] = {}
    keys: set[str] = set()
    for path in internal.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(target, ast.Name) and target.id == "_GRANULARITY_PLANNERS" for target in targets):
                    assignments.append(path)
                    value = node.value
                    assert isinstance(value, ast.Dict)
                    keys = {key.value for key in value.keys if isinstance(key, ast.Constant)}
                    for handler in value.values:
                        assert isinstance(handler, ast.Name)
                        handler_locations.setdefault(handler.id, [])
    for path in internal.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in handler_locations:
                handler_locations[node.name].append(path)
    planner_path = internal / "window_planning.py"
    assert assignments == [planner_path]
    assert keys == {
        "iso-instant",
        "date",
        "year",
        "year-month",
        "n-year-chunk",
        "capped-span",
        "fixed-backward-span",
        "none",
    }
    assert all(locations == [planner_path] for locations in handler_locations.values())


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
