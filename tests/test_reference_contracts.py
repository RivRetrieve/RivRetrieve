"""Generated reference coverage for returned source-series contracts."""

import html
import re
import subprocess
import sys
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
def reference(tmp_path_factory):
    # One strict build exercises the configured handler and snippet inclusion for
    # all field/state contracts, rather than testing the directive text alone.
    site = tmp_path_factory.mktemp("reference-site")
    subprocess.run(
        [sys.executable, "-m", "mkdocs", "build", "--strict", "--site-dir", str(site)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return (site / "reference/index.html").read_text()


def section(reference, name):
    return reference.split(f'id="{name.lower()}"', 1)[1].split("<h3 ", 1)[0]


@pytest.mark.parametrize("name", MODELS)
def test_reference_documents_source_series_fields(reference, name):
    rendered = section(reference, name)
    for field in getattr(source_series, name).model_fields:
        assert f'id="rivretrieve._internal.source_series.{name}.{field}"' in rendered


@pytest.mark.parametrize("name", ENUMS)
def test_reference_documents_source_series_states(reference, name):
    rendered = section(reference, name)
    for state in getattr(source_series, name):
        assert f'id="rivretrieve._internal.source_series.{name}.{state.name}"' in rendered
        assert repr(state.value) in html.unescape(re.sub("<[^>]+>", "", rendered))


def test_reference_observation_result_fields(reference):
    from rivretrieve._internal.observations import ObservationResult

    rendered = section(reference, "ObservationResult")
    for field in ObservationResult.model_fields:
        assert f'id="rivretrieve._internal.observations.ObservationResult.{field}"' in rendered


def test_reference_all_provider_access_kinds(reference):
    table = reference.split('id="shipped-software-capabilities"', 1)[1].split('id="packaged-access-coordinates"', 1)[0]
    rows = re.findall(r"<tr>(.*?)</tr>", table, re.DOTALL)[1:]
    assert len(rows) == 14
    assert sum("<td>live</td>" in row for row in rows) == 11
    assert sum("<td>bulk store</td>" in row for row in rows) == 2
    assert sum("<td>catalogue-only</td>" in row for row in rows) == 1


def test_reference_renders_methods_and_signature_only_properties(reference):
    # Duplicate selected members render duplicate headings, anchors and TOC entries.
    identifiers = re.findall(r'id="(rivretrieve\.[^"]+)"', reference)
    assert len(identifiers) == len(set(identifiers))
    for name in ("to_polars", "to_pandas"):
        assert f'id="rivretrieve._internal.observations.ObservationResult.{name}"' in reference
    assert 'id="rivretrieve._internal.store.reader.StoreStatus.exists"' in reference
    assert 'id="rivretrieve._internal.issues.InvalidObservationRequestError"' in reference
    assert 'id="rivretrieve._internal.source_series.EvidenceFact.check"' not in reference


def test_reference_renders_numpy_sections_examples_and_links(reference):
    rendered = section(reference, "fetch")
    for heading in ("Parameters:", "Returns:", "Raises:", "Examples:"):
        assert heading in rendered
    assert 'class="language-pycon highlight"' in rendered
    assert "&gt;&gt;&gt;" in rendered
    assert 'href="#rivretrieve._internal.issues.MissingCredentialError"' in rendered
    assert "::: rivretrieve.fetch" not in rendered
