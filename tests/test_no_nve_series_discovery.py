"""HydAPI version discovery uses recorded current metadata, not a frozen catalogue subset."""

from datetime import datetime
from pathlib import Path

from rivretrieve._internal.engine import RenderedWindow, WindowEndpoint, _make_fetch_window
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.no_nve.config import config
from rivretrieve._internal.providers.no_nve.fetch import fetch
from rivretrieve._internal.providers.no_nve.series import describe_series
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from rivretrieve._internal.source_series import SeriesScope

_DATA = Path(__file__).parent / "test_data"


def test_recorded_current_inventory_finds_versions_outside_acquired_subset():
    """The deliberately partial catalogue input is authored; publisher bytes are exact."""
    product = ProductId("discharge_daily_mean")
    recordings = [read_recording(_DATA / "no_nve_109.42.0_1001_series.recording.json")]
    recordings.extend(
        read_recording(_DATA / f"no_nve_109.42.0_1001_1440_version-{version}_2024-01-01_2024-01-03.recording.json")
        for version in (1, 2, 3)
    )
    transport = _ObservedTransport(recordings)
    acquired = fetch(
        ("109.42.0",),
        (product,),
        {product: (RenderedWindow("2024-01-01", "2024-01-03"),)},
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1)), WindowEndpoint.from_datetime(datetime(2024, 1, 3))
        ),
        config(),
        transport,
        scope=SeriesScope(provider_ids=("no_nve",), station_ids=("109.42.0",), product_ids=(product,)),
        known_series=(describe_series("109.42.0", 1001, 1, 1440, "Mean", "m³/s", origin="catalogue"),),
    )
    assert {item.origin.request_parameters["VersionNumber"] for item in acquired.value} == {1, 2, 3}
    assert transport.requests[0].url == "https://hydapi.nve.no/api/v1/Series"
    assert any(call.url == "https://hydapi.nve.no/api/v1/Series" for call in acquired.calls)
    assert any(snapshot.completeness == "complete" for snapshot in acquired.inventories)


class _ObservedTransport:
    def __init__(self, recordings, *, metadata=None):
        self.replay = ReplayTransport(recordings)
        self.requests = []
        self.metadata = metadata

    def send(self, request):
        import json
        from dataclasses import replace

        from rivretrieve._internal.transport import TransportFailure, TransportFailureReason

        self.requests.append(request)
        if request.url.endswith("/Series") and self.metadata == "failure":
            raise TransportFailure(request, TransportFailureReason.RETRY_EXHAUSTED, 3, status_code=503)
        response = self.replay.send(request)
        if request.url.endswith("/Series") and self.metadata is not None:
            # Authored structural controls over exact metadata, not publisher recordings.
            document = json.loads(response.content)
            if self.metadata == "missing-historical":
                document["data"] = [item for item in document["data"] if item["versionNo"] != 1]
                document["itemCount"] = len(document["data"])
            elif self.metadata == "malformed-member":
                document["data"][2]["unit"] = False
            elif self.metadata == "wrong-station":
                document["data"][2]["stationId"] = "wrong-station"
            elif self.metadata == "unknown-unit":
                for item in document["data"]:
                    item["unit"] = None
            elif self.metadata == "empty":
                document["data"] = []
                document["itemCount"] = 0
            response = replace(response, content=json.dumps(document).encode())
        return response


def _recorded_fetch(transport, *, known=(1, 2, 3), scope=None):
    product = ProductId("discharge_daily_mean")
    return fetch(
        ("109.42.0",),
        (product,),
        {product: (RenderedWindow("2024-01-01", "2024-01-03"),)},
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1)), WindowEndpoint.from_datetime(datetime(2024, 1, 3))
        ),
        config(),
        transport,
        scope=scope or SeriesScope(provider_ids=("no_nve",), station_ids=("109.42.0",), product_ids=(product,)),
        known_series=tuple(
            describe_series("109.42.0", 1001, v, 1440, "Mean", "m³/s", origin="catalogue") for v in known
        ),
    )


def _recordings():
    return (
        read_recording(_DATA / "no_nve_109.42.0_1001_series.recording.json"),
        *(
            read_recording(_DATA / f"no_nve_109.42.0_1001_1440_version-{v}_2024-01-01_2024-01-03.recording.json")
            for v in (1, 2, 3)
        ),
    )


