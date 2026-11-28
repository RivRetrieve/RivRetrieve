"""Ireland EPA HydroNet (`ie_epa`) source declarations for offline station discovery.

``station_latitude`` and ``station_longitude`` are published as decimal
degrees, but no HydroNet layer index, app configuration or data.gov.ie record
states their reference system. The data.gov.ie record declares ``epsg:29902``
for the dataset as a whole, which cannot describe latitude and longitude. The
catalogue therefore keeps the coordinates and publishes ``crs`` as unknown.
"""

from __future__ import annotations

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    AcquisitionRecord,
    EvidenceReference,
    ExternalFactReference,
    FactBinding,
    NativeTableIdentity,
    RecordingReference,
    SourceRecord,
    SourceStatement,
    Transformation,
    complete_transformed_fact_universe,
)
from rivretrieve._internal.catalogue_origins import (
    Authored,
    AuthoredValue,
    Evidence,
    Field,
    FloatConversion,
    NativeColumn,
    NotPublished,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE
from rivretrieve._internal.catalogues.station_metadata import MetadataField

STATIONS_URL = "https://epawebapp.epa.ie/Hydronet/output/internet/stations/stations.json"
DISCLAIMER_URL = "https://epawebapp.epa.ie/Hydronet/output/html/disclaimer.html"
FAQ_URL = "https://epawebapp.epa.ie/Hydronet/output/html/FAQ.html"

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("ie_epa")),
    "station_id": Field(NativeColumn("station_no")),
    "latitude": Field(NativeColumn("station_latitude"), FloatConversion()),
    "longitude": Field(NativeColumn("station_longitude"), FloatConversion()),
    "crs": NotPublished(Evidence(STATIONS_URL)),
}

STATION_METADATA_NOTICE = (
    "Station metadata from the Environmental Protection Agency (EPA) HydroNet station register "
    f"({STATIONS_URL}): station name (`station_name`), water body (`WTO_OBJECT`) and catchment size "
    "(`CATCHMENT_SIZE` with its inline km² unit). Elevation is withheld: `station_gauge_datum` is a "
    "water-level datum, not a ground elevation. Licensed under CC BY 4.0. Use is subject to the notes, "
    f"warnings and conditions of the HydroNet disclaimer ({DISCLAIMER_URL}) and FAQ ({FAQ_URL})."
)

STATION_METADATA_FIELDS = (
    MetadataField(
        "station_name",
        "station_name",
        source_scope="hydronet_stations",
        source_facts=("source.station.registry",),
    ),
    MetadataField(
        "water_body_name",
        "WTO_OBJECT",
        source_scope="hydronet_stations",
        source_facts=("source.station.registry",),
    ),
    MetadataField(
        "drainage_area",
        "CATCHMENT_SIZE",
        source_scope="hydronet_stations",
        source_facts=("source.station.registry",),
        support_facts=("source.station.catchment_size_unit",),
        inline_unit="km²",
    ),
)

_CATALOGUE_SOURCE_FACTS = {
    "station": ("source.station.registry",),
    "product": ("source.station_product.associations", "source.series.fields"),
    "station_product": ("source.station_product.associations",),
}


def build_acquisition_provenance(
    native_identity: NativeTableIdentity,
    recordings: tuple[RecordingReference, ...],
    *,
    acquisitions: tuple[AcquisitionRecord, ...],
    source_bindings: tuple[FactBinding, ...],
    statements: tuple[SourceStatement, ...] = (),
) -> AcquisitionProvenance:
    """Bind EPA HydroNet originals and the derived native table to catalogue facts."""
    if any(binding.source_id != "ie_epa" or binding.transformation is not None for binding in source_bindings):
        raise ValueError("EPA HydroNet source bindings must directly identify selected acquisitions")
    facts = tuple(fact for binding in source_bindings for fact in binding.facts)
    required = {fact for group in _CATALOGUE_SOURCE_FACTS.values() for fact in group}
    required.update(("source.station.catchment_size_unit", "source.provider.terms", "source.provider.attribution"))
    if missing := required - set(facts):
        raise ValueError(f"Missing EPA HydroNet source facts: {sorted(missing)!r}")
    provenance = AcquisitionProvenance(
        schema_version=2,
        provider_id="ie_epa",
        native_table=native_identity,
        source_records=(
            SourceRecord(
                source_id="ie_epa",
                issuer="Environmental Protection Agency (EPA)",
                acquisitions=acquisitions,
                evidence=tuple(
                    EvidenceReference(
                        evidence_id=item.recording_id,
                        description="Selected EPA HydroNet catalogue source",
                        recording=item,
                    )
                    for item in recordings
                ),
                statements=statements,
            ),
        ),
        fact_bindings=source_bindings,
        fact_universe=facts,
    )
    for carrier, source_facts in _CATALOGUE_SOURCE_FACTS.items():
        provenance = complete_transformed_fact_universe(
            provenance,
            tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith(carrier + ".")),
            transformation=Transformation(
                name=f"EPA HydroNet source facts to canonical {carrier}",
                external_inputs=tuple(ExternalFactReference(source_id="ie_epa", fact=fact) for fact in source_facts),
            ),
            fact_group=f"canonical_ie_epa_{carrier}",
        )
    provenance = complete_transformed_fact_universe(
        provenance,
        ("provider.license", "provider.citation"),
        transformation=Transformation(
            name="Selected EPA HydroNet CC BY 4.0 terms and pass-on conditions",
            external_inputs=(
                ExternalFactReference(source_id="ie_epa", fact="source.provider.terms"),
                ExternalFactReference(source_id="ie_epa", fact="source.provider.attribution"),
            ),
        ),
        fact_group="canonical_ie_epa_terms",
    )
    return complete_transformed_fact_universe(
        provenance,
        tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("provider.")),
        transformation=Transformation(
            name="RivRetrieve ie_epa identity and catalogue-only capabilities",
            kind="authored_constant",
            external_inputs=(),
        ),
        fact_group="canonical_ie_epa_provider",
    )


NATIVE_TABLE_ACQUISITION_IDS = ("epa-stations-json", "epa-station-file-lists-2026-11-27")
CATALOGUE_SUPPORTING_INPUTS: dict[str, tuple[str, ...]] = {}
CATALOGUE_BUILD_DECLARATIONS = (
    ("maintenance/catalogue/ie_epa/official/selection.json", None),
    ("src/rivretrieve/_internal/providers/ie_epa/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/ie_epa/origins.py", "NATIVE_TABLE_ACQUISITION_IDS"),
    ("src/rivretrieve/_internal/providers/ie_epa/origins.py", "CATALOGUE_SUPPORTING_INPUTS"),
    ("src/rivretrieve/_internal/providers/ie_epa/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/ie_epa/origins.py", "STATION_METADATA_NOTICE"),
    ("src/rivretrieve/_internal/providers/ie_epa/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/providers/ie_epa/series.py", "PRODUCT_SPECS"),
    ("src/rivretrieve/_internal/providers/ie_epa/series.py", "catalogue_product_rows"),
    ("src/rivretrieve/_internal/providers/ie_epa/series.py", "describe_associations"),
    ("src/rivretrieve/_internal/providers/ie_epa/generate_catalogue.py", "read_catalogue_sources"),
    ("src/rivretrieve/_internal/providers/ie_epa/station_metadata.py", "project_station_metadata"),
)
