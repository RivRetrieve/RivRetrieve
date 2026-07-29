import ast
import inspect
from dataclasses import fields
from datetime import datetime

import polars as pl
import polars.testing as pl_testing

import rivretrieve
import rivretrieve._internal
import rivretrieve._internal.assembly as assembly_module
from rivretrieve._internal.assembly import _AssemblyResult, assemble
from rivretrieve._internal.engine import CanonicalRowsSchema
from rivretrieve._internal.issues import Issue
from rivretrieve._internal.observations import ObservationProvenance, RawPayload
from rivretrieve._internal.primitives import ProviderId


def test_assemble_packages_populated_inputs_unchanged() -> None:
    rows = pl.DataFrame(
        {
            "time": [datetime(2026, 1, 2, 23, 30), datetime(2026, 1, 1, 0, 0)],
            "time_zone": ["+09:00", "unknown"],
            "station_id": ["station-b", "station-a"],
            "product_id": ["flow", "stage"],
            "value": [100.0, -2.5],
        },
        schema=CanonicalRowsSchema.polars_schema,
    )
    expected_rows = pl.DataFrame(
        {
            "time": [datetime(2026, 1, 2, 23, 30), datetime(2026, 1, 1, 0, 0)],
            "time_zone": ["+09:00", "unknown"],
            "station_id": ["station-b", "station-a"],
            "product_id": ["flow", "stage"],
            "value": [100.0, -2.5],
        },
        schema=CanonicalRowsSchema.polars_schema,
    )
    provenance = ObservationProvenance(
        source="live",
        provider_id=ProviderId("provider-a"),
        request={"stations": ["station-b", "station-a"]},
        endpoints=("https://example.invalid/observations",),
        metadata="source metadata",
    )
    first_issue = Issue(
        severity="error",
        code="station_missing",
        message="Station B returned no rows",
    )
    second_issue = Issue(
        severity="info",
        code="unit_converted",
        message="Source unit was converted",
    )
    issues = (first_issue, second_issue)
    raw = RawPayload(
        provider_id=ProviderId("provider-a"),
        content_type="application/octet-stream",
        content=b"\x00raw-provider-bytes\xff",
        metadata="raw metadata",
    )

    result = assemble(rows, provenance, issues, raw)

    assert result.canonical_rows is rows
    pl_testing.assert_frame_equal(result.canonical_rows, rows)
    assert result.provenance is provenance
    assert result.issues is issues
    assert result.issues == (first_issue, second_issue)
    assert result.raw is raw
    assert result.raw.content is raw.content
    pl_testing.assert_frame_equal(rows, expected_rows)


def test_assemble_packages_empty_inputs_unchanged() -> None:
    rows = pl.DataFrame(schema=CanonicalRowsSchema.polars_schema)
    provenance = ObservationProvenance(
        source="live",
        provider_id=ProviderId("provider-empty"),
        request={"stations": ["missing-station"]},
    )
    issue = Issue(
        severity="warning",
        code="empty_window",
        message="No observations were returned",
    )
    issues = (issue,)
    raw = RawPayload(
        provider_id=ProviderId("provider-empty"),
        content_type="text/plain",
        content="",
        metadata="empty response",
    )

    result = assemble(rows, provenance, issues, raw)

    assert result.canonical_rows is rows
    pl_testing.assert_frame_equal(result.canonical_rows, rows)
    assert result.canonical_rows.schema == CanonicalRowsSchema.polars_schema
    assert result.canonical_rows.height == 0
    assert result.provenance is provenance
    assert result.issues is issues
    assert result.issues == (issue,)
    assert result.raw is raw
    assert result.raw.content == ""


def test_assemble_return_construction_is_private_and_exactly_four_input_packaging() -> None:
    result = assemble(
        pl.DataFrame(schema=CanonicalRowsSchema.polars_schema),
        ObservationProvenance(source="live", provider_id=ProviderId("provider-a")),
        (),
        RawPayload(provider_id=ProviderId("provider-a")),
    )

    assert type(result) is _AssemblyResult
    assert _AssemblyResult.__name__.startswith("_")
    assert tuple(field.name for field in fields(_AssemblyResult)) == (
        "canonical_rows",
        "provenance",
        "issues",
        "raw",
    )
    assert "_AssemblyResult" not in rivretrieve.__dict__
    assert "_AssemblyResult" not in rivretrieve._internal.__dict__


def test_assemble_body_is_constructor_only_and_has_no_conversion_or_provider_dependency() -> None:
    module_tree = ast.parse(inspect.getsource(assembly_module))
    function = next(node for node in module_tree.body if isinstance(node, ast.FunctionDef) and node.name == "assemble")

    assert len(function.body) == 1
    statement = function.body[0]
    assert isinstance(statement, ast.Return)
    call = statement.value
    assert isinstance(call, ast.Call)
    assert isinstance(call.func, ast.Name)
    assert call.func.id == "_AssemblyResult"
    assert call.args == []
    assert tuple(keyword.arg for keyword in call.keywords) == (
        "canonical_rows",
        "provenance",
        "issues",
        "raw",
    )
    for keyword in call.keywords:
        assert isinstance(keyword.value, ast.Name)
        assert keyword.value.id == keyword.arg

    imports = [node for node in module_tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    imported_modules = tuple(
        alias.name for node in imports for alias in node.names if isinstance(node, ast.Import)
    ) + tuple(node.module or "" for node in imports if isinstance(node, ast.ImportFrom))
    imported_names = tuple(alias.name for node in imports if isinstance(node, ast.ImportFrom) for alias in node.names)

    assert not any(
        ".conversion" in module or module.endswith(".convert") or ".providers." in module for module in imported_modules
    )
    assert not {
        "ObservationResult",
        "apply_on_issue",
        "AnnotationSchema",
        "AnnotationTable",
        "CanonicalRowsSchema",
        "validate_catalogue",
    }.intersection(imported_names)
    assert not any(
        forbidden_fragment in imported.lower()
        for imported in (*imported_modules, *imported_names)
        for forbidden_fragment in ("serializ", "validator")
    )
    assert not any(imported.startswith("Annotation") or imported.endswith("Schema") for imported in imported_names)
