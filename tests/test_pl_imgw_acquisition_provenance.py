from __future__ import annotations

import hashlib
import json
import shutil
from email.message import EmailMessage
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.private_source_verification as private_verification_module
from rivretrieve._internal.acquisition_provenance import PrivateStatementVerification
from rivretrieve._internal.catalogue_origins import (
    Evidence,
    NotPublished,
    Withheld,
    validate_catalogue_origins,
)
from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.catalogues.artifact import CorruptCatalogArtifactError, load_packaged_catalogue_artifact
from rivretrieve._internal.catalogues.native import read_native_table
from rivretrieve._internal.engine import CanonicalRowsSchema
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.private_source_verification import (
    FORWARDED_EMAIL_BYTES,
    FORWARDED_EMAIL_SHA256,
    STATEMENT_SHA256,
    WORKBOOK_BYTES,
    WORKBOOK_SHA256,
    PrivateEmailVerificationRecord,
    parse_private_email_verification,
    serialize_private_email_verification,
    verify_forwarded_grdc_email,
)
from rivretrieve._internal.providers.pl_imgw import generate_catalogue
from rivretrieve._internal.providers.pl_imgw.declaration import declaration
from rivretrieve._internal.providers.pl_imgw.origins import (
    NATIVE_TABLE_SHA256,
    STATION_CATALOGUE_ORIGINS,
    build_acquisition_provenance,
)
from tests._catalogue import catalogue_recording_paths
from tests._provenance import (
    assert_evidence_equal,
    legacy_document,
    remove_binding_fact,
    remove_external_inputs,
    write_evidence_table,
)

CATALOGUE = Path("src/rivretrieve/_internal/providers/pl_imgw/catalogue")
NATIVE = CATALOGUE / "native.parquet"
TERMS = Path("tests/test_data/pl_imgw_terms_regulations.html")
SYNTHETIC_PRIVATE_TEXT = "Synthetic private verification statement.\n\nSecond synthetic sentence."
PRIVATE_STATEMENT_SHA256 = STATEMENT_SHA256


def _forwarded_message(
    *,
    exact_text: str = SYNTHETIC_PRIVATE_TEXT,
    workbook: bytes = b"synthetic-workbook",
) -> bytes:
    message = EmailMessage()
    message.set_content(exact_text)
    message.add_alternative(f"<html><body>{exact_text}</body></html>", subtype="html")
    message.add_attachment(
        workbook,
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="Metadata_GRDC_30.10.2025.xlsx",
    )
    return message.as_bytes()


def _pin_synthetic_forwarded_message(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    workbook: bytes = b"synthetic-workbook",
    exact_text: str = SYNTHETIC_PRIVATE_TEXT,
) -> None:
    monkeypatch.setattr(private_verification_module, "FORWARDED_EMAIL_BYTES", len(body))
    monkeypatch.setattr(private_verification_module, "FORWARDED_EMAIL_SHA256", hashlib.sha256(body).hexdigest())
    monkeypatch.setattr(private_verification_module, "WORKBOOK_BYTES", len(workbook))
    monkeypatch.setattr(private_verification_module, "WORKBOOK_SHA256", hashlib.sha256(workbook).hexdigest())
    monkeypatch.setattr(
        private_verification_module,
        "STATEMENT_SHA256",
        hashlib.sha256(exact_text.encode("utf-8")).hexdigest(),
    )


