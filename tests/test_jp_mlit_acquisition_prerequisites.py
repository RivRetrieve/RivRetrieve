"""Authored MLIT acquisitions retain their actual prerequisites without source inputs."""

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.issues import IssuePolicyError
from rivretrieve._internal.transport import TransportFailure, TransportFailureReason, TransportResponse

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_STATION = "301011281104010"
_DAT_URL = "http://www1.river.go.jp/dat/dload/download/authored.dat"


def _html(kind, mode):
    title = "日水位年表検索結果" if kind == 3 else "日流量年表検索結果"
    unit = "単位：m" if kind == 3 else "単位：m<sup>3</sup>/s"
    link = '<a href="/dat/dload/download/authored.dat">authored</a>'
    if mode == "empty":
        link = "該当するデータはありません"
    elif mode == "malformed":
        link = ""
    return (
        f"<html><head><meta charset=EUC-JP><title>{title}</title></head>"
        f"<body>{_STATION}<table><tr><td>{unit}</td></tr></table>{link}</body></html>"
    ).encode("euc-jp")


def _dat(kind, year, value):
    title = "日水位年表検索結果" if kind == 3 else "日流量年表検索結果"
    header = ",".join([""] + [cell for day in range(1, 32) for cell in (f"{day}日", "")])
    month = ",".join(["1月"] + [cell for _ in range(31) for cell in (str(value), "")])
    return "\n".join(
        [
            title,
            "水系名,Authored",
            "河川名,Authored",
            "観測所名,Authored",
            f"観測所記号,{_STATION}",
            "#  フラグの意味： $:欠測, -:未登録",
            "# authored control",
            header,
            f"{year}年",
            month,
        ]
    ).encode("shift_jis")


class _AuthoredTransport:
    def __init__(self):
        self.requests = []
        self.responses = []
        self.modes = {}
        self.forbid = False
        self.value = 1.0
        self.context = None

    def send(self, request):
        assert not self.forbid, "cache reuse must not reacquire publisher data"
        self.requests.append(request)
        if request.params:
            self.context = (request.params["KIND"], int(request.params["BGNDATE"][:4]))
        kind, year = self.context
        mode = self.modes.get((kind, year), "success")
        if not request.params and mode == "failed":
            raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 3, status_code=503)
        content = (
            _html(kind, mode)
            if request.params
            else b"authored unsupported DAT"
            if mode == "unsupported"
            else _dat(kind, year, self.value)
        )
        response = TransportResponse(
            content,
            200,
            datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=len(self.requests)),
            "text/html" if request.params else "text/plain",
            request.url,
            request.params or {},
        )
        self.responses.append(response)
        return response


@pytest.fixture
def authored(monkeypatch, tmp_path):
    transport = _AuthoredTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    return transport


def _selection(quantity="stage"):
    found = rr.find(provider="jp_mlit", station=_STATION, quantity=quantity, frequency="daily")
    return rr.pick(found, series_id=tuple(series.series_id for series in found.series))


def _fetch(selection, start="2023-01-03", end="2023-01-04", *, cache="refresh", receipts=False):
    return rr.fetch(selection, start=start, end=end, cache=cache, receipts=receipts, on_issue="ignore")


def _calls(result):
    return list(result.provenance.calls_made)


@pytest.mark.parametrize("receipts", [False, True])
def test_original_html_and_dat_survive_network_free_reuse(authored, receipts):
    selected = _selection()
    fresh = _fetch(selected, receipts=receipts)
    original = _calls(fresh)
    assert len(original) == 2
    assert_frame_equal(
        fresh.data.select("time", "value"),
        pl.DataFrame({"time": [datetime(2023, 1, 3), datetime(2023, 1, 4)], "value": [1.0, 1.0]}),
    )
    assert len({call["call_id"] for call in original}) == 2
    assert original[0]["prerequisite_acquisition_ids"] == ()
    assert original[1]["prerequisite_acquisition_ids"] == (original[0]["call_id"],)
    assert len(fresh.outcomes) == 1
    assert fresh.outcomes[0].status == "success"
    assert [call["url"] for call in original] == [request.url for request in authored.requests]
    assert original[1]["url"] == _DAT_URL
    assert [call["request_parameters"] for call in original] == [
        {"KIND": 3, "ID": _STATION, "BGNDATE": "20230101", "ENDDATE": "20231231", "KAWABOU": "NO"},
        {},
    ]
    assert [call["retrieved_at"] for call in original] == [
        datetime(2026, 1, 1, 0, 0, second, tzinfo=UTC) for second in (1, 2)
    ]
    assert [entry.content for entry in fresh.receipts.entries] == (
        [response.content for response in authored.responses] if receipts else []
    )
    authored.forbid = True
    held = _fetch(selected, cache="reuse", receipts=receipts)
    assert_frame_equal(fresh.data, held.data)
    assert len(authored.requests) == 2
    assert len(held.receipts.entries) == (1 if receipts else 0)
    assert _calls(held) == original
    assert list(rr.cache_status("jp_mlit").manifest.source_calls) == original


