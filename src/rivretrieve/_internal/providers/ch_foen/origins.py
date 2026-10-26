"""Official Swiss catalogue origins and explicitly selected acquisition evidence."""

from datetime import datetime
from pathlib import PurePosixPath

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
    NativeColumn,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE
from rivretrieve._internal.catalogues.station_metadata import MetadataField

# Name mappings require genuine-input validation and owner disclosure approval
# before generated metadata can be packaged. Native presence is insufficient.
STATION_REFERENCE_METADATA_FIELDS: tuple[MetadataField, ...] = (
    MetadataField(
        "station_name",
        "data-name",
        source_scope="station_directory",
        source_facts=("source.station.foen_directory_identity_and_names",),
    ),
    MetadataField(
        "water_body_name",
        "data-hydro-body",
        source_scope="station_directory",
        source_facts=("source.station.foen_directory_identity_and_names",),
    ),
    MetadataField(
        "drainage_area",
        "Catchment size",
        "km2",
        source_scope="station_page",
        source_facts=("source.station.foen_reference_altitude_and_catchment",),
    ),
    MetadataField(
        "elevation",
        "Station altitude",
        "m",
        datum="LN02",
        source_scope="station_page",
        source_facts=("source.station.foen_reference_altitude_and_catchment",),
        support_facts=("source.station.foen_altitude_unit_datum_definition",),
        datum_support=("source.station.foen_altitude_unit_datum_definition",),
    ),
)

API_STATION_METADATA_FIELDS: tuple[MetadataField, ...] = (
    MetadataField("station_name", "name", source_scope="station_api"),
    MetadataField("water_body_name", "riverName", source_scope="station_api"),
)
STATION_METADATA_FIELDS = (*STATION_REFERENCE_METADATA_FIELDS, *API_STATION_METADATA_FIELDS)


STATION_METADATA_NOTICE = (
    "Station metadata is from the Federal Office for the Environment (FOEN). "
    "Names and station-information text remain unchanged. "
    "This metadata projection is produced by RivRetrieve."
)

CRS_EVIDENCE_URL = "https://data.bafu.admin.ch/dataproduct-water-observations"
STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("ch_foen")),
    "station_id": Field(NativeColumn("no")),
    "latitude": Field(NativeColumn("latitude")),
    "longitude": Field(NativeColumn("longitude")),
    "crs": Documented(DocumentedValue("EPSG:4326"), Evidence(CRS_EVIDENCE_URL)),
}

_CATALOGUE_SOURCE_FACTS = {
    "station": (
        "source.station.native_identity",
        "source.station.native_geometry",
        "source.station.documented_crs",
    ),
    "product": ("source.product.native_physics", "source.product.temporal_meaning"),
    "station_product": (
        "source.station.native_identity",
        "source.station_product.source_associations",
    ),
}


