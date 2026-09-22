"""Authored protocol controls; these are not publisher recordings."""

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import pytest

from rivretrieve._internal import engine
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.usgs_nwis.config import UsgsNwisSourceCoordinates, config, window_declarations
from rivretrieve._internal.providers.usgs_nwis.fetch import fetch
from rivretrieve._internal.providers.usgs_nwis.metadata import source_series
from rivretrieve._internal.source_series import InventoryCompleteness, OutcomeStatus, RestrictionKind, SeriesScope
from rivretrieve._internal.transport import TransportFailure, TransportFailureReason, TransportResponse
from rivretrieve._internal.window_planning import plan_windows

PRODUCT = ProductId("discharge_daily_mean")
STATION = "02196000"
LOCATION = "USGS-02196000"
BASE = "https://api.waterdata.usgs.gov/ogcapi/v1/collections/daily/items"
PARAMS = {
    "f": "json",
    "monitoring_location_id": LOCATION,
    "parameter_code": "00060",
    "statistic_id": "00003",
    "datetime": "2000-01-01/2000-01-07",
    "limit": "10000",
}


def feature(identifier="alpha", day="2000-01-01"):
    return {
        "type": "Feature",
        "id": "record-version",
        "properties": {
            "time_series_id": identifier,
            "monitoring_location_id": LOCATION,
            "parameter_code": "00060",
            "statistic_id": "00003",
            "unit_of_measure": "ft^3/s",
            "time": day,
            "value": "12.25",
            "approval_status": "Approved",
            "qualifier": None,
        },
    }


def page(*features, next_url=None):
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": features,
            "links": [] if next_url is None else [{"rel": "next", "href": next_url}],
        }
    ).encode()


def next_url(**changes):
    return BASE + "?" + urlencode({**PARAMS, "cursor": "next", **changes})


def definition(identifier):
    return source_series(
        feature(identifier)["properties"],
        STATION,
        str(PRODUCT),
        UsgsNwisSourceCoordinates("daily", "00060", "00003"),
        metadata=False,
        monitoring_location_id=LOCATION,
    )


class Transport:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        data = next(self.responses)
        if data == "fail":
            raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=429)
        return TransportResponse(
            data, 200, datetime(2026, 9, 22, tzinfo=UTC), "application/geo+json", request.url, request.params or {}
        )


def acquire(transport, known=(), scope=None):
    window = engine._make_fetch_window(
        engine.WindowEndpoint.from_datetime(datetime(2000, 1, 1)),
        engine.WindowEndpoint.from_datetime(datetime(2000, 1, 7, 23, 59, 59, 999999)),
    )
    return fetch(
        (STATION,),
        (PRODUCT,),
        {PRODUCT: (engine.RenderedWindow("2000-01-01", "2000-01-07"),)},
        window,
        config(),
        transport,
        monitoring_locations={STATION: LOCATION},
        known_series=known,
        scope=scope,
    )


def test_exhausted_pages_keep_exact_bytes_union_and_empty_only_at_end():
    first = page(feature(), next_url=next_url())
    second = page(feature("beta", "2000-01-02"))
    result = acquire(Transport(first, second), (definition("ended"),))
    assert tuple(p.content for p in result.value) == (first, second)
    assert result.inventories[0].completeness is InventoryCompleteness.COMPLETE
    assert len(result.inventories[0].members) == 3
    assert [(o.series_id, o.status) for o in result.outcomes] == [(definition("ended").series_id, OutcomeStatus.EMPTY)]


@pytest.mark.parametrize("late", ["fail", b"not JSON", page(next_url="https://evil.example/items")])
def test_late_failure_preserves_bytes_and_cannot_certify_complete(late):
    first = page(feature(), next_url=next_url())
    result = acquire(Transport(first, late), (definition("ended"),))
    assert result.value[0].content == first
    assert len(result.value) == (1 if late == "fail" else 2)
    assert result.inventories[0].completeness is InventoryCompleteness.INCOMPLETE
    assert not any(o.status is OutcomeStatus.EMPTY for o in result.outcomes)
    assert {o.series_id for o in result.outcomes} >= {definition("alpha").series_id, definition("ended").series_id}
    if late == "fail":
        assert result.failed_requests[0].failure.status_code == 429


