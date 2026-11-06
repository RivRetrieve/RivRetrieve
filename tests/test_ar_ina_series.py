"""Unit tests for Argentina INA Alerta5 source-series identity, physical facts, and payload validation."""

from __future__ import annotations

from datetime import UTC

import pytest

from rivretrieve._internal.catalogues.products import product_row
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ar_ina.series import (
    DATA_AVAILABILITY_CODES,
    IN_SCOPE_SERIES_SPECS,
    NAMESPACE,
    SPECS_BY_PRODUCT_ID,
    SPECS_BY_VAR_ID,
    product_physical_facts,
    route_product_facts,
    source_series,
    validate_observation_row,
    validate_procedimientos_dictionary,
    validate_series_record_metadata,
    validate_unidades_dictionary,
    validate_variables_dictionary,
)
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceState,
    PhysicalPredicate,
    RestrictionKind,
    SeriesScope,
    admission,
    stable_id,
)

EXPECTED_PRODUCT_TABLE_PROJECTION: dict[str, tuple[str, str, str, str, str, str, str]] = {
    "discharge_daily_mean": ("discharge", "daily", "mean", "calendar_day", "start", "m3/s", "var_id=40;proc_id=1"),
    "discharge_instantaneous": (
        "discharge",
        "unknown",
        "instantaneous",
        "instant",
        "measurement_time",
        "m3/s",
        "var_id=4;proc_id=2",
    ),
    "discharge_monthly_mean": (
        "discharge",
        "monthly",
        "mean",
        "calendar_month",
        "start",
        "m3/s",
        "var_id=48;proc_id=1",
    ),
    "discharge_monthly_min": (
        "discharge",
        "monthly",
        "min",
        "calendar_month",
        "start",
        "m3/s",
        "var_id=51;proc_id=1",
    ),
    "discharge_monthly_max": (
        "discharge",
        "monthly",
        "max",
        "calendar_month",
        "start",
        "m3/s",
        "var_id=52;proc_id=1",
    ),
    "stage_daily_mean": ("stage", "daily", "mean", "calendar_day", "start", "m", "var_id=39;proc_id=1"),
    "stage_instantaneous": (
        "stage",
        "unknown",
        "instantaneous",
        "instant",
        "measurement_time",
        "m",
        "var_id=2;proc_id=1",
    ),
    "stage_hourly": ("stage", "hourly", "unknown", "unknown", "start", "m", "var_id=85;proc_id=1"),
    "stage_4hourly": ("stage", "unknown", "unknown", "unknown", "start", "m", "var_id=101;proc_id=1"),
    "stage_weekly_mean": ("stage", "unknown", "mean", "interval", "start", "m", "var_id=67;proc_id=1"),
    "stage_monthly_mean": ("stage", "monthly", "mean", "calendar_month", "start", "m", "var_id=33;proc_id=1"),
    "stage_monthly_min": ("stage", "monthly", "min", "calendar_month", "start", "m", "var_id=49;proc_id=1"),
    "stage_monthly_max": ("stage", "monthly", "max", "calendar_month", "start", "m", "var_id=50;proc_id=1"),
}


