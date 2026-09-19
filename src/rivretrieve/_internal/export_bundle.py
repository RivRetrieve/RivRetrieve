"""Versioned, self-contained exports of selection intent and retrieved source evidence."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

import polars as pl
from pydantic import TypeAdapter

from rivretrieve._internal.catalogues.evidence import CatalogueEvidence
from rivretrieve._internal.engine import SourceCallOrigin, SourceQuery, UnknownOriginFact, UnknownOriginReason
from rivretrieve._internal.issues import Issue
from rivretrieve._internal.observations import (
    ObservationProvenance,
    ObservationResult,
    ReceiptAuthorship,
    ReceiptEntry,
    Receipts,
    StoreExcerptReceipt,
)
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.selection import StationLocation, _EmptyReason, _Selection
from rivretrieve._internal.source_series import InventorySnapshot, RetrievalOutcome, SeriesScope, SourceSeries

_FORMAT = "rivretrieve-source-series"
_VERSION = 1
_PROVENANCE_VALUES = ("request", "calls_made", "time_windows", "query")


def _json(data: object) -> bytes:
    return json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate bundle field: {key}")
        result[key] = value
    return result


def _origin_value(value: object) -> dict[str, object]:
    if isinstance(value, UnknownOriginFact):
        return {"kind": "unknown", "value": value.reason.value}
    if isinstance(value, datetime):
        return {"kind": "datetime", "value": value.isoformat()}
    if isinstance(value, SourceQuery):
        return {
            "kind": "query",
            "statement": value.statement,
            "parameters": [_origin_value(item) for item in value.parameters],
        }
    if isinstance(value, bytes):
        return {"kind": "bytes", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (tuple, list)):
        return {
            "kind": "tuple" if isinstance(value, tuple) else "list",
            "value": [_origin_value(item) for item in value],
        }
    if isinstance(value, Mapping):
        return {"kind": "mapping", "value": {key: _origin_value(item) for key, item in value.items()}}
    if value is None or isinstance(value, (str, int, float)):
        return {"kind": "scalar", "value": value}
    raise TypeError(f"Unsupported origin value: {type(value).__name__}")


def _read_origin_value(data):
    kind = data["kind"]
    if kind == "unknown":
        return UnknownOriginFact(UnknownOriginReason(data["value"]))
    if kind == "datetime":
        return datetime.fromisoformat(data["value"])
    if kind == "bytes":
        return base64.b64decode(data["value"], validate=True)
    if kind == "query":
        return SourceQuery(data["statement"], tuple(_read_origin_value(item) for item in data["parameters"]))
    if kind == "mapping":
        return {key: _read_origin_value(item) for key, item in data["value"].items()}
    if kind in ("tuple", "list"):
        values = [_read_origin_value(item) for item in data["value"]]
        return tuple(values) if kind == "tuple" else values
    if kind == "scalar":
        value = data["value"]
        if value is not None and not isinstance(value, (str, int, float)):
            raise ValueError("Invalid source-call scalar")
        return value
    raise ValueError("Unknown source-call value format")


def _write_entry(archive: ZipFile, name: str, content: bytes) -> None:
    # ZIP container timestamps are not acquisition evidence. Keep them fixed so
    # unchanged source evidence has a reproducible export representation.
    entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = ZIP_DEFLATED
    entry.create_system = 3
    archive.writestr(entry, content)


def encode_bundle(value: _Selection | ObservationResult) -> bytes:
    """Encode exact metadata and receipt bytes; observation arrays retain their Parquet schema."""
    if not isinstance(value, (_Selection, ObservationResult)):
        raise TypeError("to_bundle requires a selection or observation result")
    selected = isinstance(value, _Selection)
    definitions = value.known_series if selected else value.source_series
    manifest = {
        "format": _FORMAT,
        "version": _VERSION,
        "kind": "selection" if selected else "result",
        "scope": value.scope.model_dump(mode="json"),
        "series": [item.model_dump(mode="json") for item in definitions],
        "inventories": [item.model_dump(mode="json") for item in value.inventories],
        "issues": [item.model_dump(mode="json") for item in value.issues],
    }
    destination = BytesIO()
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        if isinstance(value, _Selection):
            manifest.update(
                {
                    "locations": [asdict(item) for item in value.locations],
                    "catalogue_evidence": [json.loads(item.model_dump_json()) for item in value.acquisition_provenance],
                    "empty_reason": asdict(value.empty_reason) if value.empty_reason is not None else None,
                }
            )
        else:
            data = BytesIO()
            value.data.write_parquet(data)
            _write_entry(archive, "observations.parquet", data.getvalue())
            manifest.update(
                {
                    "view_scope": value.view_scope.model_dump(mode="json") if value.view_scope is not None else None,
                    "outcomes": [item.model_dump(mode="json") for item in value.outcomes],
                    "provenance": json.loads(value.provenance.model_dump_json(exclude=set(_PROVENANCE_VALUES))),
                    "provenance_values": {
                        name: _origin_value(getattr(value.provenance, name)) for name in _PROVENANCE_VALUES
                    },
                    "receipt_provider": str(value.receipts.provider_id),
                    "receipts": [],
                }
            )
            receipts = []
            for index, receipt in enumerate(value.receipts.entries):
                name = f"receipts/{index}.bin"
                _write_entry(archive, name, receipt.content)
                item: dict[str, object] = {
                    "file": name,
                    "authorship": receipt.authorship.value,
                    "origin": {
                        name: _origin_value(getattr(receipt.origin, name))
                        for name in SourceCallOrigin.__dataclass_fields__
                    },
                }
                if isinstance(receipt, StoreExcerptReceipt):
                    item.update(
                        {
                            "store_path": str(receipt.store_path),
                            "format_version": receipt.format_version,
                            "source_vintage": receipt.source_vintage.isoformat()
                            if receipt.source_vintage is not None
                            else None,
                            "executed_query": json.loads(
                                TypeAdapter(type(receipt.executed_query)).dump_json(receipt.executed_query)
                            ),
                        }
                    )
                receipts.append(item)
            manifest["receipts"] = receipts
        _write_entry(archive, "manifest.json", _json(manifest))
    return destination.getvalue()


def decode_bundle(content: bytes) -> _Selection | ObservationResult:
    """Validate imported identity, facts and format without consulting current catalogues."""
    if type(content) is not bytes:
        raise TypeError("from_bundle requires versioned bundle bytes")
    try:
        archive = ZipFile(BytesIO(content))
    except BadZipFile as error:
        raise ValueError("Invalid versioned source-series bundle format") from error
    with archive:
        if archive.namelist().count("manifest.json") != 1 or len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError("Bundle requires unique files and one manifest")
        manifest = json.loads(archive.read("manifest.json"), object_pairs_hook=_unique_object)
        if (
            manifest.get("format") != _FORMAT
            or type(manifest.get("version")) is not int
            or manifest["version"] != _VERSION
        ):
            raise ValueError("Unsupported source-series bundle format version; export/refetch explicitly")
        kind = manifest.get("kind")
        if kind not in ("selection", "result"):
            raise ValueError("Unknown source-series bundle kind")
        fields = {"format", "version", "kind", "scope", "series", "inventories", "issues"}
        fields.update(
            {"locations", "catalogue_evidence", "empty_reason"}
            if kind == "selection"
            else {"view_scope", "outcomes", "provenance", "provenance_values", "receipt_provider", "receipts"}
        )
        if set(manifest) != fields:
            raise ValueError("Bundle manifest does not match its declared format schema")
        definitions = tuple(SourceSeries.model_validate(item) for item in manifest["series"])
        definition_ids = {item.series_id for item in definitions}
        physical_facts = {}
        for definition in definitions:
            for facts in definition.facts:
                previous = physical_facts.get(facts.facts_id)
                if previous is not None and previous != facts:
                    raise ValueError("Bundle redefines physical facts under one fact-segment identity")
                physical_facts[facts.facts_id] = facts
        if len(definition_ids) != len(definitions):
            raise ValueError("Bundle contains duplicate source-series identities")
        scope = SeriesScope.model_validate(manifest["scope"])
        inventories = tuple(InventorySnapshot.model_validate(item) for item in manifest["inventories"])
        if any(member not in definition_ids for inventory in inventories for member in inventory.members):
            raise ValueError("Bundle inventory references a missing source-series definition")
        definitions_by_id = {item.series_id: item for item in definitions}
        for inventory in inventories:
            for member, fact_ids in inventory.member_facts:
                available = {facts.facts_id for facts in definitions_by_id[member].facts}
                if not set(fact_ids).issubset(available):
                    raise ValueError("Bundle inventory references missing physical facts for its source-series member")
        issues = tuple(Issue.model_validate(item) for item in manifest["issues"])
        if kind == "selection":
            if set(archive.namelist()) != {"manifest.json"}:
                raise ValueError("Selection bundle contains unexpected files")
            reason = (
                TypeAdapter(_EmptyReason).validate_json(_json(manifest["empty_reason"]))
                if manifest["empty_reason"] is not None
                else None
            )
            return _Selection(
                scope=scope,
                known_series=definitions,
                inventories=inventories,
                issues=issues,
                locations=tuple(
                    TypeAdapter(StationLocation).validate_json(_json(item)) for item in manifest["locations"]
                ),
                acquisition_provenance=tuple(
                    CatalogueEvidence.model_validate_json(_json(item)) for item in manifest["catalogue_evidence"]
                ),
                empty_reason=reason,
            )
        receipt_files = [item["file"] for item in manifest["receipts"]]
        if set(archive.namelist()) != {"manifest.json", "observations.parquet", *receipt_files} or len(
            set(receipt_files)
        ) != len(receipt_files):
            raise ValueError("Result bundle receipt inventory does not match its files")
        receipts = []
        for item in manifest["receipts"]:
            origin = SourceCallOrigin(**{name: _read_origin_value(value) for name, value in item["origin"].items()})
            authorship = ReceiptAuthorship(item["authorship"])
            if authorship is ReceiptAuthorship.STORE_EXCERPT:
                from datetime import date

                from rivretrieve._internal.store.reader import ExecutedStoreQuery
                from rivretrieve._internal.store.validation import StoreRoot

                receipt = StoreExcerptReceipt(
                    content=archive.read(item["file"]),
                    origin=origin,
                    authorship=authorship,
                    store_path=StoreRoot(Path(item["store_path"])),
                    executed_query=TypeAdapter(ExecutedStoreQuery).validate_json(_json(item["executed_query"])),
                    format_version=item["format_version"],
                    source_vintage=date.fromisoformat(item["source_vintage"])
                    if item["source_vintage"] is not None
                    else None,
                )
            else:
                receipt = ReceiptEntry(content=archive.read(item["file"]), origin=origin, authorship=authorship)
            receipts.append(receipt)
        provenance = ObservationProvenance.model_validate_json(_json(manifest["provenance"]))
        if set(manifest["provenance_values"]) != set(_PROVENANCE_VALUES):
            raise ValueError("Bundle provenance type information does not match its schema")
        provenance = ObservationProvenance.model_validate(
            {
                **provenance.model_dump(mode="python"),
                **{name: _read_origin_value(value) for name, value in manifest["provenance_values"].items()},
            }
        )
        return ObservationResult(
            data=pl.read_parquet(BytesIO(archive.read("observations.parquet"))),
            provenance=provenance,
            receipts=Receipts(provider_id=ProviderId(manifest["receipt_provider"]), entries=tuple(receipts)),
            source_series=definitions,
            scope=scope,
            view_scope=SeriesScope.model_validate(manifest["view_scope"])
            if manifest["view_scope"] is not None
            else None,
            inventories=inventories,
            outcomes=tuple(RetrievalOutcome.model_validate(item) for item in manifest["outcomes"]),
            issues=issues,
        )
