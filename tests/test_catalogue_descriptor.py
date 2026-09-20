from __future__ import annotations

import importlib
import json
import socket
from hashlib import sha256
from itertools import islice
from pathlib import Path

import mlcroissant as mlc
import polars as pl
import polars.testing as pl_testing
import pytest
from rdflib import RDF, Graph, Literal, Namespace, URIRef

from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance
from rivretrieve._internal.catalogues.artifact import REQUIRED_ARTIFACT_FILES
from rivretrieve._internal.catalogues.descriptor import ABSENCE_NAMESPACE, PROFILE_URI, build_catalogue_descriptor
from rivretrieve._internal.catalogues.evidence import (
    EVIDENCE_FILENAMES,
    EVIDENCE_SCHEMAS,
    EvidenceHeader,
    normalize_provenance,
)
from rivretrieve._internal.catalogues.evidence_encoding import encode_catalogue_evidence, parse_catalogue_evidence
from rivretrieve._internal.catalogues.evidence_graph import FactSelection, resolve_evidence
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS

ROOT = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers"
SC = Namespace("https://schema.org/")
BASE = "https://example.org/catalogue/"


def _path(provider: str) -> Path:
    return ROOT / provider / "catalogue"


def _descriptor(provider: str) -> dict:
    return json.loads((_path(provider) / "croissant.json").read_text())


def _inputs(provider: str):
    directory = _path(provider)
    payload = (directory / "provenance.json").read_bytes()
    canonical = {name: (directory / name).read_bytes() for name in REQUIRED_ARTIFACT_FILES}
    if json.loads(payload)["schema_version"] == 2:
        legacy = AcquisitionProvenance.model_validate_json(payload)
        provenance = normalize_provenance(
            legacy,
            stations=pl.read_parquet(directory / "stations.parquet"),
            station_products=pl.read_parquet(directory / "station_products.parquet"),
        )
        evidence_files = encode_catalogue_evidence(provenance)
    else:
        evidence_files = {
            "provenance.json": payload,
            **{name: (directory / name).read_bytes() for name in EVIDENCE_FILENAMES.values()},
        }
        provenance = parse_catalogue_evidence(
            EvidenceHeader.model_validate_json(payload),
            {name: evidence_files[name] for name in EVIDENCE_FILENAMES.values()},
        )
    module = importlib.import_module(f"rivretrieve._internal.providers.{provider}.origins")
    origins = (
        (module.HYDROMETRY_STATION_CATALOGUE_ORIGINS, module.TEMPERATURE_STATION_CATALOGUE_ORIGINS)
        if provider == "fr_hubeau"
        else (module.STATION_CATALOGUE_ORIGINS,)
    )
    files = {
        **canonical,
        **evidence_files,
        **{
            name: (directory / name).read_bytes()
            for name in ("format.json", "source_series.json", "series_claims.parquet")
        },
    }
    return provenance, origins, files


def _record_sets(value: object) -> list[dict]:
    assert isinstance(value, list)
    records: list[dict] = []
    for record in value:
        assert isinstance(record, dict)
        records.append(record)
    return records


def _field(descriptor: dict, identity: str) -> dict:
    return next(field for record in descriptor["recordSet"] for field in record["field"] if field["@id"] == identity)


def _graph(provider: str) -> Graph:
    return Graph().parse(data=json.dumps(_descriptor(provider)), format="json-ld", publicID=BASE)


def _deny_network(*args, **kwargs):
    raise AssertionError("Catalogue description attempted network access")


@pytest.mark.parametrize("provider", tuple(BUILTIN_PROVIDER_IDS))
def test_every_committed_descriptor_passes_reference_validator_without_network(provider: str, monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _deny_network)
    dataset = mlc.Dataset(_path(provider) / "croissant.json")
    assert len(dataset.metadata.record_sets) == 9
    assert _descriptor(provider)["schemaVersion"] == PROFILE_URI
    descriptor = _descriptor(provider)
    for distribution in descriptor["distribution"]:
        assert distribution["sha256"] == sha256((_path(provider) / distribution["contentUrl"]).read_bytes()).hexdigest()
    for record in descriptor["recordSet"]:
        for field in record["field"]:
            assert "source" in field
            if not record["@id"].startswith("provenance_"):
                assert "subjectOf" in field or "rr:absence" in field


