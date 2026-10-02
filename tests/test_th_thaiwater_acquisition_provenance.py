from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.acquisition_provenance import ExternalFactReference
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.catalogues.native import read_native_table
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.th_thaiwater import generate_catalogue
from rivretrieve._internal.providers.th_thaiwater.declaration import declaration
from rivretrieve._internal.providers.th_thaiwater.generate_catalogue import GraphAvailabilityEvidence
from rivretrieve._internal.providers.th_thaiwater.origins import build_acquisition_provenance
from tests._provenance import legacy_provenance

LEDGER_PATH = (
    Path(__file__).parents[1] / "maintenance/catalogue/th_thaiwater/inventory/governing_station_product_evidence.csv"
)


def _evidence() -> GraphAvailabilityEvidence:
    return GraphAvailabilityEvidence(LEDGER_PATH.read_bytes())


@pytest.mark.derived("src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
def test_thailand_provenance_maps_every_row_to_its_exact_native_agency(
    retained_evidence_root: Path,
) -> None:
    provenance = load_packaged_catalogue_artifact(declaration.catalogue).acquisition_provenance
    assert provenance is not None
    provenance = legacy_provenance(provenance)
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

    native = pl.read_parquet(
        retained_evidence_root / "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet"
    )
    source_by_station = {
        str(station): f"th_agency_{agency}" for station, agency in native.select("station.id", "agency.id").iter_rows()
    }
    assert {
        binding.fact_group.removeprefix("station:"): binding.source_id for binding in station_bindings
    } == source_by_station


def test_thailand_product_meanings_and_units_are_source_bound_while_period_is_unknown() -> None:
    provenance = load_packaged_catalogue_artifact(declaration.catalogue).acquisition_provenance
    assert provenance is not None
    provenance = legacy_provenance(provenance)
    assert provenance is not None
    source = next(item for item in provenance.source_records if item.source_id == "th_agency_9")
    evidence_ids = {item.evidence_id for item in source.evidence}
    assert {"th_thaiwater_graph_field_mapping", "th_thaiwater_graph_page"} <= evidence_ids
    binding = next(item for item in provenance.fact_bindings if item.fact_group == "source_product_semantics")
    assert binding.source_id == "th_agency_9"
    assert binding.acquisition_id == "product_semantics_capture_2026_09_02"
    canonical = next(item for item in provenance.fact_bindings if item.fact_group == "canonical_product_carrier")
    assert canonical.transformation is not None
    assert canonical.transformation.external_inputs == (
        ExternalFactReference(source_id="th_agency_9", fact="source.product.thaiwater_graph_field_meanings_and_units"),
    )


def test_thailand_canonical_product_definition_is_rivretrieve_owned() -> None:
    provenance = load_packaged_catalogue_artifact(declaration.catalogue).acquisition_provenance
    assert provenance is not None
    provenance = legacy_provenance(provenance)
    assert provenance is not None
    assert not any(binding.fact_group == "product_identity" for binding in provenance.fact_bindings)
    canonical = next(
        binding for binding in provenance.fact_bindings if binding.fact_group == "canonical_product_carrier"
    )
    assert canonical.source_id is None
    assert canonical.acquisition_id is None
    assert canonical.transformation is not None
    assert canonical.transformation.name == "ThaiWater graph fields to conservative canonical product definitions"
    assert canonical.transformation.external_inputs == (
        ExternalFactReference(source_id="th_agency_9", fact="source.product.thaiwater_graph_field_meanings_and_units"),
    )
    assert set(canonical.facts) == {fact for fact in provenance.fact_universe if fact.startswith("product.")}


def test_every_governing_pair_is_bound_to_its_actual_acquisition_and_agency() -> None:
    artifact = load_packaged_catalogue_artifact(declaration.catalogue)
    provenance = artifact.acquisition_provenance
    assert provenance is not None
    provenance = legacy_provenance(provenance)
    assert provenance is not None
    assert provenance.withheld_facts == ()
    ledger = list(csv.DictReader(io.StringIO(LEDGER_PATH.read_text())))
    bindings = {
        binding.fact_group: binding
        for binding in provenance.fact_bindings
        if binding.fact_group.startswith("station_product:")
    }
    acquisitions = {
        (source.source_id, acquisition.acquisition_id): acquisition
        for source in provenance.source_records
        for acquisition in source.acquisitions
    }
    catalogue = {(row["station_id"], row["product_id"]): row for row in artifact.station_products.to_dicts()}
    assert len(bindings) == len(catalogue) == len(ledger) == 1650
    for row in ledger:
        binding = bindings[f"station_product:{row['station_id']}:{row['product_id']}:availability"]
        assert binding.source_id == row["source_id"]
        assert binding.acquisition_id == row["request_id"]
        assert binding.source_id is not None and binding.acquisition_id is not None
        acquisition = acquisitions[(binding.source_id, binding.acquisition_id)]
        assert acquisition.requested_from == (row["request_url"],)
        assert acquisition.retrieved_at_start == datetime.fromisoformat(row["retrieved_at"])
        assert acquisition.recording_ids == ()  # Private material is not a public RecordingReference.
        assert acquisition.material is not None
        assert acquisition.material.filename == Path(row["evidence_body"]).name
        assert acquisition.material.byte_count == int(row["response_bytes"])
        assert acquisition.material.sha256 == row["response_sha256"]
        pair = catalogue[(row["station_id"], row["product_id"])]
        assert pair["availability"] == row["availability"]
        assert pair["last_catalogue_check"] == datetime.fromisoformat(row["retrieved_at"]).date()
        assert row["request_id"] in pair["availability_reason"]
        assert row["native_field"] in pair["availability_reason"]
        assert row["window_start"] in pair["availability_reason"]
        assert row["window_end"] in pair["availability_reason"]
        if row["availability"] == "unknown":
            assert "null-only" in pair["availability_reason"]
        else:
            assert f"{row['nonnull_observations']} non-null" in pair["availability_reason"]
    graph_acquisitions: set[tuple[str, str]] = set()
    for binding in bindings.values():
        assert binding.source_id is not None and binding.acquisition_id is not None
        graph_acquisitions.add((binding.source_id, binding.acquisition_id))
    assert len(graph_acquisitions) == 825
    assert Counter(source for source, _ in graph_acquisitions) == {
        "th_agency_8": 73,
        "th_agency_9": 329,
        "th_agency_12": 328,
        "th_agency_91": 95,
    }
    acquisition_dates = []
    for key in graph_acquisitions:
        retrieved_at = acquisitions[key].retrieved_at_start
        assert retrieved_at is not None
        acquisition_dates.append(retrieved_at.date().isoformat())
    assert Counter(acquisition_dates) == {
        "2026-09-11": 12,
        "2026-09-13": 813,
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("station_id", "999999999"),
        ("product_id", "stage_instantaneous"),
        ("native_field", "waterlevel_msl"),
        ("source_id", "th_agency_8"),
        ("response_sha256", "0" * 64),
        ("response_bytes", "1"),
        ("retrieved_at", "2026-09-12T18:03:34Z"),
        ("request_url", "https://example.org/forged"),
        ("status", "empty_in_tested_window"),
        ("availability", "unknown"),
        ("nonnull_observations", "0"),
    ],
)
def test_reviewed_ledger_rejects_identity_hash_date_and_status_tampering(field: str, value: str) -> None:
    original = LEDGER_PATH.read_bytes()
    first_row = original.splitlines()[1]
    fields = original.splitlines()[0].decode().split(",")
    cells = first_row.decode().split(",")
    cells[fields.index(field)] = value
    altered = original.replace(first_row, ",".join(cells).encode(), 1)
    with pytest.raises(FatalContractError, match="availability evidence digest mismatch"):
        GraphAvailabilityEvidence(altered)


