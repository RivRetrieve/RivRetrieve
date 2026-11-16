"""Annotation schema for HydroPortail station-own instantaneous observation responses."""

from __future__ import annotations

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

HYDROPORTAIL_GLOSSAIRE_URL = "https://hydro.eaufrance.fr/glossaire"

S_FIELD = AnnotationField(
    name="s",
    dtype="Int64",
    description=(
        "HydroPortail observation processing status code "
        "(0 Sans validation, 4 Données brutes, 8 Données corrigées, "
        "12 Données pré-validées, 16 Données validées)."
    ),
    reference_url=HYDROPORTAIL_GLOSSAIRE_URL,
)

Q_FIELD = AnnotationField(
    name="q",
    dtype="Int64",
    description=(
        "HydroPortail observation qualification code "
        "(0 Valeur inconnue neutre, 4 Valeur inconnue faible, 8 Valeur inconnue forte, "
        "12 Valeur douteuse, 16 Valeur non qualifiée, 20 Valeur bonne)."
    ),
    reference_url=HYDROPORTAIL_GLOSSAIRE_URL,
)

M_FIELD = AnnotationField(
    name="m",
    dtype="Int64",
    description=(
        "HydroPortail observation acquisition method code "
        "(0 Mesuré, 4 Reconstitué, 8 Calculé, 10 Expertisé, "
        "12 Interpolation, 14 Estimé, 16 Valeur forcée)."
    ),
    reference_url=HYDROPORTAIL_GLOSSAIRE_URL,
)

C_FIELD = AnnotationField(
    name="c",
    dtype="Int64",
    description=(
        "HydroPortail observation continuity code "
        "(0 Continue, 1 Discontinue, 4 Discontinue faible, "
        "6 Discontinue neutre, 8 Discontinue forte)."
    ),
    reference_url=HYDROPORTAIL_GLOSSAIRE_URL,
)

FR_HYDROPORTAIL_SERIES_SCHEMA = AnnotationSchema(
    schema_id="fr_hydroportail.series",
    provider_id="fr_hydroportail",
    scope=AnnotationScope.OBSERVATION,
    fields=(S_FIELD, Q_FIELD, M_FIELD, C_FIELD),
)

__all__ = [
    "C_FIELD",
    "FR_HYDROPORTAIL_SERIES_SCHEMA",
    "HYDROPORTAIL_GLOSSAIRE_URL",
    "M_FIELD",
    "Q_FIELD",
    "S_FIELD",
]
