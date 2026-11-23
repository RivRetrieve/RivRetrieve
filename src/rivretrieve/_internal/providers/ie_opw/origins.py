"""Ireland OPW (`ie_opw`) source declarations for offline river station discovery.

All retained stations carry decimal WGS84 coordinates in ``stations.json``
verified equal to ``https://waterlevel.ie/geojson/`` which explicitly declares
``EPSG:4326``. No coordinate transformation is required beyond ``FloatConversion``.
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
    Documented,
    DocumentedValue,
    Evidence,
    Field,
    FloatConversion,
    NativeColumn,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE
from rivretrieve._internal.catalogues.station_metadata import MetadataField

_CRS_EVIDENCE = Evidence("https://waterlevel.ie/geojson/")

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("ie_opw")),
    "station_id": Field(NativeColumn("station_no")),
    "latitude": Field(NativeColumn("station_latitude"), FloatConversion()),
    "longitude": Field(NativeColumn("station_longitude"), FloatConversion()),
    "crs": Documented(DocumentedValue("EPSG:4326"), _CRS_EVIDENCE),
}

STATION_METADATA_NOTICE = (
    "Station metadata from Ireland's Office of Public Works (OPW) Hydro-Data "
    "registry (https://waterlevel.ie/hydro-data/data/internet/stations/stations.json): "
    "station name (`station_name`), waterbody (`WTO_OBJECT`), and catchment size "
    "(`CATCHMENT_SIZE` in inline km2 units). Elevation is withheld (`station_elevation` "
    "is blank across river stations and `station_gauge_datum` is staff-gauge datum height "
    "above Ordnance Datum). Contains Irish Public Sector Information licensed under a "
    "Creative Commons Attribution 4.0 International (CC BY 4.0) licence "
    "(source http://waterlevel.ie - provided by the Office of Public Works.)."
)

STATION_METADATA_FIELDS = (
    MetadataField(
        "station_name",
        "station_name",
        source_scope="hydro_stations",
        source_facts=("source.station.registry",),
    ),
    MetadataField(
        "water_body_name",
        "WTO_OBJECT",
        source_scope="hydro_stations",
        source_facts=("source.station.registry",),
    ),
    MetadataField(
        "drainage_area",
        "CATCHMENT_SIZE",
        source_scope="hydro_stations",
        source_facts=("source.station.registry",),
        support_facts=("source.station.catchment_size_unit",),
        inline_unit="km²",
    ),
)

_CATALOGUE_SOURCE_FACTS = {
    "station": ("source.station.registry", "source.station.geojson_crs"),
    "product": (
        "source.station_product.associations",
        "source.series.fields",
        "source.product.unit_definitions",
    ),
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
    """Bind Office of Public Works originals and derived native table to catalogue facts."""
    if any(binding.source_id != "ie_opw" or binding.transformation is not None for binding in source_bindings):
        raise ValueError("OPW source bindings must directly identify selected acquisitions")
    facts = tuple(fact for binding in source_bindings for fact in binding.facts)
    required = {fact for group in _CATALOGUE_SOURCE_FACTS.values() for fact in group}
    required.update(
        (
            "source.station.catchment_size_unit",
            "source.provider.terms",
            "source.provider.attribution",
        )
    )
    if missing := required - set(facts):
        raise ValueError(f"Missing OPW source facts: {sorted(missing)!r}")
    provenance = AcquisitionProvenance(
        schema_version=2,
        provider_id="ie_opw",
        native_table=native_identity,
        source_records=(
            SourceRecord(
                source_id="ie_opw",
                issuer="Office of Public Works (OPW)",
                acquisitions=acquisitions,
                evidence=tuple(
                    EvidenceReference(
                        evidence_id=item.recording_id,
                        description="Selected OPW Hydro-Data catalogue source",
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
                name=f"OPW Hydro-Data source facts to canonical {carrier}",
                external_inputs=tuple(ExternalFactReference(source_id="ie_opw", fact=fact) for fact in source_facts),
            ),
            fact_group=f"canonical_ie_opw_{carrier}",
        )
    provenance = complete_transformed_fact_universe(
        provenance,
        ("provider.license", "provider.citation"),
        transformation=Transformation(
            name="Selected OPW CC BY 4.0 terms and attribution",
            external_inputs=(
                ExternalFactReference(source_id="ie_opw", fact="source.provider.terms"),
                ExternalFactReference(source_id="ie_opw", fact="source.provider.attribution"),
            ),
        ),
        fact_group="canonical_ie_opw_terms",
    )
    return complete_transformed_fact_universe(
        provenance,
        tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("provider.")),
        transformation=Transformation(
            name="RivRetrieve ie_opw identity and catalogue-only capabilities",
            kind="authored_constant",
            external_inputs=(),
        ),
        fact_group="canonical_ie_opw_provider",
    )


CATALOGUE_SUPPORTING_INPUTS: dict[str, tuple[str, ...]] = {}
CATALOGUE_BUILD_DECLARATIONS = (
    ("maintenance/catalogue/ie_opw/official/selection.json", None),
    ("src/rivretrieve/_internal/providers/ie_opw/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/ie_opw/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/ie_opw/origins.py", "STATION_METADATA_NOTICE"),
    ("src/rivretrieve/_internal/providers/ie_opw/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/providers/ie_opw/generate_catalogue.py", "read_catalogue_sources"),
    ("src/rivretrieve/_internal/providers/ie_opw/station_metadata.py", "project_station_metadata"),
    ("src/rivretrieve/_internal/providers/ie_opw/series.py", "describe_associations"),
)
