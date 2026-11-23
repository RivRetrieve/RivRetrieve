"""Official Colombia IDEAM S3 series identities, physical facts, and CSV contract.

Kept free of network, filesystem, and runtime configuration I/O so offline
catalogue generation and observation parsing share one source-backed contract.
"""

from __future__ import annotations

import csv
import io
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceFact,
    EvidenceState,
    PhysicalFacts,
    SourceIdentity,
    SourceSeries,
    admission,
    stable_id,
)

if TYPE_CHECKING:
    from rivretrieve._internal.catalogues.source_series import SourceDescription

NAMESPACE = "ideam.s3.historicos"
CSV_HEADER: tuple[str, str, str] = ("fechaObservacion", "valorObservado", "nivelAprobacion")
EXPECTED_LICENSE_ID = "CC_40_BY_SA"
EXPECTED_LICENSE_TEXT = "Creative Commons Attribution | Share Alike 4.0 International"

UNITS: dict[str, str] = {
    "m3/s": "m3/s",
    "cm": "cm",
}

# Publisher approval-stage labels published per row in S3 CSVs (nivelAprobacion).
# Documented here for provenance and potential future source-quality exposure;
# RivRetrieve preserves all observation rows without filtering or ranking by
# nivelAprobacion. AQUARIUS WebPortal's separate Grade attribute remains
# unpopulated ("50 - INDEFINIDO") across IDEAM hydrological exports.
APPROVAL_VOCABULARY: dict[str, str] = {
    "Preliminar": "AQUARIUS approval 900 - Preliminar (operational or migrated unvalidated observation)",
    "En revisión": "AQUARIUS approval 1100 - En revisión (observation under hydrological validation review)",
    "Definitivo": "AQUARIUS approval 1200 - Definitivo (hydrologically validated observation)",
    "": "Unlabeled legacy migrated S3 row (e.g. 0011037020-Q_MX_M.csv)",
}
AQUARIUS_UNPOPULATED_GRADE = "50 - INDEFINIDO"

DEFERRED_SEDIMENT_LABELS: frozenset[str] = frozenset(
    {
        "CM_D",
        "CM_M",
        "TR_QS_D",
        "TR_QS_M",
        "TR_QS_A",
    }
)

VARIABLES_CATALOGUE_EVIDENCE = "catalogue:co_ideam:source.product.variables_catalogue"
S3_LISTINGS_EVIDENCE = "catalogue:co_ideam:source.station_product.s3_prefix_listings"
DATOSGOV_SERIES_EVIDENCE = "catalogue:co_ideam:source.product.datosgov_series_definitions"
HYDROLOGICAL_MANUALS_EVIDENCE = "catalogue:co_ideam:source.product.ideam_hydrological_manuals"
S3_OBSERVATION_WITNESSES_EVIDENCE = "catalogue:co_ideam:source.product.s3_observation_witnesses"


def _known_fact(value: str, *evidence: str) -> EvidenceFact:
    return EvidenceFact(value=value, state=EvidenceState.KNOWN, evidence=evidence)


@dataclass(frozen=True, slots=True)
class IdeamSeriesSpec:
    """Verified IDEAM S3 hydrological prefix identity, physical facts, and clipping rule."""

    etiqueta: str
    product_id: str
    socrata_view_id: str
    expected_parametro: Literal["Caudal", "Nivel"]
    expected_periodo: Literal["Horario", "Diario", "Mensual", "Anual"]
    expected_tipo_estadistica: Literal["", "Promedio", "Maxima", "Minima"]
    quantity: Literal["discharge", "stage"]
    source_unit: Literal["m3/s", "cm"]
    normalized_unit: Literal["m3/s", "cm"]
    target_unit: Literal["m3/s", "m"]
    frequency: Literal["daily", "monthly", "yearly"] | None
    statistic: Literal["mean", "max", "min"] | None
    clipping_axis: ClippingAxis


