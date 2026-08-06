"""drive : concrete ObservationRequest × ProviderStages × WindowPadder × ObservationProvenance × RawPayload → _AssemblyResult."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import polars as pl

from rivretrieve._internal.assembly import _AssemblyResult, assemble
from rivretrieve._internal.catalogues.schemas import validate_catalogue
from rivretrieve._internal.conversion import convert
from rivretrieve._internal.engine import (
    CanonicalRowsSchema,
    FetchWindow,
    ObservationRequest,
    Payload,
    ProviderConfig,
    RequestedWindow,
    Rows,
    RowsSchema,
    WithIssues,
    _make_fetch_window,
)
from rivretrieve._internal.observations import ObservationProvenance, RawPayload
from rivretrieve._internal.primitives import ProductId

type WindowPadder = Callable[[RequestedWindow], FetchWindow]


class ProviderStages(Protocol):
    config: ProviderConfig

    @staticmethod
    def fetch(
        stations: tuple[str, ...],
        products: tuple[ProductId, ...],
        window: FetchWindow,
        config: ProviderConfig,
    ) -> WithIssues[tuple[Payload, ...]]: ...

    @staticmethod
    def parse(
        payload: Payload,
        config: ProviderConfig,
    ) -> WithIssues[Rows]: ...


def identity_window(window: RequestedWindow) -> FetchWindow:
    """Change only the nominal window type; perform no padding arithmetic."""
    return _make_fetch_window(window.start, window.end)


def drive(
    request: ObservationRequest,
    provider: ProviderStages,
    pad_window: WindowPadder,
    *,
    provenance: ObservationProvenance,
    raw: RawPayload,
) -> _AssemblyResult:
    config = provider.config
    fetch_window = pad_window(request.window)
    fetched = provider.fetch(request.stations, request.products, fetch_window, config)
    parsed: list[WithIssues[Rows]] = []
    for payload in fetched.value:
        result = provider.parse(payload, config)
        validate_catalogue(result.value, RowsSchema, on_issue="raise")
        parsed.append(result)
    rows = pl.concat([result.value for result in parsed] + [pl.DataFrame(schema=RowsSchema.polars_schema)])
    converted = convert(rows, config, request.window)
    validate_catalogue(converted.value, CanonicalRowsSchema, on_issue="raise")
    issues = fetched.issues + tuple(issue for result in parsed for issue in result.issues) + converted.issues
    return assemble(converted.value, provenance, issues, raw)
