"""Germany PEGELONLINE catalogue origins and acquisition provenance.

PEGELONLINE's `stations.json?includeTimeseries=true&includeCharacteristicValues=true`
response (step 1's settled source,
`planning/visions/2026-11-24-de-pegelonline-source-scope-and-access.md`) is the
single input this catalogue builder consumes. Unlike `ch_foen`/`dk_vanda`, no
retained-input-receipt/selection.json evidence trail is used here: the committed
native table (`catalogue/native.parquet`) and this module's authored provenance
follow the lighter `lt_lhmt` pattern, since PEGELONLINE's one public, unauthenticated
endpoint needs no archive-member selection step.
"""

from collections.abc import Mapping
from datetime import datetime

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
    ConversionName,
    Field,
    FieldConversion,
    NativeColumn,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE
from rivretrieve._internal.catalogues.station_metadata import MetadataField

STATIONS_URL = (
    "https://www.pegelonline.wsv.de/webservices/rest-api/v2/stations.json"
    "?includeTimeseries=true&includeCharacteristicValues=true&includeTrmTimeseries=true"
)
TERMS_URL = "https://pegelonline.wsv.de/gast/nutzungsbedingungen"


class CrsFromCoordinatePresenceConversion(FieldConversion):
    """Resolve `crs` from whether a station published coordinates at all.

    57 of 787 stations publish no `latitude`/`longitude` (step 2 vision). Those
    stations keep `latitude`/`longitude = null` and `crs = "unknown"`; every other
    station is WGS84, the API's native and only coordinate system. `crs` cannot be
    a single `Documented` constant because its value genuinely depends on another
    native field's presence, not on a fixed publisher statement.
    """

    __slots__ = ()

    @property
    def name(self) -> ConversionName:
        return ConversionName("pegelonline_crs_from_coordinate_presence")

    def apply(self, canonical_column: str, native_column: NativeColumn, native_row: Mapping[str, object]) -> object:
        if canonical_column != "crs":
            raise ValueError("CrsFromCoordinatePresenceConversion applies only to crs")
        value = native_row[str(native_column)]
        return "unknown" if value is None else "EPSG:4326"


STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("de_pegelonline")),
    "station_id": Field(NativeColumn("uuid")),
    "latitude": Field(NativeColumn("latitude")),
    "longitude": Field(NativeColumn("longitude")),
    "crs": Field(NativeColumn("latitude"), CrsFromCoordinatePresenceConversion()),
}

# `source_scope`/`source_facts` are left at their defaults: these fields are
# exposed straight from the historical native table's own flat columns (no
# supplementary source, no per-field override), matching lt_lhmt's pattern.
# `agency`, `number`, `km` and `remark` have no fitting SOURCE_METADATA_SCHEMA
# attribute_role (station_name/water_body_name/drainage_area/elevation) and are
# not forced into one; they remain preserved verbatim in the retained native
# table instead. See the implementation PR description for this judgment call.
STATION_METADATA_FIELDS: tuple[MetadataField, ...] = (
    MetadataField("station_name", "longname"),
    MetadataField("station_name", "shortname"),
    MetadataField("water_body_name", "water_longname"),
    MetadataField("water_body_name", "water_shortname"),
    MetadataField(
        "elevation",
        "w_gauge_zero_value",
        datum_field="w_unit",
        datum_support=("source.station.pegelonline_vertical_datum_regime",),
    ),
)

STATION_METADATA_NOTICE = (
    "Station metadata from WSV/GDWS's PEGELONLINE service "
    "(https://www.pegelonline.wsv.de/webservices/rest-api/v2). This RivRetrieve "
    "projection selected the fields below from the published station catalogue; "
    "source names and absence remain unchanged. The `elevation` field's `w_unit` "
    "datum association records the W timeseries' own native unit (`cm`, `m+NN` or "
    "`m+PNP`) alongside its `gaugeZero` value, not a geodetic elevation datum code, "
    "so a later conversion step can find the vertical-datum regime without "
    "re-fetching the source. PEGELONLINE's terms page states the licence "
    "`DL-DE->Zero-2.0` over information, products and services from the site "
    "with no origin-based exception."
)

_CATALOGUE_SOURCE_FACTS = {
    "station": (
        "source.station.native_identity",
        "source.station.native_geometry",
        "source.station.documented_crs",
    ),
    "product": ("source.product.native_timeseries_shortnames", "source.product.temporal_meaning"),
    "station_product": ("source.station.native_identity", "source.station_product.native_timeseries_listing"),
}

# Supports the `elevation` metadata field's `w_unit` datum association
# (STATION_METADATA_FIELDS below), not a canonical catalogue carrier.
_VERTICAL_DATUM_REGIME_FACT = "source.station.pegelonline_vertical_datum_regime"


