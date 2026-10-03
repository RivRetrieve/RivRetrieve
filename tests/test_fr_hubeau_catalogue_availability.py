"""France catalogue admission preserves every evidenced native station/product pair."""

import lzma

import pytest

from rivretrieve._internal.catalogues.native import read_native_table
from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import (
    EXPECTED_PRODUCT_IDS,
    NativeInventoryCapture,
    build_catalogue,
    decode_availability,
)
from rivretrieve._internal.providers.fr_hubeau.origins import FRANCE_ORIGIN_DECLARATIONS


@pytest.mark.derived(
    "maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz",
    "maintenance/catalogue/fr_hubeau/inventory/native_capture.json",
)
@pytest.mark.derived("src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet")
def test_catalogue_admits_full_evidenced_native_inventory(retained_evidence_root) -> None:
    native_path = retained_evidence_root / "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet"
    native = read_native_table(native_path)
    ledger_path = retained_evidence_root / "maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz"
    availability = decode_availability(lzma.decompress(ledger_path.read_bytes()))
    capture = NativeInventoryCapture.model_validate_json((ledger_path.parent / "native_capture.json").read_bytes())
    catalogue = build_catalogue(native, FRANCE_ORIGIN_DECLARATIONS, availability, native_capture=capture)
    artifact = catalogue.public_artifact
    assert artifact.stations.height == 7347
    assert artifact.station_products.height == 20297
    assert set(artifact.stations["station_id"]) == set(native.data["code_station"])
    assert dict(artifact.station_products.group_by("availability").len().iter_rows()) == {
        "available": 15283,
        "unknown": 5014,
    }

    catalogue_rows = {
        (row["station_id"], row["product_id"]): row for row in artifact.station_products.iter_rows(named=True)
    }
    provenance = catalogue.acquisition_provenance
    assert provenance is not None
    bindings = {fact: binding for binding in provenance.fact_bindings for fact in binding.facts}
    acquisitions = {
        (source.source_id, acquisition.acquisition_id): acquisition
        for source in provenance.source_records
        for acquisition in source.acquisitions
    }
    for pair in availability.pairs:
        if pair.product_id not in EXPECTED_PRODUCT_IDS:
            continue
        row = catalogue_rows[pair.code_station, pair.product_id]
        assert row["last_catalogue_check"] == max(a.retrieved_at_start for a in pair.acquisitions).date()
        assert row["availability_reason"] == pair.reason
        assert row["published_record_start_date"] is None
        assert row["published_record_end_date"] is None
        availability_binding = bindings[f"station_product:{pair.code_station}:{pair.product_id}.availability"]
        assert availability_binding.transformation is not None
        references = availability_binding.transformation.external_inputs
        assert len(references) == len(pair.acquisitions)
        for reference, expected in zip(references, pair.acquisitions, strict=True):
            binding = bindings[reference.fact]
            assert binding.source_id is not None
            assert binding.acquisition_id is not None
            actual = acquisitions[binding.source_id, binding.acquisition_id]
            assert actual.material == expected.material
            assert actual.requested_from == expected.requested_from
            assert actual.retrieved_at_start == expected.retrieved_at_start
        values_binding = bindings[f"source.observation.{pair.code_station}.{pair.product_id}.values_quality"]
        assert values_binding.source_id is not None
        assert values_binding.acquisition_id is not None
        assert acquisitions[values_binding.source_id, values_binding.acquisition_id].instant_type == "runtime"
