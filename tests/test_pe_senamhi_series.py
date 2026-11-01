"""Synthetic controls for SENAMHI published field identity and physical unknowns."""

import polars as pl

from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import ASSOCIATION_SCHEMA, describe_associations


def test_phisis_daily_fields_and_hourly_value_have_distinct_identities():
    associations = pl.DataFrame(
        [
            ("A", "phisis", resolution, variable, unit)
            for resolution in ("DAILY", "HOURLY")
            for variable, unit in (("FLOW", "m3/s"), ("LEVEL", "m"), ("LEVEL", "m.s.n.m"))
        ],
        schema=ASSOCIATION_SCHEMA,
        orient="row",
    )
    descriptions = describe_associations(associations).descriptions
    assert len(descriptions) == 12
    assert len({(item.identity.namespace, item.identity.published_id) for item in descriptions}) == 12
    daily = [item for item in descriptions if item.product_id == "phisis_daily_flow"]
    assert {item.identity.published_id for item in daily} == {"current", "minimum", "maximum"}
    hourly = [item for item in descriptions if item.product_id == "phisis_hourly_flow"]
    assert [item.identity.published_id for item in hourly] == ["value"]


def test_monthly_fields_stay_distinct_from_each_other_and_monitoring():
    fields = (
        "NIVEL_DEL_RIO_06H",
        "NIVEL_DEL_RIO_10H",
        "NIVEL_DEL_RIO_14H",
        "NIVEL_DEL_RIO_18H",
        "NIVEL_DEL_RIO_PROMEDIO",
        "N_NIVELAGUA",
        "N_NIVELMEDIO",
        "N_NIV_INST_00",
        "N_NIV_INST_10",
    )
    associations = pl.DataFrame(
        [("A", "monthly_archive", None, field, "m") for field in fields] + [("A", "phisis", "DAILY", "LEVEL", "m")],
        schema=ASSOCIATION_SCHEMA,
        orient="row",
    )
    descriptions = describe_associations(associations).descriptions
    assert len(descriptions) == 12
    monthly = [item for item in descriptions if item.product_id.startswith("monthly_archive_")]
    assert {item.identity.published_id for item in monthly} == set(fields)
    assert len({(item.identity.namespace, item.identity.published_id) for item in descriptions}) == 12


def test_mapped_facts_admit_numeric_values_without_inventing_time_or_datum():
    from rivretrieve._internal.providers.pe_senamhi.series import series_mappings
    from rivretrieve._internal.source_series import EvidenceState, PhysicalPredicate, SeriesScope, admission

    for subsystem, resolution, variable, unit, quantity, reference in (
        ("phisis", "DAILY", "FLOW", "m3/s", "discharge", None),
        ("phisis", "DAILY", "LEVEL", "m", "stage", None),
        ("phisis", "DAILY", "LEVEL", "m.s.n.m", "stage", "above_sea_level"),
        ("phisis", "HOURLY", "LEVEL", "m", "stage", None),
        ("monthly_archive", None, "NIVEL_DEL_RIO_PROMEDIO", "m", "stage", None),
        ("monthly_archive", None, "N_NIV_INST_00", "m", "stage", None),
    ):
        for mapping in series_mappings(subsystem, resolution, variable, unit).values():
            facts = mapping.physical_facts()
            assert facts.quantity.value == quantity
            assert facts.source_unit.value == unit
            assert facts.vertical_reference.value == reference
            decision = admission(facts)
            assert (decision.status, decision.target_unit, decision.factor) == (
                "supported",
                "m3/s" if variable == "FLOW" else "m",
                1.0,
            )
            for field, unsupported in (
                ("frequency", "daily"),
                ("statistic", "mean"),
                ("temporal_support", "day"),
                ("day_definition", "calendar_day"),
                ("timestamp_anchor", "start"),
                ("time_zone", "America/Lima"),
                ("vertical_datum", "WGS84"),
            ):
                fact = getattr(facts, field)
                assert fact.state is EvidenceState.NOT_ESTABLISHED
                assert fact.value is None
                assert not SeriesScope(predicates=(PhysicalPredicate(field=field, value=unsupported),)).matches_facts(
                    facts
                )
            assert facts.label_time is None
            assert facts.clipping_axis.value == "source_timestamp"
            assert not SeriesScope(
                predicates=(PhysicalPredicate(field="vertical_reference", value="relative"),)
            ).matches_facts(facts)


def test_catalogue_and_future_parser_use_the_same_series_identity():
    from datetime import date
    from types import SimpleNamespace

    from rivretrieve._internal.catalogues.source_series import materialize_series
    from rivretrieve._internal.providers.pe_senamhi.series import series_mappings

    associations = pl.DataFrame(
        [("A", "phisis", "DAILY", "FLOW", "m3/s")],
        schema=ASSOCIATION_SCHEMA,
        orient="row",
    )
    artifact = SimpleNamespace(
        provider_info={"provider_id": "pe_senamhi"},
        source_descriptions=describe_associations(associations),
        catalogue_claims=None,
        station_products=pl.DataFrame(
            {
                "station_id": ["A"],
                "product_id": ["phisis_daily_flow"],
                "availability": ["available"],
                "last_catalogue_check": [date(2026, 1, 1)],
            }
        ),
    )
    discovered, inventories = materialize_series(artifact)
    mapped = tuple(
        mapping.source_series("pe_senamhi", "A", "phisis_daily_flow")
        for mapping in series_mappings("phisis", "DAILY", "FLOW", "m3/s").values()
    )
    assert discovered == mapped
    assert len(set(inventories[0].members)) == 3