@pytest.mark.governing(
    "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet",
    full_verification=("th_thaiwater",),
)
def test_native_agency_disagreement_with_reviewed_acquisition_fails(
    retained_evidence_root: Path,
) -> None:
    native = read_native_table(
        retained_evidence_root / "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet"
    )
    from rivretrieve._internal.catalogues.native import NativeTable

    altered = native.data.with_columns(
        pl.when(pl.col("station.id") == "1").then(8).otherwise(pl.col(column)).alias(column)
        for column in ("agency.id", "station.agency_id")
    )
    with pytest.raises(FatalContractError, match="unverified evidence agency mapping"):
        build_acquisition_provenance(NativeTable(altered), _evidence())


@pytest.mark.governing(
    "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet",
    full_verification=("th_thaiwater",),
)
def test_thailand_cli_rejects_native_byte_substitution(retained_evidence_root: Path, tmp_path: Path) -> None:
    native = tmp_path / "native.parquet"
    native.write_bytes(
        (
            retained_evidence_root / "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet"
        ).read_bytes()
        + b"changed"
    )
    with pytest.raises(FatalContractError, match="native table digest mismatch: expected .* observed"):
        generate_catalogue.main(
            [
                "--evidence-root",
                str(retained_evidence_root),
                "--native",
                str(native),
                "--availability-evidence",
                str(LEDGER_PATH),
                "--out",
                str(tmp_path / "out"),
            ]
        )


