"""Public cache and policy boundaries isolate nonrepresentable publisher numbers."""

import json
import warnings
from dataclasses import replace

import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.issues import IssuePolicyError
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from tests.test_json_measurement_cells import DATA
from tests.test_live_numeric_values import BAD, TOKENS


class NumericReplay(ReplayTransport):
    def __init__(self, recordings, mutation):
        super().__init__(recordings)
        self.mean = recordings[0].content
        self.mutation = mutation
        self.bodies = []
        self.calls = 0

    def send(self, request):
        response = super().send(request)
        self.calls += 1
        content = response.content
        if content == self.mean:
            document = json.loads(content)
            for row in document["data"]:
                row["resultat_obs_elab"] = "__NUMERIC_TEST_CELL__"
            content = json.dumps(document).encode().replace(b'"__NUMERIC_TEST_CELL__"', TOKENS[self.mutation].encode())
        self.bodies.append(content)
        return replace(response, content=content)


# The real-parser matrix in test_live_numeric_values covers every representation.
# Here overflow exercises each policy; valid zero/finite/null states prove cache integration.
@pytest.mark.parametrize(
    "mutation,policy",
    [("large_exponent", policy) for policy in ("raise", "warn", "ignore")]
    + [(mutation, "raise") for mutation in ("zero", "finite", "null")],
)
def test_public_numeric_representation_preserves_sibling_receipts_and_coverage(tmp_path, monkeypatch, mutation, policy):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    recordings = tuple(
        read_recording(DATA / f"fr_hubeau_1011000101_{field}_padded.recording.json") for field in ("QmnJ", "QIXnJ")
    )
    replay = NumericReplay(recordings, mutation)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    selection = rr.find(provider="fr_hubeau", station="1011000101", quantity="discharge", frequency="daily")
    ids = {series.facts[0].statistic.value: series.series_id for series in selection.series}
    bad = mutation in BAD

    def fetch():
        return rr.fetch(selection, start="2025-01-03", end="2025-01-03", cache="reuse", receipts=True, on_issue=policy)

    if bad and policy == "raise":
        with pytest.raises(IssuePolicyError) as error:
            fetch()
        assert any(issue.code == "unsupported_source_structure" for issue in error.value.issues)
    else:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = fetch()
        assert bool(caught) == (bad and policy == "warn")
        assert replay.calls == 2
        assert [entry.content for entry in result.receipts.entries] == replay.bodies
        mean = [outcome for outcome in result.outcomes if outcome.series_id == ids["mean"]]
        assert mean and all(outcome.status == ("unsupported" if bad else "success") for outcome in mean)
        assert all(outcome.reason for outcome in mean) if bad else all(outcome.reason is None for outcome in mean)
        maximum = result.data.filter(result.data["series_id"] == ids["max"])
        assert maximum.height == 1
        source_max = json.loads(recordings[1].content)["data"]
        expected = next(
            row["resultat_obs_elab"] / 1000 for row in source_max if row["date_obs_elab"].startswith("2025-01-03")
        )
        assert maximum["value"][0] == pytest.approx(expected)
        values = result.data.filter(result.data["series_id"] == ids["mean"])["value"]
        if bad:
            assert values.is_empty()
        else:
            assert values.to_list() == [{"zero": 0.0, "finite": 0.00125, "null": None}[mutation]]
    coverage = rr.cache_status("fr_hubeau").coverage
    assert {item.series_id for item in coverage} == ({ids["max"]} if bad else set(ids.values()))
    # Cache reuse of the independent successful sibling needs no second source call.
    healthy = rr.pick(selection, series_id=ids["max"])
    cached = rr.fetch(healthy, start="2025-01-03", end="2025-01-03", cache="reuse", on_issue="ignore")
    assert replay.calls == 2
    assert cached.data.height == 1
    if not (bad and policy == "raise"):
        assert_frame_equal(cached.data, maximum)
