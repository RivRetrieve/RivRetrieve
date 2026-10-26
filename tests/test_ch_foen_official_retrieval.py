"""Synthetic controls for official retrieval; source certification is separate."""

import json
from datetime import UTC, datetime

from rivretrieve._internal.engine import (
    Payload,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId


def test_archive_parser_preserves_parallel_variants_nulls_and_labels():
    from rivretrieve._internal.providers.ch_foen.official_config import OfficialRoute, config
    from rivretrieve._internal.providers.ch_foen.official_parse import parse

    route = OfficialRoute("data_1month_mean", "Q")
    records = [
        {
            "station": {"no": "station"},
            "parameterName": "Q",
            "tsName": name,
            "unitSymbol": "m3/s",
            "timestamp": "2025-01-31T23:00:00Z",
            "value": value,
            "releaseState": status,
        }
        for name, value, status in [("Variant", 12.0, "3"), ("Variant_01", None, None)]
    ]
    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2025, 1, 31)),
        WindowEndpoint.from_datetime(datetime(2025, 2, 28, 23, 59, 59)),
    )
    payload = Payload(
        SourceCoordinates(route),
        (("station", ProductId("discharge_1month_mean")),),
        window,
        json.dumps({"data": {"water": {"observations": {route.route: records}}}}).encode(),
        SourceCallOrigin(
            "https://example.test",
            {},
            200,
            datetime(2026, 1, 1, tzinfo=UTC),
            "application/json",
            UnknownOriginFact(),
            UnknownOriginFact(),
        ),
        (),
    )
    parsed = parse(payload, config())
    assert [(item.variant, item.product_id) for item in parsed.series] == [
        ("Variant", "discharge_1month_mean"),
        ("Variant_01", "discharge_1month_mean"),
    ]
    assert parsed.rows.select("time", "value").rows() == [
        (datetime(2025, 1, 31, 23), 12.0),
        (datetime(2025, 1, 31, 23), None),
    ]
    assert all(item.status.value == "success" for item in parsed.outcomes)


def test_official_fetch_splits_only_documented_overflow_and_keeps_sibling_success():
    from datetime import timedelta

    from rivretrieve._internal.engine import RenderedWindow
    from rivretrieve._internal.providers.ch_foen.official_config import config
    from rivretrieve._internal.providers.ch_foen.official_fetch import fetch
    from rivretrieve._internal.transport import TransportResponse

    product = ProductId("discharge_10min_mean")
    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2025, 1, 1, 0, 0, 3, 999999)),
    )
    rendered = RenderedWindow("2025-01-01T00:00:00Z", "2025-01-01T00:00:04Z", window)
    requests = []

    class Transport:
        def send(self, request):
            requests.append(request)
            if len(requests) == 1:
                document = {
                    "data": None,
                    "errors": [
                        {
                            "errorType": "ValidationError",
                            "message": "Query returned more than 10000 rows. Please narrow your query using filters or specify a limit.",
                            "path": ["water", "observations", "data_10min_mean"],
                        }
                    ],
                }
            elif len(requests) == 2:
                document = {"data": {"water": {"observations": {"data_10min_mean": []}}}}
            else:
                document = {"data": None, "errors": [{"errorType": "ValidationError", "message": "unrelated"}]}
            return TransportResponse(
                json.dumps(document).encode(),
                200,
                datetime(2026, 1, 1, tzinfo=UTC),
                "application/json",
                request.url,
                {},
            )

    acquired = fetch(
        ("station",),
        (product,),
        {product: (rendered,)},
        window,
        config(),
        Transport(),
        timestamp_precision=timedelta(seconds=1),
    )
    assert len(requests) == 3
    assert len(acquired.value) == 1
    assert len(acquired.calls) == 2
    assert len(acquired.outcomes) == 1
    assert acquired.outcomes[0].status.value == "failed"
    assert acquired.outcomes[0].window.start == datetime(2025, 1, 1, 0, 0, 2)
    queries = [json.loads(request.body)["query"] for request in requests]
    assert all("limit" not in query and "tsName:" not in query for query in queries)
    assert '"2025-01-01T00:00:02Z"' in queries[1]
    assert '"2025-01-01T00:00:02Z"' in queries[2]


