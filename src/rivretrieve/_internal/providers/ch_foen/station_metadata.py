"""Preserve FOEN station-directory attributes and station-information text."""

from __future__ import annotations

import json
from collections.abc import Mapping
from html.parser import HTMLParser

import polars as pl

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
            if tag == "dt":
                self.label = []
                self.pending_label = None
            elif tag == "dd" and self.pending_label in _FIELDS:
                self.value = []
            elif self.pending_label in _FIELDS:
                raise FatalContractError("FOEN station information label lacks its immediate value")
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
