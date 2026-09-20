"""Normalized evidence preserves all ordered source assertions and rejects corrupt relations."""

import json
from hashlib import sha256
from pathlib import Path

import polars as pl
import polars.testing as plt
import pytest
from pydantic import ValidationError

from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance
from rivretrieve._internal.catalogues.evidence import (
    EVIDENCE_SCHEMAS,
    CatalogueEvidence,
    EvidenceHeader,
    normalize_provenance,
    validate_catalogue_locators,
)
from rivretrieve._internal.catalogues.evidence_encoding import (
    encode_catalogue_evidence,
    parse_catalogue_evidence,
    reconstruct_provenance,
)
from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS

ROOT = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers"


def _legacy(provider):
    path = ROOT / provider / "catalogue"
    content = (path / "provenance.json").read_bytes()
    import json

    if json.loads(content)["schema_version"] == 3:
        header = EvidenceHeader.model_validate_json(content)
        evidence = parse_catalogue_evidence(header, {name: (path / name).read_bytes() for name in header.files})
        return reconstruct_provenance(evidence)
    return AcquisitionProvenance.model_validate_json(content)


def _normalized(provider):
    path = ROOT / provider / "catalogue"
    return normalize_provenance(
        _legacy(provider),
        stations=pl.read_parquet(path / "stations.parquet"),
        station_products=pl.read_parquet(path / "station_products.parquet"),
    )


@pytest.mark.parametrize("provider", BUILTIN_PROVIDER_IDS)
def test_complete_ordered_provenance_roundtrip(provider):
    old = _legacy(provider)
    path = ROOT / provider / "catalogue"
    evidence = normalize_provenance(
        old,
        stations=pl.read_parquet(path / "stations.parquet"),
        station_products=pl.read_parquet(path / "station_products.parquet"),
    )
    assert reconstruct_provenance(evidence).model_dump(mode="json") == old.model_dump(mode="json")
    files = encode_catalogue_evidence(evidence)
    assert files == encode_catalogue_evidence(evidence)
    header = EvidenceHeader.model_validate_json(files.pop("provenance.json"))
    parsed = parse_catalogue_evidence(header, files)
    assert parsed.header == evidence.header
    for name in EVIDENCE_SCHEMAS:
        plt.assert_frame_equal(getattr(parsed, name), getattr(evidence, name))
    assert reconstruct_provenance(parsed).model_dump(mode="json") == old.model_dump(mode="json")


def test_column_json_roundtrip_and_python_values():
    evidence = _normalized("pl_imgw")
    parsed = CatalogueEvidence.model_validate_json(evidence.model_dump_json())
    assert parsed.header == evidence.header
    assert isinstance(evidence.model_dump()["facts"], pl.DataFrame)
    for name in EVIDENCE_SCHEMAS:
        plt.assert_frame_equal(getattr(parsed, name), getattr(evidence, name))
    assert "source.station" not in repr(evidence)


def _change(evidence, name, frame):
    return {**evidence.model_dump(), name: frame}


@pytest.mark.parametrize(
    "relation,column,value",
    [
        ("facts", "fact_id", 999999),
        ("acquisitions", "source_ordinal", 999999),
        ("acquisitions", "acquisition_ordinal", 999999),
        ("acquisitions", "description_id", 999999),
        ("bindings", "acquisition_key", 999999),
        ("binding_facts", "fact_id", 999999),
        ("external_inputs", "source_ordinal", 999999),
        ("external_inputs", "position", 999999),
    ],
)
def test_relation_keys_fail_closed(relation, column, value):
    evidence = _normalized("pl_imgw")
    frame = getattr(evidence, relation).with_columns(
        pl.when(pl.int_range(pl.len()) == 0)
        .then(pl.lit(value, dtype=pl.UInt32))
        .otherwise(pl.col(column))
        .alias(column)
    )
    with pytest.raises(ValidationError):
        CatalogueEvidence.model_validate(_change(evidence, relation, frame))


