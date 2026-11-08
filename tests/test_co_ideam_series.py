"""Unit and offline discovery tests for Colombia IDEAM series identity and physical meaning."""

from __future__ import annotations

import json

import polars as pl
import pytest

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.co_ideam.series import (
    APPROVAL_VOCABULARY,
    AQUARIUS_UNPOPULATED_GRADE,
    CSV_HEADER,
    DEFERRED_SEDIMENT_LABELS,
    DISCHARGE_LABELS,
    EXPECTED_LICENSE_TEXT,
    IN_SCOPE_HYDROLOGICAL_LABELS,
    NAMESPACE,
    SERIES_SPECS,
    SPECS_BY_ETIQUETA,
    STAGE_LABELS,
    association_product,
    route_product_facts,
    series_physical_facts,
    source_series,
    validate_s3_observation_csv_bytes,
    validate_socrata_series_view,
    validate_variables_row,
)
from rivretrieve._internal.source_series import ClippingAxis, EvidenceState, admission


def test_twenty_distinct_ideam_series_identities_and_physical_facts():
    assert len(SERIES_SPECS) == 20
    assert len(DISCHARGE_LABELS) == 10
    assert len(STAGE_LABELS) == 10
    assert len(IN_SCOPE_HYDROLOGICAL_LABELS) == 20
    assert len({spec.etiqueta for spec in SERIES_SPECS}) == 20
    assert len({spec.product_id for spec in SERIES_SPECS}) == 20
    assert len({spec.socrata_view_id for spec in SERIES_SPECS}) == 20
    assert DEFERRED_SEDIMENT_LABELS.isdisjoint(IN_SCOPE_HYDROLOGICAL_LABELS)

    series_at_station = [source_series("0011017010", spec.etiqueta) for spec in SERIES_SPECS]
    assert len({item.series_id for item in series_at_station}) == 20
    assert len({item.identity.published_id for item in series_at_station}) == 20
    assert {item.identity.namespace for item in series_at_station} == {NAMESPACE}

    for spec, item in zip(SERIES_SPECS, series_at_station, strict=True):
        assert item.product_id == association_product(spec.etiqueta) == spec.product_id
        facts = item.facts[0]
        assert facts == route_product_facts(spec.etiqueta) == route_product_facts(spec.product_id)
        decision = admission(facts)
        assert decision.status == "supported"
        if spec.quantity == "discharge":
            assert decision.target_unit == "m3/s"
            assert decision.factor == 1.0
            assert facts.source_unit.value == "m3/s"
            assert facts.normalized_unit == "m3/s"
            assert facts.vertical_reference.state is EvidenceState.NOT_ESTABLISHED
            assert facts.vertical_reference.value is None
        else:
            assert decision.target_unit == "m"
            assert decision.factor == 0.01
            assert facts.source_unit.value == "cm"
            assert facts.normalized_unit == "cm"
            assert facts.vertical_reference.state is EvidenceState.KNOWN
            assert facts.vertical_reference.value == "gauge_zero"
        assert facts.vertical_datum.state is EvidenceState.NOT_ESTABLISHED
        assert facts.vertical_datum.value is None
        assert facts.temporal_support.state is EvidenceState.NOT_ESTABLISHED
        assert facts.day_definition.state is EvidenceState.NOT_ESTABLISHED
        assert facts.timestamp_anchor.state is EvidenceState.NOT_ESTABLISHED
        assert facts.time_zone.state is EvidenceState.NOT_ESTABLISHED
        assert facts.label_time is None


def test_subdaily_vs_aggregate_frequencies_statistics_and_clipping_axes():
    for subdaily in ("CAUDAL_H", "NIVEL_H"):
        facts = series_physical_facts(subdaily)
        assert facts.frequency.state is EvidenceState.NOT_ESTABLISHED
        assert facts.frequency.value is None
        assert facts.statistic.state is EvidenceState.NOT_ESTABLISHED
        assert facts.statistic.value is None
        assert facts.clipping_axis is ClippingAxis.SOURCE_TIMESTAMP

    daily_labels = {"Q_MEDIA_D", "Q_MX_D", "Q_MN_D", "NV_MEDIA_D", "NV_MX_D", "NV_MN_D"}
    for etiqueta in IN_SCOPE_HYDROLOGICAL_LABELS:
        if etiqueta in {"CAUDAL_H", "NIVEL_H"}:
            continue
        facts = series_physical_facts(etiqueta)
        if etiqueta.endswith("_D"):
            assert facts.frequency.value == "daily"
            assert facts.clipping_axis is ClippingAxis.CALENDAR_DATE
        elif etiqueta.endswith("_M"):
            assert facts.frequency.value == "monthly"
            assert facts.clipping_axis is ClippingAxis.SOURCE_TIMESTAMP
        else:
            assert etiqueta.endswith("_A")
            assert facts.frequency.value == "yearly"
            assert facts.clipping_axis is ClippingAxis.SOURCE_TIMESTAMP
        if "_MEDIA_" in etiqueta:
            assert facts.statistic.value == "mean"
        elif "_MX_" in etiqueta:
            assert facts.statistic.value == "max"
        else:
            assert "_MN_" in etiqueta
            assert facts.statistic.value == "min"
    assert {
        etiqueta
        for etiqueta in IN_SCOPE_HYDROLOGICAL_LABELS
        if series_physical_facts(etiqueta).clipping_axis is ClippingAxis.CALENDAR_DATE
    } == daily_labels


