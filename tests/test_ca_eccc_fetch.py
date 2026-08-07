from __future__ import annotations

import ast
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import pytest

from rivretrieve._internal.engine import (
    FetchWindow,
    RenderedWindow,
    SourceQuery,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.ca_eccc import fetch as fetch_module
from rivretrieve._internal.providers.ca_eccc.config import config
from rivretrieve._internal.providers.ca_eccc.fetch import fetch
from rivretrieve._internal.providers.ca_eccc.observation_client import HydatClient


def _create_table(
    connection: sqlite3.Connection,
    table_name: str,
    value_prefix: str,
    symbol_prefix: str,
    rows: list[tuple[str, int, int, int, dict[int, tuple[float, str]]]],
) -> None:
    day_columns = ", ".join(f"{value_prefix}{day} REAL, {symbol_prefix}{day} TEXT" for day in range(1, 32))
    connection.execute(
        f"CREATE TABLE {table_name} (STATION_NUMBER TEXT, YEAR INTEGER, MONTH INTEGER, NO_DAYS INTEGER, {day_columns})"
    )
    placeholders = ", ".join("?" for _ in range(66))
    for station_id, year, month, no_days, values in rows:
        row: list[object] = [station_id, year, month, no_days]
        for day in range(1, 32):
            value = values.get(day)
            row.append(value[0] if value is not None else None)
            row.append(value[1] if value is not None else None)
        connection.execute(
            f"INSERT INTO {table_name} VALUES ({placeholders})",
            row,
        )


@pytest.fixture
def hydat_db(tmp_path: Path) -> Path:
    sqlite_path = tmp_path / "Hydat.sqlite3"
    connection = sqlite3.connect(sqlite_path)
    _create_table(
        connection,
        "DLY_FLOWS",
        "FLOW",
        "FLOW_SYMBOL",
        [
            ("02GA010", 2010, 1, 31, {1: (16.0, ""), 2: (17.0, "B")}),
            ("02GA010", 2010, 12, 31, {31: (21.0, "")}),
        ],
    )
    _create_table(
        connection,
        "DLY_LEVELS",
        "LEVEL",
        "LEVEL_SYMBOL",
        [("02GA010", 2010, 1, 31, {1: (1.1, ""), 2: (1.2, "E")})],
    )
    connection.commit()
    connection.close()
    return sqlite_path


def _window(
    start: datetime = datetime(2010, 1, 2),
    end: datetime = datetime(2010, 1, 2),
) -> FetchWindow:
    return _make_fetch_window(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end))


def _renderings(*products: ProductId) -> Mapping[ProductId, tuple[RenderedWindow, ...]]:
    return MappingProxyType({product: (RenderedWindow("2010", None),) for product in products})


def _point_fetch_at(
    monkeypatch: pytest.MonkeyPatch,
    sqlite_path: Path | None,
) -> None:
    monkeypatch.setattr(fetch_module, "default_cache_dir", lambda: Path("/unused/cache"))
    monkeypatch.setattr(fetch_module, "_find_sqlite", lambda _cache_dir: sqlite_path)


