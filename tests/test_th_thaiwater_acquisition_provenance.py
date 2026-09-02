from __future__ import annotations

from collections import Counter
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.catalogues.native import read_native_table
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.th_thaiwater import generate_catalogue
from rivretrieve._internal.providers.th_thaiwater.declaration import declaration
from rivretrieve._internal.providers.th_thaiwater.origins import build_acquisition_provenance


def test_thailand_provenance_maps_every_row_to_its_exact_native_agency() -> None:
    provenance = load_packaged_catalogue_artifact(declaration.catalogue).acquisition_provenance
    assert provenance is not None
    station_bindings = [b for b in provenance.fact_bindings if b.fact_group.startswith("station:")]
    observation_bindings = [b for b in provenance.fact_bindings if b.fact_group.startswith("observation:")]
    assert len(station_bindings) == 825
    assert len(observation_bindings) == 825
    assert Counter(b.source_id for b in station_bindings) == {
        "th_agency_8": 73,
        "th_agency_9": 329,
        "th_agency_12": 328,
        "th_agency_91": 95,
    }
    assert Counter(b.source_id for b in observation_bindings) == Counter(b.source_id for b in station_bindings)

    native = pl.read_parquet(declaration.catalogue / "native.parquet")
    source_by_station = {
        str(station): f"th_agency_{agency}" for station, agency in native.select("station.id", "agency.id").iter_rows()
    }
    assert {
        binding.fact_group.removeprefix("station:"): binding.source_id for binding in station_bindings
    } == source_by_station


def test_thailand_canonical_product_definition_is_rivretrieve_owned() -> None:
    provenance = load_packaged_catalogue_artifact(declaration.catalogue).acquisition_provenance
    assert provenance is not None
    assert not any(binding.fact_group == "product_identity" for binding in provenance.fact_bindings)
    canonical = next(
        binding for binding in provenance.fact_bindings if binding.fact_group == "canonical_product_carrier"
    )
    assert canonical.source_id is None
    assert canonical.acquisition_id is None
    assert canonical.transformation is not None
    assert canonical.transformation.name == "RivRetrieve canonical ThaiWater product definitions"
    assert canonical.transformation.external_inputs == ()
    assert set(canonical.facts) == {fact for fact in provenance.fact_universe if fact.startswith("product.")}


def test_thailand_withholds_each_station_product_availability_fact() -> None:
    provenance = load_packaged_catalogue_artifact(declaration.catalogue).acquisition_provenance
    assert provenance is not None
    assert len(provenance.withheld_facts) == 1_648
    assert {item.reason for item in provenance.withheld_facts} == {"no_acquisition_record_established"}
    assert all(
        fact.startswith("station_product:") and fact.endswith(":availability")
        for item in provenance.withheld_facts
        for fact in item.facts
    )
    withheld_edges = {
        (locator.station_id, locator.product_id)
        for item in provenance.withheld_facts
        for locator in item.catalogue_rows
    }
    assert ("1373273", "discharge_instantaneous") not in withheld_edges
    assert ("1373273", "stage_instantaneous") not in withheld_edges
    assert ("1373272", "discharge_instantaneous") in withheld_edges
    assert ("1373272", "stage_instantaneous") in withheld_edges


def test_recorded_graph_binds_only_the_two_established_edges_to_existing_issuer() -> None:
    provenance = load_packaged_catalogue_artifact(declaration.catalogue).acquisition_provenance
    assert provenance is not None
    bindings = [
        binding for binding in provenance.fact_bindings if binding.fact_group.startswith("station_product:1373273:")
    ]
    assert {(binding.fact_group, binding.source_id, binding.acquisition_id) for binding in bindings} == {
        (
            "station_product:1373273:discharge_instantaneous:availability",
            "th_agency_9",
            "waterlevel_graph_1373273_2026_08_01_02",
        ),
        (
            "station_product:1373273:stage_instantaneous:availability",
            "th_agency_9",
            "waterlevel_graph_1373273_2026_08_01_02",
        ),
    }
    issuer = next(source for source in provenance.source_records if source.source_id == "th_agency_9")
    acquisition = next(
        item for item in issuer.acquisitions if item.acquisition_id == "waterlevel_graph_1373273_2026_08_01_02"
    )
    assert acquisition.recording_ids == ("th_thaiwater_1373273_graph_2026_08_01_02",)
    assert acquisition.material is not None
    assert acquisition.material.sha256 == "436593e32ccb99e2edff4ea87681679608f226efada8bc263fd706dfc7c20d01"


def test_thailand_cli_rejects_native_byte_substitution(tmp_path: Path) -> None:
    native = tmp_path / "native.parquet"
    native.write_bytes((declaration.catalogue / "native.parquet").read_bytes() + b"changed")
    with pytest.raises(FatalContractError, match="native table digest mismatch: expected .* observed"):
        generate_catalogue.main(["--native", str(native), "--out", str(tmp_path / "out")])


def test_thailand_cli_invokes_recording_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*_args: object) -> None:
        raise FatalContractError("recording verification invoked")

    monkeypatch.setattr(generate_catalogue, "verify_provenance_recordings", reject)
    with pytest.raises(FatalContractError, match="recording verification invoked"):
        generate_catalogue.main(["--native", str(declaration.catalogue / "native.parquet"), "--out", str(tmp_path)])


def test_thailand_station_carrier_has_exact_multi_agency_lineage() -> None:
    provenance = build_acquisition_provenance(read_native_table(declaration.catalogue / "native.parquet"))
    station_carrier = next(
        binding for binding in provenance.fact_bindings if binding.fact_group == "canonical_station_carrier"
    )
    assert station_carrier.source_id is None
    assert station_carrier.transformation is not None
    referenced_sources = {reference.source_id for reference in station_carrier.transformation.external_inputs}
    assert referenced_sources == {"th_agency_8", "th_agency_9", "th_agency_12", "th_agency_91"}
