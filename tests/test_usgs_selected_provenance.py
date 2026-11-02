"""Synthetic selected modern provenance; no retained source inputs."""

from datetime import UTC, datetime

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionRecord,
    MaterialIdentity,
    NativeTableIdentity,
    RecordingReference,
)
from rivretrieve._internal.providers.usgs_nwis import origins


def selected_graph():
    records = tuple(
        RecordingReference(
            recording_id=f"record-{i}",
            repository_path=f"inputs/{i}.gz",
            source_url=f"https://example.test/{i}",
            retrieved_at=datetime(2026, 1, i + 1, tzinfo=UTC),
            media_type="application/gzip",
            sha256=str(i) * 64,
        )
        for i in range(2)
    )
    acquisitions = tuple(
        AcquisitionRecord(
            acquisition_id=f"original-{i}",
            method="http_campaign",
            instant_type="retrieval",
            description="Synthetic source campaign",
            requested_from=(record.source_url,),
            retrieved_at_start=record.retrieved_at,
            recording_ids=(record.recording_id,),
        )
        for i, record in enumerate(records)
    )
    baseline = AcquisitionRecord(
        acquisition_id="baseline-git",
        method="repository_recovery",
        instant_type="provenance_lower_bound",
        description="Recovered published baseline identity map",
        requested_from=("https://github.com/RivRetrieve/RivRetrieve/blob/" + "a" * 40 + "/monitoring_locations.json",),
        retrieved_at_start=datetime(2026, 1, 3, tzinfo=UTC),
        material=MaterialIdentity(filename="monitoring_locations.json", byte_count=2, sha256="f" * 64),
    )
    native = NativeTableIdentity(
        repository_path="inputs/modern-native.parquet", revision="a" * 40, sha256="b" * 64, byte_size=1
    )
    return origins.build_modern_acquisition_provenance(
        native,
        acquisitions,
        records,
        role_acquisitions={
            "modern_monitoring_locations": ("original-0", "original-1"),
            "legacy_sitefile_attributes": ("original-0", "original-1"),
            "modern_series": ("original-0",),
            "retained_historical_metadata": ("original-1",),
        },
        baseline=baseline,
    )


def test_two_original_events_support_stable_roles_and_direct_metadata_leaves():
    graph = selected_graph()
    modern = next(
        binding for binding in graph.fact_bindings if binding.facts == ("selected.modern_monitoring_locations",)
    )
    assert [ref.fact for ref in modern.transformation.external_inputs] == [
        "source.modern_monitoring_locations.input_0",
        "source.modern_monitoring_locations.input_1",
    ]
    bindings = {fact: binding for binding in graph.fact_bindings for fact in binding.facts}
    assert [bindings[ref.fact].acquisition_id for ref in modern.transformation.external_inputs] == [
        "original-0",
        "original-1",
    ]
    fields = origins.selected_station_metadata_fields(graph)
    name = next(field for field in fields if field.attribute_role == "station_name")
    assert name.source_facts == tuple(ref.fact for ref in modern.transformation.external_inputs)
    assert bindings["source.station.baseline_identity"].acquisition_id == "baseline-git"
    assert "source.station.nwis_identity_location_datum" not in graph.fact_universe


