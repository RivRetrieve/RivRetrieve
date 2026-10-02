"""Inventory materialization preserves exact retained source rows, not product claims."""

import json
import lzma
from dataclasses import replace
from datetime import timedelta

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.br_ana.inventory import (
    BRAZILIAN_UNITS,
    materialize_inventory,
    native_table_semantic_digest,
)
from rivretrieve._internal.recordings import read_recording


@pytest.fixture
def recording(retained_evidence_root, tmp_path):
    path = tmp_path / "ac.recording.json"
    path.write_bytes(
        lzma.decompress(
            (retained_evidence_root / "tests/test_data/br_ana_inventory/inventory_UF_AC.recording.json")
            .with_suffix(".json.xz")
            .read_bytes()
        )
    )
    return read_recording(path)


def changed(recording, mutate):
    payload = json.loads(recording.content)
    mutate(payload)
    return replace(recording, content=json.dumps(payload, ensure_ascii=False).encode())


def test_complete_retained_ac_response(recording):
    result = materialize_inventory((recording,), expected_units=("AC",))
    rows = json.loads(recording.content)["items"]
    expected = (
        pl.DataFrame(rows, schema=dict.fromkeys(rows[0], pl.String))
        .with_columns(pl.lit(recording.retrieved_at).cast(pl.Datetime("us", "UTC")).alias("retrieved_at"))
        .sort("codigoestacao")
    )
    assert_frame_equal(result.native.data, expected)
    assert result.native.data.height == 152
    assert "Pluviometrica" in result.native.data["Tipo_Estacao"].to_list()
    (response,) = result.responses
    assert response.request == recording.request
    assert response.sha256 == "0f69fe786751e42a0a0f87cb5f8d3448ca8d18235c291de983701afd67a103ae"
    assert response.retrieved_at == recording.retrieved_at
    assert response.byte_size == 337961
    assert response.row_count == response.distinct_station_count == 152


def test_null_coordinates_and_source_strings_are_retained(recording):
    def mutate(payload):
        payload["items"][0]["Latitude"] = None
        payload["items"][0]["Longitude"] = ""

    altered = changed(recording, mutate)
    result = materialize_inventory((altered,), expected_units=("AC",))
    row = result.native.data.filter(pl.col("codigoestacao") == "771001").row(0, named=True)
    assert row["Latitude"] is None
    assert row["Longitude"] == ""
    assert row["Rio_Nome"] == "N/A"


@pytest.mark.parametrize("conflict", [False, True])
def test_duplicate_identity_is_rejected(recording, conflict):
    def mutate(payload):
        duplicate = dict(payload["items"][0])
        if conflict:
            duplicate["Estacao_Nome"] = "changed"
        payload["items"].append(duplicate)

    with pytest.raises(FatalContractError, match="duplicate"):
        materialize_inventory((changed(recording, mutate),), expected_units=("AC",))


@pytest.mark.parametrize(
    "field,value",
    [("Latitude", 3.0), ("Operando", True), ("codigoestacao", None), ("codigoestacao", ""), ("UF_Estacao", "AM")],
)
def test_invalid_source_value_is_rejected(recording, field, value):
    altered = changed(recording, lambda p: p["items"][0].__setitem__(field, value))
    with pytest.raises(FatalContractError):
        materialize_inventory((altered,), expected_units=("AC",))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["items"][0].pop("Altitude"),
        lambda p: p["items"][0].__setitem__("extra", "x"),
        lambda p: p.__setitem__("code", 503),
        lambda p: p.__setitem__("items", {}),
    ],
)
def test_schema_drift_and_source_failure_are_rejected(recording, mutation):
    with pytest.raises(FatalContractError):
        materialize_inventory((changed(recording, mutation),), expected_units=("AC",))


def test_missing_units_and_repeated_requests_are_rejected(recording):
    with pytest.raises(FatalContractError, match="units"):
        materialize_inventory((recording,))
    with pytest.raises(FatalContractError, match="duplicate"):
        materialize_inventory((recording, recording), expected_units=("AC",))


