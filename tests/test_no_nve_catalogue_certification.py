"""Refusal and secret-boundary proofs for NVE catalogue certification."""

from __future__ import annotations

import copy
import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

from rivretrieve._internal.catalogue_origins import (
    ORIGIN_GATE_ENROLLED_PROVIDERS,
    Authored,
    AuthoredValue,
    Field,
    NativeColumn,
    enforce_catalogue_origins,
)
from rivretrieve._internal.catalogues.native import NativeTable, read_native_table
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.no_nve import generate_catalogue
from rivretrieve._internal.providers.no_nve.origins import STATION_CATALOGUE_ORIGINS
from rivretrieve._internal.transport import AuthenticatedTransport, CredentialHeader, HttpClient, TransportFailure

_ROOT = Path(__file__).parents[1]
_DATA = Path(__file__).parent / "test_data"
_NATIVE = _ROOT / "src/rivretrieve/_internal/providers/no_nve/catalogue/native.parquet"
_CAPTURE = _DATA / "no_nve_station_catalogue_capture.json"
_SENTINEL = "CATALOGUE-CREDENTIAL-SENTINEL-NOT-REAL"


def _active_document() -> dict[str, object]:
    return json.loads((_DATA / "no_nve_stations_active_1.json").read_text(encoding="utf-8"))


def _encoded(document: object) -> bytes:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()


def test_no_nve_is_enrolled_and_cli_has_no_value_bearing_key_argument(capsys: pytest.CaptureFixture[str]) -> None:
    assert ProviderId("no_nve") in ORIGIN_GATE_ENROLLED_PROVIDERS
    with pytest.raises(SystemExit) as caught:
        generate_catalogue.main(["--help"])
    assert caught.value.code == 0
    output = capsys.readouterr().out
    assert "--api-key" not in output
    assert "NVE_API_KEY" not in output


@pytest.mark.parametrize(
    "mutation",
    ["missing_series", "null_series", "malformed_member", "missing_coordinate", "duplicate_id", "item_count"],
)
def test_complete_response_shape_refuses_every_previous_silent_loss(mutation: str) -> None:
    document = _active_document()
    rows_value = document["data"]
    assert isinstance(rows_value, list)
    rows = cast("list[dict[str, object]]", rows_value)
    row = rows[0]
    if mutation == "missing_series":
        del row["seriesList"]
    elif mutation == "null_series":
        row["seriesList"] = None
    elif mutation == "malformed_member":
        row["seriesList"] = ["not-an-object"]
    elif mutation == "missing_coordinate":
        row["latitude"] = None
    elif mutation == "duplicate_id":
        rows[1]["stationId"] = row["stationId"]
    else:
        document["itemCount"] = len(rows) - 1
    with pytest.raises(FatalContractError):
        generate_catalogue._parse_station_response(_encoded(document), generate_catalogue.StationActivityFilter.ALL)


def test_empty_complete_series_list_establishes_unavailability() -> None:
    native = read_native_table(_NATIVE)
    row = native.data.head(1).with_columns(pl.lit([]).cast(native.data.schema["seriesList"]).alias("seriesList"))
    products = generate_catalogue.build_station_products(NativeTable(row))
    assert set(products["availability"].cast(str)) == {"unavailable"}


def test_capture_attestation_mutations_refuse_before_semantic_comparison(tmp_path: Path) -> None:
    document = json.loads(_CAPTURE.read_text(encoding="utf-8"))
    document["responses"][0]["accepted_row_count"] -= 1
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    capture = generate_catalogue.read_capture_record(path)
    with pytest.raises(FatalContractError, match="counts mismatch"):
        generate_catalogue.materialize_captured_native_table(capture, _ROOT)


def _copy_capture_responses(root: Path, capture: generate_catalogue.StationCatalogueCapture) -> None:
    for response in capture.responses:
        target = root / response.repository_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_ROOT / response.repository_path, target)


def test_captured_raw_response_substitution_refuses(tmp_path: Path) -> None:
    capture = generate_catalogue.read_capture_record(_CAPTURE)
    _copy_capture_responses(tmp_path, capture)
    target = tmp_path / capture.responses[0].repository_path
    body = bytearray(target.read_bytes())
    body[-2] ^= 1
    target.write_bytes(body)

    with pytest.raises(FatalContractError, match="captured response identity mismatch"):
        generate_catalogue.materialize_captured_native_table(capture, tmp_path)


