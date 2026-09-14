"""Mutation tests for typed acquisition instants and acyclic provenance lineage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    ExternalFactReference,
    FactBinding,
    Transformation,
)
from tests._provenance import legacy_document

_PROVIDER_ROOT = Path("src/rivretrieve/_internal/providers")
_PROVENANCE_PATHS = tuple(sorted(_PROVIDER_ROOT.glob("*/catalogue/provenance.json")))


def _document(provider_id: str) -> dict[str, Any]:
    return legacy_document(_PROVIDER_ROOT / provider_id / "catalogue" / "provenance.json")


def _model_payload(provenance: AcquisitionProvenance) -> dict[str, object]:
    return {name: getattr(provenance, name) for name in type(provenance).model_fields}


def test_every_v2_acquisition_has_exact_typed_instant_semantics() -> None:
    for path in _PROVENANCE_PATHS:
        document = legacy_document(path)
        assert document["schema_version"] == 2
        for source in document["source_records"]:
            for acquisition in source["acquisitions"]:
                method = acquisition["method"]
                expected = (
                    "runtime"
                    if method == "runtime_http_request"
                    else "provenance_lower_bound"
                    if method == "repository_recovery"
                    else "private_redacted_corroborating_receipt"
                    if method == "corroborating_receipt" and acquisition.get("retrieved_at_start") is None
                    else "corroborating_receipt"
                    if method == "corroborating_receipt"
                    else "retrieval_interval"
                    if acquisition.get("retrieved_at_end") is not None
                    else "retrieval"
                )
                assert acquisition["instant_type"] == expected, (path, acquisition["acquisition_id"])


def test_v2_rejects_an_acquisition_without_instant_type() -> None:
    document = _document("pl_imgw")
    del document["source_records"][0]["acquisitions"][0]["instant_type"]

    with pytest.raises(ValidationError, match="Field required"):
        AcquisitionProvenance.model_validate(document)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ({"instant_type": "runtime"}, "recorded acquisitions cannot use the runtime instant type"),
        ({"instant_type": "retrieval", "retrieved_at_end": "2026-08-02T19:54:27Z"}, "only retrieval intervals"),
        ({"instant_type": "retrieval_interval", "retrieved_at_end": None}, "retrieval intervals require an end"),
        ({"instant_type": "provenance_lower_bound", "retrieved_at_end": None}, "HTTP acquisitions must use"),
    ),
)
def test_acquisition_rejects_inconsistent_typed_instant_semantics(mutation: dict[str, object], message: str) -> None:
    document = _document("pl_imgw")
    acquisition = document["source_records"][0]["acquisitions"][0]
    acquisition.update(mutation)

    with pytest.raises(ValidationError, match=message):
        AcquisitionProvenance.model_validate(document)


@pytest.mark.parametrize(
    "payload",
    (
        {"name": "missing marker", "kind": "absence_marker", "external_inputs": ()},
        {"name": "derived marker", "marker_value": "null", "external_inputs": ()},
    ),
)
def test_transformation_requires_marker_value_to_match_kind(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="marker value"):
        Transformation.model_validate(payload)


def test_absence_marker_value_must_match_its_canonical_output_fact() -> None:
    document = _document("pl_imgw")
    crs = next(
        binding for binding in document["fact_bindings"] if binding["fact_group"] == "rivretrieve_crs_knowledge_state"
    )
    crs["transformation"]["marker_value"] = "null"

    with pytest.raises(ValidationError, match="absence-marker value is incompatible"):
        AcquisitionProvenance.model_validate(document)


def test_exclusive_shape_prevents_direct_self_reference() -> None:
    provenance = AcquisitionProvenance.model_validate(_document("ca_eccc"))
    bindings = list(provenance.fact_bindings)
    original = next(binding for binding in bindings if binding.transformation is not None)
    bad = FactBinding.model_construct(
        fact_group=original.fact_group,
        facts=original.facts,
        source_id="ca_eccc_msc",
        acquisition_id="station_registry_capture_2026_08_02",
        transformation=Transformation(
            name="invalid direct self edge",
            external_inputs=(ExternalFactReference(source_id="ca_eccc_msc", fact=original.facts[0]),),
        ),
    )
    bindings[bindings.index(original)] = bad
    payload = _model_payload(provenance)
    payload["fact_bindings"] = tuple(bindings)

    with pytest.raises(ValidationError, match="derived bindings cannot attribute outputs"):
        AcquisitionProvenance.model_validate(payload)


def test_exclusive_shape_prevents_indirect_cycle() -> None:
    provenance = AcquisitionProvenance.model_validate(_document("ca_eccc"))
    bindings = list(provenance.fact_bindings)
    first, second = bindings[:2]
    bindings[0] = FactBinding.model_construct(
        fact_group=first.fact_group,
        facts=first.facts,
        source_id="ca_eccc_msc",
        acquisition_id="station_registry_capture_2026_08_02",
        transformation=Transformation(
            name="invalid first cycle edge",
            external_inputs=(ExternalFactReference(source_id="ca_eccc_msc", fact=second.facts[0]),),
        ),
    )
    bindings[1] = FactBinding.model_construct(
        fact_group=second.fact_group,
        facts=second.facts,
        source_id="ca_eccc_msc",
        acquisition_id="station_registry_capture_2026_08_02",
        transformation=Transformation(
            name="invalid second cycle edge",
            external_inputs=(ExternalFactReference(source_id="ca_eccc_msc", fact=first.facts[0]),),
        ),
    )
    payload = _model_payload(provenance)
    payload["fact_bindings"] = tuple(bindings)

    with pytest.raises(ValidationError, match="derived bindings cannot attribute outputs"):
        AcquisitionProvenance.model_validate(payload)


def test_transformation_output_cannot_resolve_as_an_external_source_fact() -> None:
    document = _document("th_thaiwater")
    platform = next(item for item in document["fact_bindings"] if item["fact_group"] == "canonical_platform_carrier")
    station = next(item for item in document["fact_bindings"] if item["fact_group"] == "canonical_station_carrier")
    station["transformation"]["external_inputs"] = [{"source_id": "th_agency_9", "fact": platform["facts"][0]}]

    with pytest.raises(ValidationError, match="dangling or misattributed fact"):
        AcquisitionProvenance.model_validate(document)


def test_transformation_rejects_dual_issuer_attribution() -> None:
    document = _document("ca_eccc")
    binding = next(item for item in document["fact_bindings"] if item.get("transformation"))
    binding["source_id"] = "ca_eccc_msc"
    binding["acquisition_id"] = "station_registry_capture_2026_08_02"

    with pytest.raises(ValidationError, match="derived bindings cannot attribute outputs to a source acquisition"):
        AcquisitionProvenance.model_validate(document)


def test_transformation_cannot_republish_a_withheld_value() -> None:
    document = _document("pl_imgw")
    station = next(item for item in document["fact_bindings"] if item["fact_group"] == "rivretrieve_station_catalogue")
    station["facts"].remove("station.latitude")
    crs = next(item for item in document["fact_bindings"] if item["fact_group"] == "rivretrieve_crs_knowledge_state")
    crs["facts"].append("station.latitude")

    with pytest.raises(ValidationError, match="withheld external inputs may only produce absence markers"):
        AcquisitionProvenance.model_validate(document)


def test_v2_model_rejects_external_direct_ownership_of_canonical_carrier_facts() -> None:
    document = _document("pl_imgw")
    binding = next(item for item in document["fact_bindings"] if item["fact_group"] == "rivretrieve_station_catalogue")
    binding["source_id"] = "sr.pl.grdc"
    binding["acquisition_id"] = "recovered_upstream_import_f67f6d8"
    del binding["transformation"]

    with pytest.raises(ValidationError, match="external direct bindings must name source or native facts"):
        AcquisitionProvenance.model_validate(document)


def test_v2_artifacts_do_not_attribute_rivretrieve_canonical_facts_to_external_issuers() -> None:
    canonical_prefixes = ("provider.", "product.", "station.", "station_product.", "canonical.")
    violations: list[tuple[Path, str, str]] = []
    for path in _PROVENANCE_PATHS:
        document = legacy_document(path)
        for binding in document["fact_bindings"]:
            if binding.get("source_id") is None:
                continue
            for fact in binding["facts"]:
                if fact.startswith(canonical_prefixes) or fact == "observation.canonical_five_column_shape":
                    violations.append((path, binding["fact_group"], fact))

    assert violations == []


def test_transformations_require_lineage_except_authored_constants() -> None:
    document = _document("ca_eccc")
    binding = next(
        item for item in document["fact_bindings"] if item["fact_group"] == "canonical_msc_catalogue_carrier"
    )
    binding["transformation"]["external_inputs"] = []
    with pytest.raises(ValidationError, match="external inputs"):
        AcquisitionProvenance.model_validate(document)

    thailand = _document("th_thaiwater")
    product = next(item for item in thailand["fact_bindings"] if item["fact_group"] == "canonical_product_carrier")
    product["transformation"] = {"name": "authored", "kind": "authored_constant", "external_inputs": []}
    AcquisitionProvenance.model_validate(thailand)
    product["facts"].append("canonical.illegal")
    thailand["fact_universe"].append("canonical.illegal")
    with pytest.raises(ValidationError, match="authored-constant"):
        AcquisitionProvenance.model_validate(thailand)


def test_acquisition_record_requires_what_and_where() -> None:
    document = _document("ca_eccc")
    acquisition = document["source_records"][0]["acquisitions"][0]
    acquisition["description"] = "   "
    acquisition["requested_from"] = []
    with pytest.raises(ValidationError, match="description|requested_from"):
        AcquisitionProvenance.model_validate(document)


def test_runtime_acquisition_cannot_ground_catalogue_facts() -> None:
    document = _document("ch_foen")
    acquisition = document["source_records"][0]["acquisitions"][0]
    acquisition.update(
        {
            "method": "runtime_http_request",
            "instant_type": "runtime",
            "retrieved_at_start": None,
            "retrieved_at_end": None,
        }
    )
    with pytest.raises(ValidationError, match="runtime acquisitions may bind only runtime observation"):
        AcquisitionProvenance.model_validate(document)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("issuer", "   ", "issuer"),
        ("issuer", " Environment Canada", "issuer"),
        ("operator", "   ", "operator"),
    ),
)
def test_source_identity_requires_stripped_nonblank_names(field: str, value: str, message: str) -> None:
    document = _document("ca_eccc")
    document["source_records"][0][field] = value
    with pytest.raises(ValidationError, match=message):
        AcquisitionProvenance.model_validate(document)


@pytest.mark.parametrize(
    "location",
    (
        "://",
        "ftp://example.test/file",
        "https:///missing-host",
        "https://:",
        "https://example.com/a b",
        "http://-",
        "private://:",
        "private://grdc-bfg/other",
        "https://example..com/path",
        "https://example.com/path\nheader",
        "https://example.com:bad/path",
        "https://example.com:/path",
        "https://example.com:70000/path",
        "https://example.com/%ZZ",
        "https://example.com/a|b",
        'https://example.com/"x',
        "https://example.com/\\x",
        "https://example.com?x=%GG",
        "https://example.com/a[b]",
        "https://example.com/path#frag#two",
        "https://example.com/{",
        "https://example.com/<>",
    ),
)
def test_acquisition_rejects_invalid_typed_locations(location: str) -> None:
    document = _document("ca_eccc")
    document["source_records"][0]["acquisitions"][0]["requested_from"] = [location]
    with pytest.raises(ValidationError, match="requested_from.*valid|location"):
        AcquisitionProvenance.model_validate(document)


def test_acquisition_accepts_runtime_templates_and_narrow_private_location() -> None:
    bosnia = _document("ba_fhmzbih")
    AcquisitionProvenance.model_validate(bosnia)
    poland = _document("pl_imgw")
    AcquisitionProvenance.model_validate(poland)


def test_every_public_statement_is_bound_to_its_recording_acquisition() -> None:
    for path in _PROVENANCE_PATHS:
        document = legacy_document(path)
        bindings = {
            (binding.get("source_id"), fact): binding.get("acquisition_id")
            for binding in document["fact_bindings"]
            for fact in binding["facts"]
        }
        for source in document["source_records"]:
            acquisitions = {item["acquisition_id"]: item for item in source["acquisitions"]}
            for statement in source["statements"]:
                if statement.get("verification_status", "verified_public_recording") != "verified_public_recording":
                    continue
                fact = statement["fact"]
                acquisition = acquisitions[bindings[(source["source_id"], fact)]]
                assert statement["recording_id"] in acquisition["recording_ids"], (path, statement)


def test_public_statement_rejects_recording_claimed_by_an_unrelated_acquisition() -> None:
    document = _document("jp_mlit")
    statement = document["source_records"][0]["statements"][0]
    statement["fact"] = "source.provider.license_terms"
    license_acquisition = document["source_records"][0]["acquisitions"][1]
    unrelated = document["source_records"][0]["acquisitions"][2]
    unrelated["recording_ids"].append(statement["recording_id"])
    license_acquisition["recording_ids"].remove(statement["recording_id"])
    with pytest.raises(ValidationError, match="statement recording must be claimed by its fact acquisition"):
        AcquisitionProvenance.model_validate(document)


def test_public_statement_rejects_fact_bound_to_an_unrelated_acquisition() -> None:
    document = _document("jp_mlit")
    statement = document["source_records"][0]["statements"][0]
    statement["fact"] = "source.provider.license_terms"
    binding = next(item for item in document["fact_bindings"] if statement["fact"] in item["facts"])
    binding["acquisition_id"] = "citation_terms_capture_2026_08_21"
    with pytest.raises(ValidationError, match="statement recording must be claimed by its fact acquisition"):
        AcquisitionProvenance.model_validate(document)


@pytest.mark.parametrize(
    ("field", "value"),
    (("requested_from", ["https://example.test/unrelated"]), ("retrieved_at_start", "2026-08-20T00:00:00Z")),
)
def test_public_statement_rejects_acquisition_that_mismatches_recording(field: str, value: object) -> None:
    document = _document("jp_mlit")
    statement = document["source_records"][0]["statements"][0]
    acquisition = next(
        item
        for item in document["source_records"][0]["acquisitions"]
        if statement["recording_id"] in item["recording_ids"]
    )
    acquisition[field] = value
    with pytest.raises(ValidationError, match="statement acquisition must match its exact recording URL and instant"):
        AcquisitionProvenance.model_validate(document)


def test_missing_terms_do_not_block_traced_values_and_do_not_explain_current_retrieval_loss() -> None:
    bosnia = _document("ba_fhmzbih")
    bosnia_statement_facts = {
        statement["fact"] for source in bosnia["source_records"] for statement in source["statements"]
    }
    bosnia_withheld = {fact for group in bosnia["withheld_facts"] for fact in group["facts"]}
    assert bosnia_statement_facts.isdisjoint(bosnia_withheld)
    assert bosnia_withheld == set()
    bosnia_bound = {
        fact for binding in AcquisitionProvenance.model_validate(bosnia).fact_bindings for fact in binding.facts
    }
    assert "source.station:2101-B.identity_location" in bosnia_bound
    assert "station_product:2101-B:water_temperature_reported.availability" in bosnia_bound

    thailand = _document("th_thaiwater")
    assert [statement for source in thailand["source_records"] for statement in source["statements"]] == []
    thailand_withheld = {fact for group in thailand["withheld_facts"] for fact in group["facts"]}
    assert thailand_withheld == set()
    bound = {fact for binding in thailand["fact_bindings"] for fact in binding["facts"]}
    assert any(fact.startswith("source.station:") for fact in bound)
    assert sum(fact.startswith("source.station_product:") and fact.endswith(".availability") for fact in bound) == 1650
