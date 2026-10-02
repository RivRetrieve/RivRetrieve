"""Offline HTML-boundary regressions; derivatives are not publisher captures."""

import re
from dataclasses import replace

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.issues import IssuePolicyError
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from tests.test_jp_mlit_observations import _recording_paths

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_STATION = "301011281104010"


def _negative_derivative(content: bytes, defect: str) -> bytes:
    text = content.decode("euc-jp")
    if defect == "invalid-encoding":
        return content + b"\xff"
    if defect == "missing-charset":
        text = text.replace("charset=EUC-JP", "charset=UTF-8")
    elif defect == "wrong-station":
        text = text.replace(_STATION, "999999999999999")
    elif defect == "wrong-title":
        text = text.replace("時刻水位月表検索結果", "日水位年表検索結果")
    elif defect == "wrong-unit":
        text = text.replace("単位：m", "単位：cm")
    elif defect in ("missing-link", "no-data-marker", "no-data-wrong-unit", "no-data-without-unit"):
        text = re.sub(r'<A HREF="[^"]+\.dat"[^>]*>.*?</A>', "", text, flags=re.I | re.S)
        if defect.startswith("no-data"):
            text += "該当するデータはありません"
        if defect == "no-data-wrong-unit":
            text = text.replace("単位：m", "単位：cm")
        elif defect == "no-data-without-unit":
            text = text.replace("単位：m", "")
    elif defect == "off-host-link":
        text = text.replace("/dat/dload/download/", "https://example.invalid/")
    elif defect == "duplicate-link":
        link = re.search(r'<A HREF="[^"]+\.dat"[^>]*>.*?</A>', text, flags=re.I | re.S)
        assert link is not None
        text += link.group()
    result = text.encode("euc-jp")
    assert result != content
    return result


class _DerivativeTransport:
    def __init__(self, defect, recording_paths):
        self.replay = ReplayTransport(recording_paths)
        self.defect = defect
        self.responses = []

    def send(self, request):
        response = self.replay.send(request)
        if request.params and request.params.get("KIND") == 2:
            response = replace(response, content=_negative_derivative(response.content, self.defect))
        self.responses.append(response)
        return response


@pytest.mark.parametrize(
    "defect",
    [
        "invalid-encoding",
        "missing-charset",
        "wrong-station",
        "wrong-title",
        "wrong-unit",
        "missing-link",
        "off-host-link",
        "duplicate-link",
        "no-data-marker",
        "no-data-wrong-unit",
        "no-data-without-unit",
    ],
)
def test_public_html_derivative_retains_identified_outcome_and_siblings(retained_evidence_root, monkeypatch, defect):
    transport = _DerivativeTransport(defect, _recording_paths(retained_evidence_root))
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    result = rr.fetch(
        rr.find(provider="jp_mlit", station=_STATION),
        start="2023-01-03",
        end="2023-01-29T23:00:00",
        receipts=True,
        on_issue="ignore",
    )
    assert result.data.height == 197
    outcomes = [o for o in result.outcomes if o.product_id == "stage_hourly"]
    assert len(outcomes) == 1
    assert outcomes[0].status == ("empty" if defect in ("no-data-marker", "no-data-without-unit") else "unsupported")
    assert outcomes[0].series_id
    assert len(result.outcomes) == 4  # HTML prerequisites must not add false EMPTY successes.
    assert len(transport.responses) == 7
    assert [e.content for e in result.receipts.entries] == [r.content for r in transport.responses]
    assert [e.origin.url for e in result.receipts.entries] == [r.url for r in transport.responses]
    assert [c["url"] for c in result.provenance.calls_made] == [r.url for r in transport.responses]
    assert [c["request_parameters"] for c in result.provenance.calls_made] == [
        r.request_parameters for r in transport.responses
    ]
    assert [e.origin.request_parameters for e in result.receipts.entries] == [
        r.request_parameters for r in transport.responses
    ]
    if defect not in ("no-data-marker", "no-data-without-unit"):
        assert outcomes[0].reason
        issue = next(i for i in result.issues if i.code == "unsupported_source_structure")
        assert issue.details["series_id"] == outcomes[0].series_id


@pytest.mark.parametrize("policy", ["warn", "raise"])
def test_public_html_unsupported_obeys_issue_policy(retained_evidence_root, monkeypatch, policy):
    monkeypatch.setattr(
        discovery, "HttpClient", lambda: _DerivativeTransport("wrong-unit", _recording_paths(retained_evidence_root))
    )
    context = pytest.warns(RuntimeWarning) if policy == "warn" else pytest.raises(IssuePolicyError)
    with context:
        rr.fetch(
            rr.find(provider="jp_mlit", station=_STATION),
            start="2023-01-03",
            end="2023-01-29T23:00:00",
            on_issue=policy,
        )


