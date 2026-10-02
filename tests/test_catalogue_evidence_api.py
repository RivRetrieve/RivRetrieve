"""Real public selection and recorded retrieval carry normalized evidence values."""

from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.catalogues.evidence import CatalogueEvidence
from rivretrieve._internal.engine import CanonicalRowsSchema
from rivretrieve._internal.observations import ObservationProvenance

ROOT = Path(__file__).parents[1]


def test_real_selection_exposes_normalized_metadata_without_legacy_aliases():
    selection = rr.find(
        provider="fr_hydroportail", station="1232000101", quantity="discharge", statistic="instantaneous"
    )
    assert type(selection.acquisition_provenance) is tuple
    evidence = selection.acquisition_provenance[0]
    assert type(evidence) is CatalogueEvidence
    assert evidence.header.schema_version == 3
    assert evidence.header.provider_id == "fr_hydroportail"
    assert not hasattr(evidence, "fact_bindings")
    assert not hasattr(evidence.header.source_records[0], "acquisitions")
    assert len(repr(evidence)) < 300
    locator = evidence.facts.filter(
        (pl.col("station_id") == "1232000101")
        & (pl.col("product_id") == "discharge_instantaneous")
        & (pl.col("locator_role") == "availability")
    )
    assert locator.height == 1
    frame = rr.as_frame(selection)
    assert frame["station_id"].to_list() == ["1232000101"] * 4
    assert set(frame["variant"]) == {"raw", "validated", "pre_validated_and_validated", "most_valid"}


def test_recorded_public_fetch_normalized_provenance_serialization(
    monkeypatch: pytest.MonkeyPatch, retained_evidence_root: Path
):
    from tests.usgs_modern_recordings import ModernReplay

    replay = ModernReplay("continuous-07374000-2010-discharge", evidence_root=retained_evidence_root)
    monkeypatch.setattr(discovery, "_credentialed_transport", lambda provider_id, values: replay)
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", temporal_support="instantaneous"
    )
    result = rr.fetch(selection, start="2010-06-01T05:00:00", end="2010-06-02T04:59:59", on_issue="ignore")
    evidence = result.provenance.acquisition_provenance
    assert type(evidence) is CatalogueEvidence
    assert evidence.header.provider_id == "usgs_nwis"
    assert result.data.schema == CanonicalRowsSchema.polars_schema
    assert result.data.height > 0
    python_value = result.provenance.model_dump(mode="python")
    assert isinstance(python_value["acquisition_provenance"]["facts"], pl.DataFrame)
    json_value = result.provenance.model_dump(mode="json")
    assert isinstance(json_value["acquisition_provenance"]["facts"]["fact_id"], list)
    assert "fact_bindings" not in json_value["acquisition_provenance"]
    restored = ObservationProvenance.model_validate_json(result.provenance.model_dump_json())
    assert restored.acquisition_provenance is not None
    assert restored.acquisition_provenance.header == evidence.header
    for name in ("facts", "acquisitions", "bindings", "binding_facts", "external_inputs"):
        pl_testing.assert_frame_equal(
            getattr(restored.acquisition_provenance, name), getattr(evidence, name), check_exact=True
        )
    assert restored.license == result.provenance.license
    assert restored.citation == result.provenance.citation
