"""Preserve FOEN station-directory attributes and station-information text."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit  # noqa: TID251 - URL parsing only; no network access

import polars as pl

from rivretrieve._internal.acquisition_provenance import RecordingReference, RetainedInputReceipt, RetainedInputUse
from rivretrieve._internal.catalogues.inputs import verify_retained_input_files
from rivretrieve._internal.catalogues.station_metadata import MetadataField
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.station_metadata import (
    ATTRIBUTE_ROLES,
    SOURCE_METADATA_SCHEMA,
    metadata_support_fact,
    source_metadata_frame,
)

_FIELDS = {"Station altitude", "Catchment size"}
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _StationMetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.directory: dict[str, dict[str, str]] = {}
        self.station_ids: list[str] = []
        self.fields: dict[str, str] = {}
        self.heading: tuple[str, list[str]] | None = None
        self.small: list[str] | None = None
        self.label: list[str] | None = None
        self.value: list[str] | None = None
        self.pending_label: str | None = None
        self.in_information = False
        self.information_lists = 0
        self.definition_depth: int | None = None
        self.row: dict[str, str] | None = None
        self.row_linked = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.value is not None:
            raise FatalContractError("FOEN station information scalar contains unsupported nested markup")
        attributes = dict(attrs)
        parent = self.stack[-1] if self.stack else None
        if tag in _HEADINGS:
            self.heading = (tag, [])
            self.in_information = False
        if tag == "small" and parent == "h1":
            self.small = []
        if tag == "dl" and self.in_information:
            if self.definition_depth is not None or self.information_lists:
                raise FatalContractError("FOEN station information has ambiguous definition lists")
            self.information_lists += 1
            self.definition_depth = len(self.stack)
        if parent == "dl" and self.definition_depth == len(self.stack) - 1:
            if self.pending_label in _FIELDS and tag != "dd":
                raise FatalContractError("FOEN station information label lacks its immediate value")
            if tag == "dt":
                self.label = []
                self.pending_label = None
            elif tag == "dd" and self.pending_label in _FIELDS:
                self.value = []
        if tag == "tr" and "station-row" in (attributes.get("class") or "").split():
            if self.row is not None:
                raise FatalContractError("FOEN station directory contains nested station rows")
            names = ("data-key", "data-name", "data-hydro-body")
            if any(
                sum(key == name for key, _ in attrs) != 1 or not isinstance(attributes.get(name), str) for name in names
            ):
                raise FatalContractError("FOEN station directory lacks unique string metadata attributes")
            self.row = {name: str(attributes[name]) for name in names}
            if not self.row["data-key"]:
                raise FatalContractError("FOEN station directory has an empty station identity")
            self.row_linked = False
        if tag == "a" and self.row is not None:
            self.row_linked |= attributes.get("href") == f"/en/seen-und-fluesse/stations/{self.row['data-key']}"
        if tag not in _VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "small" and self.small is not None:
            self.station_ids.append("".join(self.small))
            self.small = None
        if self.heading is not None and tag == self.heading[0]:
            self.in_information = self.heading[0] == "h2" and "".join(self.heading[1]) == "Station information"
            self.heading = None
        if tag == "dt" and self.label is not None:
            self.pending_label = "".join(self.label)
            self.label = None
        if tag == "dd":
            if self.value is not None:
                if self.pending_label in self.fields:
                    raise FatalContractError("FOEN station information contains duplicate source fields")
                assert self.pending_label is not None
                self.fields[self.pending_label] = "".join(self.value)
                self.value = None
            self.pending_label = None
        if tag == "dl" and self.definition_depth == len(self.stack) - 1:
            if self.pending_label in _FIELDS:
                raise FatalContractError("FOEN station information label lacks its immediate value")
            self.definition_depth = None
        if tag == "tr" and self.row is not None:
            if not self.row_linked:
                raise FatalContractError("FOEN directory station identity disagrees with its station link")
            station = self.row["data-key"]
            values = {name: self.row[name] for name in ("data-name", "data-hydro-body")}
            if station in self.directory and self.directory[station] != values:
                raise FatalContractError("FOEN repeated directory rows disagree on station metadata")
            self.directory[station] = values
            self.row = None
        if tag in self.stack:
            self.stack = self.stack[: len(self.stack) - 1 - self.stack[::-1].index(tag)]

    def handle_data(self, data: str) -> None:
        if self.heading is not None:
            self.heading[1].append(data)
        for parts in (self.small, self.label, self.value):
            if parts is not None:
                parts.append(data)


def _parse(body: bytes) -> _StationMetadataParser:
    parser = _StationMetadataParser()
    try:
        parser.feed(body.decode("utf-8", errors="strict"))
        parser.close()
    except UnicodeDecodeError as error:
        raise FatalContractError("FOEN metadata original is not UTF-8") from error
    if any(
        item is not None for item in (parser.small, parser.label, parser.value, parser.row, parser.definition_depth)
    ):
        raise FatalContractError("FOEN station metadata original contains an incomplete source structure")
    return parser


def parse_station_directory(body: bytes) -> dict[str, dict[str, str]]:
    """Read exact decoded metadata attributes, rejecting conflicting repeated rows."""
    parser = _parse(body)
    if not parser.directory:
        raise FatalContractError("FOEN station directory contains no station rows")
    return parser.directory


def parse_station_page(body: bytes, station_id: str) -> dict[str, str]:
    """Read whole decoded values from Station information for the exact gauge."""
    parser = _parse(body)
    if parser.station_ids != [station_id] or parser.information_lists != 1:
        raise FatalContractError("FOEN station page lacks the selected identity or Station information list")
    return parser.fields


def project_station_metadata(
    stations: pl.DataFrame,
    directory_body: bytes,
    station_pages: Mapping[str, bytes],
    fields: tuple[MetadataField, ...],
) -> pl.DataFrame:
    """Project approved source fields without parsing quantities or filling absences.

    Station pages must cover exactly the canonical gauges linked by the supplied
    directory. A missing required page raises FatalContractError. A field absent
    from an adopted page remains unexposed. HTML scalars, including empty strings
    and inline units, remain String values. Canonical geometry is not changed.
    """
    directory = parse_station_directory(directory_body)
    identities = stations["station_id"].to_list()
    if (
        stations.schema.get("station_id") != pl.String
        or any(not identity for identity in identities)
        or len(set(identities)) != len(identities)
    ):
        raise FatalContractError("FOEN metadata requires distinct canonical string station identities")
    if set(station_pages) != set(identities).intersection(directory):
        raise FatalContractError("FOEN station pages do not cover the directory-linked canonical gauge scope")
    pages = {station: parse_station_page(body, station) for station, body in station_pages.items()}
    sources = {"station_directory": directory, "station_page": pages}
    if any(field.source_scope not in sources or field.datum_field is not None for field in fields):
        raise FatalContractError("FOEN metadata declarations require an established source scope and declared datum")
    rows = []
    for station in identities:
        exposed = set()
        for field in fields:
            scope = field.source_scope
            if scope is None:
                raise FatalContractError("FOEN metadata requires an explicit source scope")
            values = sources[scope].get(station, {})
            if field.source_field not in values:
                continue
            exposed.add(field.attribute_role)
            fact = metadata_support_fact(field.attribute_role, field.source_field, field.source_scope)
            rows.append(
                {
                    "provider_id": "ch_foen",
                    "station_id": station,
                    "attribute_role": field.attribute_role,
                    "source_field": field.source_field,
                    "source_scope": field.source_scope,
                    "source_value": json.dumps(values[field.source_field], ensure_ascii=False),
                    "source_dtype": "String",
                    "source_unit": field.source_unit,
                    "state": "value",
                    "support_fact": fact,
                    "source_datum": field.datum,
                    "datum_support_fact": f"{fact}.datum" if field.datum_support else None,
                }
            )
        rows.extend(
            {"provider_id": "ch_foen", "station_id": station, "attribute_role": role, "state": "no_metadata"}
            for role in ATTRIBUTE_ROLES
            if role not in exposed
        )
    result = pl.DataFrame(rows, schema=SOURCE_METADATA_SCHEMA)
    return source_metadata_frame(stations.select(pl.lit("ch_foen").alias("provider_id"), "station_id"), result)


@dataclass(frozen=True, slots=True)
class StationMetadataSources:
    """Validated original bodies and their identities for a FOEN metadata build.

    Bodies are omitted from repr. The publication boundary also checks member
    digests against its independently selected archive inputs.
    """

    directory_body: bytes = dataclass_field(repr=False)
    directory_reference: RecordingReference
    station_pages: Mapping[str, bytes] = dataclass_field(repr=False)
    page_recordings: tuple[RecordingReference, ...]
    member_digests: Mapping[str, frozenset[str]] = dataclass_field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "station_pages", MappingProxyType(dict(self.station_pages)))
        object.__setattr__(self, "member_digests", MappingProxyType(dict(self.member_digests)))


def read_station_metadata_sources(
    evidence_root: Path,
    *,
    directory_reference: RecordingReference,
    input_receipt: RetainedInputReceipt,
    page_root: str,
    manifest_sha256: str,
) -> StationMetadataSources:
    """Read explicit retained originals; verify their receipt and manifest links.

    ``input_receipt`` supplies independently selected archive member identities.
    Every consumed file must match that receipt through the shared retained-input
    verifier. ``page_root`` is the repository-relative consumer directory. Its
    documents manifest is also pinned by ``manifest_sha256``. Receipts retain their original
    body filenames; adopted body bytes are read from the explicit ``body`` path.
    This function does not make requests or discover archive credentials.
    """
    if Path(page_root).is_absolute() or ".." in Path(page_root).parts or "\\" in page_root:
        raise FatalContractError("FOEN page consumer root must be a relative path")
    selected = {reference.consumer_path: reference for reference in input_receipt.inputs}

    def verify_paths(paths: Sequence[str]) -> None:
        if not set(paths) <= selected.keys():
            raise FatalContractError("FOEN metadata files are absent from the selected archive inputs")
        verify_retained_input_files(
            input_receipt.model_copy(
                update={
                    "inputs": tuple(selected[path] for path in paths),
                    "declaration_inputs": (),
                    "support_inputs": (),
                }
            ),
            evidence_root,
        )

    directory_receipt_path = str(Path(directory_reference.repository_path).with_name("receipt.json"))
    verify_paths(
        (
            directory_reference.repository_path,
            directory_receipt_path,
            f"{page_root}/documents.json",
            f"{page_root}/acquisition-run.json",
        )
    )
    directory_path = evidence_root / directory_reference.repository_path
    directory_body = directory_path.read_bytes()
    if hashlib.sha256(directory_body).hexdigest() != directory_reference.sha256:
        raise FatalContractError("FOEN directory original differs from its declared byte identity")
    directory_receipt = directory_path.with_name("receipt.json").read_bytes()
    _, directory_time, directory_type = _response_receipt(
        directory_receipt, directory_body, directory_reference.source_url
    )
    if (directory_time, directory_type) != (directory_reference.retrieved_at, directory_reference.media_type):
        raise FatalContractError("FOEN directory acquisition differs from its declared reference")
    root = evidence_root / page_root
    manifest_bytes = (root / "documents.json").read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != manifest_sha256:
        raise FatalContractError("FOEN page manifest differs from its selected byte identity")
    try:
        documents = json.loads(manifest_bytes)
    except (ValueError, TypeError) as error:
        raise FatalContractError("FOEN page manifest is not valid JSON") from error
    if not isinstance(documents, list) or not documents:
        raise FatalContractError("FOEN page manifest must contain selected station documents")
    campaign_bytes = (root / "acquisition-run.json").read_bytes()
    try:
        campaign = json.loads(campaign_bytes)
    except (ValueError, TypeError) as error:
        raise FatalContractError("FOEN campaign identity is not valid JSON") from error
    if not isinstance(campaign, dict) or campaign.get("manifest_sha256") != manifest_sha256:
        raise FatalContractError("FOEN campaign does not identify the selected page manifest")
    origin = urlsplit(directory_reference.source_url)
    if (origin.scheme, origin.netloc) != ("https", "www.hydrodaten.admin.ch") or origin.query or origin.fragment:
        raise FatalContractError("FOEN directory requires its declared publisher origin")
    pages: dict[str, bytes] = {}
    recordings = []
    digests = {hashlib.sha256(manifest_bytes).hexdigest(), hashlib.sha256(campaign_bytes).hexdigest()}
    for document in documents:
        if not isinstance(document, dict):
            raise FatalContractError("FOEN page manifest contains an invalid document")
        station = document.get("station_id")
        identity = document.get("id")
        if (
            document.get("provider") != "ch_foen"
            or not isinstance(station, str)
            or not station
            or station in {".", ".."}
            or "/" in station
            or "\\" in station
            or station in pages
            or not isinstance(identity, str)
            or not identity.strip()
            or identity in {".", ".."}
            or "/" in identity
            or "\\" in identity
        ):
            raise FatalContractError("FOEN page manifest has invalid or duplicate station identities")
        source_url = f"{origin.scheme}://{origin.netloc}/en/seen-und-fluesse/stations/{station}"
        parsed_url = urlsplit(source_url)
        if document.get("url") != source_url or parsed_url.query or parsed_url.fragment:
            raise FatalContractError("FOEN page manifest has an unsupported source origin or station URL")
        verify_paths((f"{page_root}/{identity}/body", f"{page_root}/{identity}/receipt.json"))
        body = (root / identity / "body").read_bytes()
        receipt_bytes = (root / identity / "receipt.json").read_bytes()
        receipt, retrieved_at, media_type = _response_receipt(receipt_bytes, body, source_url)
        if receipt.get("document") != document:
            raise FatalContractError("FOEN page receipt does not identify its selected manifest document")
        recordings.append(
            RecordingReference(
                recording_id=identity,
                repository_path=f"{page_root}/{identity}/body",
                source_url=source_url,
                retrieved_at=retrieved_at,
                media_type=media_type,
                sha256=hashlib.sha256(body).hexdigest(),
            )
        )
        pages[station] = body
        digests.update((hashlib.sha256(body).hexdigest(), hashlib.sha256(receipt_bytes).hexdigest()))
    if len({item.recording_id for item in recordings}) != len(recordings):
        raise FatalContractError("FOEN page manifest has duplicate recording identities")
    return StationMetadataSources(
        directory_body=directory_body,
        directory_reference=directory_reference,
        station_pages=pages,
        page_recordings=tuple(recordings),
        member_digests={
            "source.station.foen_directory_identity_and_names": frozenset(
                (directory_reference.sha256, hashlib.sha256(directory_receipt).hexdigest())
            ),
            "source.station.foen_reference_altitude_and_catchment": frozenset(digests),
        },
    )


def _response_receipt(receipt_bytes: bytes, body: bytes, source_url: str) -> tuple[dict, datetime, str]:
    try:
        receipt = json.loads(receipt_bytes)
        if (
            not isinstance(receipt, dict)
            or receipt.get("fresh_acquisition") is not True
            or receipt.get("stopped") != "terminal_response"
        ):
            raise ValueError("invalid receipt state")
        hops = receipt["hops"]
        if not isinstance(hops, list) or len(hops) != 1 or not isinstance(hops[0], dict):
            raise ValueError("invalid receipt hops")
        hop = hops[0]
        if (
            hop.get("hop") != 0
            or hop.get("status") != 200
            or hop.get("executed_url") != source_url
            or hop.get("requested_url") != source_url
            or hop.get("sha256") != hashlib.sha256(body).hexdigest()
            or type(hop.get("byte_size")) is not int
            or hop["byte_size"] != len(body)
        ):
            raise ValueError("receipt identity mismatch")
        headers = hop["headers"]
        if not isinstance(headers, dict):
            raise ValueError("invalid headers")
        content_types = [value for name, value in headers.items() if name.lower() == "content-type"]
        if (
            len(content_types) != 1
            or not isinstance(content_types[0], str)
            or not content_types[0].lower().startswith("text/html")
        ):
            raise ValueError("invalid content type")
        retrieved_at = datetime.fromisoformat(hop["body_received_at"])
        if retrieved_at.tzinfo is None:
            raise ValueError("missing acquisition time zone")
        body.decode("utf-8", errors="strict")
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise FatalContractError("FOEN metadata receipt or original violates its acquisition identity") from error
    return receipt, retrieved_at, content_types[0]


def verify_adopted_station_metadata(sources: StationMetadataSources, inputs: Sequence[RetainedInputUse]) -> None:
    """Reject source bodies or receipts outside the independently selected inputs."""
    directory_fact = "source.station.foen_directory_identity_and_names"
    page_fact = "source.station.foen_reference_altitude_and_catchment"
    if set(sources.member_digests) != {directory_fact, page_fact} or not all(sources.member_digests.values()):
        raise FatalContractError("FOEN metadata source identities are incomplete")
    directory_digest = hashlib.sha256(sources.directory_body).hexdigest()
    if (
        directory_digest != sources.directory_reference.sha256
        or directory_digest not in sources.member_digests[directory_fact]
    ):
        raise FatalContractError("FOEN directory bytes differ from their validated identity")
    references = {urlsplit(item.source_url).path.rsplit("/", 1)[-1]: item for item in sources.page_recordings}
    if len(references) != len(sources.page_recordings) or set(references) != set(sources.station_pages):
        raise FatalContractError("FOEN station page identities are incomplete")
    for station, body in sources.station_pages.items():
        digest = hashlib.sha256(body).hexdigest()
        if digest != references[station].sha256 or digest not in sources.member_digests[page_fact]:
            raise FatalContractError("FOEN page bytes differ from their validated identity")
    for fact, digests in sources.member_digests.items():
        adopted = {item.reference.sha256 for item in inputs if fact in item.facts and item.usage != "native_table"}
        if not digests <= adopted:
            raise FatalContractError("FOEN metadata originals and receipts must match adopted archive members")