@pytest.mark.parametrize(
    "url",
    [
        next_url(parameter_code="00065"),
        next_url(statistic_id="00001"),
        next_url(datetime="2000-01-01/2000-01-08"),
        next_url(time_series_id="other"),
        next_url().replace("/v1/", "/v0/"),
        next_url().replace("https://", "http://"),
        next_url() + "#fragment",
        next_url() + "&limit=10000",
    ],
)
def test_next_link_rejects_scope_or_origin_changes_before_network(url):
    transport = Transport(page(feature(), next_url=url))
    result = acquire(transport)
    assert len(transport.requests) == 1
    assert result.inventories[0].completeness is InventoryCompleteness.INCOMPLETE


def test_cursor_cycle_is_failure():
    transport = Transport(
        page(feature(), next_url=next_url()), page(feature("alpha", "2000-01-02"), next_url=next_url())
    )
    result = acquire(transport)
    assert len(transport.requests) == 2
    assert "cycle" in result.inventories[0].reason


def test_duplicate_logical_observation_is_not_silently_overwritten():
    result = acquire(Transport(page(feature(), next_url=next_url()), page(feature())))
    assert result.inventories[0].completeness is InventoryCompleteness.INCOMPLETE
    assert "repeats" in result.inventories[0].reason


def test_explicit_sibling_requests_are_independent():
    scope = SeriesScope(
        provider_ids=("usgs_nwis",),
        station_ids=(STATION,),
        product_ids=(str(PRODUCT),),
        restriction=RestrictionKind.EXPLICIT,
        variants=("alpha", "beta"),
    )
    transport = Transport("fail", page(feature("beta")))
    result = acquire(transport, (definition("alpha"), definition("beta")), scope)
    assert [r.params["time_series_id"] for r in transport.requests] == ["alpha", "beta"]
    assert len(result.value) == 1
    assert result.failed_requests[0].series.identity.published_id == "alpha"
    assert not any(
        o.series_id == definition("beta").series_id and o.status is OutcomeStatus.UNRESOLVED for o in result.outcomes
    )


def test_missing_monitoring_location_mapping_is_fatal():
    from rivretrieve._internal.issues import FatalContractError

    with pytest.raises(FatalContractError, match="monitoring location identity"):
        window = engine._make_fetch_window(
            engine.WindowEndpoint.from_datetime(datetime(2000, 1, 1)),
            engine.WindowEndpoint.from_datetime(datetime(2000, 1, 7)),
        )
        fetch((STATION,), (PRODUCT,), {}, window, config(), Transport(), monitoring_locations={})


def test_continuous_inclusive_chunks_preserve_endpoints_without_gaps():
    start = datetime(2000, 1, 1, 12, 13, 14, 123456)
    end = start + timedelta(days=2200, hours=4)
    window = engine._make_fetch_window(
        engine.WindowEndpoint.from_datetime(start), engine.WindowEndpoint.from_datetime(end)
    )
    declarations = window_declarations()
    rendered = plan_windows(window, declarations.products[ProductId("discharge_instantaneous")])
    pairs = [
        (datetime.fromisoformat(w.start.removesuffix("Z")), datetime.fromisoformat(w.stop.removesuffix("Z")))
        for w in rendered
    ]
    assert pairs[0][0] == start and pairs[-1][1] == end
    assert all(stop - begin < timedelta(days=1100) for begin, stop in pairs)
    assert all(left[1] + timedelta(microseconds=1) == right[0] for left, right in zip(pairs, pairs[1:], strict=False))
    assert config().products[ProductId("discharge_instantaneous")].coordinates.value.statistic_code is None


def test_unknown_empty_explicit_id_does_not_fabricate_identity_or_success():
    scope = SeriesScope(restriction=RestrictionKind.EXPLICIT, variants=("unestablished",))
    result = acquire(Transport(page()), scope=scope)
    assert result.series == ()
    assert result.inventories[0].completeness is InventoryCompleteness.INCOMPLETE
    assert result.outcomes[0].requested_selector.value == "unestablished"


def test_empty_broad_response_has_finite_no_match_outcome():
    result = acquire(Transport(page()))
    assert result.inventories[0].completeness is InventoryCompleteness.COMPLETE
    assert result.outcomes[0].status is OutcomeStatus.NO_MATCH


def test_internal_parser_error_is_never_isolated_as_source_failure(monkeypatch):
    import importlib

    from rivretrieve._internal.issues import FatalContractError

    module = importlib.import_module("rivretrieve._internal.providers.usgs_nwis.fetch")

    def fatal(*args):
        raise FatalContractError("invalid internal stage")

    monkeypatch.setattr(module, "parse", fatal)
    with pytest.raises(FatalContractError, match="internal stage"):
        acquire(Transport(page(feature())))