def test_approval_vocabulary_and_csv_validator_edge_cases():
    assert set(APPROVAL_VOCABULARY) == {"Preliminar", "En revisión", "Definitivo", ""}
    assert AQUARIUS_UNPOPULATED_GRADE == "50 - INDEFINIDO"
    assert CSV_HEADER == ("fechaObservacion", "valorObservado", "nivelAprobacion")

    # Folded Hora Gaviria night (1993-02-06 23:00:00 duplicate wall-clock timestamps), negative stage, and 0.0 stage
    folded_stage_csv = (
        "fechaObservacion,valorObservado,nivelAprobacion\n"
        "1993-02-06 19:00:00,420.0,Definitivo\n"
        "1993-02-06 23:00:00,415.0,Preliminar\n"
        "1993-02-06 23:00:00,414.0,Preliminar\n"
        "1993-02-07 06:00:00,0.0,En revisión\n"
        "1993-02-07 18:00:00,-3.5,Definitivo\n"
    ).encode()
    count, approvals = validate_s3_observation_csv_bytes(folded_stage_csv, etiqueta="NIVEL_H")
    assert count == 5
    assert approvals == frozenset({"Definitivo", "Preliminar", "En revisión"})

    # Monthly CSV with legacy empty approval ("") and Hora Gaviria 01:00:00 stamp
    monthly_csv = (
        b"fechaObservacion,valorObservado,nivelAprobacion\n"
        b"1992-06-01 01:00:00,125.4,\n"
        b"1993-03-01 00:00:00,0.0,Definitivo\n"
    )
    m_count, m_approvals = validate_s3_observation_csv_bytes(monthly_csv, etiqueta="Q_MX_M")
    assert m_count == 2
    assert m_approvals == frozenset({"", "Definitivo"})

    # Reject wrong header, decreasing timestamp, blank value, non-finite float, negative discharge, bad M/A day
    with pytest.raises(FatalContractError, match="header"):
        validate_s3_observation_csv_bytes(
            b"fecha,valor,aprob\n2020-01-01 00:00:00,1.0,Definitivo\n", etiqueta="Q_MEDIA_D"
        )
    with pytest.raises(FatalContractError, match="decreases"):
        validate_s3_observation_csv_bytes(
            b"fechaObservacion,valorObservado,nivelAprobacion\n"
            b"2020-01-02 00:00:00,1.0,Definitivo\n"
            b"2020-01-01 00:00:00,1.0,Definitivo\n",
            etiqueta="Q_MEDIA_D",
        )
    with pytest.raises(FatalContractError, match="blank valorObservado"):
        validate_s3_observation_csv_bytes(
            b"fechaObservacion,valorObservado,nivelAprobacion\n2020-01-01 00:00:00,,Definitivo\n",
            etiqueta="Q_MEDIA_D",
        )
    with pytest.raises(FatalContractError, match="non-finite"):
        validate_s3_observation_csv_bytes(
            b"fechaObservacion,valorObservado,nivelAprobacion\n2020-01-01 00:00:00,nan,Definitivo\n",
            etiqueta="Q_MEDIA_D",
        )
    with pytest.raises(FatalContractError, match="negative discharge"):
        validate_s3_observation_csv_bytes(
            b"fechaObservacion,valorObservado,nivelAprobacion\n2020-01-01 00:00:00,-0.1,Definitivo\n",
            etiqueta="Q_MEDIA_D",
        )
    with pytest.raises(FatalContractError, match="not first-of-month"):
        validate_s3_observation_csv_bytes(
            b"fechaObservacion,valorObservado,nivelAprobacion\n2020-01-15 00:00:00,10.0,Definitivo\n",
            etiqueta="Q_MEDIA_M",
        )
    with pytest.raises(FatalContractError, match="not Jan 1"):
        validate_s3_observation_csv_bytes(
            b"fechaObservacion,valorObservado,nivelAprobacion\n2020-06-01 00:00:00,10.0,Definitivo\n",
            etiqueta="Q_MEDIA_A",
        )


