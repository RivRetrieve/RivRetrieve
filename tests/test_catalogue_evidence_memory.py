"""National evidence normalization releases duplicate build buffers before validation."""

from __future__ import annotations

import inspect
from pathlib import Path

import polars.testing as pl_testing

from rivretrieve._internal.catalogues import evidence as evidence_module
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from tests._provenance import legacy_provenance


def test_national_normalization_releases_row_buffers_before_closure(monkeypatch):
    artifact = load_packaged_catalogue_artifact(Path("src/rivretrieve/_internal/providers/br_ana/catalogue"))
    expected = artifact.acquisition_provenance
    assert expected is not None
    provenance = legacy_provenance(expected)
    original_validate = evidence_module._validate_relations
    retained_counts = []
    validated_sizes = []

    def instrument_validation(evidence):
        frame = inspect.currentframe()
        count = 0
        try:
            frame = frame.f_back
            while frame is not None:
                for value in frame.f_locals.values():
                    if (
                        isinstance(value, dict)
                        and value.keys() == evidence_module.EVIDENCE_SCHEMAS.keys()
                        and all(isinstance(rows, list) for rows in value.values())
                    ):
                        count += sum(len(rows) for rows in value.values())
                frame = frame.f_back
        finally:
            del frame
        retained_counts.append(count)
        validated_sizes.append(evidence.facts.height)
        # Instrument, but never replace or bypass, the real closure validator.
        original_validate(evidence)

    monkeypatch.setattr(evidence_module, "_validate_relations", instrument_validation)
    result = evidence_module.normalize_provenance(
        provenance, stations=artifact.stations, station_products=artifact.station_products
    )
    metadata_facts = {
        "metadata.drainage_area.Area_Drenagem",
        "metadata.station_name.Estacao_Nome",
        "metadata.river_name.Rio_Nome",
    }
    actual_metadata_facts = {name for name in expected.facts["name"] if name.startswith("metadata.")}
    assert actual_metadata_facts == metadata_facts
    assert expected.facts.height - len(metadata_facts) == 107578
    assert validated_sizes == [107578 + len(metadata_facts)]
    assert retained_counts == [0], "Raw relation row buffers overlap full national closure validation"
    assert result.header == expected.header
    for name in evidence_module.EVIDENCE_SCHEMAS:
        pl_testing.assert_frame_equal(getattr(result, name), getattr(expected, name))