@pytest.mark.parametrize("provider", tuple(BUILTIN_PROVIDER_IDS))
def test_jsonld_uses_only_standard_properties_and_preserves_absence_literals(provider: str):
    graph = _graph(provider)
    for predicate in set(graph.predicates()):
        assert str(predicate).startswith(
            (str(SC), "http://mlcommons.org/croissant/", str(RDF), "http://purl.org/dc/terms/")
        ) or predicate == URIRef(ABSENCE_NAMESPACE + "absence")
    descriptor = _descriptor(provider)
    for record in descriptor["recordSet"]:
        for node in [record, *record["field"]]:
            if "rr:absence" in node:
                values = list(graph.objects(URIRef(BASE + node["@id"]), URIRef(ABSENCE_NAMESPACE + "absence")))
                assert len(values) == 1 and isinstance(values[0], Literal) and values[0].datatype == RDF.JSON
                assert json.loads(str(values[0])) == node["rr:absence"]


def test_poland_historical_derivation_retains_both_issuers_and_separate_corroboration():
    evidence, _, _ = _inputs("pl_imgw")
    graph = Graph().parse(
        data=json.dumps(resolve_evidence(evidence, FactSelection(names=("station.latitude", "station.station_id")))),
        format="json-ld",
        publicID=BASE,
    )
    for column in ("latitude", "station_id"):
        field = next(graph.subjects(SC.identifier, Literal("station." + column)))
        lineage = next(graph.objects(field, SC.isBasedOn))
        inputs = set(graph.transitive_objects(lineage, SC.isBasedOn))
        recovered = next(
            subject
            for subject in graph.subjects(
                SC.sha256, Literal("8c4cdd675c2811cd3b91a5889cbcd4273830c2fa4ee90ad6142c69ba7a198f49")
            )
        )
        workbook = next(
            subject
            for subject in graph.subjects(
                SC.sha256, Literal("dfab6ea7de80fb1570f4a8dded8743ed7c7dcb4eb67fe75e2c0e02e9b964b7bf")
            )
        )
        assert recovered in inputs
        assert workbook not in inputs
        assert not list(graph.objects(workbook, SC.contentUrl))
        assert "not established as the historical acquisition" in str(next(graph.objects(workbook, SC.description)))
        assert list(graph.subjects(SC.citation, workbook))
        assert not list(graph.objects(recovered, SC.license))
        assert not list(graph.objects(recovered, SC.citation))
        if column == "station_id":
            names = {
                str(name)
                for material in inputs
                for creator in graph.objects(material, SC.creator)
                for name in graph.objects(creator, SC.name)
            }
            assert "Global Runoff Data Centre" in names
            assert "Institute of Meteorology and Water Management – National Research Institute" in names


def test_field_absences_distinguish_documented_silence_and_missing_acquisition():
    from rivretrieve._internal.catalogue_origins import NotPublished
    from rivretrieve._internal.providers.ch_foen.origins import STATION_CATALOGUE_ORIGINS

    assert isinstance(STATION_CATALOGUE_ORIGINS["crs"], NotPublished)
    swiss = _field(_descriptor("ch_foen"), "stations/crs")
    polish = _field(_descriptor("pl_imgw"), "stations/crs")
    assert swiss["rr:absence"] == {"kind": "not_published", "evidence": str(STATION_CATALOGUE_ORIGINS["crs"].evidence)}
    assert polish["rr:absence"] == {"kind": "withheld", "reason": "no_acquisition_record_established"}
    assert (
        swiss["source"] == polish["source"] == {"fileObject": {"@id": "stations.parquet"}, "extract": {"column": "crs"}}
    )


@pytest.mark.parametrize("provider", ("ba_fhmzbih", "fr_hubeau", "th_thaiwater"))
@pytest.mark.parametrize("record_set", ("stations", "station_products"))
def test_evidenced_baseline_record_sets_do_not_report_withheld_rows(provider: str, record_set: str):
    record = next(record for record in _descriptor(provider)["recordSet"] if record["@id"] == record_set)
    assert "rr:absence" not in record


