"""NVE catalogue authority : ∅ → OriginDeclarations × AcquisitionProvenance (pure)."""

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
    SemanticDigest,
    SourceRecord,
    SourceStatement,
    Transformation,
)
from rivretrieve._internal.catalogue_origins import (
    Authored,
    AuthoredValue,
    Evidence,
    Field,
    FieldTransform,
    NativeColumn,
    NotPublished,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("no_nve")),
    "station_id": Field(NativeColumn("stationId")),
    "latitude": Field(NativeColumn("latitude"), FieldTransform.FLOAT),
    "longitude": Field(NativeColumn("longitude"), FieldTransform.FLOAT),
    "crs": NotPublished(Evidence("https://hydapi.nve.no/swagger/v1/swagger.json")),
}
NATIVE_TABLE_REPOSITORY_PATH = "src/rivretrieve/_internal/providers/no_nve/catalogue/native.parquet"
NATIVE_TABLE_REVISION = "0ce05667a7cddc3aca877dc5b687f0c97986cca1"
NATIVE_TABLE_SHA256 = "26b9f113fb85a81b89690db8c3bd5b1bf2c4eebc1472d21eae193a6f5c7409bc"
NATIVE_TABLE_BYTE_SIZE = 809226
NATIVE_TABLE_SEMANTIC_SHA256 = "31cecf6af263800ca8b355f5047860a48ad20371fd2491e8b7c73ae430e8a4c9"

_LICENSE_FACT = "source.nve.license_statement"
_CITATION_FACT = "source.nve.citation_statement"
_LICENSE = "The data provided by the API is licensed under the Norwegian License for Open Government Data (NLOD) which is compatible with CC Navngivelse 3.0 Norge (CC BY 3.0)."
_CITATION = "When using data from this service, if possible, please refer to this service as origin of data."
_ACTIVE_1_FACT = "source.station_catalogue.active_1.complete_response"
_ACTIVE_0_FACT = "source.station_catalogue.active_0.complete_response"
_PRODUCT_FACT = "source.station_catalogue.series_parameter_resolution_unit"
_CRS_FACT = "source.station_catalogue.coordinate_reference_system_not_published"


def _capture_reference(active: int, retrieved_at: str, sha256: str) -> RecordingReference:
    return RecordingReference(
        recording_id=f"no_nve_stations_active_{active}",
        repository_path=f"tests/test_data/no_nve_stations_active_{active}.json",
        source_url=f"https://hydapi.nve.no/api/v1/Stations?Active={active}",
        retrieved_at=datetime.fromisoformat(retrieved_at),
        media_type="application/json; charset=utf-8",
        sha256=sha256,
    )