def test_wrong_request_and_http_failure_are_rejected(recording):
    for altered in (
        replace(recording, status_code=503),
        replace(recording, request=replace(recording.request, parameters={"Unidade Federativa": "AC", "extra": "1"})),
        replace(recording, request=replace(recording.request, url="https://www.ana.gov.br/wrong")),
    ):
        with pytest.raises(FatalContractError):
            materialize_inventory((altered,), expected_units=("AC",))


def test_source_order_does_not_change_native_table(recording):
    reversed_rows = changed(recording, lambda p: p["items"].reverse())
    assert_frame_equal(
        materialize_inventory((recording,), expected_units=("AC",)).native.data,
        materialize_inventory((reversed_rows,), expected_units=("AC",)).native.data,
    )


def test_full_domestic_acquisition(retained_evidence_root, tmp_path):
    recordings = []
    expected_frames = []
    for uf in BRAZILIAN_UNITS:
        path = tmp_path / f"inventory_UF_{uf}.recording.json"
        path.write_bytes(
            lzma.decompress(
                (
                    (retained_evidence_root / "tests/test_data/br_ana_inventory/inventory_UF_AC.recording.json").parent
                    / (path.name + ".xz")
                ).read_bytes()
            )
        )
        recording = read_recording(path)
        recordings.append(recording)
        rows = json.loads(recording.content)["items"]
        expected_frames.append(
            pl.DataFrame(rows, schema=dict.fromkeys(rows[0], pl.String)).with_columns(
                pl.lit(recording.retrieved_at).cast(pl.Datetime("us", "UTC")).alias("retrieved_at")
            )
        )
    result = materialize_inventory(tuple(reversed(recordings)))
    assert_frame_equal(result.native.data, pl.concat(expected_frames).sort("codigoestacao"))
    assert result.native.data.height == 38089
    assert result.native.data.filter(pl.col("Tipo_Estacao") == "Fluviometrica").height == 17334
    assert result.native.data.filter(pl.col("Tipo_Estacao") == "Pluviometrica").height == 20755
    assert tuple(response.uf for response in result.responses) == BRAZILIAN_UNITS
    assert sum(response.row_count for response in result.responses) == 38089
    assert native_table_semantic_digest(result.native) == native_table_semantic_digest(
        materialize_inventory(recordings).native
    )


@pytest.mark.parametrize("value", [None, "", "Fluviométrica", "unknown"])
def test_unestablished_station_type_fails(recording, value):
    altered = changed(recording, lambda p: p["items"][0].__setitem__("Tipo_Estacao", value))
    with pytest.raises(FatalContractError, match="station type"):
        materialize_inventory((altered,), expected_units=("AC",))


def test_recording_digest_tampering_fails(retained_evidence_root, tmp_path):
    document = json.loads(
        lzma.decompress(
            (retained_evidence_root / "tests/test_data/br_ana_inventory/inventory_UF_AC.recording.json")
            .with_suffix(".json.xz")
            .read_bytes()
        )
    )
    document["response"]["sha256"] = "0" * 64
    path = tmp_path / "changed.recording.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        read_recording(path)


def test_duplicate_json_members_fail(recording):
    altered = replace(recording, content=recording.content.replace(b'"status":"OK"', b'"status":"OK","status":"OK"', 1))
    # Publisher uses compact JSON; this must actually instrument the duplicate path.
    assert altered.content != recording.content
    with pytest.raises(FatalContractError, match="duplicate"):
        materialize_inventory((altered,), expected_units=("AC",))


def test_cross_uf_duplicate_identity_fails(recording):
    def mutate(payload):
        for row in payload["items"]:
            row["UF_Estacao"] = "AM"

    other = changed(recording, mutate)
    other = replace(other, request=replace(other.request, parameters={"Unidade Federativa": "AM"}))
    with pytest.raises(FatalContractError, match="duplicate"):
        materialize_inventory((recording, other), expected_units=("AC", "AM"))


