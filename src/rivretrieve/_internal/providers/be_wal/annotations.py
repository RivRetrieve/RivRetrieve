"""Official source-annotation schema for Belgium - Wallonia (`be_wal`) KiWIS quality codes."""

from __future__ import annotations

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

BE_WAL_QUALITY_CODES_URL = (
    "https://hydrometrie.wallonie.be/services/KiWIS/KiWIS"
    "?service=kisters&type=queryServices&datasource=0&request=getQualityCodes&format=json"
)

QUALITY_CODES: dict[int, tuple[str, str]] = {
    0: ("Excellent", "Quality control data (Excellent)"),
    40: ("Good", "Quality control data (Good)"),
    80: ("Fair", "Quality control data (Fair)"),
    120: ("Suspect", "Quality control data (Suspect)"),
    160: ("Poor", "Quality control data (Poor)"),
    161: ("S", "Manuel"),
    162: ("S", "Manuel"),
    163: ("S", "Manuel pris en compte pour les stat"),
    165: ("L", "Limnimétrie"),
    200: ("Unknown", "Quality control data (Unknown)"),
    205: ("Douteux (publié)", "Contrôle automatique douteux"),
    210: ("Douteux (non publié)", "Contrôle automatique douteux"),
    253: ("VF", "Valeurs fantomes"),
}

QUALITY_CODE_FIELD = AnnotationField(
    name="quality_code",
    dtype="Int64",
    description=(
        "SPW KiWIS getQualityCodes numeric quality key emitted per observation row: "
        "0 (Excellent), 40 (Good), 80 (Fair), 120 (Suspect), 160 (Poor), "
        "161/162 (S Manuel), 163 (S Manuel pris en compte pour les stat), 165 (L Limnimétrie), "
        "200 (Unknown, carried by operational/unreviewed peak and recent readings and retained verbatim), "
        "205 (Douteux (publié)), 210 (Douteux (non publié)), 253 (VF Valeurs fantomes), "
        "or -1 when emitted alongside Value=null on published Value=null missing-value rows. "
        "RivRetrieve preserves the publisher code without filtering or ranking."
    ),
    reference_url=BE_WAL_QUALITY_CODES_URL,
)

QUALITY_CODE_NAME_FIELD = AnnotationField(
    name="quality_code_name",
    dtype="String",
    description=(
        "Verbatim SPW KiWIS Quality Code Name paired with quality_code "
        "(Excellent, Good, Fair, Suspect, Poor, S, L, Unknown, Douteux (publié), "
        "Douteux (non publié), VF), or null when Quality Code is -1 on published Value=null missing-value rows."
    ),
    reference_url=BE_WAL_QUALITY_CODES_URL,
)

BE_WAL_QUALITY_SCHEMA = AnnotationSchema(
    schema_id="be_wal.quality",
    provider_id="be_wal",
    scope=AnnotationScope.OBSERVATION,
    fields=(QUALITY_CODE_FIELD, QUALITY_CODE_NAME_FIELD),
)

__all__ = [
    "BE_WAL_QUALITY_CODES_URL",
    "BE_WAL_QUALITY_SCHEMA",
    "QUALITY_CODES",
    "QUALITY_CODE_FIELD",
    "QUALITY_CODE_NAME_FIELD",
]
