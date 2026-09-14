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


@pytest.mark.parametrize("provider", BUILTIN_PROVIDER_IDS)
def test_all_ordered_source_assertions_match_pinned_original_revision(provider):
    oracle = json.loads((Path(__file__).parent / "test_data/catalogue_provenance_ordered_v2.json").read_text())
    assert oracle["revision"] == "6f0edf6a455735cb1f8c858a1a9f35d4245cf209"
    # This expected digest comes from original v2 Git bytes, not a v3 self-roundtrip.
    restored = _legacy(provider)
    ordered = json.dumps(restored.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    assert sha256(ordered.encode()).hexdigest() == oracle["providers"][provider]["ordered_model_sha256"]
