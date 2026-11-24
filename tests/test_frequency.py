from __future__ import annotations

import datetime as dt

import pandas as pd
import polars as pl
import pytest

from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.catalogues.artifact import (
    CorruptCatalogArtifactError,
    packaged_catalogue_artifact_from_components,
)
from rivretrieve._internal.catalogues.source_descriptions import generic_source_descriptions
from rivretrieve._internal.frequency import (
    DAILY,
    MONTHLY,
    Frequency,
    FrequencyFamily,
    FrequencyUnit,
    canonicalize_frequency,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.provider_series import SeriesMapping
from rivretrieve._internal.selection import _intersect_scope, _selection_scope
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceFact,
    EvidenceState,
    PhysicalFacts,
    PhysicalPredicate,
    ScopeState,
    known,
    stable_id,
)


def _minimal_artifact_inputs(
    *, frequency: str = "P1D"
) -> tuple[dict[str, object], pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    provider_info: dict[str, object] = {
        "provider_id": "synthetic",
        "name": "Synthetic Provider",
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "none",
        "catalogue_version": "2026.01",
        "license": None,
        "citation": None,
    }
    products = pl.DataFrame(
        [
            {
                "provider_id": "synthetic",
                "product_id": "flow",
                "observed_property": "discharge",
                "frequency": frequency,
                "statistic": "mean",
                "period_type": "unknown",
                "period_anchor": "unknown",
                "unit": "m3/s",
                "native_id": "FLOW",
            }
        ],
        schema={
            "provider_id": pl.Utf8,
            "product_id": pl.Utf8,
            "observed_property": pl.Utf8,
            "frequency": pl.Utf8,
            "statistic": pl.Utf8,
            "period_type": pl.Utf8,
            "period_anchor": pl.Utf8,
            "unit": pl.Utf8,
            "native_id": pl.Utf8,
        },
    )
    stations = pl.DataFrame(
        [
            {
                "provider_id": "synthetic",
                "station_id": "s1",
                "latitude": 46.2,
                "longitude": 7.1,
                "crs": "unknown",
            }
        ],
        schema={
            "provider_id": pl.Utf8,
            "station_id": pl.Utf8,
            "latitude": pl.Float64,
            "longitude": pl.Float64,
            "crs": pl.Utf8,
        },
    )
    station_products = pl.DataFrame(
        [
            {
                "provider_id": "synthetic",
                "station_id": "s1",
                "product_id": "flow",
                "availability": "unknown",
                "availability_reason": "not_catalogued",
                "published_record_start_date": None,
                "published_record_end_date": None,
                "last_catalogue_check": dt.date(2026, 1, 1),
            }
        ],
        schema={
            "provider_id": pl.Utf8,
            "station_id": pl.Utf8,
            "product_id": pl.Utf8,
            "availability": pl.Utf8,
            "availability_reason": pl.Utf8,
            "published_record_start_date": pl.Date,
            "published_record_end_date": pl.Date,
            "last_catalogue_check": pl.Date,
        },
    )
    return provider_info, products, stations, station_products


def _facts_with_frequency(
    frequency: EvidenceFact,
    *,
    clipping_axis: ClippingAxis = ClippingAxis.SOURCE_TIMESTAMP,
) -> PhysicalFacts:
    facts = PhysicalFacts(
        facts_id="unidentified",
        quantity=known("stage", "https://example.org/spec"),
        source_unit=known("m", "https://example.org/spec"),
        normalized_unit="m",
        frequency=frequency,
        clipping_axis=clipping_axis,
    )
    return facts.model_copy(update={"facts_id": stable_id(facts.model_dump_json(exclude={"facts_id"}))})


@pytest.mark.parametrize(
    ("raw", "expected_family", "expected_value", "expected_unit", "expected_canonical"),
    [
        ("PT1S", FrequencyFamily.ELAPSED, 1, FrequencyUnit.SECONDS, "PT1S"),
        ("PT30S", FrequencyFamily.ELAPSED, 30, FrequencyUnit.SECONDS, "PT30S"),
        ("PT90S", FrequencyFamily.ELAPSED, 90, FrequencyUnit.SECONDS, "PT90S"),
        ("PT1M30S", FrequencyFamily.ELAPSED, 90, FrequencyUnit.SECONDS, "PT90S"),
        ("PT60S", FrequencyFamily.ELAPSED, 1, FrequencyUnit.MINUTES, "PT1M"),
        ("PT10M", FrequencyFamily.ELAPSED, 10, FrequencyUnit.MINUTES, "PT10M"),
        ("PT3600S", FrequencyFamily.ELAPSED, 1, FrequencyUnit.HOURS, "PT1H"),
        ("PT60M", FrequencyFamily.ELAPSED, 1, FrequencyUnit.HOURS, "PT1H"),
        ("PT1H", FrequencyFamily.ELAPSED, 1, FrequencyUnit.HOURS, "PT1H"),
        ("PT1H30M", FrequencyFamily.ELAPSED, 90, FrequencyUnit.MINUTES, "PT90M"),
        ("PT90M", FrequencyFamily.ELAPSED, 90, FrequencyUnit.MINUTES, "PT90M"),
        ("PT4H", FrequencyFamily.ELAPSED, 4, FrequencyUnit.HOURS, "PT4H"),
        ("PT24H", FrequencyFamily.ELAPSED, 24, FrequencyUnit.HOURS, "PT24H"),
        ("PT1440M", FrequencyFamily.ELAPSED, 24, FrequencyUnit.HOURS, "PT24H"),
        ("PT168H", FrequencyFamily.ELAPSED, 168, FrequencyUnit.HOURS, "PT168H"),
        ("P1D", FrequencyFamily.CALENDAR_DAYS, 1, FrequencyUnit.DAYS, "P1D"),
        ("P7D", FrequencyFamily.CALENDAR_DAYS, 1, FrequencyUnit.WEEKS, "P1W"),
        ("P1W", FrequencyFamily.CALENDAR_DAYS, 1, FrequencyUnit.WEEKS, "P1W"),
        ("P1W2D", FrequencyFamily.CALENDAR_DAYS, 9, FrequencyUnit.DAYS, "P9D"),
        ("P9D", FrequencyFamily.CALENDAR_DAYS, 9, FrequencyUnit.DAYS, "P9D"),
        ("P14D", FrequencyFamily.CALENDAR_DAYS, 2, FrequencyUnit.WEEKS, "P2W"),
        ("P365D", FrequencyFamily.CALENDAR_DAYS, 365, FrequencyUnit.DAYS, "P365D"),
        ("P1M", FrequencyFamily.CALENDAR_MONTHS, 1, FrequencyUnit.MONTHS, "P1M"),
        ("P12M", FrequencyFamily.CALENDAR_MONTHS, 1, FrequencyUnit.YEARS, "P1Y"),
        ("P1Y", FrequencyFamily.CALENDAR_MONTHS, 1, FrequencyUnit.YEARS, "P1Y"),
        ("P1Y6M", FrequencyFamily.CALENDAR_MONTHS, 18, FrequencyUnit.MONTHS, "P18M"),
        ("P18M", FrequencyFamily.CALENDAR_MONTHS, 18, FrequencyUnit.MONTHS, "P18M"),
        ("P24M", FrequencyFamily.CALENDAR_MONTHS, 2, FrequencyUnit.YEARS, "P2Y"),
    ],
)
def test_frequency_parse_and_canonicalize(
    raw: str,
    expected_family: FrequencyFamily,
    expected_value: int,
    expected_unit: FrequencyUnit,
    expected_canonical: str,
) -> None:
    parsed = Frequency.parse(raw)
    assert parsed.family is expected_family
    assert parsed.value == expected_value
    assert parsed.unit is expected_unit
    assert parsed.canonical == expected_canonical
    assert str(parsed) == expected_canonical
    assert canonicalize_frequency(raw) == expected_canonical


def test_frequency_preserves_distinct_families_and_enum_members() -> None:
    assert FrequencyUnit.MINUTES is not FrequencyUnit.MONTHS
    assert Frequency.parse("P1D") != Frequency.parse("PT24H")
    assert Frequency.parse("P1W") != Frequency.parse("PT168H")
    assert Frequency.parse("P1Y") != Frequency.parse("P365D")
    assert Frequency.parse("P1D") == DAILY
    assert Frequency.parse("P1M") == MONTHLY


def test_frequency_equivalence_and_hashing() -> None:
    assert Frequency.parse("PT60M") == Frequency.parse("PT1H")
    assert Frequency.parse("PT3600S") == Frequency.parse("PT1H")
    assert Frequency.parse("P7D") == Frequency.parse("P1W")
    assert Frequency.parse("P12M") == Frequency.parse("P1Y")
    assert hash(Frequency.parse("P7D")) == hash(Frequency.parse("P1W"))


@pytest.mark.parametrize(
    "raw",
    [
        "",
        " ",
        "daily",
        "hourly",
        "monthly",
        "yearly",
        "10min",
        "unknown",
        "P",
        "PT",
        "PT0S",
        "P0D",
        "P0W",
        "P0M",
        "P0Y",
        "-P1D",
        "+P1D",
        "-PT1H",
        "p1d",
        "PT1h",
        " P1D",
        "P1D ",
        "P1D\n",
        "PT1\nH",
        "PT\u0661H",
        "PT0.5H",
        "PT1,5H",
        "P1.5D",
        "P1DT1H",
        "P1Y1D",
        "P1M1W",
        "P1M1D",
        "P1Y1W",
        "PT1S1M",
        "P1D1W",
        "P1M1Y",
        "PT1M1H",
        dt.timedelta(days=1),
        pd.Timedelta("1D"),
        1,
        True,
        None,
    ],
)
def test_frequency_rejects_invalid_and_unsupported_inputs(raw: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        Frequency.parse(raw)
    with pytest.raises((TypeError, ValueError)):
        canonicalize_frequency(raw)


def test_frequency_constructor_enforces_invariants() -> None:
    with pytest.raises(ValueError):
        Frequency(
            family=FrequencyFamily.ELAPSED,
            value=0,
            unit=FrequencyUnit.HOURS,
            canonical="PT0H",
        )
    with pytest.raises(ValueError):
        Frequency(
            family=FrequencyFamily.ELAPSED,
            value=True,  # type: ignore[arg-type]
            unit=FrequencyUnit.HOURS,
            canonical="PT1H",
        )
    with pytest.raises(ValueError):
        Frequency(
            family=FrequencyFamily.ELAPSED,
            value=60,
            unit=FrequencyUnit.MINUTES,
            canonical="PT60M",
        )
    with pytest.raises(ValueError):
        Frequency(
            family=FrequencyFamily.CALENDAR_DAYS,
            value=7,
            unit=FrequencyUnit.DAYS,
            canonical="P1W",
        )
    with pytest.raises(ValueError):
        Frequency(
            family=FrequencyFamily.CALENDAR_MONTHS,
            value=1,
            unit=FrequencyUnit.DAYS,
            canonical="P1D",
        )
    with pytest.raises(ValueError):
        Frequency(
            family=FrequencyFamily.CALENDAR_MONTHS,
            value=1,
            unit=FrequencyUnit.MINUTES,
            canonical="P1M",
        )
    with pytest.raises(ValueError):
        Frequency(
            family=FrequencyFamily.ELAPSED,
            value=1,
            unit=FrequencyUnit.MONTHS,
            canonical="PT1M",
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PT60M", "PT1H"),
        ("PT1H30M", "PT90M"),
        ("P7D", "P1W"),
        ("P1W2D", "P9D"),
        ("P12M", "P1Y"),
        ("P1Y6M", "P18M"),
    ],
)
def test_physical_facts_canonicalizes_frequency_and_preserves_evidence(raw: str, expected: str) -> None:
    evidence = "https://example.org/spec"
    facts = _facts_with_frequency(known(raw, evidence))
    assert facts.frequency == EvidenceFact(value=expected, state=EvidenceState.KNOWN, evidence=(evidence,))


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("PT60M", "PT1H"),
        ("P7D", "P1W"),
        ("P12M", "P1Y"),
    ],
)
def test_physical_facts_equivalent_frequencies_share_facts_id(left: str, right: str) -> None:
    left_facts = _facts_with_frequency(known(left, "https://example.org/spec"))
    right_facts = _facts_with_frequency(known(right, "https://example.org/spec"))
    assert left_facts.facts_id == right_facts.facts_id


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("P1D", "PT24H"),
        ("P1W", "PT168H"),
        ("P1Y", "P365D"),
    ],
)
def test_physical_facts_preserves_distinct_families_in_facts_id(left: str, right: str) -> None:
    left_facts = _facts_with_frequency(known(left, "https://example.org/spec"))
    right_facts = _facts_with_frequency(known(right, "https://example.org/spec"))
    assert left_facts.facts_id != right_facts.facts_id