def test_all_13_products_admit_dimensions_and_project_expected_product_rows() -> None:
    assert len(IN_SCOPE_SERIES_SPECS) == 13
    assert set(SPECS_BY_PRODUCT_ID) == set(EXPECTED_PRODUCT_TABLE_PROJECTION)

    for spec in IN_SCOPE_SERIES_SPECS:
        facts = route_product_facts(spec.product_id)
        assert facts.facts_id == stable_id(facts.model_dump_json(exclude={"facts_id"}))
        assert facts.time_zone.value == "UTC"
        assert facts.day_definition.state is EvidenceState.NOT_ESTABLISHED
        assert facts.vertical_datum.state is EvidenceState.NOT_ESTABLISHED
        assert facts.clipping_axis is ClippingAxis.SOURCE_TIMESTAMP

        decision = admission(facts)
        assert decision.status == "supported"
        assert decision.factor == 1.0
        if spec.observed_property == "discharge":
            assert decision.target_unit == "m3/s"
            assert facts.source_unit.value == "m^3/s"
            assert facts.normalized_unit == "m3/s"
            assert facts.vertical_reference.state is EvidenceState.NOT_ESTABLISHED
        else:
            assert decision.target_unit == "m"
            assert facts.source_unit.value == "m"
            assert facts.normalized_unit == "m"
            assert facts.vertical_reference.value == "gauge_zero"

        row = product_row("ar_ina", spec.product_id, spec.native_id, facts)
        assert (
            row["observed_property"],
            row["frequency"],
            row["statistic"],
            row["period_type"],
            row["period_anchor"],
            row["unit"],
            row["native_id"],
        ) == EXPECTED_PRODUCT_TABLE_PROJECTION[spec.product_id]


def test_source_series_identity_stability_and_predicate_honesty() -> None:
    cat_qmd = source_series("19", "discharge_daily_mean", published_series_id=26616, origin="catalogue")
    resp_qmd = source_series(
        "19",
        "discharge_daily_mean",
        published_series_id="26616",
        origin="response",
        identity_evidence="https://alerta.ina.gob.ar/a5/obs/puntual/series/26616/observaciones",
    )
    assert cat_qmd.series_id == resp_qmd.series_id == stable_id("ar_ina", "19", NAMESPACE, "26616")
    assert cat_qmd.identity.namespace == NAMESPACE
    assert cat_qmd.identity.published_id == "26616"
    assert cat_qmd.variant == "26616"

    # Pre-2009 Argentina DST shifts civil midnight between UTC-03:00 and UTC-02:00;
    # fixed day_definition predicates must not match.
    fixed_day_scope = SeriesScope(predicates=(PhysicalPredicate(field="day_definition", value="UTC-03:00"),))
    assert not fixed_day_scope.matches(cat_qmd)

    utc_daily_mean_scope = SeriesScope(
        predicates=(
            PhysicalPredicate(field="quantity", value="discharge"),
            PhysicalPredicate(field="frequency", value="daily"),
            PhysicalPredicate(field="statistic", value="mean"),
            PhysicalPredicate(field="temporal_support", value="calendar_day"),
            PhysicalPredicate(field="time_zone", value="UTC"),
        )
    )
    assert utc_daily_mean_scope.matches(cat_qmd)

    # Slotted Continuous stage series (H1h=85, Hm4h=101) do not claim mean or instantaneous statistics.
    h1h = source_series("52", "stage_hourly", published_series_id=31605)
    hm4h = source_series("2112", "stage_4hourly", published_series_id=38398)
    for slotted in (h1h, hm4h):
        assert not SeriesScope(predicates=(PhysicalPredicate(field="statistic", value="mean"),)).matches(slotted)
        assert not SeriesScope(predicates=(PhysicalPredicate(field="statistic", value="instantaneous"),)).matches(
            slotted
        )
        assert SeriesScope(predicates=(PhysicalPredicate(field="timestamp_anchor", value="start"),)).matches(slotted)
        assert SeriesScope(predicates=(PhysicalPredicate(field="vertical_reference", value="gauge_zero"),)).matches(
            slotted
        )
        assert not SeriesScope(predicates=(PhysicalPredicate(field="vertical_datum", value="IGN"),)).matches(slotted)
    assert SeriesScope(predicates=(PhysicalPredicate(field="frequency", value="hourly"),)).matches(h1h)
    assert not SeriesScope(predicates=(PhysicalPredicate(field="frequency", value="hourly"),)).matches(hm4h)

    # Monthly extrema match calendar_month support and min/max statistics.
    hmmin = source_series("52", "stage_monthly_min", published_series_id=25638)
    assert SeriesScope(
        predicates=(
            PhysicalPredicate(field="frequency", value="monthly"),
            PhysicalPredicate(field="statistic", value="min"),
            PhysicalPredicate(field="temporal_support", value="calendar_month"),
        )
    ).matches(hmmin)

    # Explicit variant restriction matches published Serie.id without matching sibling products.
    explicit_variant = SeriesScope(restriction=RestrictionKind.EXPLICIT, variants=("26616",))
    assert explicit_variant.matches(cat_qmd)
    assert not explicit_variant.matches(hmmin)


