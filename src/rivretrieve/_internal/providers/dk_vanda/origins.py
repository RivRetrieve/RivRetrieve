"""VandA source declarations for offline station discovery.

Coordinate conversion: every retained station's `location.srid` was checked
and found to be uniformly `"25832"` (ETRS89 / UTM zone 32N); re-projecting all
1,565 river stations to EPSG:4326 and checking against Denmark's bounding box
confirmed this numerically (research/dk-vanda-source-access.md, 2026-11-09),
rather than trusting the field's name alone. VandA does not publish latitude
and longitude directly, so this conversion is RivRetrieve's own computation
from the source-stated SRID, not a source-documented geographic coordinate.
"""

from collections.abc import Mapping

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
    Documented,
    DocumentedValue,
    Evidence,
    Field,
    FieldConversion,
    NativeColumn,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE
from rivretrieve._internal.catalogues.station_metadata import MetadataField


class Utm32EtrsToWgs84Conversion(FieldConversion):
    """Re-project the native ETRS89/UTM32N station coordinate to EPSG:4326.

    Reads both ``x`` and ``y`` from the native row regardless of which one
    ``native_column`` names, since a single projected coordinate needs both.
    """

    __slots__ = ()

    @property
    def name(self) -> ConversionName:
        return ConversionName("utm32n_etrs89_to_wgs84")

    def apply(self, canonical_column: str, native_column: NativeColumn, native_row: Mapping[str, object]) -> object:
        del native_column
        if canonical_column not in {"latitude", "longitude"}:
            raise ValueError("Utm32EtrsToWgs84Conversion applies only to latitude or longitude")
        x, y = native_row["x"], native_row["y"]
        if x is None or y is None:
            return None
        from pyproj import Transformer

        transformer = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True)
        lon, lat = transformer.transform(x, y)
        return lon if canonical_column == "longitude" else lat


# location.srid=25832 on every retained station; re-projected to EPSG:4326 and
# numerically verified against Denmark's bounding box
# (research/dk-vanda-source-access.md, 2026-11-09).
_CRS_EVIDENCE = Evidence("https://vandah.miljoeportal.dk/api/stations")

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("dk_vanda")),
    "station_id": Field(NativeColumn("stationId")),
    "latitude": Field(NativeColumn("y"), Utm32EtrsToWgs84Conversion()),
    "longitude": Field(NativeColumn("x"), Utm32EtrsToWgs84Conversion()),
    "crs": Documented(DocumentedValue("EPSG:4326"), _CRS_EVIDENCE),
}

STATION_METADATA_NOTICE = (
    "Station metadata from Miljøstyrelsen's VandA service, distributed through the Miljøportal platform "
    "(https://vandah.miljoeportal.dk/api). This RivRetrieve projection selected the fields below from the "
    "published station registry; source names and absence remain unchanged. Danmarks Miljøportal's own "
    "open-data catalogue record states this dataset (and its API distribution) is licensed CC0 (see the "
    "continuing research record's 'Terms and attribution: resolved' section)."
)

STATION_METADATA_FIELDS = (
    MetadataField("station_name", "name", source_scope="station_registry", source_facts=("source.station.registry",)),
    MetadataField(
        "drainage_area",
        "catchmentAreaKm2",
        "km2",
        source_scope="station_registry",
        source_facts=("source.station.registry",),
        support_facts=("source.station.catchment_area_unit",),
    ),
)