@pytest.mark.parametrize(
    "bad_frequency",
    ["daily", "10min", "unknown", "PT0S", "P1DT1H", "publisher-specific-cadence"],
)
def test_physical_facts_rejects_non_canonical_or_legacy_frequency(bad_frequency: str) -> None:
    with pytest.raises(ValueError):
        _facts_with_frequency(known(bad_frequency, "https://example.org/spec"))


def test_physical_facts_preserves_unknown_frequency_states() -> None:
    silent = _facts_with_frequency(EvidenceFact(state=EvidenceState.SOURCE_SILENT))
    unestablished = _facts_with_frequency(EvidenceFact(state=EvidenceState.NOT_ESTABLISHED))
    assert silent.frequency.state is EvidenceState.SOURCE_SILENT
    assert silent.frequency.value is None
    assert unestablished.frequency.state is EvidenceState.NOT_ESTABLISHED
    assert unestablished.frequency.value is None


def test_clipping_axis_requires_canonical_calendar_frequencies() -> None:
    assert _facts_with_frequency(known("P1D", "ev"), clipping_axis=ClippingAxis.CALENDAR_DATE).clipping_axis is (
        ClippingAxis.CALENDAR_DATE
    )
    assert _facts_with_frequency(known("P1M", "ev"), clipping_axis=ClippingAxis.CALENDAR_MONTH).clipping_axis is (
        ClippingAxis.CALENDAR_MONTH
    )

    for wrong_daily in ("PT24H", "P1W", "PT1H"):
        with pytest.raises(ValueError):
            _facts_with_frequency(known(wrong_daily, "ev"), clipping_axis=ClippingAxis.CALENDAR_DATE)
    with pytest.raises(ValueError):
        _facts_with_frequency(
            EvidenceFact(state=EvidenceState.NOT_ESTABLISHED), clipping_axis=ClippingAxis.CALENDAR_DATE
        )

    for wrong_monthly in ("P30D", "P1Y"):
        with pytest.raises(ValueError):
            _facts_with_frequency(known(wrong_monthly, "ev"), clipping_axis=ClippingAxis.CALENDAR_MONTH)
    with pytest.raises(ValueError):
        _facts_with_frequency(
            EvidenceFact(state=EvidenceState.SOURCE_SILENT), clipping_axis=ClippingAxis.CALENDAR_MONTH
        )


