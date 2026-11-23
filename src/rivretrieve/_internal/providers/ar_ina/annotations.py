"""Annotation schema for INA Alerta5 publisher operational-availability codes."""

from __future__ import annotations

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

INA_A5_PORTAL_HOME_URL = "https://alerta.ina.gob.ar/a5/secciones/mapa/puntual"

DATA_AVAILABILITY_FIELD = AnnotationField(
    name="data_availability",
    dtype="String",
    description=(
        "INA Alerta5 publisher operational-availability code for this series, documented on the a5-portal-home "
        "map (H: historical, C: current operational, RT: real-time, NRT: near-real-time, S: simulated, and the "
        "H+S/C+S/RT+S/NRT+S combinations, N: no observations available). Not a RivRetrieve quality ranking."
    ),
    reference_url=INA_A5_PORTAL_HOME_URL,
)

AR_INA_SERIES_SCHEMA = AnnotationSchema(
    schema_id="ar_ina.series",
    provider_id="ar_ina",
    scope=AnnotationScope.SERIES,
    fields=(DATA_AVAILABILITY_FIELD,),
)

__all__ = [
    "AR_INA_SERIES_SCHEMA",
    "DATA_AVAILABILITY_FIELD",
    "INA_A5_PORTAL_HOME_URL",
]
