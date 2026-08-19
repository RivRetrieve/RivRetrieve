"""Boundary-probe run : PortedProviderProduct* × BoundaryProbe* → ProbeResult* | BoundaryProbeContractError."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

import polars as pl

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.recordings import RecordedRequest, RecordingEnvelope, ReplayTransport
from rivretrieve._internal.transport import TransportRequest, TransportResponse

READING_COUNT = "reading_count"
FIRST_WALL_CLOCK_TIME = "first_wall_clock_time"
LAST_WALL_CLOCK_TIME = "last_wall_clock_time"
BOUNDARY_ASSERTIONS = frozenset({READING_COUNT, FIRST_WALL_CLOCK_TIME, LAST_WALL_CLOCK_TIME})

type ProviderProduct = tuple[ProviderId, ProductId]
type ProbeRunner = Callable[[ReplayTransport], pl.DataFrame]


class BoundaryProbeContractError(FatalContractError):
    """A boundary probe is unauditable, incomplete, duplicated, or wrong."""


@dataclass(frozen=True, slots=True)
class WallClockExpectation:
    """One independently authored local time and its source-published zone label."""

    time: str
    time_zone: str

    def __post_init__(self) -> None:
        if not isinstance(self.time, str) or not self.time:
            raise TypeError("expected wall-clock time must be non-empty")
        if not isinstance(self.time_zone, str) or not self.time_zone:
            raise TypeError("expected wall-clock time_zone must be non-empty")


@dataclass(frozen=True, slots=True)
class BoundaryProbe:
    """One source-backed claim about readings that straddle local midnight."""

    provider_id: ProviderId
    product_id: ProductId
    recordings: tuple[RecordingEnvelope, ...]
    assertions: Mapping[str, object]
    run: ProbeRunner

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise TypeError("boundary probe provider_id must be non-empty")
        if not isinstance(self.product_id, str) or not self.product_id:
            raise TypeError("boundary probe product_id must be non-empty")
        if not isinstance(self.recordings, tuple):
            raise TypeError("boundary probe recordings must be a tuple")
        if not isinstance(self.assertions, Mapping):
            raise TypeError("boundary probe assertions must be a mapping")
        if any(not isinstance(name, str) for name in self.assertions):
            raise TypeError("boundary probe assertion names must be strings")
        if not callable(self.run):
            raise TypeError("boundary probe run must be callable")
        object.__setattr__(self, "assertions", MappingProxyType(dict(self.assertions)))

    @property
    def key(self) -> ProviderProduct:
        return self.provider_id, self.product_id


class _AuditedReplayTransport(ReplayTransport):
    """Replay transport that reports which declared recordings a probe resolved."""

    def __init__(self, recordings: tuple[RecordingEnvelope, ...]) -> None:
        super().__init__(recordings)
        self._declared_requests = tuple(recording.request for recording in recordings)
        self._replayed_requests: list[RecordedRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        response = super().send(request)
        self._replayed_requests.append(RecordedRequest.from_transport_request(request))
        return response

    @property
    def unreplayed_requests(self) -> tuple[RecordedRequest, ...]:
        return tuple(request for request in self._declared_requests if request not in self._replayed_requests)


class BoundaryProbeHarness:
    """Register and run exactly one audited boundary probe for every ported product."""

    def __init__(self, ported_provider_products: Iterable[ProviderProduct]) -> None:
        ported = tuple(_provider_product(value) for value in ported_provider_products)
        if len(ported) != len(set(ported)):
            raise BoundaryProbeContractError("ported provider-products contain a duplicate")
        self._ported = frozenset(ported)
        self._probes: dict[ProviderProduct, BoundaryProbe] = {}

    def register(self, probe: BoundaryProbe) -> None:
        """Validate and register a probe without executing provider code."""
        if not isinstance(probe, BoundaryProbe):
            raise TypeError("probe must be BoundaryProbe")
        _require_recordings(probe)
        _require_exact_assertions(probe)
        _require_assertion_values(probe)
        if probe.key not in self._ported:
            raise BoundaryProbeContractError(
                f"Boundary probe is not for a ported provider-product: {_describe(probe.key)}"
            )
        if probe.key in self._probes:
            raise BoundaryProbeContractError(f"Boundary probe is already registered: {_describe(probe.key)}")
        self._probes[probe.key] = probe

    def run(self) -> tuple[pl.DataFrame, ...]:
        """Refuse incomplete coverage, then replay and check every registered probe."""
        missing = sorted(self._ported - self._probes.keys())
        if missing:
            names = ", ".join(_describe(key) for key in missing)
            raise BoundaryProbeContractError(f"Ported provider-products have no boundary probe: {names}")

        results: list[pl.DataFrame] = []
        for key in sorted(self._probes):
            probe = self._probes[key]
            replay = _AuditedReplayTransport(probe.recordings)
            frame = probe.run(replay)
            if replay.unreplayed_requests:
                requests = "; ".join(request.describe() for request in replay.unreplayed_requests)
                raise BoundaryProbeContractError(
                    f"Boundary probe {_describe(key)} did not replay recorded request(s): {requests}"
                )
            _check_result(probe, frame)
            results.append(frame)
        return tuple(results)


def run_boundary_probes(
    ported_provider_products: Iterable[ProviderProduct],
    probes: Iterable[BoundaryProbe],
) -> tuple[pl.DataFrame, ...]:
    """Build one harness, register its probes, and run complete coverage."""
    harness = BoundaryProbeHarness(ported_provider_products)
    for probe in probes:
        harness.register(probe)
    return harness.run()


def _provider_product(value: object) -> ProviderProduct:
    if not isinstance(value, tuple) or len(value) != 2:
        raise TypeError("ported provider-product must be a (provider_id, product_id) tuple")
    provider_id, product_id = value
    if not isinstance(provider_id, str) or not provider_id:
        raise TypeError("ported provider_id must be non-empty")
    if not isinstance(product_id, str) or not product_id:
        raise TypeError("ported product_id must be non-empty")
    return ProviderId(provider_id), ProductId(product_id)


def _require_recordings(probe: BoundaryProbe) -> None:
    if not probe.recordings or not all(isinstance(value, RecordingEnvelope) for value in probe.recordings):
        raise BoundaryProbeContractError(
            f"Boundary probe {_describe(probe.key)} has no RecordingEnvelope carrying "
            "a recorded request and retrieval instant"
        )


def _require_exact_assertions(probe: BoundaryProbe) -> None:
    actual = set(probe.assertions)
    extra = sorted(actual - BOUNDARY_ASSERTIONS)
    if extra:
        raise BoundaryProbeContractError(
            f"Boundary probe {_describe(probe.key)} has extra assertion(s) {extra}; "
            f"allowed assertions are {sorted(BOUNDARY_ASSERTIONS)}"
        )
    missing = sorted(BOUNDARY_ASSERTIONS - actual)
    if missing:
        raise BoundaryProbeContractError(f"Boundary probe {_describe(probe.key)} is missing assertion(s) {missing}")


def _require_assertion_values(probe: BoundaryProbe) -> None:
    count = probe.assertions[READING_COUNT]
    if type(count) is not int or count <= 0:
        raise BoundaryProbeContractError(
            f"Boundary probe {_describe(probe.key)} reading_count must be a positive integer"
        )
    for name in (FIRST_WALL_CLOCK_TIME, LAST_WALL_CLOCK_TIME):
        if not isinstance(probe.assertions[name], WallClockExpectation):
            raise BoundaryProbeContractError(
                f"Boundary probe {_describe(probe.key)} {name} must be WallClockExpectation"
            )


def _check_result(probe: BoundaryProbe, frame: object) -> None:
    name = _describe(probe.key)
    if not isinstance(frame, pl.DataFrame):
        raise BoundaryProbeContractError(f"Boundary probe {name} did not return a Polars DataFrame")
    missing_columns = {"time", "time_zone"} - set(frame.columns)
    if missing_columns:
        raise BoundaryProbeContractError(f"Boundary probe {name} result is missing columns {sorted(missing_columns)}")
    if "product_id" in frame.columns:
        frame = frame.filter(pl.col("product_id") == probe.product_id)
    frame = frame.sort("time")
    count = frame.height
    expected_count = probe.assertions[READING_COUNT]
    if count != expected_count:
        raise BoundaryProbeContractError(
            f"Boundary probe {name} reading_count differs: expected {expected_count}, got {count}"
        )
    times = frame.get_column("time").to_list()
    zones = frame.get_column("time_zone").to_list()
    first = _wall_clock(times[0], zones[0], probe, FIRST_WALL_CLOCK_TIME)
    last = _wall_clock(times[-1], zones[-1], probe, LAST_WALL_CLOCK_TIME)
    for assertion, actual in (
        (FIRST_WALL_CLOCK_TIME, first),
        (LAST_WALL_CLOCK_TIME, last),
    ):
        expected = probe.assertions[assertion]
        if actual != expected:
            raise BoundaryProbeContractError(
                f"Boundary probe {name} {assertion} differs: expected {expected!r}, got {actual!r}"
            )


def _wall_clock(
    value: object,
    zone: object,
    probe: BoundaryProbe,
    assertion: str,
) -> WallClockExpectation:
    if not isinstance(value, datetime):
        raise BoundaryProbeContractError(f"Boundary probe {_describe(probe.key)} {assertion} is not a datetime")
    if value.tzinfo is not None:
        raise BoundaryProbeContractError(
            f"Boundary probe {_describe(probe.key)} {assertion} must be a local wall-clock datetime"
        )
    if not isinstance(zone, str) or not zone:
        raise BoundaryProbeContractError(
            f"Boundary probe {_describe(probe.key)} {assertion} has no source time-zone label"
        )
    return WallClockExpectation(value.isoformat(), zone)


def _describe(key: ProviderProduct) -> str:
    return f"{key[0]}/{key[1]}"
