"""drive : ObservationRequest × ProviderStages × WindowPadder × ObservationProvenance × RawPayload → _AssemblyResult."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import polars as pl

from rivretrieve._internal.assembly import _AssemblyResult, assemble
from rivretrieve._internal.conversion import convert
from rivretrieve._internal.engine import (
    FetchWindow,
    ObservationRequest,
    Payload,
    ProviderConfig,
    RequestedWindow,
    Rows,
    WithIssues,
)
from rivretrieve._internal.observations import ObservationProvenance, RawPayload
from rivretrieve._internal.primitives import ProductId

type WindowPadder = Callable[[RequestedWindow], FetchWindow]


class ProviderStages(Protocol):
    config: ProviderConfig

    def fetch(
        self,
        stations: tuple[str, ...],
        products: tuple[ProductId, ...],
        window: FetchWindow,
        config: ProviderConfig,
    ) -> WithIssues[tuple[Payload, ...]]: ...

    def parse(
        self,
        payload: Payload,
        config: ProviderConfig,
    ) -> WithIssues[Rows]: ...


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
    parsed = [provider.parse(payload, config) for payload in fetched.value]
    rows = pl.concat([result.value for result in parsed])
    converted = convert(rows, config, request.window)
    return assemble(converted.value, provenance, converted.issues, raw)