def test_physical_predicate_and_scope_canonicalize_and_intersect() -> None:
    assert PhysicalPredicate(field="frequency", value="PT60M").value == "PT1H"
    assert PhysicalPredicate(field="frequency", value="P7D").value == "P1W"
    assert PhysicalPredicate(field="frequency", value="P12M").value == "P1Y"

    scope_a = _selection_scope(frequency="PT60M")
    scope_b = _selection_scope(frequency="PT1H")
    assert scope_a == scope_b
    intersected_same = _intersect_scope(scope_a, scope_b)
    assert intersected_same.state is ScopeState.ACTIVE
    assert intersected_same.predicates == (PhysicalPredicate(field="frequency", value="PT1H"),)

    intersected_different = _intersect_scope(_selection_scope(frequency="P1D"), _selection_scope(frequency="PT24H"))
    assert intersected_different.state is ScopeState.EMPTY

    for bad_filter in (
        "daily",
        "irregular",
        "unknown",
        "PT0S",
        "-P1D",
        "PT1.5H",
        "P1DT1H",
        dt.timedelta(days=1),
        pd.Timedelta("1D"),
    ):
        with pytest.raises(ValueError):
            _selection_scope(frequency=bad_filter)  # type: ignore[arg-type]


def test_series_mapping_and_generic_descriptions_carry_canonical_frequency() -> None:
    mapping = SeriesMapping(
        namespace="test:series",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        frequency="PT60M",
        evidence=("https://example.org/series",),
    )
    facts = mapping.physical_facts()
    assert facts.frequency.value == "PT1H"
    assert facts.clipping_axis is ClippingAxis.SOURCE_TIMESTAMP

    daily_mapping = SeriesMapping(
        namespace="test:daily",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        frequency="P1D",
        evidence=("https://example.org/daily",),
    )
    assert daily_mapping.physical_facts().clipping_axis is ClippingAxis.CALENDAR_DATE

    products = pl.DataFrame(
        [
            {
                "provider_id": "synthetic",
                "product_id": "daily_flow",
                "observed_property": "discharge",
                "frequency": "P1D",
                "statistic": "mean",
                "period_type": "calendar_day",
                "period_anchor": "unknown",
                "unit": "m3/s",
                "native_id": "DAILY",
            },
            {
                "provider_id": "synthetic",
                "product_id": "hourly_flow",
                "observed_property": "discharge",
                "frequency": "PT1H",
                "statistic": "mean",
                "period_type": "instant",
                "period_anchor": "unknown",
                "unit": "m3/s",
                "native_id": "HOURLY",
            },
        ],
        schema={
            "provider_id": pl.Utf8,
            "product_id": pl.Utf8,
            "observed_property": pl.Utf8,
            "frequency": pl.Utf8,
            "statistic": pl.Utf8,
            "period_type": pl.Utf8,
            "period_anchor": pl.Utf8,
            "unit": pl.Utf8,
            "native_id": pl.Utf8,
        },
    )
    station_products = pl.DataFrame(
        [
            {
                "provider_id": "synthetic",
                "station_id": "s1",
                "product_id": "daily_flow",
                "availability": "unknown",
                "availability_reason": "not_catalogued",
                "published_record_start_date": None,
                "published_record_end_date": None,
                "last_catalogue_check": dt.date(2026, 1, 1),
            },
            {
                "provider_id": "synthetic",
                "station_id": "s1",
                "product_id": "hourly_flow",
                "availability": "unknown",
                "availability_reason": "not_catalogued",
                "published_record_start_date": None,
                "published_record_end_date": None,
                "last_catalogue_check": dt.date(2026, 1, 1),
            },
        ],
        schema={
            "provider_id": pl.Utf8,
            "station_id": pl.Utf8,
            "product_id": pl.Utf8,
            "availability": pl.Utf8,
            "availability_reason": pl.Utf8,
            "published_record_start_date": pl.Date,
            "published_record_end_date": pl.Date,
            "last_catalogue_check": pl.Date,
        },
    )
    provider_info, _, stations, _ = _minimal_artifact_inputs()
    artifact = packaged_catalogue_artifact_from_components(provider_info, products, stations, station_products)
    descriptions = generic_source_descriptions(
        artifact,
        None,
        mappings={
            "daily_flow": daily_mapping,
            "hourly_flow": mapping,
        },
    )
    by_product = {item.product_id: item.facts[0] for item in descriptions.descriptions}
    assert by_product["daily_flow"].frequency.value == "P1D"
    assert by_product["daily_flow"].clipping_axis is ClippingAxis.CALENDAR_DATE
    assert by_product["hourly_flow"].frequency.value == "PT1H"
    assert by_product["hourly_flow"].clipping_axis is ClippingAxis.SOURCE_TIMESTAMP


