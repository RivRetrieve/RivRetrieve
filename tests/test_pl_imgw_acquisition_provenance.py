from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal.catalogue_origins import (
    Evidence,
    NotPublished,
    Withheld,
    validate_catalogue_origins,
)
from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.catalogues.artifact import CorruptCatalogArtifactError, load_packaged_catalogue_artifact
from rivretrieve._internal.catalogues.native import read_native_table
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.private_source_verification import (
    FORWARDED_EMAIL_BYTES,
    FORWARDED_EMAIL_SHA256,
    ORIGINAL_EMAIL_BYTES,
    ORIGINAL_EMAIL_SHA256,
    WORKBOOK_BYTES,
    WORKBOOK_SHA256,
    PrivateEmailVerificationRecord,
    parse_private_email_verification,
    serialize_private_email_verification,
    verify_original_grdc_email,
)
from rivretrieve._internal.providers.pl_imgw import generate_catalogue
from rivretrieve._internal.providers.pl_imgw.declaration import declaration
from rivretrieve._internal.providers.pl_imgw.origins import (
    NATIVE_TABLE_SHA256,
    STATION_CATALOGUE_ORIGINS,
    build_acquisition_provenance,
)

CATALOGUE = Path("src/rivretrieve/_internal/providers/pl_imgw/catalogue")
NATIVE = CATALOGUE / "native.parquet"
TERMS = Path("tests/test_data/pl_imgw_terms_regulations.html")


def test_poland_provenance_is_closed_and_credits_fields_without_provider_inheritance() -> None:
    provenance = build_acquisition_provenance()
    assert [source.source_id for source in provenance.source_records] == ["sr.pl.imgw", "sr.pl.grdc"]
    grdc = provenance.source_records[1]
    assert grdc.issuer == "Global Runoff Data Centre"
    assert grdc.operator == "Bundesanstalt für Gewässerkunde"
    assert all(statement.kind != "citation" for statement in grdc.statements)

    by_fact = {fact: binding.source_id for binding in provenance.fact_bindings for fact in binding.facts}
    assert by_fact["station.station_id"] == "sr.pl.grdc"
    assert by_fact["station.latitude"] == "sr.pl.grdc"
    assert by_fact["station.longitude"] == "sr.pl.grdc"
    assert by_fact["provider.provider_id"] == "sr.pl.imgw"
    assert by_fact["provider.license"] is None
    assert by_fact["provider.citation"] is None
    compatibility = next(
        binding
        for binding in provenance.fact_bindings
        if binding.fact_group == "rivretrieve_provider_terms_compatibility"
    )
    assert compatibility.transformation is not None
    assert {reference.source_id for reference in compatibility.transformation.external_inputs} == {
        "sr.pl.imgw",
        "sr.pl.grdc",
    }
    assert by_fact["product.product_id"] == "sr.pl.imgw"
    assert by_fact["station_product.availability_reason"] == "sr.pl.imgw"
    assert by_fact["observation.value"] == "sr.pl.imgw"
    assert by_fact["station.crs"] is None
    crs_binding = next(binding for binding in provenance.fact_bindings if "station.crs" in binding.facts)
    assert crs_binding.source_id is None
    assert crs_binding.acquisition_id is None
    assert crs_binding.transformation is not None
    assert crs_binding.transformation.name.startswith("RivRetrieve unknown marker")
    assert [(reference.source_id, reference.fact) for reference in crs_binding.transformation.external_inputs] == [
        ("sr.pl.grdc", "source.grdc.horizontal_crs")
    ]
    assert [(item.fact_group, item.facts, item.reason, item.source_id) for item in provenance.withheld_facts] == [
        (
            "grdc_horizontal_crs",
            ("source.grdc.horizontal_crs",),
            "no_acquisition_record_established",
            "sr.pl.grdc",
        )
    ]


def test_poland_source_null_not_published_and_withheld_crs_are_distinct() -> None:
    provenance = build_acquisition_provenance()
    by_fact = {fact: binding for binding in provenance.fact_bindings for fact in binding.facts}
    withheld = {fact for group in provenance.withheld_facts for fact in group.facts}

    artifact = load_packaged_catalogue_artifact(declaration.catalogue, on_issue="raise")
    assert artifact.station_products["published_record_start_date"].null_count() == artifact.station_products.height
    assert by_fact["station_product.published_record_start_date"].source_id == "sr.pl.imgw"
    assert "station_product.published_record_start_date" not in withheld

    assert isinstance(STATION_CATALOGUE_ORIGINS["crs"], Withheld)
    assert NotPublished(Evidence("https://example.test/source-crs")) != STATION_CATALOGUE_ORIGINS["crs"]
    assert "source.grdc.horizontal_crs" in withheld
    assert by_fact["station.crs"].source_id is None
    assert artifact.stations["crs"].unique().to_list() == ["unknown"]


