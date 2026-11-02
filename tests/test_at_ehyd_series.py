"""Synthetic controls for official Austria eHYD series identity and physical facts."""

import polars as pl
import pytest

from rivretrieve._internal.catalogues.artifact import packaged_catalogue_artifact_from_components
from rivretrieve._internal.catalogues.source_series import catalogue_series
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.at_ehyd.generate_catalogue import (
    ASSOCIATION_SCHEMA,
    catalogue_tables,
    describe_associations,
    station_native_table,
)
from rivretrieve._internal.providers.at_ehyd.series import (
    IN_SCOPE_OWF_FTYPES,
    OWF_INTERVAL_RULE_TEXT,
    OWF_MISSING_VALUE_TOKEN,
    PEGEL_AKTUELL_OBSERVATION_FIELDS,
    PEGEL_BGIS_NON_SERIES_FIELDS,
    PEGEL_LONGTERM_EXCLUDED_FIELDS,
    QUALITY_VOCABULARY,
    parse_exportzeitreihe,
    parse_owf_header_facts,
    route_product_facts,
    source_series,
)
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceState,
    PhysicalPredicate,
    SeriesScope,
    admission,
    stable_id,
)


def _owf_preamble(
    *,
    unit_field: str = " [cm]",
    ezr: str = "(10001025,Wasserstand,I,Mit,T,1,F,Z,0,,,)",
    interval_rule: bool = True,
    pnp_rows: tuple[tuple[str, str], ...] = (("01.01.1981", "160,11"),),
) -> bytes:
    lines = [
        "Messstelle:                ;Synthetic Gauge",
        "HZB-Nummer:                ;209486",
        f"Einheit:                   ;{unit_field}",
    ]
    if pnp_rows:
        lines.append("Pegelnullpunkt:")
        lines.append("        gültig seit:       ;Höhe [m ü.A.]:")
        for since, height in pnp_rows:
            lines.append(f"         {since}        ;{height}")
    lines.append(f"Exportzeitreihe:           ;{ezr}")
    if interval_rule:
        lines.append(f";                          ;{OWF_INTERVAL_RULE_TEXT}")
    lines.append("Werte:")
    return ("\r\n".join(lines) + "\r\n").encode("cp1252")


def test_publication_routes_remain_distinct_at_overlapping_gauge():
    station = "209486"
    routes = [
        *[(station, "owf", ftyp, unit) for ftyp, (_, unit) in sorted(IN_SCOPE_OWF_FTYPES.items())],
        (station, "pegel_bgis", "Abfluss", "m³/s"),
        (station, "pegel_bgis", "Wasserstand", "cm"),
        (station, "pegel_longterm", "Abfluss", "m³/s"),
        (station, "pegel_longterm", "Wasserstand", "cm"),
    ]
    resolved = [source_series(st, sub, var, units=(unit,), origin="response") for st, sub, var, unit in routes]
    assert len(resolved) == 11
    assert len({item.series_id for item in resolved}) == 11
    assert len({(item.identity.namespace, item.identity.published_id) for item in resolved}) == 11

    by_product = {item.product_id: item for item in resolved}
    assert by_product["owf_abfl_tagesmittel"].identity.namespace == "ehyd.owf"
    assert by_product["owf_abfl_tagesmittel"].identity.published_id == "owf_abfl_tagesmittel"
    assert by_product["pegel_bgis_abfluss"].identity.namespace == "ehyd.pegel_bgis.Abfluss"
    assert by_product["pegel_bgis_abfluss"].identity.published_id == "data"
    assert by_product["pegel_longterm_abfluss"].identity.namespace == "ehyd.pegel_longterm.Abfluss"
    assert by_product["pegel_longterm_abfluss"].identity.published_id == "current_value"
    assert (
        source_series("0209486", "owf", "owf_abfl_tagesmittel", units=("m³/s",)).series_id
        != by_product["owf_abfl_tagesmittel"].series_id
    )