SERIES_SPECS: tuple[IdeamSeriesSpec, ...] = (
    # Discharge (10 series: m3/s -> m3/s)
    IdeamSeriesSpec(
        etiqueta="CAUDAL_H",
        product_id="caudal_h",
        socrata_view_id="79gx-f3v5",
        expected_parametro="Caudal",
        expected_periodo="Horario",
        expected_tipo_estadistica="",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        target_unit="m3/s",
        frequency=None,
        statistic=None,
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
    ),
    IdeamSeriesSpec(
        etiqueta="Q_MEDIA_D",
        product_id="q_media_d",
        socrata_view_id="jxnq-r3i9",
        expected_parametro="Caudal",
        expected_periodo="Diario",
        expected_tipo_estadistica="Promedio",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        target_unit="m3/s",
        frequency="daily",
        statistic="mean",
        clipping_axis=ClippingAxis.CALENDAR_DATE,
    ),
    IdeamSeriesSpec(
        etiqueta="Q_MX_D",
        product_id="q_mx_d",
        socrata_view_id="qp2g-x6it",
        expected_parametro="Caudal",
        expected_periodo="Diario",
        expected_tipo_estadistica="Maxima",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        target_unit="m3/s",
        frequency="daily",
        statistic="max",
        clipping_axis=ClippingAxis.CALENDAR_DATE,
    ),
    IdeamSeriesSpec(
        etiqueta="Q_MN_D",
        product_id="q_mn_d",
        socrata_view_id="qjdp-f6cs",
        expected_parametro="Caudal",
        expected_periodo="Diario",
        expected_tipo_estadistica="Minima",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        target_unit="m3/s",
        frequency="daily",
        statistic="min",
        clipping_axis=ClippingAxis.CALENDAR_DATE,
    ),
    IdeamSeriesSpec(
        etiqueta="Q_MEDIA_M",
        product_id="q_media_m",
        socrata_view_id="gih4-w7rj",
        expected_parametro="Caudal",
        expected_periodo="Mensual",
        expected_tipo_estadistica="Promedio",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        target_unit="m3/s",
        frequency="monthly",
        statistic="mean",
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
    ),
    IdeamSeriesSpec(
        etiqueta="Q_MX_M",
        product_id="q_mx_m",
        socrata_view_id="jkw2-6jak",
        expected_parametro="Caudal",
        expected_periodo="Mensual",
        expected_tipo_estadistica="Maxima",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        target_unit="m3/s",
        frequency="monthly",
        statistic="max",
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
    ),
    IdeamSeriesSpec(
        etiqueta="Q_MN_M",
        product_id="q_mn_m",
        socrata_view_id="ff2d-mj75",
        expected_parametro="Caudal",
        expected_periodo="Mensual",
        expected_tipo_estadistica="Minima",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        target_unit="m3/s",
        frequency="monthly",
        statistic="min",
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
    ),
    IdeamSeriesSpec(
        etiqueta="Q_MEDIA_A",
        product_id="q_media_a",
        socrata_view_id="yvp6-pqhh",
        expected_parametro="Caudal",
        expected_periodo="Anual",
        expected_tipo_estadistica="Promedio",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        target_unit="m3/s",
        frequency="yearly",
        statistic="mean",
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
    ),
    IdeamSeriesSpec(
        etiqueta="Q_MX_A",
        product_id="q_mx_a",
        socrata_view_id="k7qg-5zes",
        expected_parametro="Caudal",
        expected_periodo="Anual",
        expected_tipo_estadistica="Maxima",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        target_unit="m3/s",
        frequency="yearly",
        statistic="max",
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
    ),
    IdeamSeriesSpec(
        etiqueta="Q_MN_A",
        product_id="q_mn_a",
        socrata_view_id="5fz8-rtgp",
        expected_parametro="Caudal",
        expected_periodo="Anual",
        expected_tipo_estadistica="Minima",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        target_unit="m3/s",
        frequency="yearly",
        statistic="min",
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
    ),
    # Stage (10 series: cm -> m, vertical_reference="gauge_zero", vertical_datum=None)
    IdeamSeriesSpec(
        etiqueta="NIVEL_H",
        product_id="nivel_h",
        socrata_view_id="ig79-2jr9",
        expected_parametro="Nivel",
        expected_periodo="Horario",
        expected_tipo_estadistica="",
        quantity="stage",
        source_unit="cm",
        normalized_unit="cm",
        target_unit="m",
        frequency=None,
        statistic=None,
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
    ),
    IdeamSeriesSpec(
        etiqueta="NV_MEDIA_D",
        product_id="nv_media_d",
        socrata_view_id="9fxi-fthb",
        expected_parametro="Nivel",
        expected_periodo="Diario",
        expected_tipo_estadistica="Promedio",
        quantity="stage",
        source_unit="cm",
        normalized_unit="cm",
        target_unit="m",
        frequency="daily",
        statistic="mean",
        clipping_axis=ClippingAxis.CALENDAR_DATE,
    ),
    IdeamSeriesSpec(
        etiqueta="NV_MX_D",
        product_id="nv_mx_d",
        socrata_view_id="u372-gstf",
        expected_parametro="Nivel",
        expected_periodo="Diario",
        expected_tipo_estadistica="Maxima",
        quantity="stage",
        source_unit="cm",
        normalized_unit="cm",
        target_unit="m",
        frequency="daily",
        statistic="max",
        clipping_axis=ClippingAxis.CALENDAR_DATE,
    ),
    IdeamSeriesSpec(
        etiqueta="NV_MN_D",
        product_id="nv_mn_d",
        socrata_view_id="6uzq-e2fq",
        expected_parametro="Nivel",
        expected_periodo="Diario",
        expected_tipo_estadistica="Minima",
        quantity="stage",
        source_unit="cm",
        normalized_unit="cm",
        target_unit="m",
        frequency="daily",
        statistic="min",
        clipping_axis=ClippingAxis.CALENDAR_DATE,
    ),
    IdeamSeriesSpec(
        etiqueta="NV_MEDIA_M",
        product_id="nv_media_m",
        socrata_view_id="nu6h-fpsj",
        expected_parametro="Nivel",
        expected_periodo="Mensual",
        expected_tipo_estadistica="Promedio",
        quantity="stage",
        source_unit="cm",
        normalized_unit="cm",
        target_unit="m",
        frequency="monthly",
        statistic="mean",
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
    ),
    IdeamSeriesSpec(
        etiqueta="NV_MX_M",
        product_id="nv_mx_m",
        socrata_view_id="5pgu-m2b7",
        expected_parametro="Nivel",
        expected_periodo="Mensual",
        expected_tipo_estadistica="Maxima",
        quantity="stage",
        source_unit="cm",
        normalized_unit="cm",
        target_unit="m",
        frequency="monthly",
        statistic="max",
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
    ),
    IdeamSeriesSpec(
        etiqueta="NV_MN_M",
        product_id="nv_mn_m",
        socrata_view_id="tu7p-5m7z",
        expected_parametro="Nivel",
        expected_periodo="Mensual",
        expected_tipo_estadistica="Minima",
        quantity="stage",
        source_unit="cm",
        normalized_unit="cm",
        target_unit="m",
        frequency="monthly",
        statistic="min",
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
    ),
    IdeamSeriesSpec(
        etiqueta="NV_MEDIA_A",
        product_id="nv_media_a",
        socrata_view_id="uebv-rmna",
        expected_parametro="Nivel",
        expected_periodo="Anual",
        expected_tipo_estadistica="Promedio",
        quantity="stage",
        source_unit="cm",
        normalized_unit="cm",
        target_unit="m",
        frequency="yearly",
        statistic="mean",
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
    ),
    IdeamSeriesSpec(
        etiqueta="NV_MX_A",
        product_id="nv_mx_a",
        socrata_view_id="5r7u-4gzb",
        expected_parametro="Nivel",
        expected_periodo="Anual",
        expected_tipo_estadistica="Maxima",
        quantity="stage",
        source_unit="cm",
        normalized_unit="cm",
        target_unit="m",
        frequency="yearly",
        statistic="max",
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
    ),
    IdeamSeriesSpec(
        etiqueta="NV_MN_A",
        product_id="nv_mn_a",
        socrata_view_id="ay8a-9ujr",
        expected_parametro="Nivel",
        expected_periodo="Anual",
        expected_tipo_estadistica="Minima",
        quantity="stage",
        source_unit="cm",
        normalized_unit="cm",
        target_unit="m",
        frequency="yearly",
        statistic="min",
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
    ),
)

