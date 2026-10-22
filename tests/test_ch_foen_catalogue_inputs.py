"""Synthetic selected originals exercise the composed offline input boundary."""

import hashlib
import json
from datetime import UTC, datetime

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionRecord,
    AuthoredDeclarationInput,
    CodeReference,
    FactBinding,
    RecordingReference,
    RetainedInputReceipt,
    RetainedInputReference,
    SourceStatement,
)
from rivretrieve._internal.catalogues.native import RetrievedAt, write_native_table
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ch_foen import generate_catalogue, station_metadata
from rivretrieve._internal.providers.ch_foen.station_metadata import StationMetadataSources


@pytest.fixture
def selected_sources(tmp_path, monkeypatch):
    instant = datetime(2026, 1, 1, tzinfo=UTC)

    def payload(route, rows):
        return {"data": {"water": {"observations": {route: rows}}}}

    stations = payload(
        "stations",
        [{"no": "001", "latitude": 46.0, "longitude": 7.0}, {"no": "002", "latitude": None, "longitude": None}],
    )
    archive = payload(
        "data_1day_mean",
        [
            {
                "station": {"no": "001", "id": "embedded"},
                "parameterName": "Q",
                "tsName": "Q.raw",
                "unitName": "cubic metres",
                "unitSymbol": "m³/s",
                "value": None,
            }
        ],
    )
    recent = payload(
        "data_live", [{"stationNo": number, "parameterName": "Q", "value": None} for number in ("001", "002")]
    )
    page = b'<h1>Station <small>001</small></h1><table class="sensors-table"><thead><tr><th><div>Discharge</div><div class="opacity-75">l/s</div></th></tr></thead></table>'
    bodies = {
        "stations": json.dumps(stations).encode(),
        "archive": json.dumps(archive).encode(),
        "recent": json.dumps(recent).encode(),
        "page": page,
        "redirect": b"not a station page",
        "terms": b"Synthetic licence",
    }
    captures = {}
    members = []
    for name, body in bodies.items():
        path = name + ".body"
        (tmp_path / path).write_bytes(body)
        url = (
            "https://www.hydrodaten.admin.ch/en/seen-und-fluesse/stations/001"
            if name == "page"
            else "https://example.org/" + name
        )
        reference = RecordingReference(
            recording_id=name,
            repository_path=path,
            source_url=url,
            retrieved_at=instant,
            media_type="application/octet-stream",
            sha256=hashlib.sha256(body).hexdigest(),
        )
        captures[name] = {"body": path, "recording": reference.model_dump(mode="json")}
        members.append(
            RetainedInputReference(
                consumer_path=path,
                archive_repository="https://github.com/RivRetrieve/verification-evidence",
                archive_revision="a" * 40,
                collection_id="synthetic",
                manifest_sha256="b" * 64,
                artifact_id=name,
                sha256=reference.sha256,
                byte_size=len(body),
                role="publisher_original",
            )
        )
    native = generate_catalogue.station_native_table(stations, retrieved_at=RetrievedAt(instant))
    write_native_table(native, tmp_path / "native.parquet")
    native_bytes = (tmp_path / "native.parquet").read_bytes()
    members.append(
        members[0].model_copy(
            update={
                "consumer_path": "native.parquet",
                "artifact_id": "native",
                "role": "derived_input",
                "sha256": hashlib.sha256(native_bytes).hexdigest(),
                "byte_size": len(native_bytes),
            }
        )
    )
    facts_by_capture = {
        "stations": ("source.station.native_identity", "source.station.native_geometry"),
        "archive": ("source.station_product.source_associations", "source.product.native_physics"),
        "terms": ("source.station.documented_crs", "source.provider.license"),
    }
    acquisitions = tuple(
        AcquisitionRecord(
            acquisition_id=name,
            method="http_request",
            instant_type="retrieval",
            description="Synthetic selected original",
            requested_from=(capture["recording"]["source_url"],),
            retrieved_at_start=instant,
            recording_ids=(name,),
        )
        for name, capture in captures.items()
        if name != "redirect"
    )
    selection = {
        "native_table": "native.parquet",
        "native_revision": "f" * 40,
        "checked_on": "2026-01-02",
        "captures": [
            {**captures["stations"], "kind": "stations", "outcome": "rows"},
            {**captures["archive"], "kind": "archive", "outcome": "rows", "routes": ["data_1day_mean"]},
            {**captures["page"], "kind": "page", "outcome": "station_page"},
            {**captures["redirect"], "kind": "page", "outcome": "redirected"},
        ],
        "prior_live": captures["recent"],
        "prior_support": [captures["terms"]],
        "publication_acquisitions": [item.model_dump(mode="json") for item in acquisitions],
        "source_bindings": [
            FactBinding(fact_group=name, facts=facts, source_id="ch_foen", acquisition_id=name).model_dump(mode="json")
            for name, facts in facts_by_capture.items()
        ],
        "statements": [
            SourceStatement(
                kind="license", exact_text="Synthetic licence", recording_id="terms", fact="source.provider.license"
            ).model_dump(mode="json")
        ],
    }
    selection_bytes = json.dumps(selection).encode()
    (tmp_path / "selection.json").write_bytes(selection_bytes)
    declaration = AuthoredDeclarationInput(
        consumer_path="selection.json",
        declaration=CodeReference(
            repository="https://github.com/RivRetrieve/verification-evidence",
            revision="c" * 40,
            repository_path="synthetic/selection.json",
        ),
        sha256=hashlib.sha256(selection_bytes).hexdigest(),
        byte_size=len(selection_bytes),
    )
    receipt = RetainedInputReceipt(
        schema_version=3,
        archive_code_revision="c" * 40,
        code_revision="d" * 40,
        declaration_revision="d" * 40,
        inputs=tuple(members),
        declaration_inputs=(declaration,),
    )
    baseline_recording = RecordingReference(
        recording_id="baseline-page",
        repository_path="baseline/page",
        source_url="https://example.org/baseline",
        retrieved_at=instant,
        media_type="text/html",
        sha256="e" * 64,
    )
    baseline = StationMetadataSources(
        directory_body=b'<tr class="station-row discharge_001" data-key="001" data-name="Synthetic" data-hydro-body=""><td><a href="/en/seen-und-fluesse/stations/001">Synthetic</a></td></tr>',
        directory_reference=baseline_recording,
        station_pages={},
        page_recordings=(baseline_recording,),
        member_digests={},
    )
    monkeypatch.setattr(station_metadata, "read_station_metadata_sources", lambda *args, **kwargs: baseline)
    return tmp_path, receipt, native


