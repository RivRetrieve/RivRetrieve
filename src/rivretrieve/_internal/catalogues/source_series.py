"""Materialize source-series descriptions from a recorded catalogue snapshot."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal, cast

from pydantic import BaseModel, ConfigDict, model_validator

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.source_series import (
    CatalogueSeriesClaim,
    InventoryCompleteness,
    InventorySnapshot,
    PhysicalFacts,
    SeriesScope,
    SourceIdentity,
    SourceSeries,
    stable_id,
)

if TYPE_CHECKING:
    from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact


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


def decode_source_descriptions(content: bytes) -> SourceDescriptions:
    """Read both disk revisions; resolve strict references to shared fact instances."""
    try:
        raw = json.loads(content)
        if not isinstance(raw, dict):
            raise ValueError("Source descriptions must be a JSON object")
        revision = raw.get("schema_version", 1)
        if type(revision) is not int:
            raise ValueError("Source-description schema revision must be an integer")
        if revision == 1:
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


def materialize_series(
    artifact: PackagedCatalogArtifact,
    *,
    scope: SeriesScope | None = None,
) -> tuple[tuple[SourceSeries, ...], tuple[InventorySnapshot, ...]]:
    provider_id = str(artifact.provider_info["provider_id"])
    if artifact.source_descriptions is None:
        return (), ()
    descriptions = artifact.source_descriptions
    by_product: dict[str, list[SourceDescription]] = {}
    by_pair: dict[tuple[str, str], list[SourceDescription]] = {}
    for item in descriptions.descriptions:
        if item.station_ids:
            for station in item.station_ids:
                if scope is None or not scope.station_ids or station in scope.station_ids:
                    by_pair.setdefault((station, item.product_id), []).append(item)
        elif item.station_id is None:
            by_product.setdefault(item.product_id, []).append(item)
        else:
            by_pair.setdefault((item.station_id, item.product_id), []).append(item)
    series = []
    inventories = []
    pairs = artifact.station_products
    if scope is not None:
        if scope.provider_ids and provider_id not in scope.provider_ids:
            return (), ()
        import polars as pl

        if scope.station_ids:
            pairs = pairs.filter(pl.col("station_id").is_in(scope.station_ids))
        if scope.product_ids:
            pairs = pairs.filter(pl.col("product_id").is_in(scope.product_ids))
    claims_by_pair: dict[tuple[str, str], list[CatalogueSeriesClaim]] = {}
    if artifact.catalogue_claims is not None and not artifact.catalogue_claims.is_empty():
        claim_rows = artifact.catalogue_claims.join(
            pairs.select("station_id", "product_id"), on=["station_id", "product_id"], how="semi"
        )
        for claim in claim_rows.iter_rows(named=True):
            value = CatalogueSeriesClaim(
                provider_id=claim["provider_id"],
                station_id=claim["station_id"],
                product_id=claim["product_id"],
                identity=SourceIdentity(
                    namespace=claim["namespace"],
                    published_id=claim["published_id"],
                    description=claim["description"],
                    origin="catalogue",
                    evidence=tuple(claim["evidence"]),
                ),
                native_coordinates=tuple((item["name"], item["value"]) for item in claim["native_coordinates"]),
            )
            claims_by_pair.setdefault((value.station_id, value.product_id), []).append(value)
    for row in pairs.iter_rows(named=True):
        if row["availability"] == "unavailable":
            continue
        station, product = row["station_id"], row["product_id"]
        members = []
        for item in by_pair.get((station, product), by_product.get(product, [])):
            identity = item.series_id or stable_id(
                provider_id, station, *(item.identity_key or (item.identity.namespace, item.identity.published_id))
            )
            members.append(identity)
            series.append(
                SourceSeries(
                    series_id=identity,
                    provider_id=provider_id,
                    station_id=station,
                    product_id=product,
                    identity=item.identity,
                    variant=item.variant,
                    facts=item.facts,
                )
            )
        claims = tuple(claims_by_pair.get((station, product), ()))
        if claims:
            # Native catalogue identities are claims, not established response identities.
            members = []
        vintage = row["last_catalogue_check"].isoformat()
        inventories.append(
            InventorySnapshot(
                snapshot_id=stable_id(
                    provider_id, station, product, vintage, *members, *(claim.model_dump_json() for claim in claims)
                ),
                scope=SeriesScope(provider_ids=(provider_id,), station_ids=(station,), product_ids=(product,)),
                members=tuple(members),
                completeness=InventoryCompleteness.INCOMPLETE,
                access="catalogue",
                origin="catalogue",
                catalogue_check_date=row["last_catalogue_check"],
                catalogue_claims=claims,
                evidence=(f"catalogue:{provider_id}:station_product.last_catalogue_check",),
                reason=f"Catalogue check date {vintage}; exact inventory acquisition instant is not represented by this date. Static snapshot does not establish exhaustive current or historical source inventory.",
            )
        )
    return tuple(series), tuple(inventories)