def test_basin_overlap_union_is_exact_and_order_independent(recording):
    basin = replace(
        recording,
        retrieved_at=recording.retrieved_at - timedelta(days=1),
        request=replace(recording.request, parameters={"Código da Bacia": 1}),
    )
    left = materialize_inventory((recording, basin), expected_units=("AC",), expected_basins=(1,))
    right = materialize_inventory((basin, recording), expected_units=("AC",), expected_basins=(1,))
    assert_frame_equal(left.native.data, right.native.data)
    assert left.native.data.height == 152
    assert left.native.data["retrieved_at"].min() == basin.retrieved_at
    assert left.native.data["retrieved_at"].max() == basin.retrieved_at
    assert len(left.responses) == 2
    assert sum(response.row_count for response in left.responses) == 304


def test_basin_overlap_conflict_fails(recording):
    basin = changed(recording, lambda p: p["items"][0].__setitem__("Altitude", "changed"))
    basin = replace(basin, request=replace(basin.request, parameters={"Código da Bacia": 1}))
    with pytest.raises(FatalContractError, match="conflict"):
        materialize_inventory((recording, basin), expected_units=("AC",), expected_basins=(1,))


def test_retained_basin9_preserves_foreign_population(retained_evidence_root, tmp_path):
    path = tmp_path / "basin9.recording.json"
    path.write_bytes(
        lzma.decompress(
            (
                (retained_evidence_root / "tests/test_data/br_ana_inventory/inventory_UF_AC.recording.json").parent
                / "population_inventory_basin9.recording.json.xz"
            ).read_bytes()
        )
    )
    recording = read_recording(path)
    result = materialize_inventory((recording,), expected_units=(), expected_basins=(9,))
    rows = json.loads(recording.content)["items"]
    expected = (
        pl.DataFrame(rows, schema=dict.fromkeys(rows[0], pl.String))
        .with_columns(pl.lit(recording.retrieved_at).cast(pl.Datetime("us", "UTC")).alias("retrieved_at"))
        .sort("codigoestacao")
    )
    assert_frame_equal(result.native.data, expected)
    assert result.native.data.height == 1104
    assert result.native.data.filter(~pl.col("UF_Estacao").is_in(BRAZILIAN_UNITS)).height == 1103
    assert result.responses[0].basin == 9
    assert result.responses[0].uf is None


def test_full_acquired_population_union(retained_evidence_root, tmp_path):
    names: list[str] = [f"inventory_UF_{uf}.recording.json" for uf in BRAZILIAN_UNITS]
    names += [f"population_inventory_basin{basin}.recording.json" for basin in range(1, 10)]
    recordings = []
    expected_rows = {}
    earliest = {}
    for name in names:
        path = tmp_path / name
        path.write_bytes(
            lzma.decompress(
                (
                    (retained_evidence_root / "tests/test_data/br_ana_inventory/inventory_UF_AC.recording.json").parent
                    / (name + ".xz")
                ).read_bytes()
            )
        )
        recording = read_recording(path)
        recordings.append(recording)
        for row in json.loads(recording.content)["items"]:
            identity = row["codigoestacao"]
            if identity in expected_rows:
                assert expected_rows[identity] == row
                earliest[identity] = min(earliest[identity], recording.retrieved_at)
            else:
                expected_rows[identity] = row
                earliest[identity] = recording.retrieved_at
    result = materialize_inventory(tuple(reversed(recordings)), expected_basins=tuple(range(1, 10)))
    ids = sorted(expected_rows)
    rows = [expected_rows[identity] for identity in ids]
    expected = pl.DataFrame(rows, schema=dict.fromkeys(rows[0], pl.String)).with_columns(
        pl.Series("retrieved_at", [earliest[identity] for identity in ids], dtype=pl.Datetime("us", "UTC"))
    )
    assert_frame_equal(result.native.data, expected)
    assert result.native.data.height == 40747
    assert result.native.data.filter(pl.col("Tipo_Estacao") == "Fluviometrica").height == 17914
    assert result.native.data.filter(pl.col("Tipo_Estacao") == "Pluviometrica").height == 22833
    assert len(result.responses) == 36
    assert sum(response.row_count for response in result.responses) == 78836