def test_quality_and_excluded_field_vocabularies_preserve_publisher_boundaries():
    assert QUALITY_VOCABULARY == {
        "owf": "Geprüfte Daten",
        "pegel_aktuell": "ungeprüfte Rohdaten!",
    }
    assert OWF_MISSING_VALUE_TOKEN == "Lücke"
    assert PEGEL_AKTUELL_OBSERVATION_FIELDS == {
        "pegel_bgis": "data",
        "pegel_longterm": "current_value",
    }
    assert "last_year_value" in PEGEL_LONGTERM_EXCLUDED_FIELDS
    assert {"min_data", "min_year", "max_data", "max_year", "mit_data", "p5_data", "p95_data"} <= (
        PEGEL_LONGTERM_EXCLUDED_FIELDS
    )
    assert {"wert", "zp", "niedrigwasser", "hochwasser1", "hochwasser2", "hochwasser3"} <= PEGEL_BGIS_NON_SERIES_FIELDS


@pytest.mark.parametrize(
    "subsystem,variable,unit,quantity,target_unit,factor,vertical_ref",
    [
        ("owf", "owf_abfl_tagesmittel", "m³/s", "discharge", "m3/s", 1.0, None),
        ("owf", "owf_wasserst_tagesmittel", "cm", "stage", "m", 0.01, "gauge_zero"),
        ("owf", "owf_wassertemp_monatsmittel", "°C", "temperature", "degC", 1.0, None),
        ("pegel_bgis", "Abfluss", "m³/s", "discharge", "m3/s", 1.0, None),
        ("pegel_bgis", "Wasserstand", "cm", "stage", "m", 0.01, "gauge_zero"),
        ("pegel_longterm", "Abfluss", "m³/s", "discharge", "m3/s", 1.0, None),
        ("pegel_longterm", "Wasserstand", "cm", "stage", "m", 0.01, "gauge_zero"),
    ],
)
def test_dimensional_admission_and_gauge_zero_stage_without_datum_rewrite(
    subsystem, variable, unit, quantity, target_unit, factor, vertical_ref
):
    facts = source_series("209486", subsystem, variable, units=(unit,)).facts[0]
    decision = admission(facts)
    assert decision.status == "supported"
    assert facts.quantity.value == quantity
    assert facts.source_unit.value == unit
    assert decision.target_unit == target_unit
    assert decision.factor == pytest.approx(factor)
    assert facts.vertical_reference.value == vertical_ref
    assert facts.vertical_datum.state is EvidenceState.NOT_ESTABLISHED
    assert facts.vertical_datum.value is None

    # Signed values (negative cm below Pegelnullpunkt, supercooling °C) scale linearly without offset
    if unit == "cm":
        assert -227.0 * decision.factor == pytest.approx(-2.27)
    if unit == "°C":
        assert -2.8 * decision.factor == pytest.approx(-2.8)


@pytest.mark.parametrize("bad_unit", [None, "t", "m ü.A", "°C"])
def test_missing_or_incompatible_units_remain_unsupported_for_discharge_and_stage(bad_unit):
    q_facts = source_series("209486", "owf", "owf_abfl_tagesmittel", units=(bad_unit,)).facts[0]
    w_facts = source_series("209486", "pegel_bgis", "Wasserstand", units=(bad_unit,)).facts[0]
    assert admission(q_facts).status == "unsupported"
    assert admission(w_facts).status == "unsupported"
    assert w_facts.vertical_reference.value is None


