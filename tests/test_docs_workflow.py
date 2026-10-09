"""Source-only checks for preparing the documentation explorer in CI."""

from pathlib import Path

import yaml


def test_docs_workflow_prepares_explorer_before_strict_mkdocs_build():
    workflow = yaml.load(
        (Path(__file__).parents[1] / ".github/workflows/deploy-docs.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert "web/**" in workflow["on"]["push"]["paths"]
    steps = workflow["jobs"]["build-and-deploy"]["steps"]
    node = next(step for step in steps if step.get("uses", "").startswith("actions/setup-node@"))
    assert node["with"] == {
        "node-version": "22",
        "cache": "npm",
        "cache-dependency-path": "web/station-explorer/package-lock.json",
    }
    dependencies = next(step for step in steps if step.get("run") == "uv sync --all-extras --dev")
    npm = next(step for step in steps if step.get("run") == "npm --prefix web/station-explorer ci")
    catalogue = next(
        step for step in steps if step.get("run") == "uv run python docs/scripts/generate_station_catalogue.py"
    )
    frontend = next(step for step in steps if "npm --prefix web/station-explorer run build" in step.get("run", ""))
    assert frontend["env"] == {"VITE_CARTO_BASEMAP_API_KEY": "${{ secrets.CARTO_BASEMAP_API_KEY }}"}
    commands = frontend["run"]
    assert 'if [ -z "$VITE_CARTO_BASEMAP_API_KEY" ]; then' in commands
    assert "::error::CARTO_BASEMAP_API_KEY is required" in commands
    assert commands.index("exit 1") < commands.index("npm --prefix web/station-explorer run build")
    docs = next(step for step in steps if step.get("run") == "uv run mkdocs build --strict")
    deploy = next(step for step in steps if step.get("uses") == "peaceiris/actions-gh-pages@v4")
    assert steps.index(node) < steps.index(npm) < steps.index(frontend)
    assert steps.index(dependencies) < steps.index(catalogue) < steps.index(frontend)
    assert steps.index(frontend) < steps.index(docs) < steps.index(deploy)
    assert deploy["if"] == "github.ref == 'refs/heads/main'"
    assert deploy["with"]["external_repository"] == "RivRetrieve/RivRetrieve.github.io"