def test_late_continuous_chunk_failure_blocks_whole_transaction():
    product = ProductId("discharge_instantaneous")
    start = datetime(2000, 1, 1, 12)
    stop = start + timedelta(days=1101)
    window = engine._make_fetch_window(
        engine.WindowEndpoint.from_datetime(start), engine.WindowEndpoint.from_datetime(stop)
    )
    rendered = plan_windows(window, window_declarations().products[product])
    observation = feature()
    observation["properties"].update(statistic_id="00011", time="2000-01-01T12:00:00Z")
    transport = Transport(page(observation), "fail")
    result = fetch(
        (STATION,),
        (product,),
        {product: rendered},
        window,
        config(),
        transport,
        monitoring_locations={STATION: LOCATION},
    )
    assert len(transport.requests) == 2
    assert all("statistic_id" not in request.params for request in transport.requests)
    assert result.inventories[0].completeness is InventoryCompleteness.INCOMPLETE
    assert len(result.value) == 1
    assert result.outcomes[0].window.start == start
    assert result.outcomes[0].window.end == stop


@pytest.mark.parametrize("endpoint,statistic", [("daily", None), ("continuous", "00011"), ("dv", "00003")])
def test_coordinates_reject_legacy_or_ambiguous_route_declarations(endpoint, statistic):
    with pytest.raises(ValueError):
        UsgsNwisSourceCoordinates(endpoint, "00060", statistic)


@pytest.mark.parametrize("first_mode", ["reuse", "refresh"])
def test_empty_explicit_known_series_is_cached_without_an_observed_page_definition(tmp_path, first_mode):
    from functools import partial

    from rivretrieve._internal.driver import drive
    from rivretrieve._internal.observations import ObservationProvenance
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.providers.usgs_nwis.parse import parse as parse_page
    from rivretrieve._internal.store import StoreRoot

    class Stages:
        config = config()
        window_declarations = window_declarations()
        fetch = staticmethod(partial(fetch, monitoring_locations={STATION: LOCATION}))
        parse = staticmethod(parse_page)

    scope = SeriesScope(
        provider_ids=("usgs_nwis",),
        station_ids=(STATION,),
        product_ids=(str(PRODUCT),),
        restriction=RestrictionKind.EXPLICIT,
        variants=("ended",),
    )
    request = engine.ObservationRequest(
        ProviderId("usgs_nwis"),
        (STATION,),
        (PRODUCT,),
        engine.RequestedWindow(
            engine.WindowEndpoint.from_datetime(datetime(2000, 1, 1)),
            engine.WindowEndpoint.from_datetime(datetime(2000, 1, 7)),
        ),
        scope=scope,
        known_series=(definition("ended"),),
    )
    transport = Transport(page())
    store = StoreRoot(tmp_path / "store")

    def run(mode):
        return drive(
            request,
            Stages(),
            provenance=ObservationProvenance(source="USGS", provider_id=ProviderId("usgs_nwis")),
            transport=transport,
            cache=mode,
            store=store,
        )

    fresh = run(first_mode)
    assert fresh.canonical_rows.is_empty()
    assert any(outcome.status is OutcomeStatus.EMPTY for outcome in fresh.outcomes)
    reused = run("reuse")
    assert reused.canonical_rows.is_empty()
    assert len(transport.requests) == 1
    assert reused.provenance.served_intervals