SPECS_BY_ETIQUETA: dict[str, IdeamSeriesSpec] = {spec.etiqueta: spec for spec in SERIES_SPECS}
SPECS_BY_PRODUCT_ID: dict[str, IdeamSeriesSpec] = {spec.product_id: spec for spec in SERIES_SPECS}
SPECS_BY_SOCRATA_VIEW_ID: dict[str, IdeamSeriesSpec] = {spec.socrata_view_id: spec for spec in SERIES_SPECS}

DISCHARGE_LABELS: tuple[str, ...] = tuple(spec.etiqueta for spec in SERIES_SPECS if spec.quantity == "discharge")
STAGE_LABELS: tuple[str, ...] = tuple(spec.etiqueta for spec in SERIES_SPECS if spec.quantity == "stage")
IN_SCOPE_HYDROLOGICAL_LABELS: tuple[str, ...] = tuple(spec.etiqueta for spec in SERIES_SPECS)


def association_product(etiqueta: str) -> str:
    """Map an in-scope IDEAM S3 ``etiqueta`` to its canonical ``product_id``."""
    spec = SPECS_BY_ETIQUETA.get(etiqueta)
    if spec is None:
        raise FatalContractError(f"Unsupported IDEAM S3 hydrological etiqueta: {etiqueta!r}")
    return spec.product_id