@pytest.mark.parametrize(
    "column,value",
    [
        ("requested_from", ["https://bad host"]),
        ("requested_from", []),
        ("recording_ids", [None]),
        ("method", "guess"),
        ("instant_type", "runtime"),
        ("retrieved_at_start", None),
        ("material_sha256", "invalid"),
    ],
)
def test_acquisition_semantics_fail_closed(column, value):
    evidence = _normalized("usgs_nwis")
    frame = evidence.acquisitions.with_columns(
        pl.when(pl.int_range(pl.len()) == 0)
        .then(pl.lit(value, dtype=EVIDENCE_SCHEMAS["acquisitions"][column]))
        .otherwise(pl.col(column))
        .alias(column)
    )
    with pytest.raises(ValidationError):
        CatalogueEvidence.model_validate(_change(evidence, "acquisitions", frame))


def test_exact_file_authority_and_bytes():
    evidence = _normalized("usgs_nwis")
    files = encode_catalogue_evidence(evidence)
    header = EvidenceHeader.model_validate_json(files.pop("provenance.json"))
    with pytest.raises(ValueError, match="five"):
        parse_catalogue_evidence(header, {**files, "native.parquet": b"private"})
    filename = next(iter(files))
    with pytest.raises(ValueError, match="digest"):
        parse_catalogue_evidence(header, {**files, filename: files[filename] + b"changed"})
    payload = header.model_dump()
    payload["files"][filename]["path"] = "../" + filename
    with pytest.raises(ValidationError, match="basename"):
        EvidenceHeader.model_validate(payload)


@pytest.mark.parametrize("provider", ["fr_hubeau", "ba_fhmzbih", "th_thaiwater"])
def test_every_actual_pair_has_exact_availability_locator(provider):
    evidence = _normalized(provider)
    path = ROOT / provider / "catalogue"
    pairs = pl.read_parquet(path / "station_products.parquet")
    stations = pl.read_parquet(path / "stations.parquet")
    locators = evidence.facts.filter(pl.col("locator_role") == "availability")
    plt.assert_frame_equal(
        locators.select("station_id", "product_id").sort("station_id", "product_id"),
        pairs.select("station_id", "product_id").sort("station_id", "product_id"),
    )
    with pytest.raises(ValueError, match="absent canonical"):
        validate_catalogue_locators(evidence, stations=stations, station_products=pairs.slice(1))
    fact = locators["fact_id"][0]
    frame = evidence.facts.with_columns(
        [
            pl.when(pl.col("fact_id") == fact).then(None).otherwise(pl.col(c)).alias(c)
            for c in ("carrier", "station_id", "product_id", "locator_role")
        ]
    )
    incomplete = CatalogueEvidence.model_validate(_change(evidence, "facts", frame))
    with pytest.raises(ValueError, match="exactly cover"):
        validate_catalogue_locators(incomplete, stations=stations, station_products=pairs)


def test_runtime_ancestor_and_source_ownership_rejected():
    evidence = _normalized("pl_imgw")
    # A transformed canonical binding cannot consume its own output.
    b = evidence.bindings.filter(pl.col("transformation_id").is_not_null())["binding_id"][0]
    fact = evidence.binding_facts.filter(pl.col("binding_id") == b)["fact_id"][0]
    inputs = evidence.external_inputs.with_columns(
        pl.when((pl.col("binding_id") == b) & (pl.col("position") == 0))
        .then(pl.lit(fact, dtype=pl.UInt32))
        .otherwise(pl.col("fact_id"))
        .alias("fact_id"),
        pl.when((pl.col("binding_id") == b) & (pl.col("position") == 0))
        .then(None)
        .otherwise(pl.col("source_ordinal"))
        .alias("source_ordinal"),
    )
    with pytest.raises(ValidationError, match="cycle"):
        CatalogueEvidence.model_validate(_change(evidence, "external_inputs", inputs))
    inputs = evidence.external_inputs.with_columns(
        pl.when((pl.col("binding_id") == b) & (pl.col("position") == 0))
        .then(None)
        .otherwise(pl.col("source_ordinal"))
        .alias("source_ordinal")
    )
    with pytest.raises(ValidationError, match="misattributed"):
        CatalogueEvidence.model_validate(_change(evidence, "external_inputs", inputs))
    # Runtime cannot become the ancestor of packaged station facts.
    acquisition = evidence.acquisitions.with_columns(
        [
            pl.when(pl.col("acquisition_key") == 0)
            .then(pl.lit(value, dtype=EVIDENCE_SCHEMAS["acquisitions"][column]))
            .otherwise(pl.col(column))
            .alias(column)
            for column, value in (
                ("method", "runtime_http_request"),
                ("instant_type", "runtime"),
                ("retrieved_at_start", None),
                ("retrieved_at_end", None),
            )
        ]
    )
    with pytest.raises(ValidationError, match="runtime acquisitions"):
        CatalogueEvidence.model_validate(_change(evidence, "acquisitions", acquisition))