@pytest.mark.parametrize("mode", ["failed", "unsupported"])
def test_dat_failure_keeps_html_without_covering_failed_interval(authored, mode):
    selected = _selection()
    authored.modes[(3, 2022)] = mode
    result = _fetch(selected, "2022-01-03", "2023-01-04", receipts=True)
    assert set(result.data["time"].dt.year()) == {2023}
    assert sorted(outcome.status.value for outcome in result.outcomes) == sorted([mode, "success"])
    bad = next(outcome for outcome in result.outcomes if outcome.status == mode)
    assert bad.reason
    assert bad.calls
    original = _calls(result)
    assert len(original) == 4
    assert [call["url"] for call in original] == [request.url for request in authored.requests]
    assert original[1]["prerequisite_acquisition_ids"] == (original[0]["call_id"],)
    if mode == "failed":
        assert original[1]["status_code"] == 503
        assert original[1]["attempts"] == 3
        assert original[1]["failure_reason"] == "http_status"
        assert original[1]["retrieved_at"] == {"status": "unknown", "reason": "unknown"}
    else:
        assert original[1]["retrieved_at"] == datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC)
    assert len(result.receipts.entries) == (3 if mode == "failed" else 4)
    status = rr.cache_status("jp_mlit")
    assert status.coverage
    assert all(coverage.interval.start.year == 2023 for coverage in status.coverage)
    assert list(status.manifest.source_calls) == original
    saved_bad = next(outcome for outcome in status.manifest.outcomes if outcome.status == mode)
    assert saved_bad.outcome_id == bad.outcome_id
    assert saved_bad.reason == bad.reason
    assert saved_bad.calls == bad.calls
    authored.forbid = True
    healthy = _fetch(selected, cache="reuse")
    assert healthy.data.height == 2
    assert _calls(healthy) == original[2:]
    authored.forbid = False
    authored.modes.clear()
    repaired = _fetch(selected, "2022-01-03", "2022-01-04", cache="reuse")
    assert repaired.data.height == 2
    assert len(authored.requests) == 6
    assert all(outcome.status != mode for outcome in repaired.outcomes)


@pytest.mark.parametrize("mode", ["empty", "malformed"])
def test_html_only_outcomes_keep_their_coverage_semantics(authored, mode):
    selected = _selection()
    authored.modes[(3, 2023)] = mode
    first = _fetch(selected, receipts=True)
    expected = "empty" if mode == "empty" else "unsupported"
    assert first.data.is_empty()
    assert [outcome.status.value for outcome in first.outcomes] == [expected]
    assert len(authored.requests) == 1
    assert len(first.receipts.entries) == 1
    assert first.receipts.entries[0].content == _html(3, mode)
    assert len(rr.cache_status("jp_mlit").coverage) == (1 if mode == "empty" else 0)
    authored.forbid = mode == "empty"
    second = _fetch(selected, cache="reuse")
    assert second.data.is_empty()
    assert [outcome.status.value for outcome in second.outcomes] == [expected]
    assert len(authored.requests) == (1 if mode == "empty" else 2)
    assert all(request.params for request in authored.requests)


def test_full_refresh_retires_obsolete_chain(authored):
    selected = _selection()
    first = _fetch(selected)
    authored.value = 2.0
    replacement = _fetch(selected)
    assert replacement.data["value"].to_list() == [2.0, 2.0]
    assert _calls(replacement) != _calls(first)
    assert list(rr.cache_status("jp_mlit").manifest.source_calls) == _calls(replacement)
    authored.forbid = True
    held = _fetch(selected, cache="reuse")
    assert_frame_equal(held.data, replacement.data)
    assert _calls(held) == _calls(replacement)