def test_poland_withheld_crs_origin_rejects_an_asserted_crs() -> None:
    native = read_native_table(NATIVE)
    claimed = generate_catalogue.build_stations(native).with_columns(pl.lit("EPSG:4326").alias("crs"))

    issues = validate_catalogue_origins(ProviderId("pl_imgw"), STATION_CATALOGUE_ORIGINS, native, claimed)

    assert [issue.code for issue in issues] == ["catalogue_origin.withheld_marker_mismatch"]


def test_poland_recovery_and_corroboration_are_distinct_acquisitions() -> None:
    provenance = build_acquisition_provenance()
    grdc = next(source for source in provenance.source_records if source.source_id == "sr.pl.grdc")
    recovery, workbook = grdc.acquisitions
    assert recovery.method == "repository_recovery"
    assert recovery.instant_type == "provenance_lower_bound"
    assert recovery.retrieved_at_start.isoformat() == "2025-10-10T18:46:34+00:00"
    assert "f67f6d8507a55144bf235feb3f27f65648b90f83" in recovery.requested_from[0]
    assert workbook.method == "corroborating_receipt"
    assert workbook.instant_type == "corroborating_receipt"
    assert workbook.retrieved_at_start.isoformat() == "2025-11-07T12:40:38+00:00"
    assert workbook.material is not None
    assert workbook.material.filename == "Metadata_GRDC_30.10.2025.xlsx"
    assert workbook.material.byte_count == WORKBOOK_BYTES == 116_301
    assert workbook.material.sha256 == WORKBOOK_SHA256


def test_poland_native_identity_and_raw_substitution_refusal(tmp_path: Path) -> None:
    provenance = build_acquisition_provenance()
    assert provenance.native_table.repository_path == str(NATIVE)
    assert provenance.native_table.revision == "c9c81934bb1773b0286c968f4fd7323f724c71ac"
    assert provenance.native_table.sha256 == NATIVE_TABLE_SHA256 == hashlib.sha256(NATIVE.read_bytes()).hexdigest()
    assert provenance.native_table.semantic_digest is not None
    assert (
        provenance.native_table.semantic_digest.sha256
        == "c7fb3582edcc4b66a154d5dac52acd22d2847cd04ed54f5ee94fbf7c8bc6d9ec"
    )

    substituted = tmp_path / "native.parquet"
    payload = bytearray(NATIVE.read_bytes())
    payload[-1] ^= 1
    substituted.write_bytes(payload)
    with pytest.raises(FatalContractError, match=f"expected {NATIVE_TABLE_SHA256}.*observed"):
        generate_catalogue.main(
            [
                "--native",
                str(substituted),
                "--out",
                str(tmp_path / "substituted"),
                "--terms-recording",
                str(TERMS),
            ]
        )


def test_poland_terms_are_verified_in_real_generation_path(tmp_path: Path) -> None:
    assert (
        generate_catalogue.main(["--native", str(NATIVE), "--out", str(tmp_path), "--terms-recording", str(TERMS)]) == 0
    )
    provenance = json.loads((tmp_path / "provenance.json").read_text())
    imgw = next(source for source in provenance["source_records"] if source["source_id"] == "sr.pl.imgw")
    assert {statement["kind"] for statement in imgw["statements"]} == {"license", "citation"}

    changed = tmp_path / "changed.html"
    changed.write_bytes(TERMS.read_bytes() + b"x")
    with pytest.raises(FatalContractError, match="digest mismatch"):
        generate_catalogue.main(
            ["--native", str(NATIVE), "--out", str(tmp_path / "changed"), "--terms-recording", str(changed)]
        )


def test_poland_private_email_remains_unverified_and_forward_is_rejected() -> None:
    provenance = build_acquisition_provenance()
    grdc = next(source for source in provenance.source_records if source.source_id == "sr.pl.grdc")
    statement = grdc.statements[0]
    assert statement.verification_status == "unverified_private_original_required"
    assert statement.recording_id is None
    assert (
        statement.exact_text
        == "I just wanted to send you the metadata for all stations of Poland.\n\nFeel free to include them!"
    )
    assert ORIGINAL_EMAIL_BYTES == 188_701
    assert ORIGINAL_EMAIL_SHA256 == "5a12e0fd96d5f2b35e15cc75a76e6e9a62416a87d7d483e28be3d18c03a936e0"
    assert FORWARDED_EMAIL_BYTES == 228_628
    assert FORWARDED_EMAIL_SHA256 == "6ffc840e3a371cc7731fdd587e3d3a3918e47aa73c0e7e1c1251e54494054742"

    with pytest.raises(FatalContractError, match="original email byte count mismatch"):
        verify_original_grdc_email(b"forwarded-copy")


