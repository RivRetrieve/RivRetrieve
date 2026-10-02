"""ANA conventional catalogue : ReviewedEvidence × NativeInventory → SixProductCatalogue."""

import json
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.catalogues.evidence import normalize_provenance, validate_catalogue_locators
from rivretrieve._internal.catalogues.native import read_native_table
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.br_ana.capture import parse_conventional_daily_evidence, read_capture_record
from rivretrieve._internal.providers.br_ana.generate_catalogue import build_catalogue, project_stations
from rivretrieve._internal.providers.br_ana.origins import (
    STATION_CATALOGUE_ORIGINS,
    build_acquisition_provenance,
    with_observation_products,
)
from rivretrieve._internal.recordings import read_recording
from tests.test_br_ana_catalogue_telemetry import telemetry_evidence

DOCUMENTS = (
    "hidro-1.4-conventional-dictionary-derived.json",
    "hidro-sqlserver-selected-views-derived.json",
    "hidro-extraction-manifest.json",
    "daily-source-comparison-report.md",
    "daily-correspondence-identities.json",
    "paired-stage-2020-comparison.json",
    "paired-stage-2024-comparison.json",
    "paired-discharge-2020-comparison.json",
    "paired-discharge-2024-comparison.json",
)
DAILY_PRODUCTS = {
    "discharge_daily_mean_bruto",
    "discharge_daily_mean_consistido",
    "stage_daily_mean_bruto",
    "stage_daily_mean_consistido",
}


def daily_inputs(retained_evidence_root):
    return (
        {name: ((retained_evidence_root / "tests/recordings/br_ana") / name).read_bytes() for name in DOCUMENTS},
        tuple(
            (str(p.relative_to(retained_evidence_root)), read_recording(p))
            for p in sorted((retained_evidence_root / "tests/recordings/br_ana").glob("HidroSerie*.recording.json"))
            if "_2023-" not in p.name
        ),
        tuple(
            (str(p.relative_to(retained_evidence_root)), read_recording(p))
            for p in sorted(
                ((retained_evidence_root / "tests/recordings/br_ana") / "correspondence").glob("*.recording.json")
            )
        ),
    )


def test_daily_documentation_and_variants_are_established_from_original_recordings(retained_evidence_root):
    daily = parse_conventional_daily_evidence(*daily_inputs(retained_evidence_root))
    assert daily.available_pairs == frozenset(("15400000", product) for product in DAILY_PRODUCTS)
    assert daily.documentation.recording_ids == ()
    assert daily.documentation.material is not None
    assert daily.documentation.material.sha256 == "68a8da15e82d254e631431fd18a64c29f1ad1e46b58e6c94b3aa1f3f3e33d373"
    assert len(daily.observations) == 6


@pytest.mark.parametrize("name", DOCUMENTS)
def test_source_definition_gate_rejects_changed_reviewed_material(retained_evidence_root, name):
    documents, recordings, comparisons = daily_inputs(retained_evidence_root)
    documents[name] += b"changed"
    with pytest.raises(FatalContractError, match="source-definition identity"):
        parse_conventional_daily_evidence(documents, recordings, comparisons)


def test_source_correspondence_gate_requires_the_actual_originals(retained_evidence_root):
    documents, recordings, comparisons = daily_inputs(retained_evidence_root)
    with pytest.raises(FatalContractError, match="incomplete"):
        parse_conventional_daily_evidence(documents, recordings, comparisons[:-1])


def test_daily_evidence_does_not_promote_instantaneous_rows_or_another_consistency(retained_evidence_root):
    documents, recordings, comparisons = daily_inputs(retained_evidence_root)
    january = tuple(item for item in recordings if "Cotas_15400000_2024-01" in item[0])
    daily = parse_conventional_daily_evidence(documents, january, comparisons)
    assert daily.available_pairs == frozenset({("15400000", "stage_daily_mean_bruto")})
    # Contract mutation of a real response, never an invented observation expectation.
    path, original = january[0]
    payload = json.loads(original.content)
    payload["items"] = [row for row in payload["items"] if row["Mediadiaria"] == "0"]
    only_instantaneous = replace(original, content=json.dumps(payload).encode())
    assert not parse_conventional_daily_evidence(documents, ((path, only_instantaneous),), comparisons).available_pairs


