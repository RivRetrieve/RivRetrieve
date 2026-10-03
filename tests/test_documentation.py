"""documentation examples : MarkdownPythonBlocks × PublicAPI → ExecutableContracts."""

import ast
import re
import runpy
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr

ROOT = Path(__file__).resolve().parents[1]


def python_blocks(path: Path) -> list[str]:
    return re.findall(r"```python\n(.*?)```", path.read_text(), re.DOTALL)


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_camels_example_selects_documented_gauges_without_network(monkeypatch, capsys):
    def refuse_network(*args, **kwargs):
        raise AssertionError("Offline selection must not retrieve observations")

    monkeypatch.setattr(rr, "fetch", refuse_network)
    block = python_blocks(ROOT / "docs/examples/camels-us.md")[0]
    tree = ast.parse(block)
    fetch_index = next(
        index
        for index, statement in enumerate(tree.body)
        if isinstance(statement, ast.Assign)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and statement.value.func.attr == "fetch"
    )
    scope = {}
    exec(compile(ast.Module(body=tree.body[:fetch_index], type_ignores=[]), "camels-us.md", "exec"), scope)
    expected = pl.DataFrame(
        {
            "provider_id": ["usgs_nwis"] * 3,
            "station_id": ["01013500", "01022500", "01030500"],
            "product_id": ["discharge_daily_mean"] * 3,
        }
    )
    assert_frame_equal(rr.as_frame(scope["selection"]).select(expected.columns), expected)


PAGES = [
    "README.md",
    "docs/README.md",
    "docs/usage.md",
    "docs/architecture.md",
    "docs/reference.md",
    "docs/examples/camels-us.md",
    "docs/station-metadata.md",
    "docs/catalogue-evidence.md",
    "docs/maintenance/evidence.md",
    "docs/catalogue-provenance.md",
    "docs/catalogue-absence.md",
    "docs/design/observation-store-layout.md",
    "docs/development-conventions.md",
    "docs/contributing.md",
    "docs/maintenance/testing.md",
    "CONTEXT.md",
]


def test_documentation_local_links_and_python_syntax():
    pages = [*PAGES, *(str(path.relative_to(ROOT)) for path in (ROOT / "docs/providers").glob("*.md"))]
    for name in pages:
        path = ROOT / name
        text = path.read_text()
        for block in python_blocks(path):
            ast.parse(block)
        for destination in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
            if "://" in destination or destination.startswith("mailto:"):
                continue
            local, _, fragment = destination.partition("#")
            target = (path.parent / local).resolve() if local else path
            assert target.exists(), (name, destination)
            if fragment and target.suffix == ".md":
                content = target.read_text()
                if target == ROOT / "docs/reference.md":
                    content += (ROOT / "docs/_generated/reference-tables.md").read_text()
                headings = re.findall(r"^#{1,6} (.+)$", content, re.MULTILINE)
                anchors = [re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-") for heading in headings]
                assert fragment in anchors, (name, destination, anchors)


def test_generated_reference_is_current():
    namespace = runpy.run_path(str(ROOT / "scripts/generate_reference.py"))
    assert (ROOT / "docs/_generated/reference-tables.md").read_text() == namespace["render_tables"]()


def test_station_map_counts_match_packaged_catalogues():
    text = (ROOT / "docs/map.md").read_text()
    documented = {
        provider: int(count.replace(",", "")) for provider, count in re.findall(r"\| `([^`]+)` \| ([\d,]+) \|", text)
    }
    from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS
    from rivretrieve._internal.providers.registration import load_manifest

    actual = {
        item.provider_id: pl.read_parquet(item.declaration.catalogue / "stations.parquet").height
        for item in load_manifest(BUILTIN_PROVIDER_IDS)
    }
    assert documented == actual
    total = re.search(r"Explore \*\*([\d,]+)\*\*", text)
    assert total is not None
    assert int(total.group(1).replace(",", "")) == sum(actual.values())
