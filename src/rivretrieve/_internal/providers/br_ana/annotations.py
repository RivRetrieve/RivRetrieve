"""Official source-annotation schema definitions for ``br_ana``."""

from __future__ import annotations

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

BR_ANA_SWAGGER_URL = "https://www.ana.gov.br/hidrowebservice/swagger-ui/index.html"
BR_ANA_MANUAL_URL = (
    "https://www.gov.br/ana/pt-br/assuntos/monitoramento-e-eventos-criticos/"
    "monitoramento-hidrologico/orientacoes-manuais/manuais/manual-hidrowebservice_publica.pdf"
)

BR_ANA_DAILY_COTAS_SCHEMA = AnnotationSchema(
    schema_id="br_ana.daily_cotas",
    provider_id="br_ana",
    scope=AnnotationScope.OBSERVATION,
    fields=(
        AnnotationField(
            name="Cota_Status",
            dtype="String",
            description="ANA verbatim HidroSerieCotas day-slot status code.",
            reference_url=BR_ANA_SWAGGER_URL,
        ),
        AnnotationField(
            name="Tipo_Medicao_Cotas",
            dtype="String",
            description="ANA HidroSerieCotas monthly header measurement type code propagated to each day of the month.",
            reference_url=BR_ANA_SWAGGER_URL,
        ),
    ),
)

BR_ANA_DAILY_VAZAO_SCHEMA = AnnotationSchema(
    schema_id="br_ana.daily_vazao",
    provider_id="br_ana",
    scope=AnnotationScope.OBSERVATION,
    fields=(
        AnnotationField(
            name="Vazao_Status",
            dtype="String",
            description="ANA verbatim HidroSerieVazao day-slot status code.",
            reference_url=BR_ANA_SWAGGER_URL,
        ),
        AnnotationField(
            name="Metodo_Obtencao_Vazoes",
            dtype="String",
            description="ANA HidroSerieVazao monthly header acquisition method code propagated to each day of the month.",
            reference_url=BR_ANA_SWAGGER_URL,
        ),
    ),
)

BR_ANA_TELEMETRY_COTA_SCHEMA = AnnotationSchema(
    schema_id="br_ana.telemetry_cota",
    provider_id="br_ana",
    scope=AnnotationScope.OBSERVATION,
    fields=(
        AnnotationField(
            name="Cota_Adotada_Status",
            dtype="String",
            description="ANA verbatim adopted stage telemetry status code.",
            reference_url=BR_ANA_MANUAL_URL,
        ),
    ),
)

BR_ANA_TELEMETRY_VAZAO_SCHEMA = AnnotationSchema(
    schema_id="br_ana.telemetry_vazao",
    provider_id="br_ana",
    scope=AnnotationScope.OBSERVATION,
    fields=(
        AnnotationField(
            name="Vazao_Adotada_Status",
            dtype="String",
            description="ANA verbatim adopted discharge telemetry status code.",
            reference_url=BR_ANA_MANUAL_URL,
        ),
    ),
)
