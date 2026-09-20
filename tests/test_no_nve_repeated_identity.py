"""Authored repeated-block controls over exact HydAPI recordings, not new source captures."""

import copy
import json
from dataclasses import replace
from pathlib import Path

import polars as pl
import polars.testing as pt
import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.engine import SourceCoordinates
from rivretrieve._internal.providers.no_nve.parse import parse
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from tests.test_no_nve_series_discovery import _ObservedTransport, _recorded_fetch, _recordings, config

_DATA = Path(__file__).parent / "test_data"


def _repeated(content, kind, reverse=False):
    document = json.loads(content)
    first = document["data"][0]
    other = copy.deepcopy(first)
    if kind == "conflicting":
        other["observations"][0]["value"] = 999
    elif kind == "disjoint":
        first["observations"] = first["observations"][:1]
        other["observations"] = other["observations"][1:]
        first["observationCount"] = len(first["observations"])
        other["observationCount"] = len(other["observations"])
    elif kind == "different-facts":
        other["method"] = "Instantaneous"
    document["data"] = [other, first] if reverse else [first, other]
    return json.dumps(document).encode()


@pytest.mark.parametrize("kind", ["equal", "conflicting", "disjoint", "different-facts"])
def test_repeated_identity_refuses_every_block_independently_of_order(kind):
    acquired = _recorded_fetch(_ObservedTransport(_recordings()))
    original = acquired.value[1]
    sibling = json.loads(acquired.value[2].content)["data"][0]
    expected = parse(acquired.value[2], config())
    results = []
    for reverse in (False, True):
        document = json.loads(_repeated(original.content, kind, reverse))
        document["data"].append(sibling)
        # Authored multi-version envelope: remove explicit request restriction so sibling is valid.
        payload = replace(
            original,
            content=json.dumps(document).encode(),
            source_coordinates=SourceCoordinates(replace(original.source_coordinates.value, version_number=None)),
        )
        result = parse(payload, config())
        results.append(result)
        pt.assert_frame_equal(result.rows, expected.rows)
        ambiguous = next(item for item in result.series if item.variant == "2")
        outcomes = [item for item in result.outcomes if item.series_id == ambiguous.series_id]
        assert len(outcomes) == 1
        assert outcomes[0].status == "unsupported"
        assert "repeats a version identity" in outcomes[0].reason
        assert any(
            issue.details["series_id"] == ambiguous.series_id
            for issue in result.issues
            if issue.code == "source.unsupported_series"
        )
        assert any(item.status == "success" for item in result.outcomes)
    pt.assert_frame_equal(results[0].rows, results[1].rows)
    assert results[0].series == results[1].series


@pytest.mark.parametrize("kind", ["equal", "conflicting", "disjoint"])
def test_public_repeated_identity_never_certifies_cache_and_preserves_receipts(kind, monkeypatch, tmp_path):
    recordings = tuple(
        read_recording(_DATA / f"no_nve_109.42.0_1001_1440_version-{v}_engine_2024-01-02.recording.json")
        for v in (1, 2, 3)
    )
    metadata = read_recording(_DATA / "no_nve_109.42.0_1001_series.recording.json")
    replay = ReplayTransport((*recordings, metadata))
    calls = []
    contents = []

    class Repeated:
        def send(self, request):
            calls.append(request)
            response = replay.send(request)
            if request.url.endswith("/Observations") and request.params["VersionNumber"] == 2:
                content = _repeated(response.content, kind)
                contents.append(content)
                return replace(response, content=content)
            return response

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("NVE_API_KEY", "protocol-only-key")
    monkeypatch.setattr(discovery, "HttpClient", Repeated)
    selection = rr.find(
        provider="no_nve", station="109.42.0", quantity="discharge", frequency="daily", statistic="mean"
    )
    ambiguous_id = next(item.series_id for item in selection.series if item.variant == "2")
    for cache in ("refresh", "reuse"):
        result = rr.fetch(
            selection, start="2024-01-02", end="2024-01-02", cache=cache, receipts=True, on_issue="ignore"
        )
        assert result.data.filter(pl.col("series_id") == ambiguous_id).is_empty()
        assert result.data.height == 2
        assert {item.status.value for item in result.outcomes if item.series_id == ambiguous_id} == {"unsupported"}
        assert contents[-1] in {entry.content for entry in result.receipts.entries}
    assert len(contents) == 2  # Reuse must reacquire the unsupported identity.
    before = len(calls)
    siblings = rr.pick(selection, variant=("1", "3"))
    cached = rr.fetch(siblings, start="2024-01-02", end="2024-01-02", cache="reuse", on_issue="ignore")
    assert len(calls) == before
    pt.assert_frame_equal(cached.data, result.data)