def build_acquisition_provenance(
    native_identity: NativeTableIdentity,
    recordings: tuple[RecordingReference, ...],
    *,
    acquisitions: tuple[AcquisitionRecord, ...],
    source_bindings: tuple[FactBinding, ...],
    statements: tuple[SourceStatement, ...] = (),
) -> AcquisitionProvenance:
    """Bind selected official source evidence to the Swiss catalogue.

    Parameters
    ----------
    native_identity
        Identity of the derived native table selected for this build.
    recordings
        Selected original responses and documentation, with their exact identities.
    acquisitions
        Acquisition records claiming the selected recordings, including any page campaigns.
    source_bindings
        Direct ``ch_foen`` bindings for station identity, geometry, CRS, physical facts,
        and source associations. Temporal meaning requires its own source binding.
        Approved station metadata uses its existing source fact names.
    statements
        An exact license statement is required. Citation wording is optional;
        an unestablished citation remains null, without claiming source silence.

    Returns
    -------
    AcquisitionProvenance
        Closed source and canonical fact bindings. This pure operation does not
        verify bytes, select archive members or approve metadata disclosure.

    Raises
    ------
    ValueError
        If required source facts are missing or supplied relations do not close.
    """
    if any(binding.source_id != "ch_foen" or binding.transformation is not None for binding in source_bindings):
        raise ValueError("Official source bindings must directly name ch_foen acquisitions")
    facts = tuple(fact for binding in source_bindings for fact in binding.facts)
    required = {fact for group in _CATALOGUE_SOURCE_FACTS.values() for fact in group}
    if missing := required - set(facts):
        raise ValueError(f"Missing official catalogue source facts: {sorted(missing)!r}")
    provenance = AcquisitionProvenance(
        schema_version=2,
        provider_id="ch_foen",
        native_table=native_identity,
        source_records=(
            SourceRecord(
                source_id="ch_foen",
                issuer="Federal Office for the Environment (FOEN)",
                acquisitions=acquisitions,
                evidence=tuple(
                    EvidenceReference(
                        evidence_id=recording.recording_id,
                        description="Selected official FOEN catalogue source",
                        recording=recording,
                    )
                    for recording in recordings
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
                name=(
                    f"Official FOEN source facts to canonical {carrier} fields; "
                    "route-wide temporal fields and sampled record bounds remain unresolved"
                ),
                external_inputs=tuple(ExternalFactReference(source_id="ch_foen", fact=fact) for fact in source_facts),
            ),
            fact_group=f"canonical_foen_{carrier}",
        )
    term_facts = tuple(statement.fact for statement in statements if statement.fact is not None)
    if not any(statement.kind == "license" and statement.fact is not None for statement in statements):
        raise ValueError("Official catalogue requires selected license evidence")
    provenance = complete_transformed_fact_universe(
        provenance,
        ("provider.license", "provider.citation"),
        transformation=Transformation(
            name="Selected FOEN terms statements; unestablished licence or citation remains null",
            external_inputs=tuple(ExternalFactReference(source_id="ch_foen", fact=fact) for fact in term_facts),
        ),
        fact_group="canonical_foen_terms",
    )
    return complete_transformed_fact_universe(
        provenance,
        tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("provider.")),
        transformation=Transformation(
            name="RivRetrieve Swiss provider identity and catalogue capabilities",
            kind="authored_constant",
            external_inputs=(),
        ),
        fact_group="canonical_foen_provider",
    )


STATION_DIRECTORY_REFERENCE = RecordingReference(
    recording_id="ch_foen-foen-station-directory-body",
    repository_path="maintenance/catalogue/station_metadata/sources/ch_foen/foen-station-directory/body",
    source_url="https://www.hydrodaten.admin.ch/en/seen-und-fluesse/stations",
    retrieved_at=datetime.fromisoformat("2026-10-04T10:21:35.238298+00:00"),
    media_type="text/html; charset=utf-8",
    sha256="45236552617612f7f4c29203fcfaa4d5a269ea2a09a016184297059cfe035b11",
)

STATION_DATUM_REFERENCE = RecordingReference(
    recording_id="ch_foen-foen-questions-body",
    repository_path="maintenance/catalogue/station_metadata/sources/ch_foen/foen-questions/body",
    source_url="https://www.hydrodaten.admin.ch/en/questions",
    retrieved_at=datetime.fromisoformat("2026-10-04T10:20:47.014071+00:00"),
    media_type="text/html; charset=utf-8",
    sha256="08f018954ac867f30c0958cd8993468d7992b3a63d777a530fb390f47b7acd68",
)

STATION_TERMS_REFERENCE = RecordingReference(
    recording_id="ch_foen-foen-station-bulk-body",
    repository_path="maintenance/catalogue/station_metadata/sources/ch_foen/foen-station-bulk/body",
    source_url="https://data.geo.admin.ch/ch.bafu.hydroweb-messstationen_zustand/data.zip",
    retrieved_at=datetime.fromisoformat("2026-10-04T10:24:03.413551+00:00"),
    media_type="application/octet-stream",
    sha256="8997c6d31e88e962d91de2604555dc04fdd2a8c4e6b0fe22445d113fcf878934",
)

STATION_PAGE_ROOT = "maintenance/catalogue/station_metadata/sources/ch_foen/station_pages"
STATION_PAGE_MANIFEST_SHA256 = "398ddad76cbccb24c50d3ae6f2112a90c81ef4867146de163ee9fcae1acfdb40"


def with_station_metadata_sources(
    provenance: AcquisitionProvenance, page_recordings: tuple[RecordingReference, ...]
) -> AcquisitionProvenance:
    """Keep direct FOEN metadata acquisitions separate from the historical intermediary."""
    if not page_recordings:
        raise ValueError("FOEN metadata publication requires its selected station page recordings")
    source_id = "ch_foen.foen_station_reference"
    records = (STATION_DIRECTORY_REFERENCE, STATION_DATUM_REFERENCE, STATION_TERMS_REFERENCE)
    acquisitions = (
        AcquisitionRecord(
            acquisition_id="ch_foen-foen-station-directory",
            method="http_request",
            instant_type="retrieval",
            description="Retained direct FOEN station metadata source",
            requested_from=(STATION_DIRECTORY_REFERENCE.source_url,),
            retrieved_at_start=STATION_DIRECTORY_REFERENCE.retrieved_at,
            recording_ids=(STATION_DIRECTORY_REFERENCE.recording_id,),
        ),
        AcquisitionRecord(
            acquisition_id="ch_foen-foen-questions",
            method="http_request",
            instant_type="retrieval",
            description="Retained direct FOEN station metadata source",
            requested_from=(STATION_DATUM_REFERENCE.source_url,),
            retrieved_at_start=STATION_DATUM_REFERENCE.retrieved_at,
            recording_ids=(STATION_DATUM_REFERENCE.recording_id,),
        ),
        AcquisitionRecord(
            acquisition_id="ch_foen-foen-station-bulk",
            method="http_request",
            instant_type="retrieval",
            description="Retained direct FOEN station metadata source",
            requested_from=(STATION_TERMS_REFERENCE.source_url,),
            retrieved_at_start=STATION_TERMS_REFERENCE.retrieved_at,
            recording_ids=(STATION_TERMS_REFERENCE.recording_id,),
        ),
        AcquisitionRecord(
            acquisition_id="station_reference_pages",
            method="http_campaign",
            instant_type="retrieval_interval",
            description="Directory-linked FOEN station reference page responses; separate from historical intermediary inputs",
            requested_from=tuple(item.source_url for item in page_recordings),
            retrieved_at_start=min(item.retrieved_at for item in page_recordings),
            retrieved_at_end=max(item.retrieved_at for item in page_recordings),
            recording_ids=tuple(item.recording_id for item in page_recordings),
        ),
    )
    source = SourceRecord(
        source_id=source_id,
        issuer="Federal Office for the Environment (FOEN)",
        operator="www.hydrodaten.admin.ch",
        acquisitions=acquisitions,
        evidence=tuple(
            EvidenceReference(
                evidence_id=item.recording_id,
                description="Retained direct FOEN station metadata source",
                recording=item,
            )
            for item in (*records, *page_recordings)
        ),
    )
    bindings = (
        FactBinding(
            fact_group="ch_foen-foen-station-directory-body",
            facts=("source.station.foen_directory_identity_and_names",),
            source_id=source_id,
            acquisition_id="ch_foen-foen-station-directory",
        ),
        FactBinding(
            fact_group="ch_foen-foen-questions-body",
            facts=("source.station.foen_altitude_unit_datum_definition", "source.provider.foen_station_metadata_reuse"),
            source_id=source_id,
            acquisition_id="ch_foen-foen-questions",
        ),
        FactBinding(
            fact_group="ch_foen-foen-station-bulk-body",
            facts=("source.provider.foen_station_metadata_terms",),
            source_id=source_id,
            acquisition_id="ch_foen-foen-station-bulk",
        ),
        FactBinding(
            fact_group="station_reference_pages",
            facts=("source.station.foen_reference_altitude_and_catchment",),
            source_id=source_id,
            acquisition_id="station_reference_pages",
        ),
    )
    return AcquisitionProvenance.model_validate(
        {
            **provenance.model_dump(mode="python"),
            "source_records": (*provenance.source_records, source),
            "fact_bindings": (*provenance.fact_bindings, *bindings),
            "fact_universe": (*provenance.fact_universe, *(fact for binding in bindings for fact in binding.facts)),
        }
    )


def station_metadata_supporting_inputs(provenance: AcquisitionProvenance) -> dict[str, tuple[str, ...]]:
    """Include unchanged per-page receipts beside their selected original bodies."""
    paths: dict[str, tuple[str, ...]] = dict(CATALOGUE_SUPPORTING_INPUTS)
    receipts = tuple(
        str(PurePosixPath(item.recording.repository_path).with_name("receipt.json"))
        for source in provenance.source_records
        if source.source_id == "ch_foen.foen_station_reference"
        for item in source.evidence
        if item.recording.repository_path.startswith(STATION_PAGE_ROOT + "/")
    )
    fact = "source.station.foen_reference_altitude_and_catchment"
    paths[fact] = (*paths[fact], *receipts)
    return paths


CATALOGUE_SUPPORTING_INPUTS = {
    "source.station.foen_directory_identity_and_names": (
        "maintenance/catalogue/station_metadata/sources/ch_foen/foen-station-directory/body",
        "maintenance/catalogue/station_metadata/sources/ch_foen/foen-station-directory/receipt.json",
    ),
    "source.station.foen_altitude_unit_datum_definition": (
        "maintenance/catalogue/station_metadata/sources/ch_foen/foen-questions/body",
        "maintenance/catalogue/station_metadata/sources/ch_foen/foen-questions/receipt.json",
    ),
    "source.provider.foen_station_metadata_reuse": (
        "maintenance/catalogue/station_metadata/sources/ch_foen/foen-questions/body",
        "maintenance/catalogue/station_metadata/sources/ch_foen/foen-questions/receipt.json",
    ),
    "source.provider.foen_station_metadata_terms": (
        "maintenance/catalogue/station_metadata/sources/ch_foen/foen-station-bulk/body",
        "maintenance/catalogue/station_metadata/sources/ch_foen/foen-station-bulk/receipt.json",
    ),
    "source.station.foen_reference_altitude_and_catchment": (
        "maintenance/catalogue/station_metadata/sources/ch_foen/station_pages/documents.json",
        "maintenance/catalogue/station_metadata/sources/ch_foen/station_pages/acquisition-run.json",
    ),
}


CATALOGUE_BUILD_DECLARATIONS = (
    ("maintenance/catalogue/ch_foen/official/selection.json", None),
    ("maintenance/catalogue/station_metadata/review.json", None),
    ("src/rivretrieve/_internal/providers/ch_foen/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/ch_foen/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/ch_foen/origins.py", "STATION_METADATA_NOTICE"),
    ("src/rivretrieve/_internal/providers/ch_foen/origins.py", "with_station_metadata_sources"),
    ("src/rivretrieve/_internal/providers/ch_foen/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/providers/ch_foen/official_series.py", "source_series"),
    ("src/rivretrieve/_internal/providers/ch_foen/generate_catalogue.py", "read_catalogue_sources"),
    ("src/rivretrieve/_internal/providers/ch_foen/station_metadata.py", "project_official_station_metadata"),
)