def test_packaged_artifact_and_reader_frequency_validation() -> None:
    for accepted in ("P1D", "PT4H", "P1W", "unknown"):
        provider_info, products, stations, station_products = _minimal_artifact_inputs(frequency=accepted)
        artifact = packaged_catalogue_artifact_from_components(provider_info, products, stations, station_products)
        assert artifact.products["frequency"].to_list() == [accepted]

    for rejected in ("daily", "hourly", "PT60M", "P7D", "P1DT1H", ""):
        provider_info, products, stations, station_products = _minimal_artifact_inputs(frequency=rejected)
        with pytest.raises(CorruptCatalogArtifactError):
            packaged_catalogue_artifact_from_components(provider_info, products, stations, station_products)

    weekly_inputs = _minimal_artifact_inputs(frequency="P1W")
    weekly_artifact = packaged_catalogue_artifact_from_components(*weekly_inputs)
    reader = CatalogueReader(artifact=weekly_artifact, provider_id=ProviderId("synthetic"))
    assert reader.read_products(frequency="P1W").data.height == 1
    assert reader.read_products(frequency="P7D").data.height == 1
    assert reader.read_products(frequency="unknown").data.height == 0

    with pytest.raises(ValueError):
        reader.read_products(frequency="daily")
    with pytest.raises(FatalContractError):
        reader.read_products(frequency=123)  # type: ignore[arg-type]


