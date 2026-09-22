"""Inventory materialization : RecordingEnvelope* → InventoryMaterialization.

Source strings and nulls remain unchanged. Selected UF and basin recordings
describe their acquired population, not guaranteed source completeness or
product availability.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import cast

import polars as pl

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.native import RETRIEVED_AT_DTYPE, NativeTable
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.br_ana.config import BrAnaDailySourceCoordinates, BrAnaSourceCoordinates, config
from rivretrieve._internal.providers.br_ana.series import describe_series
from rivretrieve._internal.recordings import RecordedRequest, RecordingEnvelope
from rivretrieve._internal.source_series import SourceSeries
from rivretrieve._internal.transport import HttpMethod

INVENTORY_URL = "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroInventarioEstacoes/v1"
BRAZILIAN_UNITS = (
    "AC",
    "AL",
    "AM",
    "AP",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MG",
    "MS",
    "MT",
    "PA",
    "PB",
    "PE",
    "PI",
    "PR",
    "RJ",
    "RN",
    "RO",
    "RR",
    "RS",
    "SC",
    "SE",
    "SP",
    "TO",
)
SOURCE_FIELDS = (
    "Altitude",
    "Area_Drenagem",
    "Bacia_Nome",
    "Codigo_Adicional",
    "Codigo_Operadora_Unidade_UF",
    "Data_Periodo_Climatologica_Fim",
    "Data_Periodo_Climatologica_Inicio",
    "Data_Periodo_Desc_Liquida_Fim",
    "Data_Periodo_Desc_liquida_Inicio",
    "Data_Periodo_Escala_Fim",
    "Data_Periodo_Escala_Inicio",
    "Data_Periodo_Piezometria_Fim",
    "Data_Periodo_Piezometria_Inicio",
    "Data_Periodo_Pluviometro_Fim",
    "Data_Periodo_Pluviometro_Inicio",
    "Data_Periodo_Qual_Agua_Fim",
    "Data_Periodo_Qual_Agua_Inicio",
    "Data_Periodo_Registrador_Chuva_Fim",
    "Data_Periodo_Registrador_Chuva_Inicio",
    "Data_Periodo_Registrador_Nivel_Fim",
    "Data_Periodo_Registrador_Nivel_Inicio",
    "Data_Periodo_Sedimento_Inicio",
    "Data_Periodo_Sedimento_fim",
    "Data_Periodo_Tanque_Evapo_Fim",
    "Data_Periodo_Tanque_Evapo_Inicio",
    "Data_Periodo_Telemetrica_Fim",
    "Data_Periodo_Telemetrica_Inicio",
    "Data_Ultima_Atualizacao",
    "Estacao_Nome",
    "Latitude",
    "Longitude",
    "Municipio_Codigo",
    "Municipio_Nome",
    "Operadora_Codigo",
    "Operadora_Sigla",
    "Operadora_Sub_Unidade_UF",
    "Operando",
    "Responsavel_Codigo",
    "Responsavel_Sigla",
    "Responsavel_Unidade_UF",
    "Rio_Codigo",
    "Rio_Nome",
    "Sub_Bacia_Codigo",
    "Sub_Bacia_Nome",
    "Tipo_Estacao",
    "Tipo_Estacao_Climatologica",
    "Tipo_Estacao_Desc_Liquida",
    "Tipo_Estacao_Escala",
    "Tipo_Estacao_Piezometria",
    "Tipo_Estacao_Pluviometro",
    "Tipo_Estacao_Qual_Agua",
    "Tipo_Estacao_Registrador_Chuva",
    "Tipo_Estacao_Registrador_Nivel",
    "Tipo_Estacao_Sedimentos",
    "Tipo_Estacao_Tanque_evapo",
    "Tipo_Estacao_Telemetrica",
    "Tipo_Rede_Basica",
    "Tipo_Rede_Captacao",
    "Tipo_Rede_Classe_Vazao",
    "Tipo_Rede_Curso_Dagua",
    "Tipo_Rede_Energetica",
    "Tipo_Rede_Estrategica",
    "Tipo_Rede_Navegacao",
    "Tipo_Rede_Qual_Agua",
    "Tipo_Rede_Sedimentos",
    "UF_Estacao",
    "UF_Nome_Estacao",
    "codigobacia",
    "codigoestacao",
)


@dataclass(frozen=True, slots=True)
class InventoryResponse:
    uf: str | None
    request: RecordedRequest
    retrieved_at: datetime
    byte_size: int
    sha256: str
    row_count: int
    distinct_station_count: int
    basin: int | None = None


@dataclass(frozen=True, slots=True)
class InventoryMaterialization:
    native: NativeTable
    responses: tuple[InventoryResponse, ...]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise FatalContractError("br_ana inventory contains a duplicate JSON member")
        result[key] = value
    return result


def _source_rows(recording: RecordingEnvelope, uf: str | None, basin: int | None) -> list[dict[str, str | None]]:
    try:
        payload = json.loads(recording.content, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeDecodeError) as exc:
        raise FatalContractError("br_ana inventory response is not valid JSON") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"status", "code", "message", "items"}
        or type(payload["code"]) is not int
        or payload["code"] != 200
        or payload["status"] != "OK"
        or payload["message"] != "Sucesso"
        or not isinstance(payload["items"], list)
    ):
        raise FatalContractError("br_ana inventory response envelope is invalid or unsuccessful")
    rows = payload["items"]
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(SOURCE_FIELDS):
            raise FatalContractError("br_ana inventory source columns changed")
        if any(value is not None and not isinstance(value, str) for value in row.values()):
            raise FatalContractError("br_ana inventory source values must be strings or null")
        if not row["codigoestacao"] or row["codigoestacao"].strip() != row["codigoestacao"]:
            raise FatalContractError(
                "br_ana inventory station identity must be nonblank without surrounding whitespace"
            )
        if uf is not None and row["UF_Estacao"] != uf:
            raise FatalContractError("br_ana inventory native UF differs from requested UF")
        if basin is not None and row["codigobacia"] != str(basin):
            raise FatalContractError("br_ana inventory native basin differs from requested basin")
        if row["Tipo_Estacao"] not in {"Fluviometrica", "Pluviometrica"}:
            raise FatalContractError("br_ana inventory station type is unestablished")
    return cast("list[dict[str, str | None]]", rows)


def materialize_inventory(
    recordings: Sequence[RecordingEnvelope],
    *,
    expected_units: tuple[str, ...] = BRAZILIAN_UNITS,
    expected_basins: tuple[int, ...] = (),
) -> InventoryMaterialization:
    """Union exact acquired rows, preserving identical overlap and rejecting conflicts.

    The explicit UF/basin selection describes acquisition scope, not a claim of
    universal source completeness. Repeated identities within one response fail.
    Across distinct requests only identical source rows collapse, with the earliest
    acquisition instant. Every response identity and pre-union count remains.
    """
    if len(set(expected_units)) != len(expected_units) or not set(expected_units) <= set(BRAZILIAN_UNITS):
        raise FatalContractError("br_ana inventory expected units must be distinct Brazilian UFs")
    if len(set(expected_basins)) != len(expected_basins) or any(
        type(basin) is not int or not 1 <= basin <= 9 for basin in expected_basins
    ):
        raise FatalContractError("br_ana inventory expected basins must be distinct codes 1 through 9")
    if not expected_units and not expected_basins:
        raise FatalContractError("br_ana inventory requires expected units or basins")
    seen_units: set[str] = set()
    seen_basins: set[int] = set()
    union: dict[str, dict[str, str | None]] = {}
    instants: dict[str, datetime] = {}
    responses: list[InventoryResponse] = []
    for recording in recordings:
        request = recording.request
        parameters = request.parameters
        if (
            request.method != HttpMethod.GET
            or request.url != INVENTORY_URL
            or request.body is not None
            or parameters is None
        ):
            raise FatalContractError("br_ana inventory requires an exact UF or basin inventory request")
        uf: str | None = None
        basin: int | None = None
        if (
            set(parameters) == {"Unidade Federativa"}
            and isinstance(parameters["Unidade Federativa"], str)
            and parameters["Unidade Federativa"] in expected_units
        ):
            uf = parameters["Unidade Federativa"]
            if uf in seen_units:
                raise FatalContractError("br_ana inventory contains duplicate UF requests")
            seen_units.add(uf)
        elif (
            set(parameters) == {"Código da Bacia"}
            and type(parameters["Código da Bacia"]) is int
            and parameters["Código da Bacia"] in expected_basins
        ):
            basin = parameters["Código da Bacia"]
            if basin in seen_basins:
                raise FatalContractError("br_ana inventory contains duplicate basin requests")
            seen_basins.add(basin)
        else:
            raise FatalContractError("br_ana inventory requires an exact expected UF or basin request")
        if recording.status_code != 200:
            raise FatalContractError("br_ana inventory HTTP request was unsuccessful")
        rows = _source_rows(recording, uf, basin)
        response_ids: set[str] = set()
        for row in rows:
            station_id = cast("str", row["codigoestacao"])
            if station_id in response_ids:
                raise FatalContractError(f"br_ana inventory duplicate station identity: {station_id}")
            response_ids.add(station_id)
            if station_id in union:
                if union[station_id] != row:
                    raise FatalContractError(f"br_ana inventory duplicate station conflict: {station_id}")
                instants[station_id] = min(instants[station_id], recording.retrieved_at)
            else:
                union[station_id] = row
                instants[station_id] = recording.retrieved_at
        responses.append(
            InventoryResponse(
                uf,
                request,
                recording.retrieved_at,
                len(recording.content),
                recording.sha256,
                len(rows),
                len(response_ids),
                basin,
            )
        )
    if seen_units != set(expected_units) or seen_basins != set(expected_basins):
        raise FatalContractError("br_ana inventory recordings do not cover expected units and basins")
    ids = sorted(union)
    data = pl.DataFrame([union[station_id] for station_id in ids], schema=dict.fromkeys(SOURCE_FIELDS, pl.String))
    data = data.with_columns(
        pl.Series("retrieved_at", [instants[station_id] for station_id in ids], dtype=RETRIEVED_AT_DTYPE)
    )
    return InventoryMaterialization(
        NativeTable(data), tuple(sorted(responses, key=lambda r: (r.uf is None, r.uf or "", r.basin or 0)))
    )


def native_table_semantic_digest(table: NativeTable) -> str:
    """Digest deterministic column order, exact source values, and UTC acquisition instants."""
    if table.data.columns != [*SOURCE_FIELDS, "retrieved_at"]:
        raise FatalContractError("br_ana native table column order differs from inventory schema")
    data = table.data.with_columns(pl.col("retrieved_at").dt.strftime("%Y-%m-%dT%H:%M:%S%.6fZ"))
    return hashlib.sha256(data.write_json().encode("utf-8")).hexdigest()


def source_inventory(artifact: PackagedCatalogArtifact) -> tuple[SourceSeries, ...]:
    declarations = config()
    result = []
    for row in artifact.station_products.iter_rows(named=True):
        product = ProductId(row["product_id"])
        if product not in declarations.products or row["availability"] == "unavailable":
            continue
        source = declarations.products[product].coordinates.value
        if isinstance(source, (BrAnaDailySourceCoordinates, BrAnaSourceCoordinates)):
            result.append(describe_series(row["station_id"], product, source, origin="catalogue"))
    return tuple(result)
