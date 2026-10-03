"""Wheel installation : BuiltWheel → ReadableBuiltInCatalogues."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from tests._distribution import InstalledDistribution
from tests._provenance import historical_recording_locations, historical_source_provenance

_CANONICAL_CATALOGUE_FILES = {
    "format.json",
    "source_series.json",
    "series_claims.parquet",
    "croissant.json",
    "provenance_facts.parquet",
    "provenance_acquisitions.parquet",
    "provenance_bindings.parquet",
    "provenance_binding_facts.parquet",
    "provenance_external_inputs.parquet",
    "products.parquet",
    "provider.json",
    "station_products.parquet",
    "station_metadata.parquet",
    "stations.parquet",
}

_PROVENANCE_PROVIDER_IDS = {
    "ba_fhmzbih",
    "br_ana",
    "ca_eccc",
    "ch_foen",
    "cz_chmi",
    "fr_hubeau",
    "fr_hydroportail",
    "jp_mlit",
    "lt_lhmt",
    "no_nve",
    "pl_imgw",
    "th_thaiwater",
    "usgs_nwis",
    "za_dws",
}


def test_wheel_carries_every_manifest_catalogue(direct_distribution: InstalledDistribution) -> None:
    repository = Path(__file__).parents[1]

    expected_descriptor = json.loads(
        (repository / "src/rivretrieve/_internal/providers/usgs_nwis/catalogue/croissant.json").read_text()
    )
    verification = f"""
import json
import os
import socket
import sys
from pathlib import Path

def forbid_network(*args, **kwargs):
    raise AssertionError("Network access during installed-wheel discovery")

socket.socket.connect = forbid_network
socket.socket.connect_ex = forbid_network
socket.create_connection = forbid_network

from importlib.resources import files

import rivretrieve
import polars as pl
from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact

def artifact(provider):
    return load_packaged_catalogue_artifact(Path(str(provider_root.joinpath(provider, "catalogue"))), on_issue="raise")

before_describe = set(sys.modules)
assert rivretrieve.describe("usgs_nwis") == json.loads({json.dumps(expected_descriptor)!r})
assert not {{name.split(".")[0] for name in set(sys.modules) - before_describe}} - sys.stdlib_module_names - {{"rivretrieve"}}
assert "mlcroissant" not in sys.modules
provider_frame = rivretrieve.providers()
assert provider_frame.columns == ["provider_id", "credentials", "access"]
provider_ids = tuple(provider_frame["provider_id"])
assert provider_ids == BUILTIN_PROVIDER_IDS
provider_root = files("rivretrieve._internal.providers")
for provider_id in provider_ids:
    catalogue = provider_root.joinpath(provider_id, "catalogue")
    packaged_names = {{item.name for item in catalogue.iterdir()}}
    assert {_CANONICAL_CATALOGUE_FILES!r} <= packaged_names, (provider_id, packaged_names)
    if provider_id in {_PROVENANCE_PROVIDER_IDS!r}:
        assert "provenance.json" in packaged_names
    assert "native.parquet" not in packaged_names
    assert rivretrieve.describe(provider_id) == json.loads(catalogue.joinpath("croissant.json").read_text())
    assert not any(name.endswith((".eml", ".xlsx")) for name in packaged_names)