def build_acquisition_provenance() -> AcquisitionProvenance:
    """Build closed catalogue lineage from the two station captures and public terms."""
    terms = RecordingReference(
        recording_id="no_nve_terms_licence",
        repository_path="tests/test_data/no_nve_terms_licence.html",
        source_url="https://hydapi.nve.no/UserDocumentation/",
        retrieved_at=datetime.fromisoformat("2026-08-21T09:19:38Z"),
        media_type="text/html; charset=utf-8",
        sha256="d66c35806f7f62ac5fb95fa4219f80a8c2690c7e8ae4bdc022c770a684fa9f8a",
    )
    active_1 = _capture_reference(
        1,
        "2026-09-04T18:59:57.133119Z",
        "048a947ca05c9850cabdd76e90d8e010a3384ad03b08af19e7080915aae9c7c9",
    )
    active_0 = _capture_reference(
        0,
        "2026-09-04T18:59:58.038985Z",
        "87ffaf3a633a0f4b40bc43bed0d047a66c061f7816b314e7a89db1b5ca370233",
    )
    swagger = RecordingReference(
        recording_id="no_nve_swagger_2026_09_04",
        repository_path="tests/test_data/no_nve_swagger.json",
        source_url="https://hydapi.nve.no/swagger/v1/swagger.json",
        retrieved_at=datetime.fromisoformat("2026-09-04T17:48:13Z"),
        media_type="application/json; charset=utf-8",
        sha256="6f30fa885e55ca4600e974de702ac818a14e6b236f11c968ecb511da3b9a0516",
    )
    source_id = "no_nve.nve_hydapi"
    source = SourceRecord(
        source_id=source_id,
        issuer="Norwegian Water Resources and Energy Directorate (NVE)",
        operator="hydapi.nve.no",
        acquisitions=(
            AcquisitionRecord(
                acquisition_id="terms_capture_2026_08_21",
                method="http_request",
                instant_type="retrieval",
                description="NVE HydAPI public user-documentation terms response",
                requested_from=(terms.source_url,),
                retrieved_at_start=terms.retrieved_at,
                recording_ids=(terms.recording_id,),
            ),
            AcquisitionRecord(
                acquisition_id="station_schema_capture_2026_09_04",
                method="http_request",
                instant_type="retrieval",
                description="NVE OpenAPI station schema reviewed for the absence of a latitude/longitude CRS declaration",
                requested_from=(swagger.source_url,),
                retrieved_at_start=swagger.retrieved_at,
                recording_ids=(swagger.recording_id,),
                material=MaterialIdentity(
                    filename="no_nve_swagger.json",
                    byte_count=78_385,
                    sha256=swagger.sha256,
                ),
            ),
            AcquisitionRecord(
                acquisition_id="stations_active_1_capture_2026_09_04",
                method="http_request",
                instant_type="retrieval",
                description="Complete credentialed NVE Stations Active=1 response: 4,902 response and accepted rows, 4,902 distinct stations",
                requested_from=(active_1.source_url,),
                retrieved_at_start=active_1.retrieved_at,
                recording_ids=(active_1.recording_id,),
                material=MaterialIdentity(
                    filename="no_nve_stations_active_1.json",
                    byte_count=13_865_773,
                    sha256=active_1.sha256,
                ),
            ),
            AcquisitionRecord(
                acquisition_id="stations_active_0_capture_2026_09_04",
                method="http_request",
                instant_type="retrieval",
                description="Complete credentialed NVE Stations Active=0 response: 1,893 response and accepted rows, 1,893 distinct stations; all overlap identically with Active=1",
                requested_from=(active_0.source_url,),
                retrieved_at_start=active_0.retrieved_at,
                recording_ids=(active_0.recording_id,),
                material=MaterialIdentity(
                    filename="no_nve_stations_active_0.json",
                    byte_count=6_114_369,
                    sha256=active_0.sha256,
                ),
            ),
        ),
        evidence=(
            EvidenceReference(evidence_id="no_nve_public_terms", description="NVE public terms", recording=terms),
            EvidenceReference(
                evidence_id="no_nve_station_schema",
                description="Complete public NVE OpenAPI schema used to review coordinate fields and their absent CRS declaration",
                recording=swagger,
            ),
            EvidenceReference(
                evidence_id="no_nve_stations_active_1_response",
                description="Complete Active=1 station response retained outside the wheel",
                recording=active_1,
            ),
            EvidenceReference(
                evidence_id="no_nve_stations_active_0_response",
                description="Complete Active=0 station response retained outside the wheel",
                recording=active_0,
            ),
        ),
        statements=(
            SourceStatement(kind="license", exact_text=_LICENSE, recording_id=terms.recording_id, fact=_LICENSE_FACT),
            SourceStatement(
                kind="citation", exact_text=_CITATION, recording_id=terms.recording_id, fact=_CITATION_FACT
            ),
        ),
    )
    authored_provider = (
        "provider.provider_id",
        "provider.live_stations",
        "provider.live_products",
        "provider.live_station_products",
        "provider.bulk_observations",
        "provider.catalogue_version",
    )
    derived_provider = ("provider.name", "provider.license", "provider.citation")
    products = tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("product."))
    stations = tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("station."))
    station_products = tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("station_product."))
    source_facts = (_LICENSE_FACT, _CITATION_FACT, _ACTIVE_1_FACT, _ACTIVE_0_FACT, _PRODUCT_FACT, _CRS_FACT)
    bindings = (
        FactBinding(
            fact_group="public_terms",
            facts=(_LICENSE_FACT, _CITATION_FACT),
            source_id=source_id,
            acquisition_id="terms_capture_2026_08_21",
        ),
        FactBinding(
            fact_group="coordinate_schema_review",
            facts=(_CRS_FACT,),
            source_id=source_id,
            acquisition_id="station_schema_capture_2026_09_04",
        ),
        FactBinding(
            fact_group="active_1_station_response",
            facts=(_ACTIVE_1_FACT, _PRODUCT_FACT),
            source_id=source_id,
            acquisition_id="stations_active_1_capture_2026_09_04",
        ),
        FactBinding(
            fact_group="active_0_station_response",
            facts=(_ACTIVE_0_FACT,),
            source_id=source_id,
            acquisition_id="stations_active_0_capture_2026_09_04",
        ),
        FactBinding(
            fact_group="rivretrieve_provider_constants",
            facts=authored_provider,
            source_id=None,
            acquisition_id=None,
            transformation=Transformation(
                name="RivRetrieve provider identifiers and capabilities", kind="authored_constant", external_inputs=()
            ),
        ),
        FactBinding(
            fact_group="canonical_provider_source_facts",
            facts=derived_provider,
            source_id=None,
            acquisition_id=None,
            transformation=Transformation(
                name="NVE identity and exact public terms to canonical provider facts",
                external_inputs=(
                    ExternalFactReference(source_id=source_id, fact=_LICENSE_FACT),
                    ExternalFactReference(source_id=source_id, fact=_CITATION_FACT),
                    ExternalFactReference(source_id=source_id, fact=_ACTIVE_1_FACT),
                ),
            ),
        ),
        FactBinding(
            fact_group="canonical_products",
            facts=products,
            source_id=None,
            acquisition_id=None,
            transformation=Transformation(
                name="NVE parameter-resolution-unit vocabulary to canonical products",
                external_inputs=(ExternalFactReference(source_id=source_id, fact=_PRODUCT_FACT),),
            ),
        ),
        FactBinding(
            fact_group="canonical_stations",
            facts=stations,
            source_id=None,
            acquisition_id=None,
            transformation=Transformation(
                name="Complete NVE station response union to canonical identity and geometry",
                external_inputs=(
                    ExternalFactReference(source_id=source_id, fact=_ACTIVE_1_FACT),
                    ExternalFactReference(source_id=source_id, fact=_ACTIVE_0_FACT),
                    ExternalFactReference(source_id=source_id, fact=_CRS_FACT),
                ),
            ),
        ),
        FactBinding(
            fact_group="canonical_station_products",
            facts=station_products,
            source_id=None,
            acquisition_id=None,
            transformation=Transformation(
                name="Complete NVE seriesList parameter-resolution pairs to canonical station-product availability",
                external_inputs=(
                    ExternalFactReference(source_id=source_id, fact=_ACTIVE_1_FACT),
                    ExternalFactReference(source_id=source_id, fact=_ACTIVE_0_FACT),
                    ExternalFactReference(source_id=source_id, fact=_PRODUCT_FACT),
                ),
            ),
        ),
    )
    return AcquisitionProvenance(
        schema_version=2,
        provider_id="no_nve",
        native_table=NativeTableIdentity(
            repository_path=NATIVE_TABLE_REPOSITORY_PATH,
            revision=NATIVE_TABLE_REVISION,
            sha256=NATIVE_TABLE_SHA256,
            byte_size=NATIVE_TABLE_BYTE_SIZE,
            semantic_digest=SemanticDigest(
                name="no_nve.native_semantic_frame_sha256", sha256=NATIVE_TABLE_SEMANTIC_SHA256
            ),
        ),
        fact_universe=(*source_facts, *CATALOGUE_FACT_UNIVERSE),
        source_records=(source,),
        fact_bindings=bindings,
    )
