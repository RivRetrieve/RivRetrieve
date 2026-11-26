"""Source-independent tests for nl_rws series identity, physical facts, missing values, and annotations."""

from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.nl_rws.annotations import NL_RWS_OBSERVATION_SCHEMA
from rivretrieve._internal.providers.nl_rws.series import (
    PRODUCT_DEFINITIONS,
    is_missing_observation_value,
    parse_tijdstip_offset,
    resolve_response_series,
)
from rivretrieve._internal.source_annotations import (
    OBSERVATION_STRUCTURAL_SCHEMA,
    AnnotationScope,
    ObservationAnnotationTable,
)
from rivretrieve._internal.source_series import ClippingAxis, EvidenceState, admission


def _aquo_meta(
    *,
    comp: str = "OW",
    g: str = "Q",
    e: str = "m3/s",
    h: str = "NVT",
    pt: str = "meting",
    wbw: str = "NVT",
    wbp: str = "other:F216",
    grp: str = "",
) -> dict[str, object]:
    return {
        "Compartiment": {"Code": comp},
        "Grootheid": {"Code": g},
        "Eenheid": {"Code": e},
        "Hoedanigheid": {"Code": h},
        "ProcesType": pt,
        "WaardeBewerkingsMethode": {"Code": wbw},
        "WaardeBepalingsMethode": {"Code": wbp},
        "Groepering": {"Code": grp},
    }


def test_all_ten_admitted_products_pass_admission_with_exact_conversions() -> None:
    assert len(PRODUCT_DEFINITIONS) == 10
    for definition in PRODUCT_DEFINITIONS:
        series = resolve_response_series(
            station_id="lobith.bovenrijn.tolkamer",
            aquo_metadata=_aquo_meta(
                g=definition.grootheid,
                e=definition.eenheid,
                h=definition.hoedanigheid,
                wbw=definition.waarde_bewerkings_methode,
                wbp="other:F007",
            ),
            offsets=("+01:00",),
        )
        assert series is not None
        assert len(series.facts) == 1
        facts = series.facts[0]
        adm = admission(facts)
        assert adm.status == "supported", f"{definition.product_id} failed admission: {adm}"
        assert adm.target_unit == definition.canonical_unit
        if definition.eenheid == "m3/d":
            assert adm.factor == pytest.approx(1.0 / 86400.0)
        elif definition.eenheid == "cm":
            assert adm.factor == pytest.approx(0.01)
        else:
            assert adm.factor == pytest.approx(1.0)
        assert facts.clipping_axis is ClippingAxis.SOURCE_TIMESTAMP
        assert facts.time_zone.value == "+01:00"
        if definition.waarde_bewerkings_methode == "GEM24H":
            assert facts.frequency.value == "P1D"
            assert facts.statistic.value == "mean"
            assert facts.timestamp_anchor.state is EvidenceState.NOT_ESTABLISHED
            assert facts.day_definition.state is EvidenceState.NOT_ESTABLISHED
        else:
            assert facts.frequency.state is EvidenceState.NOT_ESTABLISHED
            assert facts.statistic.state is EvidenceState.NOT_ESTABLISHED
        if definition.hoedanigheid in {"NAP", "MSL", "TAW"}:
            assert facts.vertical_reference.value == "above_sea_level"
            assert facts.vertical_datum.value == definition.hoedanigheid
        elif definition.hoedanigheid == "PLAATSLR":
            assert facts.vertical_reference.state is EvidenceState.NOT_ESTABLISHED
            assert facts.vertical_datum.value == "PLAATSLR"


def test_parallel_waarde_bepalings_methode_series_stay_distinct() -> None:
    f216 = resolve_response_series(
        station_id="lobith.bovenrijn.tolkamer",
        aquo_metadata=_aquo_meta(wbp="other:F216", wbw="NVT"),
        offsets=("+01:00",),
    )
    f230 = resolve_response_series(
        station_id="lobith.bovenrijn.tolkamer",
        aquo_metadata=_aquo_meta(wbp="other:F230", wbw="NVT"),
        offsets=("+01:00",),
    )
    gem24h = resolve_response_series(
        station_id="lobith.bovenrijn.tolkamer",
        aquo_metadata=_aquo_meta(wbp="other:F006", wbw="GEM24H"),
        offsets=("+01:00",),
    )
    assert f216 is not None and f230 is not None and gem24h is not None
    assert f216.product_id == "discharge_m3s_nvt"
    assert f230.product_id == "discharge_m3s_nvt"
    assert gem24h.product_id == "discharge_m3s_gem24h"
    assert f216.variant == "other:F216"
    assert f230.variant == "other:F230"
    assert f216.identity.published_id == "other:F216"
    assert f216.identity.origin == "response"
    assert f216.series_id != f230.series_id
    assert f216.series_id != gem24h.series_id