def test_poland_provenance_is_closed_and_credits_fields_without_provider_inheritance() -> None:
    provenance = build_acquisition_provenance()
    assert [source.source_id for source in provenance.source_records] == ["sr.pl.imgw", "sr.pl.grdc"]
    grdc = provenance.source_records[1]
    assert grdc.issuer == "Global Runoff Data Centre"
    assert grdc.operator == "Bundesanstalt für Gewässerkunde"
    assert all(statement.kind != "citation" for statement in grdc.statements)

    by_fact = {fact: binding.source_id for binding in provenance.fact_bindings for fact in binding.facts}
    assert by_fact["station.station_id"] is None
    assert by_fact["station.latitude"] is None
    assert by_fact["station.longitude"] is None
    assert by_fact["provider.provider_id"] is None
    assert by_fact["provider.license"] is None
    assert by_fact["provider.citation"] is None
    compatibility = next(
        binding
        for binding in provenance.fact_bindings
        if binding.fact_group == "rivretrieve_provider_terms_compatibility"
    )
    assert compatibility.transformation is not None
    assert compatibility.transformation.kind == "absence_marker"
    assert compatibility.transformation.marker_value == "null"
    assert {reference.source_id for reference in compatibility.transformation.external_inputs} == {
        "sr.pl.imgw",
        "sr.pl.grdc",
    }
    assert by_fact["product.product_id"] is None
    assert by_fact["station_product.availability_reason"] is None
    assert by_fact["source.observation.value"] == "sr.pl.imgw"
    assert by_fact["station.crs"] is None
    crs_binding = next(binding for binding in provenance.fact_bindings if "station.crs" in binding.facts)
    assert crs_binding.source_id is None
    assert crs_binding.acquisition_id is None
    assert crs_binding.transformation is not None
    assert crs_binding.transformation.name.startswith("RivRetrieve unknown marker")
    assert crs_binding.transformation.marker_value == "unknown"
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
    assert by_fact["station_product.published_record_start_date"].source_id is None
    assert "station_product.published_record_start_date" not in withheld

    assert isinstance(STATION_CATALOGUE_ORIGINS["crs"], Withheld)
    assert NotPublished(Evidence("https://example.test/source-crs")) != STATION_CATALOGUE_ORIGINS["crs"]
    assert "source.grdc.horizontal_crs" in withheld
    assert by_fact["station.crs"].source_id is None
    assert artifact.stations["crs"].unique().to_list() == ["unknown"]


def test_packaged_poland_rejects_absence_marker_carrier_mismatches(tmp_path: Path) -> None:
    crs_catalogue = tmp_path / "crs"
    shutil.copytree(CATALOGUE, crs_catalogue)
    stations = pl.read_parquet(crs_catalogue / "stations.parquet")
    first_station = stations["station_id"].item(0)
    stations = stations.with_columns(
        pl.when(pl.col("station_id") == first_station).then(pl.lit("EPSG:4326")).otherwise(pl.col("crs")).alias("crs")
    )
    stations.write_parquet(crs_catalogue / "stations.parquet")
    with pytest.raises(CorruptCatalogArtifactError, match="station.crs.*unknown"):
        load_packaged_catalogue_artifact(crs_catalogue, on_issue="raise")

    for field in ("license", "citation"):
        terms_catalogue = tmp_path / field
        shutil.copytree(CATALOGUE, terms_catalogue)
        provider = json.loads((terms_catalogue / "provider.json").read_text())
        provider[field] = "https://example.test/invented-terms"
        (terms_catalogue / "provider.json").write_text(json.dumps(provider))
        with pytest.raises(CorruptCatalogArtifactError, match=rf"provider.{field}.*null"):
            load_packaged_catalogue_artifact(terms_catalogue, on_issue="raise")


def test_packaged_poland_rejects_external_direct_canonical_station_ownership(tmp_path: Path) -> None:
    mutated = tmp_path / "catalogue"
    shutil.copytree(CATALOGUE, mutated)
    header = json.loads((mutated / "provenance.json").read_text())
    source_ordinal = next(i for i, source in enumerate(header["source_records"]) if source["source_id"] == "sr.pl.grdc")
    acquisitions = pl.read_parquet(mutated / "provenance_acquisitions.parquet")
    acquisition_key = acquisitions.filter(
        (pl.col("source_ordinal") == source_ordinal) & (pl.col("acquisition_id") == "recovered_upstream_import_f67f6d8")
    )["acquisition_key"].item()
    remove_external_inputs(mutated, ("rivretrieve_station_catalogue",))
    bindings = pl.read_parquet(mutated / "provenance_bindings.parquet")
    changed = bindings.with_columns(
        pl.when(pl.col("fact_group") == "rivretrieve_station_catalogue")
        .then(pl.lit(value, dtype=pl.UInt32))
        .otherwise(pl.col(name))
        .alias(name)
        for name, value in {
            "source_ordinal": source_ordinal,
            "acquisition_key": acquisition_key,
            "transformation_id": None,
        }.items()
    )
    write_evidence_table(mutated, "provenance_bindings.parquet", changed)

    with pytest.raises(CorruptCatalogArtifactError, match="external direct bindings must name source or native facts"):
        load_packaged_catalogue_artifact(mutated, on_issue="raise")


