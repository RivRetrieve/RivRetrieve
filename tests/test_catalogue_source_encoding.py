"""Disk encoding controls are authored fixtures, not publisher recordings."""

import json

import pytest

from rivretrieve._internal.catalogues.source_series import (
    SourceDescription,
    SourceDescriptions,
    decode_source_descriptions,
    encode_source_descriptions,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.source_series import PhysicalFacts, SourceIdentity, known


def descriptions():
    facts = PhysicalFacts(
        facts_id="physical", quantity=known("stage", "source"), source_unit=known("m", "source"), normalized_unit="m"
    )
    return SourceDescriptions(
        provider_id="test",
        descriptions=tuple(
            SourceDescription(
                product_id="stage",
                station_id=station,
                identity=SourceIdentity(
                    namespace="source", published_id=station, origin="catalogue", evidence=("source",)
                ),
                facts=(facts,),
            )
            for station in ("one", "two")
        ),
    )


@pytest.mark.parametrize("revision", [1, 2])
def test_encoding_preserves_all_source_facts_and_identity(revision):
    expected = descriptions()
    actual = decode_source_descriptions(encode_source_descriptions(expected, schema_version=revision))
    assert actual == expected
    if revision == 2:
        assert actual.descriptions[0].facts[0] is actual.descriptions[1].facts[0]


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda raw: raw["physical_facts"].append(raw["physical_facts"][0]), "Duplicate physical-fact identifiers"),
        (lambda raw: raw["descriptions"][0].update(facts_ids=["missing"]), "Missing referenced"),
        (
            lambda raw: raw["descriptions"][0].update(facts_ids=["physical", "physical"]),
            "Duplicate physical-fact references",
        ),
        (lambda raw: raw["descriptions"][0].update(facts_ids=[]), "nonempty physical-fact references"),
        (lambda raw: raw.update(descriptions=[]), "Unreferenced physical facts"),
        (lambda raw: raw.update(extra=True), "Extra inputs"),
        (lambda raw: raw["descriptions"][0].update(extra=True), "Extra inputs"),
        (lambda raw: raw["descriptions"][0].update(facts=[]), "must reference physical facts"),
        (lambda raw: raw.update(schema_version=3), "Unsupported"),
    ],
)
def test_encoding_rejects_invalid_references_and_schema(mutation, message):
    raw = json.loads(encode_source_descriptions(descriptions(), schema_version=2))
    mutation(raw)
    with pytest.raises(FatalContractError, match=message):
        decode_source_descriptions(json.dumps(raw).encode())


def test_encoder_rejects_same_id_with_conflicting_physical_facts():
    value = descriptions()
    first, second = value.descriptions
    changed = second.facts[0].model_copy(update={"quantity": known("discharge", "source")})
    value = value.model_copy(update={"descriptions": (first, second.model_copy(update={"facts": (changed,)}))})
    with pytest.raises(FatalContractError, match="Conflicting physical facts"):
        encode_source_descriptions(value, schema_version=2)


def test_referenced_physical_facts_remain_immutable():
    from pydantic import ValidationError

    decoded = decode_source_descriptions(encode_source_descriptions(descriptions(), schema_version=2))
    with pytest.raises(ValidationError, match="frozen"):
        decoded.descriptions[0].facts[0].facts_id = "changed"