def test_exact_html_and_dat_have_only_dat_outcomes(retained_evidence_root, monkeypatch):
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(_recording_paths(retained_evidence_root)))
    result = rr.fetch(
        rr.find(provider="jp_mlit", station=_STATION),
        start="2023-01-03",
        end="2023-01-29T23:00:00",
        receipts=True,
        on_issue="ignore",
    )
    assert result.data.height == 845
    assert len(result.outcomes) == 4
    assert all(o.status == "success" for o in result.outcomes)
    assert [e.content for e in result.receipts.entries] == [
        read_recording(p).content for p in _recording_paths(retained_evidence_root)
    ]


@pytest.mark.parametrize("defect", ["coordinates", "tags", "kind"])
def test_internal_payload_defects_remain_fatal(retained_evidence_root, defect):
    from rivretrieve._internal.engine import SourceCoordinates
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.providers.jp_mlit.config import config
    from rivretrieve._internal.providers.jp_mlit.fetch import JpMlitPayloadCoordinates
    from rivretrieve._internal.providers.jp_mlit.parse import parse
    from tests.test_jp_mlit_observations import _fetched

    payload = _fetched(retained_evidence_root)[0]
    if defect == "coordinates":
        payload = replace(payload, source_coordinates=SourceCoordinates("invalid"))
    elif defect == "tags":
        payload = replace(payload, station_products=())
    else:
        payload = replace(payload, source_coordinates=SourceCoordinates(JpMlitPayloadCoordinates(7, "html")))
    with pytest.raises(FatalContractError):
        parse(payload, config())


@pytest.mark.parametrize("defect", ["wrong-unit", "no-data-marker"])
def test_html_boundary_provenance_survives_without_receipts(retained_evidence_root, monkeypatch, defect):
    transport = _DerivativeTransport(defect, _recording_paths(retained_evidence_root))
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    result = rr.fetch(
        rr.find(provider="jp_mlit", station=_STATION),
        start="2023-01-03",
        end="2023-01-29T23:00:00",
        receipts=False,
        on_issue="ignore",
    )
    assert result.receipts.entries == ()
    assert len(result.outcomes) == 4
    assert [call["url"] for call in result.provenance.calls_made] == [r.url for r in transport.responses]
    assert [call["retrieved_at"] for call in result.provenance.calls_made] == [
        r.retrieved_at for r in transport.responses
    ]


@pytest.mark.parametrize("defect", ["wrong-unit", "no-data-marker"])
def test_html_outcome_controls_explicit_series_cache_coverage(retained_evidence_root, monkeypatch, tmp_path, defect):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    transport = _DerivativeTransport(defect, _recording_paths(retained_evidence_root))
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    broad = rr.find(provider="jp_mlit", station=_STATION)
    selection = rr.pick(broad, series_id=tuple(s.series_id for s in broad.series))
    first = rr.fetch(
        selection,
        start="2023-01-03",
        end="2023-01-29T23:00:00",
        cache="refresh",
        on_issue="ignore",
    )
    assert len(transport.responses) == 7
    stage = next(o for o in first.outcomes if o.product_id == "stage_hourly")
    expected = "unsupported" if defect == "wrong-unit" else "empty"
    code = "unsupported_source_structure" if defect == "wrong-unit" else "source_no_data"
    assert stage.status == expected
    assert code in {i.code for i in first.issues}
    successes = {o.series_id for o in first.outcomes if o.status in ("success", "empty")}
    assert len(successes) == (3 if defect == "wrong-unit" else 4)
    assert {c.series_id for c in rr.cache_status("jp_mlit").coverage} == successes
    only_stage = rr.pick(selection, series_id=stage.series_id)
    second = rr.fetch(
        only_stage,
        start="2023-01-03",
        end="2023-01-29T23:00:00",
        cache="reuse",
        on_issue="ignore",
    )
    assert len(transport.responses) == (8 if defect == "wrong-unit" else 7)
    assert second.data.is_empty()
    assert [(o.series_id, o.status) for o in second.outcomes] == [(stage.series_id, expected)]
    assert code in {i.code for i in second.issues}
    assert {c.series_id for c in rr.cache_status("jp_mlit").coverage} == successes
