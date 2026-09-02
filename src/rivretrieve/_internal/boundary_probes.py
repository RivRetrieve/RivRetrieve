"""Boundary-probe run : DeclaredProvider* × (LiveProbe | StoreProbe)* → ProbeResult* | BoundaryProbeContractError."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

import polars as pl

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.registration import BulkStore, DeclaredProvider, LiveStages
from rivretrieve._internal.recordings import RecordedRequest, RecordingEnvelope, ReplayTransport
from rivretrieve._internal.store import StoreQuery, read_store
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


@dataclass(frozen=True, slots=True)
class StoreBoundaryProbe:
    """One source-backed claim resolved through an exact validated-store query."""

    provider_id: ProviderId
    product_id: ProductId
    query: StoreQuery
    assertions: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise TypeError("store boundary probe provider_id must be non-empty")
        if not isinstance(self.product_id, str) or not self.product_id:
            raise TypeError("store boundary probe product_id must be non-empty")
        if not isinstance(self.query, StoreQuery):
            raise TypeError("store boundary probe query must be StoreQuery")
        if not isinstance(self.assertions, Mapping):
            raise TypeError("store boundary probe assertions must be a mapping")
        if any(not isinstance(name, str) for name in self.assertions):
            raise TypeError("store boundary probe assertion names must be strings")
        object.__setattr__(self, "assertions", MappingProxyType(dict(self.assertions)))

    @property
    def key(self) -> ProviderProduct:
        return self.provider_id, self.product_id


# Explicit name for callers that register both provider-kind evidence variants.
LiveBoundaryProbe = BoundaryProbe

type BoundaryEvidence = LiveBoundaryProbe | StoreBoundaryProbe


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
    """Register and run exactly one typed boundary proof for every ported product."""

    def __init__(self, ported_provider_products: Iterable[ProviderProduct]) -> None:
        ported = tuple(_provider_product(value) for value in ported_provider_products)
        if len(ported) != len(set(ported)):
            raise BoundaryProbeContractError("ported provider-products contain a duplicate")
        self._ported = frozenset(ported)
        self._probes: dict[ProviderProduct, BoundaryEvidence] = {}

    def register(self, probe: BoundaryEvidence) -> None:
        """Validate and register typed evidence without executing its source path."""
        if not isinstance(probe, BoundaryProbe | StoreBoundaryProbe):
            raise TypeError("probe must be BoundaryProbe or StoreBoundaryProbe")
        if isinstance(probe, BoundaryProbe):
            _require_recordings(probe)
        else:
            _require_store_query(probe)
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
        """Refuse incomplete coverage, then execute and check every registered probe."""
        missing = sorted(self._ported - self._probes.keys())
        if missing:
            names = ", ".join(_describe(key) for key in missing)
            raise BoundaryProbeContractError(f"Ported provider-products have no boundary probe: {names}")

        results: list[pl.DataFrame] = []
        for key in sorted(self._probes):
            probe = self._probes[key]
            if isinstance(probe, BoundaryProbe):
                replay = _AuditedReplayTransport(probe.recordings)
                frame = probe.run(replay)
                if replay.unreplayed_requests:
                    requests = "; ".join(request.describe() for request in replay.unreplayed_requests)
                    raise BoundaryProbeContractError(
                        f"Boundary probe {_describe(key)} did not replay recorded request(s): {requests}"
                    )
            else:
                frame = read_store(probe.query).rows
            _check_result(probe, frame)
            results.append(frame)
        return tuple(results)


def run_boundary_probes(
    ported_provider_products: Iterable[ProviderProduct],
    probes: Iterable[BoundaryEvidence],
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


def run_manifest_boundary_probes(
    declared: Iterable[DeclaredProvider],
    probes: Iterable[BoundaryEvidence],
) -> tuple[pl.DataFrame, ...]:
    """Execute complete typed boundary evidence for manifest observation declarations.

    Parameters
    ----------
    declared
        Loaded providers whose observation products define the coverage obligation.
    probes
        Live replay or validated-store evidence registered for those products.

    Returns
    -------
    tuple[polars.DataFrame, ...]
        Checked source-wall-clock frames in provider-product order.

    Raises
    ------
    BoundaryProbeContractError
        If coverage or any registered evidence is incomplete or inconsistent.
    """
    declared_values = tuple(declared)
    probe_values = tuple(probes)
    kinds = _manifest_boundary_kinds(declared_values)
    for probe in probe_values:
        expected = kinds.get(probe.key)
        if expected is LiveStages and not isinstance(probe, BoundaryProbe):
            raise BoundaryProbeContractError(
                f"Manifest LiveStages product {_describe(probe.key)} requires ReplayTransport evidence"
            )
        if expected is BulkStore and not isinstance(probe, StoreBoundaryProbe):
            raise BoundaryProbeContractError(
                f"Manifest BulkStore product {_describe(probe.key)} requires validated-store evidence"
            )
    return run_boundary_probes(manifest_boundary_obligations(declared_values), probe_values)


def manifest_boundary_obligations(declared: Iterable[DeclaredProvider]) -> tuple[ProviderProduct, ...]:
    """Return every observation product implied by manifest provider declarations.

    Parameters
    ----------
    declared
        Loaded provider declarations in manifest order.

    Returns
    -------
    tuple[ProviderProduct, ...]
        One obligation per product for each live or bulk provider.
    """
    obligations: list[ProviderProduct] = []
    for item in declared:
        observations = item.declaration.observations
        if isinstance(observations, LiveStages):
            products = observations.stages.config.products
        elif isinstance(observations, BulkStore):
            products = observations.config.products
        else:
            continue
        obligations.extend(
            (ProviderId(item.provider_id), ProductId(str(product_id))) for product_id in sorted(products, key=str)
        )
    return tuple(obligations)


def _manifest_boundary_kinds(
    declared: Iterable[DeclaredProvider],
) -> dict[ProviderProduct, type[LiveStages] | type[BulkStore]]:
    kinds: dict[ProviderProduct, type[LiveStages] | type[BulkStore]] = {}
    for item in declared:
        observations = item.declaration.observations
        if isinstance(observations, LiveStages):
            kind = LiveStages
            products = observations.stages.config.products
        elif isinstance(observations, BulkStore):
            kind = BulkStore
            products = observations.config.products
        else:
            continue
        for product_id in products:
            kinds[(ProviderId(item.provider_id), ProductId(str(product_id)))] = kind
    return kinds


def _require_store_query(probe: StoreBoundaryProbe) -> None:
    query = probe.query
    if query.provider_id != probe.provider_id:
        raise BoundaryProbeContractError(
            f"Boundary probe {_describe(probe.key)} query provider {query.provider_id} does not match"
        )
    if query.products != (probe.product_id,):
        products = ", ".join(str(product) for product in query.products)
        raise BoundaryProbeContractError(
            f"Boundary probe {_describe(probe.key)} query products [{products}] do not match exactly"
        )


def _require_recordings(probe: BoundaryProbe) -> None:
    if not probe.recordings or not all(isinstance(value, RecordingEnvelope) for value in probe.recordings):
        raise BoundaryProbeContractError(
            f"Boundary probe {_describe(probe.key)} has no RecordingEnvelope carrying "
            "a recorded request and retrieval instant"
        )


def _require_exact_assertions(probe: BoundaryEvidence) -> None:
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


def _require_assertion_values(probe: BoundaryEvidence) -> None:
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


def _check_result(probe: BoundaryEvidence, frame: object) -> None:
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
    probe: BoundaryEvidence,
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
