"""Bounded concrete-series source-call attempts without provider failure policy."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from rivretrieve._internal.acquisition_dependencies import validate_prerequisite_ids
from rivretrieve._internal.authentication import CredentialExchangeError
from rivretrieve._internal.source_series import SeriesWindow, SourceSeries
from rivretrieve._internal.transport import (
    Transport,
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)


class SourceResponseMeaning(StrEnum):
    """Publisher-established meaning, distinct from transport failure classification."""

    UNSPECIFIED = "unspecified"
    NO_OBSERVATIONS = "no_observations"


def http_response_meaning(
    failure: TransportFailure | CredentialExchangeError,
    declared_status_meanings: Mapping[int, SourceResponseMeaning],
) -> SourceResponseMeaning:
    """Resolve publisher vocabulary only for an established HTTP status failure.

    A status carried by retry or authentication failure does not establish the
    meaning of a completed source response. Issue and interval policy remain
    engine responsibilities.
    """
    if (
        not isinstance(failure, TransportFailure)
        or failure.reason is not TransportFailureReason.HTTP_STATUS
        or failure.status_code is None
    ):
        return SourceResponseMeaning.UNSPECIFIED
    return declared_status_meanings.get(failure.status_code, SourceResponseMeaning.UNSPECIFIED)


@dataclass(frozen=True, slots=True)
class SourceRequestTarget:
    """A requested station and product before any concrete series is established."""

    station_id: str
    product_id: str

    @property
    def series_id(self) -> None:
        return None

    @property
    def variant(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class FailedSourceRequest:
    event_id: str
    series: SourceSeries | SourceRequestTarget
    window: SeriesWindow
    request: TransportRequest
    failure: TransportFailure | CredentialExchangeError
    meaning: SourceResponseMeaning = SourceResponseMeaning.UNSPECIFIED
    # Series events may share one physical request without sharing outcome identity.
    call_id: str | None = field(default=None, kw_only=True)
    # Successful source acquisitions needed to attempt this request.
    prerequisite_acquisition_ids: tuple[str, ...] = field(default=(), kw_only=True)

    def __post_init__(self) -> None:
        validate_prerequisite_ids(self.prerequisite_acquisition_ids)
        if not isinstance(self.meaning, SourceResponseMeaning):
            raise TypeError("source response meaning must be SourceResponseMeaning")


def attempt_series_request(
    transport: Transport,
    request: TransportRequest,
    series: SourceSeries,
    window: SeriesWindow,
    *,
    meaning: SourceResponseMeaning = SourceResponseMeaning.UNSPECIFIED,
) -> TransportResponse | FailedSourceRequest:
    """Retain a failed call for engine classification without discarding sibling responses."""
    attempted = attempt_request(transport, request)
    if isinstance(attempted, (TransportFailure, CredentialExchangeError)):
        return FailedSourceRequest(uuid4().hex, series, window, request, attempted, meaning)
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
