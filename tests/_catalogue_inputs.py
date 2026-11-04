"""Detached, validated packaged inputs for explicitly enrolled behavior tests.

Loading and corruption tests must use the real artifact boundary. This pool is
owned by a pytest session, accepts an explicit path allowlist, and checks file
content before reuse. It never caches registry handles, declarations or paths
resolved from the environment.
"""

from collections.abc import Callable, Iterable
from copy import deepcopy
from hashlib import blake2b
from pathlib import Path

from rivretrieve._internal.catalogues.artifact import (
    REQUIRED_ARTIFACT_FILES,
    PackagedCatalogArtifact,
)
from rivretrieve._internal.catalogues.evidence import (
    EVIDENCE_FILENAMES,
    CatalogueEvidence,
    _mark_validated_file_identity,
    _mark_validated_header,
)
from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
from rivretrieve._internal.source_series import PhysicalFacts, SourceIdentity

# These are the files read by load_packaged_catalogue_artifact, including its
# source-definition and provenance readers. Native build inputs are not read.
_INPUT_FILES = (
    *REQUIRED_ARTIFACT_FILES,
    "format.json",
    "source_series.json",
    "series_claims.parquet",
    "provenance.json",
    *EVIDENCE_FILENAMES.values(),
)
type Fingerprint = tuple[tuple[str, bytes], ...]


def _fingerprint(path: Path) -> Fingerprint | None:
    try:
        if path.is_symlink():
            return None
        values = []
        for name in _INPUT_FILES:
            file = path / name
            if file.is_symlink():
                return None
            values.append((name, blake2b(file.read_bytes(), digest_size=32).digest()))
        return tuple(values)
    except OSError:
        # The real loader owns missing-file and unreadable-input diagnostics.
        return None


def _detach_evidence(evidence: CatalogueEvidence) -> CatalogueEvidence:
    header_copy = deepcopy(evidence.header)
    for file_identity in header_copy.files.values():
        _mark_validated_file_identity(file_identity)
    _mark_validated_header(header_copy)
    return CatalogueEvidence.model_construct(
        header=header_copy,
        facts=evidence.facts.clone(),
        acquisitions=evidence.acquisitions.clone(),
        bindings=evidence.bindings.clone(),
        binding_facts=evidence.binding_facts.clone(),
        external_inputs=evidence.external_inputs.clone(),
    )


def _detach_facts(facts: PhysicalFacts) -> PhysicalFacts:
    return facts.model_copy(
        update={
            "quantity": facts.quantity.model_copy(),
            "source_unit": facts.source_unit.model_copy(),
            "source_unit_definition": (
                None if facts.source_unit_definition is None else facts.source_unit_definition.model_copy()
            ),
            "frequency": facts.frequency.model_copy(),
            "statistic": facts.statistic.model_copy(),
            "temporal_support": facts.temporal_support.model_copy(),
            "day_definition": facts.day_definition.model_copy(),
            "timestamp_anchor": facts.timestamp_anchor.model_copy(),
            "time_zone": facts.time_zone.model_copy(),
            "vertical_reference": facts.vertical_reference.model_copy(),
            "vertical_datum": facts.vertical_datum.model_copy(),
        }
    )