def test_part1_ar_ina_and_cz_chmi_end_to_end_discovery_and_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    import rivretrieve as rr
    import rivretrieve._internal.discovery as discovery
    from rivretrieve._internal.providers.registration import register_manifest
    from rivretrieve._internal.registry import _registry

    monkeypatch.setattr(
        discovery,
        "_ensure_default_providers_registered",
        lambda: register_manifest(_registry, ("ar_ina", "cz_chmi")) if not _registry.list_provider_ids() else None,
    )

    hm4h_sel = rr.find(provider="ar_ina", quantity="stage", frequency="PT4H")
    hm4h_alias_sel = rr.find(provider="ar_ina", quantity="stage", frequency="PT240M")
    assert hm4h_sel.series == hm4h_alias_sel.series
    assert len(hm4h_sel.series) == 391
    assert set(rr.series(hm4h_sel)["statistic"].to_list()) == {None}

    hms_sel = rr.find(provider="ar_ina", quantity="stage", frequency="P1W")
    hms_days_sel = rr.find(provider="ar_ina", quantity="stage", frequency="P7D")
    assert hms_sel.series == hms_days_sel.series
    assert len(hms_sel.series) == 32
    assert set(rr.series(hms_sel)["statistic"].to_list()) == {"mean"}
    assert len(rr.find(provider="ar_ina", quantity="stage", frequency="PT168H").series) == 0

    for inst_pid in ("discharge_instantaneous", "stage_instantaneous"):
        inst_rows = rr.series(rr.find(provider="ar_ina")).filter(pl.col("product_id") == inst_pid)
        assert inst_rows.height > 0
        assert set(inst_rows["frequency"].to_list()) == {None}
        assert set(inst_rows["frequency_state"].to_list()) == {"not_established"}

    cz_series = rr.find(provider="cz_chmi")
    cz_by_product = {
        s.product_id: s.facts[0] for s in cz_series.known_series if s.station_id == cz_series.known_series[0].station_id
    }
    assert cz_by_product["discharge_daily_mean"].frequency.value == "P1D"
    assert cz_by_product["discharge_daily_mean"].clipping_axis is ClippingAxis.CALENDAR_DATE
    assert cz_by_product["discharge_hourly_mean"].frequency.value == "PT1H"
    assert cz_by_product["discharge_hourly_mean"].clipping_axis is ClippingAxis.SOURCE_TIMESTAMP

    for provider_id in ("ar_ina", "cz_chmi"):
        broad = rr.find(provider=provider_id)
        frame = rr.series(broad)
        known_rows = frame.filter(pl.col("frequency").is_not_null())
        assert known_rows.height > 0
        seen_combinations: set[tuple[str | None, str | None, str | None]] = set()
        for row in known_rows.iter_rows(named=True):
            combo = (row["quantity"], row["frequency"], row["statistic"])
            if combo in seen_combinations:
                continue
            seen_combinations.add(combo)
            by_find = rr.find(
                provider=provider_id,
                quantity=row["quantity"],
                frequency=row["frequency"],
                statistic=row["statistic"],
            )
            by_pick = rr.pick(
                broad,
                quantity=row["quantity"],
                frequency=row["frequency"],
                statistic=row["statistic"],
            )
            assert by_find.series == by_pick.series
            assert len(by_find.series) > 0
            assert row["series_id"] in {s.series_id for s in by_find.series}
            assert set(rr.series(by_find)["frequency"].to_list()) == {row["frequency"]}

            station_find = rr.find(
                provider=provider_id,
                station=row["station_id"],
                quantity=row["quantity"],
                frequency=row["frequency"],
                statistic=row["statistic"],
            )
            station_pick = rr.pick(
                broad,
                station=row["station_id"],
                quantity=row["quantity"],
                frequency=row["frequency"],
                statistic=row["statistic"],
            )
            assert station_find.series == station_pick.series
            assert row["series_id"] in {s.series_id for s in station_find.series}


