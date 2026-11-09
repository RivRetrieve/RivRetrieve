"""Synthetic SENAMHI catalogue identity and source-fidelity checks."""

from datetime import UTC, datetime

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.catalogues.native import RetrievedAt
from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import station_native_table


def station(code, **values):
    return {"stationId": code, "typeId": "H", "categoryId": "05", "name": "Synthetic station", **values}


def envelope(rows):
    return {"status": True, "data": rows}


def test_registry_keeps_primary_identity_hydrological_exceptions_and_closed_stations():
    native = station_native_table(
        envelope([station("A", legacyStationId="B", conditionId="C", latitude="-12.5", longitude="-74.25")]),
        envelope(
            [station("B", typeId="M", categoryId="22", conditionId="P"), station("MET", typeId="M", categoryId="01")]
        ),
        envelope([station("A", legacyStationId="B", conditionId="C", latitude="-12.5", longitude="-74.25")]),
        retrieved_at=RetrievedAt(datetime(2026, 10, 31, tzinfo=UTC)),
    )
    assert_frame_equal(
        native.data.select("stationId", "legacyStationId", "conditionId", "latitude", "longitude"),
        pl.DataFrame(
            {
                "stationId": ["A", "B"],
                "legacyStationId": ["B", None],
                "conditionId": ["C", "P"],
                "latitude": ["-12.5", None],
                "longitude": ["-74.25", None],
            }
        ),
    )


def test_recognized_empty_hourly_association_uses_response_units():
    from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import phisis_associations

    result = phisis_associations(
        envelope({"station": {"code": "A"}, "type": "HOURLY", "variable": "LEVEL", "unit": "m.s.n.m", "hourly": []}),
        station="A",
        resolution="HOURLY",
        variable="LEVEL",
        station_ids={"A"},
    )
    assert result.select("station_id", "subsystem", "resolution", "variable", "unit").rows() == [
        ("A", "phisis", "HOURLY", "LEVEL", "m.s.n.m")
    ]


def test_monthly_preserves_distinct_water_level_fields_without_using_dates():
    from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import monthly_associations

    result = monthly_associations(
        envelope(
            {
                "columns": [
                    {"column": "N_NIVELMEDIO", "unit": "m"},
                    {"column": "N_NIV_INST_00", "unit": "m"},
                    {"column": "RAIN", "unit": "mm"},
                ],
                "readings": [{"date": "2099-12-01"}],
            }
        ),
        station="A",
        station_ids={"A"},
    )
    assert result.select("station_id", "subsystem", "variable", "unit").rows() == [
        ("A", "monthly_archive", "N_NIVELMEDIO", "m"),
        ("A", "monthly_archive", "N_NIV_INST_00", "m"),
    ]
    empty = monthly_associations(
        envelope({"columns": [{"column": "RAIN", "unit": "mm"}], "readings": []}), station="A", station_ids={"A"}
    )
    assert empty.is_empty()


def test_metadata_joins_only_exact_primary_code_and_preserves_unknowns():
    from rivretrieve._internal.providers.pe_senamhi.station_metadata import (
        enrich_station_metadata,
        project_station_metadata,
    )

    native = station_native_table(
        envelope([station("A", legacyStationId="B", altitude=123.5), station("B")]),
        envelope([]),
        envelope([]),
        retrieved_at=RetrievedAt(datetime(2026, 10, 31, tzinfo=UTC)),
    )
    enriched = enrich_station_metadata(
        native, [envelope({"code": "B", "waterBody": "Synthetic river", "waterBodyType": "RÍO", "automaticCode": "A"})]
    )
    assert enriched.data.select("stationId", "waterBody").rows() == [("A", None), ("B", "Synthetic river")]
    stations = pl.DataFrame({"provider_id": ["pe_senamhi"] * 2, "station_id": ["A", "B"]})
    metadata = project_station_metadata(enriched, stations)
    elevation = metadata.filter((pl.col("station_id") == "A") & (pl.col("attribute_role") == "elevation"))
    assert elevation.select("source_value", "source_unit", "source_datum").row(0) == ("123.5", "m", None)
    missing = metadata.filter((pl.col("station_id") == "A") & (pl.col("attribute_role") == "water_body_name"))
    assert missing["state"].item() == "source_null"


