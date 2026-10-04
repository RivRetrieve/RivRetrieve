"""catalogue metadata : AcquisitionProvenance × OriginDeclarations × CatalogueFiles → MetadataFiles (pure)."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from io import BytesIO
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
    from rivretrieve._internal.engine import ProviderConfig
    from rivretrieve._internal.provider_series import SeriesMapping

import polars as pl

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    CatalogueBuildInputs,
    CodeReference,
    ExternalFactReference,
    FactBinding,
    Transformation,
)
from rivretrieve._internal.catalogue_origins import Field, OriginDeclarations
from rivretrieve._internal.catalogues.descriptor import build_catalogue_descriptor
from rivretrieve._internal.catalogues.evidence import CatalogueEvidence, normalize_provenance
from rivretrieve._internal.catalogues.evidence_encoding import encode_catalogue_evidence, reconstruct_provenance
from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.catalogues.schemas import CATALOGUE_SERIES_CLAIMS_SCHEMA
from rivretrieve._internal.catalogues.source_series import SourceDescriptions, encode_source_descriptions
from rivretrieve._internal.catalogues.station_metadata import (
    MetadataField,
    build_station_metadata,
    validate_metadata_fields,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.publication_identity import publication_identity_fields
from rivretrieve._internal.station_metadata import metadata_support_fact, source_metadata_frame


def build_catalogue_metadata(
    provenance: AcquisitionProvenance | CatalogueEvidence,
    origins: Sequence[OriginDeclarations],
    files: Mapping[str, bytes],
    *,
    build_inputs: CatalogueBuildInputs | None = None,
    native_table: NativeTable | None = None,
    metadata_fields: tuple[MetadataField, ...] | None = None,
    station_metadata: pl.DataFrame | None = None,
    metadata_implementation: tuple[str, str] | None = None,
    station_metadata_notice: str | None = None,
    transformation_implementations: Mapping[str, tuple[str, str]] | None = None,
    source_descriptions: SourceDescriptions | None = None,
    source_config: ProviderConfig | None = None,
    source_describer: Callable[[PackagedCatalogArtifact], SourceDescriptions] | None = None,
    source_mappings: Mapping[str, SeriesMapping] | None = None,
    catalogue_claims: pl.DataFrame | None = None,
) -> dict[str, bytes]:
    """Encode catalogue evidence, metadata and the descriptor from explicit inputs.

    ``build_inputs``, ``native_table`` and ``metadata_fields`` are required for every new publication.
    Historical provenance remains readable without these build-only inputs.
    ``station_metadata`` can supply an explicit source projection when a provider
    combines supplementary sources. Its canonical scope, value states and field
    declarations are validated here. Provider projection code establishes actual
    source exposure; each alternative source uses ``MetadataField.source_facts``.
    An explicit projection requires ``metadata_implementation``, the exact
    (repository path, symbol) of its producer in ``build_inputs.declarations``.
    Without this projection, fields are built from ``native_table`` by the
    shared implementation; an alternate implementation cannot be supplied.
    ``transformation_implementations`` maps exact non-catalogue fact groups to
    declared code locations. It records operation responsibility without running
    those observation operations. ``station_metadata_notice`` is retained verbatim
    on the descriptor's station-metadata record set, separate from source terms.
    Missing inputs, unresolved responsibilities or
    ambiguous station identity declarations raise ``FatalContractError`` before
    publication.
    """
    if build_inputs is None or native_table is None:
        raise FatalContractError("Catalogue publication requires explicit build_inputs and native_table")
    if metadata_fields is None:
        raise FatalContractError("Catalogue publication requires explicit metadata_fields")
    if not origins or not isinstance(station_origin := origins[0].get("station_id"), Field):
        raise FatalContractError("Metadata publication requires an explicit native station identity field")
    if any(origin.get("station_id") != station_origin for origin in origins):
        raise FatalContractError("Metadata publication requires consistent station identity declarations")
    stations = pl.read_parquet(BytesIO(files["stations.parquet"]))
    station_products = pl.read_parquet(BytesIO(files["station_products.parquet"]))
    provider_id = (
        provenance.provider_id if isinstance(provenance, AcquisitionProvenance) else provenance.header.provider_id
    )
    if station_metadata is None:
        if metadata_implementation is not None:
            raise FatalContractError("A metadata implementation requires an explicit station metadata projection")
        if any(field.source_facts for field in metadata_fields):
            raise FatalContractError("Alternate metadata sources require an explicit station metadata projection")
        station_metadata = build_station_metadata(provider_id, native_table, stations, station_origin, metadata_fields)
    else:
        if metadata_implementation is None:
            raise FatalContractError("An explicit station metadata projection requires its implementation declaration")
        validated = source_metadata_frame(stations.select("provider_id", "station_id"), station_metadata)
        if validated.height != station_metadata.height:
            raise FatalContractError("Station metadata contains identities outside the canonical catalogue")
        station_metadata = validated
    validate_metadata_fields(station_metadata, metadata_fields)
    for field in metadata_fields:
        if not field.source_facts and any(
            name not in native_table.data.columns
            for name in (field.source_field, field.datum_field)
            if name is not None
        ):
            raise FatalContractError(
                "Metadata fields outside the historical native table require explicit source facts"
            )
    bound = _bind_catalogue_build_inputs(
        provenance,
        build_inputs,
        station_metadata,
        metadata_fields=metadata_fields,
        metadata_implementation=metadata_implementation,
        transformation_implementations=transformation_implementations,
    )
    evidence = normalize_provenance(
        bound,
        stations=stations,
        station_products=station_products,
        row_locator_requirements=(
            provenance.header.row_locator_requirements if isinstance(provenance, CatalogueEvidence) else ()
        ),
    )
    metadata = encode_catalogue_evidence(evidence)
    buffer = BytesIO()
    station_metadata.write_parquet(buffer, compression="zstd", statistics=True)
    metadata["station_metadata.parquet"] = buffer.getvalue()
    if source_descriptions is None:
        from rivretrieve._internal.catalogues.artifact import packaged_catalogue_artifact_from_components
        from rivretrieve._internal.catalogues.source_descriptions import (
            build_source_descriptions,
            content_identified_descriptions,
        )

        artifact = packaged_catalogue_artifact_from_components(
            json.loads(files["provider.json"]),
            pl.read_parquet(BytesIO(files["products.parquet"])),
            pl.read_parquet(BytesIO(files["stations.parquet"])),
            pl.read_parquet(BytesIO(files["station_products.parquet"])),
            acquisition_provenance=evidence,
            withheld_rows_already_applied=True,
        )
        if source_describer is not None:
            source_descriptions = content_identified_descriptions(source_describer(artifact))
        else:
            if artifact.products.height and source_config is None:
                raise ValueError("Catalogue publication requires explicit source_config or source_describer")
            source_descriptions = build_source_descriptions(artifact, source_config, mappings=source_mappings)
    if source_descriptions.provider_id != evidence.header.provider_id:
        raise ValueError("Source descriptions provider does not match catalogue evidence")
    metadata["source_series.json"] = encode_source_descriptions(source_descriptions)
    format_identity: dict[str, object] = {"catalogue_format_version": 2}
    format_identity.update(publication_identity_fields((evidence.header.provider_id,)))
    metadata["format.json"] = (json.dumps(format_identity, separators=(",", ":")) + "\n").encode()
    claims = (
        catalogue_claims
        if catalogue_claims is not None
        else pl.DataFrame(schema=CATALOGUE_SERIES_CLAIMS_SCHEMA.polars_schema)
    )
    buffer = BytesIO()
    claims.write_parquet(buffer, compression="zstd", statistics=True)
    metadata["series_claims.parquet"] = buffer.getvalue()
    descriptor = build_catalogue_descriptor(
        evidence, origins, {**files, **metadata}, station_metadata_notice=station_metadata_notice
    )
    metadata["croissant.json"] = (json.dumps(descriptor, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return metadata


_METADATA_MODULE = "src/rivretrieve/_internal/catalogues/station_metadata.py"


def _bind_catalogue_build_inputs(
    provenance: AcquisitionProvenance | CatalogueEvidence,
    build_inputs: CatalogueBuildInputs,
    metadata: pl.DataFrame,
    *,
    metadata_fields: tuple[MetadataField, ...] = (),
    metadata_implementation: tuple[str, str] | None = None,
    transformation_implementations: Mapping[str, tuple[str, str]] | None = None,
) -> AcquisitionProvenance:
    """Bind each transformation to its implementation and authored declaration.

    Catalogue conversion, observation operations and metadata projection retain
    separate implementation references. Authored constants have no executable
    reference. Non-catalogue operations require an explicit fact-group mapping.
    Runtime references identify implementations, not build-time runs.
    Historical source acquisitions, native identities and times remain unchanged.
    """
    original = reconstruct_provenance(provenance) if isinstance(provenance, CatalogueEvidence) else provenance
    build_inputs = CatalogueBuildInputs.model_validate(build_inputs.model_dump(mode="python"))
    native_uses = tuple(item for item in build_inputs.inputs if item.usage == "native_table")
    if len(native_uses) != 1:
        raise FatalContractError("Catalogue publication requires one explicitly adopted native table")
    native = original.native_table
    reference = native_uses[0].reference
    if (
        native is None
        or reference.sha256 != native.sha256
        or (native.byte_size is not None and reference.byte_size != native.byte_size)
    ):
        raise FatalContractError("Adopted native input must match the historical native byte identity")
    declarations = tuple(
        reference
        for reference in build_inputs.declarations
        if reference.repository == build_inputs.build.repository
        and reference.symbol in {"build_acquisition_provenance", "build_modern_acquisition_provenance"}
    )
    if len(declarations) != 1:
        raise FatalContractError("Catalogue publication requires one exact origins declaration reference")
    payload = original.model_dump(mode="python")
    payload["build_inputs"] = build_inputs
    # Metadata is a replaceable leaf projection. Never remove acquired facts or
    # a projection that another catalogue transformation depends on.
    prior_metadata = {fact for fact in original.fact_universe if fact.startswith("metadata.")}
    bindings = []
    for binding in payload["fact_bindings"]:
        outputs = set(binding["facts"])
        if outputs & prior_metadata:
            if not outputs <= prior_metadata:
                raise FatalContractError("Metadata projection cannot share a binding with other catalogue facts")
            continue
        transformation = binding.get("transformation")
        if transformation is not None and any(
            reference["fact"] in prior_metadata for reference in transformation["external_inputs"]
        ):
            raise FatalContractError("Metadata projection has a nonmetadata dependent transformation")
        bindings.append(binding)
    if any(set(group.facts) & prior_metadata for group in original.withheld_facts):
        raise FatalContractError("Only bound metadata leaf projections can be replaced")
    payload["fact_universe"] = tuple(fact for fact in original.fact_universe if fact not in prior_metadata)
    payload["fact_bindings"] = bindings
    implementations = transformation_implementations or {}
    executable_groups = {
        binding["fact_group"]
        for binding in bindings
        if binding.get("transformation") is not None
        and binding["transformation"].get("kind", "derived_value") != "authored_constant"
    }
    if not set(implementations) <= executable_groups:
        raise FatalContractError("Implementation responsibility must name an existing executable transformation group")
    declared_code = {
        (reference.repository_path, reference.symbol): reference
        for reference in build_inputs.declarations
        if reference.repository == build_inputs.build.repository
    }
    metadata_producer = None if metadata_implementation is None else declared_code.get(metadata_implementation)
    if metadata_implementation is not None and metadata_producer is None:
        raise FatalContractError("Metadata projection requires its exact implementation declaration reference")
    catalogue_builders = tuple(
        reference
        for reference in build_inputs.declarations
        if reference.repository == build_inputs.build.repository
        and reference.repository_path
        == f"src/rivretrieve/_internal/providers/{original.provider_id}/generate_catalogue.py"
        and reference.symbol in {"build_catalogue", "build_modern_catalogue"}
    )
    if len(catalogue_builders) != 1:
        raise FatalContractError("Catalogue publication requires one exact catalogue builder declaration")
    catalogue_builder = catalogue_builders[0]
    canonical_legacy = {
        "canonical.provider_id",
        "canonical.product_identity",
        "canonical.product_unit",
        "canonical.product_period",
        "canonical.station_identity",
        "canonical.station_location",
        "canonical.station.crs",
    }
    for binding in bindings:
        if not (transformation := binding.get("transformation")):
            continue
        facts = binding["facts"]
        if binding["fact_group"] in implementations:
            implementation_key = implementations[binding["fact_group"]]
        elif all(
            fact in canonical_legacy
            or fact.startswith(
                ("provider.", "product.", "station.", "station_product.", "station:", "station_product:")
            )
            for fact in facts
        ):
            implementation_key = (catalogue_builder.repository_path, catalogue_builder.symbol)
        else:
            raise FatalContractError("Transformation outputs have no declared implementation responsibility")
        implementation = declared_code.get(implementation_key)
        if implementation is None:
            raise FatalContractError("Transformation requires its exact implementation declaration reference")
        if transformation.get("kind", "derived_value") == "authored_constant":
            transformation["executable"] = None
            transformation["declaration"] = implementation
        else:
            transformation["executable"] = CodeReference(
                repository=implementation.repository,
                revision=build_inputs.build.revision,
                repository_path=implementation.repository_path,
                symbol=implementation.symbol,
            )
            transformation["declaration"] = declarations[0]
    supported = (
        metadata.filter(pl.col("support_fact").is_not_null())
        .select("attribute_role", "source_scope", "source_field", "support_fact")
        .unique(maintain_order=True)
    )
    if supported.height:
        mapping_declarations = tuple(
            reference
            for reference in build_inputs.declarations
            if reference.repository == build_inputs.build.repository
            and reference.repository_path == f"src/rivretrieve/_internal/providers/{original.provider_id}/origins.py"
            and reference.symbol == "STATION_METADATA_FIELDS"
        )
        if len(mapping_declarations) != 1:
            raise FatalContractError("Metadata publication requires the exact field-mapping declaration reference")
        direct = {
            fact: binding
            for binding in original.fact_bindings
            if binding.transformation is None
            for fact in binding.facts
        }
        acquisitions = {
            (source.source_id, acquisition.acquisition_id): acquisition
            for source in original.source_records
            for acquisition in source.acquisitions
        }
        support: list[ExternalFactReference] = []
        for fact in native_uses[0].facts:
            binding = direct.get(fact)
            if binding is None or binding.source_id is None or binding.acquisition_id is None:
                raise FatalContractError("Metadata native support must resolve a direct source/native fact")
            acquisition = acquisitions[(binding.source_id, binding.acquisition_id)]
            if acquisition.method == "runtime_http_request" or acquisition.instant_type == "runtime":
                raise FatalContractError("Metadata native support cannot use a runtime acquisition")
            support.append(ExternalFactReference(source_id=binding.source_id, fact=fact))
        executable = CodeReference(
            repository=build_inputs.build.repository,
            revision=build_inputs.build.revision,
            repository_path=_METADATA_MODULE if metadata_producer is None else metadata_producer.repository_path,
            symbol="build_station_metadata" if metadata_producer is None else metadata_producer.symbol,
        )
        declared_fields = {
            (field.attribute_role, field.source_scope, field.source_field): field for field in metadata_fields
        }
        adopted_facts = {fact for item in build_inputs.inputs for fact in item.facts}

        def supported_inputs(
            extra_facts: tuple[str, ...], source_facts: tuple[str, ...] = ()
        ) -> tuple[ExternalFactReference, ...]:
            references = [] if source_facts else list(support)
            for support_fact in (*source_facts, *extra_facts):
                binding = direct.get(support_fact)
                if (
                    binding is None
                    or binding.source_id is None
                    or binding.acquisition_id is None
                    or support_fact not in adopted_facts
                ):
                    raise FatalContractError("Metadata support must resolve an adopted direct source fact")
                acquisition = acquisitions[(binding.source_id, binding.acquisition_id)]
                if acquisition.method == "runtime_http_request" or acquisition.instant_type == "runtime":
                    raise FatalContractError("Metadata support cannot use a runtime acquisition")
                reference = ExternalFactReference(source_id=binding.source_id, fact=support_fact)
                if reference not in references:
                    references.append(reference)
            return tuple(references)

        facts = list(payload["fact_universe"])
        for role, scope, field, fact in supported.iter_rows():
            declaration = declared_fields.get((role, scope, field))
            if field is None or fact != metadata_support_fact(role, field, scope) or fact in facts:
                raise FatalContractError("Metadata support facts must be exact, unique projection outputs")
            facts.append(fact)
            bindings.append(
                FactBinding(
                    fact_group=fact,
                    facts=(fact,),
                    source_id=None,
                    acquisition_id=None,
                    transformation=Transformation(
                        name="project_station_metadata",
                        external_inputs=supported_inputs(
                            declaration.support_facts if declaration is not None else (),
                            declaration.source_facts if declaration is not None else (),
                        ),
                        executable=executable,
                        declaration=mapping_declarations[0],
                    ),
                ).model_dump(mode="python")
            )
        datum_rows = (
            metadata.filter(pl.col("datum_support_fact").is_not_null())
            .select("source_scope", "source_field", "source_datum_field", "datum_support_fact")
            .unique(maintain_order=True)
        )
        for scope, field_name, datum_field, fact in datum_rows.iter_rows():
            field = declared_fields.get(("elevation", scope, field_name))
            if (
                field is None
                or not field.datum_support
                or field.datum_field != datum_field
                or fact != f"{metadata_support_fact('elevation', field_name, scope)}.datum"
                or fact in facts
            ):
                raise FatalContractError("Metadata datum association requires its exact field declaration")
            facts.append(fact)
            bindings.append(
                FactBinding(
                    fact_group=fact,
                    facts=(fact,),
                    source_id=None,
                    acquisition_id=None,
                    transformation=Transformation(
                        name="associate_elevation_datum",
                        external_inputs=supported_inputs(field.datum_support, field.source_facts),
                        executable=executable,
                        declaration=mapping_declarations[0],
                    ),
                ).model_dump(mode="python")
            )
        payload["fact_universe"] = facts
    return AcquisitionProvenance.model_validate(payload)
