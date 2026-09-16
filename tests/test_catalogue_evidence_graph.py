"""Selected evidence closure : PackagedCatalogue × ExactFactSelection → FaithfulJSONLD."""

import json
import socket

import polars as pl
import pytest
from rdflib import Graph, Literal, Namespace

from rivretrieve._internal.catalogues.evidence_graph import CanonicalPair, FactSelection, resolve_evidence
from rivretrieve._internal.issues import FatalContractError
from tests.test_catalogue_descriptor import _deny_network, _inputs, _path

SC = Namespace("https://schema.org/")
BASE = "https://example.org/catalogue/"


def _nodes(value: object) -> list[dict]:
    assert isinstance(value, list)
    result: list[dict] = []
    for node in value:
        assert isinstance(node, dict)
        result.append(node)
    return result


@pytest.mark.parametrize("provider", ("fr_hubeau", "ba_fhmzbih", "th_thaiwater"))
@pytest.mark.parametrize("availability", ("available", "unknown"))
def test_actual_pair_closure_retains_exact_identity_status_reason_and_acquisition(provider, availability, monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _deny_network)
    evidence, _, _ = _inputs(provider)
    row = (
        pl.read_parquet(_path(provider) / "station_products.parquet")
        .filter(pl.col("availability") == availability)
        .row(0, named=True)
    )
    pair = CanonicalPair(**{name: row[name] for name in CanonicalPair.model_fields})
    fact = evidence.facts.filter(
        (pl.col("station_id") == pair.station_id)
        & (pl.col("product_id") == pair.product_id)
        & (pl.col("locator_role") == "availability")
    )
    selection = FactSelection(names=(fact["name"].item(),))
    resolved = resolve_evidence(evidence, selection, pair)
    properties = _nodes(resolved["additionalProperty"])
    nodes = _nodes(resolved["@graph"])
    assert {item["name"]: item["value"] for item in properties} == pair.model_dump()
    graph = Graph().parse(data=json.dumps(resolved), format="json-ld", publicID=BASE)
    selected_node = next(graph.subjects(SC.identifier, Literal(selection.names[0])))
    ancestors = set(graph.transitive_objects(selected_node, SC.isBasedOn))
    actual_ids = {
        str(node).removeprefix(BASE + "acquisition/")
        for node in ancestors
        if str(node).startswith(BASE + "acquisition/")
    }
    pending = set(fact["fact_id"])
    expected_keys = set()
    visited = set()
    while pending:
        current = pending - visited
        if not current:
            break
        visited.update(current)
        memberships = evidence.binding_facts.filter(pl.col("fact_id").is_in(current))
        bindings = evidence.bindings.join(memberships.select("binding_id").unique(), on="binding_id", how="semi")
        expected_keys.update(str(key) for key in bindings["acquisition_key"].drop_nulls())
        pending = set(
            evidence.external_inputs.join(bindings.select("binding_id"), on="binding_id", how="semi")["fact_id"]
        )
    assert actual_ids == expected_keys
    for key in expected_keys:
        acquisition = evidence.acquisitions.filter(pl.col("acquisition_key") == int(key)).row(0, named=True)
        node = next(node for node in nodes if node["@id"] == f"acquisition/{key}")
        assert node["identifier"] == acquisition["acquisition_id"]
        assert node["url"] == acquisition["requested_from"]
        assert node["description"] == evidence.header.descriptions[acquisition["description_id"]]
        assert node["subjectOf"]["name"] == acquisition["instant_type"]
        assert node["subjectOf"].get("startDate") == acquisition["retrieved_at_start"]
        assert node["subjectOf"].get("endDate") == acquisition["retrieved_at_end"]
        source = evidence.header.source_records[acquisition["source_ordinal"]]
        assert node["creator"]["name"] == source.issuer
        if acquisition["material_sha256"] is not None:
            assert node["sha256"] == acquisition["material_sha256"]
            assert node["contentSize"] == f"{acquisition['material_byte_count']} B"
    assert len(nodes) < 200
    for field in ("provider_id", "station_id", "product_id"):
        wrong = pair.model_copy(update={field: pair.model_dump()[field] + "-wrong"})
        with pytest.raises(FatalContractError, match="pair identity"):
            resolve_evidence(evidence, selection, wrong)


def test_undeclared_fact_is_not_guessed():
    evidence, _, _ = _inputs("pl_imgw")
    with pytest.raises(FatalContractError, match="undeclared exact fact"):
        resolve_evidence(evidence, FactSelection(names=("station.latitude-guess",)))


def test_brazil_adopted_product_fact_resolves_to_documented_source_material():
    evidence, _, _ = _inputs("br_ana")
    resolved = resolve_evidence(evidence, FactSelection(names=("product.product_id",)))
    nodes = _nodes(resolved["@graph"])
    assert not any("rr:absence" in node for node in nodes)
    assert any(node["@id"].startswith("acquisition/") for node in nodes)
    assert "89e2929cb436241b4aae2bbb04c4077edd55379886f39c9a32eb7fec0c8faba3" in str(nodes)


def test_source_terms_are_once_and_explicitly_linked_from_every_selected_acquisition():
    evidence, _, _ = _inputs("usgs_nwis")
    result = resolve_evidence(
        evidence, FactSelection(names=("station.station_id", "provider.license", "provider.citation"))
    )
    graph_nodes = _nodes(result["@graph"])
    nodes = {node["@id"]: node for node in graph_nodes}
    source = evidence.header.source_records[0]
    for statement in source.statements:
        if statement.verification_status != "verified_public_recording":
            continue
        matches = [node for node in nodes.values() if node.get("text") == statement.exact_text]
        assert len(matches) == 1
        for identity, node in nodes.items():
            if identity.startswith("acquisition/"):
                assert {"@id": matches[0]["@id"]} in node[statement.kind]