@pytest.mark.derived("src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet")
def test_poland_withheld_crs_origin_rejects_an_asserted_crs(retained_evidence_root: Path) -> None:
    native = read_native_table(retained_evidence_root / NATIVE)
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
    assert workbook.instant_type == "private_redacted_corroborating_receipt"
    assert workbook.retrieved_at_start is None
    assert workbook.requested_from == ("private://grdc-bfg/correspondence",)
    assert workbook.material is not None
    assert workbook.material.filename == "Metadata_GRDC_30.10.2025.xlsx"
    assert workbook.material.byte_count == WORKBOOK_BYTES == 116_301
    assert workbook.material.sha256 == WORKBOOK_SHA256


@pytest.mark.governing(
    "src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet",
    "tests/test_data/pl_imgw_terms_regulations.html",
)
def test_poland_native_identity_and_raw_substitution_refusal(retained_evidence_root: Path, tmp_path: Path) -> None:
    from tests.test_catalogue_build_provenance import _build

    # Synthetic selection reaches only the intended failing verification boundary.
    build_inputs_path = tmp_path / "synthetic-build-inputs.json"
    build_inputs_path.write_text(_build().model_dump_json(), encoding="utf-8")
    provenance = build_acquisition_provenance()
    assert provenance.native_table.repository_path == str(NATIVE)
    assert provenance.native_table.revision == "c9c81934bb1773b0286c968f4fd7323f724c71ac"
    assert (
        provenance.native_table.sha256
        == NATIVE_TABLE_SHA256
        == hashlib.sha256((retained_evidence_root / NATIVE).read_bytes()).hexdigest()
    )
    assert provenance.native_table.semantic_digest is not None
    assert (
        provenance.native_table.semantic_digest.sha256
        == "c7fb3582edcc4b66a154d5dac52acd22d2847cd04ed54f5ee94fbf7c8bc6d9ec"
    )

    substituted = tmp_path / "native.parquet"
    payload = bytearray((retained_evidence_root / NATIVE).read_bytes())
    payload[-1] ^= 1
    substituted.write_bytes(payload)
    with pytest.raises(FatalContractError, match=f"expected {NATIVE_TABLE_SHA256}.*observed"):
        generate_catalogue.main(
            [
                "--build-inputs",
                str(build_inputs_path),
                "--native",
                str(substituted),
                "--out",
                str(tmp_path / "substituted"),
                "--terms-recording",
                str(retained_evidence_root / TERMS),
            ]
        )