def _detach_descriptions(descriptions: SourceDescriptions) -> SourceDescriptions:
    facts_cache: dict[int, PhysicalFacts] = {}
    tuple_cache: dict[tuple[int, ...], tuple[PhysicalFacts, ...]] = {}
    identity_cache: dict[int, SourceIdentity] = {}
    detached_items = []
    construct_desc = SourceDescription.model_construct
    construct_ident = SourceIdentity.model_construct
    for item in descriptions.descriptions:
        f_key = tuple(id(f) for f in item.facts)
        detached_facts = tuple_cache.get(f_key)
        if detached_facts is None:
            parts = []
            for f in item.facts:
                fid = id(f)
                df = facts_cache.get(fid)
                if df is None:
                    df = _detach_facts(f)
                    facts_cache[fid] = df
                parts.append(df)
            detached_facts = tuple(parts)
            tuple_cache[f_key] = detached_facts
        ident = item.identity
        iid = id(ident)
        detached_ident = identity_cache.get(iid)
        if detached_ident is None:
            detached_ident = construct_ident(
                _fields_set=set(ident.__pydantic_fields_set__),
                namespace=ident.namespace,
                published_id=ident.published_id,
                description=ident.description,
                origin=ident.origin,
                evidence=ident.evidence,
            )
            identity_cache[iid] = detached_ident
        detached_items.append(
            construct_desc(
                _fields_set=set(item.__pydantic_fields_set__),
                product_id=item.product_id,
                station_id=item.station_id,
                station_ids=item.station_ids,
                series_id=item.series_id,
                identity_key=item.identity_key,
                native_coordinate=item.native_coordinate,
                identity=detached_ident,
                variant=item.variant,
                facts=detached_facts,
            )
        )
    return descriptions.model_copy(update={"descriptions": tuple(detached_items)})


class _LazyDetachedField:
    """Non-data descriptor that detaches heavy nested models on first attribute read."""

    def __init__(self, attr_name: str, template_key: str, detacher: Callable) -> None:
        self._attr_name = attr_name
        self._template_key = template_key
        self._detacher = detacher

    def __get__(self, instance: object | None, owner: type | None = None) -> object:
        if instance is None:
            return None
        template_val = instance.__dict__.get(self._template_key)
        detached = None if template_val is None else self._detacher(template_val)
        object.__setattr__(instance, self._attr_name, detached)
        return detached


class _DetachedPackagedCatalogArtifact(PackagedCatalogArtifact):
    acquisition_provenance = _LazyDetachedField(  # type: ignore[assignment]
        "acquisition_provenance", "_template_evidence", _detach_evidence
    )
    source_descriptions = _LazyDetachedField(  # type: ignore[assignment]
        "source_descriptions", "_template_descriptions", _detach_descriptions
    )


def _detach_artifact(template: PackagedCatalogArtifact) -> PackagedCatalogArtifact:
    instance = object.__new__(_DetachedPackagedCatalogArtifact)
    object.__setattr__(instance, "provider_info", deepcopy(template.provider_info))
    object.__setattr__(instance, "products", template.products.clone())
    object.__setattr__(instance, "stations", template.stations.clone())
    object.__setattr__(instance, "station_products", template.station_products.clone())
    object.__setattr__(
        instance,
        "catalogue_claims",
        None if template.catalogue_claims is None else template.catalogue_claims.clone(),
    )
    if template.acquisition_provenance is None:
        object.__setattr__(instance, "acquisition_provenance", None)
    else:
        object.__setattr__(instance, "_template_evidence", template.acquisition_provenance)
    if template.source_descriptions is None:
        object.__setattr__(instance, "source_descriptions", None)
    else:
        object.__setattr__(instance, "_template_descriptions", template.source_descriptions)
    return instance


class PackagedCatalogueInputs:
    """Keep pristine inputs, returning a fully detached value on every borrow."""

    def __init__(
        self,
        paths: Iterable[Path],
        loader: Callable[[Path], PackagedCatalogArtifact],
    ) -> None:
        self._paths = frozenset(path.absolute() for path in paths)
        self._loader = loader
        self._validated: dict[Path, tuple[Fingerprint, PackagedCatalogArtifact]] = {}

    def load(self, path: Path) -> PackagedCatalogArtifact:
        path = path.absolute()
        if path not in self._paths:
            return self._loader(path)
        fingerprint = _fingerprint(path)
        previous = self._validated.get(path)
        if fingerprint is not None and previous is not None and previous[0] == fingerprint:
            return _detach_artifact(previous[1])
        artifact = self._loader(path)
        if fingerprint is not None and _fingerprint(path) == fingerprint:
            self._validated[path] = (fingerprint, artifact)
            return _detach_artifact(artifact)
        return artifact
