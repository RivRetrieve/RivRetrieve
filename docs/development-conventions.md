# Development conventions

## Docstrings

Public functions and user-facing returned types, methods and attributes follow the
[public API docstring rule](../AGENTS.md#public-api-docstrings) in the root `AGENTS.md`.

For internal functions, use NumPy-style docstrings when the contract is not clear from the
signature. Document the parameters, returns and raised exceptions that need explanation.

## API reference

Edit NumPy docstrings in the source. `uv run mkdocs build --strict` renders them
with mkdocstrings. `docs/reference.md` lists the supported functions, returned
interfaces and exceptions; add directives there when the supported surface grows.
Keep private helpers and validation methods out of the reference.

Factual schema and provider tables are committed in
`docs/_generated/reference-tables.md`. After changing those facts, run
`uv run python scripts/generate_reference.py` and commit the updated tables.
The build checks their freshness before preparing other files. Docstring edits
need no regeneration. Run the focused checks with
`uv run pytest tests/test_documentation.py tests/test_reference_contracts.py`.

## Versions and publishing

`pyproject.toml` holds the package version. `rivretrieve.__version__` reads the
installed distribution metadata, so there is no second version to update.
Use uv to prepare the version and update `uv.lock`:

```sh
uv version 0.1.0
```

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