def test_two_event_graph_publishes_metadata_with_original_support():
    import json
    from io import BytesIO

    import polars as pl

    from rivretrieve._internal.acquisition_provenance import (
        ArchiveMemberReference,
        CatalogueBuildInputs,
        CodeReference,
        RetainedInputUse,
    )
    from rivretrieve._internal.catalogues.native import NativeTable
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.catalogues.schemas import (
        PRODUCT_CATALOG_SCHEMA,
        STATION_CATALOG_SCHEMA,
        STATION_PRODUCT_CATALOG_SCHEMA,
    )
    from rivretrieve._internal.catalogues.source_series import SourceDescriptions
    from rivretrieve._internal.providers.usgs_nwis.station_metadata import project_modern_station_metadata

    graph = selected_graph()
    fields = origins.selected_station_metadata_fields(graph)
    stations = pl.DataFrame(
        [("usgs_nwis", "001", 40.0, -75.0, "EPSG:4326")], schema=STATION_CATALOG_SCHEMA.polars_schema, orient="row"
    )
    modern = NativeTable(
        pl.DataFrame(
            {
                "station_id": ["001"],
                "monitoring_location_number": ["001"],
                "agency_code": ["USGS"],
                "monitoring_location_name": ["Modern name"],
                "retrieved_at": [datetime(2026, 1, 1, tzinfo=UTC)],
            }
        )
    )
    legacy = NativeTable(
        pl.DataFrame(
            {
                "site_no": ["001"],
                "agency_cd": ["USGS"],
                "drain_area_va": ["2"],
                "contrib_drain_area_va": [""],
                "alt_va": ["3"],
                "alt_datum_cd": ["NAVD88"],
                "retrieved_at": [datetime(2026, 1, 1, tzinfo=UTC)],
            }
        )
    )
    metadata = project_modern_station_metadata(modern, legacy, stations, fields)

    def code(path, symbol):
        return CodeReference(
            repository="https://github.com/RivRetrieve/RivRetrieve",
            revision="a" * 40,
            repository_path=path,
            symbol=symbol,
        )

    prefix = "src/rivretrieve/_internal/providers/usgs_nwis/"
    declarations = tuple(
        code(prefix + path, symbol)
        for path, symbol in [
            ("origins.py", "build_modern_acquisition_provenance"),
            ("origins.py", "STATION_METADATA_FIELDS"),
            ("generate_catalogue.py", "build_modern_catalogue"),
            ("station_metadata.py", "project_modern_station_metadata"),
        ]
    )
    direct = tuple(f for binding in graph.fact_bindings if binding.transformation is None for f in binding.facts)
    reference = ArchiveMemberReference(
        archive_repository="https://github.com/RivRetrieve/verification-evidence",
        archive_revision="a" * 40,
        collection_id="synthetic",
        manifest_sha256="c" * 64,
        artifact_id="native",
        sha256="b" * 64,
        byte_size=1,
        role="derived_input",
    )
    build = CatalogueBuildInputs(
        build=code(prefix + "generate_catalogue.py", "main"),
        declarations=declarations,
        inputs=(RetainedInputUse(reference=reference, usage="native_table", facts=direct),),
    )
    provider = {
        "provider_id": "usgs_nwis",
        "name": "Synthetic",
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "none",
        "catalogue_version": None,
        "license": None,
        "citation": None,
    }
    files = {"provider.json": json.dumps(provider).encode()}
    for name, frame in [
        ("stations", stations),
        ("products", pl.DataFrame(schema=PRODUCT_CATALOG_SCHEMA.polars_schema)),
        ("station_products", pl.DataFrame(schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema)),
    ]:
        buffer = BytesIO()
        frame.write_parquet(buffer)
        files[name + ".parquet"] = buffer.getvalue()
    result = build_catalogue_metadata(
        graph,
        (origins.MODERN_STATION_CATALOGUE_ORIGINS,),
        files,
        build_inputs=build,
        native_table=modern,
        metadata_fields=fields,
        station_metadata=metadata,
        metadata_implementation=(prefix + "station_metadata.py", "project_modern_station_metadata"),
        transformation_implementations={
            "selected_" + role: (prefix + "origins.py", "build_modern_acquisition_provenance")
            for role in origins.SELECTED_SOURCE_ROLES
        },
        source_descriptions=SourceDescriptions(provider_id="usgs_nwis", descriptions=()),
    )
    published = pl.read_parquet(BytesIO(result["station_metadata.parquet"]))
    assert published.filter(pl.col("source_field") == "monitoring_location_name")["source_value"].to_list() == [
        '"Modern name"'
    ]
