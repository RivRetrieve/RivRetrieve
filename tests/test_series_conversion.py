from datetime import datetime

import polars as pl
import pytest

from rivretrieve._internal.conversion import convert
from rivretrieve._internal.engine import RequestedWindow, RowsSchema, WindowEndpoint
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.usgs_nwis.config import config
from rivretrieve._internal.source_series import PhysicalFacts, SourceIdentity, SourceSeries, known


@pytest.mark.parametrize("normalized_unit", ["m", "m3/s"])
def test_conversion_refuses_dimensionally_incompatible_series_facts(normalized_unit):
    facts = PhysicalFacts(
        facts_id="contradiction",
        quantity=known("discharge", "test source definition"),
        source_unit=known("m", "test response unit"),
        normalized_unit=normalized_unit,
    )
    series = SourceSeries(
        series_id="series",
        provider_id="usgs_nwis",
        station_id="07374000",
        product_id="discharge_daily_mean",
        identity=SourceIdentity(namespace="methodID", published_id="1", origin="response", evidence=("test response",)),
        facts=(facts,),
    )
    rows = pl.DataFrame(
        [
            {
                "station_id": "07374000",
                "product_id": "discharge_daily_mean",
                "time": datetime(2023, 1, 1),
                "value": 1.0,
                "time_zone": "unknown",
                "series_id": "series",
                "facts_id": "contradiction",
                "source_unit": "m",
            }
        ],
        schema=RowsSchema.polars_schema,
    )
    window = RequestedWindow(
        WindowEndpoint.from_datetime(datetime(2023, 1, 1)), WindowEndpoint.from_datetime(datetime(2023, 1, 2))
    )
    with pytest.raises(FatalContractError, match="admitted"):
        convert(rows, config(), window, series=(series,))


def test_conversion_refuses_conflicting_fact_identity_across_series():
    def definition(sid, unit):
        return SourceSeries(
            series_id=sid,
            provider_id="usgs_nwis",
            station_id="07374000",
            product_id="discharge_daily_mean",
            identity=SourceIdentity(namespace="methodID", published_id=sid, origin="response", evidence=("source",)),
            facts=(
                PhysicalFacts(
                    facts_id="shared",
                    quantity=known("discharge", "source"),
                    source_unit=known(unit, "source"),
                    normalized_unit=unit,
                ),
            ),
        )

    definitions = (definition("a", "m3/s"), definition("b", "ft3/s"))
    rows = pl.DataFrame(
        [
            {
                "station_id": "07374000",
                "product_id": "discharge_daily_mean",
                "time": datetime(2023, 1, 1),
                "value": 1.0,
                "time_zone": "unknown",
                "series_id": "a",
                "facts_id": "shared",
                "source_unit": "m3/s",
            }
        ],
        schema=RowsSchema.polars_schema,
    )
    window = RequestedWindow(
        WindowEndpoint.from_datetime(datetime(2023, 1, 1)), WindowEndpoint.from_datetime(datetime(2023, 1, 2))
    )
    with pytest.raises(FatalContractError, match="fact.*identity|facts.*identity"):
        convert(rows, config(), window, series=definitions)


def test_active_explicit_scope_cannot_omit_its_identity_restriction():
    from rivretrieve._internal.source_series import RestrictionKind, SeriesScope

    with pytest.raises(ValueError, match="explicit.*restriction"):
        SeriesScope(restriction=RestrictionKind.EXPLICIT)


def test_inventory_fact_membership_cannot_reference_an_absent_series():
    from rivretrieve._internal.source_series import InventoryCompleteness, InventorySnapshot, SeriesScope

    with pytest.raises(ValueError, match="fact.*member"):
        InventorySnapshot(
            snapshot_id="snapshot",
            scope=SeriesScope(),
            members=("known",),
            member_facts=(("absent", ("fact",)),),
            completeness=InventoryCompleteness.COMPLETE,
            access="recorded scope",
            origin="response",
            evidence=("source",),
        )
