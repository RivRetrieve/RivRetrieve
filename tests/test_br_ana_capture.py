"""Retained ANA capture identities bind exact offline native materialization."""

import lzma
from datetime import timedelta
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal
from pydantic import ValidationError

from rivretrieve._internal.catalogues.native import NativeTable, read_native_table
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.br_ana.capture import (
    materialize_captured_native_table,
    read_capture_record,
    verify_materialization,
    verify_native_identity,
)
from rivretrieve._internal.recordings import read_recording

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "tests/test_data/br_ana_inventory/capture.json"


@pytest.fixture(scope="module")
def capture():
    return read_capture_record(CAPTURE)


@pytest.fixture(scope="module")
def recordings(capture, tmp_path_factory):
    directory = tmp_path_factory.mktemp("ana-capture-recordings")
    result = []
    for index, response in enumerate(capture.responses):
        path = directory / f"{index}.recording.json"
        path.write_bytes(lzma.decompress((ROOT / response.repository_path).read_bytes()))
        result.append(read_recording(path))
    return tuple(result)


@pytest.fixture(scope="module")
def native(capture):
    return read_native_table(ROOT / capture.native_table.repository_path)


def test_capture_reproduces_committed_native_exactly(capture, native):
    rebuilt = materialize_captured_native_table(capture, ROOT)
    assert_frame_equal(rebuilt.data, native.data)
    assert rebuilt.data.height == 40747
    assert rebuilt.data.filter(pl.col("Tipo_Estacao") == "Fluviometrica").height == 17914
    assert rebuilt.data.filter(pl.col("Tipo_Estacao") == "Pluviometrica").height == 22833
    assert len(capture.responses) == 36
    assert sum(response.row_count for response in capture.responses) == 78836
    verify_native_identity(capture, (ROOT / capture.native_table.repository_path).read_bytes(), rebuilt)


@pytest.mark.parametrize(
    "field",
    [
        "requested_url",
        "parameters",
        "retrieved_at",
        "media_type",
        "payload_sha256",
        "byte_size",
        "row_count",
        "distinct_station_count",
    ],
)
def test_response_attestation_mutations_fail(capture, recordings, field):
    first = capture.responses[0]
    values = {
        "requested_url": first.requested_url + "/changed",
        "parameters": {"Unidade Federativa": "AM"},
        "retrieved_at": first.retrieved_at + timedelta(microseconds=1),
        "media_type": "text/plain",
        "payload_sha256": "0" * 64,
        "byte_size": first.byte_size + 1,
        "row_count": first.row_count + 1,
        "distinct_station_count": first.distinct_station_count + 1,
    }
    altered = capture.model_copy(
        update={"responses": (first.model_copy(update={field: values[field]}), *capture.responses[1:])}
    )
    with pytest.raises(FatalContractError, match="identity mismatch|count mismatch"):
        verify_materialization(altered, recordings)


def test_retained_compressed_bytes_are_verified_before_decoding(capture, tmp_path):
    path = tmp_path / capture.responses[0].repository_path
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not the attested compressed recording")
    with pytest.raises(FatalContractError, match="retained recording identity mismatch"):
        materialize_captured_native_table(capture.model_copy(update={"supporting_evidence": ()}), tmp_path)


def test_missing_recording_is_not_empty_population(capture, recordings):
    with pytest.raises(FatalContractError, match="response count mismatch"):
        verify_materialization(capture, recordings[:-1])


def test_population_counts_are_attested(capture, recordings):
    altered = capture.model_copy(update={"distinct_station_count": capture.distinct_station_count + 1})
    with pytest.raises(FatalContractError, match="population accounting mismatch"):
        verify_materialization(altered, recordings)


def test_fresh_materialization_semantic_digest_is_attested(capture, recordings):
    semantic = capture.native_table.semantic_digest.model_copy(update={"sha256": "0" * 64})
    identity = capture.native_table.model_copy(update={"semantic_digest": semantic})
    altered = capture.model_copy(update={"native_table": identity})
    with pytest.raises(FatalContractError, match="native semantic identity mismatch"):
        verify_materialization(altered, recordings)


def test_native_byte_and_semantic_identity_are_independent(capture, native):
    content = (ROOT / capture.native_table.repository_path).read_bytes()
    with pytest.raises(FatalContractError, match="native byte identity mismatch"):
        verify_native_identity(capture, content + b"changed", native)
    altered = NativeTable(native.data.with_columns(pl.lit("changed").alias("Estacao_Nome")))
    with pytest.raises(FatalContractError, match="native semantic identity mismatch"):
        verify_native_identity(capture, content, altered)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.__setitem__("extra", "unexpected"),
        lambda value: value["responses"][0].__setitem__("repository_path", "../outside.recording.json.xz"),
        lambda value: value["responses"][0].__setitem__("payload_sha256", "invalid"),
        lambda value: value["responses"][0].__setitem__("retrieved_at", "2026-09-16T00:00:00"),
    ],
)
def test_persisted_capture_rejects_invalid_shape(capture, tmp_path, mutation):
    import json

    value = capture.model_dump(mode="json")
    mutation(value)
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValidationError):
        read_capture_record(path)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["responses"].pop(),
        lambda value: value["responses"][0].__setitem__("parameters", {"Unidade Federativa": "AM"}),
        lambda value: value["responses"][-1].__setitem__("parameters", {"Código da Bacia": "9"}),
        lambda value: value["responses"][0].pop("recording_byte_size"),
        lambda value: value.__setitem__("response_row_count", value["response_row_count"] + 1),
        lambda value: value.__setitem__("fluviometric_station_count", value["fluviometric_station_count"] + 1),
    ],
)
def test_persisted_capture_requires_complete_population_accounting(capture, tmp_path, mutation):
    import json

    value = capture.model_dump(mode="json")
    mutation(value)
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValidationError):
        read_capture_record(path)


def test_supporting_acquisition_evidence_digest_is_verified(capture, tmp_path):
    assert capture.supporting_evidence
    path = tmp_path / capture.supporting_evidence[0].repository_path
    path.parent.mkdir(parents=True)
    path.write_bytes(b"changed acquisition accounting")
    with pytest.raises(FatalContractError, match="supporting acquisition evidence identity mismatch"):
        materialize_captured_native_table(capture, tmp_path)


def test_original_failed_uf_attempts_remain_distinct_from_successful_retries(capture):
    import json

    first_path = ROOT / "maintenance/catalogue/br_ana/inventory/inventory-ufs.json.results.json"
    retry_path = ROOT / "maintenance/catalogue/br_ana/inventory/inventory-ufs-retry.json.results.json"
    first = json.loads(first_path.read_bytes())
    retry = json.loads(retry_path.read_bytes())
    failed = {item["name"] for item in first if "failure" in item}
    assert len(first) == 27 and len(failed) == 7
    assert {item["http_status"] for item in first if "failure" in item} == {503}
    assert {item["name"] for item in retry} == failed
    assert {item["http_status"] for item in retry} == {200}
    paths = {item.repository_path for item in capture.supporting_evidence}
    assert str(first_path.relative_to(ROOT)) in paths
    assert str(retry_path.relative_to(ROOT)) in paths
