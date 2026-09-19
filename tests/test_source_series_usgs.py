from datetime import datetime
from hashlib import sha256
from pathlib import Path

import pytest

from rivretrieve._internal.engine import (
    Payload,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.usgs_nwis.config import config
from rivretrieve._internal.providers.usgs_nwis.parse import parse


def test_original_two_method_response_retains_both_published_identities():
    content = Path("tests/test_data/usgs_nwis_02196000_multi_method.json").read_bytes()
    assert len(content) == 1702244
    assert sha256(content).hexdigest() == "92c43227ececed5373bc92abc4cbb19035dfc4b0ec7db736f2b4e443d8bf1275"
    unknown = UnknownOriginFact()
    payload = Payload(
        SourceCoordinates(object()),
        (("02196000", ProductId("discharge_daily_mean")),),
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(1979, 12, 30)), WindowEndpoint.from_datetime(datetime(2026, 1, 2))
        ),
        content,
        SourceCallOrigin(unknown, unknown, unknown, unknown, unknown, unknown, unknown),
        (),
    )
    parsed = parse(payload, config())
    assert {series.identity.published_id for series in parsed.series} == {"126801", "126805"}
    assert parsed.rows.height == 15388 + 7989
    assert parsed.rows.group_by("series_id").len()["len"].sort().to_list() == [7989, 15388]


def _parse_document(document):
    import json

    unknown = UnknownOriginFact()
    payload = Payload(
        SourceCoordinates(object()),
        (("02196000", ProductId("discharge_daily_mean")),),
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(1983, 11, 16)), WindowEndpoint.from_datetime(datetime(1983, 11, 17))
        ),
        json.dumps(document).encode(),
        SourceCallOrigin(unknown, unknown, unknown, unknown, unknown, unknown, unknown),
        (),
    )
    return parse(payload, config())


def _small_document():
    import json

    doc = json.loads(Path("tests/test_data/usgs_nwis_02196000_multi_method.json").read_bytes())
    for block in doc["value"]["timeSeries"][0]["values"]:
        block["value"] = block["value"][:2]
    return doc


def test_zero_method_and_null_are_preserved():
    doc = _small_document()
    block = doc["value"]["timeSeries"][0]["values"][0]
    block["method"][0]["methodID"] = 0
    block["value"][0]["value"] = "-999999"
    parsed = _parse_document(doc)
    assert {s.identity.published_id for s in parsed.series} == {"0", "126805"}
    assert parsed.rows.height == 4
    assert parsed.rows["value"].null_count() == 1


def test_ambiguous_block_does_not_discard_independent_method():
    doc = _small_document()
    doc["value"]["timeSeries"][0]["values"][0]["method"] = []
    parsed = _parse_document(doc)
    assert parsed.rows.height == 2
    assert any(o.status == "unsupported" for o in parsed.outcomes)
    assert parsed.issues


def test_per_value_association_is_not_first_method_selection():
    doc = _small_document()
    blocks = doc["value"]["timeSeries"][0]["values"]
    blocks[0]["method"] += blocks[1]["method"]
    blocks[0]["value"][0]["methodID"] = 126801
    blocks[0]["value"][1]["methodID"] = 126805
    del blocks[1:]
    parsed = _parse_document(doc)
    assert parsed.rows.height == 2
    assert parsed.rows["series_id"].n_unique() == 2


def test_contradictory_unit_is_unsupported_without_numeric_output():
    doc = _small_document()
    doc["value"]["timeSeries"][0]["variable"]["unit"]["unitCode"] = "ft"
    parsed = _parse_document(doc)
    assert parsed.rows.is_empty()
    assert len(parsed.series) == 2
    assert all(o.status == "unsupported" for o in parsed.outcomes)


def test_partial_ambiguous_association_never_establishes_successful_coverage():
    doc = _small_document()
    blocks = doc["value"]["timeSeries"][0]["values"]
    blocks[0]["method"] += blocks[1]["method"]
    blocks[0]["value"][0]["methodID"] = 126801
    del blocks[1:]
    parsed = _parse_document(doc)
    assert parsed.rows.height == 1
    assert not any(o.status in ("success", "empty") for o in parsed.outcomes)