france = rivretrieve.find(provider="fr_hubeau")
# Native inventory snapshots acquired 2026-09-21, not enduring national totals.
assert len(france.series) == 20_297
assert {{series.product_id for series in france.series}} == {{"discharge_daily_mean", "discharge_daily_max", "stage_daily_max", "water_temperature_reported"}}
assert not france.acquisition_provenance[0].header.withheld_facts
hydroportail = rivretrieve.find(provider="fr_hydroportail")
assert len(hydroportail.series) == 12_818 * 4
assert {{series.variant for series in hydroportail.series}} == {{"raw", "validated", "pre_validated_and_validated", "most_valid"}}
assert {{series.product_id for series in hydroportail.series}} == {{"discharge_instantaneous", "stage_instantaneous"}}
assert {{series.provider_id for series in hydroportail.series}} == {{"fr_hydroportail"}}
bosnia = rivretrieve.find(provider="ba_fhmzbih")
assert len(bosnia.series) == 180
assert len({{series.station_id for series in bosnia.series}}) == 60
bosnia_pairs = artifact("ba_fhmzbih").station_products
assert bosnia_pairs["availability"].eq("available").sum() == 132
assert bosnia_pairs["availability"].eq("unknown").sum() == 48
assert bosnia.acquisition_provenance[0].header.withheld_facts == ()
unknown_bosnia = rivretrieve.find(provider="ba_fhmzbih", station="2101-B", quantity="temperature")
assert len(unknown_bosnia.series) == 1
assert bosnia_pairs.filter((pl.col("station_id") == "2101-B") & (pl.col("product_id") == "water_temperature_reported"))["availability"].to_list() == ["unknown"]
assert not provider_root.joinpath("ba_fhmzbih", "catalogue", "baseline_workbook_access.json").is_file()
norway = rivretrieve.find(
    provider="no_nve", station="1.200.0", quantity="stage", frequency="daily", statistic="mean"
)
assert len(norway.series) == 1
assert artifact("no_nve").station_products.filter((pl.col("station_id") == "1.200.0") & (pl.col("product_id") == "stage_daily_mean"))["availability"].to_list() == ["available"]
assert rivretrieve.series(norway)["admission"].to_list() == ["supported"]
assert norway.acquisition_provenance[0].header.native_table is not None
thailand = rivretrieve.find(
    provider="th_thaiwater", station="1", quantity="stage"
)
assert rivretrieve.as_frame(thailand).height == 1
groups = thailand.acquisition_provenance[0].header.withheld_facts
assert groups == ()
"""
    verification += "\n" + inspect.getsource(historical_source_provenance)
    verification += "\n" + inspect.getsource(historical_recording_locations)
    verification += "\nclosure_oracles = " + repr(_CLOSURE_ORACLES) + "\n" + _PROFILE_VERIFICATION
    direct_distribution.verify(verification)


# Original v2 inputs: git 6f0edf6. Full selected semantic closures (excluding JSON-LD
# context only) are pinned, not recomputed from the wheel under test. Original byte
# digests identify the pre-migration oracle; independent RDF assertions pin ancestry.
_CLOSURE_ORACLES = {
    "fr_hubeau": {
        "original_sha256": "172427cd2a859594a3da9c2f81d078aa456bcb9c48559207bdaa971ac35b61f0",
        "cases": [],
        # Preserved against immutable pre-split evidence below, not new identities.
        "historical_cases": [
            {
                "names": ["station_product:01001336:water_temperature_reported.availability"],
                "pair": {
                    "provider_id": "fr_hubeau",
                    "station_id": "01001336",
                    "product_id": "water_temperature_reported",
                    "availability": "available",
                    "availability_reason": "Publisher observation count is positive for the recorded query; numerical values and continuity are not implied",
                },
                "sha256": "1fe8669ec23331bc70b59b7f5c7fd85548934160051a49a74580eec183ff0292",
            },
            {
                "names": ["station_product:1011000201:discharge_instantaneous.availability"],
                "pair": {
                    "provider_id": "fr_hubeau",
                    "station_id": "1011000201",
                    "product_id": "discharge_instantaneous",
                    "availability": "unknown",
                    "availability_reason": "Recent publisher count was zero; historical availability was not checked",
                },
                "sha256": "bafd0641acea7d58724927ed98b2e1d60d5bf7e626160c73e119442e927f0a36",
            },
        ],
        "terms": {
            "license": "La réutilisation des Jeux de données est régie par la licence ouverte Etalab, https://www.etalab.gouv.fr/licence-ouverte-open-licence. Les Jeux de données sont donc librement et gratuitement utilisables et réutilisables, y compris dans un but commercial.",
            "citation": "L'utilisateur de ces données doit néanmoins veiller à citer l'auteur des Jeux de données.",
        },
        "descriptor_terms": {
            "license": "La réutilisation des Jeux de données est régie par la licence ouverte Etalab, https://www.etalab.gouv.fr/licence-ouverte-open-licence. Les Jeux de données sont donc librement et gratuitement utilisables et réutilisables, y compris dans un but commercial.",
            "citation": "L'utilisateur de ces données doit néanmoins veiller à citer l'auteur des Jeux de données.",
        },
    },
    "fr_hydroportail": {"cases": [], "terms": {}, "descriptor_terms": {}},
    "ba_fhmzbih": {
        "original_sha256": "55984ba0622e71eea47074dfbaae0fbb31b5cc077b513a8b1f7f946ce3069307",
        "cases": [
            {
                "names": ["station_product:1010:discharge_reported.availability"],
                "pair": {
                    "provider_id": "ba_fhmzbih",
                    "station_id": "1010",
                    "product_id": "discharge_reported",
                    "availability": "available",
                    "availability_reason": "Workbook contained 17212 numerical measurement rows at 2026-09-13T17:57:40.072312+00:00",
                },
                "sha256": "eb62e17e13bd1e11ba66d890c45600ced089bd4ff276ad36c42d777de9abf24b",
            },
            {
                "names": ["station_product:1010:water_temperature_reported.availability"],
                "pair": {
                    "provider_id": "ba_fhmzbih",
                    "station_id": "1010",
                    "product_id": "water_temperature_reported",
                    "availability": "unknown",
                    "availability_reason": "Valid station/parameter/unit-matched workbook contained zero data rows at 2026-09-09T15:53:11.518156+00:00; availability remains unknown",
                },
                "sha256": "87b97d231d0c1954ed7da1c962af56b92ac07b6bc280f93916f6ea32b7d00b74",
            },
        ],
        "terms": {},
        "descriptor_terms": {},
    },
    "th_thaiwater": {
        "original_sha256": "5ca8990c76da7f6445a4b3339c72af5e5493cfe89d4d529173908d1f76dce43a",
        "cases": [
            {
                "names": ["source.station_product:1:stage_reported.availability"],
                "pair": {
                    "provider_id": "th_thaiwater",
                    "station_id": "1",
                    "product_id": "stage_reported",
                    "availability": "available",
                    "availability_reason": "ThaiWater graph new_20260913_1_2026-06-08_2026-09-06_a1: 13069 non-null value measurements; tested 2026-06-08 through 2026-09-06 inclusive",
                },
                "sha256": "c7047ce3de18cde4953fad2e4e8abce4a79c9492a8c89d45556cf7b05d5bb30a",
            },
            {
                "names": ["source.station_product:1:discharge_reported.availability"],
                "pair": {
                    "provider_id": "th_thaiwater",
                    "station_id": "1",
                    "product_id": "discharge_reported",
                    "availability": "unknown",
                    "availability_reason": "ThaiWater graph new_20260913_1_2026-06-08_2026-09-06_a1: null-only discharge; availability outside the tested window is unknown; tested 2026-06-08 through 2026-09-06 inclusive",
                },
                "sha256": "b9efdebae04ac5b1721780bb4a69ed97f22d921edda4d4870f3ecad2e46a94ea",
            },
        ],
        "terms": {},
        "descriptor_terms": {},
    },
    "pl_imgw": {
        "original_sha256": "f2c130e1e32817877ddc3eba1566aa4a7e7d322cb1f4a2101208f62a98146a5a",
        "cases": [
            {
                "names": ["station.latitude", "station.station_id"],
                "pair": None,
                "sha256": "8415c2bee647d45d6acbc037bed4b2b890c6576c862c84527944c5efb6f856de",
            }
        ],
        "terms": {},
        "descriptor_terms": {},
    },
    "br_ana": {
        "original_sha256": "aefb34d6582bc53b6463f3cec882b6395ee96aa99fcf118f41f862f9af07173e",
        # Retain the historical oracle verbatim; it does not describe the newly
        # acquired adopted products. Current material assertions are separate below.
        "historical_cases": [
            {
                "names": ["product.product_id"],
                "pair": None,
                "sha256": "2fb41fd37c8c1e2223d1f95831974e36ec1215bd1f6a94e4aec02c37ae7d2216",
            }
        ],
        "cases": [],
        "terms": {
            "license": "Os dados abertos são disponibilizados livremente para a utilização de toda a sociedade, sem restrição de licenças, patentes ou mecanismos de controle."
        },
        "descriptor_terms": {
            "license": "Os dados abertos são disponibilizados livremente para a utilização de toda a sociedade, sem restrição de licenças, patentes ou mecanismos de controle."
        },
    },
}

_PROFILE_VERIFICATION = r"""
import hashlib
import polars as pl
import polars.testing as plt
import mlcroissant as mlc
from rdflib import Graph, Literal, Namespace
from rivretrieve._internal.catalogues.evidence import EVIDENCE_FILENAMES, EVIDENCE_SCHEMAS, EvidenceHeader
from rivretrieve._internal.catalogues.evidence_encoding import parse_catalogue_evidence
from rivretrieve._internal.catalogues.evidence_graph import CanonicalPair, FactSelection, resolve_evidence
from rivretrieve._internal.catalogues.terms import verified_catalogue_terms