_CATALOGUE_SOURCE_FACTS = {
    "station": ("source.station.registry",),
    "product": ("source.station_product.associations",),
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
    """Bind original source evidence and a retained derivative to catalogue facts.

    Terms of use are established directly from Danmarks Miljøportal's own
    open-data catalogue record (Effort #800, step 5; see
    research/dk-vanda-source-access.md's "Terms and attribution: resolved
    (2026-11-14)" section in the evidence repository): CC0, stated at both
    dataset and API-distribution level. Callers must still bind
    ``source.provider.terms``/``source.provider.attribution`` to an acquisition
    that records what was actually checked, not invent a statement. An empty
    ``statements`` tuple correctly yields an unknown license rather than one
    this port has not verified.
    """
    if any(binding.source_id != "dk_vanda" or binding.transformation is not None for binding in source_bindings):
        raise ValueError("VandA source bindings must directly identify selected acquisitions")
    facts = tuple(fact for binding in source_bindings for fact in binding.facts)
    required = {fact for group in _CATALOGUE_SOURCE_FACTS.values() for fact in group}
    required.update(
        (
            "source.station.catchment_area_unit",
            "source.provider.terms",
            "source.provider.attribution",
            "source.series.fields",
        )
    )
    if missing := required - set(facts):
        raise ValueError(f"Missing VandA source facts: {sorted(missing)!r}")
    provenance = AcquisitionProvenance(
        schema_version=2,
        provider_id="dk_vanda",
        native_table=native_identity,
        source_records=(
            SourceRecord(
                source_id="dk_vanda",
                issuer="Miljøstyrelsen (Danish Environmental Protection Agency)",
                acquisitions=acquisitions,
                evidence=tuple(
                    EvidenceReference(
                        evidence_id=item.recording_id, description="Selected VandA catalogue source", recording=item
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
                name=f"VandA source facts to canonical {carrier}; unsupported meanings remain unknown",
                external_inputs=tuple(ExternalFactReference(source_id="dk_vanda", fact=fact) for fact in source_facts),
            ),
            fact_group=f"canonical_dk_vanda_{carrier}",
        )
    provenance = complete_transformed_fact_universe(
        provenance,
        ("provider.license", "provider.citation"),
        transformation=Transformation(
            name="Selected VandA attribution; no inferred license",
            external_inputs=(
                ExternalFactReference(source_id="dk_vanda", fact="source.provider.terms"),
                ExternalFactReference(source_id="dk_vanda", fact="source.provider.attribution"),
            ),
        ),
        fact_group="canonical_dk_vanda_terms",
    )
    return complete_transformed_fact_universe(
        provenance,
        tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("provider.")),
        transformation=Transformation(
            name="RivRetrieve dk_vanda identity and catalogue-only capabilities",
            kind="authored_constant",
            external_inputs=(),
        ),
        fact_group="canonical_dk_vanda_provider",
    )


# Existing acquisition fact materialised in the retained native table.
# This declares derived-input support, not preservation of original responses.
NATIVE_TABLE_ACQUISITION_IDS = ("dk-vanda-catalogue-stations",)

CATALOGUE_SUPPORTING_INPUTS: dict[str, tuple[str, ...]] = {}
CATALOGUE_BUILD_DECLARATIONS = (
    ("maintenance/catalogue/dk_vanda/official/selection.json", None),
    ("src/rivretrieve/_internal/providers/dk_vanda/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/dk_vanda/origins.py", "NATIVE_TABLE_ACQUISITION_IDS"),
    ("src/rivretrieve/_internal/providers/dk_vanda/origins.py", "CATALOGUE_SUPPORTING_INPUTS"),
    ("src/rivretrieve/_internal/providers/dk_vanda/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/dk_vanda/origins.py", "STATION_METADATA_NOTICE"),
    ("src/rivretrieve/_internal/providers/dk_vanda/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/providers/dk_vanda/series.py", "series_mappings"),
    ("src/rivretrieve/_internal/providers/dk_vanda/series.py", "stage_identity"),
    ("src/rivretrieve/_internal/providers/dk_vanda/series.py", "stage_facts"),
    ("src/rivretrieve/_internal/providers/dk_vanda/generate_catalogue.py", "read_catalogue_sources"),
    ("src/rivretrieve/_internal/providers/dk_vanda/station_metadata.py", "project_station_metadata"),
)