def test_catalogue_keeps_unknown_pairs_and_distinguishes_unit_based_level_products():
    from datetime import date

    from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import catalogue_tables, phisis_associations

    native = station_native_table(
        envelope([station("A", latitude="-12", longitude="-75"), station("B")]),
        envelope([]),
        envelope([]),
        retrieved_at=RetrievedAt(datetime(2026, 10, 31, tzinfo=UTC)),
    )
    associations = phisis_associations(
        envelope({"station": {"code": "A"}, "type": "DAILY", "variable": "LEVEL", "unit": "m.s.n.m"}),
        station="A",
        resolution="DAILY",
        variable="LEVEL",
        station_ids={"A", "B"},
    )
    products, stations, pairs = catalogue_tables(native, associations, checked_on=date(2026, 10, 31))
    assert stations["crs"].to_list() == ["unknown", "unknown"]
    assert stations.select("latitude", "longitude").row(0) == (-12.0, -75.0)
    assert products.select("product_id", "frequency", "statistic").rows() == [
        ("phisis_daily_level_above_sea_level", "daily", "unknown")
    ]
    assert pairs.select("station_id", "availability").rows() == [("A", "available"), ("B", "unknown")]
    assert pairs["published_record_start_date"].null_count() == 2
    assert pairs["published_record_end_date"].null_count() == 2


def test_source_descriptions_preserve_unknown_time_and_datum():
    from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import describe_associations, phisis_associations

    associations = phisis_associations(
        envelope({"station": {"code": "A"}, "type": "DAILY", "variable": "LEVEL", "unit": "m.s.n.m"}),
        station="A",
        resolution="DAILY",
        variable="LEVEL",
        station_ids={"A"},
    )
    description = describe_associations(associations).descriptions[0]
    facts = description.facts[0]
    assert facts.source_unit.value == "m.s.n.m"
    assert facts.vertical_reference.value == "above_sea_level"
    assert facts.frequency.value == "daily"
    assert facts.time_zone.value is None
    assert facts.vertical_datum.value is None


def test_conflicting_registry_identity_and_mismatched_response_are_fatal():
    import pytest

    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import phisis_associations

    with pytest.raises(FatalContractError, match="disagree"):
        station_native_table(
            envelope([station("A")]),
            envelope([]),
            envelope([station("A", name="Changed")]),
            retrieved_at=RetrievedAt(datetime(2026, 10, 31, tzinfo=UTC)),
        )
    with pytest.raises(FatalContractError, match="differs"):
        phisis_associations(
            envelope({"station": {"code": "B"}, "type": "HOURLY", "variable": "LEVEL", "unit": "m"}),
            station="A",
            resolution="HOURLY",
            variable="LEVEL",
            station_ids={"A", "B"},
        )


def test_original_reader_requires_selected_bytes_before_json_parsing(tmp_path):
    import hashlib

    import pytest

    from rivretrieve._internal.acquisition_provenance import (
        RecordingReference,
        RetainedInputReceipt,
        RetainedInputReference,
    )
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import read_original

    body = b'{"data": {}}'
    path = tmp_path / "stations.body"
    path.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    reference = RecordingReference(
        recording_id="station-snapshot",
        repository_path="stations.body",
        source_url="https://example.test/synthetic",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        media_type="application/json",
        sha256=digest,
    )
    receipt = RetainedInputReceipt(
        schema_version=3,
        code_revision="a" * 40,
        declaration_revision="a" * 40,
        archive_code_revision="b" * 40,
        inputs=(
            RetainedInputReference(
                consumer_path="stations.body",
                archive_repository="https://github.com/RivRetrieve/verification-evidence",
                archive_revision="b" * 40,
                collection_id="synthetic",
                manifest_sha256="c" * 64,
                artifact_id="stations",
                sha256=digest,
                byte_size=len(body),
                role="publisher_original",
            ),
        ),
    )
    assert read_original(tmp_path, reference, input_receipt=receipt) == body
    path.write_bytes(b"changed")
    with pytest.raises(FatalContractError, match="archive identity"):
        read_original(tmp_path, reference, input_receipt=receipt)
    with pytest.raises(FatalContractError, match="selected"):
        read_original(tmp_path, reference, input_receipt=receipt.model_copy(update={"inputs": ()}))