@pytest.mark.parametrize("duplicate", [False, True])
def test_all_series_cache_requires_complete_chain_and_retains_every_page(tmp_path, duplicate):
    from functools import partial

    import polars.testing as pt

    from rivretrieve._internal.driver import drive
    from rivretrieve._internal.observations import ObservationProvenance
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.providers.usgs_nwis.parse import parse as parse_page
    from rivretrieve._internal.store import StoreRoot

    class Stages:
        config = config()
        window_declarations = window_declarations()
        fetch = staticmethod(partial(fetch, monitoring_locations={STATION: LOCATION}))
        parse = staticmethod(parse_page)

    request = engine.ObservationRequest(
        ProviderId("usgs_nwis"),
        (STATION,),
        (PRODUCT,),
        engine.RequestedWindow(
            engine.WindowEndpoint.from_datetime(datetime(2000, 1, 1)),
            engine.WindowEndpoint.from_datetime(datetime(2000, 1, 7)),
        ),
        known_series=(definition("ended"),),
    )
    # The driver adds two days on each side before rendering a daily request.
    following = next_url(datetime="1999-12-30/2000-01-09")
    if duplicate:
        conflict = feature()
        conflict["properties"]["value"] = "99.5"
        transport = Transport(page(feature(), feature("beta", "2000-01-02"), next_url=following), page(conflict))
    else:
        transport = Transport(page(feature(), next_url=following), page(feature("beta", "2000-01-02")))
    store = StoreRoot(tmp_path / "store")

    def run():
        return drive(
            request,
            Stages(),
            provenance=ObservationProvenance(source="USGS", provider_id=ProviderId("usgs_nwis")),
            transport=transport,
            cache="reuse",
            store=store,
        )

    fresh = run()
    assert fresh.canonical_rows.height == (1 if duplicate else 2)
    assert len(fresh.source_series) == 3
    if duplicate:
        assert fresh.canonical_rows["series_id"].to_list() == [definition("beta").series_id]
        assert any(
            outcome.series_id == definition("alpha").series_id and outcome.status is OutcomeStatus.UNSUPPORTED
            for outcome in fresh.outcomes
        )
        return
    reused = run()
    pt.assert_frame_equal(reused.canonical_rows, fresh.canonical_rows)
    assert len(transport.requests) == 2


def test_shared_request_attempt_preserves_failure_identity_and_does_not_catch_internal_errors():
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.source_acquisition import attempt_request
    from rivretrieve._internal.transport import HttpMethod, TransportRequest

    request = TransportRequest(HttpMethod.GET, BASE)
    source_failure = TransportFailure(request, TransportFailureReason.HTTP_STATUS, 2, status_code=429)

    class RaisingTransport:
        def __init__(self, error):
            self.error = error

        def send(self, request):
            raise self.error

    assert attempt_request(RaisingTransport(source_failure), request) is source_failure
    with pytest.raises(FatalContractError, match="internal invariant"):
        attempt_request(RaisingTransport(FatalContractError("internal invariant")), request)


def test_conflicting_refresh_retains_held_series_without_marking_it_fresh(tmp_path):
    from dataclasses import replace
    from functools import partial

    import polars as pl
    import polars.testing as pt

    from rivretrieve._internal.driver import drive
    from rivretrieve._internal.observations import ObservationProvenance
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.providers.usgs_nwis.parse import parse as parse_page
    from rivretrieve._internal.store import StoreReader, StoreRoot

    class Stages:
        config = config()
        window_declarations = window_declarations()
        fetch = staticmethod(partial(fetch, monitoring_locations={STATION: LOCATION}))
        parse = staticmethod(parse_page)

    class DatedTransport(Transport):
        def __init__(self, instant, *responses):
            super().__init__(*responses)
            self.instant = instant

        def send(self, request):
            return replace(super().send(request), retrieved_at=self.instant)

    provider = ProviderId("usgs_nwis")
    request = engine.ObservationRequest(
        provider,
        (STATION,),
        (PRODUCT,),
        engine.RequestedWindow(
            engine.WindowEndpoint.from_datetime(datetime(2000, 1, 1)),
            engine.WindowEndpoint.from_datetime(datetime(2000, 1, 7)),
        ),
        known_series=(definition("alpha"), definition("beta")),
    )
    store = StoreRoot(tmp_path / "store")
    old_time = datetime(2026, 9, 20, tzinfo=UTC)
    new_time = datetime(2026, 9, 22, tzinfo=UTC)
    seed_transport = DatedTransport(old_time, page(feature(), feature("beta", "2000-01-02")))

    def run(mode, transport, req=request):
        return drive(
            req,
            Stages(),
            provenance=ObservationProvenance(source="USGS", provider_id=provider),
            transport=transport,
            cache=mode,
            store=store,
        )

    seed = run("reuse", seed_transport)
    alpha_id = definition("alpha").series_id
    beta_id = definition("beta").series_id
    old_alpha = seed.canonical_rows.filter(pl.col("series_id") == alpha_id)
    current_beta = feature("beta", "2000-01-02")
    current_beta["properties"]["value"] = "20.0"
    contradictory_alpha = feature()
    contradictory_alpha["properties"]["value"] = "99.5"
    transport = DatedTransport(
        new_time,
        page(feature(), current_beta, next_url=next_url(datetime="1999-12-30/2000-01-09")),
        page(contradictory_alpha),
    )
    result = run("refresh", transport)
    assert result.canonical_rows.filter(pl.col("series_id") == alpha_id).is_empty()
    assert result.canonical_rows.filter(pl.col("series_id") == beta_id)["value"].to_list() == [20.0 * 0.028316846592]
    assert any(item.series_id == alpha_id and item.status is OutcomeStatus.UNSUPPORTED for item in result.outcomes)
    assert not result.provenance.served_intervals
    status = StoreReader().status(store, provider)
    assert {item.retrieved_at for item in status.coverage if item.series_id == alpha_id} == {old_time}
    explicit = replace(
        request,
        scope=SeriesScope(
            provider_ids=(str(provider),),
            station_ids=(STATION,),
            product_ids=(str(PRODUCT),),
            restriction=RestrictionKind.EXPLICIT,
            variants=("alpha",),
        ),
    )
    no_network = Transport()
    reused = run("reuse", no_network, explicit)
    pt.assert_frame_equal(reused.canonical_rows, old_alpha)
    assert all(item.retrieved_at == old_time for item in reused.provenance.served_intervals)
    assert any(item.series_id == alpha_id and item.status is OutcomeStatus.UNSUPPORTED for item in reused.outcomes)
    assert no_network.requests == []
    # The incomplete ALL snapshot must force a new broad acquisition. Its
    # rejected series can use held rows only with their original vintage.
    retry = DatedTransport(
        new_time,
        page(feature(), current_beta, next_url=next_url(datetime="1999-12-30/2000-01-09")),
        page(contradictory_alpha),
    )
    reacquired = run("reuse", retry)
    assert len(retry.requests) == 2
    pt.assert_frame_equal(reacquired.canonical_rows.filter(pl.col("series_id") == alpha_id), old_alpha)
    assert any(
        item.series_id == alpha_id and item.retrieved_at == old_time for item in reacquired.provenance.served_intervals
    )


