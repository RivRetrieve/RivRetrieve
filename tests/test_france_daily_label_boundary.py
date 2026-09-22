"""A malformed daily label is a source limitation, not an internal row contract."""

import json
from contextlib import nullcontext

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.issues import IssuePolicyError
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from tests.test_source_field_boundaries import DATA, AlteredResponseTransport


@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
def test_daily_nonmidnight_label_preserves_valid_daily_max(monkeypatch, tmp_path, policy):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    recordings = tuple(
        read_recording(DATA / name)
        for name in (
            "fr_hubeau_1011000101_QmnJ_padded.recording.json",
            "fr_hubeau_1011000101_QIXnJ_padded.recording.json",
        )
    )
    selection = rr.find(provider="fr_hubeau", station="1011000101", quantity="discharge", frequency="daily")
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(recordings))
    expected = rr.fetch(selection, start="2025-01-03", end="2025-01-03", cache="bypass", on_issue="ignore")
    assert set(expected.data["product_id"]) == {"discharge_daily_mean", "discharge_daily_max"}

    mutated = []

    def alter(request, body):
        if dict(request.params or {}).get("grandeur_hydro_elab") == "QmnJ":
            document = json.loads(body)
            document["data"][0]["date_obs_elab"] = "2025-01-01T12:00:00"
            content = json.dumps(document).encode()
            mutated.append(content)
            return content
        return body

    monkeypatch.setattr(discovery, "HttpClient", lambda: AlteredResponseTransport(recordings, alter))
    context = (
        pytest.raises(IssuePolicyError)
        if policy == "raise"
        else pytest.warns(RuntimeWarning)
        if policy == "warn"
        else nullcontext()
    )
    with context:
        result = rr.fetch(
            selection, start="2025-01-03", end="2025-01-03", cache="refresh", receipts=True, on_issue=policy
        )
    if policy == "raise":
        return
    assert_frame_equal(result.data, expected.data.filter(pl.col("product_id") == "discharge_daily_max"))
    unsupported = [outcome for outcome in result.outcomes if outcome.status == "unsupported"]
    assert len(unsupported) == 1
    assert unsupported[0].product_id == "discharge_daily_mean"
    assert "midnight" in unsupported[0].reason
    assert any(issue.code == "unsupported_source_structure" for issue in result.issues)
    assert any(receipt.content == mutated[0] for receipt in result.receipts.entries)
    manifest = json.loads((tmp_path / "fr_hubeau/store/manifest.json").read_text())
    assert all(coverage["series_id"] != unsupported[0].series_id for coverage in manifest["coverage"])