def series_physical_facts(
    etiqueta: str,
    *,
    source_unit: str | None = None,
    variables_evidence: str = VARIABLES_CATALOGUE_EVIDENCE,
    datosgov_evidence: str = DATOSGOV_SERIES_EVIDENCE,
    manuals_evidence: str = HYDROLOGICAL_MANUALS_EVIDENCE,
    witnesses_evidence: str = S3_OBSERVATION_WITNESSES_EVIDENCE,
) -> PhysicalFacts:
    """Build source-backed ``PhysicalFacts`` for one IDEAM S3 hydrological series.

    Sub-daily ``CAUDAL_H`` and ``NIVEL_H`` mix hourly automatic/limnigraphic records
    with conventional ``06:00``/``18:00`` staff-gauge observations, keeping
    ``frequency``, ``statistic``, and ``temporal_support`` ``not_established``.
    Across all 20 series, ``temporal_support``, ``day_definition``,
    ``timestamp_anchor``, ``time_zone``, and ``label_time`` remain unestablished
    because pre-2016 ``SISDHIM`` arithmetic daily averages and post-2016 AQUARIUS
    trapezoidal ``[00:00, 24:00]`` integrals coexist, partial months/years are
    published, and Colombia's 1992-1993 *Hora Gaviria* shifted timestamps by
    ``+01:00`` and folded ``1993-02-06 23:00:00`` without UTC offsets.
    """
    spec = SPECS_BY_ETIQUETA.get(etiqueta)
    if spec is None:
        raise FatalContractError(f"Unsupported IDEAM S3 hydrological etiqueta: {etiqueta!r}")

    resolved_unit = spec.source_unit if source_unit is None else source_unit.strip()
    normalized = UNITS.get(resolved_unit)
    if resolved_unit != spec.source_unit or normalized != spec.normalized_unit:
        raise FatalContractError(
            f"Unsupported IDEAM unit {source_unit!r} for {etiqueta!r}; expected {spec.source_unit!r}"
        )

    temporal_ev = (variables_evidence, datosgov_evidence, manuals_evidence, witnesses_evidence)
    facts = PhysicalFacts(
        facts_id="pending",
        quantity=_known_fact(spec.quantity, variables_evidence, datosgov_evidence),
        source_unit=_known_fact(resolved_unit, variables_evidence, datosgov_evidence, manuals_evidence),
        normalized_unit=normalized,
        frequency=_known_fact(spec.frequency, *temporal_ev) if spec.frequency is not None else EvidenceFact(),
        statistic=_known_fact(spec.statistic, *temporal_ev) if spec.statistic is not None else EvidenceFact(),
        temporal_support=EvidenceFact(),
        day_definition=EvidenceFact(),
        timestamp_anchor=EvidenceFact(),
        time_zone=EvidenceFact(),
        vertical_reference=(
            _known_fact("gauge_zero", manuals_evidence, witnesses_evidence)
            if spec.quantity == "stage"
            else EvidenceFact()
        ),
        vertical_datum=EvidenceFact(),
        clipping_axis=spec.clipping_axis,
        label_time=None,
    )
    facts = facts.model_copy(update={"facts_id": stable_id(facts.model_dump_json(exclude={"facts_id"}))})
    decision = admission(facts)
    if decision.status != "supported" or decision.target_unit != spec.target_unit:
        raise FatalContractError(f"IDEAM series {etiqueta!r} failed dimensional admission: {decision.reason}")
    return facts


