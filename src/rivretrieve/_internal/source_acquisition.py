"""Bounded concrete-series source-call attempts without provider failure policy."""

from dataclasses import dataclass
from uuid import uuid4

from rivretrieve._internal.authentication import CredentialExchangeError
from rivretrieve._internal.source_series import SeriesWindow, SourceSeries
from rivretrieve._internal.transport import Transport, TransportFailure, TransportRequest, TransportResponse


@dataclass(frozen=True, slots=True)
class FailedSourceRequest:
    event_id: str
    series: SourceSeries
    window: SeriesWindow
    request: TransportRequest
    failure: TransportFailure | CredentialExchangeError


def attempt_series_request(
    transport: Transport,
    request: TransportRequest,
    series: SourceSeries,
    window: SeriesWindow,
) -> TransportResponse | FailedSourceRequest:
    """Retain a failed call for engine classification without discarding sibling responses."""
    attempted = attempt_request(transport, request)
    if isinstance(attempted, (TransportFailure, CredentialExchangeError)):
        return FailedSourceRequest(uuid4().hex, series, window, request, attempted)
    return attempted


def attempt_request(
    transport: Transport,
    request: TransportRequest,
) -> TransportResponse | TransportFailure | CredentialExchangeError:
    """Retain supported source failure values even before a concrete identity is established."""
    try:
        return transport.send(request)
    except (TransportFailure, CredentialExchangeError) as failure:
        return failure
