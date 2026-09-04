"""source failure isolation : RequestedSeries × ProviderStages × TransportOutcomes → PartialAssembly."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

import polars as pl
import polars.testing as pl_testing

from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
    CanonicalRowsSchema,
    FetchWindow,
    Instant,
    ObservationRequest,
    Payload,
    ProductConfig,
    ProductWindowDeclarations,
    ProviderConfig,
    RenderedWindow,
    RequestedWindow,
    Rows,
    RowsSchema,
    SourceCallOrigin,
    SourceCoordinates,
    StopConvention,
    Unit,
    UnknownOriginFact,
    WindowDeclaration,
    WindowEndpoint,
    WindowGranularity,
    WindowRenderingVocabulary,
    WithIssues,
    ZoneValue,
)
from rivretrieve._internal.observations import ObservationProvenance
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.transport import (
    HttpMethod,
    Transport,
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

_PROVIDER = ProviderId("failure_probe")
_PRODUCT = ProductId("level")
_COORDINATES = SourceCoordinates("value")
_CONFIG = ProviderConfig(
    ZoneValue("+00:00"),
    {_PRODUCT: ProductConfig(_COORDINATES, Unit.M, Instant())},
)
_DECLARATIONS = ProductWindowDeclarations(
    {
        _PRODUCT: WindowDeclaration(
            WindowGranularity("date"),
            WindowRenderingVocabulary.DATE,
            StopConvention.INCLUSIVE,
        )
    }
)


class _TransportDrivenStages:
    config = _CONFIG
    window_declarations = _DECLARATIONS

    @staticmethod
    def fetch(
        stations: tuple[str, ...],
        products: tuple[ProductId, ...],
        rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
        fetch_window: FetchWindow,
        config: ProviderConfig,
        transport: Transport,
    ) -> WithIssues[tuple[Payload, ...]]:
        assert len(stations) == len(products) == 1
        station_id = stations[0]
        product_id = products[0]
        assert rendered_windows == {_PRODUCT: (RenderedWindow("2025-12-30", "2026-01-03"),)}
        assert config is _CONFIG
        response = transport.send(TransportRequest(HttpMethod.GET, f"https://source.test/{station_id}"))
        return WithIssues(
            (
                Payload(
                    _COORDINATES,
                    ((station_id, product_id),),
                    fetch_window,
                    response.content,
                    SourceCallOrigin(
                        response.url,
                        response.request_parameters,
                        response.status_code,
                        response.retrieved_at,
                        response.content_type or UnknownOriginFact(),
                        UnknownOriginFact(),
                        UnknownOriginFact(),
                    ),
                    response.prerequisite_calls,
                ),
            )
        )

    @staticmethod
    def parse(payload: Payload, config: ProviderConfig) -> WithIssues[Rows]:
        assert config is _CONFIG
        station_id = payload.content.decode()
        return WithIssues(
            pl.DataFrame(
                {
                    "station_id": [station_id],
                    "product_id": ["level"],
                    "time": [datetime(2026, 1, 1, 12)],
                    "value": [float(station_id.removeprefix("station-"))],
                    "time_zone": ["+00:00"],
                },
                schema=RowsSchema.polars_schema,
            )
        )


class _ScriptedTransport:
    def __init__(self, outcomes: dict[str, int | TransportFailureReason]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        station_id = request.url.rsplit("/", 1)[-1]
        self.calls.append(station_id)
        outcome = self.outcomes[station_id]
        if isinstance(outcome, TransportFailureReason):
            raise TransportFailure(request, outcome, 3)
        return TransportResponse(
            content=station_id.encode(),
            status_code=outcome,
            retrieved_at=datetime(2026, 1, 2, tzinfo=UTC),
            content_type="text/plain",
            url=request.url,
            request_parameters={},
        )


def _request(stations: tuple[str, ...]) -> ObservationRequest:
    return ObservationRequest(
        _PROVIDER,
        stations,
        (_PRODUCT,),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2026, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2026, 1, 1, 23, 59, 59, 999999)),
        ),
    )


def test_one_source_failure_does_not_discard_independent_series() -> None:
    stations = tuple(f"station-{number}" for number in range(1, 6))
    transport = _ScriptedTransport(
        {
            "station-1": 200,
            "station-2": 200,
            "station-3": TransportFailureReason.RETRY_EXHAUSTED,
            "station-4": 200,
            "station-5": 500,
        }
    )

    result = drive(
        _request(stations),
        _TransportDrivenStages(),
        provenance=ObservationProvenance(source="test", provider_id=_PROVIDER),
        transport=transport,
    )

    assert transport.calls == list(stations)
    expected = pl.DataFrame(
        {
            "time": [datetime(2026, 1, 1, 12)] * 3,
            "time_zone": ["+00:00"] * 3,
            "station_id": ["station-1", "station-2", "station-4"],
            "product_id": ["level"] * 3,
            "value": [1.0, 2.0, 4.0],
        },
        schema=CanonicalRowsSchema.polars_schema,
    )
    pl_testing.assert_frame_equal(result.canonical_rows, expected, check_exact=True)
    assert all(issue.details is not None for issue in result.issues)
    assert [(issue.severity, issue.details["station_id"]) for issue in result.issues if issue.details] == [
        ("error", "station-3"),
        ("error", "station-5"),
    ]
    assert "timeout" in result.issues[0].message
    assert "HTTP 500" in result.issues[1].message


def test_all_failed_series_return_an_empty_canonical_frame_with_issues() -> None:
    stations = ("station-1", "station-2")
    transport = _ScriptedTransport(dict.fromkeys(stations, 503))

    result = drive(
        _request(stations),
        _TransportDrivenStages(),
        provenance=ObservationProvenance(source="test", provider_id=_PROVIDER),
        transport=transport,
    )

    assert transport.calls == list(stations)
    pl_testing.assert_frame_equal(
        result.canonical_rows,
        pl.DataFrame(schema=CanonicalRowsSchema.polars_schema),
        check_exact=True,
    )
    assert [issue.severity for issue in result.issues] == ["error", "error"]
    assert [issue.details["status_code"] for issue in result.issues if issue.details] == [503, 503]


def test_404_is_warning_and_credential_rejection_names_only_the_variable() -> None:
    secret = "credential-secret-sentinel"
    transport = _ScriptedTransport({"station-1": 404, "station-2": 403})

    result = drive(
        _request(("station-1", "station-2")),
        _TransportDrivenStages(),
        provenance=ObservationProvenance(source="test", provider_id=_PROVIDER),
        transport=transport,
        credential_names=("NVE_API_KEY",),
    )

    assert [(issue.severity, issue.details["status_code"]) for issue in result.issues if issue.details] == [
        ("warning", 404),
        ("error", 403),
    ]
    assert "NVE_API_KEY" in result.issues[1].message
    public_text = repr(result)
    assert secret not in public_text