def test_empty_response_does_not_imply_nonexistent_unidentified_series():
    doc = _small_document()
    doc["value"]["timeSeries"] = []
    parsed = _parse_document(doc)
    assert parsed.rows.is_empty()
    assert parsed.outcomes
    assert parsed.outcomes[0].status == "unresolved"


def test_unreadable_source_container_is_recoverable():
    parsed = _parse_document({"value": []})
    assert parsed.rows.is_empty()
    assert parsed.outcomes[0].status == "unsupported"


def test_malformed_inventory_notes_do_not_discard_method_rows():
    doc = _small_document()
    doc["value"]["queryInfo"]["note"] = None
    parsed = _parse_document(doc)
    assert parsed.rows.height == 4
    assert parsed.inventories[0].completeness == "incomplete"


def test_unrecognised_unit_retains_exact_published_spelling():
    doc = _small_document()
    doc["value"]["timeSeries"][0]["variable"]["unit"]["unitCode"] = "CFS-unknown"
    parsed = _parse_document(doc)
    assert parsed.rows.is_empty()
    assert {s.facts[0].source_unit.value for s in parsed.series} == {"CFS-unknown"}


def test_public_recorded_singleton_preserves_identity_conversion_and_exact_receipt(monkeypatch):
    import pytest

    import rivretrieve as rr
    import rivretrieve._internal.discovery as discovery
    from rivretrieve._internal.recordings import ReplayTransport, read_recording

    recording = read_recording(
        Path("tests/test_data/usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json")
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    result = rr.fetch(selection, start="2023-01-01", end="2023-01-01", cache="bypass", receipts=True, on_issue="ignore")
    import json

    method = json.loads(recording.content)["value"]["timeSeries"][0]["values"][0]["method"][0]
    assert len(result.source_series) == 1
    assert result.source_series[0].identity.published_id == str(method["methodID"])
    assert result.source_series[0].identity.description == method["methodDescription"]
    assert result.data.height == 1
    assert result.data["value"][0] == pytest.approx(373000 * 0.028316846592)
    assert result.data["time_zone"][0] == "unknown"
    assert result.data["source_unit"][0] == "ft3/s"
    assert result.data["unit"][0] == "m3/s"
    assert result.receipts.entries[0].content == recording.content
    assert result.receipts.entries[0].origin.retrieved_at == recording.retrieved_at


def test_explicit_request_retains_complete_acquired_inventory_for_driver_filtering():
    import json
    from dataclasses import replace

    from rivretrieve._internal.source_series import RestrictionKind, SeriesScope

    unknown = UnknownOriginFact()
    payload = Payload(
        SourceCoordinates(object()),
        (("02196000", ProductId("discharge_daily_mean")),),
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(1983, 11, 16)), WindowEndpoint.from_datetime(datetime(1983, 11, 17))
        ),
        json.dumps(_small_document()).encode(),
        SourceCallOrigin(unknown, unknown, unknown, unknown, unknown, unknown, unknown),
        (),
    )
    payload = replace(payload, scope=SeriesScope(restriction=RestrictionKind.EXPLICIT, variants=("126801",)))
    parsed = parse(payload, config())
    assert {s.identity.published_id for s in parsed.series} == {"126801", "126805"}
    assert parsed.inventories[0].scope.restriction == "all"
    assert set(parsed.inventories[0].members) == {s.series_id for s in parsed.series}


def test_changed_response_has_distinct_outcome_identity():
    doc = _small_document()
    before = _parse_document(doc)
    doc["value"]["timeSeries"][0]["values"][0]["value"][0]["value"] = "42"
    after = _parse_document(doc)
    assert {o.outcome_id for o in before.outcomes}.isdisjoint({o.outcome_id for o in after.outcomes})


def test_per_value_method_code_association_uses_published_mapping():
    doc = _small_document()
    blocks = doc["value"]["timeSeries"][0]["values"]
    blocks[0]["method"][0]["methodCode"] = "sensor-A"
    blocks[1]["method"][0]["methodCode"] = "sensor-B"
    blocks[0]["method"] += blocks[1]["method"]
    blocks[0]["value"][0]["methodCode"] = "sensor-A"
    blocks[0]["value"][1]["methodCode"] = "sensor-B"
    del blocks[1:]
    parsed = _parse_document(doc)
    assert parsed.rows.height == 2
    assert parsed.rows["series_id"].n_unique() == 2
    assert not parsed.issues