@pytest.mark.parametrize(
    "column,value", [("requested_from", ["https://example.org/other"]), ("retrieved_at_start", "2000-01-01T00:00:00Z")]
)
def test_statement_requires_exact_request_and_instant(column, value):
    evidence = _normalized("usgs_nwis")
    statement = evidence.header.source_records[0].statements[0]
    key = evidence.acquisitions.filter(pl.col("recording_ids").list.contains(statement.recording_id))[
        "acquisition_key"
    ][0]
    frame = evidence.acquisitions.with_columns(
        pl.when(pl.col("acquisition_key") == key)
        .then(pl.lit(value, dtype=EVIDENCE_SCHEMAS["acquisitions"][column]))
        .otherwise(pl.col(column))
        .alias(column)
    )
    with pytest.raises(ValidationError, match="exact recording URL and instant"):
        CatalogueEvidence.model_validate(_change(evidence, "acquisitions", frame))


@pytest.mark.parametrize("mutation", ["extra", "unequal", "boolean", "negative", "overflow", "string", "partial"])
def test_json_column_boundary_rejects_invalid_shapes(mutation):
    import json

    payload = _normalized("usgs_nwis").model_dump(mode="json")
    if mutation == "extra":
        payload["facts"]["extra"] = []
    elif mutation == "unequal":
        payload["facts"]["name"].pop()
    elif mutation == "partial":
        payload["facts"]["station_id"][0] = "unlocated"
    else:
        payload["facts"]["fact_id"][0] = {"boolean": True, "negative": -1, "overflow": 2**32, "string": "0"}[mutation]
    with pytest.raises(ValidationError):
        CatalogueEvidence.model_validate_json(json.dumps(payload))


def test_v3_parse_never_constructs_old_national_models(monkeypatch):
    from rivretrieve._internal import acquisition_provenance as legacy

    evidence = _normalized("th_thaiwater")
    files = encode_catalogue_evidence(evidence)
    header = EvidenceHeader.model_validate_json(files.pop("provenance.json"))

    def reject(*args, **kwargs):
        raise AssertionError("v2 national model constructed")

    for model in (
        legacy.AcquisitionProvenance,
        legacy.AcquisitionRecord,
        legacy.FactBinding,
        legacy.ExternalFactReference,
        legacy.Transformation,
        legacy.SourceRecord,
    ):
        monkeypatch.setattr(model, "__init__", reject)
    parsed = parse_catalogue_evidence(header, files)
    plt.assert_frame_equal(parsed.facts, evidence.facts)


