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
from rivretrieve._internal.catalogues.descriptor import ABSENCE_NAMESPACE, build_catalogue_descriptor
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
    provenance = AcquisitionProvenance.model_validate_json((directory / "provenance.json").read_bytes())
    if provider == "br_ana":
        origins = ()
    else:
        module = importlib.import_module(f"rivretrieve._internal.providers.{provider}.origins")
        origins = (
            (module.HYDROMETRY_STATION_CATALOGUE_ORIGINS, module.TEMPERATURE_STATION_CATALOGUE_ORIGINS)
            if provider == "fr_hubeau"
            else (module.STATION_CATALOGUE_ORIGINS,)
        )
    files = {name: (directory / name).read_bytes() for name in REQUIRED_ARTIFACT_FILES}
    return provenance, origins, files


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
    assert len(dataset.metadata.record_sets) == 4
    descriptor = _descriptor(provider)
    for distribution in descriptor["distribution"]:
        assert distribution["sha256"] == sha256((_path(provider) / distribution["contentUrl"]).read_bytes()).hexdigest()
    for record in descriptor["recordSet"]:
        for field in record["field"]:
            assert "source" in field
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
    graph = _graph("pl_imgw")
    for column in ("latitude", "station_id"):
        field = URIRef(BASE + "stations/" + column)
        lineage = next(graph.objects(field, SC.subjectOf))
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


@pytest.mark.parametrize(
    ("provider", "record_set", "count"),
    [
        ("fr_hubeau", "stations", 7320),
        ("fr_hubeau", "station_products", 33133),
        ("th_thaiwater", "station_products", 1648),
    ],
)
def test_record_set_absence_counts_exact_withheld_row_locators(provider: str, record_set: str, count: int):
    record = next(record for record in _descriptor(provider)["recordSet"] if record["@id"] == record_set)
    assert record["rr:absence"] == {
        "kind": "withheld",
        "reason": "no_acquisition_record_established",
        "rowCount": count,
    }


def test_reference_loader_reads_empty_tables_and_null_fields(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _deny_network)
    brazil = mlc.Dataset(_path("br_ana") / "croissant.json")
    for record in ("products", "stations", "station_products"):
        assert list(brazil.records(record)) == []
    provider = list(brazil.records("provider"))
    assert provider[0]["provider/catalogue_version"] is None
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


def test_brazil_preserves_terms_without_inventing_date_or_native_identity():
    descriptor = _descriptor("br_ana")
    provenance = AcquisitionProvenance.model_validate_json((_path("br_ana") / "provenance.json").read_bytes())
    assert descriptor["license"] == provenance.source_records[0].statements[0].exact_text
    assert not {"version", "datePublished", "isBasedOn"}.intersection(descriptor)
    assert all("rr:absence" in record for record in descriptor["recordSet"])
    assert all("rowCount" not in record["rr:absence"] for record in descriptor["recordSet"])


def test_generator_rejects_missing_origins_and_unattributed_canonical_column():
    provenance, origins, files = _inputs("pl_imgw")
    with pytest.raises(FatalContractError, match="requires station origins"):
        build_catalogue_descriptor(provenance, (), files)
    damaged = dict(origins[0])
    del damaged["latitude"]
    with pytest.raises(FatalContractError, match="Station column has no origin"):
        build_catalogue_descriptor(provenance, (damaged,), files)
    bindings = tuple(
        binding.model_copy(update={"facts": tuple(fact for fact in binding.facts if fact != "station.latitude")})
        for binding in provenance.fact_bindings
    )
    with pytest.raises(FatalContractError, match="Canonical column has no lineage or withheld fact"):
        build_catalogue_descriptor(provenance.model_copy(update={"fact_bindings": bindings}), origins, files)


def test_generator_rejects_missing_acquisition_and_native_byte_identity():
    provenance, origins, files = _inputs("pl_imgw")
    bindings = tuple(
        binding.model_copy(update={"acquisition_id": "does-not-exist"})
        if binding.source_id == "sr.pl.grdc"
        else binding
        for binding in provenance.fact_bindings
    )
    with pytest.raises(FatalContractError, match="not an established historical acquisition"):
        build_catalogue_descriptor(provenance.model_copy(update={"fact_bindings": bindings}), origins, files)
    assert provenance.native_table is not None
    with pytest.raises(FatalContractError, match="Native table byte size"):
        build_catalogue_descriptor(
            provenance.model_copy(
                update={"native_table": provenance.native_table.model_copy(update={"byte_size": None})}
            ),
            origins,
            files,
        )


def test_verbatim_source_terms_remain_separate_and_uninterpreted():
    descriptor = _descriptor("usgs_nwis")
    provenance, _, _ = _inputs("usgs_nwis")
    for kind in ("license", "citation"):
        assert descriptor[kind] == next(
            statement.exact_text for statement in provenance.source_records[0].statements if statement.kind == kind
        )
    for provider in ("ch_foen", "ca_eccc", "pl_imgw", "fr_hubeau", "th_thaiwater"):
        assert "license" not in _descriptor(provider) and "citation" not in _descriptor(provider)
    bosnia = _descriptor("ba_fhmzbih")
    provenance, _, _ = _inputs("ba_fhmzbih")
    source = next(node for node in bosnia["subjectOf"] if node["@id"].startswith("issuer/"))
    assert source["usageInfo"][0]["text"] == next(
        statement.exact_text for statement in provenance.source_records[0].statements if statement.kind == "terms"
    )
    assert "license" not in source


@pytest.mark.parametrize("provider", BUILTIN_PROVIDER_IDS)
def test_native_material_identity_matches_committed_provenance_and_bytes(provider: str):
    descriptor = _descriptor(provider)
    provenance = AcquisitionProvenance.model_validate_json((_path(provider) / "provenance.json").read_bytes())
    native = provenance.native_table
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


def test_bosnia_record_sets_have_no_withheld_baseline_rows():
    descriptor = _descriptor("ba_fhmzbih")
    for record in descriptor["recordSet"]:
        if record["@id"] in {"stations", "station_products"}:
            assert "rr:absence" not in record


@pytest.mark.parametrize("provider", BUILTIN_PROVIDER_IDS)
def test_descriptor_preserves_exact_contents_without_binding_position_scans(provider: str):
    import sys

    provenance, origins, files = _inputs(provider)
    position_scans = 0

    def count_position_scans(frame, event, arg):
        nonlocal position_scans
        if (
            event == "c_call"
            and getattr(arg, "__name__", None) == "index"
            and getattr(arg, "__self__", None) is provenance.fact_bindings
        ):
            position_scans += 1

    previous_profile = sys.getprofile()
    sys.setprofile(count_position_scans)
    try:
        descriptor = build_catalogue_descriptor(provenance, origins, files)
    finally:
        sys.setprofile(previous_profile)

    assert descriptor == _descriptor(provider)
    assert position_scans == 0, f"descriptor scanned binding positions {position_scans} times"
