"""Official source-annotation schema definition for ``si_arso``."""

from __future__ import annotations

from rivretrieve._internal.source_annotations import AnnotationField, AnnotationSchema, AnnotationScope

ARSO_OPOMBA_HIDRO_URL = "https://www.arso.gov.si/vode/podatki/opombe/OpombaHidro.html"

SI_ARSO_SERIES_SCHEMA = AnnotationSchema(
    schema_id="si_arso.series",
    provider_id="si_arso",
    scope=AnnotationScope.SERIES,
    fields=(
        AnnotationField(
            name="data_status",
            dtype="String",
            description=(
                "ARSO source verification status published by each hydrological endpoint: "
                "'Verificirani podatki' for verified archive CSV exports from pov_arhiv_tab.php "
                "(3-level QA/QC per Program hidrološkega monitoringa površinskih voda od 2021 §4–5 "
                "and HIDMON_Porocilo_2023 §2.3), versus 'Začasni podatki' for provisional unverified "
                "operational telemetry tables under /vode/podatki/amp/. Not a RivRetrieve quality ranking."
            ),
            reference_url=ARSO_OPOMBA_HIDRO_URL,
        ),
    ),
)

__all__ = [
    "ARSO_OPOMBA_HIDRO_URL",
    "SI_ARSO_SERIES_SCHEMA",
]
