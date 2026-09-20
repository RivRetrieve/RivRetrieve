"""Execute the French guide against exact saved public source exchanges.

This checks examples and printed outputs offline, not current source availability.
"""

import io
import re
from contextlib import redirect_stdout
from pathlib import Path

import polars as pl
from polars.testing import assert_frame_equal

import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.recordings import ReplayTransport

ROOT = Path(__file__).resolve().parents[1]


def test_french_page_examples_and_displayed_outputs(monkeypatch, tmp_path):
    page = (ROOT / "docs/providers/fr_hubeau.md").read_text()
    blocks = re.findall(r"```python\n(.*?)```\n\nOutput:\n\n```text\n(.*?)```", page, re.DOTALL)
    assert len(blocks) == page.count("```python") == 3
    replay = ReplayTransport(
        [
            ROOT / "tests/test_data/fr_hubeau_Y251002001_daily_january2024.recording.json",
            ROOT / "tests/test_data/fr_hydroportail_H_padded.recording.json",
        ]
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    monkeypatch.chdir(tmp_path)
    namespace = {}
    for index, (code, expected) in enumerate(blocks, 1):
        output = io.StringIO()
        with redirect_stdout(output):
            exec(compile(code, f"fr_hubeau.md:block-{index}", "exec"), namespace)
        assert output.getvalue() == expected, index
    assert not namespace["result"].issues
    assert not namespace["instantaneous"].issues
    assert namespace["instantaneous"].receipts.entries


def test_french_page_catalogue_counts():
    page = (ROOT / "docs/providers/fr_hubeau.md").read_text()
    labels = {
        "Daily mean discharge": "discharge_daily_mean",
        "Daily maximum discharge": "discharge_daily_max",
        "Daily maximum stage": "stage_daily_max",
        "Instantaneous discharge": "discharge_instantaneous",
        "Instantaneous stage": "stage_instantaneous",
        "Reported water temperature": "water_temperature_reported",
    }
    table = re.findall(r"^\| ([^|]+) \| ([0-9,]+) \| ([0-9,]+) \|$", page, re.MULTILINE)
    displayed = pl.DataFrame(
        [
            (labels[label], int(positive.replace(",", "")), int(listed.replace(",", "")))
            for label, positive, listed in table
        ],
        schema={"product_id": pl.String, "positive": pl.Int64, "listed": pl.Int64},
        orient="row",
    ).sort("product_id")
    catalogue = ROOT / "src/rivretrieve/_internal/providers/fr_hubeau/catalogue"
    actual = (
        pl.read_parquet(catalogue / "station_products.parquet")
        .group_by("product_id")
        .agg(
            (pl.col("availability") == "available").sum().cast(pl.Int64).alias("positive"),
            pl.len().cast(pl.Int64).alias("listed"),
        )
        .sort("product_id")
    )
    assert_frame_equal(displayed, actual)
    station_count = pl.read_parquet(catalogue / "stations.parquet").height
    assert f"| Stations in the catalogue | {station_count:,} locations;" in page
