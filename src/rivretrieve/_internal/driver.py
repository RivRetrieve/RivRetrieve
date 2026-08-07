"""drive : concrete ObservationRequest × ProviderStages × ObservationProvenance × RawPayload → _AssemblyResult."""

from __future__ import annotations

from datetime import datetime, timedelta
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
    Rows,
    RowsSchema,
    WindowEndpoint,
    WithIssues,
    _make_fetch_window,
)
from rivretrieve._internal.observations import ObservationProvenance, RawPayload
from rivretrieve._internal.primitives import ProductId

_FETCH_WINDOW_PADDING = timedelta(days=2)


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


def drive(
    request: ObservationRequest,
    provider: ProviderStages,
    *,
    provenance: ObservationProvenance,
    raw: RawPayload,
) -> _AssemblyResult:
    config = provider.config
    requested_start = request.window.start
    requested_end = request.window.end
    fetch_window = _make_fetch_window(
        WindowEndpoint.from_datetime(
            datetime(
                requested_start.year,
                requested_start.month,
                requested_start.day,
                requested_start.hour,
                requested_start.minute,
                requested_start.second,
                requested_start.microsecond,
            )
            - _FETCH_WINDOW_PADDING
        ),
        WindowEndpoint.from_datetime(
            datetime(
                requested_end.year,
                requested_end.month,
                requested_end.day,
                requested_end.hour,
                requested_end.minute,
                requested_end.second,
                requested_end.microsecond,
            )
            + _FETCH_WINDOW_PADDING
        ),
    )
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
