"""deferred provenance : ProviderId × CatalogueFactUniverse → AcquisitionProvenance (pure)."""

from __future__ import annotations

from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance, WithheldFact
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE


def deferred_acquisition_provenance(provider_id: str) -> AcquisitionProvenance:
    """Build the closed provenance record for an uncertified provider.

    Parameters
    ----------
    provider_id
        Packaged provider whose credentialed acquisition remains deferred.

    Returns
    -------
    AcquisitionProvenance
        A closed record withholding every catalogue fact without inventing an
        acquisition, source, or native-table identity.
    """
    grouped_facts = {
        "provider_manifest_without_acquisition": tuple(
            fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("provider.")
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
        fact_universe=CATALOGUE_FACT_UNIVERSE,
        source_records=(),
        fact_bindings=(),
        withheld_facts=tuple(
            WithheldFact(
                fact_group=fact_group,
                facts=facts,
                reason="no_acquisition_record_established",
            )
            for fact_group, facts in grouped_facts.items()
        ),
    )