# Brazil has new adopted-product acquisitions after this migration oracle.
# Its current evidence still passes the all-provider lossless roundtrip above;
# source-material and per-pair assertions live in test_br_ana_catalogue_telemetry.
def _assert_usgs_definition_extension_and_restore_original(provenance):
    """Prove the exact new publisher evidence, then compare every original assertion."""
    model = provenance.model_dump(mode="json")
    fact = "source.usgs.instantaneous_value_definition"
    recording_id = "usgs_nwis_instantaneous_values_definition"
    acquisition_id = "instantaneous_values_definition_capture_2026_09_19"
    source_url = "https://waterservices.usgs.gov/docs/instantaneous-values/instantaneous-values-details/"
    retrieved_at = "2026-09-19T20:58:46.743636Z"
    digest = "1cec37f8cec8173f635d4afaba2d08814347d9cff672b25c29d427b004d0b3a2"
    repository_path = "tests/test_data/usgs_nwis_instantaneous_values_definition.html"
    source_bytes = (Path(__file__).parents[1] / repository_path).read_bytes()
    assert sha256(source_bytes).hexdigest() == digest
    assert b"most recent instantaneous value" in source_bytes
    expected_acquisition = {
        "acquisition_id": acquisition_id,
        "method": "http_request",
        "instant_type": "retrieval",
        "description": "Publisher Instantaneous Values Service Details documentation calls the returned measurement an instantaneous value; it does not establish a concrete series sampling frequency.",
        "requested_from": [source_url],
        "retrieved_at_start": retrieved_at,
        "retrieved_at_end": None,
        "recording_ids": [recording_id],
        "material": None,
    }
    expected_evidence = {
        "evidence_id": "usgs_instantaneous_value_definition",
        "description": 'Publisher service documentation: "most recent instantaneous value"; the service request URL is /nwis/iv/.',
        "recording": {
            "recording_id": recording_id,
            "repository_path": repository_path,
            "source_url": source_url,
            "retrieved_at": retrieved_at,
            "media_type": "text/html; charset=UTF-8",
            "sha256": digest,
        },
    }
    expected_binding = {
        "fact_group": "instantaneous_value_definition",
        "facts": [fact],
        "source_id": "usgs_nwis",
        "acquisition_id": acquisition_id,
    }
    assert model["fact_universe"].count(fact) == 1
    assert model["fact_universe"][0] == fact
    source = next(item for item in model["source_records"] if item["source_id"] == "usgs_nwis")
    assert [item for item in source["acquisitions"] if item["acquisition_id"] == acquisition_id] == [
        expected_acquisition
    ]
    assert source["acquisitions"][-1] == expected_acquisition
    assert [item for item in source["evidence"] if item["evidence_id"] == expected_evidence["evidence_id"]] == [
        expected_evidence
    ]
    assert source["evidence"][0] == expected_evidence
    assert [item for item in model["fact_bindings"] if item["fact_group"] == expected_binding["fact_group"]] == [
        expected_binding
    ]
    assert model["fact_bindings"][0] == expected_binding
    # Remove only the exact, separately verified additions. All other contents
    # and their complete original order remain subject to the pinned v2 oracle.
    model["fact_universe"].pop(0)
    source["acquisitions"].pop()
    source["evidence"].pop(0)
    model["fact_bindings"].pop(0)
    return AcquisitionProvenance.model_validate(model)


