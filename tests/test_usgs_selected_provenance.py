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
            "legacy_series_claims": ("original-0", "original-1"),
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


def test_two_event_graph_publishes_and_loads_legacy_claims(tmp_path):
    import polars as pl

    from rivretrieve._internal.acquisition_provenance import (
        ArchiveMemberReference,
        CatalogueBuildInputs,
        CodeReference,
        RetainedInputUse,
    )
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.catalogues.native import NativeTable
    from rivretrieve._internal.catalogues.schemas import (
        STATION_CATALOG_SCHEMA,
        STATION_PRODUCT_CATALOG_SCHEMA,
    )
    from rivretrieve._internal.providers.usgs_nwis import generate_catalogue as generator
    from rivretrieve._internal.providers.usgs_nwis.catalogue_series import modern_source_descriptions

    graph = selected_graph()
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
                "monitoring_location_id": ["USGS-001"],
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
                "data_type_cd": [["dv"]],
                "parm_cd": [["00060"]],
                "stat_cd": [["00003"]],
                "ts_id": [["legacy-17"]],
                "loc_web_ds": [["source description"]],
                "retrieved_at": [datetime(2026, 1, 1, tzinfo=UTC)],
            }
        )
    )

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
    direct = tuple(
        f
        for binding in graph.fact_bindings
        if binding.transformation is None
        for f in binding.facts
        if not f.startswith("source.observation.")
    )
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
    catalogue = generator.GeneratedUsgsNwisCatalogue(
        provider_info=provider,
        products=generator.build_products(),
        stations=stations,
        station_products=pl.DataFrame(schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema),
        source_native=modern.data,
        source_descriptions=modern_source_descriptions(
            [
                {
                    "id": "modern-17",
                    "monitoring_location_id": "USGS-001",
                    "parameter_code": "00060",
                    "statistic_id": "00003",
                    "unit_of_measure": "ft^3/s",
                    "computation_period_identifier": "Daily",
                    "computation_identifier": "Mean",
                    "web_description": "modern description",
                    "sublocation_identifier": None,
                }
            ],
            {"001": "USGS-001"},
        ),
    )
    generator.write_catalogue(
        catalogue, tmp_path, build_inputs=build, native_table=modern, acquisition_provenance=graph, legacy_table=legacy
    )
    loaded = load_packaged_catalogue_artifact(tmp_path)
    claims = pl.read_parquet(tmp_path / "series_claims.parquet")
    assert claims["published_id"].to_list() == ["legacy-17"]
    assert claims["evidence"].to_list() == [
        [
            "catalogue:usgs_nwis:source.legacy_series_claims.input_0",
            "catalogue:usgs_nwis:source.legacy_series_claims.input_1",
        ]
    ]
    assert loaded.provider_info["provider_id"] == "usgs_nwis"


def test_selected_graph_keeps_historical_and_current_observation_routes_independent():
    graph = selected_graph()
    source = next(source for source in graph.source_records if source.source_id == "usgs_nwis")
    acquisitions = {item.acquisition_id: item for item in source.acquisitions}
    bindings = {fact: binding for binding in graph.fact_bindings for fact in binding.facts}
    assert bindings["source.observation.nwis_values_qualifiers_and_timestamps"].acquisition_id == "observation_request"
    assert (
        bindings["source.observation.modern_values_qualifiers_and_timestamps"].acquisition_id
        == "modern_observation_request"
    )
    assert acquisitions["observation_request"].requested_from == (
        "https://waterservices.usgs.gov/nwis/dv/",
        "https://waterservices.usgs.gov/nwis/iv/",
    )
    assert acquisitions["modern_observation_request"].requested_from == (
        "https://api.waterdata.usgs.gov/ogcapi/v1/collections/daily/items",
        "https://api.waterdata.usgs.gov/ogcapi/v1/collections/continuous/items",
    )
