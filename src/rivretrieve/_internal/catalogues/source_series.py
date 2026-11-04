"""Materialize source-series descriptions from a recorded catalogue snapshot."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Literal, cast

from pydantic import BaseModel, ConfigDict, model_validator

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.source_series import (
    _PLAIN_JSON_ASCII_FULLMATCH,
    CatalogueSeriesClaim,
    InventoryCompleteness,
    InventorySnapshot,
    PhysicalFacts,
    RestrictionKind,
    ScopeState,
    SeriesScope,
    SourceIdentity,
    SourceSeries,
    stable_id,
)

if TYPE_CHECKING:
    from datetime import date, datetime

    from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
    from rivretrieve._internal.source_series import PhysicalPredicate, SeriesWindow


class SourceDescription(BaseModel):
    """A source coordinate and its established facts, optionally station scoped."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    product_id: str
    station_id: str | None = None
    station_ids: tuple[str, ...] = ()
    series_id: str | None = None
    identity_key: tuple[str | None, ...] | None = None
    native_coordinate: str | None = None
    identity: SourceIdentity
    variant: str | None = None
    facts: tuple[PhysicalFacts, ...]

    @model_validator(mode="after")
    def _validate_description(self) -> SourceDescription:
        if not self.product_id or not self.facts:
            raise ValueError("Source description requires an access product and physical facts")
        if len({facts.facts_id for facts in self.facts}) != len(self.facts):
            raise ValueError("Source description requires unique physical-fact segments")
        if self.identity_key is not None and not self.identity_key:
            raise ValueError("Explicit source identity key cannot be empty")
        return self


