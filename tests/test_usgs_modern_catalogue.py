"""Modern catalogue tests; mutations below are authored negative controls."""

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from rivretrieve._internal.catalogues.source_series import decode_source_descriptions
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.usgs_nwis.catalogue_series import modern_source_descriptions
from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import read_modern_metadata

CATALOGUE = Path("src/rivretrieve/_internal/providers/usgs_nwis/catalogue")


def test_modern_concrete_snapshot_retains_siblings_unknowns_and_legacy_scope():
    descriptions = decode_source_descriptions((CATALOGUE / "source_series.json").read_bytes())
    locations = json.loads((CATALOGUE / "monitoring_locations.json").read_text())
    assert len(locations) == 26258
    assert len(descriptions.descriptions) == 59159
    # Full definition digest after the content-derived facts-ID repair.
    # Disk v1/v2 equality was checked separately before that repair.
    assert hashlib.sha256(descriptions.model_dump_json().encode()).hexdigest() == (
        "361206d8f6421e1934c2e4a9098ca3beb9e834d75283ffaec39aa8812bc7ff0e"
    )
    assert len({id(fact) for item in descriptions.descriptions for fact in item.facts}) == 8
    assert {item.station_id for item in descriptions.descriptions} <= locations.keys()
    siblings = [
        item
        for item in descriptions.descriptions
        if item.station_id == "02196000" and item.product_id == "discharge_daily_mean"
    ]
    assert {item.variant for item in siblings} == {
        "0df18b246e8f48ec8e6547a92070e94a",
        "4d186669708e4dc18f84d271efb953a1",
    }
    assert all(item.identity.description is None for item in siblings)
    unknowns = [item for item in descriptions.descriptions if item.facts[0].statistic.value is None]
    assert len(unknowns) == 6
    assert all(item.facts[0].temporal_support.value is None for item in unknowns)
    assert (CATALOGUE / "source_series.json").stat().st_size < 100_000_000


def test_description_preserves_empty_and_null_without_parameter_prose(
    retained_evidence_root,
):
    page = json.loads(
        gzip.decompress(
            (retained_evidence_root / "research/usgs-modern-coverage" / "metadata-00060-0000.json.gz").read_bytes()
        )
    )
    properties = page["features"][0]["properties"]
    locations = {"10172640": "USGS-10172640"}
    for description in (None, "", "publisher text"):
        # Authored description variations on otherwise untouched publisher metadata.
        altered = {**properties, "web_description": description}
        result = modern_source_descriptions([altered], locations)
        assert result.descriptions[0].identity.description == description


def test_saved_pagination_rejects_incomplete_chain(retained_evidence_root, tmp_path):
    completion = json.loads(
        (retained_evidence_root / "research/usgs-modern-coverage" / "metadata-00060-completion.json").read_text()
    )
    completion["status"] = "incomplete"  # Authored negative control.
    (tmp_path / "metadata-00060-completion.json").write_text(json.dumps(completion))
    with pytest.raises(FatalContractError, match="complete unsorted"):
        read_modern_metadata(tmp_path)


def test_materialization_preserves_shared_immutable_physical_facts():
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.catalogues.source_series import materialize_series
    from rivretrieve._internal.source_series import SeriesScope

    artifact = load_packaged_catalogue_artifact(CATALOGUE)
    series, _ = materialize_series(artifact, scope=SeriesScope(station_ids=("02196000",)))
    siblings = [item for item in series if item.product_id == "discharge_daily_mean"]
    assert len(siblings) == 2
    assert siblings[0].facts[0] is siblings[1].facts[0]
    assert artifact.source_descriptions is not None
    description = next(
        item for item in artifact.source_descriptions.descriptions if item.series_id == siblings[0].series_id
    )
    assert siblings[0].facts[0] is description.facts[0]


def test_modern_observation_provenance_keeps_legacy_calls_independent():
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact

    artifact = load_packaged_catalogue_artifact(CATALOGUE)
    evidence = artifact.acquisition_provenance
    assert evidence is not None
    acquisitions = evidence.acquisitions
    identifiers = set(acquisitions["acquisition_id"].to_list())
    assert {"observation_request", "modern_observation_request"} <= identifiers
    assert "source.observation.modern_values_qualifiers_and_timestamps" in evidence.facts["name"].to_list()