assert "PYTHONPATH" not in os.environ
assert Path(rivretrieve.__file__).is_relative_to(Path(sys.prefix))
SC = Namespace("https://schema.org/")
CR = Namespace("http://mlcommons.org/croissant/")
BASE = "https://example.org/catalogue/"
keys = {"facts": ("fact_id",), "acquisitions": ("acquisition_key",), "bindings": ("binding_id",),
        "binding_facts": ("binding_id", "position"), "external_inputs": ("binding_id", "position")}
targets = {"fact_id": "facts", "binding_id": "bindings", "acquisition_key": "acquisitions"}
def decode(value):
    if isinstance(value, bytes):
        return value.decode()
    if hasattr(value, "tolist"):
        return [decode(item) for item in value.tolist()]
    if isinstance(value, list):
        return [decode(item) for item in value]
    return value

def historical_closure_evidence(provider, evidence):
    # Project only verified additions out of the historical closure oracle. The
    # installed current relations above and current RDF ancestry below stay intact.
    from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance
    from rivretrieve._internal.catalogues.evidence import normalize_provenance
    from rivretrieve._internal.catalogues.evidence_encoding import reconstruct_provenance

    catalogue = artifact(provider)
    projected = historical_source_provenance(
        reconstruct_provenance(evidence),
        pl.read_parquet(provider_root.joinpath(provider, "catalogue", "station_metadata.parquet")),
    )
    if provider not in {"ba_fhmzbih", "pl_imgw"}:
        return normalize_provenance(projected, stations=catalogue.stations, station_products=catalogue.station_products)
    model = projected.model_dump(mode="json")
    if provider == "ba_fhmzbih":
        (source,) = model["source_records"]
        assert source["source_id"] == "ba_avp_sava"
        added = [
            ("ba_fhmzbih_4024_Q_1Y", "e40e760cf99d4e23b62b8d5d95edc86af01ddca9aa6c55226d59c859e8801d05"),
            ("ba_fhmzbih_4024_H_1Y", "45b5663132a58f5bdcf3ee29c5cdd8c5f83389dabb80d3716b5e318b77ca79a0"),
            ("ba_fhmzbih_4110_Tvode_1Y", "e0532ec0a269acb735db6957a478652ac0fb7ece9194b688852478d6d186dbb3"),
            ("ba_fhmzbih_layer20_series", "afb0dbd8530f1b589028731a42611e933d6991ec35414bdaba071c7a3180dabf"),
        ]
        assert [(item["recording"]["recording_id"], item["recording"]["sha256"]) for item in source["evidence"][:4]] == added
        assert [(item["acquisition_id"], item["recording_ids"]) for item in source["acquisitions"][:2]] == [
            ("product_workbook_headers", [item[0] for item in added[:3]]),
            ("layer20_series_capture", [added[3][0]]),
        ]
        del source["evidence"][:4]
        del source["acquisitions"][:2]
        assert model["fact_bindings"].pop(0) == {
            "fact_group": "layer20_discharge_series",
            "facts": ["source.series.layer20_discharge_identity"],
            "source_id": "ba_avp_sava", "acquisition_id": "layer20_series_capture",
        }
        assert model["fact_universe"].pop(484) == "source.series.layer20_discharge_identity"
        binding = next(item for item in model["fact_bindings"] if item["fact_group"] == "canonical_products")
        assert binding["acquisition_id"] == "product_workbook_headers"
        binding["acquisition_id"] = "catalogue_capture_2026_08_02"
    else:
        source = next(item for item in model["source_records"] if item["source_id"] == "sr.pl.imgw")
        added = [
            ("pl_imgw_codz_format", "d8e7cbbc7680663d99813dd5f9abd793384b2f560600229625bb808ea71ef362"),
            ("pl_imgw_yearbook_2025", "c2ad75c472ab46363fb149ac5cf982230e2506d7e0b73b8e4eecb6623fa2a916"),
        ]
        assert [(item["recording"]["recording_id"], item["recording"]["sha256"]) for item in source["evidence"][:2]] == added
        acquisition = source["acquisitions"].pop(0)
        assert acquisition["acquisition_id"] == "imgw_archive_definitions_2026_09_20"
        assert acquisition["recording_ids"] == [item[0] for item in added]
        del source["evidence"][:2]
        binding = next(item for item in model["fact_bindings"] if item["fact_group"] == "imgw_archive_physics")
        assert binding == {
            "fact_group": "imgw_archive_physics", "facts": ["source.imgw.observation_archive_product_semantics"],
            "source_id": "sr.pl.imgw", "acquisition_id": "imgw_archive_definitions_2026_09_20",
        }
        model["fact_bindings"].remove(binding)
        roster = next(item for item in model["fact_bindings"] if item["fact_group"] == "imgw_catalogue_inputs")
        assert "source.imgw.observation_archive_product_semantics" not in roster["facts"]
        roster["facts"].insert(1, "source.imgw.observation_archive_product_semantics")
    return normalize_provenance(AcquisitionProvenance.model_validate(model), stations=catalogue.stations,
                                station_products=catalogue.station_products)