def test_private_verification_record_is_redacted_and_not_packaged() -> None:
    record = PrivateEmailVerificationRecord(
        schema_version=1,
        statement_id="pl_imgw.grdc.inclusion",
        original_email_sha256=ORIGINAL_EMAIL_SHA256,
        original_email_byte_count=ORIGINAL_EMAIL_BYTES,
        workbook_sha256=WORKBOOK_SHA256,
        workbook_byte_count=WORKBOOK_BYTES,
        verified=True,
    )
    rendered = serialize_private_email_verification(record)
    assert "I just wanted" not in rendered
    assert "Feel free" not in rendered
    assert "@" not in rendered
    assert not list(CATALOGUE.glob("*email*"))
    assert not list(CATALOGUE.glob("*.eml"))


def test_redacted_private_record_can_upgrade_a_later_canonical_build(tmp_path: Path) -> None:
    record = PrivateEmailVerificationRecord(
        schema_version=1,
        statement_id="pl_imgw.grdc.inclusion",
        original_email_sha256=ORIGINAL_EMAIL_SHA256,
        original_email_byte_count=ORIGINAL_EMAIL_BYTES,
        workbook_sha256=WORKBOOK_SHA256,
        workbook_byte_count=WORKBOOK_BYTES,
        verified=True,
    )
    record_path = tmp_path / "redacted.json"
    record_path.write_text(serialize_private_email_verification(record))
    assert parse_private_email_verification(record_path.read_bytes()) == record
    substituted = json.loads(record_path.read_text())
    substituted["original_email_sha256"] = "0" * 64
    with pytest.raises(FatalContractError, match="redacted private verification record identity mismatch"):
        parse_private_email_verification(json.dumps(substituted).encode())

    output = tmp_path / "catalogue"
    generate_catalogue.main(
        [
            "--native",
            str(NATIVE),
            "--out",
            str(output),
            "--terms-recording",
            str(TERMS),
            "--private-verification-record",
            str(record_path),
        ]
    )
    generated = load_packaged_catalogue_artifact(output, on_issue="raise")
    assert generated.acquisition_provenance is not None
    grdc = next(
        source for source in generated.acquisition_provenance.source_records if source.source_id == "sr.pl.grdc"
    )
    statement = grdc.statements[0]
    assert statement.verification_status == "verified_private_original"
    assert statement.private_verification == record


def test_committed_poland_quote_remains_unverified_without_original_record() -> None:
    artifact = load_packaged_catalogue_artifact(declaration.catalogue, on_issue="raise")
    assert artifact.acquisition_provenance is not None
    grdc = next(source for source in artifact.acquisition_provenance.source_records if source.source_id == "sr.pl.grdc")
    assert grdc.statements[0].verification_status == "unverified_private_original_required"
    assert grdc.statements[0].private_verification is None


def test_packaged_poland_provenance_propagates_without_frame_changes() -> None:
    artifact = load_packaged_catalogue_artifact(declaration.catalogue, on_issue="raise")
    assert artifact.acquisition_provenance is not None
    assert len(artifact.acquisition_provenance.source_records) == 2
    result = CatalogueReader(artifact, ProviderId("pl_imgw")).read_stations(on_issue="raise")
    selection = rr.find(provider="pl_imgw", station="149180010", product="discharge_daily_mean")
    assert result.provenance.acquisition_provenance == artifact.acquisition_provenance
    assert selection.acquisition_provenance == (artifact.acquisition_provenance,)
    assert rr.as_frame(selection).columns == [
        "provider_id",
        "station_id",
        "product_id",
        "latitude",
        "longitude",
        "crs",
        "observed_property",
        "frequency",
        "statistic",
        "period_type",
        "period_anchor",
        "unit",
        "native_id",
        "availability",
        "availability_reason",
        "published_record_start_date",
        "published_record_end_date",
        "last_catalogue_check",
    ]
    assert rr.as_frame(selection)["crs"].item() == "unknown"


def test_poland_observation_result_propagates_two_sources_with_five_columns() -> None:
    selection = rr.find(provider="pl_imgw", station="149180010", product="discharge_daily_mean")
    result = rr.fetch(selection, start="2024-01-01", end="2024-01-02", on_issue="ignore")

    assert result.data.columns == ["time", "time_zone", "station_id", "product_id", "value"]
    assert result.provenance.acquisition_provenance is not None
    assert [source.source_id for source in result.provenance.acquisition_provenance.source_records] == [
        "sr.pl.imgw",
        "sr.pl.grdc",
    ]


def test_enrolled_poland_refuses_missing_provenance(tmp_path: Path) -> None:
    for name in ("provider.json", "products.parquet", "stations.parquet", "station_products.parquet"):
        shutil.copy2(CATALOGUE / name, tmp_path / name)
    with pytest.raises(CorruptCatalogArtifactError, match="pl_imgw acquisition provenance is required"):
        load_packaged_catalogue_artifact(tmp_path, on_issue="raise")
