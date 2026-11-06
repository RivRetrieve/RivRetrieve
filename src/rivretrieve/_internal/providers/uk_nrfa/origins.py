"""NRFA catalogue origins and reviewed station metadata fields."""

from datetime import datetime

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    AcquisitionRecord,
    EvidenceReference,
    ExternalFactReference,
    FactBinding,
    MaterialIdentity,
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

CRS_SUPPORT = "https://github.com/RivRetrieve/verification-evidence/blob/fd15877bab32fe6bdd20e60dce3cccaf6e0014a2/inventory/collections.json"

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("uk_nrfa")),
    "station_id": Field(NativeColumn("station_id")),
    "latitude": Field(NativeColumn("latitude")),
    "longitude": Field(NativeColumn("longitude")),
    "crs": Documented(DocumentedValue("EPSG:4326"), Evidence(CRS_SUPPORT)),
}

STATION_METADATA_FIELDS = (
    MetadataField("station_name", "name"),
    MetadataField("water_body_name", "river"),
    MetadataField("drainage_area", "catchment-area", "km²", support_facts=("source.station.metadata_definitions",)),
    MetadataField(
        "elevation",
        "station-level",
        "m",
        datum_field="station_altitude_datum",
        support_facts=("source.station.metadata_definitions", "source.station.altitude_location"),
        datum_support=(
            "source.station.metadata_definitions",
            "source.station.regional_numbering",
            "source.station.uk_numbering",
            "source.station.uk_inventory",
        ),
    ),
)

STATION_METADATA_NOTICE = (
    "Station metadata from the UK National River Flow Archive (UK Centre for Ecology & Hydrology). "
    "Station altitude generally describes the banks of the gauge, not stage zero. "
    "RivRetrieve preserves source values and names; the altitude datum association uses reviewed "
    "station numbering within the UK inventory."
)


_RECORDINGS = (
    (
        "api-help.html",
        "https://nrfaapps.ceh.ac.uk/nrfa/nrfa-api.html",
        "2026-11-06T15:47:50.531377+00:00",
        "b5f8bfa21ceeb69dda1d0d773f911eac3ce5a19d03bc323cdf54acadbfd2028e",
    ),
    (
        "station-number.html",
        "https://nrfa.ceh.ac.uk/data/about-data/gauging-station-information/station-number",
        "2026-11-06T15:47:51.410672+00:00",
        "648b1e736363ed4493e7eff0c5355e456264f2865e35fc008eb9457fec15cd6c",
    ),
    (
        "locational-information.html",
        "https://nrfa.ceh.ac.uk/data/about-data/gauging-station-information/locational-information",
        "2026-11-06T15:47:50.895783+00:00",
        "060f97568e437e60b079c0db16bd982150201420c8da317e29c467b8a39dffac",
    ),
    (
        "api-terms.html",
        "https://eidc.ceh.ac.uk/licences/nrfa-data-terms-and-conditions-for-api-access-to-time-series-data-and-metadata/",
        "2026-11-06T15:47:50.705142+00:00",
        "d1dd007ad2a9ec22daa4ad8bbc052c52d37ff281da5be6038e396c7989875532",
    ),
    (
        "hydrometric-areas.html",
        "https://nrfa.ceh.ac.uk/data/about-data/gauging-station-information/hydrometric-areas",
        "2026-11-06T15:47:51.693893+00:00",
        "1fe239104e06559cdc9ac68d930760cc0386762f7861165e650111490505e139",
    ),
    (
        "station-info.json",
        "https://nrfaapps.ceh.ac.uk/nrfa/ws/station-info?station=*&format=json-object&fields=id,name,river,lat-long,catchment-area,station-level,opened,closed,data-summary",
        "2026-11-06T15:47:52.144768+00:00",
        "21ed88685a7cffe917d553cd752d62a1b9484b31456ca4b9eebe7c25e0998137",
    ),
    (
        "station-ids.json",
        "https://nrfaapps.ceh.ac.uk/nrfa/ws/station-ids?format=json-object",
        "2026-11-06T15:47:52.036748+00:00",
        "3f8da8a47390468e422e2bdd1c07ccf2e29c86dd4ddec97f93f00d7a98c04639",
    ),
)
_INPUT_ROOT = "maintenance/catalogue/uk_nrfa/inputs/"
NATIVE_TABLE_REPOSITORY_PATH = "src/rivretrieve/_internal/providers/uk_nrfa/catalogue/native.parquet"
NATIVE_TABLE_REVISION = "10ba4ec8b4a31685b394c9e1e8eb66529616dd06"
NATIVE_TABLE_SHA256 = "a7b1ad5f9bfd61d83ba34670522e1e9bea387a485e8e8a4817034946232fa017"
NATIVE_TABLE_BYTE_SIZE = 200390