def test_current_metadata_does_not_erase_historical_acquired_version():
    transport = _ObservedTransport(_recordings(), metadata="missing-historical")
    acquired = _recorded_fetch(transport)
    assert {item.origin.request_parameters["VersionNumber"] for item in acquired.value} == {1, 2, 3}
    assert acquired.inventories[0].completeness == "incomplete"
    assert "historical" in acquired.inventories[0].reason
    assert acquired.issues


def test_metadata_failure_keeps_independent_known_versions_without_complete_inventory():
    transport = _ObservedTransport(_recordings(), metadata="failure")
    acquired = _recorded_fetch(transport)
    assert {item.origin.request_parameters["VersionNumber"] for item in acquired.value} == {1, 2, 3}
    assert acquired.inventories[0].completeness == "incomplete"
    assert acquired.outcomes[0].status == "unresolved"
    assert "503" in acquired.issues[0].message
    assert acquired.calls[0].status_code == 503


def test_explicit_identity_never_widens_or_requires_metadata():
    from rivretrieve._internal.source_series import RestrictionKind

    transport = _ObservedTransport(_recordings())
    scope = SeriesScope(
        provider_ids=("no_nve",),
        station_ids=("109.42.0",),
        product_ids=("discharge_daily_mean",),
        restriction=RestrictionKind.EXPLICIT,
        variants=("2",),
    )
    acquired = _recorded_fetch(transport, scope=scope)
    assert {item.origin.request_parameters["VersionNumber"] for item in acquired.value} == {2}
    assert not any(request.url.endswith("/Series") for request in transport.requests)


def test_malformed_metadata_member_does_not_drop_valid_version():
    transport = _ObservedTransport(_recordings(), metadata="malformed-member")
    acquired = _recorded_fetch(transport, known=())
    assert {item.origin.request_parameters["VersionNumber"] for item in acquired.value} == {1, 2}
    assert acquired.inventories[0].completeness == "incomplete"
    assert acquired.issues


def test_wrong_station_metadata_never_becomes_a_version_selector():
    transport = _ObservedTransport(_recordings(), metadata="wrong-station")
    acquired = _recorded_fetch(transport, known=())
    assert {item.origin.request_parameters["VersionNumber"] for item in acquired.value} == {1, 2}
    assert "station or parameter" in acquired.inventories[0].reason


def test_current_empty_inventory_is_not_unidentified_empty_observations():
    transport = _ObservedTransport(_recordings(), metadata="empty")
    acquired = _recorded_fetch(transport, known=())
    assert acquired.value == ()
    assert acquired.inventories[0].completeness == "complete"
    assert acquired.outcomes[0].status == "no_match"
    assert acquired.issues == ()


def test_current_complete_inventory_can_settle_no_physical_match():
    from rivretrieve._internal.source_series import PhysicalPredicate

    transport = _ObservedTransport(_recordings())
    scope = SeriesScope(
        provider_ids=("no_nve",),
        station_ids=("109.42.0",),
        product_ids=("discharge_daily_mean",),
        predicates=(PhysicalPredicate(field="statistic", value="max"),),
    )
    acquired = _recorded_fetch(transport, known=(), scope=scope)
    assert acquired.value == ()
    assert acquired.inventories[0].completeness == "complete"
    assert acquired.outcomes[0].status == "no_match"
    assert not acquired.issues


def test_unknown_admission_metadata_is_not_established_physical_absence():
    from rivretrieve._internal.source_series import PhysicalPredicate

    transport = _ObservedTransport(_recordings(), metadata="unknown-unit")
    scope = SeriesScope(
        provider_ids=("no_nve",),
        station_ids=("109.42.0",),
        product_ids=("discharge_daily_mean",),
        predicates=(PhysicalPredicate(field="statistic", value="max"),),
    )
    acquired = _recorded_fetch(transport, known=(), scope=scope)
    assert acquired.outcomes[0].status == "unresolved"
    assert "admission" in acquired.outcomes[0].reason
    assert acquired.series and all(item.facts[0].source_unit.value is None for item in acquired.series)