def test_selected_native_requires_verified_declaration_and_originals(tmp_path):
    import hashlib
    import json

    import pytest

    from rivretrieve._internal.acquisition_provenance import RetainedInputReceipt
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import read_native_sources

    captures = []
    inputs = []
    for kind, payload in (
        ("registry_h", envelope([station("A")])),
        ("registry_m", envelope([])),
        ("registry_actives", envelope([])),
        ("phisis_detail", envelope({"code": "A", "waterBody": "Synthetic river"})),
    ):
        name = kind + ".body"
        content = json.dumps(payload).encode()
        (tmp_path / name).write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        inputs.append(
            {
                "consumer_path": name,
                "archive_repository": "https://github.com/RivRetrieve/verification-evidence",
                "archive_revision": "b" * 40,
                "collection_id": "synthetic",
                "manifest_sha256": "c" * 64,
                "artifact_id": kind,
                "sha256": digest,
                "byte_size": len(content),
                "role": "publisher_original",
            }
        )
        captures.append(
            {
                "kind": kind,
                "body": name,
                "recording": {
                    "recording_id": kind,
                    "repository_path": name,
                    "source_url": "https://example.test/synthetic",
                    "retrieved_at": "2026-01-01T00:00:00Z",
                    "media_type": "application/json",
                    "sha256": digest,
                },
            }
        )
    declaration = json.dumps({"captures": captures}).encode()
    (tmp_path / "selection.json").write_bytes(declaration)
    receipt = RetainedInputReceipt.model_validate(
        {
            "schema_version": 3,
            "code_revision": "a" * 40,
            "declaration_revision": "a" * 40,
            "archive_code_revision": "b" * 40,
            "inputs": inputs,
            "declaration_inputs": [
                {
                    "consumer_path": "selection.json",
                    "declaration": {
                        "repository": "https://github.com/RivRetrieve/verification-evidence",
                        "revision": "b" * 40,
                        "repository_path": "declarations/pe_senamhi/catalogue.json",
                    },
                    "sha256": hashlib.sha256(declaration).hexdigest(),
                    "byte_size": len(declaration),
                }
            ],
        }
    )
    native = read_native_sources(tmp_path, selection_path="selection.json", input_receipt=receipt)
    assert native.data.select("stationId", "waterBody").rows() == [("A", "Synthetic river")]
    from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import main

    receipt_path = tmp_path / "input-receipt.json"
    receipt_path.write_text(receipt.model_dump_json())
    output = tmp_path.parent / (tmp_path.name + "-native")
    args = [
        "--evidence-root",
        str(tmp_path),
        "--selection",
        "selection.json",
        "--input-receipt",
        str(receipt_path),
        "--native-only",
        "--out",
        str(output),
    ]
    assert main(args) == 0
    assert pl.read_parquet(output / "native.parquet").equals(native.data)
    with pytest.raises(FatalContractError, match="new path"):
        main(args)
    with pytest.raises(FatalContractError, match="authored declaration"):
        read_native_sources(
            tmp_path,
            selection_path="selection.json",
            input_receipt=receipt.model_copy(update={"declaration_inputs": ()}),
        )
    from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import read_catalogue_sources

    changed_selection = json.loads(declaration)
    changed_selection["native_table"] = "absent.parquet"
    changed_bytes = json.dumps(changed_selection).encode()
    (tmp_path / "selection.json").write_bytes(changed_bytes)
    changed_receipt = receipt.model_copy(
        update={
            "declaration_inputs": (
                receipt.declaration_inputs[0].model_copy(
                    update={"sha256": hashlib.sha256(changed_bytes).hexdigest(), "byte_size": len(changed_bytes)}
                ),
            )
        }
    )
    with pytest.raises(FatalContractError, match="native table is absent"):
        read_catalogue_sources(tmp_path, selection_path="selection.json", input_receipt=changed_receipt)
    changed_native = native.data.with_columns(pl.lit("Changed source name").alias("name"))
    changed_native.write_parquet(tmp_path / "absent.parquet")
    native_bytes = (tmp_path / "absent.parquet").read_bytes()
    from rivretrieve._internal.acquisition_provenance import RetainedInputReference

    native_member = RetainedInputReference.model_validate(
        {
            **inputs[0],
            "consumer_path": "absent.parquet",
            "artifact_id": "derived",
            "role": "derived_input",
            "sha256": hashlib.sha256(native_bytes).hexdigest(),
            "byte_size": len(native_bytes),
        }
    )
    changed_receipt = changed_receipt.model_copy(update={"inputs": (*changed_receipt.inputs, native_member)})
    with pytest.raises(FatalContractError, match="differs from selected original reconstruction"):
        read_catalogue_sources(tmp_path, selection_path="selection.json", input_receipt=changed_receipt)
    (tmp_path / "selection.json").write_bytes(declaration)
    (tmp_path / "registry_h.body").write_bytes(b"not JSON")
    with pytest.raises(FatalContractError, match="archive identity"):
        read_native_sources(tmp_path, selection_path="selection.json", input_receipt=receipt)