def test_fetch_returns_tagged_non_http_hydat_payloads_for_both_products(
    hydat_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _point_fetch_at(monkeypatch, hydat_db)
    fetch_window = _window()

    result = fetch(
        ("02GA010",),
        (
            ProductId("discharge_daily_mean"),
            ProductId("stage_daily_mean"),
        ),
        _renderings(ProductId("discharge_daily_mean"), ProductId("stage_daily_mean")),
        fetch_window,
        config,
    )

    assert result.issues == ()
    assert len(result.value) == 2
    discharge, stage = result.value
    assert discharge.source_coordinates is config.products[ProductId("discharge_daily_mean")].coordinates
    assert discharge.station_products == (("02GA010", ProductId("discharge_daily_mean")),)
    assert discharge.fetch_window is fetch_window
    assert type(discharge.content) is bytes
    discharge_rows = cast(list[dict[str, object]], json.loads(discharge.content.decode("utf-8")))
    assert all(type(row) is dict for row in discharge_rows)
    assert [row["MONTH"] for row in discharge_rows] == [1, 12]
    assert discharge.content == json.dumps(
        discharge_rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    assert discharge.origin.source_path == str(hydat_db.resolve())
    assert discharge.origin.content_type == "application/json"
    assert discharge.origin.query == SourceQuery(
        'SELECT * FROM "DLY_FLOWS" WHERE STATION_NUMBER = ? AND YEAR BETWEEN ? AND ? ORDER BY YEAR, MONTH',
        ("02GA010", "2010", "2010"),
    )
    for fact in (
        discharge.origin.url,
        discharge.origin.request_parameters,
        discharge.origin.status_code,
        discharge.origin.retrieved_at,
    ):
        assert isinstance(fact, UnknownOriginFact)
    assert "headers" not in {field.name for field in fields(discharge.origin)}

    assert stage.source_coordinates is config.products[ProductId("stage_daily_mean")].coordinates
    assert stage.station_products == (("02GA010", ProductId("stage_daily_mean")),)
    assert stage.fetch_window is fetch_window
    assert type(stage.content) is bytes
    stage_rows = cast(list[dict[str, object]], json.loads(stage.content.decode("utf-8")))
    assert all(type(row) is dict for row in stage_rows)
    assert [row["MONTH"] for row in stage_rows] == [1]
    assert stage.content == json.dumps(
        stage_rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    assert stage.origin.source_path == str(hydat_db.resolve())
    assert stage.origin.content_type == "application/json"
    assert stage.origin.query == SourceQuery(
        'SELECT * FROM "DLY_LEVELS" WHERE STATION_NUMBER = ? AND YEAR BETWEEN ? AND ? ORDER BY YEAR, MONTH',
        ("02GA010", "2010", "2010"),
    )
    for fact in (
        stage.origin.url,
        stage.origin.request_parameters,
        stage.origin.status_code,
        stage.origin.retrieved_at,
    ):
        assert isinstance(fact, UnknownOriginFact)
    assert "headers" not in {field.name for field in fields(stage.origin)}

    http_only_facts = (
        "https://source.example/data",
        "Authorization",
        "Bearer transport-secret",
        "X-API-Key",
        "api-key-secret",
    )
    known_http_call = (
        "https://source.example/data",
        "Authorization: Bearer transport-secret",
        "X-API-Key: api-key-secret",
    )
    for forbidden in http_only_facts:
        assert any(forbidden in candidate for candidate in known_http_call)
    for origin in (discharge.origin, stage.origin):
        scanned = tuple(str(getattr(origin, field.name)) for field in fields(origin))
        for forbidden in http_only_facts:
            assert all(forbidden not in candidate for candidate in scanned)


def test_fetch_opens_sqlite_once_per_request(
    hydat_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _point_fetch_at(monkeypatch, hydat_db)
    real_connect = sqlite3.connect
    calls: list[tuple[str]] = []

    def recording_connect(database: str, *, uri: bool = False) -> sqlite3.Connection:
        calls.append((database,))
        return real_connect(database, uri=uri)

    monkeypatch.setattr(fetch_module.sqlite3, "connect", recording_connect)

    result = fetch(
        ("02GA010", "ABSENT"),
        (
            ProductId("discharge_daily_mean"),
            ProductId("stage_daily_mean"),
        ),
        _renderings(ProductId("discharge_daily_mean"), ProductId("stage_daily_mean")),
        _window(),
        config,
    )

    assert len(calls) == 1
    assert calls[0][0].endswith("?mode=ro")
    assert len(result.value) == 2
    assert len(result.issues) == 2


def test_fetch_year_selection_is_not_clipped_to_fetch_window(
    hydat_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _point_fetch_at(monkeypatch, hydat_db)

    result = fetch(
        ("02GA010",),
        (ProductId("discharge_daily_mean"),),
        _renderings(ProductId("discharge_daily_mean")),
        _window(datetime(2010, 1, 2), datetime(2010, 1, 2)),
        config,
    )

    rows = cast(list[dict[str, object]], json.loads(result.value[0].content.decode("utf-8")))
    assert isinstance(rows, list)
    assert [(row["YEAR"], row["MONTH"]) for row in rows] == [
        (2010, 1),
        (2010, 12),
    ]


def test_fetch_absent_station_is_an_issue_and_other_stations_survive(
    hydat_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _point_fetch_at(monkeypatch, hydat_db)

    result = fetch(
        ("ABSENT", "02GA010"),
        (ProductId("discharge_daily_mean"),),
        _renderings(ProductId("discharge_daily_mean")),
        _window(),
        config,
    )

    assert [payload.station_products for payload in result.value] == [(("02GA010", ProductId("discharge_daily_mean")),)]
    assert [issue.code for issue in result.issues] == ["missing_data"]
    assert result.issues[0].details == {
        "station_id": "ABSENT",
        "product_id": "discharge_daily_mean",
        "table_name": "DLY_FLOWS",
        "start_year": "2010",
        "end_year": "2010",
    }


def test_fetch_all_absent_stations_return_empty_payloads_with_issues(
    hydat_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _point_fetch_at(monkeypatch, hydat_db)

    result = fetch(
        ("ABSENT-1", "ABSENT-2"),
        (ProductId("discharge_daily_mean"),),
        _renderings(ProductId("discharge_daily_mean")),
        _window(),
        config,
    )

    assert result.value == ()
    assert [issue.code for issue in result.issues] == [
        "missing_data",
        "missing_data",
    ]


def test_fetch_missing_hydat_returns_error_issue_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _point_fetch_at(monkeypatch, None)

    result = fetch(
        ("02GA010",),
        (ProductId("discharge_daily_mean"),),
        _renderings(ProductId("discharge_daily_mean")),
        _window(),
        config,
    )

    assert result.value == ()
    assert [issue.code for issue in result.issues] == ["hydat_not_available"]
    assert result.issues[0].severity == "error"
    assert result.issues[0].details == {"cache_dir": str(Path("/unused/cache"))}


def test_fetch_unreadable_hydat_returns_distinct_error_issue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unreadable = tmp_path / "Hydat.sqlite3"
    unreadable.write_text("not a SQLite database", encoding="utf-8")
    _point_fetch_at(monkeypatch, unreadable)

    result = fetch(
        ("02GA010",),
        (ProductId("discharge_daily_mean"),),
        _renderings(ProductId("discharge_daily_mean")),
        _window(),
        config,
    )

    assert result.value == ()
    assert [issue.code for issue in result.issues] == ["source_request_failed"]
    assert result.issues[0].severity == "error"
    assert result.issues[0].details == {
        "path": str(unreadable),
        "exception_type": "DatabaseError",
    }


def test_fetch_malformed_hydat_table_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sqlite_path = tmp_path / "Hydat.sqlite3"
    connection = sqlite3.connect(sqlite_path)
    connection.execute("CREATE TABLE OTHER_TABLE (STATION_NUMBER TEXT)")
    connection.close()
    _point_fetch_at(monkeypatch, sqlite_path)

    with pytest.raises(FatalContractError, match="DLY_FLOWS.*does not exist"):
        fetch(
            ("02GA010",),
            (ProductId("discharge_daily_mean"),),
            _renderings(ProductId("discharge_daily_mean")),
            _window(),
            config,
        )


def test_fetch_missing_hydat_day_columns_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sqlite_path = tmp_path / "Hydat.sqlite3"
    connection = sqlite3.connect(sqlite_path)
    connection.execute(
        "CREATE TABLE DLY_FLOWS ("
        "STATION_NUMBER TEXT, YEAR INTEGER, MONTH INTEGER, NO_DAYS INTEGER, "
        "FLOW1 REAL, FLOW_SYMBOL1 TEXT)"
    )
    connection.close()
    _point_fetch_at(monkeypatch, sqlite_path)

    with pytest.raises(FatalContractError, match="lacks required columns"):
        fetch(
            ("02GA010",),
            (ProductId("discharge_daily_mean"),),
            _renderings(ProductId("discharge_daily_mean")),
            _window(),
            config,
        )


def test_ca_eccc_fetch_uses_first_and_last_engine_rendered_year_tokens(
    hydat_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _point_fetch_at(monkeypatch, hydat_db)
    window = _window(
        datetime(2010, 1, 2, 12, 34, 56, 123456),
        datetime(2010, 12, 31, 23, 59, 59, 999999),
    )
    calls: list[tuple[str, str]] = []
    real_query = fetch_module._query_station_product

    def recording_query(*args: Any) -> tuple[list[dict[str, object]], SourceQuery]:
        calls.append((cast(str, args[-2]), cast(str, args[-1])))
        return real_query(*args)

    monkeypatch.setattr(fetch_module, "_query_station_product", recording_query)

    result = fetch(
        ("02GA010",),
        (ProductId("discharge_daily_mean"),),
        MappingProxyType(
            {
                ProductId("discharge_daily_mean"): (
                    RenderedWindow("2009", None),
                    RenderedWindow("2010", None),
                    RenderedWindow("2011", None),
                )
            }
        ),
        window,
        config,
    )

    rows = json.loads(result.value[0].content.decode("utf-8"))
    assert [(row["YEAR"], row["MONTH"]) for row in rows] == [(2010, 1), (2010, 12)]
    assert calls == [("2009", "2011")]
    assert result.value[0].fetch_window is window
    assert result.issues == ()


def test_ca_eccc_fetch_selects_renderings_by_product_id(
    hydat_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _point_fetch_at(monkeypatch, hydat_db)
    calls: list[tuple[str, str, str]] = []

    def recording_query(
        connection: sqlite3.Connection,
        coordinates: object,
        station_id: str,
        start_year: str,
        end_year: str,
    ) -> tuple[list[dict[str, object]], SourceQuery]:
        calls.append((cast(Any, coordinates).table_name, start_year, end_year))
        query = SourceQuery("SELECT test", (station_id, start_year, end_year))
        return [{"STATION_NUMBER": station_id, "YEAR": 2010, "MONTH": 1, "NO_DAYS": 1}], query

    monkeypatch.setattr(fetch_module, "_query_station_product", recording_query)
    discharge = ProductId("discharge_daily_mean")
    stage = ProductId("stage_daily_mean")
    renderings = MappingProxyType(
        {
            discharge: (RenderedWindow("2008", None), RenderedWindow("2009", None)),
            stage: (RenderedWindow("2011", None), RenderedWindow("2012", None)),
        }
    )

    result = fetch(("02GA010",), (discharge, stage), renderings, _window(), config)

    assert calls == [("DLY_FLOWS", "2008", "2009"), ("DLY_LEVELS", "2011", "2012")]
    assert len(result.value) == 2
    assert result.issues == ()


def test_fetch_never_calls_hydat_acquisition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _point_fetch_at(monkeypatch, None)

    def unexpected_acquisition(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("fetch must not acquire or refresh HYDAT")

    monkeypatch.setattr(HydatClient, "ensure_database", unexpected_acquisition)
    monkeypatch.setattr(HydatClient, "refresh_cache", unexpected_acquisition)

    result = fetch(
        ("02GA010",),
        (ProductId("discharge_daily_mean"),),
        _renderings(ProductId("discharge_daily_mean")),
        _window(),
        config,
    )

    assert result.value == ()
    assert [issue.code for issue in result.issues] == ["hydat_not_available"]


def _is_short_bounded_range(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "range":
        return False
    literal_args: list[int] = []
    for argument in node.args:
        if not isinstance(argument, ast.Constant) or type(argument.value) is not int:
            return False
        literal_args.append(argument.value)
    return 1 <= len(literal_args) <= 3 and 0 < len(range(*literal_args)) <= 10


def test_fetch_source_uses_no_http_decoder_or_retry_capabilities() -> None:
    module_path = fetch_module.__file__
    assert module_path is not None
    source = Path(module_path).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules: set[str] = set()
    imported_symbols: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".", 1)[0] for alias in node.names)
            imported_symbols.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                imported_modules.add(node.module.split(".", 1)[0])
            imported_symbols.update(alias.asname or alias.name for alias in node.names)

    assert imported_modules.isdisjoint({"httpx", "requests", "urllib"})
    assert imported_symbols.isdisjoint({"HttpClient", "decode_json", "decode_csv", "httpx", "requests", "urllib"})

    retry_loops = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.While) or (isinstance(node, ast.For) and _is_short_bounded_range(node.iter))
    ]
    assert retry_loops == []