def test_variables_and_socrata_validators_reject_drift():
    spec = SPECS_BY_ETIQUETA["Q_MEDIA_D"]
    assert (
        validate_variables_row(
            "Q_MEDIA_D",
            parametro="Caudal ",
            unidad="m3/s",
            periodo="Diario",
            tipo_estadistica="Promedio",
        )
        == spec
    )
    with pytest.raises(FatalContractError, match="drifted"):
        validate_variables_row(
            "Q_MEDIA_D",
            parametro="Caudal",
            unidad="m3/s",
            periodo="Diario",
            tipo_estadistica="Maxima",
        )
    with pytest.raises(FatalContractError, match="Unsupported IDEAM unit"):
        series_physical_facts("NV_MEDIA_D", source_unit="m")
    with pytest.raises(FatalContractError, match="10-digit code"):
        source_series("11017010", "Q_MEDIA_D")

    valid_card = json.dumps(
        {
            "id": "jxnq-r3i9",
            "licenseId": "CC_40_BY_SA",
            "license": {"name": EXPECTED_LICENSE_TEXT},
            "metadata": {
                "accessPoints": {
                    "Q_MEDIA_D": (
                        "https://datos.ideam.gov.co/objectsbrowser/index.html?public=#/app/ostore-buckets/"
                        "s3-estacionesideam/objects/observaciones/historicos/csv/Q_MEDIA_D"
                    )
                }
            },
        }
    ).encode("utf-8")
    assert validate_socrata_series_view(valid_card, expected_view_id="jxnq-r3i9") == spec
    with pytest.raises(FatalContractError, match="accessPoints"):
        validate_socrata_series_view(
            json.dumps(
                {
                    "id": "jxnq-r3i9",
                    "licenseId": "CC_40_BY_SA",
                    "license": {"name": EXPECTED_LICENSE_TEXT},
                    "metadata": {"accessPoints": {}},
                }
            ).encode("utf-8")
        )


def test_packaged_co_ideam_discovery_honors_established_facts_and_rejects_unestablished_predicates():
    import rivretrieve as rr

    daily_q = rr.series(
        rr.find(provider="co_ideam", quantity="discharge", frequency="daily", statistic="mean", on_issue="raise")
    )
    assert daily_q.height == 943
    assert daily_q["product_id"].unique().to_list() == ["q_media_d"]
    assert daily_q["frequency"].unique().to_list() == ["daily"]
    assert daily_q["statistic"].unique().to_list() == ["mean"]

    gauge_stage = rr.series(
        rr.find(provider="co_ideam", quantity="stage", vertical_reference="gauge_zero", on_issue="raise")
    )
    assert set(gauge_stage["product_id"].unique()) == {
        spec.product_id for spec in SERIES_SPECS if spec.quantity == "stage"
    }
    assert gauge_stage.filter(pl.col("product_id") == "nivel_h")["frequency"].unique().to_list() == [None]
    assert gauge_stage.filter(pl.col("product_id") == "nivel_h")["statistic"].unique().to_list() == [None]

    monthly_max_stage = rr.series(
        rr.find(
            provider="co_ideam",
            quantity="stage",
            frequency="monthly",
            statistic="max",
            vertical_reference="gauge_zero",
            on_issue="raise",
        )
    )
    assert monthly_max_stage.height == 1_232
    assert monthly_max_stage["product_id"].unique().to_list() == ["nv_mx_m"]

    # Mixed conventional/automatic sub-daily series never guess frequency="hourly" or statistic="instantaneous"
    assert rr.series(rr.find(provider="co_ideam", frequency="hourly", on_issue="raise")).is_empty()
    assert rr.series(rr.find(provider="co_ideam", statistic="instantaneous", on_issue="raise")).is_empty()

    # Unestablished temporal support, time zone, day definition, and vertical datum reject rather than guess
    assert rr.series(rr.find(provider="co_ideam", time_zone="America/Bogota", on_issue="raise")).is_empty()
    assert rr.series(rr.find(provider="co_ideam", time_zone="UTC-05:00", on_issue="raise")).is_empty()
    assert rr.series(rr.find(provider="co_ideam", temporal_support="calendar_day", on_issue="raise")).is_empty()
    assert rr.series(rr.find(provider="co_ideam", day_definition="00:00", on_issue="raise")).is_empty()
    assert rr.series(rr.find(provider="co_ideam", vertical_datum="Buenaventura", on_issue="raise")).is_empty()
