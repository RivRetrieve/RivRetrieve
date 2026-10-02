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

_DATA = Path("tests/test_data")


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


@pytest.mark.recorded(
    "tests/test_data/no_nve_109.42.0_1001_1440_version-1_2024-01-01_2024-01-03.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_1440_version-2_2024-01-01_2024-01-03.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_1440_version-3_2024-01-01_2024-01-03.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_series.recording.json",
)
@pytest.mark.parametrize("kind", ["equal", "conflicting", "disjoint", "different-facts"])
def test_repeated_identity_refuses_every_block_independently_of_order(retained_evidence_root, kind):
    acquired = _recorded_fetch(_ObservedTransport(_recordings(retained_evidence_root)))
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


@pytest.mark.recorded(
    "tests/test_data/no_nve_109.42.0_1001_1440_version-1_engine_2024-01-02.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_1440_version-3_engine_2024-01-02.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_series.recording.json",
)
@pytest.mark.parametrize("kind", ["equal", "conflicting", "disjoint", "different-facts"])
@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_public_repeated_identity_never_certifies_cache_and_preserves_receipts(
    retained_evidence_root, kind, monkeypatch, tmp_path
):
    recordings = tuple(
        read_recording(
            retained_evidence_root / _DATA / f"no_nve_109.42.0_1001_1440_version-{v}_engine_2024-01-02.recording.json"
        )
        for v in (1, 2, 3)
    )
    metadata = read_recording(retained_evidence_root / _DATA / "no_nve_109.42.0_1001_series.recording.json")
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
        failed = next(item for item in result.outcomes if item.series_id == ambiguous_id)
        definition = next(item for item in result.source_series if item.series_id == ambiguous_id)
        assert "repeats a version identity" in failed.reason
        diagnostic_facts = tuple(fact for fact in definition.facts if fact.facts_id in failed.facts_ids)
        assert {fact.facts_id for fact in diagnostic_facts} == set(failed.facts_ids)
        assert diagnostic_facts
        assert any(
            issue.code == "source.unsupported_series" and issue.details["series_id"] == ambiguous_id
            for issue in result.issues
        )
        if kind == "different-facts":
            assert all(fact.statistic.state.value != "known" for fact in diagnostic_facts)
        restored = rr.from_bundle(rr.to_bundle(result))
        assert restored.outcomes == result.outcomes
        assert restored.source_series == result.source_series
        assert restored.issues == result.issues
        pt.assert_frame_equal(restored.data, result.data)
    assert len(contents) == 2  # Reuse must reacquire the unsupported identity.
    before = len(calls)
    siblings = rr.pick(selection, variant=("1", "3"))
    cached = rr.fetch(siblings, start="2024-01-02", end="2024-01-02", cache="reuse", on_issue="ignore")
    assert len(calls) == before
    pt.assert_frame_equal(cached.data, result.data)
    assert not any(item.series_id == ambiguous_id for item in cached.outcomes)


@pytest.mark.recorded(
    "tests/test_data/no_nve_109.42.0_1001_1440_version-1_engine_2024-01-02.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_1440_version-3_engine_2024-01-02.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_series.recording.json",
)
@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_public_supported_nonmatching_facts_are_not_retained_as_failures(retained_evidence_root, monkeypatch):
    recordings = tuple(
        read_recording(
            retained_evidence_root / _DATA / f"no_nve_109.42.0_1001_1440_version-{v}_engine_2024-01-02.recording.json"
        )
        for v in (1, 2, 3)
    )
    metadata = read_recording(retained_evidence_root / _DATA / "no_nve_109.42.0_1001_series.recording.json")
    replay = ReplayTransport((*recordings, metadata))

    class DifferentStatistic:
        def send(self, request):
            response = replay.send(request)
            if request.url.endswith("/Observations") and request.params["VersionNumber"] == 2:
                document = json.loads(response.content)
                document["data"][0]["method"] = "Instantaneous"
                return replace(response, content=json.dumps(document).encode())
            return response

    monkeypatch.setenv("NVE_API_KEY", "protocol-only-key")
    monkeypatch.setattr(discovery, "HttpClient", DifferentStatistic)
    selection = rr.find(
        provider="no_nve", station="109.42.0", quantity="discharge", frequency="daily", statistic="mean"
    )
    excluded = next(item.series_id for item in selection.series if item.variant == "2")
    result = rr.fetch(selection, start="2024-01-02", end="2024-01-02", cache="bypass", on_issue="ignore")
    assert result.data.height == 2
    assert result.data.filter(pl.col("series_id") == excluded).is_empty()
    assert not any(item.series_id == excluded for item in result.outcomes)
    assert not any(item.code == "source.unsupported_series" for item in result.issues)