def _assert_bulk_source_history_preserved(provider, provenance):
    """Compare retained source inputs, not superseded output/authority assertions."""
    path = Path(__file__).parent / "test_data/catalogue_provenance_original_v2" / f"{provider}.json"
    original = AcquisitionProvenance.model_validate_json(path.read_bytes())
    before = original.model_dump(mode="json")
    after = provenance.model_dump(mode="json")
    if provider == "ca_eccc":
        # The observation carrier changed; publisher evidence did not.
        assert before["fact_universe"][7] == "observation.canonical_five_column_shape"
        assert after["fact_universe"][7] == "observation.identity_bearing_shape"
        after["fact_universe"][7] = before["fact_universe"][7]
        old_binding = next(x for x in before["fact_bindings"] if x["fact_group"] == "canonical_observation_shape")
        new_binding = next(x for x in after["fact_bindings"] if x["fact_group"] == "canonical_observation_shape")
        assert new_binding["facts"] == ["observation.identity_bearing_shape"]
        assert (
            new_binding["transformation"]["name"]
            == "HYDAT observations to identity-bearing RivRetrieve observation rows"
        )
        new_binding["facts"] = old_binding["facts"]
        new_binding["transformation"]["name"] = old_binding["transformation"]["name"]
    elif provider == "pl_imgw":
        source = next(x for x in after["source_records"] if x["source_id"] == "sr.pl.imgw")
        assert source["acquisitions"][0]["acquisition_id"] == "imgw_archive_definitions_2026_09_20"
        assert source["acquisitions"][0]["recording_ids"] == ["pl_imgw_codz_format", "pl_imgw_yearbook_2025"]
        source["acquisitions"].pop(0)
        assert [x["evidence_id"] for x in source["evidence"][:2]] == [
            "pl_imgw_codz_definition",
            "pl_imgw_yearbook_methods",
        ]
        del source["evidence"][:2]
        physics = next(x for x in after["fact_bindings"] if x["fact_group"] == "imgw_archive_physics")
        assert physics == {
            "fact_group": "imgw_archive_physics",
            "facts": ["source.imgw.observation_archive_product_semantics"],
            "source_id": "sr.pl.imgw",
            "acquisition_id": "imgw_archive_definitions_2026_09_20",
        }
        after["fact_bindings"].remove(physics)
        roster = next(x for x in after["fact_bindings"] if x["fact_group"] == "imgw_catalogue_inputs")
        assert "source.imgw.observation_archive_product_semantics" not in roster["facts"]
        roster["facts"].insert(1, "source.imgw.observation_archive_product_semantics")
    else:
        # CatalogueOnly has no runtime observation acquisition. Its field facts
        # now cite recovered publisher legends rather than a station catalogue.
        (old_source,) = before["source_records"]
        (new_source,) = after["source_records"]
        assert [x["acquisition_id"] for x in old_source["acquisitions"]] == [
            "verified_hydrology_archive_campaign_2026_08_02",
            "observation_request",
        ]
        assert [x["acquisition_id"] for x in new_source["acquisitions"]] == [
            "verified_hydrology_archive_campaign_2026_08_02",
            "daily_field_definitions_repository_recovery",
            "point_field_definitions_repository_recovery",
        ]
        old_note = next(x for x in old_source["evidence"] if x["evidence_id"] == "za_dws_observation_terms_absence")
        new_note = next(x for x in new_source["evidence"] if x["evidence_id"] == "za_dws_observation_terms_absence")
        assert new_note["description"] == (
            "Archived A2H023 Monthly response publishes Variable 100.00 Surface Water Level and monthly volumes "
            "in million cubic metres; no equivalence with D_AVG_FR, COR_FLOW or COR_LEVEL is established. "
            "No applicable terms or citation statement."
        )
        new_note["description"] = old_note["description"]
        old_source["acquisitions"].pop()
        del new_source["acquisitions"][1:]
        removed = {
            "source.product.dws_datatype_and_file_semantics",
            "source.observation.dws_fixed_format_values_quality_and_time",
        }
        added = {"source.product.daily_field_definition", "source.product.point_field_definitions"}
        assert set(before["fact_universe"]) - set(after["fact_universe"]) == removed
        assert set(after["fact_universe"]) - set(before["fact_universe"]) == added
        before["fact_universe"] = [x for x in before["fact_universe"] if x not in removed]
        after["fact_universe"] = [x for x in after["fact_universe"] if x not in added]
        for group, fact, acquisition in (
            (
                "daily_product_identity",
                "source.product.daily_field_definition",
                "daily_field_definitions_repository_recovery",
            ),
            (
                "point_product_identity",
                "source.product.point_field_definitions",
                "point_field_definitions_repository_recovery",
            ),
        ):
            assert next(x for x in after["fact_bindings"] if x["fact_group"] == group) == {
                "fact_group": group,
                "facts": [fact],
                "source_id": "za_dws",
                "acquisition_id": acquisition,
            }
        before["fact_bindings"] = [
            x for x in before["fact_bindings"] if x["fact_group"] not in {"product_identity", "observation_values"}
        ]
        after["fact_bindings"] = [
            x
            for x in after["fact_bindings"]
            if x["fact_group"] not in {"daily_product_identity", "point_product_identity"}
        ]
        for model, omitted in ((before, removed), (after, added)):
            carrier = next(x for x in model["fact_bindings"] if x["fact_group"] == "canonical_catalogue_carrier")
            carrier["transformation"]["external_inputs"] = [
                x for x in carrier["transformation"]["external_inputs"] if x["fact"] not in omitted
            ]
    assert after == before
    # The immutable historical fixture, not today's corrected assertions, remains
    # subject to the original full ordered digest below.
    return original


@pytest.mark.parametrize("provider", tuple(provider for provider in BUILTIN_PROVIDER_IDS if provider != "br_ana"))
def test_all_ordered_source_assertions_match_pinned_original_revision(provider):
    oracle = json.loads((Path(__file__).parent / "test_data/catalogue_provenance_ordered_v2.json").read_text())
    assert oracle["revision"] == "6f0edf6a455735cb1f8c858a1a9f35d4245cf209"
    # This expected digest comes from original v2 Git bytes, not a v3 self-roundtrip.
    restored = _legacy(provider)
    if provider in {"ca_eccc", "pl_imgw", "za_dws"}:
        restored = _assert_bulk_source_history_preserved(provider, restored)
    if provider == "usgs_nwis":
        restored = _assert_usgs_definition_extension_and_restore_original(restored)
        assert oracle["providers"][provider]["ordered_model_sha256"] == (
            "28e9cc34f71f4fd3712c69cc205c30b8c70d55270cfc04f90e991a55121450a0"
        )
    ordered = json.dumps(restored.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    assert sha256(ordered.encode()).hexdigest() == oracle["providers"][provider]["ordered_model_sha256"]
