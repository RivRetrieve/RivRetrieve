"""deferred provenance : ProviderId × SourceRecords × FactBindings × SourceFacts → AcquisitionProvenance (pure)."""

from __future__ import annotations

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    FactBinding,
    SourceRecord,
    Transformation,
    WithheldFact,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE


def deferred_acquisition_provenance(
    provider_id: str,
    *,
    source_records: tuple[SourceRecord, ...] = (),
    fact_bindings: tuple[FactBinding, ...] = (),
    source_facts: tuple[str, ...] = (),
) -> AcquisitionProvenance:
    """Build the closed provenance record for an uncertified provider.

    Parameters
    ----------
    provider_id
        Packaged provider whose credentialed acquisition remains deferred.
    source_records
        Independently established non-catalogue source records to retain.
    fact_bindings
        Direct bindings for the independently established source facts.
    source_facts
        Source facts added to the otherwise canonical catalogue fact universe.

    Returns
    -------
    AcquisitionProvenance
        A closed record withholding every unestablished catalogue fact without
        inventing a native-table identity. Independently established source
        records and their direct fact bindings remain available.
    """
    authored_provider_facts = tuple(
        fact
        for fact in CATALOGUE_FACT_UNIVERSE
        if fact.startswith("provider.")
        and fact not in {"provider.catalogue_version", "provider.license", "provider.citation"}
    )
    grouped_facts = {
        "provider_external_catalogue_facts_without_acquisition": (
            "provider.catalogue_version",
            "provider.license",
            "provider.citation",
        ),
        "product_definitions_without_acquisition": tuple(
            fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("product.")
        ),
        "station_identity_and_location_without_acquisition": tuple(
            fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("station.")
        ),
        "station_product_relationships_without_acquisition": tuple(
            fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("station_product.")
        ),
    }
    return AcquisitionProvenance(
        schema_version=2,
        provider_id=provider_id,
        native_table=None,
        fact_universe=CATALOGUE_FACT_UNIVERSE + source_facts,
        source_records=source_records,
        fact_bindings=(
            FactBinding(
                fact_group="rivretrieve_authored_provider_registration",
                facts=authored_provider_facts,
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="RivRetrieve code-defined provider registration and capabilities",
                    kind="authored_constant",
                    external_inputs=(),
                ),
            ),
            *fact_bindings,
        ),
        withheld_facts=tuple(
            WithheldFact(
                fact_group=fact_group,
                facts=facts,
                reason="no_acquisition_record_established",
            )
            for fact_group, facts in grouped_facts.items()
        ),
    )
