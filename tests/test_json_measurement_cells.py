"""Required JSON measurement cells are distinct from published nulls and booleans."""

import json
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.recordings import ReplayTransport, read_recording

DATA = Path(__file__).parent / "test_data"
CASES = (
    (
        "daily",
        "1011000101",
        {"quantity": "discharge", "frequency": "daily", "statistic": "mean"},
        "2025-01-03",
        "2025-01-03",
        ("fr_hubeau_1011000101_QmnJ_padded.recording.json",),
        "resultat_obs_elab",
        1,
    ),
    (
        "temperature",
        "01001336",
        {"quantity": "temperature"},
        "2008-07-09",
        "2008-07-10T23:59:59",
        tuple(f"fr_hubeau_01001336_temp_padded_p{i}.recording.json" for i in range(1, 6)),
        "resultat",
        37,
    ),
    (
        "hydroportail",
        "1232000101",
        {"quantity": "discharge", "statistic": "instantaneous"},
        "2026-06-01",
        "2026-06-02",
        ("fr_hydroportail_station_Q_padded.recording.json",),
        "v",
        282,
    ),
)


class MeasurementReplay(ReplayTransport):
    def __init__(self, recordings, field, mutation, *, selected_content=None):
        super().__init__(recordings)
        self.field = field
        self.mutation = mutation
        self.selected_content = selected_content
        self.modified_bodies = []

    def send(self, request):
        response = super().send(request)
        if self.mutation == "original" or (
            self.selected_content is not None and response.content != self.selected_content
        ):
            return response
        document = json.loads(response.content)
        rows = document["series"]["data"] if "series" in document else document["data"]
        assert rows
        for row in rows:
            assert self.field in row, "mutation must start from a genuine published measurement cell"
            if self.mutation == "missing":
                del row[self.field]
            else:
                row[self.field] = {"null": None, "true": True, "false": False}[self.mutation]
        content = json.dumps(document, ensure_ascii=False).encode()
        self.modified_bodies.append(content)
        return replace(response, content=content)


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
@pytest.mark.parametrize("mutation", ["original", "null", "missing", "true", "false"])
def test_public_france_measurement_cells_keep_absence_distinct_from_null(tmp_path, monkeypatch, case, mutation):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    route, station, predicates, start, end, filenames, field, count = case
    provider = "fr_hydroportail" if route == "hydroportail" else "fr_hubeau"
    recordings = tuple(read_recording(DATA / filename) for filename in filenames)
    replay = MeasurementReplay(recordings, field, mutation)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    selection = rr.find(provider=provider, station=station, **predicates)
    if provider == "fr_hydroportail":
        selection = rr.pick(selection, variant="raw")
    assert len(selection.series) == 1
    result = rr.fetch(selection, start=start, end=end, cache="reuse", receipts=True, on_issue="ignore")
    if mutation in ("missing", "true", "false"):
        assert result.data.is_empty(), "malformed cells must not become numeric or published-null rows"
        assert result.outcomes
        assert all(outcome.status == "unsupported" for outcome in result.outcomes)
        assert all(outcome.series_id == selection.series[0].series_id for outcome in result.outcomes)
        assert all(outcome.reason for outcome in result.outcomes)
        assert any(issue.code == "unsupported_source_structure" for issue in result.issues)
        assert rr.cache_status(provider).coverage == ()
    else:
        assert result.data.height == count
        assert all(outcome.status in ("success", "empty") for outcome in result.outcomes)
        assert any(outcome.status == "success" for outcome in result.outcomes)
        assert not any(issue.severity == "error" for issue in result.issues)
        if mutation == "null":
            assert result.data["value"].is_null().all()
    if mutation != "original":
        assert [entry.content for entry in result.receipts.entries] == replay.modified_bodies


@pytest.mark.parametrize("mutation", ["missing", "true", "false"])
def test_bad_daily_measurement_does_not_discard_independent_recorded_statistic(monkeypatch, mutation):
    mean = read_recording(DATA / "fr_hubeau_1011000101_QmnJ_padded.recording.json")
    maximum = read_recording(DATA / "fr_hubeau_1011000101_QIXnJ_padded.recording.json")
    replay = MeasurementReplay((mean, maximum), "resultat_obs_elab", mutation, selected_content=mean.content)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    selection = rr.find(provider="fr_hubeau", station="1011000101", quantity="discharge", frequency="daily")
    result = rr.fetch(selection, start="2025-01-03", end="2025-01-03", receipts=True, on_issue="ignore")
    assert result.data.height == 1
    successful = next(outcome for outcome in result.outcomes if outcome.status == "success")
    unsupported = next(outcome for outcome in result.outcomes if outcome.status == "unsupported")
    assert successful.series_id != unsupported.series_id
    assert result.data["series_id"].unique().to_list() == [successful.series_id]
    assert result.data.filter(pl.col("series_id") == unsupported.series_id).is_empty()
    by_id = {series.series_id: series for series in result.source_series}
    assert by_id[successful.series_id].facts[0].statistic.value == "max"
    assert by_id[unsupported.series_id].facts[0].statistic.value == "mean"
    assert maximum.content in [entry.content for entry in result.receipts.entries]