def test_partial_refresh_keeps_surviving_chain_but_excludes_unrelated_calls(authored):
    selected = _selection()
    old = _fetch(selected, "2023-01-03", "2023-01-06")
    unrelated_interval = _fetch(selected, "2024-01-03", "2024-01-04")
    unrelated_product = _fetch(_selection("discharge"))
    authored.value = 2.0
    replacement = _fetch(selected, "2023-01-05", "2023-01-06")
    authored.forbid = True
    held = _fetch(selected, "2023-01-03", "2023-01-06", cache="reuse")
    assert held.data["value"].to_list() == [1.0, 1.0, 2.0, 2.0]
    assert _calls(held) == _calls(old) + _calls(replacement)
    # Every DAT deliberately has the same URL. It is not a dependency key.
    assert all(
        call["url"] == _DAT_URL
        for result in (old, unrelated_interval, unrelated_product, replacement)
        for call in _calls(result)
        if not call["request_parameters"]
    )
    saved = list(rr.cache_status("jp_mlit").manifest.source_calls)
    assert saved == _calls(old) + _calls(unrelated_interval) + _calls(unrelated_product) + _calls(replacement)


@pytest.mark.parametrize("policy", ["warn", "raise"])
@pytest.mark.parametrize("mode", ["failed", "unsupported"])
def test_dat_diagnoses_obey_public_issue_policy(authored, policy, mode):
    authored.modes[(3, 2023)] = mode
    context = pytest.warns(RuntimeWarning) if policy == "warn" else pytest.raises(IssuePolicyError)
    with context:
        rr.fetch(_selection(), start="2023-01-03", end="2023-01-04", cache="refresh", on_issue=policy)
    assert len(authored.requests) == 2


@pytest.mark.parametrize("cache", ["reuse", "refresh"])
def test_old_cache_requires_explicit_clear_before_new_acquisition(authored, cache):
    import json

    from rivretrieve._internal.store.validation import ObservationStoreRefusedError

    selected = _selection()
    fresh = _fetch(selected)
    status = rr.cache_status("jp_mlit")
    path = status.store / "manifest.json"
    document = json.loads(path.read_text())
    # Reproduce the old writer: only DAT survived, with no dependency declaration.
    document["source_calls"] = [call for call in document["source_calls"] if call["url"] == _DAT_URL]
    for call in document["source_calls"]:
        call.pop("prerequisite_acquisition_ids")
    path.write_text(json.dumps(document))
    before = {file.relative_to(status.store): file.read_bytes() for file in status.store.rglob("*") if file.is_file()}
    authored.forbid = True
    with pytest.raises(ObservationStoreRefusedError, match="jp_mlit cache lacks required acquisition evidence"):
        _fetch(selected, cache=cache)
    assert len(authored.requests) == 2
    assert before == {
        file.relative_to(status.store): file.read_bytes() for file in status.store.rglob("*") if file.is_file()
    }
    rr.clear_cache("jp_mlit")
    authored.forbid = False
    refreshed = _fetch(selected)
    assert_frame_equal(fresh.data, refreshed.data)
    assert [call["retrieved_at"] for call in _calls(refreshed)] == [
        datetime(2026, 1, 1, 0, 0, second, tzinfo=UTC) for second in (3, 4)
    ]
    assert not {call["call_id"] for call in _calls(fresh)}.intersection(call["call_id"] for call in _calls(refreshed))
    authored.forbid = True
    held = _fetch(selected, cache="reuse")
    assert _calls(held) == _calls(refreshed)


@pytest.mark.parametrize("defect", ["conflicting-identity", "unknown-prerequisite"])
def test_invalid_acquisition_dependencies_are_fatal_before_parse(authored, monkeypatch, tmp_path, defect):
    from dataclasses import replace

    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.providers.jp_mlit.declaration import declaration

    stages = declaration.observations.stages
    acquire = stages.fetch

    def invalid_acquisition(*args, **kwargs):
        acquired = acquire(*args, **kwargs)
        html, dat = acquired.value
        if defect == "conflicting-identity":
            # Same acquisition identity cannot declare two different support chains.
            payloads = (html, dat, replace(dat, prerequisite_acquisition_ids=()))
        else:
            payloads = (html, replace(dat, prerequisite_acquisition_ids=("not-acquired",)))
        return replace(acquired, value=payloads)

    def forbidden_parse(*args, **kwargs):
        pytest.fail("invalid dependencies must fail before parsing")

    monkeypatch.setattr(stages, "fetch", staticmethod(invalid_acquisition))
    monkeypatch.setattr(stages, "parse", staticmethod(forbidden_parse))
    with pytest.raises(FatalContractError, match="[Pp]rerequisite|[Aa]cquisition"):
        rr.fetch(_selection(), start="2023-01-03", end="2023-01-04", cache="bypass", on_issue="ignore")
    assert len(authored.requests) == 2
    assert not list(tmp_path.rglob("manifest.json"))