def test_owf_header_parser_covers_witnessed_variants_and_rejects_contradictions():
    # Standard coded interval series with multi-epoch Pegelnullpunkt
    parsed = parse_owf_header_facts(
        _owf_preamble(
            unit_field=" [cm]",
            ezr="(10001025,Wasserstand,I,Mit,T,1,F,Z,0,,,)",
            interval_rule=True,
            pnp_rows=(("01.01.1951", "161,00"), ("01.01.1981", "160,11")),
        ),
        expected_ftyp="owf_wasserst_tagesmittel",
    )
    assert parsed.unit == "cm"
    assert parsed.has_interval_rule is True
    assert parsed.pegelnullpunkt_epochs == (("01.01.1951", "161,00"), ("01.01.1981", "160,11"))
    assert parsed.descriptor is not None
    assert (parsed.descriptor.parameter, parsed.descriptor.kind_code, parsed.descriptor.canonical_statistic) == (
        "Wasserstand",
        "I",
        "mean",
    )

    # 204032 Werfen unparenthesized Exportzeitreihe without numeric code
    werfen = parse_owf_header_facts(
        _owf_preamble(unit_field=" m³/s", ezr="Abfluss,I,Mit,T,1", interval_rule=True, pnp_rows=()),
        expected_ftyp="owf_abfl_tagesmittel",
    )
    assert werfen.descriptor is not None and werfen.descriptor.series_code is None
    assert werfen.descriptor.parameter == "Abfluss"

    # 204388 / 211078 uppercase MIN/MAX with step 0 on monthly extrema
    monthly_zero = parse_owf_header_facts(
        _owf_preamble(
            unit_field=" [cm]",
            ezr="(10001027,Wasserstand,M,MIN,M,0,F,Z,0,,,)",
            interval_rule=False,
        ),
        expected_ftyp="owf_wasserst_monatsminima",
    )
    assert monthly_zero.descriptor is not None
    assert (monthly_zero.descriptor.canonical_statistic, monthly_zero.descriptor.period_step) == ("min", "0")

    # Nested brackets on water temperature
    wt = parse_owf_header_facts(
        _owf_preamble(
            unit_field=" [ [°C]]",
            ezr="(10002010,WTemperatur,I,Mit,M,1,F,Z,0,,,)",
            interval_rule=True,
            pnp_rows=(),
        ),
        expected_ftyp="owf_wassertemp_monatsmittel",
    )
    assert wt.unit == "°C"

    # Empty Einheit: [] with (Invalid ZR) returns unit=None without raising
    empty_unit = parse_owf_header_facts(
        _owf_preamble(unit_field=" []", ezr="(Invalid ZR)", interval_rule=False),
        expected_ftyp="owf_wasserst_tagesmittel",
    )
    assert empty_unit.unit is None and empty_unit.descriptor is None

    # Missing interval rule on 'I' series raises
    with pytest.raises(FatalContractError, match="interval validity"):
        parse_owf_header_facts(
            _owf_preamble(unit_field=" [cm]", ezr="(1,Wasserstand,I,Mit,T,1)", interval_rule=False),
            expected_ftyp="owf_wasserst_tagesmittel",
        )

    # Interval rule present on 'M' instantaneous extrema raises
    with pytest.raises(FatalContractError, match="interval rule"):
        parse_owf_header_facts(
            _owf_preamble(unit_field=" [cm]", ezr="(1,Wasserstand,M,Max,M,1)", interval_rule=True),
            expected_ftyp="owf_wasserst_monatsmaxima",
        )

    # Contradicted parameter / statistic raises
    with pytest.raises(FatalContractError, match="contradicts"):
        parse_owf_header_facts(
            _owf_preamble(unit_field=" m³/s", ezr="(1,Abfluss,M,Max,M,1)", interval_rule=False),
            expected_ftyp="owf_abfl_monatsminima",
        )


def test_207340_daily_anomaly_withholds_monthly_frequency_and_route_wide_period():
    ezr_207340 = parse_exportzeitreihe("(10001027,Wasserstand,M,Min,T,1,F,Z,0,,,)")
    from_cat = source_series("207340", "owf", "owf_wasserst_monatsminima", units=("cm",), origin="catalogue")
    from_resp = source_series(
        "207340",
        "owf",
        "owf_wasserst_monatsminima",
        units=("cm",),
        origin="response",
        descriptor=ezr_207340,
    )
    for item in (from_cat, from_resp):
        facts = item.facts[0]
        assert admission(facts).status == "supported"
        assert facts.statistic.value == "min"
        assert facts.vertical_reference.value == "gauge_zero"
        assert facts.frequency.state is EvidenceState.NOT_ESTABLISHED
        assert facts.temporal_support.state is EvidenceState.NOT_ESTABLISHED

    normal = source_series("209486", "owf", "owf_wasserst_monatsminima", units=("cm",), origin="catalogue")
    assert normal.facts[0].frequency.value == "monthly"
    assert normal.facts[0].temporal_support.value == "calendar_month"
    assert normal.facts[0].facts_id != from_cat.facts[0].facts_id

    route_facts = route_product_facts("owf", "owf_wasserst_monatsminima", "cm")
    assert route_facts.statistic.value == "min"
    assert route_facts.frequency.value is None
    assert route_facts.temporal_support.value is None


