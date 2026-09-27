# Development conventions

## Docstrings

Public functions and user-facing returned types, methods and attributes follow the
[public API docstring rule](../AGENTS.md#public-api-docstrings) in the root `AGENTS.md`.

For internal functions, use NumPy-style docstrings when the contract is not clear from the
signature. Document the parameters, returns and raised exceptions that need explanation.

## Provider safety guards

A live catalogue refresh may enforce a provider-specific minimum-station guard to reject an
implausibly small response. Calibrate the threshold from that provider's established population and
source behavior. Never copy a numeric threshold from another provider.
