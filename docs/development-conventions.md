# Development conventions

## Docstrings

Use NumPy-style docstrings. Document parameters, returns, and raised exceptions for public functions
and for internal functions whose contract is not clear from the signature.

## Provider safety guards

A live catalogue refresh may enforce a provider-specific minimum-station guard to reject an
implausibly small response. Calibrate the threshold from that provider's established population and
source behavior. Never copy a numeric threshold from another provider.