def route_product_facts(etiqueta_or_product_id: str, *, source_unit: str | None = None) -> PhysicalFacts:
    """Return canonical product-level ``PhysicalFacts`` for ``products.parquet`` projection."""
    spec = SPECS_BY_ETIQUETA.get(etiqueta_or_product_id) or SPECS_BY_PRODUCT_ID.get(etiqueta_or_product_id)
    if spec is None:
        raise FatalContractError(f"Unsupported IDEAM product or etiqueta: {etiqueta_or_product_id!r}")
    return series_physical_facts(spec.etiqueta, source_unit=source_unit)


def source_identity_key(etiqueta: str, source_unit: str | None = None) -> tuple[str, str, str]:
    """Return the deterministic identity key shared between ``SourceDescription`` and ``SourceSeries``."""
    spec = SPECS_BY_ETIQUETA.get(etiqueta)
    if spec is None:
        raise FatalContractError(f"Unsupported IDEAM S3 hydrological etiqueta: {etiqueta!r}")
    resolved_unit = spec.source_unit if source_unit is None else source_unit.strip()
    if resolved_unit != spec.source_unit:
        raise FatalContractError(
            f"Unsupported IDEAM unit {source_unit!r} for {etiqueta!r}; expected {spec.source_unit!r}"
        )
    return ("s3_historicos_csv", spec.etiqueta, resolved_unit)


def source_series(
    station_id: str,
    etiqueta: str,
    *,
    source_unit: str | None = None,
    origin: Literal["catalogue", "response"] = "catalogue",
    identity_evidence: tuple[str, ...] = (
        VARIABLES_CATALOGUE_EVIDENCE,
        S3_LISTINGS_EVIDENCE,
        DATOSGOV_SERIES_EVIDENCE,
    ),
) -> SourceSeries:
    """Construct one concrete Colombia IDEAM ``SourceSeries`` for ``(station_id, etiqueta)``."""
    clean_station = station_id.strip()
    if len(clean_station) != 10 or not clean_station.isdigit() or clean_station != station_id:
        raise FatalContractError(f"IDEAM station_id must be a canonical 10-digit code: {station_id!r}")
    if not identity_evidence or any(not item for item in identity_evidence):
        raise FatalContractError("IDEAM source_series requires nonblank identity_evidence")
    spec = SPECS_BY_ETIQUETA.get(etiqueta)
    if spec is None:
        raise FatalContractError(f"Unsupported IDEAM S3 hydrological etiqueta: {etiqueta!r}")
    id_key = source_identity_key(spec.etiqueta, source_unit)
    facts = series_physical_facts(spec.etiqueta, source_unit=source_unit)
    return SourceSeries(
        series_id=stable_id("co_ideam", clean_station, *id_key),
        provider_id="co_ideam",
        station_id=clean_station,
        product_id=spec.product_id,
        identity=SourceIdentity(
            namespace=NAMESPACE,
            published_id=spec.etiqueta,
            origin=origin,
            evidence=identity_evidence,
        ),
        facts=(facts,),
    )


