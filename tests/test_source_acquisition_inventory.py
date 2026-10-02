"""SourceAcquisition metadata and real parse output form one bounded retrieval proof."""

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import polars.testing as pl_testing
import pytest

from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import ObservationRequest, RequestedWindow, SourceAcquisition, WindowEndpoint
from rivretrieve._internal.observations import ObservationProvenance
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.no_nve.declaration import declaration
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from rivretrieve._internal.source_series import EvidenceFact, SeriesScope
from rivretrieve._internal.store import StoreRoot


@pytest.mark.parametrize(
    "control", ["unchanged", "unknown-member", "different-facts", "unestablished-metadata-facts", "failure"]
)
def test_acquisition_reconciliation_does_not_hide_unsettled_observations(
    retained_evidence_root: Path, tmp_path, control
):
    stages = declaration.observations.stages
    metadata = read_recording(retained_evidence_root / "tests/test_data" / "no_nve_109.42.0_1001_series.recording.json")
    observations = tuple(
        read_recording(
            retained_evidence_root
            / "tests/test_data"
            / f"no_nve_109.42.0_1001_1440_version-{v}_engine_2024-01-02.recording.json"
        )
        for v in (1, 2, 3)
    )
    replay = ReplayTransport((metadata, *observations))
    requests = []

    class Observed:
        def send(self, request):
            from rivretrieve._internal.transport import TransportFailure, TransportFailureReason

            requests.append(request)
            if control == "failure" and request.url.endswith("/Observations") and request.params["VersionNumber"] == 3:
                raise TransportFailure(request, TransportFailureReason.RETRY_EXHAUSTED, 3, status_code=503)
            return replay.send(request)

    class ControlledMetadata:
        config = stages.config
        window_declarations = stages.window_declarations
        parse = staticmethod(stages.parse)

        @staticmethod
        def fetch(*args, **kwargs):
            acquired = stages.fetch(*args, **kwargs)
            assert isinstance(acquired, SourceAcquisition)
            snapshot = acquired.inventories[0]
            # Explicit authored acquisition controls. Observation parser still consumes exact bytes.
            if control == "unknown-member":
                missing = acquired.series[-1].series_id
                snapshot = snapshot.model_copy(
                    update={
                        "members": tuple(k for k in snapshot.members if k != missing),
                        "member_facts": tuple((k, v) for k, v in snapshot.member_facts if k != missing),
                    }
                )
            if control in ("different-facts", "unestablished-metadata-facts"):
                definition = acquired.series[0]
                fact = definition.facts[0]
                if control == "different-facts":
                    fact = fact.model_copy(
                        update={
                            "facts_id": fact.facts_id + "/metadata-control",
                            "statistic": fact.statistic.model_copy(update={"value": "instantaneous"}),
                        }
                    )
                else:
                    fact = fact.model_copy(
                        update={
                            "facts_id": fact.facts_id + "/metadata-control",
                            "source_unit": EvidenceFact(),
                            "normalized_unit": None,
                        }
                    )
                definition = definition.model_copy(update={"facts": (fact,)})
                definitions = (definition, *acquired.series[1:])
                snapshot = snapshot.model_copy(
                    update={
                        "member_facts": tuple(
                            (item.series_id, tuple(f.facts_id for f in item.facts)) for item in definitions
                        )
                    }
                )
                acquired = replace(acquired, series=definitions)
            return replace(acquired, inventories=(snapshot,))

    request = ObservationRequest(
        ProviderId("no_nve"),
        ("109.42.0",),
        (ProductId("discharge_daily_mean"),),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 1, 2)),
            WindowEndpoint.from_datetime(datetime(2024, 1, 2, 23, 59, 59, 999999)),
        ),
        scope=SeriesScope(provider_ids=("no_nve",), station_ids=("109.42.0",), product_ids=("discharge_daily_mean",)),
    )

    def run():
        return drive(
            request,
            ControlledMetadata(),
            provenance=ObservationProvenance(source="HydAPI", provider_id=ProviderId("no_nve")),
            transport=Observed(),
            cache="reuse",
            store=StoreRoot(tmp_path / "store"),
        )

    first = run()
    assert first.canonical_rows.height == (2 if control == "failure" else 3)
    metadata_snapshots = [
        item
        for item in first.inventories
        if "reconciled" not in item.access and item.access.startswith("HydAPI Series")
    ]
    assert metadata_snapshots and metadata_snapshots[0].acquired_at == metadata.retrieved_at
    settled = [item for item in first.inventories if "reconciled" in item.access]
    assert len(settled) == 1
    assert settled[0].window.start == datetime(2024, 1, 2)
    assert settled[0].window.end == datetime(2024, 1, 2, 23, 59, 59, 999999)
    assert settled[0].completeness == ("complete" if control == "unchanged" else "incomplete")
    assert any("source-inventory:" in evidence for evidence in settled[0].evidence)
    second = run()
    pl_testing.assert_frame_equal(second.canonical_rows, first.canonical_rows)
    assert len(requests) == (4 if control == "unchanged" else 8)
    if control in ("different-facts", "unestablished-metadata-facts"):
        assert not any(issue.severity in ("warning", "error") for issue in first.issues)