def test_published_method_code_without_optional_id_is_not_fabricated():
    doc = _small_document()
    block = doc["value"]["timeSeries"][0]["values"][0]
    block["method"][0].pop("methodID")
    block["method"][0]["methodCode"] = "published-code"
    parsed = _parse_document(doc)
    assert parsed.rows.height == 4
    code_series = next(s for s in parsed.series if s.identity.published_id == "published-code")
    assert code_series.identity.namespace == "methodCode"


def test_internal_model_validation_failure_is_not_a_source_issue(monkeypatch):
    import importlib

    import pytest

    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.source_series import PhysicalFacts

    parser = importlib.import_module("rivretrieve._internal.providers.usgs_nwis.parse")

    def invalid_internal_facts(*args):
        return PhysicalFacts(facts_id="")

    monkeypatch.setattr(parser, "_facts", invalid_internal_facts)
    with pytest.raises(FatalContractError):
        _parse_document(_small_document())


def _original_capture_public_access(monkeypatch, tmp_path):
    """Compose the retained parse-boundary body without inventing its lost HTTP envelope.

    Only acquisition is authored. Selection, parser, driver, conversion, storage,
    and exports are the real implementation. Unretained historical receipt facts
    stay unknown; the known URL and request parameters come from the sidecar.
    """
    import json

    import rivretrieve as rr
    from rivretrieve._internal.engine import WithIssues
    from rivretrieve._internal.providers.usgs_nwis.declaration import declaration
    from rivretrieve._internal.transport import HttpMethod, TransportFailure, TransportFailureReason, TransportRequest

    content = Path(__file__).with_name("test_data").joinpath("usgs_nwis_02196000_multi_method.json").read_bytes()
    sidecar = json.loads(
        Path(__file__).with_name("test_data").joinpath("usgs_nwis_02196000_multi_method.provenance.json").read_text()
    )
    calls = []
    state = {"fail": False}
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "native-cache"))

    def acquire(
        stations, products, rendered_windows, fetch_window, provider_config, transport, *, scope=None, known_series=()
    ):
        assert stations == ("02196000",)
        assert products == ("discharge_daily_mean",)
        (rendered,) = rendered_windows[products[0]]
        assert (rendered.start, rendered.stop) == ("1979-12-30", "2026-01-02")
        calls.append(scope)
        if state["fail"]:
            # A separately authored failure exercises isolation, not the historical response's unknown status.
            raise TransportFailure(
                TransportRequest(
                    HttpMethod.GET, "https://waterservices.usgs.gov/nwis/dv/", params={"sites": "02196000"}
                ),
                TransportFailureReason.TERMINAL_SENDER_FAILURE,
                1,
            )
        unknown = UnknownOriginFact()
        return WithIssues(
            (
                Payload(
                    provider_config.products[products[0]].coordinates,
                    ((stations[0], products[0]),),
                    fetch_window,
                    content,
                    SourceCallOrigin(
                        sidecar["url"], sidecar["request_parameters"], unknown, unknown, unknown, unknown, unknown
                    ),
                    (),
                    scope=scope,
                    known_series=known_series,
                ),
            )
        )

    monkeypatch.setattr(declaration.observations.stages, "fetch", staticmethod(acquire))
    selection = rr.find(
        provider="usgs_nwis", station="02196000", quantity="discharge", frequency="daily", statistic="mean"
    )
    return selection, content, calls, state