def test_temporal_facts_and_predicate_rejection_prevent_silent_misinterpretation():
    owf_q = source_series("209486", "owf", "owf_abfl_tagesmittel", units=("m³/s",))
    owf_qmax = source_series("209486", "owf", "owf_abfl_monatsmaxima", units=("m³/s",))
    bgis_q = source_series("209486", "pegel_bgis", "Abfluss", units=("m³/s",))
    lt_q = source_series("209486", "pegel_longterm", "Abfluss", units=("m³/s",))

    assert owf_q.facts[0].frequency.value == "daily"
    assert owf_q.facts[0].statistic.value == "mean"
    assert owf_q.facts[0].timestamp_anchor.value == "start"
    assert owf_q.facts[0].temporal_support.value is None
    assert owf_q.facts[0].time_zone.value is None
    assert owf_q.facts[0].day_definition.value is None
    assert owf_q.facts[0].clipping_axis is ClippingAxis.SOURCE_TIMESTAMP

    assert owf_qmax.facts[0].frequency.value == "monthly"
    assert owf_qmax.facts[0].statistic.value == "max"
    assert owf_qmax.facts[0].temporal_support.value == "calendar_month"
    assert owf_qmax.facts[0].timestamp_anchor.value is None

    assert bgis_q.facts[0].time_zone.value == "UTC+01:00"
    assert bgis_q.facts[0].frequency.value is None
    assert bgis_q.facts[0].statistic.value is None
    assert bgis_q.facts[0].clipping_axis is ClippingAxis.SOURCE_TIMESTAMP

    assert lt_q.facts[0].frequency.value == "daily"
    assert lt_q.facts[0].statistic.value is None
    assert lt_q.facts[0].time_zone.value is None
    assert lt_q.facts[0].clipping_axis is ClippingAxis.CALENDAR_DATE

    # Unestablished facts never satisfy concrete predicates
    assert not SeriesScope(predicates=(PhysicalPredicate(field="time_zone", value="UTC+01:00"),)).matches(owf_q)
    assert SeriesScope(predicates=(PhysicalPredicate(field="time_zone", value="UTC+01:00"),)).matches(bgis_q)
    assert not SeriesScope(predicates=(PhysicalPredicate(field="temporal_support", value="calendar_day"),)).matches(
        owf_q
    )
    assert SeriesScope(predicates=(PhysicalPredicate(field="temporal_support", value="calendar_month"),)).matches(
        owf_qmax
    )
    assert not SeriesScope(predicates=(PhysicalPredicate(field="statistic", value="mean"),)).matches(lt_q)
    assert SeriesScope(predicates=(PhysicalPredicate(field="statistic", value="mean"),)).matches(owf_q)