def validate_variables_row(
    etiqueta: str,
    *,
    parametro: str,
    unidad: str,
    periodo: str,
    tipo_estadistica: str,
) -> IdeamSeriesSpec:
    """Verify that a ``variables.csv`` row matches the established contract for ``etiqueta``."""
    spec = SPECS_BY_ETIQUETA.get(etiqueta)
    if spec is None:
        raise FatalContractError(f"Unsupported IDEAM S3 hydrological etiqueta: {etiqueta!r}")
    if (
        parametro.strip() != spec.expected_parametro
        or unidad.strip() != spec.source_unit
        or periodo.strip() != spec.expected_periodo
        or tipo_estadistica.strip() != spec.expected_tipo_estadistica
    ):
        raise FatalContractError(
            f"IDEAM variables.csv row for {etiqueta!r} drifted: "
            f"parametro={parametro!r}, unidad={unidad!r}, periodo={periodo!r}, "
            f"tipo_estadistica={tipo_estadistica!r}"
        )
    return spec


def validate_socrata_series_view(raw_bytes: bytes, *, expected_view_id: str | None = None) -> IdeamSeriesSpec:
    """Verify an official ``datos.gov.co`` Socrata hydrological dataset view JSON."""
    try:
        doc = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FatalContractError("IDEAM Datos Abiertos series metadata view is not valid UTF-8 JSON") from error
    if not isinstance(doc, dict):
        raise FatalContractError("IDEAM Datos Abiertos series metadata view must be a JSON object")
    view_id = doc.get("id")
    if not isinstance(view_id, str) or (expected_view_id is not None and view_id != expected_view_id):
        raise FatalContractError(f"Unexpected IDEAM Datos Abiertos view id {view_id!r}")
    spec = SPECS_BY_SOCRATA_VIEW_ID.get(view_id)
    if spec is None:
        raise FatalContractError(f"Unsupported IDEAM Datos Abiertos series view id {view_id!r}")
    if doc.get("licenseId") != EXPECTED_LICENSE_ID or EXPECTED_LICENSE_TEXT not in raw_bytes.decode("utf-8"):
        raise FatalContractError(f"IDEAM Datos Abiertos view {view_id!r} lacks CC BY-SA 4.0 license metadata")
    metadata = doc.get("metadata")
    access_points = metadata.get("accessPoints") if isinstance(metadata, dict) else None
    if not isinstance(access_points, dict) or spec.etiqueta not in access_points:
        raise FatalContractError(f"IDEAM Datos Abiertos view {view_id!r} lacks accessPoints[{spec.etiqueta!r}] binding")
    target_url = str(access_points[spec.etiqueta])
    expected_fragment = f"s3-estacionesideam/objects/observaciones/historicos/csv/{spec.etiqueta}"
    if expected_fragment not in target_url:
        raise FatalContractError(
            f"IDEAM Datos Abiertos view {view_id!r} accessPoint {target_url!r} disagrees with {expected_fragment!r}"
        )
    return spec


