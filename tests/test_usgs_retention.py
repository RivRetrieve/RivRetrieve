import json

import pytest

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.usgs_nwis.retention import load_historical_features, read_retention


def test_historical_selection_keeps_source_membership(tmp_path, monkeypatch):
    manifest = tmp_path / "retention.json"
    document = {
        "schema_version": 2,
        "historical_sources": [
            {"consumer_directory": "september", "series_ids": ["a"]},
            {"consumer_directory": "october", "series_ids": ["b"]},
        ],
        "retained_station_ids": ["canadian"],
    }
    manifest.write_text(json.dumps(document))
    selection = read_retention(manifest)
    from rivretrieve._internal.providers.usgs_nwis import generate_catalogue

    rows = {"september": [{"id": "a"}, {"id": "unselected"}], "october": [{"id": "b"}]}
    monkeypatch.setattr(generate_catalogue, "read_modern_metadata", lambda path: (rows[path.name], []))
    assert load_historical_features(selection, tmp_path) == [{"id": "a"}, {"id": "b"}]
    assert selection.historical_series_ids == ("a", "b")
    rows["october"] = [{"id": "a"}]
    with pytest.raises(FatalContractError, match="missing"):
        load_historical_features(selection, tmp_path)


@pytest.mark.parametrize("mutation", ["duplicate", "escape", "absolute", "version"])
def test_retention_rejects_ambiguous_or_unscoped_selection(tmp_path, mutation):
    document = {
        "schema_version": 2,
        "historical_sources": [
            {"consumer_directory": "september", "series_ids": ["a"]},
            {"consumer_directory": "october", "series_ids": ["b"]},
        ],
        "retained_station_ids": [],
    }
    if mutation == "duplicate":
        document["historical_sources"][1]["series_ids"] = ["a"]
    elif mutation == "version":
        document["schema_version"] = 1
    else:
        document["historical_sources"][0]["consumer_directory"] = "../outside" if mutation == "escape" else "/outside"
    manifest = tmp_path / "retention.json"
    manifest.write_text(json.dumps(document))
    with pytest.raises(FatalContractError):
        read_retention(manifest)
