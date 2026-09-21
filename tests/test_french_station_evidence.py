"""Canonical French station facts resolve to their acquired native inventories."""

import pytest

import rivretrieve as rr
from rivretrieve._internal.catalogues.evidence_graph import FactSelection, resolve_evidence


@pytest.mark.parametrize(
    "provider,required_acquisitions",
    [
        ("fr_hubeau", {"hydrometry_catalogue_capture_2026_09_21", "temperature_catalogue_capture_2026_09_21"}),
        ("fr_hydroportail", {"public_station_search"}),
    ],
)
@pytest.mark.parametrize("field", ["station_id", "latitude", "longitude", "crs"])
def test_canonical_station_fact_resolves_to_native_inventory(provider, required_acquisitions, field):
    evidence = rr.find(provider=provider, station="1232000101").acquisition_provenance[0]
    graph = resolve_evidence(evidence, FactSelection(names=(f"station.{field}",)))
    actual = {node["identifier"] for node in graph["@graph"] if str(node["@id"]).startswith("acquisition/")}
    assert required_acquisitions <= actual