def test_original_capture_public_subset_then_all_reacquires_native_series_and_roundtrips(monkeypatch, tmp_path):
    import json
    from io import BytesIO

    import polars as pl
    import polars.testing as pl_testing

    import rivretrieve as rr

    selection, content, calls, _ = _original_capture_public_access(monkeypatch, tmp_path)
    subset = rr.pick(selection, variant="126801", on_issue="ignore")
    subset_result = rr.fetch(
        subset, start="1980-01-01", end="2025-12-31", cache="reuse", receipts=True, on_issue="ignore"
    )
    assert subset_result.data.height == 15386  # Two captured January 2026 labels are clipped.
    assert len(calls) == 1
    all_result = rr.fetch(
        selection, start="1980-01-01", end="2025-12-31", cache="reuse", receipts=True, on_issue="ignore"
    )
    assert len(calls) == 2, "Subset coverage must not satisfy the all-series request"
    assert all_result.data.height == 23375
    assert {s.identity.published_id for s in all_result.source_series} == {"126801", "126805"}
    assert all_result.data.group_by("series_id").len()["len"].sort().to_list() == [7989, 15386]
    assert all_result.receipts.entries[0].content == content
    assert isinstance(all_result.receipts.entries[0].origin.retrieved_at, UnknownOriginFact)
    assert isinstance(all_result.receipts.entries[0].origin.status_code, UnknownOriginFact)
    assert all(i.acquired_at is None for i in all_result.inventories if i.origin == "response")
    assert all(o.retrieved_at is None for o in all_result.outcomes)

    cached = rr.fetch(selection, start="1980-01-01", end="2025-12-31", cache="reuse", receipts=True, on_issue="ignore")
    assert len(calls) == 2
    pl_testing.assert_frame_equal(cached.data, all_result.data)
    (excerpt,) = cached.receipts.entries
    native = pl.read_parquet(BytesIO(excerpt.content))
    assert native.height == 23375
    assert native["series_id"].n_unique() == 2
    native_parser = _parse_document(json.loads(content)).rows
    assert native_parser.height == 23377
    native_parser = native_parser.filter(pl.col("time") <= datetime(2025, 12, 31, 23, 59, 59))
    pl_testing.assert_frame_equal(
        native.rename({"product": "product_id"}).select(native_parser.columns).sort("series_id", "time"),
        native_parser.sort("series_id", "time"),
    )
    narrowed = rr.pick(all_result, variant="126805", on_issue="ignore")
    assert narrowed.data.height == 7989
    assert narrowed.scope == all_result.scope
    assert narrowed.receipts.entries[0].content == content
    restored = rr.from_bundle(rr.to_bundle(narrowed))
    pl_testing.assert_frame_equal(restored.data, narrowed.data)
    assert restored.source_series == narrowed.source_series
    assert restored.outcomes == narrowed.outcomes
    assert restored.receipts.entries[0].content == content


def test_original_capture_failed_refresh_retains_native_siblings_and_identified_failure(monkeypatch, tmp_path):
    import polars.testing as pl_testing

    import rivretrieve as rr

    selection, _, calls, state = _original_capture_public_access(monkeypatch, tmp_path)
    initial = rr.fetch(selection, start="1980-01-01", end="2025-12-31", cache="reuse", on_issue="ignore")
    concrete = rr.pick(selection, variant="126805", on_issue="ignore")
    failed_id = next(s.series_id for s in initial.source_series if s.identity.published_id == "126805")
    state["fail"] = True
    failed = rr.fetch(concrete, start="1980-01-01", end="2025-12-31", cache="refresh", on_issue="ignore")
    assert failed.data.is_empty()
    assert failed.issues
    cached = rr.fetch(selection, start="1980-01-01", end="2025-12-31", cache="reuse", on_issue="ignore")
    assert len(calls) == 2
    pl_testing.assert_frame_equal(cached.data, initial.data)
    assert any(o.status == "failed" for o in cached.outcomes)
    assert any(o.status == "failed" and o.series_id == failed_id for o in failed.outcomes)


