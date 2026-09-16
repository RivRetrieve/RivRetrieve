"""ANA adopted products and candidate availability retain exact evidence and honest absence."""

from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal
from pydantic import ValidationError

from rivretrieve._internal.acquisition_provenance import AbsenceMarkerValue, AcquisitionProvenance
from rivretrieve._internal.catalogues.evidence import normalize_provenance, validate_catalogue_locators
from rivretrieve._internal.catalogues.native import read_native_table
from rivretrieve._internal.providers.br_ana.capture import parse_adopted_telemetry_evidence, read_capture_record
from rivretrieve._internal.providers.br_ana.generate_catalogue import build_catalogue, project_stations, write_catalogue
from rivretrieve._internal.providers.br_ana.origins import (
    STATION_CATALOGUE_ORIGINS,
    build_acquisition_provenance,
    with_adopted_telemetry,
)
from rivretrieve._internal.recordings import read_recording

ROOT = Path(__file__).parents[1]
DATA = ROOT / "tests/recordings/br_ana"


def telemetry_evidence():
    path = DATA / "telemetry_15400000_2024-01-04_DIAS_30.recording.json"
    return parse_adopted_telemetry_evidence(
        (DATA / "manual-page11-acquisition.json").read_bytes(),
        (DATA / "manual-page11-derived.txt").read_bytes(),
        read_recording(path),
        str(path.relative_to(ROOT)),
    )


@pytest.fixture(scope="module")
def inputs():
    capture = read_capture_record(ROOT / "tests/test_data/br_ana_inventory/capture.json")
    native = read_native_table(ROOT / capture.native_table.repository_path)
    telemetry = telemetry_evidence()
    provenance = with_adopted_telemetry(
        build_acquisition_provenance(capture), capture, project_stations(native).data, telemetry
    )
    return capture, native, telemetry, provenance


def test_real_unacquired_availability_survives_provenance_normalization_and_artifact(inputs, tmp_path):
    capture, native, telemetry, provenance = inputs
    catalogue = build_catalogue(native, STATION_CATALOGUE_ORIGINS, provenance, telemetry)
    assert catalogue.station_products.height == 2 * capture.fluviometric_station_count
    assert set(catalogue.products["product_id"]) == {"stage_instantaneous", "discharge_instantaneous"}
    available = catalogue.station_products.filter(pl.col("availability") == "available")
    assert set(available["station_id"]) == {"15400000"}
    assert available.height == 2
    assert set(catalogue.station_products["availability"].cast(pl.String)) == {"available", "unknown"}
    assert catalogue.station_products["published_record_start_date"].null_count() == catalogue.station_products.height
    assert catalogue.station_products["published_record_end_date"].null_count() == catalogue.station_products.height
    evidence = normalize_provenance(
        provenance, stations=catalogue.stations, station_products=catalogue.station_products
    )
    validate_catalogue_locators(evidence, stations=catalogue.stations, station_products=catalogue.station_products)
    located = evidence.facts.filter(pl.col("locator_role") == "availability")
    assert located.height == catalogue.station_products.height
    assert_frame_equal(
        located.select("station_id", "product_id").sort("station_id", "product_id"),
        catalogue.station_products.select("station_id", "product_id"),
    )
    write_catalogue(catalogue, tmp_path)
    assert_frame_equal(pl.read_parquet(tmp_path / "station_products.parquet"), catalogue.station_products)


@pytest.mark.parametrize("marker", [AbsenceMarkerValue.NULL])
def test_unknown_availability_rejects_wrong_marker(inputs, marker):
    _, _, _, provenance = inputs
    bindings = list(provenance.fact_bindings)
    index = next(
        i
        for i, b in enumerate(bindings)
        if b.transformation and b.transformation.kind == "absence_marker" and b.facts[0].startswith("station_product:")
    )
    binding = bindings[index]
    bindings[index] = binding.model_copy(
        update={"transformation": binding.transformation.model_copy(update={"marker_value": marker})}
    )
    value = provenance.model_dump()
    value["fact_bindings"] = tuple(bindings)
    with pytest.raises(ValidationError, match="absence-marker"):
        AcquisitionProvenance.model_validate(value)


@pytest.mark.parametrize(
    "name",
    [
        "station_product:15400000:stage_instantaneous.availabilty",
        "station_product.availability",
        "station_product:15400000:stage_instantaneous.unit",
    ],
)
def test_marker_whitelist_does_not_expand_to_arbitrary_or_misspelled_facts(inputs, name):
    _, _, _, provenance = inputs
    bindings = list(provenance.fact_bindings)
    index = next(
        i
        for i, b in enumerate(bindings)
        if b.transformation and b.transformation.kind == "absence_marker" and b.facts[0].startswith("station_product:")
    )
    old = bindings[index].facts[0]
    bindings[index] = bindings[index].model_copy(update={"facts": (name,)})
    value = provenance.model_dump()
    value["fact_bindings"] = tuple(bindings)
    value["fact_universe"] = tuple(name if f == old else f for f in provenance.fact_universe)
    with pytest.raises(ValidationError):
        AcquisitionProvenance.model_validate(value)


@pytest.fixture(scope="module")
def catalogue(inputs):
    _, native, telemetry, provenance = inputs
    return build_catalogue(native, STATION_CATALOGUE_ORIGINS, provenance, telemetry)