@pytest.mark.governing(
    "src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet",
    "tests/test_data/pl_imgw_terms_regulations.html",
)
@pytest.mark.recorded(*catalogue_recording_paths("pl_imgw"))
def test_poland_terms_are_verified_in_real_generation_path(
    retained_evidence_root: Path, tmp_path: Path, catalogue_build_inputs_path
) -> None:
    from rivretrieve._internal.providers.pl_imgw.origins import build_acquisition_provenance

    build_inputs_path = catalogue_build_inputs_path(build_acquisition_provenance())
    assert (
        generate_catalogue.main(
            [
                "--build-inputs",
                str(build_inputs_path),
                "--native",
                str(retained_evidence_root / NATIVE),
                "--out",
                str(tmp_path),
                "--terms-recording",
                str(retained_evidence_root / TERMS),
            ]
        )
        == 0
    )
    provenance = legacy_document(tmp_path / "provenance.json")
    imgw = next(source for source in provenance["source_records"] if source["source_id"] == "sr.pl.imgw")
    assert {statement["kind"] for statement in imgw["statements"]} == {"license", "citation"}
    grdc = next(source for source in provenance["source_records"] if source["source_id"] == "sr.pl.grdc")
    statement = grdc["statements"][0]
    assert statement["verification_status"] == "verified_private_forwarded_copy"
    assert statement["private_verification"]["evidence_sha256"] == FORWARDED_EMAIL_SHA256

    changed = tmp_path / "changed.html"
    changed.write_bytes((retained_evidence_root / TERMS).read_bytes() + b"x")
    with pytest.raises(FatalContractError, match="digest mismatch"):
        generate_catalogue.main(
            [
                "--build-inputs",
                str(build_inputs_path),
                "--native",
                str(retained_evidence_root / NATIVE),
                "--out",
                str(tmp_path / "changed"),
                "--terms-recording",
                str(changed),
            ]
        )


def test_poland_committed_origin_always_declares_verified_forwarded_record() -> None:
    provenance = build_acquisition_provenance()
    grdc = next(source for source in provenance.source_records if source.source_id == "sr.pl.grdc")
    statement = grdc.statements[0]
    assert statement.verification_status == "verified_private_forwarded_copy"
    assert statement.private_verification is not None
    assert statement.private_verification.evidence_sha256 == FORWARDED_EMAIL_SHA256
    assert statement.private_verification.evidence_byte_count == FORWARDED_EMAIL_BYTES == 228_628
    assert statement.recording_id is None
    assert statement.exact_text is None
    assert FORWARDED_EMAIL_SHA256 == "6ffc840e3a371cc7731fdd587e3d3a3918e47aa73c0e7e1c1251e54494054742"