@pytest.fixture(scope="module")
def catalogue_inputs(retained_evidence_root):
    capture = read_capture_record(retained_evidence_root / "tests/test_data/br_ana_inventory/capture.json")
    native = read_native_table(retained_evidence_root / capture.native_table.repository_path)
    telemetry = telemetry_evidence(retained_evidence_root)
    daily = parse_conventional_daily_evidence(*daily_inputs(retained_evidence_root))
    provenance = with_observation_products(
        build_acquisition_provenance(capture), capture, project_stations(native).data, telemetry, daily
    )
    catalogue = build_catalogue(native, STATION_CATALOGUE_ORIGINS, provenance, telemetry, daily)
    return capture, native, telemetry, daily, provenance, catalogue


def test_six_products_preserve_native_population_and_telemetry(catalogue_inputs):
    capture, native, telemetry, _, provenance, catalogue = catalogue_inputs
    assert set(catalogue.products["product_id"]) == DAILY_PRODUCTS | {"stage_instantaneous", "discharge_instantaneous"}
    assert catalogue.station_products.height == 6 * capture.fluviometric_station_count
    assert catalogue.acquired_station_count == capture.distinct_station_count
    old_provenance = with_observation_products(
        build_acquisition_provenance(capture), capture, project_stations(native).data, telemetry
    )
    old = build_catalogue(native, STATION_CATALOGUE_ORIGINS, old_provenance, telemetry)
    assert_frame_equal(catalogue.stations, old.stations)
    assert_frame_equal(catalogue.products.filter(~pl.col("product_id").is_in(DAILY_PRODUCTS)), old.products)
    assert_frame_equal(
        catalogue.station_products.filter(~pl.col("product_id").is_in(DAILY_PRODUCTS)), old.station_products
    )
    assert catalogue.station_products.filter(pl.col("availability") == "available").height == 6
    assert set(catalogue.station_products["availability"].cast(pl.String)) == {"available", "unknown"}
    for col in ("published_record_start_date", "published_record_end_date"):
        assert catalogue.station_products[col].null_count() == catalogue.station_products.height
    normalized = normalize_provenance(
        provenance, stations=catalogue.stations, station_products=catalogue.station_products
    )
    validate_catalogue_locators(normalized, stations=catalogue.stations, station_products=catalogue.station_products)
    assert normalized.facts.filter(pl.col("locator_role") == "availability").height == catalogue.station_products.height


def test_exact_variant_availability_has_only_its_own_recordings(catalogue_inputs):
    _, _, _, daily, provenance, _ = catalogue_inputs
    bindings = {b.facts[0]: b for b in provenance.fact_bindings}
    for product in DAILY_PRODUCTS:
        binding = bindings[f"station_product:15400000:{product}.availability"]
        refs = binding.transformation.external_inputs
        actual = {ref.fact for ref in refs if ref.fact.startswith("source.daily_observations.")}
        expected = {
            f"source.daily_observations.{record.recording_id}.15400000.{product}.nonnull"
            for record, pairs in daily.observations
            if ("15400000", product) in pairs
        }
        assert actual == expected
        assert not any("adopted" in ref.fact for ref in refs)


def test_six_product_packaged_artifact_rebuild_is_byte_identical(catalogue_inputs, tmp_path):
    from rivretrieve._internal.providers.br_ana.generate_catalogue import write_catalogue

    catalogue = catalogue_inputs[-1]
    write_catalogue(catalogue, tmp_path)
    packaged = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/br_ana/catalogue"
    for path in tmp_path.iterdir():
        assert path.read_bytes() == (packaged / path.name).read_bytes(), path.name


def test_daily_catalogue_labels_do_not_claim_interval_anchors(catalogue_inputs):
    from rivretrieve._internal.providers.br_ana.catalogue_series import describe_catalogue
    from rivretrieve._internal.providers.br_ana.config import config

    descriptions = describe_catalogue(catalogue_inputs[-1].public_artifact, config=config())
    for item in descriptions.descriptions:
        facts = item.facts[0]
        if item.product_id in DAILY_PRODUCTS:
            assert facts.label_time == "00:00"
            assert facts.timestamp_anchor.value is None
            assert facts.timestamp_anchor.evidence == ()
        else:
            assert facts.timestamp_anchor.value == "measurement_time"
            assert facts.timestamp_anchor.evidence