def test_observation_row_validation_preserves_dst_intervals_null_gaps_negative_stage_and_zero_flow() -> None:
    qmd_spec = SPECS_BY_VAR_ID[40]
    # 2008-10-19 Argentina DST spring-forward (23h interval)
    s1, e1, v1 = validate_observation_row(
        {
            "series_id": 26616,
            "timestart": "2008-10-19T03:00:00.000Z",
            "timeend": "2008-10-20T02:00:00.000Z",
            "unit_id": None,
            "valor": 11600,
        },
        qmd_spec,
        expected_series_id=26616,
    )
    assert (e1 - s1).total_seconds() == 23 * 3600
    assert s1.tzinfo == UTC
    assert v1 == 11600.0

    # 2009-03-14 Argentina DST fall-back (25h interval) and zero flow
    s2, e2, v2 = validate_observation_row(
        {
            "series_id": 26616,
            "timestart": "2009-03-14T02:00:00.000Z",
            "timeend": "2009-03-15T03:00:00.000Z",
            "unit_id": 10,
            "valor": 0.0,
        },
        qmd_spec,
        expected_series_id=26616,
    )
    assert (e2 - s2).total_seconds() == 25 * 3600
    assert v2 == 0.0

    # Missing interval row (valor: null) returns None rather than raising or coercing to 0.0
    _, _, gap_val = validate_observation_row(
        {
            "series_id": 31605,
            "timestart": "2024-01-01T08:00:00.000Z",
            "timeend": "2024-01-01T09:00:00.000Z",
            "unit_id": None,
            "valor": None,
        },
        SPECS_BY_VAR_ID[85],
        expected_series_id=31605,
    )
    assert gap_val is None

    # Genuine negative gauge-zero stage on instantaneous and monthly-min series
    inst_s, inst_e, neg_stage = validate_observation_row(
        {
            "series_id": 52,
            "timestart": "2022-08-15T12:45:00.000Z",
            "timeend": "2022-08-15T12:45:00.000Z",
            "unit_id": None,
            "valor": -0.19,
        },
        SPECS_BY_VAR_ID[2],
        expected_series_id=52,
    )
    assert inst_s == inst_e
    assert neg_stage == -0.19