def test_observation_result_pick_canonicalizes_and_validates_frequency() -> None:
    from rivretrieve import pick
    from rivretrieve._internal.observations import ObservationProvenance, ObservationResult, Receipts
    from rivretrieve._internal.source_series import SourceIdentity, SourceSeries

    f_4h = _facts_with_frequency(known("PT4H", "ev"))
    f_1w = _facts_with_frequency(known("P1W", "ev"))
    s_4h = SourceSeries(
        series_id="s-4h",
        provider_id="ar_ina",
        station_id="st",
        product_id="stage_4hourly",
        identity=SourceIdentity(namespace="test", published_id="1", origin="mapping", evidence=("ev",)),
        facts=(f_4h,),
    )
    s_1w = SourceSeries(
        series_id="s-1w",
        provider_id="ar_ina",
        station_id="st",
        product_id="stage_weekly_mean",
        identity=SourceIdentity(namespace="test", published_id="2", origin="mapping", evidence=("ev",)),
        facts=(f_1w,),
    )
    rows = pl.DataFrame(
        [
            {
                "station_id": "st",
                "product_id": "stage_4hourly",
                "series_id": "s-4h",
                "facts_id": f_4h.facts_id,
                "time": dt.datetime(2024, 1, 1, 0, 0),
                "time_zone": "+00:00",
                "quantity": "stage",
                "value": 1.5,
                "unit": "m",
                "source_unit": "m",
            },
            {
                "station_id": "st",
                "product_id": "stage_weekly_mean",
                "series_id": "s-1w",
                "facts_id": f_1w.facts_id,
                "time": dt.datetime(2024, 1, 1, 0, 0),
                "time_zone": "+00:00",
                "quantity": "stage",
                "value": 2.5,
                "unit": "m",
                "source_unit": "m",
            },
        ]
    )
    result = ObservationResult(
        data=rows,
        provenance=ObservationProvenance(source="test", provider_id="ar_ina"),
        receipts=Receipts(provider_id="ar_ina"),
        source_series=(s_4h, s_1w),
        inventories=(),
        scope=_selection_scope(provider="ar_ina", station="st"),
    )

    assert pick(result, frequency="PT240M").data["series_id"].to_list() == ["s-4h"]
    assert pick(result, frequency="P7D").data["series_id"].to_list() == ["s-1w"]
    assert pick(result, frequency="PT168H").data.is_empty()
    with pytest.raises(ValueError):
        pick(result, frequency="daily")