def test_unadmitted_metadata_returns_none_and_missing_method_raises() -> None:
    assert (
        resolve_response_series(
            station_id="lobith.bovenrijn.tolkamer",
            aquo_metadata=_aquo_meta(pt="verwachting"),
            offsets=("+01:00",),
        )
        is None
    )
    assert (
        resolve_response_series(
            station_id="lobith.bovenrijn.tolkamer",
            aquo_metadata=_aquo_meta(g="WATHTE", e="cm", h="NAP", pt="astronomisch"),
            offsets=("+01:00",),
        )
        is None
    )
    assert (
        resolve_response_series(
            station_id="lobith.bovenrijn.tolkamer",
            aquo_metadata=_aquo_meta(g="WATHTE", e="cm", h="NAP", grp="GETETM2"),
            offsets=("+01:00",),
        )
        is None
    )
    assert (
        resolve_response_series(
            station_id="delden.sluis.boven",
            aquo_metadata=_aquo_meta(g="Q", e="m3/d", wbw="SOM"),
            offsets=("+01:00",),
        )
        is None
    )
    assert (
        resolve_response_series(
            station_id="lobith.bovenrijn.tolkamer",
            aquo_metadata=_aquo_meta(comp="LT", g="T", e="oC"),
            offsets=("+01:00",),
        )
        is None
    )

    with pytest.raises(FatalContractError, match="WaardeBepalingsMethode"):
        resolve_response_series(
            station_id="lobith.bovenrijn.tolkamer",
            aquo_metadata=_aquo_meta(wbp=""),
            offsets=("+01:00",),
        )


def test_offset_parsing_and_mixed_offset_fact_segments() -> None:
    dt, offset = parse_tijdstip_offset("2020-03-29T02:30:00.000+01:00")
    assert dt == datetime(2020, 3, 29, 2, 30, 0)
    assert offset == "+01:00"

    mixed = resolve_response_series(
        station_id="lobith.bovenrijn.tolkamer",
        aquo_metadata=_aquo_meta(wbp="other:F230"),
        offsets=("+01:00", "+02:00", "+01:00"),
    )
    assert mixed is not None
    assert [f.time_zone.value for f in mixed.facts] == ["+01:00", "+02:00"]
    assert mixed.facts[0].facts_id != mixed.facts[1].facts_id


def test_missing_value_sentinel_classification() -> None:
    # Missing slots -> True
    assert is_missing_observation_value(9.99999e37, ".999999E+38", "99") is True
    assert is_missing_observation_value(9.99999e37, None, "00") is True
    assert is_missing_observation_value(12.3, "12.3", "99") is True
    assert is_missing_observation_value(None, None, "00") is True
    assert is_missing_observation_value(0.0, ".999999E+38", "00") is True
    # Valid physical readings -> False
    assert is_missing_observation_value(0.0, "0", "00") is False
    assert is_missing_observation_value(-27.0, "-27", "00") is False
    assert is_missing_observation_value(-0.5, "-0.5", "25") is False
    assert is_missing_observation_value(4242.07, "4242.07", "00") is False


def test_nl_rws_observation_annotation_schema_and_linked_null_row() -> None:
    assert NL_RWS_OBSERVATION_SCHEMA.schema_id == "nl_rws.observation"
    assert NL_RWS_OBSERVATION_SCHEMA.provider_id == "nl_rws"
    assert NL_RWS_OBSERVATION_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert tuple(f.name for f in NL_RWS_OBSERVATION_SCHEMA.fields) == (
        "statuswaarde",
        "kwaliteitswaardecode",
    )
    for field in NL_RWS_OBSERVATION_SCHEMA.fields:
        assert field.dtype == "String"
        assert field.reference_url.startswith("https://")

    # Verify linked published-null annotation row (measured=True, measurement_index=0)
    rows_df = pl.DataFrame(
        [
            {
                "series_id": "s1",
                "facts_id": "f1",
                "station_id": "lobith.bovenrijn.tolkamer",
                "product_id": "discharge_m3s_nvt",
                "time": datetime(2020, 1, 1, 2, 30, 0),
                "time_zone": "+01:00",
                "measured": True,
                "statuswaarde": "Ongecontroleerd",
                "kwaliteitswaardecode": "99",
            }
        ],
        schema={**OBSERVATION_STRUCTURAL_SCHEMA, **NL_RWS_OBSERVATION_SCHEMA.polars_schema()},
    )
    table = ObservationAnnotationTable.from_rows(
        schema=NL_RWS_OBSERVATION_SCHEMA,
        rows=rows_df,
        measurement_indices=(0,),
    )
    assert len(table.rows) == 1
    assert table.rows["kwaliteitswaardecode"].to_list() == ["99"]
    assert table.rows["measured"].to_list() == [True]
