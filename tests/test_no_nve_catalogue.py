"""Full offline certification of the NVE station catalogue."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
from rivretrieve._internal.acquisition_provenance import verify_provenance_recordings
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.catalogues.native import NativeTable, read_native_table
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.no_nve import generate_catalogue
from rivretrieve._internal.providers.no_nve.origins import (
    NATIVE_TABLE_BYTE_SIZE,
    NATIVE_TABLE_SEMANTIC_SHA256,
    NATIVE_TABLE_SHA256,
    STATION_CATALOGUE_ORIGINS,
    build_acquisition_provenance,
)
from tests._catalogue import catalogue_content_without_build_identity, catalogue_recording_paths

_ROOT = Path(__file__).parents[1]
_DATA = Path("tests/test_data")
_CAPTURE_RECORD = _DATA / "no_nve_station_catalogue_capture.json"
_NATIVE = Path("src/rivretrieve/_internal/providers/no_nve/catalogue/native.parquet")
_CATALOGUE = _ROOT / _NATIVE.parent


def _capture(retained_evidence_root):
    return generate_catalogue.read_capture_record(retained_evidence_root / _CAPTURE_RECORD)


def _catalogue(retained_evidence_root):
    return generate_catalogue.build_catalogue(
        read_native_table(retained_evidence_root / _NATIVE), STATION_CATALOGUE_ORIGINS
    )


@pytest.mark.governing(
    "tests/test_data/no_nve_station_catalogue_capture.json",
    "tests/test_data/no_nve_stations_active_0.json",
    "tests/test_data/no_nve_stations_active_1.json",
)
def test_complete_capture_identities_counts_and_request_set(retained_evidence_root) -> None:
    capture = _capture(retained_evidence_root)
    assert [item.activity for item in capture.responses] == [
        generate_catalogue.StationActivityFilter.ALL,
        generate_catalogue.StationActivityFilter.ACTIVE_ONLY,
    ]
    assert [item.requested_url for item in capture.responses] == [
        "https://hydapi.nve.no/api/v1/Stations?Active=1",
        "https://hydapi.nve.no/api/v1/Stations?Active=0",
    ]
    assert [
        (item.response_row_count, item.accepted_row_count, item.distinct_station_count) for item in capture.responses
    ] == [
        (4902, 4902, 4902),
        (1893, 1893, 1893),
    ]
    assert capture.overlap_station_count == 1893
    assert capture.distinct_station_count == 4902
    for response in capture.responses:
        body = (retained_evidence_root / response.repository_path).read_bytes()
        assert len(body) == response.byte_size
        assert hashlib.sha256(body).hexdigest() == response.sha256
        document = json.loads(body)
        assert document["currentLink"] == response.requested_url
        assert document["itemCount"] == len(document["data"]) == response.response_row_count
    all_rows = json.loads((retained_evidence_root / capture.responses[0].repository_path).read_bytes())["data"]
    active_only_rows = json.loads((retained_evidence_root / capture.responses[1].repository_path).read_bytes())["data"]
    all_by_id = {row["stationId"]: row for row in all_rows}
    active_only_by_id = {row["stationId"]: row for row in active_only_rows}
    assert set(active_only_by_id) < set(all_by_id)
    assert all(row["stationStatusName"] == "Aktiv" for row in active_only_rows)
    assert all(all_by_id[station_id] == row for station_id, row in active_only_by_id.items())


@pytest.mark.governing(
    "src/rivretrieve/_internal/providers/no_nve/catalogue/native.parquet",
    "tests/test_data/no_nve_station_catalogue_capture.json",
    "tests/test_data/no_nve_stations_active_0.json",
    "tests/test_data/no_nve_stations_active_1.json",
)
def test_client_retrieval_instants_are_distinct_from_server_created_at(retained_evidence_root) -> None:
    capture = _capture(retained_evidence_root)
    for response in capture.responses:
        document = json.loads((retained_evidence_root / response.repository_path).read_bytes())
        server_created_at = datetime.fromisoformat(document["createdAt"].replace("Z", "+00:00"))
        assert response.retrieved_at > server_created_at
        assert (response.retrieved_at - server_created_at).total_seconds() < 60

    native = read_native_table(retained_evidence_root / _NATIVE)
    assert set(native.data["retrieved_at"]) == {capture.responses[0].retrieved_at}
    assert native.data["retrieved_at"].item(0) != datetime.fromisoformat(
        json.loads((retained_evidence_root / capture.responses[0].repository_path).read_bytes())["createdAt"].replace(
            "Z", "+00:00"
        )
    )


@pytest.mark.governing(
    "src/rivretrieve/_internal/providers/no_nve/catalogue/native.parquet",
    "tests/test_data/no_nve_station_catalogue_capture.json",
    "tests/test_data/no_nve_stations_active_0.json",
    "tests/test_data/no_nve_stations_active_1.json",
)
def test_full_responses_materialize_the_exact_committed_semantic_frame(retained_evidence_root) -> None:
    capture = _capture(retained_evidence_root)
    fresh = generate_catalogue.materialize_captured_native_table(capture, retained_evidence_root)
    committed = read_native_table(
        (retained_evidence_root / _NATIVE),
        expected_sha256=NATIVE_TABLE_SHA256,
        expected_byte_size=NATIVE_TABLE_BYTE_SIZE,
    )
    pl_testing.assert_frame_equal(fresh.data, committed.data, check_exact=True)
    assert (
        hashlib.sha256((retained_evidence_root / _NATIVE).read_bytes()).hexdigest()
        == capture.native_table.sha256
        == NATIVE_TABLE_SHA256
    )
    assert (
        len((retained_evidence_root / _NATIVE).read_bytes()) == capture.native_table.byte_size == NATIVE_TABLE_BYTE_SIZE
    )
    assert generate_catalogue.native_table_semantic_digest(fresh) == capture.native_table.semantic_sha256
    assert generate_catalogue.native_table_semantic_digest(committed) == NATIVE_TABLE_SEMANTIC_SHA256


@pytest.mark.governing(
    "src/rivretrieve/_internal/providers/no_nve/catalogue/native.parquet",
    "tests/test_data/no_nve_station_catalogue_capture.json",
    "tests/test_data/no_nve_stations_active_0.json",
    "tests/test_data/no_nve_stations_active_1.json",
)
def test_offline_native_rematerialization_is_byte_identical(retained_evidence_root, tmp_path: Path) -> None:
    output = tmp_path / "native.parquet"
    assert (
        generate_catalogue.main(
            [
                "--materialize-record",
                str(retained_evidence_root / _CAPTURE_RECORD),
                "--native-out",
                str(output),
                "--repository-root",
                str(retained_evidence_root),
            ]
        )
        == 0
    )
    assert output.read_bytes() == (retained_evidence_root / _NATIVE).read_bytes()


@pytest.mark.derived("src/rivretrieve/_internal/providers/no_nve/catalogue/native.parquet")
def test_build_populates_exact_attested_catalogue(retained_evidence_root) -> None:
    catalogue = _catalogue(retained_evidence_root)
    assert (catalogue.stations.height, catalogue.products.height, catalogue.station_products.height) == (4902, 9, 44118)
    assert catalogue.station_products.filter(pl.col("availability") == "available").height == 14847
    assert catalogue.station_products.filter(pl.col("availability") == "unavailable").height == 29271
    assert catalogue.station_products["published_record_start_date"].null_count() == 44118
    assert catalogue.station_products["published_record_end_date"].null_count() == 44118
    assert catalogue.provider_info["catalogue_version"] == "2026-09-04"
    assert set(catalogue.products["product_id"]) == generate_catalogue.EXPECTED_PRODUCT_IDS
    assert set(catalogue.stations["crs"]) == {"unknown"}
    assert catalogue.acquisition_provenance.native_table is not None
    assert catalogue.acquisition_provenance.withheld_facts == ()


@pytest.mark.derived("src/rivretrieve/_internal/providers/no_nve/catalogue/native.parquet")
@pytest.mark.recorded(*catalogue_recording_paths("no_nve"))
def test_build_is_network_free_and_byte_identical(
    retained_evidence_root, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, catalogue_build_inputs_path
) -> None:
    from rivretrieve._internal.providers.no_nve.origins import build_acquisition_provenance

    build_inputs_path = catalogue_build_inputs_path(build_acquisition_provenance())

    def refuse(*args: object, **kwargs: object) -> object:
        raise AssertionError("network access during native catalogue build")

    monkeypatch.setattr("rivretrieve._internal.transport.HttpClient.send", refuse)
    output = tmp_path / "catalogue"
    assert (
        generate_catalogue.main(
            [
                "--build-inputs",
                str(build_inputs_path),
                "--native",
                str(retained_evidence_root / _NATIVE),
                "--out",
                str(output),
            ]
        )
        == 0
    )
    for name in (
        "provider.json",
        "products.parquet",
        "stations.parquet",
        "station_products.parquet",
        "provenance.json",
        "provenance_facts.parquet",
        "provenance_acquisitions.parquet",
        "provenance_bindings.parquet",
        "provenance_binding_facts.parquet",
        "provenance_external_inputs.parquet",
        "format.json",
        "source_series.json",
        "series_claims.parquet",
        "station_metadata.parquet",
    ):
        assert catalogue_content_without_build_identity(
            name, (output / name).read_bytes()
        ) == catalogue_content_without_build_identity(name, (_CATALOGUE / name).read_bytes())


def test_public_discovery_selects_a_real_norwegian_edge() -> None:
    selection = rr.find(provider="no_nve", station="1.200.0", quantity="stage", frequency="daily", statistic="mean")
    assert len(selection.series) == 1
    assert (selection.series[0].provider_id, selection.series[0].station_id, selection.series[0].product_id) == (
        "no_nve",
        "1.200.0",
        "stage_daily_mean",
    )
    assert selection.empty_reason is None
    assert "stage_daily_mean" in rr.products(provider="no_nve")


@pytest.mark.governing(
    "src/rivretrieve/_internal/providers/no_nve/catalogue/native.parquet",
    "tests/test_data/no_nve_station_catalogue_capture.json",
    "tests/test_data/no_nve_stations_active_0.json",
    "tests/test_data/no_nve_stations_active_1.json",
    "tests/test_data/no_nve_swagger.json",
    "tests/test_data/no_nve_terms_licence.html",
)
def test_packaged_provenance_closes_capture_and_canonical_facts(retained_evidence_root) -> None:
    provenance = build_acquisition_provenance()
    verify_provenance_recordings(provenance, retained_evidence_root)
    bound = {fact for binding in provenance.fact_bindings for fact in binding.facts}
    assert set(provenance.fact_universe) == bound
    assert [acquisition.requested_from for acquisition in provenance.source_records[0].acquisitions[2:]] == [
        ("https://hydapi.nve.no/api/v1/Stations?Active=1",),
        ("https://hydapi.nve.no/api/v1/Stations?Active=0",),
    ]
    assert all(acquisition.material is not None for acquisition in provenance.source_records[0].acquisitions[1:])


@pytest.mark.derived("src/rivretrieve/_internal/providers/no_nve/catalogue/native.parquet")
def test_native_value_mutation_is_rejected(retained_evidence_root) -> None:
    native = read_native_table(retained_evidence_root / _NATIVE)
    mutated = NativeTable(
        native.data.with_columns(
            pl.when(pl.col("stationId") == "1.200.0").then(None).otherwise(pl.col("latitude")).alias("latitude")
        )
    )
    with pytest.raises(FatalContractError, match="source field types"):
        generate_catalogue.build_catalogue(mutated, STATION_CATALOGUE_ORIGINS)


def test_brazil_certified_candidates_are_selectable_without_inferred_availability() -> None:
    selection = rr.find(provider="br_ana")
    assert len(selection.series) == 6 * 17_914
    assert rr.products(provider="br_ana") == [
        "discharge_daily_mean_bruto",
        "discharge_daily_mean_consistido",
        "discharge_instantaneous",
        "stage_daily_mean_bruto",
        "stage_daily_mean_consistido",
        "stage_instantaneous",
    ]
    artifact = load_packaged_catalogue_artifact(Path("src/rivretrieve/_internal/providers/br_ana/catalogue"))
    assert set(artifact.station_products["availability"]) == {"available", "unknown"}
    observed = artifact.station_products.filter(pl.col("availability") == "available")
    assert set(observed.select("station_id", "product_id").iter_rows()) == {
        ("15400000", "discharge_instantaneous"),
        ("15400000", "stage_instantaneous"),
        ("15400000", "discharge_daily_mean_bruto"),
        ("15400000", "discharge_daily_mean_consistido"),
        ("15400000", "stage_daily_mean_bruto"),
        ("15400000", "stage_daily_mean_consistido"),
    }