def test_reference_loader_reads_empty_tables_and_null_fields(monkeypatch, tmp_path):
    # Inventory-only projection remains a valid empty-table fixture, even though
    # the shipped Brazil catalogue now includes evidenced adopted telemetry.
    from rivretrieve._internal.catalogues.native import read_native_table
    from rivretrieve._internal.providers.br_ana.capture import read_capture_record
    from rivretrieve._internal.providers.br_ana.generate_catalogue import build_catalogue, write_catalogue
    from rivretrieve._internal.providers.br_ana.origins import STATION_CATALOGUE_ORIGINS, build_acquisition_provenance

    monkeypatch.setattr(socket.socket, "connect", _deny_network)
    repository = Path(__file__).parents[1]
    capture = read_capture_record(repository / "tests/test_data/br_ana_inventory/capture.json")
    inventory = build_catalogue(
        read_native_table(repository / capture.native_table.repository_path),
        STATION_CATALOGUE_ORIGINS,
        build_acquisition_provenance(capture),
    )
    write_catalogue(inventory, tmp_path)
    brazil = mlc.Dataset(tmp_path / "croissant.json")
    for record in ("products", "station_products"):
        assert list(brazil.records(record)) == []
    provider = list(brazil.records("provider"))
    assert provider[0]["provider/catalogue_version"] is not None
    assert len(list(islice(brazil.records("stations"), 1))) == 1
    poland = mlc.Dataset(_path("pl_imgw") / "croissant.json")
    rows = list(islice(poland.records("station_products"), 3))
    extracted = pl.DataFrame(
        [
            {
                key.partition("/")[2]: value.decode()
                if isinstance(value, bytes)
                else value.date()
                if hasattr(value, "date")
                else value
                for key, value in row.items()
            }
            for row in rows
        ]
    )
    expected = pl.read_parquet(_path("pl_imgw") / "station_products.parquet").head(3)
    extracted = extracted.cast(expected.schema)
    pl_testing.assert_frame_equal(extracted, expected)


def test_brazil_preserves_attested_identity_and_exposes_documented_adopted_products():
    descriptor = _descriptor("br_ana")
    provenance, _, _ = _inputs("br_ana")
    assert descriptor["license"] == provenance.header.source_records[0].statements[0].exact_text
    assert {"version", "datePublished", "isBasedOn"} <= set(descriptor)
    assert provenance.header.native_table is not None
    records = {record["@id"]: record for record in descriptor["recordSet"]}
    assert "rr:absence" not in records["stations"]
    for name in ("products", "station_products"):
        assert "rr:absence" not in records[name]
    documentation = provenance.acquisitions.filter(pl.col("acquisition_id") == "adopted_telemetry_manual")
    assert documentation["material_sha256"].to_list() == [
        "89e2929cb436241b4aae2bbb04c4077edd55379886f39c9a32eb7fec0c8faba3"
    ]


def test_generator_rejects_missing_origins_and_unattributed_canonical_column():
    provenance, origins, files = _inputs("pl_imgw")
    with pytest.raises(FatalContractError, match="requires station origins"):
        build_catalogue_descriptor(provenance, (), files)
    damaged = dict(origins[0])
    del damaged["latitude"]
    with pytest.raises(FatalContractError, match="Station column has no origin"):
        build_catalogue_descriptor(provenance, (damaged,), files)
    damaged_evidence = provenance.model_copy(
        update={
            "binding_facts": provenance.binding_facts.join(
                provenance.facts.filter(pl.col("name") == "station.latitude").select("fact_id"),
                on="fact_id",
                how="anti",
            )
        }
    )
    with pytest.raises(FatalContractError, match="Canonical column has no lineage or withheld fact"):
        build_catalogue_descriptor(damaged_evidence, origins, files)


def test_generator_rejects_native_byte_identity_without_size():
    evidence, origins, files = _inputs("pl_imgw")
    assert evidence.header.native_table is not None
    header = evidence.header.model_copy(
        update={"native_table": evidence.header.native_table.model_copy(update={"byte_size": None})}
    )
    with pytest.raises(FatalContractError, match="Native table byte size"):
        build_catalogue_descriptor(evidence.model_copy(update={"header": header}), origins, files)