def test_catalogue_materialization_preserves_series_id_and_facts_id_agreement():
    from datetime import UTC, date, datetime

    from rivretrieve._internal.acquisition_provenance import (
        AcquisitionRecord,
        FactBinding,
        NativeTableIdentity,
        RecordingReference,
        SourceStatement,
    )
    from rivretrieve._internal.catalogues.native import RetrievedAt
    from rivretrieve._internal.providers.at_ehyd.origins import build_acquisition_provenance
    from tests.test_at_ehyd_catalogue import (
        _ehyd_owf_feature,
        _lfrz_feature,
        _pa_feature,
        _stammdaten_bytes,
        _zip_archive,
    )

    recording = RecordingReference(
        recording_id="synthetic",
        repository_path="sample.body",
        source_url="https://ehyd.gv.at/services/PegelAktuell/json",
        retrieved_at=datetime(2026, 10, 31, tzinfo=UTC),
        media_type="application/json",
        sha256="a" * 64,
    )
    facts = (
        "source.station.owf_registry",
        "source.station.owf_stammdaten",
        "source.station.pegel_aktuell_registry",
        "source.station.documented_crs",
        "source.station.pegelnullpunkt_definition",
        "source.station_product.owf_associations",
        "source.station_product.pegel_aktuell_associations",
        "source.product.owf_export_descriptors",
        "source.product.pegelordnung_temporal_rules",
        "source.product.pegel_aktuell_coordinates",
        "source.series.pegel_aktuell_fields",
        "source.product.pegel_aktuell_temporal_meaning",
        "source.provider.license",
        "source.provider.citation",
    )
    provenance = build_acquisition_provenance(
        NativeTableIdentity(
            location_kind="retained", repository_path="native.parquet", revision="a" * 40, sha256="b" * 64, byte_size=1
        ),
        (recording,),
        acquisitions=(
            AcquisitionRecord(
                acquisition_id="synthetic",
                method="http_request",
                instant_type="retrieval",
                description="Synthetic eHYD source",
                requested_from=(recording.source_url,),
                retrieved_at_start=recording.retrieved_at,
                recording_ids=("synthetic",),
            ),
        ),
        source_bindings=(
            FactBinding(fact_group="synthetic", facts=facts, source_id="at_ehyd", acquisition_id="synthetic"),
        ),
        statements=(
            SourceStatement(
                kind="license",
                exact_text="CC BY 4.0",
                recording_id="synthetic",
                fact="source.provider.license",
                verification_status="verified_public_recording",
            ),
            SourceStatement(
                kind="citation",
                exact_text="Datenquelle: ehyd.gv.at",
                recording_id="synthetic",
                fact="source.provider.citation",
                verification_status="verified_public_recording",
            ),
        ),
    )
    lfrz = {"features": [_lfrz_feature("209486"), _lfrz_feature("207340")]}
    ehyd_owf = {"features": [_ehyd_owf_feature("209486", []), _ehyd_owf_feature("207340", [])]}
    lfrz_pa = {"features": [_pa_feature(209486)]}
    zip_bytes = _zip_archive(
        {
            "Stammdaten/Stammdaten-209486.csv": _stammdaten_bytes("209486"),
            "Stammdaten/Stammdaten-207340.csv": _stammdaten_bytes("207340"),
        }
    )
    native = station_native_table(
        lfrz,
        ehyd_owf,
        lfrz_pa,
        zip_bytes,
        lfrz_pa=lfrz_pa,
        retrieved_at=RetrievedAt(datetime(2026, 10, 31, tzinfo=UTC)),
    )
    assocs = pl.DataFrame(
        [
            ("209486", "owf", "owf_wasserst_monatsminima", "cm"),
            ("207340", "owf", "owf_wasserst_monatsminima", "cm"),
            ("209486", "pegel_bgis", "Wasserstand", "cm"),
            ("209486", "pegel_longterm", "Wasserstand", "cm"),
        ],
        schema=ASSOCIATION_SCHEMA,
        orient="row",
    )
    products, stations, pairs = catalogue_tables(native, assocs, checked_on=date(2026, 10, 31))
    descriptions = describe_associations(assocs)
    artifact = packaged_catalogue_artifact_from_components(
        {
            "provider_id": "at_ehyd",
            "name": "Electronic Hydrographic Data Austria (eHYD)",
            "live_stations": False,
            "live_products": False,
            "live_station_products": False,
            "bulk_observations": "none",
            "catalogue_version": "2026-10-31",
            "license": "CC BY 4.0",
            "citation": "Datenquelle: ehyd.gv.at",
        },
        products,
        stations,
        pairs,
        acquisition_provenance=provenance,
        source_descriptions=descriptions,
    )
    materialized, _ = catalogue_series(artifact)
    by_pair = {(item.station_id, item.product_id): item for item in materialized}
    assert set(by_pair) == {
        ("209486", "owf_wasserst_monatsminima"),
        ("207340", "owf_wasserst_monatsminima"),
        ("209486", "pegel_bgis_wasserstand"),
        ("209486", "pegel_longterm_wasserstand"),
    }
    for station, subsystem, variable, unit in assocs.iter_rows():
        direct = source_series(station, subsystem, variable, units=(unit,), origin="catalogue")
        from_artifact = by_pair[(station, direct.product_id)]
        assert from_artifact.series_id == direct.series_id
        assert from_artifact.series_id == stable_id(
            "at_ehyd", station, direct.identity.namespace, direct.identity.published_id
        )
        assert from_artifact.facts == direct.facts
