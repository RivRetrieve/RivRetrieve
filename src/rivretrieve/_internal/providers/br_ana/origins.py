"""ANA catalogue authority : InventoryCapture × OptionalObservationEvidence → OriginDeclarations × AcquisitionProvenance (pure)."""

from datetime import datetime

import polars as pl

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
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.br_ana.capture import (
    AdoptedTelemetryEvidence,
    ConventionalDailyEvidence,
    InventoryCapture,
)
from rivretrieve._internal.providers.br_ana.config import BrAnaDailySourceCoordinates, BrAnaSourceCoordinates, config

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


def with_observation_products(
    inventory: AcquisitionProvenance,
    capture: InventoryCapture,
    candidates: pl.DataFrame,
    telemetry: AdoptedTelemetryEvidence,
    daily: ConventionalDailyEvidence | None = None,
) -> AcquisitionProvenance:
    """Inventory authority × candidate source keys × source observations → product/relationship authority."""
    source_id = "br_ana.adopted_telemetry"
    documentation_fact = "source.ana.adopted_field_units_measurement_time"
    unknown_fact = "source.ana.adopted_endpoint_availability_unacquired"
    record_fact = "source.ana.adopted_published_record_unacquired"
    reference = telemetry.observations
    source = SourceRecord(
        source_id=source_id,
        issuer="Agência Nacional de Águas e Saneamento Básico (ANA)",
        operator="www.ana.gov.br",
        acquisitions=(
            telemetry.documentation,
            AcquisitionRecord(
                acquisition_id=reference.recording_id,
                method="http_request",
                instant_type="retrieval",
                description=(
                    "Exact adopted telemetry measurement-time request in retained RecordingEnvelope. "
                    "Only nonnull recorded adopted fields establish bounded per-product availability; "
                    "no continuity, current availability or published record bounds are inferred."
                ),
                requested_from=(reference.source_url,),
                retrieved_at_start=reference.retrieved_at,
                recording_ids=(reference.recording_id,),
            ),
        ),
        evidence=(
            EvidenceReference(
                evidence_id=reference.recording_id,
                description="Exact credential-free adopted telemetry observation RecordingEnvelope",
                recording=reference,
            ),
        ),
    )
    facts = [*inventory.fact_universe, documentation_fact, unknown_fact, record_fact]
    bindings = list(inventory.fact_bindings)
    bindings.append(
        FactBinding(
            fact_group="adopted_telemetry_documented_fields",
            facts=(documentation_fact,),
            source_id=source_id,
            acquisition_id=telemetry.documentation.acquisition_id,
        )
    )
    doc_ref = ExternalFactReference(source_id=source_id, fact=documentation_fact)
    observed_facts = {}
    for station, product in sorted(telemetry.available_pairs):
        fact = f"source.adopted_observations.{station}.{product}.nonnull"
        observed_facts[station, product] = fact
        facts.append(fact)
        bindings.append(
            FactBinding(
                fact_group=f"observed_adopted_{station}_{product}",
                facts=(fact,),
                source_id=source_id,
                acquisition_id=reference.recording_id,
            )
        )
    sources = [*inventory.source_records, source]
    daily_source_id = "br_ana.conventional_daily"
    daily_doc_fact = "source.ana.conventional_daily_definitions"
    daily_unknown = "source.ana.daily_variant_availability_unacquired"
    daily_record = "source.ana.daily_published_record_unacquired"
    daily_refs = {}
    correspondence_inputs = []
    if daily is not None:
        facts.extend((daily_doc_fact, daily_unknown, daily_record))
        bindings.append(
            FactBinding(
                fact_group="conventional_daily_definitions",
                facts=(daily_doc_fact,),
                source_id=daily_source_id,
                acquisition_id=daily.documentation.acquisition_id,
            )
        )
        daily_acquisitions = [daily.documentation]
        daily_evidence = []
        for ref in daily.correspondence:
            comparison_fact = f"source.ana.daily_correspondence.{ref.recording_id}"
            facts.append(comparison_fact)
            correspondence_inputs.append(ExternalFactReference(source_id=daily_source_id, fact=comparison_fact))
            bindings.append(
                FactBinding(
                    fact_group=ref.recording_id,
                    facts=(comparison_fact,),
                    source_id=daily_source_id,
                    acquisition_id=ref.recording_id,
                )
            )
            daily_acquisitions.append(
                AcquisitionRecord(
                    acquisition_id=ref.recording_id,
                    method="http_request",
                    instant_type="retrieval",
                    description="Supporting original modern/SOAP response for reviewed field correspondence; not authority to substitute SOAP values or infer availability of another variant.",
                    requested_from=(ref.source_url,),
                    retrieved_at_start=ref.retrieved_at,
                    recording_ids=(ref.recording_id,),
                )
            )
            daily_evidence.append(
                EvidenceReference(
                    evidence_id=ref.recording_id,
                    description="Original response behind retained derived field comparison",
                    recording=ref,
                )
            )
        for ref, pairs in daily.observations:
            daily_acquisitions.append(
                AcquisitionRecord(
                    acquisition_id=ref.recording_id,
                    method="http_request",
                    instant_type="retrieval",
                    description="Exact modern month request retained in RecordingEnvelope; Mediadiaria=1 and endpoint-specific consistency (stage nivelconsistencia, discharge Nivel_Consistencia) identify separate Bruto=1 and Consistido=2 variants. Nonnull numbered slots establish only this exact variant, not other variants or period bounds.",
                    requested_from=(ref.source_url,),
                    retrieved_at_start=ref.retrieved_at,
                    recording_ids=(ref.recording_id,),
                )
            )
            daily_evidence.append(
                EvidenceReference(
                    evidence_id=ref.recording_id,
                    description="Credential-free original modern monthly response, not SOAP substituted values",
                    recording=ref,
                )
            )
            for station, product in sorted(pairs):
                fact = f"source.daily_observations.{ref.recording_id}.{station}.{product}.nonnull"
                facts.append(fact)
                bindings.append(
                    FactBinding(
                        fact_group=f"daily_{ref.recording_id}_{product}",
                        facts=(fact,),
                        source_id=daily_source_id,
                        acquisition_id=ref.recording_id,
                    )
                )
                daily_refs.setdefault((station, product), []).append(
                    ExternalFactReference(source_id=daily_source_id, fact=fact)
                )
        sources.append(
            SourceRecord(
                source_id=daily_source_id,
                issuer=source.issuer,
                operator="www.ana.gov.br",
                acquisitions=tuple(daily_acquisitions),
                evidence=tuple(daily_evidence),
            )
        )
    candidate_ids = set(candidates["codigoestacao"].to_list())
    if daily is not None and any(station not in candidate_ids for station, _ in daily.available_pairs):
        raise FatalContractError("ANA daily evidence names a station outside the certified catalogue")
    if any(station not in candidate_ids for station, _ in telemetry.available_pairs):
        raise FatalContractError("ANA adopted observation evidence names a station outside the certified catalogue")
    for station, uf, basin in candidates.select("codigoestacao", "UF_Estacao", "codigobacia").iter_rows():
        source_inputs = tuple(
            ExternalFactReference(source_id="br_ana.hidro_inventory", fact=f"source.inventory.{response.recording_id}")
            for response in capture.responses
            if response.parameters == {"Unidade Federativa": uf}
            or response.parameters == {"Código da Bacia": int(basin)}
        )
        if not source_inputs:
            raise FatalContractError("ANA candidate lacks a containing inventory acquisition")
        for product, definition in config().products.items():
            is_telemetry = isinstance(definition.coordinates.value, BrAnaSourceCoordinates)
            if not is_telemetry and daily is None:
                continue
            fact = f"station_product:{station}:{product}.availability"
            facts.append(fact)
            observed_fact = observed_facts.get((station, product))
            inputs = (
                *source_inputs,
                doc_ref,
                ExternalFactReference(source_id=source_id, fact=observed_fact or unknown_fact),
            )
            coordinates = definition.coordinates.value
            predicate = ""
            if not is_telemetry:
                assert isinstance(coordinates, BrAnaDailySourceCoordinates)
                consistency_field = (
                    "nivelconsistencia" if coordinates.endpoint == "HidroSerieCotas" else "Nivel_Consistencia"
                )
                predicate = f"{coordinates.endpoint}/v1: Mediadiaria=1 AND {consistency_field}={coordinates.consistency}; {coordinates.field_prefix}_01..31"
                observed_fact = daily_refs.get((station, product))
                inputs = (
                    *source_inputs,
                    ExternalFactReference(source_id=daily_source_id, fact=daily_doc_fact),
                    *(observed_fact or (ExternalFactReference(source_id=daily_source_id, fact=daily_unknown),)),
                )
            transform = Transformation(
                name=(
                    (
                        f"{predicate}: nonnull numbered day slot; no ranking, averaging or fallback"
                        if not is_telemetry and observed_fact
                        else f"Certified Fluviometrica candidate; {predicate}: availability unacquired, not source silence"
                    )
                    if not is_telemetry
                    else (
                        "Nonnull adopted field in exact observed request establishes available, not continuous/complete record"
                        if observed_fact
                        else "Certified Fluviometrica candidate with no established per-station adopted endpoint evidence; not source silence"
                    )
                ),
                external_inputs=inputs,
                kind="derived_value" if observed_fact else "absence_marker",
                marker_value=None if observed_fact else AbsenceMarkerValue.UNKNOWN,
            )
            bindings.append(
                FactBinding(
                    fact_group=f"observation_candidate_{station}_{product}",
                    facts=(fact,),
                    source_id=None,
                    acquisition_id=None,
                    transformation=transform,
                )
            )
    for group, output, inputs, transform_name in (
        (
            "documented_observation_products",
            tuple(f for f in CATALOGUE_FACT_UNIVERSE if f.startswith("product.")),
            (doc_ref,)
            if daily is None
            else (
                doc_ref,
                ExternalFactReference(source_id=daily_source_id, fact=daily_doc_fact),
                *correspondence_inputs,
            ),
            "Documented adopted fields with measurement-time labels but unestablished cadence, statistic and temporal support; when supplied, Hidro daily means Mediadiaria=1 with Bruto=1 and Consistido=2 as separate products, ordinal daily labels, unknown day definition and zone",
        ),
        (
            "observation_candidate_relations",
            tuple(
                f for f in CATALOGUE_FACT_UNIVERSE if f.startswith("station_product.") and "published_record" not in f
            ),
            (doc_ref, ExternalFactReference(source_id=None, fact="station.station_id"))
            + (() if daily is None else (ExternalFactReference(source_id=daily_source_id, fact=daily_doc_fact),)),
            "Certified Fluviometrica candidates crossed with documented products; exact availability authority is in each row-scoped fact; native flags and operating periods are not interpreted",
        ),
    ):
        bindings.append(
            FactBinding(
                fact_group=group,
                facts=output,
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(name=transform_name, external_inputs=inputs),
            )
        )
    bindings.append(
        FactBinding(
            fact_group="observation_record_bounds_unestablished",
            facts=tuple(
                f for f in CATALOGUE_FACT_UNIVERSE if f.startswith("station_product.") and "published_record" in f
            ),
            source_id=None,
            acquisition_id=None,
            transformation=Transformation(
                name="No published product record acquired; operating periods and probed windows are not published product records",
                kind="absence_marker",
                marker_value=AbsenceMarkerValue.NULL,
                external_inputs=(ExternalFactReference(source_id=source_id, fact=record_fact),)
                + (() if daily is None else (ExternalFactReference(source_id=daily_source_id, fact=daily_record),)),
            ),
        )
    )
    withheld = tuple(
        w for w in inventory.withheld_facts if not any(f.startswith(("product.", "station_product.")) for f in w.facts)
    )
    withheld += (
        WithheldFact(
            fact_group="adopted_endpoint_availability_not_acquired",
            facts=(unknown_fact,),
            reason="no_acquisition_record_established",
            source_id=source_id,
        ),
        WithheldFact(
            fact_group="adopted_published_record_not_acquired",
            facts=(record_fact,),
            reason="no_acquisition_record_established",
            source_id=source_id,
        ),
    )
    if daily is not None:
        withheld += tuple(
            WithheldFact(
                fact_group=name, facts=(fact,), reason="no_acquisition_record_established", source_id=daily_source_id
            )
            for name, fact in (
                ("daily_variant_availability_not_acquired", daily_unknown),
                ("daily_published_record_not_acquired", daily_record),
            )
        )
    return AcquisitionProvenance(
        schema_version=2,
        provider_id=inventory.provider_id,
        native_table=inventory.native_table,
        fact_universe=tuple(facts),
        source_records=tuple(sources),
        fact_bindings=tuple(bindings),
        withheld_facts=withheld,
    )