for provider, oracle in closure_oracles.items():
    catalogue = provider_root.joinpath(provider, "catalogue")
    descriptor = rivretrieve.describe(provider)
    distribution = {item["contentUrl"]: item for item in descriptor["distribution"]}
    header_bytes = catalogue.joinpath("provenance.json").read_bytes()
    header = EvidenceHeader.model_validate_json(header_bytes)
    assert set(header.files) == set(EVIDENCE_FILENAMES.values())
    bodies = {name: catalogue.joinpath(name).read_bytes() for name in header.files}
    for name, body in {"provenance.json": header_bytes, **bodies}.items():
        assert distribution[name]["sha256"] == hashlib.sha256(body).hexdigest()
        assert distribution[name]["contentSize"] == f"{len(body)} B"
    evidence = parse_catalogue_evidence(header, bodies)
    dataset = mlc.Dataset(Path(str(catalogue.joinpath("croissant.json"))))
    graph = Graph().parse(data=json.dumps(descriptor), format="json-ld", publicID=BASE)
    assert list(graph.triples((None, CR.key, None)))
    assert not list(graph.triples((None, SC.key, None)))
    records = {record["@id"]: record for record in descriptor["recordSet"]}
    extracted = {}
    for relation, schema in EVIDENCE_SCHEMAS.items():
        record = records[f"provenance_{relation}"]
        assert record["key"] == [{"@id": f"provenance_{relation}/{column}"} for column in keys[relation]]
        assert [field["@id"].partition("/")[2] for field in record["field"]] == list(schema)
        rows = [{key.partition("/")[2]: decode(value) for key, value in row.items()}
                for row in dataset.records(f"provenance_{relation}")]
        actual = pl.DataFrame(rows, schema=schema)
        expected = pl.read_parquet(catalogue.joinpath(EVIDENCE_FILENAMES[relation]))
        assert expected.schema == schema
        plt.assert_frame_equal(actual, expected)
        assert actual.select(keys[relation]).unique().height == actual.height
        assert header.files[EVIDENCE_FILENAMES[relation]].row_count == actual.height
        extracted[relation] = actual
        for field in record["field"]:
            column = field["@id"].partition("/")[2]
            if column in targets and targets[column] != relation:
                assert field["references"] == {"fileObject": {"@id": EVIDENCE_FILENAMES[targets[column]]},
                                               "extract": {"column": column}}
            if isinstance(schema[column], pl.List):
                assert field["isArray"] is True and field["arrayShape"] == "-1"
    for relation, frame in extracted.items():
        for column, target in targets.items():
            if column in frame.columns and target != relation:
                assert set(frame[column].drop_nulls()) <= set(extracted[target][column])
        for column, values in (("source_ordinal", header.source_records), ("description_id", header.descriptions),
                               ("transformation_id", header.transformations)):
            if column in frame.columns:
                assert set(frame[column].drop_nulls()) <= set(range(len(values)))
    ownership = extracted["bindings"].filter(pl.col("acquisition_key").is_not_null()).join(
        extracted["acquisitions"].select("acquisition_key", "source_ordinal"), on="acquisition_key", suffix="_owner")
    assert ownership["source_ordinal"].equals(ownership["source_ordinal_owner"])
    for row in extracted["acquisitions"].iter_rows(named=True):
        source = header.source_records[row["source_ordinal"]]
        assert set(row["recording_ids"]) <= {entry.recording.recording_id for entry in source.evidence}

    for case in oracle["cases"]:
        pair = CanonicalPair(**case["pair"]) if case["pair"] is not None else None
        if pair is not None:
            physical_filters = {
                "water_temperature_reported": {"quantity": "temperature"},
                "discharge_instantaneous": {"quantity": "discharge"},
                "discharge_reported": {"quantity": "discharge"},
                "stage_reported": {"quantity": "stage"},
            }
            selection = rivretrieve.find(provider=provider, station=pair.station_id, **physical_filters[pair.product_id])
            # Broad physical scope can include sibling routes and unknown temporal facts.
            assert any(item.product_id == pair.product_id for item in selection.series)
            pairs = artifact(provider).station_products
            row = pairs.filter((pl.col("station_id") == pair.station_id) & (pl.col("product_id") == pair.product_id)).row(0, named=True)
            assert {key: row[key] for key in CanonicalPair.model_fields} == pair.model_dump()
        resolved = resolve_evidence(evidence, FactSelection(names=tuple(case["names"])), pair)
        projected = historical_closure_evidence(provider, evidence)
        historical = historical_recording_locations(
            resolve_evidence(projected, FactSelection(names=tuple(case["names"])), pair), projected)
        semantic = {key: value for key, value in historical.items() if key != "@context"}
        assert hashlib.sha256(json.dumps(semantic, sort_keys=True, ensure_ascii=False).encode()).hexdigest() == case["sha256"]
        if provider == "pl_imgw":
            graph = Graph().parse(data=json.dumps(resolved), format="json-ld", publicID=BASE)
            recovered = next(graph.subjects(SC.sha256, Literal("8c4cdd675c2811cd3b91a5889cbcd4273830c2fa4ee90ad6142c69ba7a198f49")))
            workbook = next(graph.subjects(SC.sha256, Literal("dfab6ea7de80fb1570f4a8dded8743ed7c7dcb4eb67fe75e2c0e02e9b964b7bf")))
            for name in case["names"]:
                field = next(graph.subjects(SC.identifier, Literal(name)))
                ancestors = set(graph.transitive_objects(field, SC.isBasedOn))
                assert recovered in ancestors and workbook not in ancestors
                assert list(graph.subjects(SC.citation, workbook))
                assert "not established as the historical acquisition" in str(next(graph.objects(workbook, SC.description)))
                if name == "station.station_id":
                    issuers = {str(name) for node in ancestors for creator in graph.objects(node, SC.creator)
                               for name in graph.objects(creator, SC.name)}
                    assert {"Global Runoff Data Centre", "Institute of Meteorology and Water Management – National Research Institute"} <= issuers
    assert verified_catalogue_terms(evidence) == oracle["terms"]
    assert {kind: descriptor[kind] for kind in ("license", "citation") if kind in descriptor} == oracle["descriptor_terms"]
    if provider == "fr_hydroportail":
        assert {source.source_id for source in header.source_records} == {"fr_hydroportail"}
        search = extracted["acquisitions"].filter(pl.col("acquisition_id") == "public_station_search")
        assert search.height == 1
        assert all(url.startswith("https://hydro.eaufrance.fr/") for url in search["requested_from"][0])