@pytest.mark.governing(
    "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet",
    full_verification=("th_thaiwater",),
)
def test_thailand_cli_invokes_recording_verification(
    retained_evidence_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject(*_args: object) -> None:
        raise FatalContractError("recording verification invoked")

    monkeypatch.setattr(generate_catalogue, "verify_provenance_recordings", reject)
    with pytest.raises(FatalContractError, match="recording verification invoked"):
        generate_catalogue.main(
            [
                "--evidence-root",
                str(retained_evidence_root),
                "--native",
                str(
                    retained_evidence_root / "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet"
                ),
                "--availability-evidence",
                str(LEDGER_PATH),
                "--out",
                str(tmp_path),
            ]
        )


@pytest.mark.derived("src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
def test_thailand_station_carrier_has_exact_multi_agency_lineage(
    retained_evidence_root: Path,
) -> None:
    provenance = build_acquisition_provenance(
        read_native_table(
            retained_evidence_root / "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet"
        ),
        _evidence(),
    )
    station_carrier = next(
        binding for binding in provenance.fact_bindings if binding.fact_group == "canonical_station_carrier"
    )
    assert station_carrier.source_id is None
    assert station_carrier.transformation is not None
    referenced_sources = {reference.source_id for reference in station_carrier.transformation.external_inputs}
    assert referenced_sources == {"th_agency_8", "th_agency_9", "th_agency_12", "th_agency_91"}


@pytest.mark.recorded(
    "tests/test_data/th_thaiwater_official_app.chunk-2026-09-02.js",
    "tests/test_data/th_thaiwater_official_evidence_manifest-2026-09-02.json",
    "tests/test_data/th_thaiwater_official_water_wl-2026-09-02.html",
)
def test_retained_thaiwater_official_evidence_matches_capture_manifest(retained_evidence_root: Path) -> None:
    data = retained_evidence_root / "tests/test_data"
    manifest = json.loads((data / "th_thaiwater_official_evidence_manifest-2026-09-02.json").read_text())
    retained = {
        "official_water_wl.html": data / "th_thaiwater_official_water_wl-2026-09-02.html",
        "official_app.chunk.js": data / "th_thaiwater_official_app.chunk-2026-09-02.js",
    }
    captures = {item["file"]: item for item in manifest["captures"]}

    assert set(captures) == set(retained)
    for source_name, path in retained.items():
        assert path.stat().st_size == captures[source_name]["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == captures[source_name]["sha256"]

    bundle = retained["official_app.chunk.js"].read_bytes()
    assert b"e.data.graph_data.filter(e=>null!==e.value):e.data.graph_data.filter(e=>null!==e.discharge)" in bundle
    assert "ระดับน้ำ".encode() in bundle
    assert "ม.รทก.".encode() in bundle
    assert "ปริมาณน้ำท่า".encode() in bundle
    assert "(ม.3/วิ.)".encode() in bundle


@pytest.mark.derived("src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
def test_platform_identity_does_not_claim_the_agency_supplied_measurements(
    retained_evidence_root: Path,
) -> None:
    provenance = build_acquisition_provenance(
        read_native_table(
            retained_evidence_root / "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet"
        ),
        _evidence(),
    )
    bindings = {binding.fact_group: binding for binding in provenance.fact_bindings}
    platform = bindings["canonical_platform_carrier"]
    assert platform.transformation is not None
    assert all(fact.startswith("provider.") for fact in platform.facts)
    assert platform.transformation.external_inputs == (
        ExternalFactReference(source_id="th_agency_9", fact="source.provider.thaiwater_platform_identity"),
    )
    relations = bindings["canonical_station_product_carrier"]
    assert relations.transformation is not None
    assert all(fact.startswith("station_product.") for fact in relations.facts)
    expected = {
        (binding.source_id, binding.facts[0])
        for binding in provenance.fact_bindings
        if binding.fact_group.startswith("station_product:")
    }
    assert len(expected) == 1650
    assert {(item.source_id, item.fact) for item in relations.transformation.external_inputs} == expected
