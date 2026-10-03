# Development

Start with an [agreed change](contributing.md). Read the repository's
[project instructions](../AGENTS.md) and the [architecture](architecture.md) before
changing code. Use Python 3.13 or later and [uv](https://docs.astral.sh/uv/).

## Set up and check a change

Run these commands from the source checkout. `uv sync --extra map` installs the
locked project, development tools and optional map dependency. It creates the
local environment; it does not download provider observations.

```sh
uv sync --extra map
uv run pytest --logic-only
uv run ruff format --check
uv run ruff check
uv run ty check src
```

Successful tests report passed counts, formatting reports unchanged files, and
lint and type checks report no errors. Counts vary with the selected revision.
Run affected tests while editing, then the broader checks required by the changed
boundary. The [testing guide](maintenance/testing.md) explains how to choose useful
checks. Source-backed tests use the reviewed private
[evidence workflow](maintenance/evidence.md); missing inputs are not a passing check.

Use temporary cache and store roots for experiments. Do not commit credentials,
private source bodies, generated environments or local cache data.

## Documentation

Follow the [documentation language guidelines](AGENTS.md) and the
[public API docstring rule](../AGENTS.md#public-api-docstrings). Edit public NumPy
docstrings in source; mkdocstrings renders the API reference. Add reference
directives when the supported public surface grows, without exposing private helpers.

The homepage comes from the root README through `docs/hooks.py`. Edit that source,
not the generated `docs/index.md`. Schema and provider tables come from
`scripts/generate_reference.py`; regenerate them only when their underlying facts
change and commit the updated tables.

```sh
uv run python scripts/generate_reference.py --check
uv run pytest --logic-only tests/test_documentation.py tests/test_reference_contracts.py
uv run mkdocs build --strict
```

The first command reports `Reference is current.` when tables match the code and
packaged catalogues. The tests report their results; a successful build writes
`site/` and reports completion. Review the rendered navigation and links as well.
A local build does not deploy the site. Documentation publication remains in
`.github/workflows/deploy-docs.yml` and targets `RivRetrieve/RivRetrieve.github.io`.

## Versions and publishing

`pyproject.toml` holds the package version. `rivretrieve.__version__` reads the
installed distribution metadata, so there is no second version to update.
Use uv to prepare the version and update `uv.lock`:

`uv version 0.1.0` sets the version in the project files. This is a release
operation, not a setup or test command.

For subsequent pre-1.0 releases, use `uv version --bump minor` for breaking changes
or `uv version --bump patch` for compatible improvements and fixes. Review and
commit `pyproject.toml` and `uv.lock` before releasing. GitHub release notes explain
the changes and any adaptation needed for breaking changes.

The `publish-pypi.yml` workflow builds with `uv build` and uploads with
`uv publish --trusted-publishing always`. Each publishing job installs uv and uses
short-lived GitHub OIDC credentials in its `pypi` or `testpypi` environment.
TestPyPI uploads explicitly use `https://test.pypi.org/legacy/`.

Publishing a GitHub release, including a prerelease, uploads to PyPI. Manual
dispatch also uploads packages: its target selector defaults to `pypi` and offers
`testpypi`. The workflow does not bump versions, create tags or generate release
notes. Run `uv build` locally to build without uploading. Release publication and
manual dispatch require a separate decision to upload; do not use them to check a
local build.

## Provider safety guards

A live catalogue refresh may enforce a provider-specific minimum-station guard to reject an
implausibly small response. Calibrate the threshold from that provider's established population and
source behavior. Never copy a numeric threshold from another provider.
