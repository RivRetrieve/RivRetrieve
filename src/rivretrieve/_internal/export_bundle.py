"""Versioned, self-contained exports of selection intent and retrieved source evidence."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from dataclasses import asdict
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import TypeIs, cast
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

import polars as pl
from pydantic import TypeAdapter, ValidationError

from rivretrieve._internal.catalogues.evidence import CatalogueEvidence
from rivretrieve._internal.engine import SourceCallOrigin, SourceQuery, UnknownOriginFact, UnknownOriginReason
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.observations import (
    ObservationProvenance,
    ObservationResult,
    ReceiptAuthorship,
    ReceiptEntry,
    Receipts,
    StoreExcerptReceipt,
)
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.publication_identity import publication_identity_fields
from rivretrieve._internal.selection import StationLocation, _EmptyReason, _Selection
from rivretrieve._internal.source_annotations import (
    AnnotationBundle,
    AnnotationSchema,
    AnnotationScope,
    ObservationAnnotationTable,
    SeriesAnnotationTable,
    dump_annotation_schema,
    dump_series_annotations,
    load_annotation_schema,
    load_series_annotations,
    with_annotations,
)
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    PhysicalFacts,
    RestrictionKind,
    RetrievalOutcome,
    ScopeState,
    SeriesScope,
    SourceIdentity,
    SourceSeries,
)

_FORMAT = "rivretrieve-source-series"
_VERSION = 4
_PROVENANCE_VALUES = ("request", "calls_made", "time_windows", "query")
_EMPTY_REASON_ADAPTER = TypeAdapter(_EmptyReason)
_STATION_LOCATION_ADAPTER = TypeAdapter(StationLocation)
_LOCATION_KEYS = frozenset({"provider_id", "station_id", "latitude", "longitude", "crs"})
_IDENTITY_ORIGINS = frozenset({"catalogue", "response", "mapping"})
_SERIES_KEYS = frozenset({"series_id", "provider_id", "station_id", "product_id", "identity", "variant", "facts"})
_IDENTITY_KEYS = frozenset({"namespace", "published_id", "description", "origin", "evidence"})
_SCOPE_KEYS = frozenset(
    {"state", "provider_ids", "station_ids", "product_ids", "predicates", "restriction", "variants", "series_ids"}
)
_INVENTORY_KEYS = frozenset(
    {
        "snapshot_id",
        "scope",
        "members",
        "member_facts",
        "completeness",
        "access",
        "origin",
        "acquired_at",
        "catalogue_check_date",
        "catalogue_claims",
        "window",
        "evidence",
        "reason",
    }
)
_INVENTORY_ORIGINS = frozenset({"catalogue", "response", "compiled"})
_COMPLETENESS_MAP = {item.value: item for item in InventoryCompleteness}


def _json(data: object) -> bytes:
    return json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _unique_object(pairs):
    result = dict(pairs)
    if len(result) == len(pairs):
        return result
    seen = set()
    for key, _ in pairs:
        if key in seen:
            raise ValueError(f"Duplicate bundle field: {key}")
        seen.add(key)
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


def _publication_identity(manifest: dict) -> dict[str, str]:
    """Resolve provider identity from data and retained acquisition context."""
    providers = set(manifest.get("scope", {}).get("provider_ids", ()))
    providers.update(item.get("provider_id") for item in manifest.get("series", ()))
    providers.add(manifest.get("receipt_provider"))
    providers.add(manifest.get("provenance", {}).get("provider_id"))
    providers.update(item.get("provider_id") for item in manifest.get("locations", ()))
    for item in manifest.get("inventories", ()):
        providers.update(item.get("scope", {}).get("provider_ids", ()))
    providers.update(item.get("header", {}).get("provider_id") for item in manifest.get("catalogue_evidence", ()))
    return publication_identity_fields(provider for provider in providers if isinstance(provider, str))


def _dump_series(definitions: tuple[SourceSeries, ...]) -> list[dict[str, object]]:
    facts_cache: dict[int, dict[str, object]] = {}
    out: list[dict[str, object]] = []
    for item in definitions:
        ident = item.identity
        dumped_facts: list[dict[str, object]] = []
        for f in item.facts:
            fid_key = id(f)
            dumped = facts_cache.get(fid_key)
            if dumped is None:
                dumped = f.model_dump(mode="json")
                facts_cache[fid_key] = dumped
            dumped_facts.append(dumped)
        out.append(
            {
                "series_id": item.series_id,
                "provider_id": item.provider_id,
                "station_id": item.station_id,
                "product_id": item.product_id,
                "identity": {
                    "namespace": ident.namespace,
                    "published_id": ident.published_id,
                    "description": ident.description,
                    "origin": ident.origin,
                    "evidence": list(ident.evidence),
                },
                "variant": item.variant,
                "facts": dumped_facts,
            }
        )
    return out


def _dump_inventories(inventories: tuple[InventorySnapshot, ...]) -> list[dict[str, object]]:
    date_cache: dict[date, str] = {}
    out: list[dict[str, object]] = []
    for item in inventories:
        s = item.scope
        if not s.predicates and not item.catalogue_claims and item.window is None and not item.member_facts:
            chk = item.catalogue_check_date
            if chk is None:
                chk_str = None
            else:
                chk_str = date_cache.get(chk)
                if chk_str is None:
                    chk_str = chk.isoformat()
                    date_cache[chk] = chk_str
            out.append(
                {
                    "snapshot_id": item.snapshot_id,
                    "scope": {
                        "state": s.state.value,
                        "provider_ids": list(s.provider_ids),
                        "station_ids": list(s.station_ids),
                        "product_ids": list(s.product_ids),
                        "predicates": [],
                        "restriction": s.restriction.value,
                        "variants": list(s.variants),
                        "series_ids": list(s.series_ids),
                    },
                    "members": list(item.members),
                    "member_facts": [],
                    "completeness": item.completeness.value,
                    "access": item.access,
                    "origin": item.origin,
                    "acquired_at": item.acquired_at.isoformat() if item.acquired_at is not None else None,
                    "catalogue_check_date": chk_str,
                    "catalogue_claims": [],
                    "window": None,
                    "evidence": list(item.evidence),
                    "reason": item.reason,
                }
            )
        else:
            out.append(item.model_dump(mode="json"))
    return out


def _is_plain_dict(val: object) -> TypeIs[dict[str, object]]:
    return type(val) is dict


def _is_str_list(val: object) -> TypeIs[list[str]]:
    return type(val) is list and all(type(x) is str for x in val)


def _is_json_number(val: object) -> TypeIs[int | float]:
    return type(val) in (float, int)


def _decode_series_list(raw_series: list[object]) -> tuple[SourceSeries, ...]:
    facts_by_id: dict[str, tuple[dict[str, object], PhysicalFacts]] = {}
    out: list[SourceSeries] = []
    for item in raw_series:
        if _is_plain_dict(item) and len(item) == 7 and _SERIES_KEYS.issuperset(item):
            sid = item["series_id"]
            prov = item["provider_id"]
            stat = item["station_id"]
            prod = item["product_id"]
            ident_raw = item["identity"]
            variant = item["variant"]
            facts_raw = item["facts"]
            if (
                type(sid) is str
                and sid
                and type(prov) is str
                and prov
                and type(stat) is str
                and stat
                and type(prod) is str
                and prod
                and (variant is None or type(variant) is str)
                and _is_plain_dict(ident_raw)
                and len(ident_raw) == 5
                and _IDENTITY_KEYS.issuperset(ident_raw)
                and type(facts_raw) is list
                and len(facts_raw) >= 1
            ):
                ns = ident_raw["namespace"]
                pub_id = ident_raw["published_id"]
                desc = ident_raw["description"]
                orig = ident_raw["origin"]
                ev = ident_raw["evidence"]
                if (
                    type(ns) is str
                    and ns
                    and (pub_id is None or type(pub_id) is str)
                    and (desc is None or type(desc) is str)
                    and type(orig) is str
                    and orig in _IDENTITY_ORIGINS
                    and _is_str_list(ev)
                    and len(ev) >= 1
                ):
                    parsed_facts: list[PhysicalFacts] = []
                    fast_ok = True
                    for f_raw in facts_raw:
                        if not _is_plain_dict(f_raw):
                            fast_ok = False
                            break
                        fid = f_raw.get("facts_id")
                        if type(fid) is not str:
                            fast_ok = False
                            break
                        cached = facts_by_id.get(fid)
                        if cached is not None and cached[0] == f_raw:
                            pf = cached[1]
                        else:
                            pf = PhysicalFacts.model_validate(f_raw)
                            if cached is None:
                                facts_by_id[fid] = (f_raw, pf)
                        u_def = pf.source_unit_definition
                        if u_def is not None and (u_def.provider_id != prov or u_def.namespace != ns):
                            fast_ok = False
                            break
                        parsed_facts.append(pf)
                    if fast_ok and (
                        len(parsed_facts) == 1 or len({f.facts_id for f in parsed_facts}) == len(parsed_facts)
                    ):
                        identity_obj = SourceIdentity.model_construct(
                            namespace=ns,
                            published_id=pub_id,
                            description=desc,
                            origin=orig,
                            evidence=tuple(ev),
                        )
                        out.append(
                            SourceSeries.model_construct(
                                series_id=sid,
                                provider_id=prov,
                                station_id=stat,
                                product_id=prod,
                                identity=identity_obj,
                                variant=variant,
                                facts=tuple(parsed_facts),
                            )
                        )
                        continue
        out.append(SourceSeries.model_validate(item))
    return tuple(out)


def _decode_inventories_list(raw_inventories: list[object]) -> tuple[InventorySnapshot, ...]:
    date_cache: dict[str, date] = {}
    out: list[InventorySnapshot] = []
    for item in raw_inventories:
        if _is_plain_dict(item) and len(item) == 13 and _INVENTORY_KEYS.issuperset(item):
            snap_id = item["snapshot_id"]
            s_raw = item["scope"]
            members = item["members"]
            m_facts = item["member_facts"]
            comp_raw = item["completeness"]
            access = item["access"]
            orig = item["origin"]
            acq_at = item["acquired_at"]
            chk_raw = item["catalogue_check_date"]
            claims = item["catalogue_claims"]
            win = item["window"]
            ev = item["evidence"]
            reason = item["reason"]
            comp = _COMPLETENESS_MAP.get(comp_raw) if type(comp_raw) is str else None
            if (
                type(snap_id) is str
                and snap_id
                and type(access) is str
                and access
                and type(orig) is str
                and orig in _INVENTORY_ORIGINS
                and comp is not None
                and (comp is InventoryCompleteness.COMPLETE or (type(reason) is str and bool(reason)))
                and (reason is None or type(reason) is str)
                and acq_at is None
                and win is None
                and m_facts == []
                and claims == []
                and _is_str_list(members)
                and (len(members) <= 1 or len(set(members)) == len(members))
                and _is_str_list(ev)
                and len(ev) >= 1
                and (
                    chk_raw is None
                    or (type(chk_raw) is str and len(chk_raw) == 10 and chk_raw[4] == "-" and chk_raw[7] == "-")
                )
                and _is_plain_dict(s_raw)
                and len(s_raw) == 8
                and _SCOPE_KEYS.issuperset(s_raw)
                and s_raw["state"] == "active"
                and s_raw["restriction"] == "all"
                and s_raw["predicates"] == []
                and s_raw["variants"] == []
                and s_raw["series_ids"] == []
            ):
                s_provs = s_raw["provider_ids"]
                s_stats = s_raw["station_ids"]
                s_prods = s_raw["product_ids"]
                if _is_str_list(s_provs) and _is_str_list(s_stats) and _is_str_list(s_prods):
                    chk_date: date | None = None
                    date_ok = True
                    if chk_raw is not None:
                        chk_date = date_cache.get(chk_raw)
                        if chk_date is None:
                            try:
                                chk_date = date.fromisoformat(chk_raw)
                            except ValueError:
                                date_ok = False
                            else:
                                date_cache[chk_raw] = chk_date
                    if date_ok:
                        scope_obj = SeriesScope.model_construct(
                            state=ScopeState.ACTIVE,
                            provider_ids=tuple(s_provs),
                            station_ids=tuple(s_stats),
                            product_ids=tuple(s_prods),
                            predicates=(),
                            restriction=RestrictionKind.ALL,
                            variants=(),
                            series_ids=(),
                        )
                        out.append(
                            InventorySnapshot.model_construct(
                                snapshot_id=snap_id,
                                scope=scope_obj,
                                members=tuple(members),
                                member_facts=(),
                                completeness=comp,
                                access=access,
                                origin=orig,
                                acquired_at=None,
                                catalogue_check_date=chk_date,
                                catalogue_claims=(),
                                window=None,
                                evidence=tuple(ev),
                                reason=reason,
                            )
                        )
                        continue
        out.append(InventorySnapshot.model_validate(item))
    return tuple(out)


def _decode_locations_list(raw_locations: list[object]) -> tuple[StationLocation, ...]:
    out: list[StationLocation] = []
    for item in raw_locations:
        if _is_plain_dict(item) and len(item) == 5 and _LOCATION_KEYS.issuperset(item):
            prov = item["provider_id"]
            sid = item["station_id"]
            lat = item["latitude"]
            lon = item["longitude"]
            crs = item["crs"]
            if (
                type(prov) is str
                and type(sid) is str
                and (lat is None or _is_json_number(lat))
                and (lon is None or _is_json_number(lon))
                and type(crs) is str
            ):
                out.append(
                    StationLocation(
                        prov,
                        sid,
                        float(lat) if lat is not None else None,
                        float(lon) if lon is not None else None,
                        crs,
                    )
                )
                continue
        out.append(_STATION_LOCATION_ADAPTER.validate_json(_json(item)))
    return tuple(out)


def encode_bundle(value: _Selection | ObservationResult) -> bytes:
    """Encode exact metadata and receipt bytes; observation arrays retain their Parquet schema."""
    if not isinstance(value, (_Selection, ObservationResult)):
        raise TypeError("to_bundle requires a selection or observation result")
    selected = isinstance(value, _Selection)
    definitions = value.known_series if selected else value.source_series
    manifest: dict[str, object] = {
        "format": _FORMAT,
        "version": _VERSION,
        "kind": "selection" if selected else "result",
        "scope": value.scope.model_dump(mode="json"),
        "series": _dump_series(definitions),
        "inventories": _dump_inventories(value.inventories),
        "issues": [item.model_dump(mode="json") for item in value.issues],
    }
    destination = BytesIO()
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        if isinstance(value, _Selection):
            ann_bundle = (
                value.series_annotations
                if isinstance(value.series_annotations, AnnotationBundle)
                else AnnotationBundle.empty()
            )
            schemas = ann_bundle.all_schemas()
            manifest.update(
                {
                    "locations": [
                        {
                            "provider_id": item.provider_id,
                            "station_id": item.station_id,
                            "latitude": item.latitude,
                            "longitude": item.longitude,
                            "crs": item.crs,
                        }
                        for item in value.locations
                    ],
                    "catalogue_evidence": [item.to_json_dict() for item in value.acquisition_provenance],
                    "empty_reason": asdict(value.empty_reason) if value.empty_reason is not None else None,
                    "annotation_schemas": [dump_annotation_schema(schema) for schema in schemas],
                    "series_annotations": dump_series_annotations(ann_bundle.series_tables),
                }
            )
        else:
            data = BytesIO()
            value.data.write_parquet(data)
            _write_entry(archive, "observations.parquet", data.getvalue())
            ann_bundle = value._annotations
            schemas = ann_bundle.all_schemas()
            ann_files: list[dict[str, str]] = []
            for schema_id, table in ann_bundle.observation_tables.items():
                if table.row_count == 0:
                    continue
                indices = [-1 if idx is None else idx for idx in table.measurement_indices]
                ann_frame = table.rows.with_columns(pl.Series("_measurement_index", indices, dtype=pl.Int64))
                ann_buf = BytesIO()
                ann_frame.write_parquet(ann_buf)
                ann_name = f"annotations/{schema_id}.parquet"
                _write_entry(archive, ann_name, ann_buf.getvalue())
                ann_files.append({"schema_id": schema_id, "file": ann_name})
            manifest.update(
                {
                    "view_scope": value.view_scope.model_dump(mode="json") if value.view_scope is not None else None,
                    "outcomes": [item.model_dump(mode="json") for item in value.outcomes],
                    "supporting_outcomes": [item.model_dump(mode="json") for item in value.supporting_outcomes],
                    "provenance": json.loads(value.provenance.model_dump_json(exclude=set(_PROVENANCE_VALUES))),
                    "provenance_values": {
                        name: _origin_value(getattr(value.provenance, name)) for name in _PROVENANCE_VALUES
                    },
                    "receipt_provider": str(value.receipts.provider_id),
                    "receipts": [],
                    "annotation_schemas": [dump_annotation_schema(schema) for schema in schemas],
                    "series_annotations": dump_series_annotations(ann_bundle.series_tables),
                    "annotation_files": ann_files,
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
        manifest.update(_publication_identity(manifest))
        _write_entry(archive, "manifest.json", _json(manifest))
    return destination.getvalue()


def _decode_bundle_annotations_metadata(
    manifest: dict[str, object],
    definition_ids: set[str],
) -> tuple[dict[str, AnnotationSchema], dict[str, SeriesAnnotationTable]]:
    raw_schemas = manifest["annotation_schemas"]
    if type(raw_schemas) is not list:
        raise ValueError("Bundle annotation_schemas must be a list")
    schemas_by_id: dict[str, AnnotationSchema] = {}
    for entry in raw_schemas:
        if type(entry) is not dict:
            raise ValueError("Bundle annotation schema entry must be an object")
        try:
            schema = load_annotation_schema(cast("dict[str, object]", entry))
        except (ValidationError, FatalContractError, ValueError, TypeError) as error:
            raise ValueError(f"Invalid bundle annotation schema: {error}") from error
        if schema.schema_id in schemas_by_id:
            raise ValueError(f"Bundle contains duplicate annotation schema {schema.schema_id!r}")
        schemas_by_id[schema.schema_id] = schema

    raw_series_ann = manifest["series_annotations"]
    if type(raw_series_ann) is not dict:
        raise ValueError("Bundle series_annotations must be an object")
    try:
        series_tables = load_series_annotations(cast("dict[str, object]", raw_series_ann), schemas_by_id)
    except (ValidationError, FatalContractError, ValueError, TypeError, KeyError, pl.exceptions.PolarsError) as error:
        raise ValueError(f"Invalid bundle series annotations: {error}") from error
    for table in series_tables:
        for sid in table.rows.get_column("series_id").to_list():
            if sid not in definition_ids:
                raise ValueError(f"Bundle series annotations reference unknown series {sid!r}")
    return schemas_by_id, {table.schema.schema_id: table for table in series_tables}


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
        fields = {
            "format",
            "version",
            "kind",
            "scope",
            "series",
            "inventories",
            "issues",
            "annotation_schemas",
            "series_annotations",
        }
        fields.update(
            {"locations", "catalogue_evidence", "empty_reason"}
            if kind == "selection"
            else {
                "view_scope",
                "outcomes",
                "supporting_outcomes",
                "provenance",
                "provenance_values",
                "receipt_provider",
                "receipts",
                "annotation_files",
            }
        )
        identity = _publication_identity(manifest)
        if any(manifest.get(field) != expected for field, expected in identity.items()):
            raise ValueError("Unsupported publication_service identity; export/refetch explicitly")
        fields.update(identity)
        if set(manifest) != fields:
            raise ValueError("Bundle manifest does not match its declared format schema")
        raw_series = manifest["series"]
        definitions = (
            _decode_series_list(raw_series)
            if type(raw_series) is list
            else tuple(SourceSeries.model_validate(item) for item in raw_series)
        )
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
        schemas_by_id, series_tables_by_id = _decode_bundle_annotations_metadata(manifest, definition_ids)
        scope = SeriesScope.model_validate(manifest["scope"])
        raw_inventories = manifest["inventories"]
        inventories = (
            _decode_inventories_list(raw_inventories)
            if type(raw_inventories) is list
            else tuple(InventorySnapshot.model_validate(item) for item in raw_inventories)
        )
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
                _EMPTY_REASON_ADAPTER.validate_json(_json(manifest["empty_reason"]))
                if manifest["empty_reason"] is not None
                else None
            )
            raw_locations = manifest["locations"]
            selection_annotations = AnnotationBundle(series_tables=series_tables_by_id) if series_tables_by_id else None
            return _Selection(
                scope=scope,
                known_series=definitions,
                inventories=inventories,
                issues=issues,
                locations=_decode_locations_list(raw_locations)
                if type(raw_locations) is list
                else tuple(_STATION_LOCATION_ADAPTER.validate_json(_json(item)) for item in raw_locations),
                acquisition_provenance=tuple(
                    CatalogueEvidence.from_parsed_json(item) for item in manifest["catalogue_evidence"]
                ),
                empty_reason=reason,
                series_annotations=selection_annotations,
            )
        raw_ann_files = manifest["annotation_files"]
        if type(raw_ann_files) is not list:
            raise ValueError("Bundle annotation_files must be a list")
        ann_entries: list[tuple[AnnotationSchema, str]] = []
        seen_ann_schemas: set[str] = set()
        for entry in raw_ann_files:
            if type(entry) is not dict or set(entry) != {"schema_id", "file"}:
                raise ValueError("Bundle annotation_files entry is malformed")
            schema_id = entry["schema_id"]
            ann_file = entry["file"]
            if type(schema_id) is not str or type(ann_file) is not str or schema_id in seen_ann_schemas:
                raise ValueError("Bundle annotation_files entry contains invalid or duplicate schema_id")
            schema = schemas_by_id.get(schema_id)
            if schema is None or schema.scope is not AnnotationScope.OBSERVATION:
                raise ValueError(f"Bundle annotation file references unknown observation schema {schema_id!r}")
            if ann_file != f"annotations/{schema_id}.parquet":
                raise ValueError(f"Bundle annotation file path is invalid: {ann_file!r}")
            seen_ann_schemas.add(schema_id)
            ann_entries.append((schema, ann_file))
        ann_file_names = [ann_file for _, ann_file in ann_entries]
        receipt_files = [item["file"] for item in manifest["receipts"]]
        if set(archive.namelist()) != {"manifest.json", "observations.parquet", *receipt_files, *ann_file_names} or len(
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
                from rivretrieve._internal.store.remote import RemoteStoreRoot
                from rivretrieve._internal.store.validation import StoreRoot

                raw_store_path = item["store_path"]
                parsed_store_path = (
                    RemoteStoreRoot.from_uri(raw_store_path)
                    if isinstance(raw_store_path, str) and raw_store_path.startswith("s3://")
                    else Path(raw_store_path)
                )
                receipt = StoreExcerptReceipt(
                    content=archive.read(item["file"]),
                    origin=origin,
                    authorship=authorship,
                    store_path=StoreRoot(parsed_store_path),
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
        try:
            data_frame = pl.read_parquet(BytesIO(archive.read("observations.parquet")))
        except (pl.exceptions.PolarsError, OSError, ValueError) as error:
            raise ValueError(f"Invalid bundle observations parquet: {error}") from error
        obs_tables: dict[str, ObservationAnnotationTable] = {}
        for schema, ann_file in ann_entries:
            try:
                ann_frame = pl.read_parquet(BytesIO(archive.read(ann_file)))
            except (pl.exceptions.PolarsError, OSError, ValueError) as error:
                raise ValueError(f"Invalid bundle annotation parquet {ann_file!r}: {error}") from error
            if "_measurement_index" not in ann_frame.columns:
                raise ValueError(f"Bundle annotation parquet {ann_file!r} lacks _measurement_index")
            idx_col = ann_frame.get_column("_measurement_index")
            if idx_col.dtype != pl.Int64 or idx_col.null_count() > 0:
                raise ValueError(f"Bundle annotation _measurement_index in {ann_file!r} must be non-null Int64")
            raw_indices = idx_col.to_list()
            if any(idx < -1 or idx >= data_frame.height for idx in raw_indices):
                raise ValueError(f"Bundle annotation _measurement_index out of bounds in {ann_file!r}")
            meas_indices = [None if idx == -1 else int(idx) for idx in raw_indices]
            try:
                obs_tables[schema.schema_id] = ObservationAnnotationTable.from_rows(
                    schema=schema,
                    rows=ann_frame.drop("_measurement_index"),
                    measurement_indices=meas_indices,
                )
            except (ValidationError, FatalContractError, ValueError, TypeError, pl.exceptions.PolarsError) as error:
                raise ValueError(
                    f"Invalid bundle observation annotation table {schema.schema_id!r}: {error}"
                ) from error
        result = ObservationResult(
            data=data_frame,
            provenance=provenance,
            receipts=Receipts(provider_id=ProviderId(manifest["receipt_provider"]), entries=tuple(receipts)),
            source_series=definitions,
            scope=scope,
            view_scope=SeriesScope.model_validate(manifest["view_scope"])
            if manifest["view_scope"] is not None
            else None,
            inventories=inventories,
            outcomes=tuple(RetrievalOutcome.model_validate(item) for item in manifest["outcomes"]),
            supporting_outcomes=tuple(
                RetrievalOutcome.model_validate(item) for item in manifest["supporting_outcomes"]
            ),
            issues=issues,
        )
        bundle = AnnotationBundle(
            observation_tables=obs_tables,
            series_tables=series_tables_by_id,
        )
        if not bundle.is_empty:
            try:
                result = with_annotations(result, bundle)
            except FatalContractError as error:
                raise ValueError(f"Bundle annotation linkage failed: {error}") from error
        return result