def test_verbatim_source_terms_remain_separate_and_uninterpreted():
    descriptor = _descriptor("usgs_nwis")
    provenance, _, _ = _inputs("usgs_nwis")
    for kind in ("license", "citation"):
        assert descriptor[kind] == next(
            statement.exact_text
            for statement in provenance.header.source_records[0].statements
            if statement.kind == kind
        )
    for provider in ("ch_foen", "ca_eccc", "pl_imgw", "fr_hubeau", "th_thaiwater"):
        assert "license" not in _descriptor(provider) and "citation" not in _descriptor(provider)
    bosnia = _descriptor("ba_fhmzbih")
    provenance, _, _ = _inputs("ba_fhmzbih")
    assert bosnia["subjectOf"]["url"] == "provenance.json"
    source = provenance.header.source_records[0]
    assert any(statement.kind == "terms" and statement.exact_text for statement in source.statements)


@pytest.mark.parametrize("provider", BUILTIN_PROVIDER_IDS)
def test_native_material_identity_matches_committed_provenance_and_bytes(provider: str):
    descriptor = _descriptor(provider)
    provenance, _, _ = _inputs(provider)
    native = provenance.header.native_table
    assert all(item["contentUrl"] != "native.parquet" for item in descriptor["distribution"])
    assert "private://" not in json.dumps(descriptor)
    if native is None:
        assert "isBasedOn" not in descriptor
        return
    material = descriptor["isBasedOn"]
    assert material["sha256"] == native.sha256 == sha256((_path(provider) / "native.parquet").read_bytes()).hexdigest()
    assert (
        material["contentSize"] == f"{native.byte_size} B" == f"{(_path(provider) / 'native.parquet').stat().st_size} B"
    )
    assert (
        material["contentUrl"]
        == f"https://github.com/RivRetrieve/RivRetrieve/blob/{native.revision}/{native.repository_path}"
    )


def test_reference_loader_extracts_actual_columns_from_all_four_record_sets(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _deny_network)
    dataset = mlc.Dataset(_path("usgs_nwis") / "croissant.json")
    provider = next(iter(dataset.records("provider")))
    expected_provider = json.loads((_path("usgs_nwis") / "provider.json").read_text())
    assert {
        key.partition("/")[2]: value.decode() if isinstance(value, bytes) else value for key, value in provider.items()
    } == expected_provider
    for name in ("products", "stations", "station_products"):
        row = next(iter(dataset.records(name)))
        expected = pl.read_parquet(_path("usgs_nwis") / f"{name}.parquet").head(1)
        actual = pl.DataFrame(
            [
                {
                    key.partition("/")[2]: value.decode()
                    if isinstance(value, bytes)
                    else value.date()
                    if hasattr(value, "date")
                    else value
                    for key, value in row.items()
                }
            ]
        ).cast(expected.schema)
        pl_testing.assert_frame_equal(actual, expected)


def test_generator_rejects_mixed_withheld_and_established_origins():
    from rivretrieve._internal.catalogue_origins import Documented, DocumentedValue, Evidence

    provenance, origins, files = _inputs("pl_imgw")
    second = {**origins[0], "crs": Documented(DocumentedValue("EPSG:4326"), Evidence("https://example.org/evidence"))}
    with pytest.raises(FatalContractError, match="mixes established and withheld"):
        build_catalogue_descriptor(provenance, (*origins, second), files)


def test_thailand_governing_acquisitions_leave_no_withheld_relation_absence():
    record = next(record for record in _descriptor("th_thaiwater")["recordSet"] if record["@id"] == "station_products")
    assert "rr:absence" not in record


def test_bosnia_record_sets_have_no_withheld_baseline_rows():
    descriptor = _descriptor("ba_fhmzbih")
    for record in descriptor["recordSet"]:
        if record["@id"] in {"stations", "station_products"}:
            assert "rr:absence" not in record


@pytest.mark.parametrize("provider", BUILTIN_PROVIDER_IDS)
def test_descriptor_preserves_exact_bounded_contents(provider: str):
    evidence, origins, files = _inputs(provider)
    descriptor = build_catalogue_descriptor(evidence, origins, files)
    assert descriptor == _descriptor(provider)
    serialized = json.dumps(descriptor)
    assert len(serialized.encode()) <= 262_144
    assert "lineage/" not in serialized and "acquisition/" not in serialized


