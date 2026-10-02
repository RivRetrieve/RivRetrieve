"""ANA capture authority : InventoryCapture × RecordedInteractions → NativeTable; DocumentaryMaterial × RecordingEnvelope → ObservationEvidence (offline)."""

from __future__ import annotations

import hashlib
import json
import lzma
import math
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionRecord,
    MaterialIdentity,
    NativeTableIdentity,
    RecordingReference,
)
from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.recordings import RecordingEnvelope, read_recording
from rivretrieve._internal.transport import HttpMethod


class CapturedInventoryResponse(BaseModel):
    """Exact successful inventory request and retained recording identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    recording_id: str
    repository_path: str
    recording_sha256: str
    recording_byte_size: int = Field(gt=0)
    requested_url: str
    parameters: dict[str, str | int]
    retrieved_at: datetime
    media_type: str
    payload_sha256: str
    byte_size: int = Field(gt=0)
    row_count: int = Field(ge=0)
    distinct_station_count: int = Field(ge=0)

    @field_validator("repository_path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        if not value or Path(value).is_absolute() or ".." in Path(value).parts:
            raise ValueError("recording path must be repository-relative")
        return value

    @field_validator("recording_sha256", "payload_sha256")
    @classmethod
    def digest(cls, value: str) -> str:
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("invalid SHA-256")
        return value

    @field_validator("retrieved_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("retrieval instant must be UTC")
        return value


class RetainedAcquisitionEvidence(BaseModel):
    """Digest-bound acquisition outcomes and source-row accounting outside distributions."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    repository_path: str
    sha256: str
    byte_size: int = Field(gt=0)

    @field_validator("repository_path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        return CapturedInventoryResponse.relative_path(value)

    @field_validator("sha256")
    @classmethod
    def digest(cls, value: str) -> str:
        return CapturedInventoryResponse.digest(value)


class InventoryCapture(BaseModel):
    """Closed attestation for a bounded inventory acquisition and exact native union."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    responses: tuple[CapturedInventoryResponse, ...]
    native_table: NativeTableIdentity
    response_row_count: int = Field(gt=0)
    distinct_station_count: int = Field(gt=0)
    fluviometric_station_count: int = Field(ge=0)
    pluviometric_station_count: int = Field(ge=0)
    canonicalization: tuple[str, ...]
    population_scope: str
    attempt_record_paths: tuple[str, ...]
    supporting_evidence: tuple[RetainedAcquisitionEvidence, ...]

    @model_validator(mode="after")
    def closed_population(self) -> InventoryCapture:
        from rivretrieve._internal.providers.br_ana.inventory import BRAZILIAN_UNITS, INVENTORY_URL

        expected: set[tuple[str, str, str | int]] = {
            (INVENTORY_URL, "Unidade Federativa", uf) for uf in BRAZILIAN_UNITS
        }
        expected.update((INVENTORY_URL, "Código da Bacia", basin) for basin in range(1, 10))
        requests = []
        for response in self.responses:
            if len(response.parameters) != 1:
                raise ValueError("inventory capture requires one exact population filter per request")
            name, value = next(iter(response.parameters.items()))
            if name == "Código da Bacia" and type(value) is not int:
                raise ValueError("inventory basin filter must retain its integer type")
            requests.append((response.requested_url, name, value))
        if len(requests) != len(expected) or set(requests) != expected:
            raise ValueError("inventory capture must include exactly 27 UF and 9 basin requests")
        if len({response.recording_id for response in self.responses}) != len(self.responses):
            raise ValueError("inventory recording identities must be unique")
        if self.response_row_count != sum(response.row_count for response in self.responses):
            raise ValueError("inventory acquisition row accounting differs from responses")
        if self.distinct_station_count != self.fluviometric_station_count + self.pluviometric_station_count:
            raise ValueError("inventory station-type accounting does not partition the native union")
        return self


def read_capture_record(path: Path) -> InventoryCapture:
    """Read the strictly typed attestation at a supplied local path."""
    return InventoryCapture.model_validate_json(path.read_bytes())


def verify_materialization(capture: InventoryCapture, recordings: tuple[RecordingEnvelope, ...]) -> NativeTable:
    """Rebuild all retained source rows and compare exact acquisition and native identities."""
    from rivretrieve._internal.providers.br_ana.inventory import materialize_inventory, native_table_semantic_digest

    if len(recordings) != len(capture.responses):
        raise FatalContractError("ANA inventory capture response count mismatch")
    for identity, recording in zip(capture.responses, recordings, strict=True):
        actual = (
            recording.request.url,
            dict(recording.request.parameters or {}),
            recording.retrieved_at,
            recording.content_type,
            recording.sha256,
            len(recording.content),
        )
        expected = (
            identity.requested_url,
            identity.parameters,
            identity.retrieved_at,
            identity.media_type,
            identity.payload_sha256,
            identity.byte_size,
        )
        if actual != expected:
            raise FatalContractError("ANA inventory captured request or payload identity mismatch")
        rows = json.loads(recording.content)["items"]
        if (len(rows), len({row["codigoestacao"] for row in rows})) != (
            identity.row_count,
            identity.distinct_station_count,
        ):
            raise FatalContractError("ANA inventory captured response count mismatch")
    materialization = materialize_inventory(recordings, expected_basins=tuple(range(1, 10)))
    table = materialization.native
    counts = (
        sum(item.row_count for item in capture.responses),
        table.data.height,
        table.data.filter(pl.col("Tipo_Estacao") == "Fluviometrica").height,
        table.data.filter(pl.col("Tipo_Estacao") == "Pluviometrica").height,
    )
    if counts != (
        capture.response_row_count,
        capture.distinct_station_count,
        capture.fluviometric_station_count,
        capture.pluviometric_station_count,
    ):
        raise FatalContractError("ANA inventory population accounting mismatch")
    semantic = capture.native_table.semantic_digest
    if semantic is None or native_table_semantic_digest(table) != semantic.sha256:
        raise FatalContractError("ANA inventory native semantic identity mismatch")
    return table


def verify_native_identity(capture: InventoryCapture, native_bytes: bytes, table: NativeTable) -> None:
    """Verify the committed native bytes and semantic frame before offline publication."""
    from rivretrieve._internal.providers.br_ana.inventory import native_table_semantic_digest

    counts = (
        table.data.height,
        table.data.filter(pl.col("Tipo_Estacao") == "Fluviometrica").height,
        table.data.filter(pl.col("Tipo_Estacao") == "Pluviometrica").height,
    )
    if counts != (
        capture.distinct_station_count,
        capture.fluviometric_station_count,
        capture.pluviometric_station_count,
    ):
        raise FatalContractError("ANA inventory native population accounting mismatch")
    identity = capture.native_table
    if len(native_bytes) != identity.byte_size or hashlib.sha256(native_bytes).hexdigest() != identity.sha256:
        raise FatalContractError("ANA inventory native byte identity mismatch")
    if identity.semantic_digest is None or native_table_semantic_digest(table) != identity.semantic_digest.sha256:
        raise FatalContractError("ANA inventory native semantic identity mismatch")


def materialize_captured_native_table(capture: InventoryCapture, evidence_root: Path) -> NativeTable:
    """Verify compressed recording file identities, then reconstruct the attested native frame."""
    for identity in capture.supporting_evidence:
        body = (evidence_root / identity.repository_path).read_bytes()
        if len(body) != identity.byte_size or hashlib.sha256(body).hexdigest() != identity.sha256:
            raise FatalContractError("ANA inventory supporting acquisition evidence identity mismatch")
    recordings = []
    with tempfile.TemporaryDirectory(prefix="ana-inventory-") as directory:
        for index, identity in enumerate(capture.responses):
            encoded = (evidence_root / identity.repository_path).read_bytes()
            if (
                len(encoded) != identity.recording_byte_size
                or hashlib.sha256(encoded).hexdigest() != identity.recording_sha256
            ):
                raise FatalContractError("ANA inventory retained recording identity mismatch")
            target = Path(directory) / f"{index}.recording.json"
            target.write_bytes(lzma.decompress(encoded))
            recordings.append(read_recording(target))
    return verify_materialization(capture, tuple(recordings))


@dataclass(frozen=True, slots=True)
class AdoptedTelemetryEvidence:
    """Verified documentation material and nonnull per-product source observations."""

    documentation: AcquisitionRecord
    observations: RecordingReference
    available_pairs: frozenset[tuple[str, ProductId]]


def parse_adopted_telemetry_evidence(
    documentation_metadata: bytes,
    derived_excerpt: bytes,
    recording: RecordingEnvelope,
    recording_repository_path: str,
) -> AdoptedTelemetryEvidence:
    """Source materials → documented adopted units and bounded observed availability (pure)."""
    from rivretrieve._internal.providers.br_ana.config import BrAnaSourceCoordinates, config

    metadata = json.loads(documentation_metadata)
    material = metadata["publisher_material"]
    excerpt = metadata["derived_excerpt"]
    url = material["requested_url"]
    if (
        material["method"] != "GET"
        or material["status_code"] != 200
        or material["content_type"] != "application/pdf"
        or material["credential_header_names"] != []
        or material["transport_response_url"] != url
        or not url.startswith("https://www.gov.br/ana/")
        or hashlib.sha256(derived_excerpt).hexdigest() != excerpt["sha256"]
        or len(derived_excerpt) != excerpt["bytes"]
    ):
        raise FatalContractError("ANA manual material or derived excerpt identity is invalid")
    text = derived_excerpt.decode("utf-8")
    if not all(
        term in text
        for term in ("Cota_Adotada", "Cota (cm)", "Vazao_Adotada", "Vazão (m3/s)", "DataHora da medição/coleta do dado")
    ):
        raise FatalContractError("ANA manual excerpt lacks adopted units or measurement-time documentation")
    documentation = AcquisitionRecord(
        acquisition_id="adopted_telemetry_manual",
        method="http_request",
        instant_type="retrieval",
        description=(
            "Official ANA manual PDF acquired without credentials, original bytes not retained. "
            f"Safe derived page11 text SHA256 {excerpt['sha256']}, {excerpt['bytes']} bytes. "
            f"Transformation {excerpt['transformation']!r}. Derived text is not original response bytes. "
            "PDF page11 documents Cota_Adotada cm, Vazao_Adotada m3/s and measurement/collection timestamp."
        ),
        requested_from=(url,),
        retrieved_at_start=datetime.fromisoformat(material["retrieved_at"]),
        material=MaterialIdentity(
            filename=url.rsplit("/", 1)[-1], byte_count=material["bytes"], sha256=material["sha256"]
        ),
    )
    request = recording.request
    parameters = request.parameters
    if (
        request.url
        != "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroinfoanaSerieTelemetricaAdotada/v1"
        or recording.content_type is None
        or request.method != HttpMethod.GET
        or request.body is not None
        or recording.status_code != 200
        or parameters is None
        or parameters.get("Tipo Filtro Data") != "DATA_LEITURA"
        or set(parameters)
        != {"Código da Estação", "Tipo Filtro Data", "Data de Busca (yyyy-MM-dd)", "Range Intervalo de busca"}
        or parameters["Range Intervalo de busca"] != "DIAS_30"
    ):
        raise FatalContractError("ANA adopted availability requires an exact successful measurement-time recording")
    station = str(parameters["Código da Estação"])
    document = json.loads(recording.content)
    if (
        document["status"] != "OK"
        or type(document["code"]) is not int
        or document["code"] != 200
        or not isinstance(document["items"], list)
    ):
        raise FatalContractError("ANA adopted availability recording has an invalid source envelope")
    pairs = set()
    for row in document["items"]:
        if row["codigoestacao"] != station:
            raise FatalContractError("ANA adopted availability recording contains another station")
        for product, definition in config().products.items():
            coordinates = definition.coordinates.value
            if not isinstance(coordinates, BrAnaSourceCoordinates):
                continue
            value = row[coordinates.field]
            if value is not None:
                if not isinstance(value, str) or not math.isfinite(float(value)):
                    raise FatalContractError("ANA adopted availability value must be a finite numeric string or null")
                pairs.add((station, product))
    reference = RecordingReference(
        recording_id="ana_adopted_telemetry_measurements",
        repository_path=recording_repository_path,
        source_url=request.url,
        retrieved_at=recording.retrieved_at,
        media_type=recording.content_type,
        sha256=recording.sha256,
    )
    return AdoptedTelemetryEvidence(documentation, reference, frozenset(pairs))


@dataclass(frozen=True, slots=True)
class ConventionalDailyEvidence:
    """Reviewed source definitions and exact nonnull daily variant observations."""

    documentation: AcquisitionRecord
    observations: tuple[tuple[RecordingReference, frozenset[tuple[str, ProductId]]], ...]
    correspondence: tuple[RecordingReference, ...]

    @property
    def available_pairs(self) -> frozenset[tuple[str, ProductId]]:
        return frozenset(pair for _, pairs in self.observations for pair in pairs)


# Reviewed derived documents are pinned, not accepted merely because a caller
# supplies a self-consistent digest. Renewing these identities requires source review.
_DAILY_DEFINITION_DIGESTS = {
    "hidro-1.4-conventional-dictionary-derived.json": "984304fa3a47824362008f6ec2479a78ca16a2301381dec41fe6bae1f441d732",
    "hidro-sqlserver-selected-views-derived.json": "ca8d60f3780e669303bc9b3369658ab8c646efeb850a1515e81729e7b2b1ac7b",
    "hidro-extraction-manifest.json": "14edd76db0cb0277e8b1d896552b46eee4c2d03bfb47a449db7e74ea326092f6",
    "daily-source-comparison-report.md": "66a8a9b8e1ad18ce634491f9afd45f4813f855441f12602217af5d13f9403f5d",
    "paired-discharge-2024-comparison.json": "7edef07cd01b85d9a47442200ec8f2dc315667da19b53401c9143c802217f9f1",
    "paired-stage-2020-comparison.json": "1f8d95b6ae700b7c133e9cd873a7c78e678bb00b0f742f17f26bbc64a703f70a",
    "paired-discharge-2020-comparison.json": "a42f4ec3408690af0faf7155e03d0a538fc6392fc824dd5544bb77e50b4fe077",
    "paired-stage-2024-comparison.json": "cced4ceaaa5724e29cb0ebdb3428c688f444d2a83ac056b2a656cc4941fc428e",
    "daily-correspondence-identities.json": "b0de850c7658e9232b2afaa50c9d468e9f64dc5f4f85015e5e645fef2d97f823",
}


def parse_conventional_daily_evidence(
    documents: dict[str, bytes],
    recordings: tuple[tuple[str, RecordingEnvelope], ...],
    correspondence: tuple[tuple[str, RecordingEnvelope], ...],
) -> ConventionalDailyEvidence:
    """Reviewed DocumentaryMaterial × RecordingEnvelope → ConventionalDailyEvidence (pure)."""
    from calendar import monthrange

    from rivretrieve._internal.providers.br_ana.config import BrAnaDailySourceCoordinates, config

    if set(documents) != set(_DAILY_DEFINITION_DIGESTS) or any(
        hashlib.sha256(documents[name]).hexdigest() != digest for name, digest in _DAILY_DEFINITION_DIGESTS.items()
    ):
        raise FatalContractError("ANA conventional source-definition identity is not reviewed")
    dictionary = json.loads(documents["hidro-1.4-conventional-dictionary-derived.json"])
    sql = json.loads(documents["hidro-sqlserver-selected-views-derived.json"])
    extraction = json.loads(documents["hidro-extraction-manifest.json"])
    distribution = dictionary["publisher_distribution"]
    documentation = AcquisitionRecord(
        acquisition_id="conventional_hidro_definitions",
        method="http_request",
        instant_type="retrieval",
        requested_from=(distribution["url"],),
        retrieved_at_start=datetime.fromisoformat(distribution["retrieved_at"]),
        material=MaterialIdentity(
            filename=distribution["url"].rsplit("/", 1)[-1],
            byte_count=distribution["bytes"],
            sha256=distribution["sha256"],
        ),
        description=(
            "Official Hidro Build1.4.0.81 distribution; ZIP and installer are not retained publicly. "
            f"Static extraction with {extraction['extractor']}; installer SHA256 {extraction['installer_sha256']}. "
            f"Dictionary member {dictionary['source_member']!r}, SHA256 {dictionary['source_sha256']}; "
            f"derived transformation {dictionary['transformation']}. "
            f"SQL member {sql['source_member']!r}, SHA256 {sql['source_sha256']}; {sql['transformation']}. "
            "Dictionary pages21-24: MediaDiaria 0=Não (instantaneous), 1=Sim (daily mean); "
            "NivelConsistencia 1=Bruto, 2=Consistido; Data MM/AAAA; Cota01..31 cm, Vazao01..31 m3/s. "
            "SQL ordinal-day expansion corroborates calendar labels, not daily support or zone. "
            "Paired modern/SOAP field research corroborates renamed fields, not interchangeable values; "
            "modern values remain authoritative. Derived excerpts are not original response bytes. "
            + "; ".join(
                f"tests/recordings/br_ana/{name}: SHA256 {digest}, {len(documents[name])} bytes"
                for name, digest in _DAILY_DEFINITION_DIGESTS.items()
            )
        ),
    )
    correspondence_identities = json.loads(documents["daily-correspondence-identities.json"])["recordings"]
    retained = dict(correspondence)
    if set(retained) != {item["repository_path"] for item in correspondence_identities}:
        raise FatalContractError("ANA source correspondence recordings are incomplete")
    correspondence_refs = []
    for index, item in enumerate(correspondence_identities):
        recording = retained[item["repository_path"]]
        request = recording.request
        expected_request = item["request"]
        if recording.sha256 != item["response_sha256"] or (
            request.method.value,
            request.url,
            dict(request.parameters or {}),
            request.body,
            dict(request.ordinary_headers),
            list(request.credential_header_names),
        ) != (
            expected_request["method"],
            expected_request["url"],
            expected_request["parameters"],
            expected_request["body"],
            expected_request["ordinary_headers"],
            expected_request["credential_header_names"],
        ):
            raise FatalContractError("ANA source correspondence identity differs from reviewed comparison")
        if recording.content_type is None or recording.status_code != 200:
            raise FatalContractError("ANA source correspondence recording is unsuccessful")
        correspondence_refs.append(
            RecordingReference(
                recording_id=f"ana_daily_correspondence_{index}",
                repository_path=item["repository_path"],
                source_url=recording.request.url,
                retrieved_at=recording.retrieved_at,
                media_type=recording.content_type,
                sha256=recording.sha256,
            )
        )
    observations = []
    identities = set()
    for path, recording in recordings:
        request = recording.request
        parameters = request.parameters
        endpoint = request.url.rsplit("/", 2)[-2]
        if (
            endpoint not in {"HidroSerieCotas", "HidroSerieVazao"}
            or request.url != f"https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/{endpoint}/v1"
            or request.method != HttpMethod.GET
            or request.body is not None
            or recording.status_code != 200
            or recording.content_type is None
            or parameters is None
            or set(parameters)
            != {"Código da Estação", "Tipo Filtro Data", "Data Inicial (yyyy-MM-dd)", "Data Final (yyyy-MM-dd)"}
            or parameters["Tipo Filtro Data"] != "DATA_LEITURA"
        ):
            raise FatalContractError("ANA daily availability requires exact successful measurement-month requests")
        station = str(parameters["Código da Estação"])
        start = datetime.strptime(str(parameters["Data Inicial (yyyy-MM-dd)"]), "%Y-%m-%d")
        stop = datetime.strptime(str(parameters["Data Final (yyyy-MM-dd)"]), "%Y-%m-%d")
        if start.day != 1 or (stop.year, stop.month, stop.day) != (
            start.year,
            start.month,
            monthrange(start.year, start.month)[1],
        ):
            raise FatalContractError("ANA daily availability recording must request an exact whole month")
        identity = (endpoint, station, start)
        if identity in identities:
            raise FatalContractError("ANA daily availability recording request is duplicated")
        identities.add(identity)
        document = json.loads(recording.content)
        if (
            document["status"] != "OK"
            or type(document["code"]) is not int
            or document["code"] != 200
            or not isinstance(document["items"], list)
        ):
            raise FatalContractError("ANA daily availability source envelope is invalid")
        pairs = set()
        consistency_field = "nivelconsistencia" if endpoint == "HidroSerieCotas" else "Nivel_Consistencia"
        for row in document["items"]:
            if (
                row["codigoestacao"] != station
                or row["Mediadiaria"] not in {"0", "1"}
                or row[consistency_field] not in {"1", "2"}
            ):
                raise FatalContractError("ANA daily availability row identity is invalid")
            if row["Mediadiaria"] != "1":
                continue
            header = datetime.fromisoformat(row["Data_Hora_Dado"])
            if header != start:
                raise FatalContractError("ANA daily availability month label is not the requested midnight header")
            for product, definition in config().products.items():
                coordinates = definition.coordinates.value
                if (
                    not isinstance(coordinates, BrAnaDailySourceCoordinates)
                    or coordinates.endpoint != endpoint
                    or coordinates.consistency != row[consistency_field]
                ):
                    continue
                for day in range(1, 32):
                    value = row[f"{coordinates.field_prefix}_{day:02}"]
                    if value is None or value == "":
                        continue
                    if (
                        not isinstance(value, str)
                        or re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", value) is None
                        or not math.isfinite(float(value))
                        or day > stop.day
                    ):
                        raise FatalContractError("ANA daily availability requires finite values on valid calendar days")
                    pairs.add((station, product))
        reference = RecordingReference(
            recording_id=f"ana_{endpoint}_{station}_{start.date().isoformat()}",
            repository_path=path,
            source_url=request.url,
            retrieved_at=recording.retrieved_at,
            media_type=recording.content_type,
            sha256=recording.sha256,
        )
        observations.append((reference, frozenset(pairs)))
    if not observations:
        raise FatalContractError("ANA daily availability requires observation evidence")
    return ConventionalDailyEvidence(documentation, tuple(observations), tuple(correspondence_refs))