def build_acquisition_provenance() -> AcquisitionProvenance:
    recordings = tuple(
        RecordingReference(
            recording_id=filename,
            repository_path=_INPUT_ROOT + filename,
            source_url=url,
            retrieved_at=datetime.fromisoformat(instant),
            media_type="application/json" if filename.endswith(".json") else "text/html",
            sha256=digest,
        )
        for filename, url, instant, digest in _RECORDINGS
    )
    acquisitions = tuple(
        AcquisitionRecord(
            acquisition_id=recording.recording_id,
            method="http_request",
            instant_type="retrieval",
            description="Retained NRFA station inventory or supporting source documentation",
            requested_from=(recording.source_url,),
            retrieved_at_start=recording.retrieved_at,
            recording_ids=(recording.recording_id,),
        )
        for recording in recordings
    ) + (
        AcquisitionRecord(
            acquisition_id="crs-clarification",
            method="corroborating_receipt",
            instant_type="private_redacted_corroborating_receipt",
            description="Retained NRFA clarification of station-info horizontal coordinates; correspondence content withheld",
            requested_from=(CRS_SUPPORT,),
            material=MaterialIdentity(
                filename="crs-clarification.eml",
                byte_count=112974,
                sha256="11ef1113b0b6f18579ce949cc970f5e4be89670b7e9d4afb9a1b1f0f9138deb9",
            ),
        ),
    )
    source_facts = {
        "station-info.json": ("source.station.native_metadata", "source.station_product.advertised_associations"),
        "station-ids.json": ("source.station.uk_inventory",),
        "api-help.html": ("source.station.metadata_definitions", "source.product.quantity_units"),
        "locational-information.html": ("source.station.altitude_location",),
        "station-number.html": ("source.station.regional_numbering",),
        "hydrometric-areas.html": ("source.station.uk_numbering",),
        "api-terms.html": ("source.provider.terms", "source.provider.attribution"),
        "crs-clarification": ("source.station.documented_crs",),
    }
    bindings = tuple(
        FactBinding(fact_group=acquisition, facts=facts, source_id="uk_nrfa", acquisition_id=acquisition)
        for acquisition, facts in source_facts.items()
    )
    provenance = AcquisitionProvenance(
        schema_version=2,
        provider_id="uk_nrfa",
        native_table=NativeTableIdentity(
            location_kind="retained",
            repository_path=NATIVE_TABLE_REPOSITORY_PATH,
            revision=NATIVE_TABLE_REVISION,
            sha256=NATIVE_TABLE_SHA256,
            byte_size=NATIVE_TABLE_BYTE_SIZE,
        ),
        source_records=(
            SourceRecord(
                source_id="uk_nrfa",
                issuer="UK Centre for Ecology & Hydrology",
                operator="UK National River Flow Archive",
                acquisitions=acquisitions,
                evidence=tuple(
                    EvidenceReference(
                        evidence_id=recording.recording_id,
                        description="Retained NRFA source support",
                        recording=recording,
                    )
                    for recording in recordings
                ),
                statements=(
                    SourceStatement(
                        kind="citation",
                        exact_text="Data from the UK National River Flow Archive",
                        recording_id="api-terms.html",
                        fact="source.provider.attribution",
                    ),
                ),
            ),
        ),
        fact_bindings=bindings,
        fact_universe=tuple(fact for facts in source_facts.values() for fact in facts),
    )
    support = {
        "station": ("source.station.native_metadata", "source.station.uk_inventory", "source.station.documented_crs"),
        "product": ("source.product.quantity_units",),
        "station_product": ("source.station_product.advertised_associations",),
        "provider": ("source.provider.terms", "source.provider.attribution", "source.station.uk_inventory"),
    }
    for carrier, facts in support.items():
        provenance = complete_transformed_fact_universe(
            provenance,
            tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith(carrier + ".")),
            transformation=Transformation(
                name=f"NRFA source support to {carrier} catalogue; snapshot associations and unknown bounds",
                external_inputs=tuple(ExternalFactReference(source_id="uk_nrfa", fact=fact) for fact in facts),
            ),
            fact_group=f"canonical_{carrier}",
        )
    return provenance


NATIVE_TABLE_ACQUISITION_IDS = ("station-info.json", "station-ids.json")
CATALOGUE_SUPPORTING_INPUTS = {
    "source.station.documented_crs": (_INPUT_ROOT + "crs-clarification.eml",),
}
CATALOGUE_BUILD_DECLARATIONS = (
    ("maintenance/catalogue/station_metadata/review.json", None),
    ("src/rivretrieve/_internal/providers/uk_nrfa/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/uk_nrfa/origins.py", "NATIVE_TABLE_ACQUISITION_IDS"),
    ("src/rivretrieve/_internal/providers/uk_nrfa/origins.py", "CATALOGUE_SUPPORTING_INPUTS"),
    ("src/rivretrieve/_internal/providers/uk_nrfa/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/uk_nrfa/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/providers/uk_nrfa/generate_catalogue.py", "prepare_native_table"),
    ("src/rivretrieve/_internal/providers/uk_nrfa/catalogue_series.py", "describe_catalogue"),
)