def test_provenance_requires_direct_sources_and_retains_derived_native_identity(tmp_path):
    import pytest

    from rivretrieve._internal.acquisition_provenance import (
        AcquisitionRecord,
        FactBinding,
        NativeTableIdentity,
        RecordingReference,
    )
    from rivretrieve._internal.providers.pe_senamhi.origins import build_acquisition_provenance

    native = NativeTableIdentity(
        location_kind="retained", repository_path="native.parquet", revision="a" * 40, sha256="b" * 64, byte_size=1
    )
    recording = RecordingReference(
        recording_id="synthetic",
        repository_path="source.body",
        source_url="https://example.test/synthetic",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        media_type="application/json",
        sha256="c" * 64,
    )
    acquisition = AcquisitionRecord(
        acquisition_id="synthetic",
        method="http_request",
        instant_type="retrieval",
        description="Synthetic source",
        requested_from=(recording.source_url,),
        retrieved_at_start=recording.retrieved_at,
        recording_ids=(recording.recording_id,),
    )
    facts = (
        "source.station.registry",
        "source.station.phisis_detail",
        "source.station.altitude_unit",
        "source.station_product.associations",
        "source.station_product.inventory_support",
        "source.series.fields",
        "source.series.frequency",
        "source.provider.terms",
        "source.provider.attribution",
    )
    binding = FactBinding(fact_group="synthetic", facts=facts, source_id="pe_senamhi", acquisition_id="synthetic")
    provenance = build_acquisition_provenance(
        native, (recording,), acquisitions=(acquisition,), source_bindings=(binding,)
    )
    from datetime import date

    from rivretrieve._internal.acquisition_provenance import (
        ArchiveMemberReference,
        CatalogueBuildInputs,
        CodeReference,
        RetainedInputUse,
    )
    from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import (
        ASSOCIATION_SCHEMA,
        build_catalogue,
        write_catalogue,
    )
    from rivretrieve._internal.providers.pe_senamhi.origins import STATION_CATALOGUE_ORIGINS
    from rivretrieve._internal.providers.pe_senamhi.station_metadata import (
        STATION_METADATA_FIELDS,
        enrich_station_metadata,
        project_station_metadata,
    )

    rows = station_native_table(
        envelope([station("A")]), envelope([]), envelope([]), retrieved_at=RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC))
    )
    rows = enrich_station_metadata(rows, [])
    associations = pl.DataFrame([("A", "phisis", "DAILY", "FLOW", "m3/s")], schema=ASSOCIATION_SCHEMA, orient="row")
    catalogue = build_catalogue(
        rows, STATION_CATALOGUE_ORIGINS, associations=associations, checked_on=date(2026, 1, 1), provenance=provenance
    )
    from dataclasses import replace

    catalogue = replace(catalogue, station_metadata=project_station_metadata(rows, catalogue.stations))
    assert catalogue.provider_info["license"] is None
    assert "SENAMHI" in catalogue.provider_info["citation"]

    def code(path, symbol):
        return CodeReference(
            repository="https://github.com/RivRetrieve/RivRetrieve",
            repository_path=path,
            symbol=symbol,
            revision="a" * 40,
        )

    prefix = "src/rivretrieve/_internal/providers/pe_senamhi/"
    member = ArchiveMemberReference(
        archive_repository="https://github.com/RivRetrieve/verification-evidence",
        archive_revision="a" * 40,
        collection_id="synthetic",
        manifest_sha256="d" * 64,
        artifact_id="native",
        sha256="b" * 64,
        byte_size=1,
        role="derived_input",
    )
    build_inputs = CatalogueBuildInputs(
        build=code(prefix + "generate_catalogue.py", "main"),
        declarations=(
            code(prefix + "origins.py", "build_acquisition_provenance"),
            code(prefix + "generate_catalogue.py", "build_catalogue"),
            code(prefix + "origins.py", "STATION_METADATA_FIELDS"),
            code(prefix + "station_metadata.py", "project_station_metadata"),
        ),
        inputs=(RetainedInputUse(reference=member, usage="native_table", facts=facts),),
    )
    write_catalogue(
        catalogue,
        tmp_path / "catalogue",
        build_inputs=build_inputs,
        native_table=rows,
        metadata_fields=STATION_METADATA_FIELDS,
    )
    assert pl.read_parquet(tmp_path / "catalogue" / "stations.parquet")["station_id"].to_list() == ["A"]
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact

    loaded = load_packaged_catalogue_artifact(tmp_path / "catalogue", on_issue="raise")
    assert loaded.stations["station_id"].to_list() == ["A"]
    assert loaded.stations["crs"].to_list() == ["unknown"]
    assert {item.identity.published_id for item in loaded.source_descriptions.descriptions} == {
        "current",
        "minimum",
        "maximum",
    }

    attribution_recording = recording.model_copy(
        update={"recording_id": "attribution", "repository_path": "frontend.body"}
    )
    attribution_acquisition = acquisition.model_copy(
        update={"acquisition_id": "attribution", "recording_ids": ("attribution",)}
    )
    distinct_binding = binding.model_copy(
        update={"facts": tuple(fact for fact in facts if fact != "source.provider.attribution")}
    )
    attribution_binding = FactBinding(
        fact_group="attribution",
        facts=("source.provider.attribution",),
        source_id="pe_senamhi",
        acquisition_id="attribution",
    )
    supported = build_acquisition_provenance(
        native,
        (recording, attribution_recording),
        acquisitions=(acquisition, attribution_acquisition),
        source_bindings=(distinct_binding, attribution_binding),
    )
    terms_binding = next(item for item in supported.fact_bindings if "provider.citation" in item.facts)
    assert {item.fact for item in terms_binding.transformation.external_inputs} == {
        "source.provider.terms",
        "source.provider.attribution",
    }
    assert len(supported.source_records[0].acquisitions) == 2

    assert provenance.native_table == native
    station_binding = next(binding for binding in provenance.fact_bindings if "station.latitude" in binding.facts)
    assert {item.fact for item in station_binding.transformation.external_inputs} == {
        "source.station.registry",
        "source.station.phisis_detail",
    }
    with pytest.raises(ValueError, match="Missing"):
        build_acquisition_provenance(native, (recording,), acquisitions=(acquisition,), source_bindings=())


