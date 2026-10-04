"""Synthetic Hub’Eau original-input and scoped projection contracts."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.acquisition_provenance import (
    ArchiveMemberReference,
    RetainedInputReceipt,
    RetainedInputReference,
    RetainedInputUse,
)
from rivretrieve._internal.catalogues.native import RetrievedAt, stamp_native_table
from rivretrieve._internal.catalogues.station_metadata import MetadataField
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.fr_hubeau.station_metadata import (
    HYDROMETRY_SCOPE,
    SITE_ENDPOINT,
    SITE_FACT,
    SITE_SCOPE,
    TEMPERATURE_SCOPE,
    parse_site_response,
    project_station_metadata,
    read_station_metadata_sources,
    verify_adopted_station_metadata,
)


def site(**changes):
    return {
        "code_site": "001",
        "libelle_site": "Site",
        "altitude_site": 0.0,
        "code_systeme_alti_site": 0,
        "surface_bv": None,
        "libelle_cours_eau": "",
        "code_cours_eau": None,
        "uri_cours_eau": None,
        "date_maj_site": None,
        **changes,
    }


def response(rows=None, **changes):
    rows = [site()] if rows is None else rows
    return json.dumps({"count": len(rows), "next": None, "data": rows, **changes}).encode()


def test_parser_preserves_zero_blank_null_and_unknown_datum():
    actual = parse_site_response(
        response([site(), site(code_site="002", code_systeme_alti_site=999)]), ("001", "002", "003")
    )
    expected = pl.DataFrame(
        [site(), site(code_site="002", code_systeme_alti_site=999)],
        schema={
            "code_site": pl.String,
            "libelle_site": pl.String,
            "altitude_site": pl.Float64,
            "code_systeme_alti_site": pl.Int64,
            "surface_bv": pl.Float64,
            "libelle_cours_eau": pl.String,
            "code_cours_eau": pl.String,
            "uri_cours_eau": pl.String,
            "date_maj_site": pl.String,
        },
    )
    assert_frame_equal(actual, expected)


@pytest.mark.parametrize(
    "body",
    [
        response(count=True),
        response(count=2),
        response(next="next-page"),
        response([site(), site()]),
        response([site(code_site="outside")]),
        response([site(altitude_site=True)]),
        response([site(altitude_site="0")]),
        response([site(altitude_site=float("nan"))]),
        response([site(surface_bv=False)]),
        response([site(code_systeme_alti_site=1.2)]),
        response([site(code_systeme_alti_site=True)]),
        response([site(code_systeme_alti_site=2**63)]),
        response([site(libelle_cours_eau=2)]),
        response([site(libelle_site=None)]),
        response([{key: value for key, value in site().items() if key != "altitude_site"}]),
        b'{"count":1,"count":1,"next":null,"data":[]}',
        b"\xff",
    ],
)
def test_parser_rejects_malformed_or_incomplete_original(body):
    with pytest.raises(FatalContractError):
        parse_site_response(body, ("001",))


@pytest.fixture
def source_inputs(tmp_path):
    body = response()
    document = {
        "id": "batch-001",
        "url": SITE_ENDPOINT + "?code_site=001,002&size=50&page=1",
        "allowed_origins": ["https://hubeau.eaufrance.fr"],
        "purpose": "Synthetic",
        "expected_site_codes": ["001", "002"],
        "requested_page": 1,
        "requested_size": 50,
    }
    receipt = {
        "document": document,
        "fresh_acquisition": True,
        "stopped": "terminal_response",
        "hops": [
            {
                "hop": 0,
                "status": 200,
                "requested_url": document["url"],
                "executed_url": document["url"],
                "headers": {"Content-Type": "application/json"},
                "body_received_at": "2026-01-01T00:00:00Z",
                "body_file": "hop-0.body",
                "byte_size": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        ],
    }
    bodies = {
        "sites/batch-001/body": body,
        "sites/batch-001/receipt.json": json.dumps(receipt).encode(),
    }
    lineage = {
        "kind": "verified_input_view_not_new_acquisition",
        "acquisition_roots": ["synthetic"],
        "files": [
            {
                "document_id": "batch-001",
                "campaign": "synthetic",
                "original": "/restricted/original",
                "composed": path.removeprefix("sites/"),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "byte_size": len(raw),
            }
            for path, raw in bodies.items()
        ],
    }
    bodies.update(
        {"sites/documents.json": json.dumps([document]).encode(), "sites/lineage.json": json.dumps(lineage).encode()}
    )
    references = []
    for path, raw in bodies.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        references.append(
            RetainedInputReference(
                consumer_path=path,
                archive_repository="https://github.com/RivRetrieve/verification-evidence",
                archive_revision="a" * 40,
                collection_id="synthetic-hubeau",
                manifest_sha256="b" * 64,
                artifact_id=path.replace("/", "-"),
                sha256=hashlib.sha256(raw).hexdigest(),
                byte_size=len(raw),
                role="publisher_original",
            )
        )
    return tmp_path, {
        "input_receipt": RetainedInputReceipt(
            schema_version=3,
            archive_code_revision="c" * 40,
            code_revision="d" * 40,
            declaration_revision="d" * 40,
            inputs=tuple(references),
        ),
        "site_root": "sites",
        "manifest_sha256": hashlib.sha256(bodies["sites/documents.json"]).hexdigest(),
        "lineage_sha256": hashlib.sha256(bodies["sites/lineage.json"]).hexdigest(),
    }


def adopted(arguments):
    return tuple(
        RetainedInputUse(
            reference=ArchiveMemberReference.model_validate(item.model_dump(exclude={"consumer_path"})),
            usage="original",
            facts=(f"{SITE_FACT}.batch-001",),
        )
        for item in arguments["input_receipt"].inputs
    )


def test_reader_and_publication_check_exact_original_cohort(source_inputs):
    root, arguments = source_inputs
    sources = read_station_metadata_sources(root, **arguments)
    assert sources.site_bodies["batch-001"] == response()
    assert sources.site_recordings[0].source_url == SITE_ENDPOINT
    assert sources.site_recordings[0].retrieved_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert sources.expected_site_codes["batch-001"] == ("001", "002")
    verify_adopted_station_metadata(sources, adopted(arguments))
    with pytest.raises(FatalContractError, match="adopted archive members"):
        verify_adopted_station_metadata(sources, adopted(arguments)[:-1])
    changed = replace(sources, site_bodies={"batch-001": response([site(altitude_site=123.0)])})
    with pytest.raises(FatalContractError, match="validated identity"):
        verify_adopted_station_metadata(changed, adopted(arguments))
    with pytest.raises(TypeError):
        sources.site_bodies["batch-001"] = b"changed"


@pytest.mark.parametrize("update_receipt", [False, True])
def test_changed_body_and_self_consistent_receipt_cannot_replace_selected_identity(source_inputs, update_receipt):
    root, arguments = source_inputs
    read_station_metadata_sources(root, **arguments)
    body = response([site(altitude_site=123.0)])
    (root / "sites/batch-001/body").write_bytes(body)
    if update_receipt:
        path = root / "sites/batch-001/receipt.json"
        receipt = json.loads(path.read_bytes())
        receipt["hops"][0].update(sha256=hashlib.sha256(body).hexdigest(), byte_size=len(body))
        path.write_text(json.dumps(receipt))
    with pytest.raises(FatalContractError, match="resolved archive identity"):
        read_station_metadata_sources(root, **arguments)


def test_reader_requires_independent_member_selection_before_parsing(source_inputs):
    root, arguments = source_inputs
    arguments["input_receipt"] = arguments["input_receipt"].model_copy(update={"inputs": ()})
    (root / "sites/documents.json").write_bytes(b"not json")
    with pytest.raises(FatalContractError, match="absent from selected"):
        read_station_metadata_sources(root, **arguments)


FIELDS = (
    MetadataField("station_name", "libelle_station", source_scope=HYDROMETRY_SCOPE),
    MetadataField("water_body_name", "libelle_cours_eau", source_scope=HYDROMETRY_SCOPE),
    MetadataField(
        "elevation",
        "altitude_ref_alti_station",
        "m",
        datum_field="code_systeme_alti_site",
        datum_support=("source.datum",),
        source_scope=HYDROMETRY_SCOPE,
    ),
    MetadataField("station_name", "libelle_station", source_scope=TEMPERATURE_SCOPE),
    MetadataField("water_body_name", "libelle_masse_eau", source_scope=TEMPERATURE_SCOPE),
    MetadataField("elevation", "altitude", source_scope=TEMPERATURE_SCOPE),
    MetadataField("water_body_name", "libelle_cours_eau", source_scope=SITE_SCOPE),
    MetadataField(
        "elevation",
        "altitude_site",
        datum_field="code_systeme_alti_site",
        datum_support=("source.datum",),
        source_scope=SITE_SCOPE,
    ),
    MetadataField("drainage_area", "surface_bv", "km²", source_scope=SITE_SCOPE),
)


def native_table():
    return stamp_native_table(
        pl.DataFrame(
            {
                "code_station": ["0001", "0002", "0003"],
                "code_site": ["001", "002", "001"],
                "source_endpoint": [HYDROMETRY_SCOPE, HYDROMETRY_SCOPE, TEMPERATURE_SCOPE],
                "libelle_station": ["Gauge", "Other", "Temperature"],
                "libelle_cours_eau": ["River", None, None],
                "libelle_masse_eau": [None, None, "  "],
                "altitude_ref_alti_station": [12.0, None, None],
                "code_systeme_alti_site": [777, None, None],
                "altitude": [None, None, 0.0],
            }
        ),
        RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC)),
    )


def test_projection_keeps_partition_exposure_same_named_fields_and_same_site_datum(source_inputs):
    root, arguments = source_inputs
    sources = read_station_metadata_sources(root, **arguments)
    stations = pl.DataFrame(
        {"station_id": ["0001", "0002", "0003"], "latitude": [1.0, None, 2.0], "longitude": [3.0, None, 4.0]}
    )
    before = stations.clone()
    result = project_station_metadata(native_table(), stations, sources, FIELDS)
    water = result.filter((pl.col("station_id") == "0001") & (pl.col("attribute_role") == "water_body_name"))
    assert set(water.select("source_scope", "source_field", "source_value").iter_rows()) == {
        (HYDROMETRY_SCOPE, "libelle_cours_eau", '"River"'),
        (SITE_SCOPE, "libelle_cours_eau", '""'),
    }
    elevation = result.filter((pl.col("station_id") == "0001") & (pl.col("attribute_role") == "elevation"))
    assert set(
        elevation.select(
            "source_field", "source_value", "source_unit", "source_datum", "source_datum_dtype"
        ).iter_rows()
    ) == {
        ("altitude_ref_alti_station", "12.0", "m", "777", "Int64"),
        ("altitude_site", "0.0", None, "0", "Int64"),
    }
    assert result.filter((pl.col("station_id") == "0002") & (pl.col("source_scope") == SITE_SCOPE)).is_empty()
    assert result.filter((pl.col("station_id") == "0003") & (pl.col("source_scope") != TEMPERATURE_SCOPE)).is_empty()
    area = result.filter((pl.col("station_id") == "0001") & (pl.col("attribute_role") == "drainage_area"))
    assert area.select("state", "source_value", "source_dtype", "source_unit").row(0) == (
        "source_null",
        None,
        "Float64",
        "km²",
    )
    assert_frame_equal(stations, before)


def test_projection_rejects_unrequested_native_site_association(source_inputs):
    root, arguments = source_inputs
    sources = read_station_metadata_sources(root, **arguments)
    native = native_table()
    native.data[0, "code_site"] = "outside"
    with pytest.raises(FatalContractError, match="association"):
        project_station_metadata(native, pl.DataFrame({"station_id": ["0001"]}), sources, FIELDS)


def reselect(root, arguments):
    """Refresh synthetic independent identities to reach relation checks."""
    lineage_path = root / "sites/lineage.json"
    lineage = json.loads(lineage_path.read_bytes())
    for member in lineage["files"]:
        path = root / "sites" / member["document_id"] / member["composed"].split("/")[-1]
        raw = path.read_bytes()
        member.update(sha256=hashlib.sha256(raw).hexdigest(), byte_size=len(raw))
    lineage_path.write_text(json.dumps(lineage))
    arguments["input_receipt"] = arguments["input_receipt"].model_copy(
        update={
            "inputs": tuple(
                item.model_copy(
                    update={
                        "sha256": hashlib.sha256((root / item.consumer_path).read_bytes()).hexdigest(),
                        "byte_size": (root / item.consumer_path).stat().st_size,
                    }
                )
                for item in arguments["input_receipt"].inputs
            )
        }
    )
    arguments["manifest_sha256"] = hashlib.sha256((root / "sites/documents.json").read_bytes()).hexdigest()
    arguments["lineage_sha256"] = hashlib.sha256(lineage_path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "change",
    [
        {"executed_url": SITE_ENDPOINT},
        {"requested_url": SITE_ENDPOINT},
        {"status": 206},
        {"byte_size": 0},
        {"sha256": "a" * 64},
        {"body_file": "body"},
        {"body_received_at": "2026-01-01T00:00:00"},
        {"headers": {"Content-Type": "text/html"}},
    ],
)
def test_reader_checks_full_private_receipt_against_manifest_after_member_verification(source_inputs, change):
    root, arguments = source_inputs
    path = root / "sites/batch-001/receipt.json"
    receipt = json.loads(path.read_bytes())
    receipt["hops"][0].update(change)
    path.write_text(json.dumps(receipt))
    reselect(root, arguments)
    with pytest.raises(FatalContractError, match="acquisition identity") as error:
        read_station_metadata_sources(root, **arguments)
    assert "code_site=" not in str(error.value)
    assert str(root) not in str(error.value)


def test_reader_does_not_dereference_historical_lineage_paths(source_inputs):
    root, arguments = source_inputs
    path = root / "sites/lineage.json"
    lineage = json.loads(path.read_bytes())
    for member in lineage["files"]:
        member["composed"] = "historical/not-consumer/" + member["composed"].split("/")[-1]
    path.write_text(json.dumps(lineage))
    reselect(root, arguments)
    sources = read_station_metadata_sources(root, **arguments)
    assert sources.site_recordings[0].repository_path == "sites/batch-001/body"
    assert "/restricted/" not in repr(sources)


def test_projection_reparses_immutable_bodies_not_mutated_derived_frames(source_inputs):
    root, arguments = source_inputs
    sources = read_station_metadata_sources(root, **arguments)
    parsed = parse_site_response(sources.site_bodies["batch-001"], ("001", "002"))
    parsed[0, "altitude_site"] = 999.0
    projected = project_station_metadata(native_table(), pl.DataFrame({"station_id": ["0001"]}), sources, FIELDS)
    assert projected.filter(pl.col("source_field") == "altitude_site")["source_value"].item() == "0.0"


def test_native_null_datum_retains_association_dtype_and_no_borrow(source_inputs):
    root, arguments = source_inputs
    sources = read_station_metadata_sources(root, **arguments)
    native = native_table()
    native.data[0, "code_systeme_alti_site"] = None
    projected = project_station_metadata(native, pl.DataFrame({"station_id": ["0001"]}), sources, FIELDS)
    station = projected.filter(pl.col("source_field") == "altitude_ref_alti_station")
    assert station.select("source_datum", "source_datum_field", "source_datum_dtype").row(0) == (
        None,
        "code_systeme_alti_site",
        "Int64",
    )
    assert projected.filter(pl.col("source_field") == "altitude_site")["source_datum"].item() == "0"


def test_publication_requires_each_response_fact_not_a_different_events_members(source_inputs):
    root, arguments = source_inputs
    sources = read_station_metadata_sources(root, **arguments)
    uses = tuple(item.model_copy(update={"facts": (f"{SITE_FACT}.different-response",)}) for item in adopted(arguments))
    with pytest.raises(FatalContractError, match="adopted archive members"):
        verify_adopted_station_metadata(sources, uses)


def test_lineage_digest_relation_is_checked_separately_from_member_integrity(source_inputs):
    root, arguments = source_inputs
    path = root / "sites/lineage.json"
    lineage = json.loads(path.read_bytes())
    lineage["files"][0]["sha256"] = "f" * 64
    path.write_text(json.dumps(lineage))
    raw = path.read_bytes()
    arguments["lineage_sha256"] = hashlib.sha256(raw).hexdigest()
    selected = arguments["input_receipt"]
    arguments["input_receipt"] = selected.model_copy(
        update={
            "inputs": tuple(
                item.model_copy(update={"sha256": arguments["lineage_sha256"], "byte_size": len(raw)})
                if item.consumer_path == "sites/lineage.json"
                else item
                for item in selected.inputs
            )
        }
    )
    with pytest.raises(FatalContractError, match="lineage disagrees"):
        read_station_metadata_sources(root, **arguments)


def test_empty_canonical_selection_retains_source_schema(source_inputs):
    from rivretrieve._internal.station_metadata import SOURCE_METADATA_SCHEMA

    root, arguments = source_inputs
    sources = read_station_metadata_sources(root, **arguments)
    actual = project_station_metadata(native_table(), pl.DataFrame(schema={"station_id": pl.String}), sources, FIELDS)
    assert_frame_equal(actual, pl.DataFrame(schema=SOURCE_METADATA_SCHEMA))


@pytest.mark.parametrize("number", [2**53 + 1, 10**400])
def test_site_integer_quantities_cannot_round_or_overflow_in_float64(number):
    with pytest.raises(FatalContractError):
        parse_site_response(response([site(altitude_site=number)]), ("001",))


def test_site_temporary_native_table_uses_site_acquisition_time(source_inputs, monkeypatch):
    from rivretrieve._internal.catalogues.native import RETRIEVED_AT_DTYPE
    from rivretrieve._internal.providers.fr_hubeau import station_metadata as module

    root, arguments = source_inputs
    sources = read_station_metadata_sources(root, **arguments)
    native = native_table()
    native.data[0, "retrieved_at"] = datetime(2025, 1, 1, tzinfo=UTC)
    build = module.build_station_metadata
    seen = []

    def inspect(provider_id, native_table, stations, station_origin, fields):
        if fields[0].source_scope == SITE_SCOPE:
            seen.append(native_table.data["retrieved_at"])
        return build(provider_id, native_table, stations, station_origin, fields)

    monkeypatch.setattr(module, "build_station_metadata", inspect)
    project_station_metadata(native, pl.DataFrame({"station_id": ["0001"]}), sources, FIELDS)
    assert len(seen) == 1
    assert seen[0].dtype == RETRIEVED_AT_DTYPE
    assert seen[0].to_list() == [datetime(2026, 1, 1, tzinfo=UTC)]


@pytest.fixture
def metadata_provenance():
    from rivretrieve._internal.acquisition_provenance import (
        AcquisitionProvenance,
        AcquisitionRecord,
        FactBinding,
        RecordingReference,
        SourceRecord,
    )
    from rivretrieve._internal.providers.fr_hubeau import origins

    partitions = ("hydrometry", "temperature")
    bindings = tuple(
        FactBinding(
            fact_group=partition,
            facts=(f"source.station_inventory.{partition}.identity_location_crs",),
            source_id="fr_hubeau",
            acquisition_id=f"historical-{partition}",
        )
        for partition in partitions
    )
    original = AcquisitionProvenance(
        schema_version=2,
        provider_id="fr_hubeau",
        fact_bindings=bindings,
        fact_universe=tuple(fact for binding in bindings for fact in binding.facts),
        source_records=(
            SourceRecord(
                source_id="fr_hubeau",
                issuer="Hub’Eau",
                acquisitions=tuple(
                    AcquisitionRecord(
                        acquisition_id=f"historical-{partition}",
                        method="http_request",
                        instant_type="retrieval",
                        description="Synthetic native inventory",
                        requested_from=("https://hubeau.eaufrance.fr/",),
                        retrieved_at_start=datetime(2025, 1, 1, tzinfo=UTC),
                    )
                    for partition in partitions
                ),
            ),
        ),
    )
    recordings = tuple(
        RecordingReference(
            recording_id=f"synthetic-batch-{index}",
            repository_path=f"{origins.SITE_METADATA_ROOT}/synthetic-batch-{index}/body",
            source_url=SITE_ENDPOINT,
            retrieved_at=datetime(2026, 1, index, tzinfo=UTC),
            media_type="application/json",
            sha256=str(index) * 64,
        )
        for index in (1, 2)
    )
    return original, recordings


def test_provenance_preserves_distinct_site_events_and_historical_native_association(metadata_provenance):
    from rivretrieve._internal.providers.fr_hubeau import origins

    original, recordings = metadata_provenance
    updated = origins.with_station_metadata_sources(original, recordings)
    source = updated.source_records[0]
    acquisitions = {item.acquisition_id: item for item in source.acquisitions}
    evidence = {item.recording.recording_id: item.recording for item in source.evidence}
    bindings = {fact: binding for binding in updated.fact_bindings for fact in binding.facts}
    assert updated.native_table == original.native_table
    assert source.acquisitions[:2] == original.source_records[0].acquisitions
    for recording in recordings:
        event = acquisitions[recording.recording_id]
        assert event.recording_ids == (recording.recording_id,)
        assert event.retrieved_at_start == recording.retrieved_at
        assert event.requested_from == (SITE_ENDPOINT,)
        assert evidence[recording.recording_id] == recording
        assert (
            bindings[origins.SITE_METADATA_FACT_PREFIX + recording.recording_id].acquisition_id
            == recording.recording_id
        )
    assert recordings[0].retrieved_at != recordings[1].retrieved_at
    assert recordings[0].sha256 != recordings[1].sha256
    assert bindings[origins.SITE_ASSOCIATION_FACT].acquisition_id == "historical-hydrometry"
    assert bindings[origins.HYDROMETRY_METADATA_FACT].acquisition_id == "historical-hydrometry"
    assert bindings[origins.TEMPERATURE_METADATA_FACT].acquisition_id == "historical-temperature"
    assert "source.station.hubeau_site_metadata" not in updated.fact_universe
    serialized = updated.model_dump_json()
    assert "?code_site=" not in serialized
    assert "/restricted/" not in serialized
    assert "/Users/" not in serialized
    assert "/tmp/" not in serialized
    assert all(not item.repository_path.startswith("/") for item in evidence.values())


def test_provenance_fields_keep_endpoint_datum_support_and_own_response_receipts(metadata_provenance):
    from rivretrieve._internal.providers.fr_hubeau import origins

    original, recordings = metadata_provenance
    updated = origins.with_station_metadata_sources(original, recordings)
    fields = origins.station_metadata_fields(tuple(item.recording_id for item in recordings))
    site_fields = tuple(item for item in fields if item.source_scope == SITE_SCOPE)
    expected_facts = (
        "source.station.hubeau_site_metadata.synthetic-batch-1",
        "source.station.hubeau_site_metadata.synthetic-batch-2",
        origins.SITE_ASSOCIATION_FACT,
    )
    assert len(site_fields) == 3
    assert all(item.source_facts == expected_facts for item in site_fields)
    station_elevation = next(item for item in fields if item.source_field == "altitude_ref_alti_station")
    site_elevation = next(item for item in fields if item.source_field == "altitude_site")
    assert station_elevation.datum_field == site_elevation.datum_field == "code_systeme_alti_site"
    assert station_elevation.datum_support == (origins.STATION_DATUM_FACT,)
    assert site_elevation.datum_support == (origins.SITE_DATUM_FACT,)
    assert origins.STATION_DATUM_FACT != origins.SITE_DATUM_FACT
    assert station_elevation.source_unit == "m"
    assert site_elevation.source_unit is None
    assert {origins.STATION_DATUM_FACT, origins.SITE_DATUM_FACT} <= set(updated.fact_universe)
    support = origins.station_metadata_supporting_inputs(updated)
    for recording in recordings:
        assert set(support[origins.SITE_METADATA_FACT_PREFIX + recording.recording_id]) == {
            f"{origins.SITE_METADATA_ROOT}/documents.json",
            f"{origins.SITE_METADATA_ROOT}/lineage.json",
            f"{origins.SITE_METADATA_ROOT}/{recording.recording_id}/receipt.json",
        }


def test_provenance_rejects_public_batch_filter_disclosure(metadata_provenance):
    from rivretrieve._internal.providers.fr_hubeau import origins

    original, recordings = metadata_provenance
    exposed = recordings[0].model_copy(update={"source_url": SITE_ENDPOINT + "?code_site=synthetic"})
    with pytest.raises(ValueError, match="omit private batch filters"):
        origins.with_station_metadata_sources(original, (exposed, recordings[1]))