def test_original_capture_through_actual_fetch_verified_transport_and_public_cache(monkeypatch, tmp_path):
    """Replay exact bytes and known request, with an explicitly authored HTTP envelope.

    The original historical status and retrieval time were not retained. HTTP 200
    and replay_time below describe this test's transport execution only. They are
    not evidence about the original capture. The companion parse-boundary tests
    retain the historical unknowns without inventing an HTTP envelope.
    """
    import json
    from datetime import UTC

    import polars.testing as pl_testing

    import rivretrieve as rr
    import rivretrieve._internal.discovery as discovery
    from rivretrieve._internal.transport import HttpMethod, TransportResponse

    directory = Path(__file__).with_name("test_data")
    content = (directory / "usgs_nwis_02196000_multi_method.json").read_bytes()
    historical = json.loads((directory / "usgs_nwis_02196000_multi_method.provenance.json").read_text())
    assert historical["status_code"] == {"state": "not_established"}
    assert historical["retrieved_at"] == {"state": "not_established"}
    replay_time = datetime(2026, 9, 20, tzinfo=UTC)  # Authored replay clock, not historical acquisition.
    requests = []

    class ExactBodyTransport:
        def send(self, request):
            assert request.method is HttpMethod.GET
            assert request.url == historical["url"]
            assert dict(request.params) == historical["request_parameters"]
            requests.append(request)
            return TransportResponse(content, 200, replay_time, None, request.url, request.params)

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "native-cache"))
    monkeypatch.setattr(discovery, "HttpClient", ExactBodyTransport)
    selection = rr.find(
        provider="usgs_nwis", station="02196000", quantity="discharge", frequency="daily", statistic="mean"
    )
    subset = rr.pick(selection, variant="126801", on_issue="ignore")
    first = rr.fetch(subset, start="1980-01-01", end="2025-12-31", cache="reuse", receipts=True, on_issue="ignore")
    assert first.data.height == 15386
    result = rr.fetch(selection, start="1980-01-01", end="2025-12-31", cache="reuse", receipts=True, on_issue="ignore")
    assert len(requests) == 2
    assert result.data.height == 23375
    assert {s.identity.published_id for s in result.source_series} == {"126801", "126805"}
    (receipt,) = result.receipts.entries
    assert receipt.content is content
    assert receipt.origin.url == historical["url"]
    assert dict(receipt.origin.request_parameters) == historical["request_parameters"]
    assert receipt.origin.status_code == 200  # Authored replay response, never historical status.
    assert receipt.origin.retrieved_at == replay_time
    cached = rr.fetch(selection, start="1980-01-01", end="2025-12-31", cache="reuse", on_issue="ignore")
    assert len(requests) == 2
    pl_testing.assert_frame_equal(cached.data, result.data)
    restored = rr.from_bundle(rr.to_bundle(rr.pick(result, variant="126805", on_issue="ignore")))
    assert restored.data.height == 7989
    assert restored.receipts.entries[0].content == content


def test_public_recorded_instantaneous_predicates_match_catalogue_and_response(monkeypatch, tmp_path):
    import rivretrieve as rr
    import rivretrieve._internal.discovery as discovery
    from rivretrieve._internal.recordings import ReplayTransport, read_recording

    recording = read_recording(
        Path(__file__).with_name("test_data") / "usgs_nwis_07374000_iv_00060_2023-01-01.recording.json"
    )
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
    selection = rr.find(
        provider="usgs_nwis",
        station="07374000",
        quantity="discharge",
        statistic="instantaneous",
        temporal_support="instantaneous",
    )
    assert selection.series
    result = rr.fetch(selection, start="2023-01-01", end="2023-01-01", receipts=True, on_issue="raise")
    assert not result.data.is_empty()
    assert {fact.statistic.value for series in result.source_series for fact in series.facts} == {"instantaneous"}
    assert all(fact.frequency.value is None for series in result.source_series for fact in series.facts)
    assert {fact.temporal_support.value for series in result.source_series for fact in series.facts} == {
        "instantaneous"
    }
    assert result.receipts.entries[0].content == recording.content


def test_public_recorded_daily_interval_support_does_not_require_known_day_definition(monkeypatch):
    import rivretrieve as rr
    import rivretrieve._internal.discovery as discovery
    from rivretrieve._internal.recordings import ReplayTransport, read_recording

    recording = read_recording(
        Path(__file__).with_name("test_data") / "usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json"
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
    selection = rr.find(
        provider="usgs_nwis",
        station="07374000",
        quantity="discharge",
        frequency="daily",
        statistic="mean",
        temporal_support="interval",
    )
    result = rr.fetch(selection, start="2023-01-01", end="2023-01-01", on_issue="raise")
    assert result.data.height == 1
    assert all(f.day_definition.value is None for s in result.source_series for f in s.facts)


def _authored_repeated_method_document(case):
    """Authored structural control derived from a real recording, not a new capture."""
    import json
    from copy import deepcopy

    from rivretrieve._internal.recordings import read_recording

    recording = read_recording(
        Path(__file__).with_name("test_data") / "usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json"
    )
    document = json.loads(recording.content)
    blocks = document["value"]["timeSeries"][0]["values"]
    original = deepcopy(blocks[0])
    blocks.append(deepcopy(original))
    if case == "overlapping":
        blocks[0]["value"] = original["value"][:3]
        blocks[1]["value"] = original["value"][2:]
        blocks[1]["value"][0]["value"] = "1"  # Conflict remains a distinct native observation.
    elif case == "disjoint":
        blocks[0]["value"] = original["value"][:2]
        blocks[1]["value"] = original["value"][2:]
    elif case == "unsupported":
        blocks[1]["value"][2]["value"] = "authored invalid number"
    return recording, document


def _authored_method_transport(monkeypatch, tmp_path, case):
    import json

    import rivretrieve as rr
    import rivretrieve._internal.discovery as discovery
    from rivretrieve._internal.transport import TransportResponse

    recording, document = _authored_repeated_method_document(case)
    content = json.dumps(document).encode()
    sent = []

    class AuthoredTransport:
        def send(self, request):
            assert request.url == recording.request.url
            assert dict(request.params) == dict(recording.request.parameters)
            sent.append(request)
            return TransportResponse(
                content, 200, recording.retrieved_at, recording.content_type, request.url, request.params
            )

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "HttpClient", AuthoredTransport)
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    return selection, document, sent