class SourceDescriptions(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1
    claims_file: Literal["series_claims.parquet"] = "series_claims.parquet"
    provider_id: str
    descriptions: tuple[SourceDescription, ...]


class _ReferencedSourceDescriptions(BaseModel):
    """Disk representation that stores each identified physical-fact segment once."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[2]
    claims_file: Literal["series_claims.parquet"] = "series_claims.parquet"
    provider_id: str
    physical_facts: tuple[PhysicalFacts, ...]
    descriptions: tuple[dict[str, object], ...]


def encode_source_descriptions(value: SourceDescriptions, *, schema_version: Literal[1, 2] = 1) -> bytes:
    """Encode without changing identity, facts, evidence, or the in-memory schema."""
    if schema_version == 1:
        return (value.model_dump_json() + "\n").encode()
    if schema_version != 2:
        raise FatalContractError("Unsupported source-description encoding revision")
    facts_by_id: dict[str, PhysicalFacts] = {}
    descriptions = []
    for item in value.descriptions:
        for facts in item.facts:
            previous = facts_by_id.setdefault(facts.facts_id, facts)
            if previous != facts:
                raise FatalContractError(f"Conflicting physical facts for {facts.facts_id!r}")
        fields = item.model_dump(mode="json", exclude={"facts"}, exclude_defaults=True)
        fields["facts_ids"] = [facts.facts_id for facts in item.facts]
        descriptions.append(fields)
    encoded = _ReferencedSourceDescriptions(
        schema_version=2,
        provider_id=value.provider_id,
        claims_file=value.claims_file,
        physical_facts=tuple(facts_by_id.values()),
        descriptions=tuple(descriptions),
    )
    return (encoded.model_dump_json(exclude_defaults=True) + "\n").encode()


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) == len(pairs):
        return result
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            raise ValueError(f"Duplicate JSON object key: {key}")
        seen.add(key)
    return result


def decode_source_descriptions(content: bytes) -> SourceDescriptions:
    """Read both disk revisions; resolve strict references to shared fact instances."""
    try:
        raw = json.loads(content, object_pairs_hook=_unique_json_object)
        if not isinstance(raw, dict):
            raise ValueError("Source descriptions must be a JSON object")
        revision = raw.get("schema_version", 1)
        if type(revision) is not int:
            raise ValueError("Source-description schema revision must be an integer")
        if revision == 1:
            raw_descriptions = raw.get("descriptions")
            if isinstance(raw_descriptions, list) and len(raw_descriptions) > 1:
                facts_cache: dict[str, tuple[dict[str, object], PhysicalFacts]] = {}
                for desc in raw_descriptions:
                    if not isinstance(desc, dict):
                        break
                    raw_facts = desc.get("facts")
                    if not isinstance(raw_facts, list) or not raw_facts:
                        break
                    resolved_facts: list[object] = []
                    for fact_item in raw_facts:
                        if isinstance(fact_item, dict) and isinstance(fid := fact_item.get("facts_id"), str):
                            cached = facts_cache.get(fid)
                            if cached is not None and cached[0] == fact_item:
                                resolved_facts.append(cached[1])
                            else:
                                validated_fact = PhysicalFacts.model_validate(fact_item)
                                facts_cache[fid] = (fact_item, validated_fact)
                                resolved_facts.append(validated_fact)
                        else:
                            resolved_facts.append(fact_item)
                    desc["facts"] = resolved_facts
            return SourceDescriptions.model_validate(raw)
        if revision != 2:
            raise ValueError("Unsupported source-description encoding revision")
        stored = _ReferencedSourceDescriptions.model_validate(raw)
        facts_by_id = {facts.facts_id: facts for facts in stored.physical_facts}
        if len(facts_by_id) != len(stored.physical_facts):
            raise ValueError("Duplicate physical-fact identifiers")
        used = set()
        descriptions = []
        for item in stored.descriptions:
            fields = dict(item)
            references = fields.pop("facts_ids", None)
            if (
                not isinstance(references, list)
                or not references
                or any(not isinstance(ref, str) or not ref for ref in references)
            ):
                raise ValueError("Source description requires nonempty physical-fact references")
            references = cast("list[str]", references)
            if len(references) != len(set(references)):
                raise ValueError("Duplicate physical-fact references")
            if "facts" in fields:
                raise ValueError("Revision 2 descriptions must reference physical facts")
            if any(ref not in facts_by_id for ref in references):
                raise ValueError("Missing referenced physical facts")
            fields["facts"] = tuple(facts_by_id[ref] for ref in references)
            descriptions.append(SourceDescription.model_validate(fields))
            used.update(references)
        if used != facts_by_id.keys():
            raise ValueError("Unreferenced physical facts")
        return SourceDescriptions(
            provider_id=stored.provider_id, claims_file=stored.claims_file, descriptions=tuple(descriptions)
        )
    except (ValueError, TypeError) as exc:
        raise FatalContractError(f"Invalid source-series descriptions: {exc}") from exc


def catalogue_series(
    artifact: PackagedCatalogArtifact,
    *,
    scope: SeriesScope | None = None,
) -> tuple[tuple[SourceSeries, ...], tuple[InventorySnapshot, ...]]:
    """Expand routing coordinates only; physical/identity filters cannot rewrite inventory."""
    return materialize_series(artifact, scope=scope)


_ORIG_SOURCE_IDENTITY = SourceIdentity
_ORIG_CATALOGUE_CLAIM = CatalogueSeriesClaim
_ORIG_SOURCE_SERIES = SourceSeries
_ORIG_SERIES_SCOPE = SeriesScope
_ORIG_INVENTORY_SNAPSHOT = InventorySnapshot

_IDENT_FIELDS_SET = set(SourceIdentity.model_fields)
_CLAIM_FIELDS_SET = set(CatalogueSeriesClaim.model_fields)
_SERIES_FIELDS_SET = set(SourceSeries.model_fields)
_SCOPE_FIELDS_SET = set(SeriesScope.model_fields)
_INV_FIELDS_SET = set(InventorySnapshot.model_fields)


def _fast_ident(
    *,
    namespace: str,
    published_id: str | None,
    description: str | None,
    origin: Literal["catalogue", "response", "mapping"],
    evidence: tuple[str, ...],
) -> SourceIdentity:
    inst = object.__new__(_ORIG_SOURCE_IDENTITY)
    object.__setattr__(
        inst,
        "__dict__",
        {
            "namespace": namespace,
            "published_id": published_id,
            "description": description,
            "origin": origin,
            "evidence": evidence,
        },
    )
    object.__setattr__(inst, "__pydantic_fields_set__", _IDENT_FIELDS_SET.copy())
    object.__setattr__(inst, "__pydantic_extra__", None)
    object.__setattr__(inst, "__pydantic_private__", None)
    return inst


def _fast_claim(
    *,
    provider_id: str,
    station_id: str,
    product_id: str,
    identity: SourceIdentity,
    native_coordinates: tuple[tuple[str, str | None], ...],
) -> CatalogueSeriesClaim:
    inst = object.__new__(_ORIG_CATALOGUE_CLAIM)
    object.__setattr__(
        inst,
        "__dict__",
        {
            "provider_id": provider_id,
            "station_id": station_id,
            "product_id": product_id,
            "identity": identity,
            "native_coordinates": native_coordinates,
        },
    )
    object.__setattr__(inst, "__pydantic_fields_set__", _CLAIM_FIELDS_SET.copy())
    object.__setattr__(inst, "__pydantic_extra__", None)
    object.__setattr__(inst, "__pydantic_private__", None)
    return inst


def _fast_series(
    *,
    series_id: str,
    provider_id: str,
    station_id: str,
    product_id: str,
    identity: SourceIdentity,
    variant: str | None,
    facts: tuple[PhysicalFacts, ...],
) -> SourceSeries:
    inst = object.__new__(_ORIG_SOURCE_SERIES)
    object.__setattr__(
        inst,
        "__dict__",
        {
            "series_id": series_id,
            "provider_id": provider_id,
            "station_id": station_id,
            "product_id": product_id,
            "identity": identity,
            "variant": variant,
            "facts": facts,
        },
    )
    object.__setattr__(inst, "__pydantic_fields_set__", _SERIES_FIELDS_SET.copy())
    object.__setattr__(inst, "__pydantic_extra__", None)
    object.__setattr__(inst, "__pydantic_private__", None)
    return inst


def _fast_scope(
    *,
    state: ScopeState,
    provider_ids: tuple[str, ...],
    station_ids: tuple[str, ...],
    product_ids: tuple[str, ...],
    predicates: tuple[PhysicalPredicate, ...],
    restriction: RestrictionKind,
    variants: tuple[str, ...],
    series_ids: tuple[str, ...],
) -> SeriesScope:
    inst = object.__new__(_ORIG_SERIES_SCOPE)
    object.__setattr__(
        inst,
        "__dict__",
        {
            "state": state,
            "provider_ids": provider_ids,
            "station_ids": station_ids,
            "product_ids": product_ids,
            "predicates": predicates,
            "restriction": restriction,
            "variants": variants,
            "series_ids": series_ids,
        },
    )
    object.__setattr__(inst, "__pydantic_fields_set__", _SCOPE_FIELDS_SET.copy())
    object.__setattr__(inst, "__pydantic_extra__", None)
    object.__setattr__(inst, "__pydantic_private__", None)
    return inst


def _fast_inv(
    *,
    snapshot_id: str,
    scope: SeriesScope,
    members: tuple[str, ...],
    member_facts: tuple[tuple[str, tuple[str, ...]], ...],
    completeness: InventoryCompleteness,
    access: str,
    origin: Literal["catalogue", "response", "compiled"],
    acquired_at: datetime | None,
    catalogue_check_date: date | None,
    catalogue_claims: tuple[CatalogueSeriesClaim, ...],
    window: SeriesWindow | None,
    evidence: tuple[str, ...],
    reason: str | None,
) -> InventorySnapshot:
    inst = object.__new__(_ORIG_INVENTORY_SNAPSHOT)
    object.__setattr__(
        inst,
        "__dict__",
        {
            "snapshot_id": snapshot_id,
            "scope": scope,
            "members": members,
            "member_facts": member_facts,
            "completeness": completeness,
            "access": access,
            "origin": origin,
            "acquired_at": acquired_at,
            "catalogue_check_date": catalogue_check_date,
            "catalogue_claims": catalogue_claims,
            "window": window,
            "evidence": evidence,
            "reason": reason,
        },
    )
    object.__setattr__(inst, "__pydantic_fields_set__", _INV_FIELDS_SET.copy())
    object.__setattr__(inst, "__pydantic_extra__", None)
    object.__setattr__(inst, "__pydantic_private__", None)
    return inst


def materialize_series(
    artifact: PackagedCatalogArtifact,
    *,
    scope: SeriesScope | None = None,
) -> tuple[tuple[SourceSeries, ...], tuple[InventorySnapshot, ...]]:
    import polars as pl

    provider_id = str(artifact.provider_info["provider_id"])
    if artifact.source_descriptions is None:
        return (), ()
    if scope is not None and scope.provider_ids and provider_id not in scope.provider_ids:
        return (), ()
    station_filter = set(scope.station_ids) if scope is not None and scope.station_ids else None
    product_filter = set(scope.product_ids) if scope is not None and scope.product_ids else None
    if not provider_id:
        raise ValueError("Source series requires nonempty identifiers")
    prov_is_plain = _PLAIN_JSON_ASCII_FULLMATCH(provider_id) is not None
    prov_json = f'"{provider_id}"'
    descriptions = artifact.source_descriptions
    by_product: dict[str, list[tuple[SourceDescription, bool, str | None]]] = {}
    by_pair: dict[tuple[str, str], list[tuple[SourceDescription, bool, str | None]]] = {}
    for item in descriptions.descriptions:
        if product_filter is not None and item.product_id not in product_filter:
            continue
        item_facts = item.facts
        if not item_facts or (len(item_facts) > 1 and len({f.facts_id for f in item_facts}) != len(item_facts)):
            raise ValueError("Source series requires unique physical-fact segments")
        item_ns = item.identity.namespace
        for fact in item_facts:
            unit_def = fact.source_unit_definition
            if unit_def is not None and (unit_def.provider_id != provider_id or unit_def.namespace != item_ns):
                raise ValueError("Source-unit code definition does not apply to this provider and source namespace")
        if item.series_id is not None:
            fixed_sid_plain = _PLAIN_JSON_ASCII_FULLMATCH(item.series_id) is not None
            suffix_json: str | None = None
        else:
            fixed_sid_plain = True
            suffix_parts = (
                item.identity_key
                if item.identity_key is not None
                else (item.identity.namespace, item.identity.published_id)
            )
            if prov_is_plain and all(
                part is None or (type(part) is str and _PLAIN_JSON_ASCII_FULLMATCH(part) is not None)
                for part in suffix_parts
            ):
                suffix_json = ",".join("null" if part is None else f'"{part}"' for part in suffix_parts)
            else:
                suffix_json = None
        prepared_item = (item, fixed_sid_plain, suffix_json)
        if item.station_ids:
            for station in item.station_ids:
                if station_filter is None or station in station_filter:
                    by_pair.setdefault((station, item.product_id), []).append(prepared_item)
        elif item.station_id is None:
            by_product.setdefault(item.product_id, []).append(prepared_item)
        elif station_filter is None or item.station_id in station_filter:
            by_pair.setdefault((item.station_id, item.product_id), []).append(prepared_item)
    series: list[SourceSeries] = []
    inventories: list[InventorySnapshot] = []
    pairs = artifact.station_products
    if scope is not None:
        if scope.station_ids:
            pairs = pairs.filter(pl.col("station_id").is_in(scope.station_ids))
        if scope.product_ids:
            pairs = pairs.filter(pl.col("product_id").is_in(scope.product_ids))
    available_pairs = pairs.filter(pl.col("availability") != "unavailable")
    if available_pairs.is_empty():
        return (), ()
    claims_by_pair: dict[tuple[str, str], list[CatalogueSeriesClaim]] = {}
    if artifact.catalogue_claims is not None and not artifact.catalogue_claims.is_empty():
        claim_rows = artifact.catalogue_claims.join(
            available_pairs.select("station_id", "product_id"), on=["station_id", "product_id"], how="semi"
        )
        if claim_rows.height:
            c_cols = claim_rows.to_dict(as_series=False)
            ident_cache: dict[tuple[str, str | None, str | None, tuple[str, ...]], SourceIdentity] = {}
            construct_ident = (
                _fast_ident
                if SourceIdentity is _ORIG_SOURCE_IDENTITY
                else getattr(SourceIdentity, "model_construct", SourceIdentity)
            )
            construct_claim = (
                _fast_claim
                if CatalogueSeriesClaim is _ORIG_CATALOGUE_CLAIM
                else getattr(CatalogueSeriesClaim, "model_construct", CatalogueSeriesClaim)
            )
            for c_prov, c_stat, c_prod, c_ns, c_pub, c_desc, c_ev, c_coords in zip(
                c_cols["provider_id"],
                c_cols["station_id"],
                c_cols["product_id"],
                c_cols["namespace"],
                c_cols["published_id"],
                c_cols["description"],
                c_cols["evidence"],
                c_cols["native_coordinates"],
                strict=True,
            ):
                ev_tuple = tuple(c_ev)
                if not c_ns or not ev_tuple:
                    raise ValueError("Source identity requires a namespace and evidence")
                ident_key = (c_ns, c_pub, c_desc, ev_tuple)
                claim_ident = ident_cache.get(ident_key)
                if claim_ident is None:
                    claim_ident = construct_ident(
                        namespace=c_ns,
                        published_id=c_pub,
                        description=c_desc,
                        origin="catalogue",
                        evidence=ev_tuple,
                    )
                    ident_cache[ident_key] = claim_ident
                value = construct_claim(
                    provider_id=c_prov,
                    station_id=c_stat,
                    product_id=c_prod,
                    identity=claim_ident,
                    native_coordinates=tuple((coord["name"], coord["value"]) for coord in c_coords),
                )
                claims_by_pair.setdefault((c_stat, c_prod), []).append(value)
    pair_stations = available_pairs["station_id"].to_list()
    pair_products = available_pairs["product_id"].to_list()
    pair_dates = available_pairs["last_catalogue_check"].to_list()
    provider_tuple = (provider_id,)
    evidence_tuple = (f"catalogue:{provider_id}:station_product.last_catalogue_check",)
    date_cache: dict[object, tuple[str, str, bool]] = {}
    prod_plain_cache: dict[str, bool] = {}
    empty_descriptions: list[tuple[SourceDescription, bool, str | None]] = []
    has_claims = bool(claims_by_pair)
    construct_series = (
        _fast_series if SourceSeries is _ORIG_SOURCE_SERIES else getattr(SourceSeries, "model_construct", SourceSeries)
    )
    construct_scope = (
        _fast_scope if SeriesScope is _ORIG_SERIES_SCOPE else getattr(SeriesScope, "model_construct", SeriesScope)
    )
    construct_inv = (
        _fast_inv
        if InventorySnapshot is _ORIG_INVENTORY_SNAPSHOT
        else getattr(InventorySnapshot, "model_construct", InventorySnapshot)
    )
    sha256 = hashlib.sha256
    for station, product, check_date in zip(pair_stations, pair_products, pair_dates, strict=True):
        if not (station and product):
            raise ValueError("Source series requires nonempty identifiers")
        stat_plain = prov_is_plain and _PLAIN_JSON_ASCII_FULLMATCH(station) is not None
        members: list[str] = []
        all_members_plain = True
        matched_items = by_pair.get((station, product))
        if matched_items is None:
            matched_items = by_product.get(product, empty_descriptions)
        for item, fixed_sid_plain, suffix_json in matched_items:
            if item.series_id is not None:
                identity = item.series_id
                if not fixed_sid_plain:
                    all_members_plain = False
            elif stat_plain and suffix_json is not None:
                identity = sha256(f'[{prov_json},"{station}",{suffix_json}]'.encode("ascii")).hexdigest()
            else:
                identity = stable_id(
                    provider_id,
                    station,
                    *(
                        item.identity_key
                        if item.identity_key is not None
                        else (item.identity.namespace, item.identity.published_id)
                    ),
                )
            members.append(identity)
            series.append(
                construct_series(
                    series_id=identity,
                    provider_id=provider_id,
                    station_id=station,
                    product_id=product,
                    identity=item.identity,
                    variant=item.variant,
                    facts=item.facts,
                )
            )
        claims = tuple(claims_by_pair.get((station, product), ())) if has_claims else ()
        if claims:
            # Native catalogue identities are claims, not established response identities.
            members = []
        date_info = date_cache.get(check_date)
        if date_info is None:
            vintage = check_date.isoformat()
            reason = (
                f"Catalogue check date {vintage}; exact inventory acquisition instant is not represented by this date. "
                "Static snapshot does not establish exhaustive current or historical source inventory."
            )
            vint_plain = _PLAIN_JSON_ASCII_FULLMATCH(vintage) is not None
            date_info = (vintage, reason, vint_plain)
            date_cache[check_date] = date_info
        else:
            vintage, reason, vint_plain = date_info
        members_tuple = tuple(members)
        prod_plain = prod_plain_cache.get(product)
        if prod_plain is None:
            prod_plain = _PLAIN_JSON_ASCII_FULLMATCH(product) is not None
            prod_plain_cache[product] = prod_plain
        if claims:
            snap_id = stable_id(
                provider_id,
                station,
                product,
                vintage,
                *members_tuple,
                *(
                    json.dumps(
                        {
                            "provider_id": claim.provider_id,
                            "station_id": claim.station_id,
                            "product_id": claim.product_id,
                            "identity": {
                                "namespace": claim.identity.namespace,
                                "published_id": claim.identity.published_id,
                                "description": claim.identity.description,
                                "origin": claim.identity.origin,
                                "evidence": list(claim.identity.evidence),
                            },
                            "native_coordinates": [[k, v] for k, v in claim.native_coordinates],
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    for claim in claims
                ),
            )
        elif stat_plain and prod_plain and vint_plain and all_members_plain:
            n_members = len(members_tuple)
            if n_members == 1:
                snap_payload = f'[{prov_json},"{station}","{product}","{vintage}","{members_tuple[0]}"]'
            elif n_members == 0:
                snap_payload = f'[{prov_json},"{station}","{product}","{vintage}"]'
            else:
                members_str = ",".join(f'"{m}"' for m in members_tuple)
                snap_payload = f'[{prov_json},"{station}","{product}","{vintage}",{members_str}]'
            snap_id = sha256(snap_payload.encode("ascii")).hexdigest()
        else:
            snap_id = stable_id(provider_id, station, product, vintage, *members_tuple)
        snap_scope = construct_scope(
            state=ScopeState.ACTIVE,
            provider_ids=provider_tuple,
            station_ids=(station,),
            product_ids=(product,),
            predicates=(),
            restriction=RestrictionKind.ALL,
            variants=(),
            series_ids=(),
        )
        if len(members_tuple) <= 1 or len(set(members_tuple)) == len(members_tuple):
            inventories.append(
                construct_inv(
                    snapshot_id=snap_id,
                    scope=snap_scope,
                    members=members_tuple,
                    member_facts=(),
                    completeness=InventoryCompleteness.INCOMPLETE,
                    access="catalogue",
                    origin="catalogue",
                    acquired_at=None,
                    catalogue_check_date=check_date,
                    catalogue_claims=claims,
                    window=None,
                    evidence=evidence_tuple,
                    reason=reason,
                )
            )
        else:
            inventories.append(
                InventorySnapshot(
                    snapshot_id=snap_id,
                    scope=snap_scope,
                    members=members_tuple,
                    completeness=InventoryCompleteness.INCOMPLETE,
                    access="catalogue",
                    origin="catalogue",
                    catalogue_check_date=check_date,
                    catalogue_claims=claims,
                    evidence=evidence_tuple,
                    reason=reason,
                )
            )
    return tuple(series), tuple(inventories)