def test_forwarded_private_email_verification_is_typed_and_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    body = _forwarded_message()
    _pin_synthetic_forwarded_message(monkeypatch, body)

    record = verify_forwarded_grdc_email(body, SYNTHETIC_PRIVATE_TEXT)

    assert record.evidence_kind == "forwarded_copy"
    assert record.limitation == "original_byte_identity_not_established"
    assert record.evidence_sha256 == hashlib.sha256(body).hexdigest()
    assert not hasattr(record, "original_email_sha256")
    assert SYNTHETIC_PRIVATE_TEXT not in serialize_private_email_verification(record)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("wrong_outer", "forwarded email digest mismatch"),
        ("missing_excerpt", "exact quotation must occur exactly once"),
        ("duplicate_excerpt", "exact quotation must occur exactly once"),
        ("missing_attachment", "exactly one Metadata_GRDC_30.10.2025.xlsx attachment"),
        ("wrong_attachment", "GRDC workbook digest mismatch"),
    ),
)
def test_forwarded_private_email_verification_rejects_changed_evidence(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    workbook = b"synthetic-workbook"
    text = SYNTHETIC_PRIVATE_TEXT
    if mutation == "missing_excerpt":
        text = "unrelated text"
    elif mutation == "duplicate_excerpt":
        text = f"{SYNTHETIC_PRIVATE_TEXT}\n{SYNTHETIC_PRIVATE_TEXT}"
    if mutation == "missing_attachment":
        message_object = EmailMessage()
        message_object.set_content(text)
        message_object.add_alternative(f"<html><body>{text}</body></html>", subtype="html")
        body = message_object.as_bytes()
    else:
        attached = b"x" * len(workbook) if mutation == "wrong_attachment" else workbook
        body = _forwarded_message(exact_text=text, workbook=attached)
    _pin_synthetic_forwarded_message(monkeypatch, body, workbook)
    if mutation == "wrong_outer":
        body = body[:-1] + bytes([body[-1] ^ 1])

    with pytest.raises(FatalContractError, match=message):
        verify_forwarded_grdc_email(body, SYNTHETIC_PRIVATE_TEXT)


def test_forwarded_verification_record_rejects_false_original_identity_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _forwarded_message()
    _pin_synthetic_forwarded_message(monkeypatch, body)
    record = verify_forwarded_grdc_email(body, SYNTHETIC_PRIVATE_TEXT)
    false_claim = record.model_dump(mode="json")
    false_claim["evidence_kind"] = "original"

    with pytest.raises(ValueError, match="forwarded_copy|only forwarded-copy"):
        PrivateEmailVerificationRecord.model_validate(false_claim)


def test_private_verification_record_is_redacted_and_not_packaged() -> None:
    record = PrivateEmailVerificationRecord(
        schema_version=2,
        statement_id="pl_imgw.grdc.inclusion",
        evidence_kind="forwarded_copy",
        limitation="original_byte_identity_not_established",
        evidence_sha256=FORWARDED_EMAIL_SHA256,
        evidence_byte_count=FORWARDED_EMAIL_BYTES,
        workbook_sha256=WORKBOOK_SHA256,
        workbook_byte_count=WORKBOOK_BYTES,
        statement_sha256=PRIVATE_STATEMENT_SHA256,
        decoded_text_plain_occurrence_count=1,
        decoded_text_html_occurrence_count=1,
        verified=True,
    )
    rendered = serialize_private_email_verification(record)
    assert "@" not in rendered
    assert not list(CATALOGUE.glob("*email*"))
    assert not list(CATALOGUE.glob("*.eml"))


@pytest.mark.governing(
    "src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet",
    "tests/test_data/pl_imgw_terms_regulations.html",
)
@pytest.mark.recorded(*catalogue_recording_paths("pl_imgw"))
def test_canonical_build_accepts_only_the_exact_committed_reverification_record(
    retained_evidence_root: Path, tmp_path: Path, catalogue_build_inputs_path
) -> None:
    from rivretrieve._internal.providers.pl_imgw.origins import build_acquisition_provenance

    build_inputs_path = catalogue_build_inputs_path(build_acquisition_provenance())
    record = PrivateEmailVerificationRecord(
        schema_version=2,
        statement_id="pl_imgw.grdc.inclusion",
        evidence_kind="forwarded_copy",
        limitation="original_byte_identity_not_established",
        evidence_sha256=FORWARDED_EMAIL_SHA256,
        evidence_byte_count=FORWARDED_EMAIL_BYTES,
        workbook_sha256=WORKBOOK_SHA256,
        workbook_byte_count=WORKBOOK_BYTES,
        statement_sha256=PRIVATE_STATEMENT_SHA256,
        decoded_text_plain_occurrence_count=1,
        decoded_text_html_occurrence_count=1,
        verified=True,
    )
    record_path = tmp_path / "redacted.json"
    record_path.write_text(serialize_private_email_verification(record))
    assert parse_private_email_verification(record_path.read_bytes()) == record
    substituted = json.loads(record_path.read_text())
    substituted["evidence_sha256"] = "0" * 64
    substituted_path = tmp_path / "substituted-redacted.json"
    substituted_path.write_text(json.dumps(substituted))
    with pytest.raises(FatalContractError, match="redacted private verification record identity mismatch"):
        generate_catalogue.main(
            [
                "--build-inputs",
                str(build_inputs_path),
                "--native",
                str(retained_evidence_root / NATIVE),
                "--out",
                str(tmp_path / "substituted"),
                "--terms-recording",
                str(retained_evidence_root / TERMS),
                "--private-verification-record",
                str(substituted_path),
            ]
        )

    output = tmp_path / "catalogue"
    generate_catalogue.main(
        [
            "--build-inputs",
            str(build_inputs_path),
            "--native",
            str(retained_evidence_root / NATIVE),
            "--out",
            str(output),
            "--terms-recording",
            str(retained_evidence_root / TERMS),
            "--private-verification-record",
            str(record_path),
        ]
    )
    generated = load_packaged_catalogue_artifact(output, on_issue="raise")
    assert generated.acquisition_provenance is not None
    grdc = next(
        source for source in generated.acquisition_provenance.header.source_records if source.source_id == "sr.pl.grdc"
    )
    statement = grdc.statements[0]
    assert statement.verification_status == "verified_private_forwarded_copy"
    assert statement.private_verification == record
    assert statement.exact_text is None


def test_committed_poland_private_statement_is_redacted_forwarded_evidence() -> None:
    artifact = load_packaged_catalogue_artifact(declaration.catalogue, on_issue="raise")
    assert artifact.acquisition_provenance is not None
    grdc = next(
        source for source in artifact.acquisition_provenance.header.source_records if source.source_id == "sr.pl.grdc"
    )
    statement = grdc.statements[0]
    assert statement.verification_status == "verified_private_forwarded_copy"
    assert statement.private_verification is not None
    assert statement.private_verification.evidence_kind == "forwarded_copy"
    assert statement.private_verification.limitation == "original_byte_identity_not_established"
    assert statement.exact_text is None


def test_packaged_poland_provenance_propagates_with_source_series_context() -> None:
    artifact = load_packaged_catalogue_artifact(declaration.catalogue, on_issue="raise")
    assert artifact.acquisition_provenance is not None
    assert len(artifact.acquisition_provenance.header.source_records) == 2
    result = CatalogueReader(artifact, ProviderId("pl_imgw")).read_stations(on_issue="raise")
    selection = rr.find(provider="pl_imgw", station="149180010", quantity="discharge", frequency="daily")
    assert result.provenance.acquisition_provenance is artifact.acquisition_provenance
    assert len(selection.acquisition_provenance) == 1
    assert_evidence_equal(selection.acquisition_provenance[0], artifact.acquisition_provenance)
    frame = rr.as_frame(selection)
    assert frame["series_id"].to_list() == [selection.series[0].series_id]
    assert frame["quantity"].to_list() == ["discharge"]
    assert frame["source_unit"].to_list() == ["m3/s"]
    assert frame["frequency"].to_list() == ["daily"]
    assert frame["statistic"].to_list() == [None]
    assert next(location for location in selection.locations if location.station_id == "149180010").crs == "unknown"


def test_poland_observation_result_propagates_two_sources_and_series_context() -> None:
    selection = rr.find(provider="pl_imgw", station="149180010", quantity="discharge", frequency="daily")
    result = rr.fetch(selection, start="2024-01-01", end="2024-01-02", on_issue="ignore")

    assert result.data.schema == CanonicalRowsSchema.polars_schema
    assert result.provenance.acquisition_provenance is not None
    assert [source.source_id for source in result.provenance.acquisition_provenance.header.source_records] == [
        "sr.pl.imgw",
        "sr.pl.grdc",
    ]


def test_enrolled_poland_refuses_missing_provenance(tmp_path: Path) -> None:
    for name in (
        "provider.json",
        "products.parquet",
        "stations.parquet",
        "station_products.parquet",
        "format.json",
        "source_series.json",
        "series_claims.parquet",
    ):
        shutil.copy2(CATALOGUE / name, tmp_path / name)
    with pytest.raises(CorruptCatalogArtifactError, match="pl_imgw acquisition provenance is required"):
        load_packaged_catalogue_artifact(tmp_path, on_issue="raise")


def test_packaged_poland_rejects_evidence_free_absence_markers(tmp_path: Path) -> None:
    mutated = tmp_path / "catalogue"
    shutil.copytree(CATALOGUE, mutated)
    remove_external_inputs(mutated, ("rivretrieve_provider_terms_compatibility", "rivretrieve_crs_knowledge_state"))
    with pytest.raises(CorruptCatalogArtifactError, match="external inputs"):
        load_packaged_catalogue_artifact(mutated, on_issue="raise")


def test_packaged_poland_rejects_exposed_withheld_provider_scalar(tmp_path: Path) -> None:
    mutated = tmp_path / "catalogue"
    shutil.copytree(CATALOGUE, mutated)
    document = json.loads((mutated / "provenance.json").read_text())
    remove_binding_fact(mutated, "provider.name")
    document = json.loads((mutated / "provenance.json").read_text())
    document["withheld_facts"].append(
        {
            "fact_group": "withheld_provider_name",
            "facts": ["provider.name"],
            "reason": "no_acquisition_record_established",
        }
    )
    (mutated / "provenance.json").write_text(json.dumps(document))
    with pytest.raises(CorruptCatalogArtifactError, match="withheld provider.name remains exposed"):
        load_packaged_catalogue_artifact(mutated, on_issue="raise")


@pytest.mark.governing(
    "src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet",
    "tests/test_data/pl_imgw_terms_regulations.html",
)
def test_generator_rejects_original_private_identity_claim(retained_evidence_root: Path, tmp_path: Path) -> None:
    from tests.test_catalogue_build_provenance import _build

    # Synthetic selection reaches only the intended failing verification boundary.
    build_inputs_path = tmp_path / "synthetic-build-inputs.json"
    build_inputs_path.write_text(_build().model_dump_json(), encoding="utf-8")
    claim = {
        "schema_version": 2,
        "statement_id": "pl_imgw.grdc.inclusion",
        "evidence_kind": "original",
        "limitation": "original_byte_identity_established",
        "evidence_sha256": "0" * 64,
        "evidence_byte_count": 1,
        "workbook_sha256": WORKBOOK_SHA256,
        "workbook_byte_count": WORKBOOK_BYTES,
        "statement_sha256": PRIVATE_STATEMENT_SHA256,
        "verified": True,
    }
    record = tmp_path / "claim.json"
    record.write_text(json.dumps(claim))
    with pytest.raises(FatalContractError, match="redacted private verification record is invalid"):
        generate_catalogue.main(
            [
                "--build-inputs",
                str(build_inputs_path),
                "--native",
                str(retained_evidence_root / NATIVE),
                "--out",
                str(tmp_path / "out"),
                "--terms-recording",
                str(retained_evidence_root / TERMS),
                "--private-verification-record",
                str(record),
            ]
        )


def test_poland_private_receipt_acquisition_has_no_public_retrieval_timestamps() -> None:
    provenance = build_acquisition_provenance()
    grdc = next(source for source in provenance.source_records if source.source_id == "sr.pl.grdc")
    receipt = next(acquisition for acquisition in grdc.acquisitions if acquisition.method == "corroborating_receipt")

    assert receipt.instant_type == "private_redacted_corroborating_receipt"
    assert (receipt.retrieved_at_start, receipt.retrieved_at_end) == (None, None)


def test_poland_builder_rejects_an_arbitrary_structurally_valid_private_pin() -> None:
    fake = PrivateStatementVerification(
        schema_version=2,
        statement_id="fake.statement",
        evidence_kind="forwarded_copy",
        limitation="original_byte_identity_not_established",
        evidence_sha256="0" * 64,
        evidence_byte_count=1,
        workbook_sha256="1" * 64,
        workbook_byte_count=2,
        statement_sha256="2" * 64,
        decoded_text_plain_occurrence_count=1,
        decoded_text_html_occurrence_count=1,
        verified=True,
    )

    with pytest.raises(FatalContractError, match="private verification record identity mismatch"):
        build_acquisition_provenance(fake)


def test_archive_physics_lineage_uses_recorded_definitions_not_station_roster():
    provenance = build_acquisition_provenance()
    binding = next(
        item for item in provenance.fact_bindings if "source.imgw.observation_archive_product_semantics" in item.facts
    )
    assert binding.acquisition_id == "imgw_archive_definitions_2026_09_20"
    source = provenance.source_records[0]
    records = {item.recording.recording_id for item in source.evidence if item.recording is not None}
    assert {"pl_imgw_codz_format", "pl_imgw_yearbook_2025"}.issubset(records)
