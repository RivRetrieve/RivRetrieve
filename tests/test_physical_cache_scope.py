"""Public cache contract with authored mixed facts around a real publisher parser.

The second fact segment is an engine-contract control, not claimed agency evidence.
"""

from dataclasses import replace
from pathlib import Path

import polars as pl
import polars.testing as pt
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.source_series import known
from tests.usgs_modern_recordings import ModernReplay

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def test_precise_refresh_preserves_same_series_sibling_fact_rows(monkeypatch, tmp_path, retained_evidence_root: Path):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    broad = rr.find(provider="usgs_nwis", station="07374000", quantity="discharge")
    # Select an established daily frequency while leaving statistics unrestricted.
    broad = rr.pick(broad, frequency="daily")
    handle = discovery._provider_lookup("usgs_nwis")
    stages = handle._stages

    class TwoSegments:
        config = stages.config
        window_declarations = stages.window_declarations
        fetch = staticmethod(stages.fetch)

        @staticmethod
        def parse(payload, config):
            parsed = stages.parse(payload, config)
            original = parsed.series[0]
            fact = original.facts[0]
            second = fact.model_copy(
                update={
                    "facts_id": fact.facts_id + "/authored-instantaneous",
                    "statistic": known("instantaneous", "authored engine-contract source segment"),
                }
            )
            definition = original.model_copy(update={"facts": (fact, second)})
            extra = parsed.rows.with_columns(
                pl.lit(second.facts_id).alias("facts_id"), (pl.col("value") * 2).alias("value")
            )
            return replace(
                parsed,
                series=(definition,),
                rows=pl.concat([parsed.rows, extra]),
                outcomes=tuple(
                    item.model_copy(
                        update={
                            "facts_ids": (fact.facts_id, second.facts_id),
                            "outcome_id": item.outcome_id + "/two-facts",
                        }
                    )
                    for item in parsed.outcomes
                ),
            )

    lookup = discovery._provider_lookup
    monkeypatch.setattr(
        discovery,
        "_provider_lookup",
        lambda provider: (
            replace(lookup(provider), _stages=TwoSegments()) if provider == "usgs_nwis" else lookup(provider)
        ),
    )
    replay = ModernReplay("daily-07374000-docs-2023", evidence_root=retained_evidence_root)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    def fetch(selection, cache):
        return rr.fetch(selection, start="2023-01-01", end="2023-01-01", cache=cache, on_issue="ignore")

    baseline = fetch(broad, "bypass")
    assert baseline.data.height == 2
    held = fetch(broad, "reuse")
    precise = rr.pick(broad, statistic="mean")
    expected = rr.pick(baseline, statistic="mean")
    pt.assert_frame_equal(fetch(precise, "reuse").data, expected.data)
    pt.assert_frame_equal(fetch(precise, "refresh").data, expected.data)
    after = fetch(broad, "reuse")
    pt.assert_frame_equal(after.data.sort("facts_id"), held.data.sort("facts_id"))