def test_france_admitted_baseline_record_sets_have_no_missing_acquisition_absence():
    descriptor = _descriptor("fr_hubeau")
    for record in descriptor["recordSet"]:
        if record["@id"] in {"stations", "station_products"}:
            assert "rr:absence" not in record


@pytest.mark.parametrize("provider", ("br_ana", "pl_imgw", "fr_hubeau", "ba_fhmzbih", "th_thaiwater"))
def test_reference_loader_extracts_all_five_evidence_relations(provider, monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _deny_network)
    dataset = mlc.Dataset(_path(provider) / "croissant.json")
    for relation, schema in EVIDENCE_SCHEMAS.items():

        def decode(value):
            if isinstance(value, bytes):
                return value.decode()
            if hasattr(value, "tolist"):
                return [decode(item) for item in value.tolist()]
            if isinstance(value, list):
                return [decode(item) for item in value]
            return value

        rows = [
            {key.partition("/")[2]: decode(value) for key, value in row.items()}
            for row in dataset.records(f"provenance_{relation}")
        ]
        actual = pl.DataFrame(rows, schema=schema)
        expected = pl.read_parquet(_path(provider) / EVIDENCE_FILENAMES[relation])
        pl_testing.assert_frame_equal(actual, expected)


def test_descriptor_rejects_unexpected_file_authority():
    evidence, origins, files = _inputs("pl_imgw")
    for name in ("native.parquet", "../private.parquet", "https://example.org/input"):
        with pytest.raises(FatalContractError, match="exactly the public"):
            build_catalogue_descriptor(evidence, origins, {**files, name: b"unexpected"})


def test_evidence_recordsets_declare_exact_keys_and_physical_foreign_keys():
    evidence, origins, files = _inputs("pl_imgw")
    descriptor = build_catalogue_descriptor(evidence, origins, files)
    records = {record["@id"]: record for record in _record_sets(descriptor["recordSet"])}
    targets = {"fact_id": "facts", "binding_id": "bindings", "acquisition_key": "acquisitions"}
    keys = {
        "facts": ("fact_id",),
        "acquisitions": ("acquisition_key",),
        "bindings": ("binding_id",),
        "binding_facts": ("binding_id", "position"),
        "external_inputs": ("binding_id", "position"),
    }
    for relation, schema in EVIDENCE_SCHEMAS.items():
        record = records[f"provenance_{relation}"]
        assert record["key"] == [{"@id": f"provenance_{relation}/{column}"} for column in keys[relation]]
        assert [field["@id"].partition("/")[2] for field in record["field"]] == list(schema)
        for field in record["field"]:
            column = field["@id"].partition("/")[2]
            if column in targets and targets[column] != relation:
                assert field["references"] == {
                    "fileObject": {"@id": EVIDENCE_FILENAMES[targets[column]]},
                    "extract": {"column": column},
                }
            if isinstance(schema[column], pl.List):
                assert field["isArray"] is True and field["arrayShape"] == "-1"


def test_descriptor_rejects_header_and_relation_byte_disagreement():
    evidence, origins, files = _inputs("pl_imgw")
    filename = EVIDENCE_FILENAMES["facts"]
    with pytest.raises(FatalContractError, match="evidence file identity"):
        build_catalogue_descriptor(evidence, origins, {**files, filename: files[filename] + b"changed"})
    header = json.loads(files["provenance.json"])
    header["provider_id"] = "other"
    with pytest.raises(FatalContractError, match="evidence header"):
        build_catalogue_descriptor(evidence, origins, {**files, "provenance.json": json.dumps(header).encode()})


@pytest.mark.parametrize("provider", tuple(BUILTIN_PROVIDER_IDS))
def test_record_keys_expand_to_croissant_vocabulary(provider: str):
    evidence, origins, files = _inputs(provider)
    descriptor = build_catalogue_descriptor(evidence, origins, files)
    graph = Graph().parse(data=json.dumps(descriptor), format="json-ld", publicID=BASE)
    croissant = Namespace("http://mlcommons.org/croissant/")
    assert not list(graph.triples((None, SC.key, None)))
    for record in _record_sets(descriptor["recordSet"]):
        if "key" in record:
            assert list(graph.objects(URIRef(BASE + record["@id"]), croissant.key))