def test_semantic_and_raw_native_attestation_mutations_refuse_without_output(
    tmp_path: Path,
) -> None:
    capture = generate_catalogue.read_capture_record(_CAPTURE)
    for field, message in (
        ("semantic_sha256", "semantic digest mismatch"),
        ("sha256", "raw identity mismatch"),
    ):
        mutated = replace(capture, native_table=replace(capture.native_table, **{field: "0" * 64}))
        record = tmp_path / f"{field}.json"
        generate_catalogue.write_capture_record(mutated, record)
        output = tmp_path / f"{field}.parquet"
        with pytest.raises(FatalContractError, match=message):
            generate_catalogue.main(
                [
                    "--materialize-record",
                    str(record),
                    "--native-out",
                    str(output),
                    "--repository-root",
                    str(_ROOT),
                ]
            )
        assert not output.exists()
        assert not output.with_name(f".{output.name}.candidate").exists()


def test_origin_gate_refuses_real_canonical_row_deletion_and_non_null_mutation() -> None:
    native = read_native_table(_NATIVE)
    stations = generate_catalogue.build_stations(native)
    station_id = "1.10.0"
    mutations = (
        stations.filter(pl.col("station_id") != station_id),
        stations.with_columns(
            pl.when(pl.col("station_id") == station_id).then(0.0).otherwise(pl.col("longitude")).alias("longitude")
        ),
    )
    for mutated in mutations:
        with pytest.raises(FatalContractError):
            enforce_catalogue_origins(ProviderId("no_nve"), STATION_CATALOGUE_ORIGINS, native, mutated)


def test_full_response_duplicate_series_member_refuses_before_availability() -> None:
    document = _active_document()
    rows = cast("list[dict[str, object]]", document["data"])
    row = next(item for item in rows if isinstance(item["seriesList"], list) and item["seriesList"])
    series = cast("list[dict[str, object]]", row["seriesList"])
    series.append(copy.deepcopy(series[0]))

    with pytest.raises(FatalContractError, match="duplicate series member"):
        generate_catalogue._parse_station_response(_encoded(document), generate_catalogue.StationActivityFilter.ALL)


def test_non_null_wrong_field_origin_refuses_on_the_real_native_build() -> None:
    native = read_native_table(_NATIVE)
    contradicted = dict(STATION_CATALOGUE_ORIGINS)
    contradicted["longitude"] = Field(NativeColumn("latitude"))

    with pytest.raises(FatalContractError, match="does not reproduce the declared native field"):
        generate_catalogue.build_catalogue(native, contradicted)


def test_provider_identifier_has_a_truthful_authored_origin() -> None:
    native = read_native_table(_NATIVE)
    origin = STATION_CATALOGUE_ORIGINS["provider_id"]
    assert origin == Authored(AuthoredValue("no_nve"))
    contradicted = dict(STATION_CATALOGUE_ORIGINS)
    contradicted["provider_id"] = Authored(AuthoredValue("other_provider"))

    with pytest.raises(FatalContractError, match="does not match authored value"):
        generate_catalogue.build_catalogue(native, contradicted)


def test_each_real_origin_declaration_is_required_and_mutations_refuse() -> None:
    native = read_native_table(_NATIVE)
    stations = generate_catalogue.build_stations(native)
    for column in STATION_CATALOGUE_ORIGINS:
        missing = dict(STATION_CATALOGUE_ORIGINS)
        del missing[column]
        with pytest.raises(FatalContractError):
            enforce_catalogue_origins(ProviderId("no_nve"), missing, native, stations)
    absent = dict(STATION_CATALOGUE_ORIGINS)
    absent["longitude"] = Field(NativeColumn("notAcquired"))
    with pytest.raises(FatalContractError, match="does not exist"):
        enforce_catalogue_origins(ProviderId("no_nve"), absent, native, stations)
    mutated_stations = stations.with_columns(
        pl.when(pl.col("station_id") == stations["station_id"].item(0))
        .then(None)
        .otherwise(pl.col("longitude"))
        .alias("longitude")
    )
    with pytest.raises(FatalContractError, match="canonical value is null"):
        enforce_catalogue_origins(ProviderId("no_nve"), STATION_CATALOGUE_ORIGINS, native, mutated_stations)


def test_secret_echo_is_rejected_at_the_real_transport_boundary_without_files(tmp_path: Path) -> None:
    def echo_sender(request: Any, timeout_seconds: float) -> tuple[bytes, int, str]:
        del timeout_seconds
        headers = request.headers
        return headers["X-API-Key"].encode(), 200, "application/json"

    transport = AuthenticatedTransport(
        HttpClient(sender=echo_sender, sleeper=lambda _: None),
        (CredentialHeader("X-API-Key", _SENTINEL, ("https://hydapi.nve.no",)),),
    )
    with pytest.raises(TransportFailure) as caught:
        generate_catalogue.capture_station_catalogue(transport, tmp_path, "tests/test_data")
    assert _SENTINEL not in str(caught.value)
    assert _SENTINEL not in repr(caught.value)
    assert list(tmp_path.iterdir()) == []