def test_store_and_bundle_v11_v12_v5_join_canonical_facts_and_refuse_retired_versions(tmp_path) -> None:
    import hashlib
    import json
    from datetime import UTC, date, datetime
    from io import BytesIO
    from pathlib import Path
    from uuid import uuid4
    from zipfile import ZIP_DEFLATED, ZipFile

    import rivretrieve as rr
    from rivretrieve._internal.coverage import CoverageInterval, RequestedInterval
    from rivretrieve._internal.engine import RowsSchema
    from rivretrieve._internal.observations import ObservationProvenance, ObservationResult, Receipts
    from rivretrieve._internal.source_series import (
        OutcomeStatus,
        RetrievalOutcome,
        SeriesWindow,
        SourceIdentity,
        SourceSeries,
    )
    from rivretrieve._internal.store import (
        ArtifactChecksum,
        Disposition,
        NativeStoreMaterialization,
        ObservationStoreRefusedError,
        PublisherArtifact,
        SourceColumn,
        SourceColumnDisposition,
        SourceUnitCount,
        StoreCompileRequest,
        StoreQuery,
        StoreReader,
        StoreRoot,
        certify_store,
        validate_store,
    )
    from rivretrieve._internal.store.accumulation import StoreUpdate, SuccessfulReplacement, accumulate
    from rivretrieve._internal.store.integrity import seal_store

    f_4h = _facts_with_frequency(known("PT240M", "ev"))
    f_1w = _facts_with_frequency(known("P7D", "ev"))
    assert f_4h.frequency.value == "PT4H"
    assert f_1w.frequency.value == "P1W"
    assert f_4h.facts_id == _facts_with_frequency(known("PT4H", "ev")).facts_id
    assert f_1w.facts_id == _facts_with_frequency(known("P1W", "ev")).facts_id

    sid_4h = stable_id("fixture_live", "a", "level_4h")
    sid_1w = stable_id("fixture_live", "a", "level_1w")
    s_4h = SourceSeries(
        series_id=sid_4h,
        provider_id="fixture_live",
        station_id="a",
        product_id="level_4h",
        identity=SourceIdentity(namespace="test", published_id="1", origin="mapping", evidence=("ev",)),
        facts=(f_4h,),
    )
    s_1w = SourceSeries(
        series_id=sid_1w,
        provider_id="fixture_live",
        station_id="a",
        product_id="level_1w",
        identity=SourceIdentity(namespace="test", published_id="2", origin="mapping", evidence=("ev",)),
        facts=(f_1w,),
    )
    retrieved_at = datetime(2026, 9, 1, tzinfo=UTC)
    acc_store = StoreRoot(tmp_path / "accumulated")
    acc_rows = pl.DataFrame(
        {
            "station_id": ["a"],
            "product_id": ["level_4h"],
            "time": [datetime(2024, 1, 1, 0, 0)],
            "value": [1.5],
            "time_zone": ["+00:00"],
            "series_id": [sid_4h],
            "facts_id": [f_4h.facts_id],
            "source_unit": ["m"],
        },
        schema=RowsSchema.polars_schema,
    )
    interval = RequestedInterval(datetime(2024, 1, 1), datetime(2024, 1, 2))
    outcome = RetrievalOutcome(
        outcome_id=uuid4().hex,
        series_id=sid_4h,
        station_id="a",
        product_id="level_4h",
        window=SeriesWindow(start=interval.start, end=interval.end),
        status=OutcomeStatus.SUCCESS,
        facts_ids=(f_4h.facts_id,),
        retrieved_at=retrieved_at,
    )
    coverage = CoverageInterval(sid_4h, interval, retrieved_at, outcome.outcome_id)
    accumulate(
        acc_store,
        ProviderId("fixture_live"),
        StoreUpdate((s_4h,), (), (outcome,), (SuccessfulReplacement(coverage, acc_rows),)),
    )
    seal_store(acc_store, ProviderId("fixture_live"))
    validated_acc = validate_store(acc_store, ProviderId("fixture_live"))
    assert validated_acc.manifest.format_version == 11
    acc_read = StoreReader().query(
        StoreQuery(acc_store, ProviderId("fixture_live"), ("a",), ("level_4h",), interval.start, interval.end)
    )
    assert acc_read.rows["facts_id"].to_list() == [f_4h.facts_id]

    retired_acc_manifest = json.loads((Path(acc_store) / "manifest.json").read_text())
    retired_acc_manifest["format_version"] = 9
    (Path(acc_store) / "manifest.json").write_text(json.dumps(retired_acc_manifest))
    with pytest.raises(ObservationStoreRefusedError, match="unsupported format revision 9"):
        validate_store(acc_store, ProviderId("fixture_live"))

    # Compiled store v12 join + v10 refusal
    artifact = Path(tmp_path / "publisher.zip")
    artifact.write_bytes(b"fixture")
    digest = ArtifactChecksum(f"sha256:{hashlib.sha256(artifact.read_bytes()).hexdigest()}")
    bulk_sid = stable_id("fixture_bulk", "station-1", "stage")
    bulk_series = SourceSeries(
        series_id=bulk_sid,
        provider_id="fixture_bulk",
        station_id="station-1",
        product_id="stage",
        identity=SourceIdentity(namespace="test", published_id="b", origin="mapping", evidence=("ev",)),
        facts=(f_4h,),
    )
    columns = (SourceColumn("raw_value", "text"),)
    dispositions = (
        SourceColumnDisposition("raw_value", Disposition.RETAINED, reconstruction_rule=None, rationale=None),
    )
    comp_store = StoreRoot(tmp_path / "compiled")
    request = StoreCompileRequest(
        destination=comp_store,
        provider_id=ProviderId("fixture_bulk"),
        compiler_version="0.1.0",
        built_at=datetime(2026, 8, 11, tzinfo=UTC),
        source_vintage=date(2024, 12, 31),
        publisher_artifact=PublisherArtifact("https://example.test/publisher.zip", digest),
        source_columns=columns,
        source_column_dispositions=dispositions,
        series=(bulk_series,),
    )
    decoded = pl.DataFrame(
        {
            "product": ["stage"],
            "station_id": ["station-1"],
            "time": [datetime(2024, 1, 2)],
            "time_zone": ["UTC"],
            "value": [2.0],
            "value_state": ["published_value"],
            "series_id": [bulk_sid],
            "facts_id": [f_4h.facts_id],
            "source_unit": ["m"],
            "raw_value": ["2.0"],
        },
        schema={
            "product": pl.String,
            "station_id": pl.String,
            "time": pl.Datetime("us"),
            "time_zone": pl.String,
            "value": pl.Float64,
            "value_state": pl.String,
            "series_id": pl.String,
            "facts_id": pl.String,
            "source_unit": pl.String,
            "raw_value": pl.String,
        },
    )
    certified = certify_store(
        request, artifact, lambda _p: NativeStoreMaterialization(decoded, columns, (SourceUnitCount("2024.csv", 1, 1),))
    )
    assert certified.manifest.format_version == 12
    comp_read = StoreReader().query(
        StoreQuery(
            comp_store,
            ProviderId("fixture_bulk"),
            ("station-1",),
            ("stage",),
            datetime(2024, 1, 1),
            datetime(2024, 1, 3),
        )
    )
    assert comp_read.rows["facts_id"].to_list() == [f_4h.facts_id]

    retired_comp_manifest = json.loads((Path(comp_store) / "manifest.json").read_text())
    retired_comp_manifest["format_version"] = 10
    (Path(comp_store) / "manifest.json").write_text(json.dumps(retired_comp_manifest))
    with pytest.raises(ObservationStoreRefusedError, match="unsupported format revision 10"):
        validate_store(comp_store, ProviderId("fixture_bulk"))

    # Export bundle v5 round-trip + v4 refusal
    obs = ObservationResult(
        data=pl.DataFrame(
            [
                {
                    "station_id": "a",
                    "product_id": "level_4h",
                    "series_id": sid_4h,
                    "facts_id": f_4h.facts_id,
                    "time": dt.datetime(2024, 1, 1, 0, 0),
                    "time_zone": "+00:00",
                    "quantity": "stage",
                    "value": 1.5,
                    "unit": "m",
                    "source_unit": "m",
                },
                {
                    "station_id": "a",
                    "product_id": "level_1w",
                    "series_id": sid_1w,
                    "facts_id": f_1w.facts_id,
                    "time": dt.datetime(2024, 1, 1, 0, 0),
                    "time_zone": "+00:00",
                    "quantity": "stage",
                    "value": 2.5,
                    "unit": "m",
                    "source_unit": "m",
                },
            ]
        ),
        provenance=ObservationProvenance(source="test", provider_id="fixture_live"),
        receipts=Receipts(provider_id="fixture_live"),
        source_series=(s_4h, s_1w),
        inventories=(),
        scope=_selection_scope(provider="fixture_live", station="a"),
    )
    bundle_bytes = rr.to_bundle(obs)
    with ZipFile(BytesIO(bundle_bytes)) as archive:
        assert json.loads(archive.read("manifest.json"))["version"] == 5
    restored = rr.from_bundle(bundle_bytes)
    assert rr.pick(restored, frequency="PT240M").data["facts_id"].to_list() == [f_4h.facts_id]
    assert rr.pick(restored, frequency="P7D").data["facts_id"].to_list() == [f_1w.facts_id]
    assert rr.pick(restored, frequency="PT168H").data.is_empty()

    retired_bundle = BytesIO()
    with ZipFile(BytesIO(bundle_bytes)) as src_zip, ZipFile(retired_bundle, "w", compression=ZIP_DEFLATED) as dst_zip:
        for info in src_zip.infolist():
            data = src_zip.read(info.filename)
            if info.filename == "manifest.json":
                doc = json.loads(data)
                doc["version"] = 4
                data = json.dumps(doc).encode("utf-8")
            dst_zip.writestr(info.filename, data)
    with pytest.raises(ValueError, match="Unsupported source-series bundle format version"):
        rr.from_bundle(retired_bundle.getvalue())


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_cross_provider_packaged_catalogues_canonical_and_round_trip() -> None:
    import rivretrieve as rr
    from rivretrieve._internal.frequency import Frequency
    from tests._catalogue import catalogue_reader

    providers = rr.providers()["provider_id"].to_list()
    assert len(providers) == 20
    aliases = {
        "PT10M": "PT600S",
        "PT1H": "PT60M",
        "PT4H": "PT240M",
        "P1W": "P7D",
        "P1Y": "P12M",
    }
    disjoint = {
        "P1D": "PT24H",
        "P1W": "PT168H",
        "P1Y": "P365D",
    }
    seen_frequencies: set[str] = set()
    for provider_id in providers:
        selection = rr.find(provider=provider_id)
        series_df = rr.series(selection)
        assert not series_df.is_empty()
        frequencies = {value for value in series_df["frequency"].to_list() if value is not None}
        for freq in frequencies:
            assert str(Frequency.parse(freq)) == freq
            found = rr.find(provider=provider_id, frequency=freq)
            picked = rr.pick(selection, frequency=freq)
            assert not rr.series(found).is_empty()
            assert set(rr.series(found)["frequency"].to_list()) == {freq}
            assert rr.series(found)["series_id"].to_list() == rr.series(picked)["series_id"].to_list()
            if alias := aliases.get(freq):
                assert rr.find(provider=provider_id, frequency=alias).series == found.series
                assert rr.pick(selection, frequency=alias).series == picked.series
            if cross := disjoint.get(freq):
                assert freq not in set(rr.series(rr.pick(selection, frequency=cross))["frequency"].to_list())
            seen_frequencies.add(freq)

    za_reader = catalogue_reader("za_dws")
    za_freqs = {val for val in za_reader.read_products().data["frequency"].to_list() if val != "unknown"}
    for freq in za_freqs:
        assert str(Frequency.parse(freq)) == freq
    assert not za_reader.read_products(frequency="P1D").data.is_empty()
    assert za_reader.read_products(frequency="PT24H").data.is_empty()
    seen_frequencies |= za_freqs
    assert {"PT10M", "PT1H", "PT4H", "P1D", "P1W", "P1M", "P1Y"} <= seen_frequencies