def test_official_assembled_refresh_keeps_successful_sibling_and_held_failed_interval(tmp_path):
    from datetime import timedelta
    from functools import partial

    from rivretrieve._internal.driver import drive
    from rivretrieve._internal.engine import ObservationRequest, RequestedWindow
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.providers.ch_foen.official_config import config, window_declarations
    from rivretrieve._internal.providers.ch_foen.official_fetch import fetch
    from rivretrieve._internal.providers.ch_foen.official_parse import parse
    from rivretrieve._internal.providers.ch_foen.official_series import source_series
    from rivretrieve._internal.source_series import RestrictionKind, SeriesScope
    from rivretrieve._internal.store import StoreRoot
    from rivretrieve._internal.transport import TransportResponse
    from tests.test_internal_driver import _provenance

    definition = source_series(
        "station",
        "data_10min_mean",
        "Q",
        "Variant",
        units=("m3/s",),
        evidence="synthetic:unit",
        temporal_evidence="synthetic:time",
        origin="catalogue",
    )
    request = ObservationRequest(
        provider_id=ProviderId("ch_foen"),
        stations=("station",),
        products=(ProductId(definition.product_id),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2025, 1, 1, 0, 0, 3)),
        ),
        known_series=(definition,),
        scope=SeriesScope(restriction=RestrictionKind.EXPLICIT, series_ids=(definition.series_id,)),
    )

    class Provider:
        pass

    Provider.config = config()
    Provider.window_declarations = window_declarations()
    Provider.fetch = staticmethod(partial(fetch, timestamp_precision=timedelta(seconds=1)))
    Provider.parse = staticmethod(parse)

    class Transport:
        refreshing = False
        calls = 0

        def send(self, request):
            self.calls += 1
            query = json.loads(request.body)["query"]
            import re

            start, end = [
                datetime.fromisoformat(item).replace(tzinfo=None)
                for item in re.findall(r'_(?:gte|lt): "([^"]+)"', query)
            ]
            if self.refreshing and (end - start) > timedelta(days=3):
                document = {
                    "data": None,
                    "errors": [
                        {
                            "errorType": "ValidationError",
                            "message": "Query returned more than 10000 rows. Please narrow your query using filters or specify a limit.",
                            "path": ["water", "observations", "data_10min_mean"],
                        }
                    ],
                }
            elif self.refreshing and start >= datetime(2025, 1, 1, 0, 0, 1):
                document = {"data": None, "errors": [{"message": "source unavailable"}]}
            else:
                rows = [
                    {
                        "station": {"no": "station"},
                        "parameterName": "Q",
                        "tsName": "Variant",
                        "unitSymbol": "m3/s",
                        "timestamp": stamp.isoformat() + "Z",
                        "value": value,
                        "releaseState": None,
                    }
                    for stamp, value in [
                        (datetime(2025, 1, 1), 20.0 if self.refreshing else 10.0),
                        (datetime(2025, 1, 1, 0, 0, 2), 12.0),
                    ]
                    if start <= stamp < end
                ]
                document = {"data": {"water": {"observations": {"data_10min_mean": rows}}}}
            return TransportResponse(
                json.dumps(document).encode(),
                200,
                datetime(2026, 1, 1, tzinfo=UTC),
                "application/json",
                request.url,
                {},
            )

    transport = Transport()
    store = StoreRoot(tmp_path / "store")
    first = drive(
        request, Provider(), provenance=_provenance(request), transport=transport, cache="refresh", store=store
    )
    assert first.canonical_rows["value"].to_list() == [10.0, 12.0]
    transport.refreshing = True
    refreshed = drive(
        request, Provider(), provenance=_provenance(request), transport=transport, cache="refresh", store=store
    )
    assert refreshed.canonical_rows.sort("time")["value"].to_list() == [20.0, 12.0]
    failures = [item for item in refreshed.outcomes if item.status.value == "failed"]
    assert len(failures) == 1
    assert failures[0].window.start == datetime(2025, 1, 1, 0, 0, 1)
    assert json.loads(failures[0].reason.removeprefix("Source GraphQL errors: ")) == [{"message": "source unavailable"}]


def test_recent_empty_does_not_claim_retention_or_erase_null_observation():
    from dataclasses import replace

    from rivretrieve._internal.providers.ch_foen.official_config import OfficialRoute, config
    from rivretrieve._internal.providers.ch_foen.official_parse import parse
    from rivretrieve._internal.providers.ch_foen.official_series import source_series

    definition = source_series(
        "station",
        "data_live",
        "Q",
        None,
        units=("l/s",),
        evidence="synthetic:station-unit",
        temporal_evidence="synthetic:time",
        origin="catalogue",
    )
    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2025, 1, 1)), WindowEndpoint.from_datetime(datetime(2025, 1, 2))
    )
    record = {
        "stationNo": "station",
        "parameterName": "Q",
        "timestamp": "2025-01-01T00:00:00Z",
        "value": None,
        "releaseStatus": 0,
    }
    payload = Payload(
        SourceCoordinates(OfficialRoute("data_live", "Q")),
        (("station", ProductId("discharge_recent")),),
        window,
        json.dumps({"data": {"water": {"observations": {"data_live": [record]}}}}).encode(),
        SourceCallOrigin(
            "https://example.test",
            {},
            200,
            datetime(2026, 1, 1, tzinfo=UTC),
            "application/json",
            UnknownOriginFact(),
            UnknownOriginFact(),
        ),
        (),
        known_series=(definition,),
    )
    parsed = parse(payload, config())
    assert parsed.rows["value"].to_list() == [None]
    assert parsed.rows["source_unit"].to_list() == ["l/s"]
    assert parsed.outcomes[0].status.value == "success"
    assert parsed.outcomes[0].coverage == "observations"
    empty = parse(replace(payload, content=b'{"data":{"water":{"observations":{"data_live":[]}}}}'), config())
    assert empty.rows.is_empty()
    assert empty.outcomes[0].status.value == "unresolved"
    assert "retention" in empty.outcomes[0].reason
