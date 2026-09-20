"""Generated reference coverage for returned source-series contracts."""

import runpy
from pathlib import Path

import pytest

from rivretrieve._internal import source_series

ROOT = Path(__file__).resolve().parents[1]
MODELS = (
    "EvidenceFact",
    "SourceUnitCodeDefinition",
    "PhysicalFacts",
    "Admission",
    "SourceIdentity",
    "SourceSeries",
    "PhysicalPredicate",
    "SeriesScope",
    "SeriesWindow",
    "CatalogueSeriesClaim",
    "InventorySnapshot",
    "RequestedSelector",
    "RetrievalOutcome",
)
ENUMS = (
    "EvidenceState",
    "ClippingAxis",
    "RestrictionKind",
    "ScopeState",
    "InventoryCompleteness",
    "OutcomeStatus",
)


@pytest.fixture(scope="module")
def reference():
    return runpy.run_path(str(ROOT / "scripts/generate_reference.py"))["render_reference"]()


@pytest.mark.parametrize("name", MODELS)
def test_reference_documents_source_series_fields(reference, name):
    section = reference.split(f"### `{name}`\n", 1)[1].split("\n### ", 1)[0]
    for field in getattr(source_series, name).model_fields:
        assert f"| `{field}` |" in section


@pytest.mark.parametrize("name", ENUMS)
def test_reference_documents_source_series_states(reference, name):
    section = reference.split(f"### `{name}`\n", 1)[1].split("\n### ", 1)[0]
    for state in getattr(source_series, name):
        assert f"`{state.value}`" in section


def test_reference_observation_result_fields(reference):
    from rivretrieve._internal.observations import ObservationResult

    section = reference.split("### `ObservationResult`\n", 1)[1].split("\n### ", 1)[0]
    for field in ObservationResult.model_fields:
        assert f"| `{field}` |" in section


def test_reference_all_provider_access_kinds(reference):
    table = reference.split("## Shipped software capabilities", 1)[1].split("### Packaged access coordinates", 1)[0]
    rows = [line for line in table.splitlines() if line.startswith("| `")]
    assert len(rows) == 13
    assert sum("| live |" in row for row in rows) == 10
    assert sum("| bulk store |" in row for row in rows) == 2
    assert sum("| catalogue-only |" in row for row in rows) == 1
