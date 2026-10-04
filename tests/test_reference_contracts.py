"""Generated reference coverage for returned source-series contracts."""

import html
import re
import runpy
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

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


@pytest.fixture(scope="session")
def documentation_workspace():
    checks = ROOT / ".worktrees" / "documentation-checks"
    checks.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="reference-", dir=checks) as temporary:
        yield Path(temporary)


@pytest.fixture(scope="module")
def documentation_site(tmp_path_factory, documentation_workspace):
    from mkdocs.commands.build import build
    from mkdocs.config import load_config

    # One strict build exercises the configured handler and snippet inclusion for
    # all field/state contracts, rather than testing the directive text alone.
    site = tmp_path_factory.mktemp("reference-site")
    docs = documentation_workspace / "docs"
    shutil.copytree(
        ROOT / "docs",
        docs,
        ignore=lambda directory, names: {
            name
            for name in names
            if name == "__pycache__"
            or Path(directory) / name in (ROOT / "docs/index.md", ROOT / "docs/assets/stations_map.html")
        },
    )
    outputs = [ROOT / "docs/index.md", ROOT / "docs/assets/stations_map.html"]
    before = {path: path.read_bytes() if path.exists() else None for path in outputs}
    config = load_config(str(ROOT / "mkdocs.yml"), strict=True, site_dir=str(site), docs_dir=str(docs))
    hook = config.hooks["docs/hooks.py"]
    with pytest.MonkeyPatch.context() as patch:
        patch.chdir(ROOT)
        patch.setattr(hook, "INDEX_MD_PATH", docs / "index.md")
        patch.setattr(hook, "STATIONS_MAP_PATH", docs / "assets/stations_map.html")
        generator = runpy.run_path(str(ROOT / "docs/scripts/generate_station_map.py"))
        generator["build_map"](hook.STATIONS_MAP_PATH)
        try:
            build(config)
        finally:
            assert {path: path.read_bytes() if path.exists() else None for path in outputs} == before
    return site


@pytest.fixture(scope="module")
def reference(documentation_site):
    return (documentation_site / "reference/index.html").read_text()


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


def test_homepage_preserves_approved_agent_prompt(documentation_site):
    vision = (ROOT / "planning/visions/2026-10-04-agent-onboarding-prompt.md").read_text()
    approved = vision.split("```text\n", 1)[1].split("```", 1)[0]
    readme = (ROOT / "README.md").read_text()
    assert readme.index("## Install") < readme.index("## Use with a coding agent") < readme.index("## Quick start")
    assert readme.split("```text\n", 1)[1].split("```", 1)[0] == approved

    homepage = (documentation_site / "index.html").read_text()
    disclosure = re.search(r'<details id="agent-prompt">(.*?)</details>', homepage, re.DOTALL)
    assert disclosure is not None
    code = re.search(r"<code[^>]*>(.*?)</code>", disclosure[1], re.DOTALL)
    assert code is not None
    assert html.unescape(re.sub("<[^>]+>", "", code[1])) == approved
    assert '<script src="javascripts/extra.js"></script>' in homepage


@pytest.mark.parametrize("page", ["index.html", "development-conventions/index.html"])
def test_page_copy_embeds_raw_markdown_without_double_escaping(documentation_site, page):
    rendered = (documentation_site / page).read_text()
    raw = re.search(r'<textarea[^>]*id="__raw_page_markdown__"[^>]*>(.*?)</textarea>', rendered, re.DOTALL)
    assert raw is not None
    markdown = html.unescape(raw[1])
    assert "uv " in markdown
    assert "```" in markdown
    assert "Copy page text" not in markdown
    if page == "index.html":
        assert '<details id="agent-prompt">' in markdown
        assert "&lt;details" not in markdown
        assert "## Install" in markdown
