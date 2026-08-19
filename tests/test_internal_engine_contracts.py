from __future__ import annotations

import ast
import inspect
import subprocess
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve._internal.driver as driver_module
from rivretrieve._internal import engine
from rivretrieve._internal.catalogues.schemas import CatalogueSchema, validate_catalogue
from rivretrieve._internal.engine import (
    CanonicalRowsSchema,
    FetchWindow,
    ObservationRequest,
    Payload,
    RequestedWindow,
    Rows,
    RowsSchema,
    SourceCallOrigin,
    SourceCoordinates,
    SourceQuery,
    UnknownOriginFact,
    WindowEndpoint,
    WithIssues,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId


def test_window_endpoint_exposes_rendering_fields_without_arithmetic() -> None:
    endpoint = WindowEndpoint.from_datetime(datetime(2020, 7, 31, 23, 59, 59, 999999))

    assert (
        endpoint.year,
        endpoint.month,
        endpoint.day,
        endpoint.hour,
        endpoint.minute,
        endpoint.second,
        endpoint.microsecond,
    ) == (2020, 7, 31, 23, 59, 59, 999999)
    assert endpoint.date == "2020-07-31"
    assert endpoint.isoformat() == "2020-07-31T23:59:59.999999"
    with pytest.raises(TypeError):
        endpoint + timedelta(days=1)  # type: ignore[unsupported-operator]
    with pytest.raises(TypeError):
        endpoint - timedelta(days=1)  # type: ignore[unsupported-operator]
    with pytest.raises(FrozenInstanceError):
        endpoint.year = 2021


def test_requested_and_fetch_windows_remain_nominally_distinct_and_immutable() -> None:
    start = WindowEndpoint.from_datetime(datetime(2020, 7, 31))
    end = WindowEndpoint.from_datetime(datetime(2020, 7, 31, 23, 59, 59, 999999))
    requested = RequestedWindow(start=start, end=end)
    fetch = _make_fetch_window(start, end)

    assert requested.start is start
    assert requested.end is end
    assert fetch.start is start
    assert fetch.end is end
    assert type(requested) is not type(fetch)
    assert not isinstance(requested, FetchWindow)
    assert not isinstance(fetch, RequestedWindow)
    start_attribute = "start"
    with pytest.raises(FrozenInstanceError):
        setattr(requested, start_attribute, start)
    with pytest.raises(FrozenInstanceError):
        setattr(fetch, start_attribute, start)


def test_direct_fetch_window_construction_raises_for_provider_code() -> None:
    start = WindowEndpoint.from_datetime(datetime(2020, 7, 31))
    end = WindowEndpoint.from_datetime(datetime(2020, 7, 31, 23, 59, 59, 999999))

    with pytest.raises(
        TypeError,
        match="^FetchWindow is engine-owned and cannot be constructed by providers$",
    ):
        FetchWindow(start=start, end=end)


def test_requested_to_fetch_construction_is_driver_owned_with_injectable_transport() -> None:
    assert not hasattr(driver_module, "identity" + "_window")
    assert not hasattr(driver_module, "Window" + "Padder")
    signature = inspect.signature(driver_module.drive)
    assert tuple(signature.parameters) == (
        "request",
        "provider",
        "provenance",
        "raw",
        "transport",
    )
    assert signature.parameters["request"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert signature.parameters["provider"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert signature.parameters["provenance"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["raw"].kind is inspect.Parameter.KEYWORD_ONLY

    source_root = Path(__file__).parents[1] / "src" / "rivretrieve"
    requested_to_fetch: list[str] = []
    for source_path in source_root.rglob("*.py"):
        tree = ast.parse(source_path.read_text(), filename=str(source_path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            parameter_annotations = [
                argument.annotation
                for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
                if argument.annotation is not None
            ]
            takes_requested = any("RequestedWindow" in ast.unparse(annotation) for annotation in parameter_annotations)
            returns_fetch = node.returns is not None and "FetchWindow" in ast.unparse(node.returns)
            if takes_requested and returns_fetch:
                requested_to_fetch.append(f"{source_path.relative_to(source_root)}:{node.name}")

    assert requested_to_fetch == []


def test_engine_observation_request_preserves_requested_window_and_ids() -> None:
    provider_id = ProviderId("provider")
    stations = ("station-1", "station-2")
    products = (ProductId("flow"), ProductId("level"))
    window = RequestedWindow(
        WindowEndpoint.from_datetime(datetime(2020, 7, 31)),
        WindowEndpoint.from_datetime(datetime(2020, 7, 31, 23, 59, 59, 999999)),
    )
    request = ObservationRequest(
        provider_id=provider_id,
        stations=stations,
        products=products,
        window=window,
    )

    assert request.provider_id == provider_id
    assert request.stations == stations
    assert request.products == products
    assert request.window is window
    window_attribute = "window"
    with pytest.raises(FrozenInstanceError):
        setattr(request, window_attribute, window)


def test_source_coordinates_are_opaque_and_immutable() -> None:
    sentinel = object()
    coordinates = SourceCoordinates(sentinel)

    assert coordinates.value is sentinel
    value_attribute = "value"
    with pytest.raises(FrozenInstanceError):
        setattr(coordinates, value_attribute, sentinel)


def test_window_declarations_and_renderings_are_immutable_and_non_arithmetic() -> None:
    assert tuple((member.name, member.value) for member in engine.WindowRenderingVocabulary) == (
        ("ISO_INSTANT", "iso-instant"),
        ("DATE", "date"),
        ("YEAR", "year"),
        ("YEAR_MONTH", "year-month"),
        ("NONE", "none"),
    )
    assert tuple((member.name, member.value) for member in engine.StopConvention) == (
        ("INCLUSIVE", "inclusive"),
        ("EXCLUSIVE", "exclusive"),
    )
    declaration = engine.WindowDeclaration(
        engine.WindowGranularity("date"),
        engine.WindowRenderingVocabulary.DATE,
        engine.StopConvention.INCLUSIVE,
    )
    original = {ProductId("flow"): declaration}
    declarations = engine.ProductWindowDeclarations(original)
    rendered = engine.RenderedWindow("2020-01-01", "2020-01-02")
    original[ProductId("level")] = declaration

    assert tuple(field.name for field in fields(declaration)) == (
        "granularity",
        "rendering",
        "stop_convention",
        "size",
    )
    assert dict(declarations.products) == {ProductId("flow"): declaration}
    assert isinstance(rendered.start, str)
    assert isinstance(rendered.stop, str)
    with pytest.raises(FrozenInstanceError):
        declaration.size = 2
    with pytest.raises(FrozenInstanceError):
        declarations.products = {}
    with pytest.raises(FrozenInstanceError):
        rendered.start = "2021-01-01"
    with pytest.raises(TypeError):
        rendered.start + timedelta(days=1)  # type: ignore[operator]
    with pytest.raises(TypeError):
        timedelta(days=1) + rendered.start  # type: ignore[operator]
    with pytest.raises(TypeError):
        rendered.start - timedelta(days=1)  # type: ignore[operator]


def test_runtime_provider_window_helpers_do_not_perform_decomposition_arithmetic() -> None:
    providers = Path(__file__).parents[1] / "src" / "rivretrieve" / "_internal" / "providers"
    violations: list[str] = []
    for path in providers.glob("*/*.py"):
        if path.name == "generate_catalogue.py":
            continue
        module_source = path.read_text()
        tree = ast.parse(module_source)
        for function in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
            source = ast.get_source_segment(module_source, function) or ""
            if "window" not in function.name.lower() and "FetchWindow" not in source:
                continue
            for node in ast.walk(function):
                if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
                    violations.append(f"{path}:{function.name}:binary arithmetic")
                if isinstance(node, ast.Call):
                    called = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                    if called in {"timedelta", "monthrange", "relativedelta"}:
                        violations.append(f"{path}:{function.name}:{called}")
                    if called == "replace" and any(
                        keyword.arg in {"year", "month", "day", "hour", "minute", "second"} for keyword in node.keywords
                    ):
                        violations.append(f"{path}:{function.name}:boundary replace")
                if isinstance(node, (ast.For, ast.While)):
                    loop_source = (ast.get_source_segment(module_source, node) or "").lower()
                    if any(name in loop_source for name in ("cursor", "window_start", "window_end", "next_date")):
                        violations.append(f"{path}:{function.name}:window cursor loop")
    assert violations == []


def test_obsolete_window_symbols_are_absent_from_tracked_source() -> None:
    obsolete = {"identity_window", "WindowPadder", "_window_parameter", "_endpoint_year", "_query_years"}
    tracked = subprocess.run(
        ["git", "ls-files", "--", ":(glob)src/**/*.py"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    occurrences: list[str] = []
    for source_path in tracked:
        tree = ast.parse(Path(source_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: tuple[str | None, ...] = ()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names = (node.name,)
            elif isinstance(node, ast.alias):
                names = (node.name, node.asname)
            elif isinstance(node, ast.arg):
                names = (node.arg,)
            elif isinstance(node, ast.Name):
                names = (node.id,)
            for name in names:
                if name in obsolete:
                    occurrences.append(f"{source_path}:{getattr(node, 'lineno', 0)}:{name}")

    assert occurrences == []


def test_payload_accepts_bytes_and_preserves_complete_source_call() -> None:
    coordinates = SourceCoordinates(object())
    station_products = (
        ("station-1", ProductId("flow")),
        ("station-2", ProductId("level")),
    )
    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2020, 7, 31)),
        WindowEndpoint.from_datetime(datetime(2020, 7, 31, 23, 59, 59, 999999)),
    )
    parameters = {"station": "station-1"}
    query = SourceQuery("SELECT value FROM observations WHERE station = ?", ("station-1",))
    origin = SourceCallOrigin(
        url="https://source.example/data",
        request_parameters=parameters,
        status_code=200,
        retrieved_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
        content_type="application/octet-stream",
        source_path=UnknownOriginFact(),
        query=query,
    )
    content = b"payload"
    payload = Payload(
        source_coordinates=coordinates,
        station_products=station_products,
        fetch_window=window,
        content=content,
        origin=origin,
    )

    assert payload.source_coordinates is coordinates
    assert payload.station_products == station_products
    assert payload.fetch_window is window
    assert payload.content is content
    assert payload.origin is origin
    assert tuple(field.name for field in fields(SourceCallOrigin)) == (
        "url",
        "request_parameters",
        "status_code",
        "retrieved_at",
        "content_type",
        "source_path",
        "query",
    )
    assert "headers" not in {field.name for field in fields(SourceCallOrigin)}
    assert origin.request_parameters == {"station": "station-1"}
    parameters["station"] = "mutated"
    assert origin.request_parameters == {"station": "station-1"}
    with pytest.raises(TypeError):
        origin.request_parameters["station"] = "mutated"  # type: ignore[index]
    content_attribute = "content"
    with pytest.raises(FrozenInstanceError):
        setattr(payload, content_attribute, content)


@pytest.mark.parametrize(
    "content",
    ["payload", object(), bytearray(b"payload"), memoryview(b"payload"), [], {}, ()],
)
def test_payload_rejects_non_byte_content(content: object) -> None:
    with pytest.raises(TypeError, match="payload content must be bytes"):
        Payload(
            SourceCoordinates(object()),
            (("station", ProductId("flow")),),
            _make_fetch_window(
                WindowEndpoint.from_datetime(datetime(2020, 1, 1)),
                WindowEndpoint.from_datetime(datetime(2020, 1, 2)),
            ),
            content,  # type: ignore[arg-type]
            SourceCallOrigin(
                UnknownOriginFact(),
                UnknownOriginFact(),
                UnknownOriginFact(),
                UnknownOriginFact(),
                UnknownOriginFact(),
                UnknownOriginFact(),
                UnknownOriginFact(),
            ),
        )


def test_source_call_origin_distinguishes_known_empty_parameters_and_validates_facts() -> None:
    unknown = UnknownOriginFact()
    known = SourceCallOrigin(
        "https://source.example/data",
        {},
        200,
        datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
        "application/json",
        unknown,
        SourceQuery("SELECT 1", ()),
    )
    absent = SourceCallOrigin(unknown, unknown, unknown, unknown, unknown, unknown, unknown)

    assert known.request_parameters == {}
    assert not isinstance(known.request_parameters, UnknownOriginFact)
    assert isinstance(absent.request_parameters, UnknownOriginFact)
    assert SourceQuery("SELECT ?", (b"value",)).parameters == (b"value",)
    with pytest.raises(TypeError):
        SourceQuery("SELECT ?", ["value"])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        SourceCallOrigin("url", {}, 200, datetime(2026, 7, 29), "type", "path", unknown)
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        SourceCallOrigin(
            "url", {}, 200, datetime(2026, 7, 29, tzinfo=datetime.now().astimezone().tzinfo), "type", "path", unknown
        )


def test_with_issues_preserves_value_and_concatenates_existing_issues() -> None:
    sentinel = object()
    first = Issue(severity="warning", code="first", message="First issue")
    second = Issue(severity="info", code="second", message="Second issue")
    earlier = WithIssues(value=sentinel, issues=(first,))
    accumulated = WithIssues(value=earlier.value, issues=earlier.issues + (second,))

    assert accumulated.value is sentinel
    assert accumulated.issues == (first, second)
    assert earlier.value is sentinel
    assert earlier.issues == (first,)
    assert WithIssues(value=sentinel).issues == ()
    value_attribute = "value"
    issues_attribute = "issues"
    with pytest.raises(FrozenInstanceError):
        setattr(accumulated, value_attribute, sentinel)
    with pytest.raises(FrozenInstanceError):
        setattr(accumulated, issues_attribute, ())


def test_with_issues_does_not_short_circuit_for_empty_rows_or_error_severity() -> None:
    rows: Rows = pl.DataFrame(schema=RowsSchema.polars_schema)
    first = Issue(severity="error", code="empty", message="No rows")
    second = Issue(severity="info", code="checked", message="Rows checked")
    initial = WithIssues(value=rows, issues=(first,))
    accumulated = WithIssues(value=initial.value, issues=initial.issues + (second,))

    pl_testing.assert_frame_equal(initial.value, rows)
    assert initial.issues == (first,)
    pl_testing.assert_frame_equal(accumulated.value, rows)
    assert accumulated.issues == (first, second)


def test_rows_schema_declares_exact_native_row_shape() -> None:
    assert RowsSchema.name == "Rows"
    assert tuple(column.name for column in RowsSchema.columns) == (
        "station_id",
        "product_id",
        "time",
        "value",
        "time_zone",
    )
    assert RowsSchema.polars_schema == pl.Schema(
        {
            "station_id": pl.Utf8,
            "product_id": pl.Utf8,
            "time": pl.Datetime(),
            "value": pl.Float64,
            "time_zone": pl.Utf8,
        }
    )
    assert tuple(column.name for column in RowsSchema.columns if column.nullable) == ("value",)
    frame = pl.DataFrame(
        {
            "station_id": ["station"],
            "product_id": ["flow"],
            "time": [datetime(2026, 1, 1)],
            "value": [1.0],
            "time_zone": ["unknown"],
        },
        schema=RowsSchema.polars_schema,
    )

    assert validate_catalogue(frame, RowsSchema, on_issue="raise") == []


def test_canonical_rows_schema_declares_exact_canonical_shape() -> None:
    assert CanonicalRowsSchema.name == "CanonicalRows"
    assert tuple(column.name for column in CanonicalRowsSchema.columns) == (
        "time",
        "time_zone",
        "station_id",
        "product_id",
        "value",
    )
    assert CanonicalRowsSchema.polars_schema == pl.Schema(
        {
            "time": pl.Datetime(),
            "time_zone": pl.Utf8,
            "station_id": pl.Utf8,
            "product_id": pl.Utf8,
            "value": pl.Float64,
        }
    )
    assert tuple(column.name for column in CanonicalRowsSchema.columns if column.nullable) == ("value",)
    frame = pl.DataFrame(
        {
            "time": [datetime(2026, 1, 1)],
            "time_zone": ["Europe/Oslo"],
            "station_id": ["station"],
            "product_id": ["flow"],
            "value": [1.0],
        },
        schema=CanonicalRowsSchema.polars_schema,
    )

    assert validate_catalogue(frame, CanonicalRowsSchema, on_issue="raise") == []


@pytest.mark.parametrize("schema", [RowsSchema, CanonicalRowsSchema], ids=lambda schema: schema.name)
def test_row_schemas_reject_zoned_time_wrong_zone_dtype_and_null_zone(schema: CatalogueSchema) -> None:
    valid = _valid_frame(schema)
    zoned_time = valid.with_columns(pl.col("time").dt.replace_time_zone("UTC"))
    wrong_zone_dtype = valid.with_columns(pl.lit(1, dtype=pl.Int64).alias("time_zone"))
    null_zone = valid.with_columns(pl.lit(None, dtype=pl.Utf8).alias("time_zone"))

    with pytest.raises(FatalContractError):
        validate_catalogue(zoned_time, schema, on_issue="raise")
    with pytest.raises(FatalContractError):
        validate_catalogue(wrong_zone_dtype, schema, on_issue="raise")
    with pytest.raises(FatalContractError):
        validate_catalogue(null_zone, schema, on_issue="raise")


def test_fetch_window_is_rejected_where_requested_window_is_required() -> None:
    fixture = Path(__file__).parent / "typecheck" / "nominal_window_misuse.py"
    result = subprocess.run(
        ["uv", "run", "ty", "check", str(fixture)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "invalid-argument-type" in result.stdout
    assert "Expected `RequestedWindow`, found `FetchWindow`" in result.stdout


def _valid_frame(schema: CatalogueSchema) -> pl.DataFrame:
    values = {
        "station_id": ["station"],
        "product_id": ["flow"],
        "time": [datetime(2026, 1, 1)],
        "value": [1.0],
        "time_zone": ["unknown"],
    }
    return pl.DataFrame(
        {column.name: values[column.name] for column in schema.columns},
        schema=schema.polars_schema,
    )