def validate_s3_observation_csv_bytes(
    raw_bytes: bytes,
    *,
    etiqueta: str,
) -> tuple[int, frozenset[str]]:
    """Validate an IDEAM S3 historical observation CSV against the Step-3 schema contract.

    Verifies UTF-8 encoding, exact 3-column ``CSV_HEADER``, non-empty row count,
    non-decreasing ``YYYY-MM-DD HH:MM:SS`` timestamps (allowing duplicate local
    wall-clock timestamps on folded DST nights such as ``1993-02-06 23:00:00``),
    calendar-month ``YYYY-MM-01`` / calendar-year ``YYYY-01-01`` date stamps on
    ``_M`` / ``_A`` series, and finite ``valorObservado`` values without blank cells.
    Returns ``(row_count, witnessed_approval_values)``.
    """
    spec = SPECS_BY_ETIQUETA.get(etiqueta)
    if spec is None:
        raise FatalContractError(f"Unsupported IDEAM S3 hydrological etiqueta: {etiqueta!r}")
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise FatalContractError(f"IDEAM S3 {etiqueta} CSV is not valid UTF-8 text") from error

    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if header is None or tuple(header) != CSV_HEADER:
        raise FatalContractError(f"IDEAM S3 {etiqueta} CSV lacks expected header {CSV_HEADER!r}: {header!r}")

    row_count = 0
    prev_ts: datetime | None = None
    approvals: set[str] = set()

    for line_no, row in enumerate(reader, start=2):
        if len(row) != 3:
            raise FatalContractError(f"IDEAM S3 {etiqueta} CSV line {line_no} has {len(row)} columns; expected 3")
        ts_raw, val_raw, approval_raw = row
        if len(ts_raw) != 19:
            raise FatalContractError(
                f"IDEAM S3 {etiqueta} CSV line {line_no} timestamp {ts_raw!r} lacks YYYY-MM-DD HH:MM:SS format"
            )
        try:
            ts = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S")
        except ValueError as error:
            raise FatalContractError(
                f"IDEAM S3 {etiqueta} CSV line {line_no} has invalid timestamp {ts_raw!r}"
            ) from error
        if prev_ts is not None and ts < prev_ts:
            raise FatalContractError(
                f"IDEAM S3 {etiqueta} CSV line {line_no} timestamp {ts_raw!r} decreases from {prev_ts!r}"
            )
        if spec.frequency == "monthly" and ts.day != 1:
            raise FatalContractError(
                f"IDEAM S3 monthly {etiqueta} CSV line {line_no} timestamp {ts_raw!r} is not first-of-month"
            )
        if spec.frequency == "yearly" and (ts.month != 1 or ts.day != 1):
            raise FatalContractError(f"IDEAM S3 yearly {etiqueta} CSV line {line_no} timestamp {ts_raw!r} is not Jan 1")
        val_clean = val_raw.strip()
        if not val_clean:
            raise FatalContractError(f"IDEAM S3 {etiqueta} CSV line {line_no} has blank valorObservado")
        try:
            numeric = float(val_clean)
        except ValueError as error:
            raise FatalContractError(
                f"IDEAM S3 {etiqueta} CSV line {line_no} has non-numeric valorObservado {val_raw!r}"
            ) from error
        if not math.isfinite(numeric):
            raise FatalContractError(
                f"IDEAM S3 {etiqueta} CSV line {line_no} has non-finite valorObservado {val_raw!r}"
            )
        if spec.quantity == "discharge" and numeric < 0.0:
            raise FatalContractError(
                f"IDEAM S3 discharge {etiqueta} CSV line {line_no} has negative discharge {numeric!r}"
            )
        prev_ts = ts
        approvals.add(approval_raw)
        row_count += 1

    if row_count == 0:
        raise FatalContractError(f"IDEAM S3 {etiqueta} CSV contains zero observation rows")
    return row_count, frozenset(approvals)


def build_source_descriptions(
    grouped_stations: Sequence[tuple[str, str, Sequence[str]]],
) -> tuple[SourceDescription, ...]:
    """Construct ``SourceDescription`` items for ``co_ideam`` from ``(etiqueta, unit, station_ids)``."""
    from rivretrieve._internal.catalogues.source_series import SourceDescription

    identity_ev = (
        VARIABLES_CATALOGUE_EVIDENCE,
        S3_LISTINGS_EVIDENCE,
        DATOSGOV_SERIES_EVIDENCE,
    )
    descriptions = []
    for etiqueta, unit, station_ids in grouped_stations:
        spec = SPECS_BY_ETIQUETA.get(etiqueta)
        if spec is None:
            raise FatalContractError(f"Unsupported IDEAM S3 hydrological etiqueta: {etiqueta!r}")
        facts = series_physical_facts(spec.etiqueta, source_unit=unit)
        descriptions.append(
            SourceDescription(
                product_id=spec.product_id,
                station_ids=tuple(sorted(station_ids)),
                identity_key=source_identity_key(spec.etiqueta, unit),
                native_coordinate=spec.etiqueta,
                identity=SourceIdentity(
                    namespace=NAMESPACE,
                    published_id=spec.etiqueta,
                    origin="catalogue",
                    evidence=identity_ev,
                ),
                facts=(facts,),
            )
        )
    return tuple(descriptions)