def test_selected_originals_preserve_null_associations_and_live_unit_scope(selected_sources):
    root, receipt, native = selected_sources
    result = generate_catalogue.read_catalogue_sources(root, selection_path="selection.json", input_receipt=receipt)
    assert_frame_equal(result.native_table.data, native.data)
    assert result.associations.select("station_no", "route", "unitSymbol").sort("station_no", "route").rows() == [
        ("001", "data_1day_mean", "m³/s"),
        ("001", "data_live", "l/s"),
        ("002", "data_live", None),
    ]
    ids = {item.recording.recording_id for source in result.provenance.source_records for item in source.evidence}
    assert "redirect" not in ids
    assert "001" in result.native_table.data["no"].to_list()


def test_native_identity_does_not_change_with_archive_execution_revision(selected_sources):
    root, receipt, _ = selected_sources
    first = generate_catalogue.read_catalogue_sources(root, selection_path="selection.json", input_receipt=receipt)
    current = receipt.model_copy(
        update={
            "archive_code_revision": "9" * 40,
            "inputs": tuple(item.model_copy(update={"archive_revision": "9" * 40}) for item in receipt.inputs),
        }
    )
    second = generate_catalogue.read_catalogue_sources(root, selection_path="selection.json", input_receipt=current)
    assert first.provenance.native_table == second.provenance.native_table
    assert first.provenance.native_table.revision == "f" * 40
    assert current.archive_code_revision == "9" * 40
    assert {item.archive_revision for item in current.inputs} == {"9" * 40}


def test_changed_native_member_cannot_reach_parsing(selected_sources):
    root, receipt, _ = selected_sources
    (root / "native.parquet").write_bytes(b"changed")
    with pytest.raises(FatalContractError):
        generate_catalogue.read_catalogue_sources(root, selection_path="selection.json", input_receipt=receipt)


def test_valid_native_bytes_must_match_selected_station_snapshot(selected_sources):
    root, receipt, native = selected_sources
    changed = native.data.with_columns(
        pl.when(pl.col("no") == "001").then(pl.lit(45.0)).otherwise(pl.col("latitude")).alias("latitude")
    )
    changed.write_parquet(root / "native.parquet")
    body = (root / "native.parquet").read_bytes()
    receipt = receipt.model_copy(
        update={
            "inputs": tuple(
                item.model_copy(update={"sha256": hashlib.sha256(body).hexdigest(), "byte_size": len(body)})
                if item.consumer_path == "native.parquet"
                else item
                for item in receipt.inputs
            )
        }
    )
    with pytest.raises(FatalContractError, match="differs from original station snapshot"):
        generate_catalogue.read_catalogue_sources(root, selection_path="selection.json", input_receipt=receipt)


def test_skipped_page_cannot_support_a_published_acquisition(selected_sources):
    root, receipt, _ = selected_sources
    selection = json.loads((root / "selection.json").read_bytes())
    selection["publication_acquisitions"][0]["recording_ids"].append("redirect")
    body = json.dumps(selection).encode()
    (root / "selection.json").write_bytes(body)
    declaration = receipt.declaration_inputs[0].model_copy(
        update={"sha256": hashlib.sha256(body).hexdigest(), "byte_size": len(body)}
    )
    receipt = receipt.model_copy(update={"declaration_inputs": (declaration,)})
    with pytest.raises(ValueError, match="issuer-local recordings"):
        generate_catalogue.read_catalogue_sources(root, selection_path="selection.json", input_receipt=receipt)
