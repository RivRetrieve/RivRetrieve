from datetime import UTC, datetime

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve._internal.driver as driver_module
from rivretrieve._internal.assembly import _AssemblyResult
from rivretrieve._internal.assembly import assemble as real_assemble
from rivretrieve._internal.conversion import convert as real_convert
from rivretrieve._internal.engine import (
    CanonicalRows,
    CanonicalRowsSchema,
    FetchWindow,
    Instant,
    ObservationRequest,
    Payload,
    ProductConfig,
    ProviderConfig,
    RequestedWindow,
    Rows,
    RowsSchema,
    SourceCoordinates,
    Unit,
    WindowEndpoint,
    WithIssues,
    ZoneValue,
)
from rivretrieve._internal.issues import Issue
from rivretrieve._internal.observations import ObservationProvenance, RawPayload
from rivretrieve._internal.primitives import ProductId, ProviderId


class _ThrowawayProvider:
    def __init__(
        self,
        config: ProviderConfig,
        payload: Payload,
        rows: Rows,
        events: list[str],
    ) -> None:
        self.config = config
        self._payload = payload
        self._rows = rows
        self._events = events

    def fetch(
        self,
        stations: tuple[str, ...],
        products: tuple[ProductId, ...],
        window: FetchWindow,
        config: ProviderConfig,
    ) -> WithIssues[tuple[Payload, ...]]:
        self._events.append("fetch")
        assert stations == ("station-1",)
        assert products == (ProductId("level"),)
        assert window is self._payload.fetch_window
        assert isinstance(window, FetchWindow)
        assert not isinstance(window, RequestedWindow)
        assert config is self.config
        return WithIssues(value=(self._payload,))

    def parse(
        self,
        payload: Payload,
        config: ProviderConfig,
    ) -> WithIssues[Rows]:
        self._events.append("parse")
        assert payload is self._payload
        assert config is self.config
        return WithIssues(value=self._rows)


def test_drive_owns_stage_order_and_routes_nominal_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    requested_window = RequestedWindow(
        start=WindowEndpoint(datetime(2026, 1, 2, 0, tzinfo=UTC)),
        end=WindowEndpoint(datetime(2026, 1, 2, 23, tzinfo=UTC)),
    )
    request = ObservationRequest(
        provider_id=ProviderId("throwaway"),
        stations=("station-1",),
        products=(ProductId("level"),),
        window=requested_window,
    )
    padded_start = object()
    padded_end = object()
    fetch_window = FetchWindow(
        start=WindowEndpoint(padded_start),
        end=WindowEndpoint(padded_end),
    )
    coordinates = SourceCoordinates({"parameter": "height"})
    config = ProviderConfig(
        zone=ZoneValue("+00:00"),
        products={
            ProductId("level"): ProductConfig(
                coordinates=coordinates,
                unit=Unit.CM,
                semantics=Instant(),
            )
        },
    )
    payload = Payload(
        source_coordinates=coordinates,
        station_products=(("station-1", ProductId("level")),),
        fetch_window=fetch_window,
        content={"observations": [{"time": "2026-01-02T12:00:00", "value": 250.0}]},
    )
    rows = pl.DataFrame(
        {
            "station_id": ["station-1", "station-2"],
            "product_id": ["level", "level"],
            "time": [
                datetime(2026, 1, 2, 12),
                datetime(2026, 1, 2, 13),
            ],
            "value": [250.0, 300.0],
            "time_zone": ["+00:00", "unknown"],
        },
        schema=RowsSchema.polars_schema,
    )
    provider = _ThrowawayProvider(config, payload, rows, events)
    provenance = ObservationProvenance(
        source="test",
        provider_id=request.provider_id,
        request={"stations": ["station-1"], "products": ["level"]},
    )
    raw = RawPayload(
        provider_id=request.provider_id,
        content_type="application/json",
        content=b'{"observations":[{"time":"2026-01-02T12:00:00","value":250.0}]}',
        metadata="throwaway payload",
    )

    def pad_window(window: RequestedWindow) -> FetchWindow:
        events.append("pad")
        assert window is requested_window
        return fetch_window

    def recording_convert(
        supplied_rows: Rows,
        supplied_config: ProviderConfig,
        window: RequestedWindow,
    ) -> WithIssues[CanonicalRows]:
        events.append("convert")
        pl_testing.assert_frame_equal(supplied_rows, rows)
        assert supplied_config is config
        assert window is requested_window
        assert window is not fetch_window
        return real_convert(supplied_rows, supplied_config, window)

    def recording_assemble(
        canonical_rows: CanonicalRows,
        supplied_provenance: ObservationProvenance,
        issues: tuple[Issue, ...],
        supplied_raw: RawPayload,
    ) -> _AssemblyResult:
        events.append("assemble")
        assert supplied_provenance is provenance
        assert tuple(i.code for i in issues) == ("convert.unknown_time_zone",)
        assert supplied_raw is raw
        return real_assemble(canonical_rows, supplied_provenance, issues, supplied_raw)

    monkeypatch.setattr(driver_module, "convert", recording_convert)
    monkeypatch.setattr(driver_module, "assemble", recording_assemble)

    result = driver_module.drive(
        request,
        provider,
        pad_window,
        provenance=provenance,
        raw=raw,
    )

    expected = pl.DataFrame(
        {
            "time": [
                datetime(2026, 1, 2, 12),
                datetime(2026, 1, 2, 13),
            ],
            "time_zone": ["+00:00", "unknown"],
            "station_id": ["station-1", "station-2"],
            "product_id": ["level", "level"],
            "value": [2.5, 3.0],
        },
        schema=CanonicalRowsSchema.polars_schema,
    )
    pl_testing.assert_frame_equal(result.canonical_rows, expected)
    assert result.provenance is provenance
    assert tuple(i.code for i in result.issues) == ("convert.unknown_time_zone",)
    assert result.raw is raw
    assert events == ["pad", "fetch", "parse", "convert", "assemble"]
    assert {name for name in dir(provider) if not name.startswith("_")} == {
        "config",
        "fetch",
        "parse",
    }