def test_paginated_response_facts_replace_metadata_only_facts_and_cover_both_units(tmp_path):
    from functools import partial

    import polars.testing as pt

    from rivretrieve._internal.driver import drive
    from rivretrieve._internal.observations import ObservationProvenance
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.providers.usgs_nwis.parse import parse as parse_page
    from rivretrieve._internal.store import StoreReader, StoreRoot

    class Stages:
        config = config()
        window_declarations = window_declarations()
        fetch = staticmethod(partial(fetch, monitoring_locations={STATION: LOCATION}))
        parse = staticmethod(parse_page)

    metadata = definition("alpha")
    metadata = metadata.model_copy(
        update={"facts": (metadata.facts[0].model_copy(update={"facts_id": "metadata-only"}),)}
    )
    changed = feature("alpha", "2000-01-02")
    changed["properties"]["unit_of_measure"] = "m^3/s"
    native = source_series(
        changed["properties"],
        STATION,
        str(PRODUCT),
        UsgsNwisSourceCoordinates("daily", "00060", "00003"),
        metadata=False,
        monitoring_location_id=LOCATION,
    )
    expected_facts = {definition("alpha").facts[0].facts_id, native.facts[0].facts_id}
    provider = ProviderId("usgs_nwis")
    request = engine.ObservationRequest(
        provider,
        (STATION,),
        (PRODUCT,),
        engine.RequestedWindow(
            engine.WindowEndpoint.from_datetime(datetime(2000, 1, 1)),
            engine.WindowEndpoint.from_datetime(datetime(2000, 1, 7)),
        ),
        known_series=(metadata,),
    )
    transport = Transport(page(feature(), next_url=next_url(datetime="1999-12-30/2000-01-09")), page(changed))
    store = StoreRoot(tmp_path / "store")

    def run():
        return drive(
            request,
            Stages(),
            provenance=ObservationProvenance(source="USGS", provider_id=provider),
            transport=transport,
            cache="reuse",
            store=store,
        )

    result = run()
    assert {fact.facts_id for definition in result.source_series for fact in definition.facts} == expected_facts
    assert set(result.canonical_rows["facts_id"]) == expected_facts
    status = StoreReader().status(store, provider)
    assert {fact for coverage in status.coverage for fact in coverage.facts_ids} == expected_facts
    assert any(
        set(dict(inventory.member_facts)[metadata.series_id]) == expected_facts for inventory in result.inventories
    )
    reused = run()
    pt.assert_frame_equal(reused.canonical_rows, result.canonical_rows)
    assert len(transport.requests) == 2


