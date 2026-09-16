"""ANA catalogue authority : InventoryCapture → OriginDeclarations × AcquisitionProvenance (pure)."""

from datetime import datetime

from rivretrieve._internal.acquisition_provenance import (
    AbsenceMarkerValue,
    AcquisitionProvenance,
    AcquisitionRecord,
    EvidenceReference,
    ExternalFactReference,
    FactBinding,
    MaterialIdentity,
    RecordingReference,
    SourceRecord,
    SourceStatement,
    Transformation,
    WithheldFact,
)
from rivretrieve._internal.catalogue_origins import (
    Authored,
    AuthoredValue,
    Field,
    FloatConversion,
    NativeColumn,
    Withheld,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE
from rivretrieve._internal.providers.br_ana.capture import InventoryCapture

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("br_ana")),
    "station_id": Field(NativeColumn("codigoestacao")),
    "latitude": Field(NativeColumn("Latitude"), FloatConversion()),
    "longitude": Field(NativeColumn("Longitude"), FloatConversion()),
    "crs": Withheld(),
}
_SOURCE_FACT = "source.ana.open_data_license_statement"
_EXACT_TEXT = "Os dados abertos são disponibilizados livremente para a utilização de toda a sociedade, sem restrição de licenças, patentes ou mecanismos de controle."


def _terms_source() -> SourceRecord:
    recording = RecordingReference(
        recording_id="br_ana_terms_licence",
        repository_path="tests/test_data/br_ana_terms_licence.html",
        source_url="https://www.gov.br/ana/pt-br/acesso-a-informacao/dados-abertos",
        retrieved_at=datetime.fromisoformat("2026-08-21T09:30:30Z"),
        media_type="text/html;charset=utf-8",
        sha256="fdf143188469d23a9e2d4429c2a956d8fc311882a9a7e5d255f27e698ec3334f",
    )
    acquisition_id = "public_terms_capture_2026_08_21"
    source_id = "br_ana.terms"
    source = SourceRecord(
        source_id=source_id,
        issuer="Agência Nacional de Águas e Saneamento Básico (ANA)",
        acquisitions=(
            AcquisitionRecord(
                acquisition_id=acquisition_id,
                method="http_request",
                instant_type="retrieval",
                description="ANA institutional open-data terms HTML response",
                requested_from=(recording.source_url,),
                retrieved_at_start=recording.retrieved_at,
                recording_ids=(recording.recording_id,),
            ),
        ),
        evidence=(
            EvidenceReference(
                evidence_id="br_ana_public_terms",
                description="Public source terms recording from the completed source survey",
                recording=recording,
            ),
        ),
        statements=(
            SourceStatement(
                kind="license", exact_text=_EXACT_TEXT, recording_id=recording.recording_id, fact=_SOURCE_FACT
            ),
        ),
    )
    return source