def test_catalogue_builder_checks_declared_station_identity():
    from datetime import date

    import pytest

    from rivretrieve._internal.catalogue_origins import Field, NativeColumn
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import ASSOCIATION_SCHEMA, build_catalogue
    from rivretrieve._internal.providers.pe_senamhi.origins import STATION_CATALOGUE_ORIGINS

    native = station_native_table(
        envelope([station("A")]), envelope([]), envelope([]), retrieved_at=RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC))
    )
    wrong = {**STATION_CATALOGUE_ORIGINS, "station_id": Field(NativeColumn("name"))}
    with pytest.raises(FatalContractError, match="station_id"):
        build_catalogue(
            native,
            wrong,
            associations=pl.DataFrame(schema=ASSOCIATION_SCHEMA),
            checked_on=date(2026, 1, 1),
            provenance=None,
        )


def test_repeated_association_witnesses_describe_one_source_series():
    from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import ASSOCIATION_SCHEMA, describe_associations

    associations = pl.DataFrame(
        [("A", "monthly_archive", None, "N_NIVELMEDIO", "m")] * 2, schema=ASSOCIATION_SCHEMA, orient="row"
    )
    assert len(describe_associations(associations).descriptions) == 1


def test_station_origins_preserve_source_null_coordinates():
    from datetime import date

    from rivretrieve._internal.catalogue_origins import enforce_catalogue_origins
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import ASSOCIATION_SCHEMA, catalogue_tables
    from rivretrieve._internal.providers.pe_senamhi.origins import STATION_CATALOGUE_ORIGINS

    native = station_native_table(
        envelope([station("A", latitude=None, longitude=None), station("B", latitude="-12.5", longitude="-75.25")]),
        envelope([]),
        envelope([]),
        retrieved_at=RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    _, stations, _ = catalogue_tables(native, pl.DataFrame(schema=ASSOCIATION_SCHEMA), checked_on=date(2026, 1, 1))
    enforce_catalogue_origins(ProviderId("pe_senamhi"), STATION_CATALOGUE_ORIGINS, native, stations)
    assert stations.select("latitude", "longitude").rows() == [(None, None), (-12.5, -75.25)]


@pytest.mark.governing(
    "maintenance/catalogue/pe_senamhi/official",
    "maintenance/catalogue/pe_senamhi/official/selection.json",
)
def test_selected_inputs_publish_deterministic_catalogue(
    retained_evidence_root, catalogue_input_receipt, catalogue_build_inputs, tmp_path
):
    import os
    from pathlib import Path

    import polars.testing as pl_testing

    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import main, read_catalogue_sources
    from rivretrieve._internal.providers.pe_senamhi.origins import STATION_METADATA_NOTICE

    configured = os.environ.get("RIVRETRIEVE_CATALOGUE_PRODUCT_OUTPUT")
    if not configured:
        pytest.fail("Reviewed catalogue generation requires restricted product output.", pytrace=False)
    product_root = Path(configured).resolve()
    selection = "maintenance/catalogue/pe_senamhi/official/selection.json"
    sources = read_catalogue_sources(
        retained_evidence_root, selection_path=selection, input_receipt=catalogue_input_receipt
    )
    build_inputs = catalogue_build_inputs(sources.provenance)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(catalogue_input_receipt.model_dump_json())
    build_path = tmp_path / "build-inputs.json"
    build_path.write_text(build_inputs.model_dump_json())
    outputs = [product_root / "pe_senamhi", product_root / "pe_senamhi-repeat"]
    for output in outputs:
        assert (
            main(
                [
                    "--evidence-root",
                    str(retained_evidence_root),
                    "--selection",
                    selection,
                    "--input-receipt",
                    str(receipt_path),
                    "--build-inputs",
                    str(build_path),
                    "--out",
                    str(output),
                ]
            )
            == 0
        )
        load_packaged_catalogue_artifact(output, on_issue="raise")
        stations = pl.read_parquet(output / "stations.parquet")
        assert stations["crs"].unique().to_list() == ["unknown"]
        pairs = pl.read_parquet(output / "station_products.parquet")
        assert pairs["published_record_start_date"].null_count() == pairs.height
        assert pairs["published_record_end_date"].null_count() == pairs.height
        assert "unavailable" not in pairs["availability"].to_list()
        import json

        provider = json.loads((output / "provider.json").read_bytes())
        assert provider["license"] is None
        assert "SENAMHI" in provider["citation"]
        assert STATION_METADATA_NOTICE in json.dumps(
            json.loads((output / "croissant.json").read_bytes()), ensure_ascii=False
        )
        assert not (output / "native.parquet").exists()
    assert {p.name for p in outputs[0].iterdir()} == {p.name for p in outputs[1].iterdir()}
    for path in outputs[0].iterdir():
        repeated = outputs[1] / path.name
        if path.suffix == ".parquet":
            pl_testing.assert_frame_equal(pl.read_parquet(path), pl.read_parquet(repeated))
        assert path.read_bytes() == repeated.read_bytes()