@pytest.mark.parametrize("mode", ["reuse", "refresh", "bypass"])
@pytest.mark.parametrize("late", ["transport", "malformed_json", "malformed_value", "bad_link"])
def test_late_page_failure_never_overlaps_held_and_fresh_values(tmp_path, mode, late):
    """Authored changed-value failure matrix; not publisher acquisition evidence."""
    from dataclasses import replace
    from functools import partial

    import polars as pl
    import polars.testing as pt

    from rivretrieve._internal.driver import drive
    from rivretrieve._internal.observations import ObservationProvenance, ReceiptAuthorship, ReceiptMode
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.providers.usgs_nwis.parse import parse as parse_page
    from rivretrieve._internal.store import StoreReader, StoreRoot

    class Stages:
        config = config()
        window_declarations = window_declarations()
        fetch = staticmethod(partial(fetch, monitoring_locations={STATION: LOCATION}))
        parse = staticmethod(parse_page)

    provider = ProviderId("usgs_nwis")
    old_at, new_at = datetime(2026, 9, 22, tzinfo=UTC), datetime(2026, 9, 23, tzinfo=UTC)

    class DatedTransport(Transport):
        def send(self, request):
            return replace(super().send(request), retrieved_at=new_at)

    store = StoreRoot(tmp_path / "store")
    known = (definition("alpha"),)
    scope = SeriesScope(
        provider_ids=(provider,),
        station_ids=(STATION,),
        product_ids=(PRODUCT,),
        restriction=RestrictionKind.EXPLICIT,
        variants=("alpha",),
    )
    seed_request = engine.ObservationRequest(
        provider,
        (STATION,),
        (PRODUCT,),
        engine.RequestedWindow(
            engine.WindowEndpoint.from_datetime(datetime(2000, 1, 1)),
            engine.WindowEndpoint.from_datetime(datetime(2000, 1, 1, 23, 59, 59, 999999)),
        ),
        known_series=known,
        scope=scope,
    )
    provenance = ObservationProvenance(source="authored-control", provider_id=provider)
    seed = drive(
        seed_request, Stages(), provenance=provenance, transport=Transport(page(feature())), store=store, cache="reuse"
    )
    before = StoreReader().status(store, provider).manifest
    changed = feature()
    changed["properties"]["value"] = "99.5"
    outside = feature("alpha", "2000-01-03")
    outside["properties"]["value"] = "20"
    sibling = feature("beta", "2000-01-02")
    following = "https://evil.example/items" if late == "bad_link" else next_url(datetime="1999-12-30/2000-01-05")
    first = page(changed, outside, sibling, next_url=following)
    invalid = feature("alpha", "2000-01-02")
    invalid["properties"]["value"] = "not-a-number"
    second = {"transport": "fail", "malformed_json": b"not JSON", "malformed_value": page(invalid), "bad_link": "fail"}[
        late
    ]
    transport = DatedTransport(first, second)
    request = replace(
        seed_request,
        window=engine.RequestedWindow(
            engine.WindowEndpoint.from_datetime(datetime(2000, 1, 1)),
            engine.WindowEndpoint.from_datetime(datetime(2000, 1, 3, 23, 59, 59, 999999)),
        ),
        scope=SeriesScope(provider_ids=(provider,), station_ids=(STATION,), product_ids=(PRODUCT,)),
    )
    result = drive(
        request,
        Stages(),
        provenance=provenance,
        transport=transport,
        store=store,
        cache=mode,
        receipts=ReceiptMode.INCLUDE,
    )
    alpha_id = definition("alpha").series_id
    alpha = result.canonical_rows.filter(pl.col("series_id") == alpha_id).sort("time")
    expected_first = 12.25 if mode == "reuse" else 99.5
    expected = pl.DataFrame(
        {
            "time": [datetime(2000, 1, 1), datetime(2000, 1, 3)],
            "value": [expected_first * 0.028316846592, 20 * 0.028316846592],
        }
    )
    pt.assert_frame_equal(alpha.select("time", "value"), expected)
    assert result.canonical_rows.filter(pl.col("series_id") == definition("beta").series_id).height == 1
    expected_receipts = [first] if late in ("transport", "bad_link") else [first, second]
    assert [
        entry.content for entry in result.receipts.entries if entry.authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD
    ] == expected_receipts
    assert any(item.completeness is InventoryCompleteness.INCOMPLETE for item in result.inventories)
    assert any(
        item.series_id == alpha_id
        and item.status in (OutcomeStatus.FAILED, OutcomeStatus.UNRESOLVED, OutcomeStatus.UNSUPPORTED)
        for item in result.outcomes
    )
    assert any(issue.details.get("series_id") == alpha_id for issue in result.issues)
    after = StoreReader().status(store, provider).manifest
    if late == "malformed_value" and mode != "bypass":
        # The bad identity is isolated; the fully exhausted valid sibling can
        # establish its own fresh interval without refreshing alpha.
        assert tuple(item for item in after.coverage if item.series_id == alpha_id) == before.coverage
        assert {item.retrieved_at for item in after.coverage if item.series_id == definition("beta").series_id} == {
            new_at
        }
    else:
        assert after.coverage == before.coverage
    assert all(item.retrieved_at == old_at for item in after.coverage if item.series_id == alpha_id)
    if mode == "reuse":
        assert result.provenance.served_intervals
        assert all(item.retrieved_at == old_at for item in result.provenance.served_intervals)
    else:
        assert not result.provenance.served_intervals
    assert seed.canonical_rows.height == 1