def build_acquisition_provenance(
    *,
    stations_retrieved_at: datetime,
    native_identity: NativeTableIdentity,
    terms_recording: RecordingReference,
    license_exact_text: str,
) -> AcquisitionProvenance:
    """Build closed de_pegelonline acquisition provenance for the station catalogue.

    Parameters
    ----------
    stations_retrieved_at
        When the committed native table's one `stations.json` response was fetched.
    native_identity
        Byte identity of the committed native table (`catalogue/native.parquet`).
    terms_recording
        Retained recording of PEGELONLINE's terms-of-use page.
    license_exact_text
        The exact licence sentence quoted from `terms_recording`'s retained bytes.

    Returns
    -------
    AcquisitionProvenance
        Closed source and canonical fact bindings for the four catalogue tables.
    """
    stations_acquisition_id = "de_pegelonline-stations-catalogue"
    terms_acquisition_id = "de_pegelonline-terms"
    license_fact = "source.de_pegelonline.license_statement"
    # Some source facts are shared across more than one canonical carrier group
    # (e.g. native station identity underlies both `station` and
    # `station_product`); bind each exactly once here, and let each carrier's
    # transformation below reference it again as an external input.
    source_facts = tuple(dict.fromkeys(fact for group in _CATALOGUE_SOURCE_FACTS.values() for fact in group))
    fact_universe = (*source_facts, _VERTICAL_DATUM_REGIME_FACT, license_fact)
    source_bindings = (
        FactBinding(
            fact_group=stations_acquisition_id,
            facts=source_facts,
            source_id="de_pegelonline",
            acquisition_id=stations_acquisition_id,
        ),
        FactBinding(
            fact_group=f"{stations_acquisition_id}-vertical-datum-regime",
            facts=(_VERTICAL_DATUM_REGIME_FACT,),
            source_id="de_pegelonline",
            acquisition_id=stations_acquisition_id,
        ),
        FactBinding(
            fact_group=terms_acquisition_id,
            facts=(license_fact,),
            source_id="de_pegelonline",
            acquisition_id=terms_acquisition_id,
        ),
    )
    provenance = AcquisitionProvenance(
        schema_version=2,
        provider_id="de_pegelonline",
        native_table=native_identity,
        source_records=(
            SourceRecord(
                source_id="de_pegelonline",
                issuer="Wasserstraßen- und Schifffahrtsverwaltung des Bundes (WSV) / "
                "Generaldirektion Wasserstraßen und Schifffahrt (GDWS)",
                operator="PEGELONLINE (ITZBund)",
                acquisitions=(
                    AcquisitionRecord(
                        acquisition_id=stations_acquisition_id,
                        method="http_request",
                        instant_type="retrieval",
                        description="Complete PEGELONLINE station catalogue, including timeseries and characteristic values",
                        requested_from=(STATIONS_URL,),
                        retrieved_at_start=stations_retrieved_at,
                    ),
                    AcquisitionRecord(
                        acquisition_id=terms_acquisition_id,
                        method="http_request",
                        instant_type="retrieval",
                        description="PEGELONLINE terms-of-use page recording",
                        requested_from=(terms_recording.source_url,),
                        retrieved_at_start=terms_recording.retrieved_at,
                        recording_ids=(terms_recording.recording_id,),
                    ),
                ),
                evidence=(
                    EvidenceReference(
                        evidence_id=terms_recording.recording_id,
                        description="PEGELONLINE terms-of-use page: licence DL-DE->Zero-2.0 over site information, "
                        "products and services, with no origin-based exception",
                        recording=terms_recording,
                    ),
                ),
                statements=(
                    SourceStatement(
                        kind="license",
                        exact_text=license_exact_text,
                        recording_id=terms_recording.recording_id,
                        fact=license_fact,
                    ),
                ),
            ),
        ),
        fact_bindings=source_bindings,
        fact_universe=fact_universe,
    )
    for carrier, facts in _CATALOGUE_SOURCE_FACTS.items():
        provenance = complete_transformed_fact_universe(
            provenance,
            tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith(carrier + ".")),
            transformation=Transformation(
                name=f"PEGELONLINE source facts to canonical {carrier}; statistic and periods remain unknown",
                external_inputs=tuple(ExternalFactReference(source_id="de_pegelonline", fact=fact) for fact in facts),
            ),
            fact_group=f"canonical_de_pegelonline_{carrier}",
        )
    provenance = complete_transformed_fact_universe(
        provenance,
        ("provider.license", "provider.citation"),
        transformation=Transformation(
            name="Selected PEGELONLINE licence statement; no established citation wording",
            external_inputs=(ExternalFactReference(source_id="de_pegelonline", fact=license_fact),),
        ),
        fact_group="canonical_de_pegelonline_terms",
    )
    return complete_transformed_fact_universe(
        provenance,
        tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("provider.")),
        transformation=Transformation(
            name="RivRetrieve de_pegelonline identity and live-catalogue capabilities",
            kind="authored_constant",
            external_inputs=(),
        ),
        fact_group="canonical_de_pegelonline_provider",
    )


CATALOGUE_BUILD_DECLARATIONS = (
    ("src/rivretrieve/_internal/providers/de_pegelonline/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/de_pegelonline/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/de_pegelonline/origins.py", "STATION_METADATA_NOTICE"),
    ("src/rivretrieve/_internal/providers/de_pegelonline/generate_catalogue.py", "build_catalogue"),
)

# Additional retained declarations used by these source facts; not original-body claims.
CATALOGUE_SUPPORTING_INPUTS: dict[str, tuple[str, ...]] = {}