def test_validators_fail_closed_on_upstream_contract_contradictions() -> None:
    with pytest.raises(FatalContractError, match="Unsupported INA Alerta5 product_id"):
        product_physical_facts("water_temperature_daily_mean")

    with pytest.raises(FatalContractError, match="Unsupported INA Alerta5 unit"):
        source_series("8", "discharge_daily_mean", published_series_id=26605, source_unit="l/s")

    with pytest.raises(FatalContractError, match="positive integer"):
        source_series("8", "discharge_daily_mean", published_series_id=0)

    with pytest.raises(FatalContractError, match="canonical positive digits"):
        source_series("8", "discharge_daily_mean", published_series_id="0026605")

    # Observation row failures: wrong series_id, converted unit_id, non-UTC timestamp, bad interval, boolean/NaN valor
    qmd_spec = SPECS_BY_VAR_ID[40]
    base_obs = {
        "series_id": 26605,
        "timestart": "2024-01-01T03:00:00.000Z",
        "timeend": "2024-01-02T03:00:00.000Z",
        "unit_id": None,
        "valor": 1200.5,
    }
    with pytest.raises(FatalContractError, match="series_id"):
        validate_observation_row({**base_obs, "series_id": 999}, qmd_spec, expected_series_id=26605)
    with pytest.raises(FatalContractError, match="unit_id"):
        validate_observation_row({**base_obs, "unit_id": 11}, qmd_spec, expected_series_id=26605)
    with pytest.raises(FatalContractError, match="explicit UTC"):
        validate_observation_row(
            {**base_obs, "timestart": "2024-01-01T00:00:00-03:00"}, qmd_spec, expected_series_id=26605
        )
    with pytest.raises(FatalContractError, match="timestart < timeend"):
        validate_observation_row(
            {**base_obs, "timeend": "2024-01-01T03:00:00.000Z"}, qmd_spec, expected_series_id=26605
        )
    with pytest.raises(FatalContractError, match="timestart == timeend"):
        validate_observation_row(base_obs, SPECS_BY_VAR_ID[4], expected_series_id=26605)
    with pytest.raises(FatalContractError, match="finite number or null"):
        validate_observation_row({**base_obs, "valor": True}, qmd_spec, expected_series_id=26605)
    with pytest.raises(FatalContractError, match="non-finite"):
        validate_observation_row({**base_obs, "valor": float("nan")}, qmd_spec, expected_series_id=26605)

    # Series record and reference dictionary validation failures
    valid_series_row = {
        "var": {
            "id": 40,
            "datatype": "Average",
            "timeSupport": qmd_spec.expected_time_support,
            "def_hora_corte": dict.fromkeys(qmd_spec.expected_time_support, 0),
        },
        "unidades": {"id": 10, "abrev": "m^3/s"},
        "date_range": {"data_availability": "C"},
    }
    assert set(DATA_AVAILABILITY_CODES) >= {"H", "C", "RT", "NRT", "S", "N"}
    assert validate_series_record_metadata(valid_series_row, qmd_spec, series_id=26605, proc_id=1) == "m^3/s"

    with pytest.raises(FatalContractError, match="data_availability"):
        validate_series_record_metadata(
            {**valid_series_row, "date_range": {"data_availability": "UNKNOWN"}},
            qmd_spec,
            series_id=26605,
            proc_id=1,
        )
    with pytest.raises(FatalContractError, match="datatype"):
        validate_series_record_metadata(
            {**valid_series_row, "var": {**valid_series_row["var"], "datatype": "Continuous"}},
            qmd_spec,
            series_id=26605,
            proc_id=1,
        )

    unidades_ok = [
        {"id": 10, "abrev": "m^3/s", "UnitsType": "Flow"},
        {"id": 11, "abrev": "m", "UnitsType": "Length"},
    ]
    validate_unidades_dictionary(unidades_ok)
    with pytest.raises(FatalContractError, match="unidades"):
        validate_unidades_dictionary([{"id": 10, "abrev": "l/s", "UnitsType": "Flow"}])

    procs_ok = [
        {"id": 1, "abrev": "medicion"},
        {"id": 2, "abrev": "curva"},
        *({"id": pid, "abrev": f"p{pid}"} for pid in (3, 4, 5, 6, 7, 8, 9)),
    ]
    validate_procedimientos_dictionary(procs_ok)
    with pytest.raises(FatalContractError, match="procedimientos"):
        validate_procedimientos_dictionary([{"id": 1, "abrev": "sim"}])

    vars_ok = [
        {
            "id": spec.var_id,
            "var": spec.var_code,
            "datatype": spec.expected_datatype,
            "timeSupport": spec.expected_time_support,
            "def_unit_id": str(spec.expected_unit_id),
            "SampleMedium": "Surface Water",
            "GeneralCategory": "Hydrology",
        }
        for spec in IN_SCOPE_SERIES_SPECS
    ]
    validate_variables_dictionary(vars_ok)
    drifted_vars = [dict(v) for v in vars_ok]
    drifted_vars[0]["datatype"] = "Continuous"
    with pytest.raises(FatalContractError, match="datatype drifted"):
        validate_variables_dictionary(drifted_vars)
