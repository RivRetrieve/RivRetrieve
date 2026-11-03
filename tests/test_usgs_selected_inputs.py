"""Selected derived inputs remain distinct from source recordings."""

import pytest

from rivretrieve._internal.providers.usgs_nwis import origins
from tests.test_usgs_selected_provenance import selected_graph


def test_selected_native_events_and_support_come_from_declared_roles():
    graph = selected_graph()
    assert origins.selected_native_acquisition_ids(graph) == ("original-0", "original-1")
    support = origins.station_metadata_supporting_inputs(graph)
    assert support["source.station.baseline_identity"] == (
        "maintenance/catalogue/usgs_nwis/baseline-monitoring-locations.json",
        "maintenance/catalogue/usgs_nwis/baseline/recovery.receipt.json",
    )
    assert support["source.legacy_sitefile_attributes.input_0"] == (
        "maintenance/catalogue/usgs_nwis/legacy-native.parquet",
    )
    assert support["source.legacy_series_claims.input_0"] == ("maintenance/catalogue/usgs_nwis/legacy-native.parquet",)
    bad = graph.model_copy(
        update={
            "fact_bindings": tuple(
                b for b in graph.fact_bindings if b.facts != ("selected.modern_monitoring_locations",)
            )
        }
    )
    with pytest.raises(ValueError, match="Missing selected"):
        origins.selected_native_acquisition_ids(bad)


def test_receipt_selection_keeps_legacy_derived_table_distinct_from_same_event_recordings():
    from rivretrieve._internal.acquisition_provenance import RetainedInputReceipt, RetainedInputReference
    from rivretrieve._internal.catalogues.inputs import select_catalogue_build_inputs

    graph = selected_graph()
    refs = []

    def ref(path, identifier, digest, size, role):
        refs.append(
            RetainedInputReference(
                consumer_path=path,
                archive_repository="https://github.com/RivRetrieve/verification-evidence",
                archive_revision="a" * 40,
                collection_id="synthetic",
                manifest_sha256="c" * 64,
                artifact_id=identifier,
                sha256=digest,
                byte_size=size,
                role=role,
            )
        )

    ref(graph.native_table.repository_path, "modern", "b" * 64, 1, "derived_input")
    for source in graph.source_records:
        for evidence in source.evidence:
            record = evidence.recording
            ref(record.repository_path, record.recording_id.replace(":", "-"), record.sha256, 1, "response_recording")
    support = origins.station_metadata_supporting_inputs(graph)
    paths = {item.consumer_path for item in refs}
    for selected in support.values():
        for path in selected:
            if path not in paths:
                ref(
                    path,
                    "support-" + str(len(refs)),
                    "d" * 64,
                    1,
                    "derived_input" if path.endswith(".parquet") else "research_context",
                )
                paths.add(path)
    receipt = RetainedInputReceipt(
        schema_version=3,
        archive_code_revision="a" * 40,
        code_revision="e" * 40,
        declaration_revision="e" * 40,
        inputs=tuple(refs),
    )
    adopted = select_catalogue_build_inputs(
        graph,
        receipt,
        origins.selected_native_acquisition_ids(graph),
        (("src/rivretrieve/_internal/providers/usgs_nwis/origins.py", "build_modern_acquisition_provenance"),),
        supporting_inputs={
            path: tuple(fact for fact, paths in support.items() if path in paths)
            for path in {p for paths in support.values() for p in paths}
        },
    )
    legacy_facts = set(origins.selected_role_inputs(graph, "legacy_sitefile_attributes"))
    matching = [item for item in adopted.inputs if legacy_facts <= set(item.facts)]
    assert len(matching) > 1
    derived = [item for item in matching if item.usage == "reviewed_support" and item.reference.role == "derived_input"]
    assert len(derived) == 1
    assert derived[0].reference.artifact_id == next(
        item.artifact_id
        for item in refs
        if item.consumer_path == "maintenance/catalogue/usgs_nwis/legacy-native.parquet"
    )
