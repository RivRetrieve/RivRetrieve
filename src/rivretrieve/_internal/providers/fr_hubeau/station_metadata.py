"""Project Hub’Eau station partitions and exact retained site responses."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit  # noqa: TID251 - URL validation only

import polars as pl

from rivretrieve._internal.acquisition_provenance import RecordingReference, RetainedInputReceipt, RetainedInputUse
from rivretrieve._internal.catalogue_origins import Field, NativeColumn
from rivretrieve._internal.catalogues.inputs import verify_retained_input_files
from rivretrieve._internal.catalogues.native import RETRIEVED_AT_DTYPE, NativeTable
from rivretrieve._internal.catalogues.station_metadata import MetadataField, build_station_metadata
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.station_metadata import ATTRIBUTE_ROLES, SOURCE_METADATA_SCHEMA, source_metadata_frame

SITE_ENDPOINT = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/sites"
SITE_FACT = "source.station.hubeau_site_metadata"
HYDROMETRY_SCOPE = "hydrometrie/referentiel/stations"
TEMPERATURE_SCOPE = "temperature/station"
SITE_SCOPE = "hydrometrie/referentiel/sites"
_SITE_SCHEMA = {
    "code_site": pl.String,
    "libelle_site": pl.String,
    "altitude_site": pl.Float64,
    "code_systeme_alti_site": pl.Int64,
    "surface_bv": pl.Float64,
    "libelle_cours_eau": pl.String,
    "code_cours_eau": pl.String,
    "uri_cours_eau": pl.String,
    "date_maj_site": pl.String,
}


def _json(body: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        return json.loads(body.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, ValueError, TypeError):
        raise FatalContractError("Hub’Eau metadata contains invalid JSON") from None


def _finite_number(value: object) -> bool:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def parse_site_response(body: bytes, expected_codes: tuple[str, ...]) -> pl.DataFrame:
    """Parse a complete response, preserving nulls and omitting unreturned sites.

    The nine adopted source fields must be present. Numbers become Float64;
    vertical reference codes remain Int64. Boolean numbers, duplicate identities,
    incomplete pages and identities outside the exact request fail the contract.
    """
    if (
        not isinstance(expected_codes, tuple)
        or any(not isinstance(code, str) or not code for code in expected_codes)
        or len(set(expected_codes)) != len(expected_codes)
    ):
        raise FatalContractError("Hub’Eau site request has invalid expected identities")
    response = _json(body)
    if (
        not isinstance(response, dict)
        or type(response.get("count")) is not int
        or not isinstance(response.get("data"), list)
        or "next" not in response
        or response["next"] is not None
        or response["count"] != len(response["data"])
    ):
        raise FatalContractError("Hub’Eau site response is not a complete counted page")
    seen = set()
    rows = []
    for row in response["data"]:
        if not isinstance(row, dict) or not _SITE_SCHEMA.keys() <= row.keys():
            raise FatalContractError("Hub’Eau site response lacks required source fields")
        code = row["code_site"]
        if not isinstance(code, str) or code not in expected_codes or code in seen:
            raise FatalContractError("Hub’Eau site response has duplicate or unrequested identities")
        seen.add(code)
        for name, dtype in _SITE_SCHEMA.items():
            value = row[name]
            if value is None and name not in {"code_site", "libelle_site"}:
                continue
            valid = (
                isinstance(value, str)
                if dtype == pl.String
                else (type(value) is int and -(2**63) <= value < 2**63 if dtype == pl.Int64 else _finite_number(value))
            )
            if not valid:
                raise FatalContractError("Hub’Eau site source field has an invalid scalar type")
            if dtype == pl.Float64 and type(value) is int and float(value) != value:
                raise FatalContractError("Hub’Eau site number cannot be represented exactly as Float64")
        rows.append({name: row[name] for name in _SITE_SCHEMA})
    return pl.DataFrame(rows, schema=_SITE_SCHEMA)


@dataclass(frozen=True, slots=True)
class StationMetadataSources:
    """Immutable originals and selected-member identities for the site cohort.

    Projection reparses the bytes, so changes to a derived frame cannot detach
    projected values from the original response checked at publication.
    """

    site_bodies: Mapping[str, bytes] = field(repr=False)
    site_recordings: tuple[RecordingReference, ...]
    expected_site_codes: Mapping[str, tuple[str, ...]] = field(repr=False)
    member_digests: Mapping[str, frozenset[str]] = field(repr=False)

    def __post_init__(self) -> None:
        if any(not isinstance(body, bytes) for body in self.site_bodies.values()):
            raise FatalContractError("Hub’Eau metadata originals must be immutable bytes")
        object.__setattr__(self, "site_bodies", MappingProxyType(dict(self.site_bodies)))
        object.__setattr__(self, "site_recordings", tuple(self.site_recordings))
        object.__setattr__(
            self,
            "expected_site_codes",
            MappingProxyType({identity: tuple(codes) for identity, codes in self.expected_site_codes.items()}),
        )
        object.__setattr__(
            self,
            "member_digests",
            MappingProxyType({fact: frozenset(digests) for fact, digests in self.member_digests.items()}),
        )


def _relative(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or Path(value).is_absolute()
        or ".." in Path(value).parts
        or "\\" in value
    ):
        raise FatalContractError("Hub’Eau metadata member must have a relative consumer path")
    return value


def _receipt(body: bytes, raw: bytes, document: dict) -> tuple[datetime, str]:
    receipt = _json(raw)
    try:
        if (
            not isinstance(receipt, dict)
            or receipt.get("document") != document
            or receipt.get("fresh_acquisition") is not True
            or receipt.get("stopped") != "terminal_response"
        ):
            raise ValueError
        hops = receipt["hops"]
        if not isinstance(hops, list) or len(hops) != 1:
            raise ValueError
        hop = hops[0]
        if (
            type(hop["hop"]) is not int
            or hop["hop"] != 0
            or type(hop["status"]) is not int
            or hop["status"] != 200
            or hop["requested_url"] != document["url"]
            or hop["executed_url"] != document["url"]
            or hop["body_file"] != "hop-0.body"
            or hop["sha256"] != hashlib.sha256(body).hexdigest()
            or type(hop["byte_size"]) is not int
            or hop["byte_size"] != len(body)
        ):
            raise ValueError
        types = [value for name, value in hop["headers"].items() if name.lower() == "content-type"]
        if len(types) != 1 or not isinstance(types[0], str) or types[0].split(";")[0].lower() != "application/json":
            raise ValueError
        instant = datetime.fromisoformat(hop["body_received_at"])
        if instant.tzinfo is None:
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise FatalContractError("Hub’Eau site receipt violates its selected acquisition identity") from None
    return instant, types[0]


def read_station_metadata_sources(
    evidence_root: Path,
    *,
    input_receipt: RetainedInputReceipt,
    site_root: str,
    manifest_sha256: str,
    lineage_sha256: str,
) -> StationMetadataSources:
    """Verify independently selected members before reading the pinned site cohort.

    Full private request URLs must agree between manifest and response receipt.
    Public recording references expose only the publisher endpoint. Manifest IDs
    select consumer directories; historical lineage paths are never opened.
    """
    site_root = _relative(site_root)
    selected = {item.consumer_path: item for item in input_receipt.inputs}
    member_digests = {}

    def read(path: str) -> bytes:
        if path not in selected:
            raise FatalContractError("Hub’Eau metadata member is absent from selected archive inputs")
        try:
            verify_retained_input_files(
                input_receipt.model_copy(
                    update={
                        "inputs": (selected[path],),
                        "declaration_inputs": (),
                        "support_inputs": (),
                    }
                ),
                evidence_root,
            )
            body = (evidence_root / path).read_bytes()
        except OSError:
            raise FatalContractError("Hub’Eau selected metadata member is unavailable") from None
        digest = hashlib.sha256(body).hexdigest()
        if digest != selected[path].sha256 or len(body) != selected[path].byte_size:
            raise FatalContractError("Hub’Eau metadata member changed after archive verification")
        return body

    manifest = read(f"{site_root}/documents.json")
    lineage_body = read(f"{site_root}/lineage.json")
    if (
        hashlib.sha256(manifest).hexdigest() != manifest_sha256
        or hashlib.sha256(lineage_body).hexdigest() != lineage_sha256
    ):
        raise FatalContractError("Hub’Eau metadata manifest or lineage differs from its pinned identity")
    documents, lineage = _json(manifest), _json(lineage_body)
    if (
        not isinstance(documents, list)
        or not documents
        or not isinstance(lineage, dict)
        or lineage.get("kind") != "verified_input_view_not_new_acquisition"
        or not isinstance(lineage.get("files"), list)
    ):
        raise FatalContractError("Hub’Eau metadata manifest or lineage has an invalid structure")
    members = lineage["files"]
    if any(not isinstance(member, dict) or not isinstance(member.get("document_id"), str) for member in members):
        raise FatalContractError("Hub’Eau metadata lineage has an invalid member")
    bodies, expected, recordings = {}, {}, []
    all_codes = set()
    for document in documents:
        if not isinstance(document, dict):
            raise FatalContractError("Hub’Eau site manifest contains an invalid document")
        identity = document.get("id")
        codes = document.get("expected_site_codes")
        url = document.get("url")
        if (
            not isinstance(identity, str)
            or not identity
            or identity in bodies
            or not isinstance(codes, list)
            or not codes
            or len(codes) > 50
            or any(not isinstance(code, str) or not code for code in codes)
            or len(set(codes)) != len(codes)
            or all_codes.intersection(codes)
            or not isinstance(url, str)
            or type(document.get("requested_page")) is not int
            or document["requested_page"] != 1
            or type(document.get("requested_size")) is not int
            or document["requested_size"] != 50
        ):
            raise FatalContractError("Hub’Eau site manifest has invalid request identities")
        parsed = urlsplit(url)
        if (
            f"{parsed.scheme}://{parsed.netloc}{parsed.path}" != SITE_ENDPOINT
            or parsed.fragment
            or document.get("allowed_origins") != ["https://hubeau.eaufrance.fr"]
        ):
            raise FatalContractError("Hub’Eau site manifest has an unsupported publisher endpoint")
        if identity in {".", ".."} or "/" in identity or "\\" in identity:
            raise FatalContractError("Hub’Eau manifest has an invalid document directory identity")
        selected_bodies = {}
        for filename in ("body", "receipt.json"):
            raw = read(f"{site_root}/{identity}/{filename}")
            matches = [
                member
                for member in members
                if member["document_id"] == identity
                and member.get("sha256") == hashlib.sha256(raw).hexdigest()
                and type(member.get("byte_size")) is int
                and member["byte_size"] == len(raw)
            ]
            if len(matches) != 1:
                raise FatalContractError("Hub’Eau metadata lineage disagrees with selected member bytes")
            selected_bodies[filename] = raw
        body, receipt = selected_bodies["body"], selected_bodies["receipt.json"]
        member_digests[f"{SITE_FACT}.{identity}"] = frozenset(
            (
                manifest_sha256,
                lineage_sha256,
                hashlib.sha256(body).hexdigest(),
                hashlib.sha256(receipt).hexdigest(),
            )
        )
        path = f"{identity}/body"
        instant, media_type = _receipt(body, receipt, document)
        parse_site_response(body, tuple(codes))
        bodies[identity], expected[identity] = body, tuple(codes)
        all_codes.update(codes)
        recordings.append(
            RecordingReference(
                recording_id=identity,
                repository_path=f"{site_root}/{path}",
                source_url=SITE_ENDPOINT,
                retrieved_at=instant,
                media_type=media_type,
                sha256=hashlib.sha256(body).hexdigest(),
            )
        )
    if {member["document_id"] for member in members} != set(bodies):
        raise FatalContractError("Hub’Eau lineage has documents outside the selected manifest")
    return StationMetadataSources(bodies, tuple(recordings), expected, member_digests)


def verify_adopted_station_metadata(sources: StationMetadataSources, inputs: Sequence[RetainedInputUse]) -> None:
    """Recheck entire immutable bodies and their adopted original/receipt cohort."""
    references = {item.recording_id: item for item in sources.site_recordings}
    if (
        set(sources.member_digests) != {f"{SITE_FACT}.{identity}" for identity in references}
        or not references
        or not all(sources.member_digests.values())
        or len(references) != len(sources.site_recordings)
        or set(references) != set(sources.site_bodies)
        or set(references) != set(sources.expected_site_codes)
    ):
        raise FatalContractError("Hub’Eau metadata source identities are incomplete")
    for identity, body in sources.site_bodies.items():
        digest = hashlib.sha256(body).hexdigest()
        if digest != references[identity].sha256 or digest not in sources.member_digests[f"{SITE_FACT}.{identity}"]:
            raise FatalContractError("Hub’Eau site original differs from its validated identity")
    for fact, digests in sources.member_digests.items():
        adopted = {item.reference.sha256 for item in inputs if fact in item.facts and item.usage != "native_table"}
        if not digests <= adopted:
            raise FatalContractError("Hub’Eau site originals and receipts must match adopted archive members")


def project_station_metadata(
    native_table: NativeTable,
    stations: pl.DataFrame,
    sources: StationMetadataSources,
    fields: tuple[MetadataField, ...],
) -> pl.DataFrame:
    """Project genuinely exposed partition fields and exact native site associations.

    Site rows attach only to hydrometry stations through their native code_site.
    An unreturned site exposes no site fields. Same-spelled fields from different
    endpoints remain separate. This operation does not change canonical geometry.
    """
    if any(item.source_scope not in {HYDROMETRY_SCOPE, TEMPERATURE_SCOPE, SITE_SCOPE} for item in fields):
        raise FatalContractError("Hub’Eau metadata requires an explicit approved source scope")
    native = native_table.data
    if native.schema.get("code_station") != pl.String or native.schema.get("code_site") != pl.String:
        raise FatalContractError("Hub’Eau metadata requires native string station and site identities")
    if native.schema.get("source_endpoint") != pl.String:
        raise FatalContractError("Hub’Eau metadata requires native source endpoints")
    identities = stations["station_id"].to_list()
    if (
        stations.schema["station_id"] != pl.String
        or any(not code for code in identities)
        or len(set(identities)) != len(identities)
        or native["code_station"].n_unique() != native.height
    ):
        raise FatalContractError("Hub’Eau metadata requires distinct canonical and native station identities")
    matched = native.filter(pl.col("code_station").is_in(identities))
    if matched.height != len(identities) or not set(matched["source_endpoint"]) <= {
        HYDROMETRY_SCOPE,
        TEMPERATURE_SCOPE,
    }:
        raise FatalContractError("Hub’Eau canonical station lacks its native endpoint identity")
    references = {item.recording_id: item for item in sources.site_recordings}
    if len(references) != len(sources.site_recordings) or set(references) != set(sources.site_bodies):
        raise FatalContractError("Hub’Eau site originals lack distinct acquisition references")
    site_frames = [
        parse_site_response(body, sources.expected_site_codes[identity]).with_columns(
            pl.lit(references[identity].retrieved_at).cast(RETRIEVED_AT_DTYPE).alias("retrieved_at")
        )
        for identity, body in sources.site_bodies.items()
    ]
    sites = (
        pl.concat(site_frames)
        if site_frames
        else pl.DataFrame(schema={**_SITE_SCHEMA, "retrieved_at": RETRIEVED_AT_DTYPE})
    )
    if sites["code_site"].n_unique() != sites.height:
        raise FatalContractError("Hub’Eau site originals repeat a site identity")
    hydro = matched.filter(pl.col("source_endpoint") == HYDROMETRY_SCOPE)
    expected = [code for codes in sources.expected_site_codes.values() for code in codes]
    if len(set(expected)) != len(expected) or not set(hydro["code_site"].drop_nulls()) <= set(expected):
        raise FatalContractError("Hub’Eau native site association is outside the selected request scope")
    frames = []
    for scope in (HYDROMETRY_SCOPE, TEMPERATURE_SCOPE, SITE_SCOPE):
        selected = tuple(item for item in fields if item.source_scope == scope)
        if not selected:
            continue
        partition = (
            hydro.select("code_station", "code_site").join(sites, on="code_site", how="inner")
            if scope == SITE_SCOPE
            else matched.filter(pl.col("source_endpoint") == scope)
        )
        if partition.is_empty():
            continue
        canonical = stations.filter(pl.col("station_id").is_in(partition["code_station"].implode()))
        projected = build_station_metadata(
            "fr_hubeau", NativeTable(partition), canonical, Field(NativeColumn("code_station")), selected
        )
        frames.append(projected.filter(pl.col("state") != "no_metadata"))
    result = pl.concat(frames) if frames else pl.DataFrame(schema=SOURCE_METADATA_SCHEMA)
    absent = []
    exposed = set(result.select("station_id", "attribute_role").iter_rows())
    for station in identities:
        for role in ATTRIBUTE_ROLES:
            if (station, role) not in exposed:
                absent.append(
                    {"provider_id": "fr_hubeau", "station_id": station, "attribute_role": role, "state": "no_metadata"}
                )
    result = pl.concat([result, pl.DataFrame(absent, schema=SOURCE_METADATA_SCHEMA)])
    return source_metadata_frame(stations.select(pl.lit("fr_hubeau").alias("provider_id"), "station_id"), result)