@pytest.mark.parametrize("alias", ["2024-01-04T01:00:00.000000+00:00", "2024-01-04T02:00:00+01:00"])
@pytest.mark.parametrize("value", ["12.25", "99.5"])
def test_continuous_pages_detect_equivalent_published_instants(alias, value):
    from functools import partial

    from rivretrieve._internal.driver import drive
    from rivretrieve._internal.observations import ObservationProvenance, ReceiptMode
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.providers.usgs_nwis.parse import parse as parse_page

    product = ProductId("discharge_instantaneous")
    first_feature = feature()
    first_feature["properties"].update(statistic_id="00011", time="2024-01-04T01:00:00Z")
    repeated = feature()
    repeated["properties"].update(statistic_id="00011", time=alias, value=value)
    sibling = feature("beta")
    sibling["properties"].update(statistic_id="00011", time="2024-01-04T01:00:00+00:00")
    first_url = BASE.replace("/daily/", "/continuous/")
    params = {
        "f": "json",
        "monitoring_location_id": LOCATION,
        "parameter_code": "00060",
        "datetime": "2024-01-01T00:00:00Z/2024-01-07T00:00:00Z",
        "limit": "10000",
        "cursor": "next",
    }
    first, second = page(first_feature, sibling, next_url=first_url + "?" + urlencode(params)), page(repeated)
    window = engine._make_fetch_window(
        engine.WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
        engine.WindowEndpoint.from_datetime(datetime(2024, 1, 7)),
    )
    result = fetch(
        (STATION,),
        (product,),
        {product: (engine.RenderedWindow("2024-01-01T00:00:00Z", "2024-01-07T00:00:00Z"),)},
        window,
        config(),
        Transport(first, second),
        monitoring_locations={STATION: LOCATION},
    )
    assert [payload.content for payload in result.value] == [first, second]
    assert result.inventories[0].completeness is InventoryCompleteness.INCOMPLETE
    assert result.outcomes[0].status is OutcomeStatus.UNSUPPORTED
    assert "repeats" in result.outcomes[0].reason

    class Stages:
        config = config()
        window_declarations = window_declarations()
        fetch = staticmethod(partial(fetch, monitoring_locations={STATION: LOCATION}))
        parse = staticmethod(parse_page)

    request = engine.ObservationRequest(
        ProviderId("usgs_nwis"),
        (STATION,),
        (product,),
        engine.RequestedWindow(
            engine.WindowEndpoint.from_datetime(datetime(2024, 1, 3)),
            engine.WindowEndpoint.from_datetime(datetime(2024, 1, 5)),
        ),
    )
    assembled = drive(
        request,
        Stages(),
        provenance=ObservationProvenance(source="authored-control", provider_id=ProviderId("usgs_nwis")),
        transport=Transport(first, second),
        receipts=ReceiptMode.INCLUDE,
    )
    beta = next(item for item in assembled.source_series if item.variant == "beta")
    assert assembled.canonical_rows["series_id"].to_list() == [beta.series_id]
    assert [entry.content for entry in assembled.receipts.entries] == [first, second]