@pytest.mark.parametrize("case", ["repeated", "overlapping", "disjoint"])
def test_authored_same_method_blocks_have_one_coverage_owner_and_preserve_multiplicity(monkeypatch, tmp_path, case):
    import polars as pl
    import polars.testing as pl_testing

    import rivretrieve as rr

    selection, document, sent = _authored_method_transport(monkeypatch, tmp_path, case)
    expected_values = [
        float(entry["value"]) * 0.028316846592
        for block in document["value"]["timeSeries"][0]["values"]
        for entry in block["value"]
        if entry["dateTime"].startswith("2023-01-01T")
    ]

    def fetch(mode):
        return rr.fetch(selection, start="2023-01-01", end="2023-01-01", cache=mode, receipts=True, on_issue="raise")

    bypass = fetch("bypass")
    expected = pl.DataFrame({"value": expected_values})
    pl_testing.assert_frame_equal(bypass.data.select("value").sort("value"), expected.sort("value"))
    first = fetch("reuse")
    second = fetch("reuse")
    assert len(sent) == 2
    for result in (first, second, fetch("refresh"), fetch("reuse")):
        pl_testing.assert_frame_equal(result.data, bypass.data)
        assert len(result.outcomes) == 1
        assert result.outcomes[0].status == "success"
    assert len(sent) == 3


def test_authored_unsupported_same_method_block_cannot_claim_successful_full_coverage(monkeypatch, tmp_path):
    import rivretrieve as rr

    selection, _, sent = _authored_method_transport(monkeypatch, tmp_path, "unsupported")
    first = rr.fetch(selection, start="2023-01-01", end="2023-01-01", cache="reuse", on_issue="ignore")
    assert first.data.height == 1  # Representable rows from the other block remain visible.
    assert len(first.outcomes) == 1
    assert first.outcomes[0].status == "unsupported"
    again = rr.fetch(selection, start="2023-01-01", end="2023-01-01", cache="reuse", on_issue="ignore")
    assert len(sent) == 2, "Unsupported partial window cannot become successful cached coverage"
    assert again.data.height == 1


def test_repeated_physical_fact_segment_keeps_all_definitions_and_owns_only_its_rows():
    import json
    from copy import deepcopy

    from rivretrieve._internal.engine import Payload
    from rivretrieve._internal.recordings import read_recording

    recording = read_recording(
        Path(__file__).with_name("test_data") / "usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json"
    )
    document = json.loads(recording.content)
    blocks = document["value"]["timeSeries"]
    blocks.extend([deepcopy(blocks[0]), deepcopy(blocks[0])])
    blocks[1]["variable"]["unit"]["unitCode"] = "m3/s"
    unknown = UnknownOriginFact()
    payload = Payload(
        SourceCoordinates(object()),
        (("07374000", ProductId("discharge_daily_mean")),),
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2022, 12, 30)), WindowEndpoint.from_datetime(datetime(2023, 1, 3))
        ),
        json.dumps(document).encode(),
        SourceCallOrigin(unknown, unknown, unknown, unknown, unknown, unknown, unknown),
        (),
    )
    parsed = parse(payload, config())
    assert parsed.rows.height == 15
    assert len(parsed.series) == 1
    assert len(parsed.series[0].facts) == 2
    assert len(parsed.outcomes) == 2
    assert all(len(o.facts_ids) == 1 for o in parsed.outcomes)
    assert len({o.outcome_id for o in parsed.outcomes}) == 2
