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

## Provider safety guards

A live catalogue refresh may enforce a provider-specific minimum-station guard to reject an
implausibly small response. Calibrate the threshold from that provider's established population and
source behavior. Never copy a numeric threshold from another provider.
