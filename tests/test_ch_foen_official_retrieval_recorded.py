"""Parser replay of retained original responses; not an exact fetch-request replay."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import polars.testing as pt
import pytest

from rivretrieve._internal.engine import (
    Payload,
    SourceCallOrigin,
    SourceCoordinates,
    SourceQuery,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.ch_foen.official_config import OfficialRoute, config
from rivretrieve._internal.providers.ch_foen.official_parse import parse
from rivretrieve._internal.providers.ch_foen.official_series import product_id

_SCOPE = "maintenance/observations/ch_foen/official-retrieval"


@pytest.mark.recorded(_SCOPE)
def test_original_responses_match_independent_rows_facts_and_outcomes(retained_evidence_root: Path):
    root = retained_evidence_root / _SCOPE
    expectations = json.loads((root / "expectations.json").read_text())
    for case in expectations["cases"]:
        receipt = json.loads((root / f"{case['name']}.receipt.json").read_text())
        start = datetime.fromisoformat(case["requested_start"]).replace(tzinfo=None)
        stop = datetime.fromisoformat(case["requested_stop"]).replace(tzinfo=None)
        payload = Payload(
            SourceCoordinates(OfficialRoute(case["route"], case["parameter"])),
            ((case["station"], ProductId(product_id(case["route"], case["parameter"]))),),
            _make_fetch_window(
                WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(stop - timedelta(microseconds=1))
            ),
            (root / f"{case['name']}.body").read_bytes(),
            SourceCallOrigin(
                receipt["url"],
                {},
                receipt["status"],
                datetime.fromisoformat(receipt["acquired"]),
                "application/json",
                UnknownOriginFact(),
                SourceQuery(receipt["query"], ()),
            ),
            (),
        )
        parsed = parse(payload, config())
        names = {definition.series_id: definition.variant for definition in parsed.series}
        actual = pl.DataFrame(
            [
                {
                    "name": names[row["series_id"]],
                    "time": row["time"],
                    "unit": row["source_unit"],
                    "value": row["value"],
                }
                for row in parsed.rows.iter_rows(named=True)
            ],
            schema={"name": pl.String, "time": pl.Datetime, "unit": pl.String, "value": pl.Float64},
        )
        expected = pl.DataFrame(
            [
                {
                    "name": row["tsName"],
                    "time": datetime.fromisoformat(row["timestamp"]).replace(tzinfo=None),
                    "unit": row["unitSymbol"],
                    "value": row["value"],
                }
                for row in case["expected_rows"]
            ],
            schema=actual.schema,
        )
        pt.assert_frame_equal(actual.sort(["name", "time"]), expected.sort(["name", "time"]))
        assert not any(outcome.status.value == "failed" for outcome in parsed.outcomes)
        if "expected_facts" in case:
            actual_facts = [
                {
                    "variant": definition.variant,
                    "quantity": fact.quantity.value,
                    "source_unit": fact.source_unit.value,
                    "normalized_unit": fact.normalized_unit,
                    "frequency": fact.frequency.value,
                    "temporal_support": fact.temporal_support.value,
                    "day_definition": fact.day_definition.value,
                    "time_zone": fact.time_zone.value,
                }
                for definition in parsed.series
                for fact in definition.facts
            ]
            assert sorted(actual_facts, key=lambda item: (item["variant"] or "", item["source_unit"] or "")) == sorted(
                case["expected_facts"], key=lambda item: (item["variant"] or "", item["source_unit"] or "")
            )
        if "expected_outcomes" in case:
            actual_outcomes = [
                {"variant": names.get(outcome.series_id), "status": outcome.status.value, "coverage": outcome.coverage}
                for outcome in parsed.outcomes
            ]
            assert sorted(actual_outcomes, key=lambda item: (item["variant"] or "", item["status"])) == sorted(
                case["expected_outcomes"], key=lambda item: (item["variant"] or "", item["status"])
            )