def test_row_markers_use_one_carrier_index_not_per_pair_scans(catalogue, inputs, monkeypatch):
    from rivretrieve._internal.catalogues.artifact import _validate_absence_marker_values

    _, _, _, provenance = inputs
    original_select = pl.DataFrame.select
    original_filter = pl.DataFrame.filter
    index_reads = []
    scans = []

    def select(frame, *exprs, **kwargs):
        if frame is catalogue.station_products and exprs == ("station_id", "product_id", "availability"):
            index_reads.append(frame.height)
        return original_select(frame, *exprs, **kwargs)

    def filter_rows(frame, *predicates, **kwargs):
        if frame is catalogue.station_products:
            scans.append(frame.height)
        return original_filter(frame, *predicates, **kwargs)

    monkeypatch.setattr(pl.DataFrame, "select", select)
    monkeypatch.setattr(pl.DataFrame, "filter", filter_rows)
    _validate_absence_marker_values(
        pl.DataFrame([catalogue.provider_info]),
        catalogue.products,
        catalogue.stations,
        catalogue.station_products,
        provenance,
    )
    assert index_reads == [catalogue.station_products.height]
    assert len(scans) == 2  # Only the two global null published-record fields, not one scan per pair.


@pytest.mark.parametrize("normalized", [False, True])
def test_absence_marker_rejects_foreign_pair_and_nonunknown_carrier(catalogue, inputs, normalized):
    from rivretrieve._internal.catalogues.artifact import (
        CorruptCatalogArtifactError,
        packaged_catalogue_artifact_from_components,
    )

    _, _, _, provenance = inputs
    if normalized:
        provenance = normalize_provenance(
            provenance, stations=catalogue.stations, station_products=catalogue.station_products
        )
    pair = catalogue.station_products.filter(pl.col("availability") == "unknown").row(0, named=True)
    dropped = catalogue.station_products.filter(
        ~((pl.col("station_id") == pair["station_id"]) & (pl.col("product_id") == pair["product_id"]))
    )
    with pytest.raises(CorruptCatalogArtifactError, match="absent station-product"):
        packaged_catalogue_artifact_from_components(
            catalogue.provider_info, catalogue.products, catalogue.stations, dropped, acquisition_provenance=provenance
        )
    changed = catalogue.station_products.with_columns(
        pl.when((pl.col("station_id") == pair["station_id"]) & (pl.col("product_id") == pair["product_id"]))
        .then(pl.lit("available"))
        .otherwise(pl.col("availability"))
        .cast(catalogue.station_products.schema["availability"])
        .alias("availability")
    )
    with pytest.raises(CorruptCatalogArtifactError, match="exactly unknown"):
        packaged_catalogue_artifact_from_components(
            catalogue.provider_info, catalogue.products, catalogue.stations, changed, acquisition_provenance=provenance
        )


def test_normalized_marker_validation_rejects_mismatched_type(catalogue, inputs):
    from rivretrieve._internal.catalogues.evidence import CatalogueEvidence

    _, _, _, provenance = inputs
    evidence = normalize_provenance(
        provenance, stations=catalogue.stations, station_products=catalogue.station_products
    )
    transforms = tuple(
        t.model_copy(update={"marker_value": AbsenceMarkerValue.NULL})
        if t.kind == "absence_marker" and "Certified Fluviometrica" in t.name
        else t
        for t in evidence.header.transformations
    )
    header = evidence.header.model_copy(update={"transformations": transforms})
    with pytest.raises(ValidationError, match="absence-marker"):
        CatalogueEvidence(
            header=header,
            facts=evidence.facts,
            acquisitions=evidence.acquisitions,
            bindings=evidence.bindings,
            binding_facts=evidence.binding_facts,
            external_inputs=evidence.external_inputs,
        )


def test_manual_derived_excerpt_is_verified_not_pretended_publisher_recording():
    from rivretrieve._internal.issues import FatalContractError

    path = DATA / "telemetry_15400000_2024-01-04_DIAS_30.recording.json"
    with pytest.raises(FatalContractError, match="derived excerpt identity"):
        parse_adopted_telemetry_evidence(
            (DATA / "manual-page11-acquisition.json").read_bytes(),
            (DATA / "manual-page11-derived.txt").read_bytes() + b"changed",
            read_recording(path),
            str(path.relative_to(ROOT)),
        )
    evidence = telemetry_evidence()
    assert evidence.documentation.recording_ids == ()
    assert evidence.documentation.material.sha256 == "89e2929cb436241b4aae2bbb04c4077edd55379886f39c9a32eb7fec0c8faba3"


def test_each_candidate_links_only_containing_inventory_and_its_own_observation_evidence(inputs):
    capture, native, telemetry, provenance = inputs
    bindings = {b.facts[0]: b for b in provenance.fact_bindings if b.facts[0].startswith("station_product:")}
    native_rows = {row["codigoestacao"]: row for row in project_stations(native).data.iter_rows(named=True)}
    for station, product in (
        ("15400000", "stage_instantaneous"),
        ("15400000", "discharge_instantaneous"),
        (min(native_rows), "stage_instantaneous"),
    ):
        binding = bindings[f"station_product:{station}:{product}.availability"]
        row = native_rows[station]
        expected_inventory = {
            f"source.inventory.{r.recording_id}"
            for r in capture.responses
            if r.parameters == {"Unidade Federativa": row["UF_Estacao"]}
            or r.parameters == {"Código da Bacia": int(row["codigobacia"])}
        }
        refs = binding.transformation.external_inputs
        assert {r.fact for r in refs if r.source_id == "br_ana.hidro_inventory"} == expected_inventory
        assert any(r.fact == "source.ana.adopted_field_units_measurement_time" for r in refs)
        observed = [r.fact for r in refs if r.fact.startswith("source.adopted_observations.")]
        if (station, product) in telemetry.available_pairs:
            assert observed == [f"source.adopted_observations.{station}.{product}.nonnull"]
        else:
            assert observed == []
            assert any(r.fact == "source.ana.adopted_endpoint_availability_unacquired" for r in refs)