def build_acquisition_provenance(capture: InventoryCapture) -> AcquisitionProvenance:
    """Bind canonical identity/geometry to every retained inventory acquisition."""
    terms = _terms_source()
    source_id = "br_ana.hidro_inventory"
    acquisitions = []
    evidence = []
    bindings = [
        FactBinding(
            fact_group="established_public_terms",
            facts=(_SOURCE_FACT,),
            source_id=terms.source_id,
            acquisition_id="public_terms_capture_2026_08_21",
        )
    ]
    source_facts = [_SOURCE_FACT]
    for response in capture.responses:
        source_fact = f"source.inventory.{response.recording_id}"
        source_facts.append(source_fact)
        parameter_name, parameter_value = next(iter(response.parameters.items()))
        query_name = "Unidade%20Federativa" if parameter_name == "Unidade Federativa" else "C%C3%B3digo%20da%20Bacia"
        requested_from = f"{response.requested_url}?{query_name}={parameter_value}"
        recording = RecordingReference(
            recording_id=response.recording_id,
            repository_path=response.repository_path,
            source_url=requested_from,
            retrieved_at=response.retrieved_at,
            media_type=response.media_type,
            sha256=response.payload_sha256,
        )
        acquisitions.append(
            AcquisitionRecord(
                acquisition_id=response.recording_id,
                method="http_request",
                instant_type="retrieval",
                description=(
                    f"Exact HidroInventarioEstacoes request parameters {response.parameters!r}; "
                    f"{response.row_count} accepted source rows and {response.distinct_station_count} distinct IDs. "
                    "The retained compressed RecordingEnvelope carries exact request parameters and response bytes."
                ),
                requested_from=(requested_from,),
                retrieved_at_start=response.retrieved_at,
                recording_ids=(response.recording_id,),
                material=MaterialIdentity(
                    filename=response.repository_path.rsplit("/", 1)[-1],
                    byte_count=response.recording_byte_size,
                    sha256=response.recording_sha256,
                ),
            )
        )
        evidence.append(
            EvidenceReference(
                evidence_id=response.recording_id,
                description="Exact credential-free inventory recording; excluded from distributions",
                recording=recording,
            )
        )
        bindings.append(
            FactBinding(
                fact_group=response.recording_id,
                facts=(source_fact,),
                source_id=source_id,
                acquisition_id=response.recording_id,
            )
        )
    inventory = SourceRecord(
        source_id=source_id,
        issuer="Agência Nacional de Águas e Saneamento Básico (ANA)",
        operator="www.ana.gov.br",
        acquisitions=tuple(acquisitions),
        evidence=tuple(evidence),
    )
    attempt_identities = tuple(
        item for item in capture.supporting_evidence if item.repository_path in capture.attempt_record_paths
    )
    if acquisitions:
        first = acquisitions[0]
        acquisitions[0] = first.model_copy(
            update={
                "description": first.description
                + " Original failed attempts and successful retries are retained separately, not interpreted as empty inventories. "
                + "; ".join(
                    f"{item.repository_path}: SHA256 {item.sha256}, {item.byte_size} bytes"
                    for item in attempt_identities
                )
            }
        )
    inventory = inventory.model_copy(update={"acquisitions": tuple(acquisitions)})
    external_inputs = tuple(ExternalFactReference(source_id=source_id, fact=fact) for fact in source_facts[1:])
    authored = tuple(
        f
        for f in CATALOGUE_FACT_UNIVERSE
        if f.startswith("provider.") and f not in {"provider.name", "provider.license", "provider.citation"}
    )
    stations = tuple(f for f in CATALOGUE_FACT_UNIVERSE if f.startswith("station.") and f != "station.crs")
    bindings.extend(
        (
            FactBinding(
                fact_group="rivretrieve_provider_registration",
                facts=authored,
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="RivRetrieve provider identity, capabilities and attested catalogue date",
                    kind="authored_constant",
                    external_inputs=(),
                ),
            ),
            FactBinding(
                fact_group="ana_provider_name",
                facts=("provider.name",),
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(name="ANA issuing agency identity", external_inputs=external_inputs),
            ),
            FactBinding(
                fact_group="ana_provider_license",
                facts=("provider.license",),
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="ANA institutional open-data terms verbatim",
                    external_inputs=(ExternalFactReference(source_id=terms.source_id, fact=_SOURCE_FACT),),
                ),
            ),
            FactBinding(
                fact_group="fluviometric_station_identity_geometry",
                facts=stations,
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name=(
                        f"Exact native union ({capture.distinct_station_count} distinct stations); "
                        f"select Tipo_Estacao == Fluviometrica ({capture.fluviometric_station_count}); "
                        f"retain Pluviometrica ({capture.pluviometric_station_count}) in native input, not acquisition-withheld. "
                        "Equal overlapping source rows retain all containing acquisition references; conflicts fail. "
                        + capture.population_scope
                    ),
                    external_inputs=external_inputs,
                ),
            ),
            FactBinding(
                fact_group="coordinate_reference_frame_not_established",
                facts=("station.crs",),
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="CRS acquisition not established; unknown carrier, not source silence",
                    kind="absence_marker",
                    marker_value=AbsenceMarkerValue.UNKNOWN,
                    external_inputs=(ExternalFactReference(source_id=source_id, fact="source.ana.horizontal_crs"),),
                ),
            ),
        )
    )
    withheld = (
        WithheldFact(
            fact_group="horizontal_crs_not_established",
            facts=("source.ana.horizontal_crs",),
            reason="no_acquisition_record_established",
            source_id=source_id,
        ),
        WithheldFact(
            fact_group="citation_request_not_established",
            facts=("provider.citation",),
            reason="no_acquisition_record_established",
        ),
        WithheldFact(
            fact_group="products_pending_source_semantics_and_observation_stage_certification",
            facts=tuple(f for f in CATALOGUE_FACT_UNIVERSE if f.startswith("product.")),
            reason="no_acquisition_record_established",
        ),
        WithheldFact(
            fact_group="station_product_relationships_not_established_by_inventory_presence",
            facts=tuple(f for f in CATALOGUE_FACT_UNIVERSE if f.startswith("station_product.")),
            reason="no_acquisition_record_established",
        ),
    )
    return AcquisitionProvenance(
        schema_version=2,
        provider_id="br_ana",
        native_table=capture.native_table,
        fact_universe=(*CATALOGUE_FACT_UNIVERSE, *source_facts, "source.ana.horizontal_crs"),
        source_records=(terms, inventory),
        fact_bindings=tuple(bindings),
        withheld_facts=withheld,
    )