print("Installed socket-denied evidence proof: normalized relations; current service identities; historical closures and adopted products; keys/FKs/header; exact terms")

brazil_catalogue = provider_root.joinpath("br_ana", "catalogue")
brazil = parse_catalogue_evidence(EvidenceHeader.model_validate_json(brazil_catalogue.joinpath("provenance.json").read_bytes()),
    {filename: brazil_catalogue.joinpath(filename).read_bytes() for filename in EVIDENCE_FILENAMES.values()})
products = resolve_evidence(brazil, FactSelection(names=("product.product_id",)))
assert "89e2929cb436241b4aae2bbb04c4077edd55379886f39c9a32eb7fec0c8faba3" in json.dumps(products)
assert "withheld" not in json.dumps(products)
assert set(rivretrieve.products(provider="br_ana")) == {"discharge_daily_mean_bruto", "discharge_daily_mean_consistido", "discharge_instantaneous", "stage_daily_mean_bruto", "stage_daily_mean_consistido", "stage_instantaneous"}
"""


@pytest.mark.derived("tests/test_data/french_combined_artifacts.tar.xz")
def test_historical_french_closure_oracles_against_immutable_combined_evidence(retained_evidence_root: Path):
    import hashlib
    import tarfile
    from io import BytesIO
    from zipfile import ZipFile

    from rivretrieve._internal.catalogues.evidence import CatalogueEvidence
    from rivretrieve._internal.catalogues.evidence_graph import CanonicalPair, FactSelection, resolve_evidence

    archive_path = retained_evidence_root / "tests/test_data/french_combined_artifacts.tar.xz"
    with tarfile.open(archive_path) as archive:
        bundle = archive.extractfile("combined-station-selection.bundle").read()
        attestation = json.load(archive.extractfile("attestation.json"))
    assert hashlib.sha256(bundle).hexdigest() == attestation["files"]["combined-station-selection.bundle"]["sha256"]
    with ZipFile(BytesIO(bundle)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    evidence = CatalogueEvidence.model_validate_json(json.dumps(manifest["catalogue_evidence"][0]))
    for case in _CLOSURE_ORACLES["fr_hubeau"]["historical_cases"]:
        pair = CanonicalPair(**case["pair"])
        resolved = historical_recording_locations(
            resolve_evidence(evidence, FactSelection(names=tuple(case["names"])), pair), evidence
        )
        semantic = {key: value for key, value in resolved.items() if key != "@context"}
        assert (
            hashlib.sha256(json.dumps(semantic, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            == case["sha256"]
        )
