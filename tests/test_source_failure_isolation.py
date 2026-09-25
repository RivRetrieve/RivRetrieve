"""source failure isolation : RequestedSeries × ProviderStages × TransportOutcomes → PartialAssembly."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

import polars as pl
import polars.testing as pl_testing

from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
    CanonicalRowsSchema,
    Daily,
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
from rivretrieve._internal.issues import Issue
from rivretrieve._internal.observations import ObservationProvenance
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.source_series import (
    ClippingAxis,
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    PhysicalFacts,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceIdentity,
    SourceSeries,
    known,
)
from rivretrieve._internal.transport import (
    HttpMethod,
    Transport,
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)


def _parsed(rows: Rows, payload: Payload, config: ProviderConfig, issues: tuple[Issue, ...] = ()) -> ParsedSeries:
    """A response-owned concrete definition and outcome for each test payload coordinate."""
    definitions = []
    outcomes = []
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    for station, product_id in payload.station_products:
        product = config.products[product_id]
        key = f"{station}:{product_id}"
        daily = isinstance(product.semantics, Daily)
        fact = PhysicalFacts(
            facts_id=f"{key}:facts",
            quantity=known("stage", "test source definition"),
            source_unit=known(product.unit.value, "test source definition"),
            normalized_unit=product.unit.value,
            frequency=known("daily" if daily else "instantaneous", "test source definition"),
            clipping_axis=ClippingAxis.CALENDAR_DATE if daily else ClippingAxis.SOURCE_TIMESTAMP,
            label_time=product.semantics.label_time.value if daily else None,
        )
        definitions.append(
            SourceSeries(
                series_id=key,
                provider_id="failure_probe",
                station_id=station,
                product_id=str(product_id),
                identity=SourceIdentity(
                    namespace="test-source", published_id=key, origin="response", evidence=("test payload",)
                ),
                facts=(fact,),
            )
        )
        outcomes.append(
            RetrievalOutcome(
                outcome_id=f"{key}:outcome",
                series_id=key,
                station_id=station,
                product_id=str(product_id),
                window=window,
                status=OutcomeStatus.EMPTY if rows.is_empty() else OutcomeStatus.SUCCESS,
                facts_ids=(fact.facts_id,),
            )
        )
    scope = payload.scope or SeriesScope(provider_ids=("failure_probe",))
    inventory = InventorySnapshot(
        snapshot_id="inventory:" + ":".join(item.series_id for item in definitions),
        scope=scope,
        members=tuple(item.series_id for item in definitions),
        completeness=InventoryCompleteness.COMPLETE,
        access="test source",
        origin="response",
        window=window,
        evidence=("test response inventory",),
    )
    return ParsedSeries(rows, tuple(definitions), (inventory,), tuple(outcomes), issues)


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
        *,
        scope: SeriesScope,
        known_series: tuple[SourceSeries, ...],
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
    def parse(payload: Payload, config: ProviderConfig) -> ParsedSeries:
        assert config is _CONFIG
        station_id = payload.content.decode()
        return _parsed(
            pl.DataFrame(
                {
                    "station_id": [station_id],
                    "product_id": ["level"],
                    "time": [datetime(2026, 1, 1, 12)],
                    "value": [float(station_id.removeprefix("station-"))],
                    "time_zone": ["+00:00"],
                    "series_id": [f"{station_id}:level"],
                    "facts_id": [f"{station_id}:level:facts"],
                    "source_unit": ["m"],
                },
                schema=RowsSchema.polars_schema,
            ),
            payload,
            config,
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
            "series_id": ["station-1:level", "station-2:level", "station-4:level"],
            "facts_id": ["station-1:level:facts", "station-2:level:facts", "station-4:level:facts"],
            "source_unit": ["m"] * 3,
            "quantity": ["stage"] * 3,
            "unit": ["m"] * 3,
        },
        schema=CanonicalRowsSchema.polars_schema,
    )
    pl_testing.assert_frame_equal(result.canonical_rows, expected, check_exact=True)
    assert all(issue.details is not None for issue in result.issues)
    assert [(issue.severity, issue.details["station_id"]) for issue in result.issues if issue.details] == [
        ("error", "station-3"),
        ("error", "station-5"),
    ]
    assert [(item.station_id, item.status) for item in result.outcomes] == [
        ("station-1", OutcomeStatus.SUCCESS),
        ("station-2", OutcomeStatus.SUCCESS),
        ("station-3", OutcomeStatus.FAILED),
        ("station-4", OutcomeStatus.SUCCESS),
        ("station-5", OutcomeStatus.FAILED),
    ]
    assert all(item.reason for item in result.outcomes if item.status is OutcomeStatus.FAILED)
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
    assert [item.status for item in result.outcomes] == [OutcomeStatus.FAILED, OutcomeStatus.FAILED]
    assert all(item.reason for item in result.outcomes)
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


def test_authenticated_interruption_category_survives_caller_issue_and_independent_success():
    from http.client import IncompleteRead

    import requests

    from rivretrieve._internal.transport import AuthenticatedTransport, CredentialHeader, HttpClient

    sentinel = "SENTINEL-RETRY-ISSUE-SECRET"
    calls = []

    def sender(request, timeout_seconds):
        calls.append(request.url)
        if request.url.endswith("station-1"):
            raise requests.exceptions.ChunkedEncodingError(IncompleteRead(sentinel.encode(), 10))
        return b"station-2", 200, "text/plain"

    transport = AuthenticatedTransport(
        HttpClient(sender=sender, sleeper=lambda _: None),
        (CredentialHeader("Authorization", f"Token {sentinel}", ("https://source.test",)),),
    )
    result = drive(
        _request(("station-1", "station-2")),
        _TransportDrivenStages(),
        provenance=ObservationProvenance(source="test", provider_id=_PROVIDER),
        transport=transport,
    )
    assert len(calls) == 4
    assert result.canonical_rows["station_id"].to_list() == ["station-2"]
    (issue,) = result.issues
    assert issue.details["failure_category"] == "incomplete_response"
    assert issue.details["failure_reason"] == "retry_exhausted"
    assert issue.details["request_url"] == "https://source.test/station-1"
    assert issue.details["attempts"] == 3
    assert issue.details["status_code"] is None
    assert sentinel not in repr(result)


def test_exchange_retry_diagnostics_survive_caller_issue():
    from rivretrieve._internal.authentication import AuthenticationFailureReason, CredentialExchangeError
    from rivretrieve._internal.driver import _source_failure_issue
    from rivretrieve._internal.transport import TransportFailureCategory

    failure = CredentialExchangeError(
        TransportRequest(HttpMethod.GET, "https://source.test/station-1"),
        AuthenticationFailureReason.DATA_SEND_FAILED,
        category=TransportFailureCategory.TIMEOUT,
        attempts=3,
        transport_reason=TransportFailureReason.RETRY_EXHAUSTED,
    )
    issue = _source_failure_issue(_PROVIDER, "station-1", _PRODUCT, failure, ())
    assert issue.details["failure_reason"] == "data_send_failed"
    assert issue.details["transport_failure_reason"] == "retry_exhausted"
    assert issue.details["failure_category"] == "timeout"
    assert issue.details["attempts"] == 3
    assert issue.details["status_code"] is None
