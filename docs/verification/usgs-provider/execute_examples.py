"""Execute exact candidate snippets, retain public receipts, and count offline series."""

import contextlib
import hashlib
import io
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import polars.testing as pt

import rivretrieve as rr

base = Path(__file__).parent
page = Path("docs/providers/usgs_nwis.md").read_text()
namespace = {}
outputs = []
saved = set()
for index, code in enumerate(re.findall(r"```python\n(.*?)```", page, re.S), 1):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(compile(code, f"usgs_nwis.md:snippet-{index}", "exec"), namespace)
    outputs.append({"snippet": index, "code": code, "stdout": out.getvalue()})
    print(out.getvalue(), flush=True)
    for name in ("result", "all_result", "chosen_result"):
        if name not in namespace or name in saved:
            continue
        result = namespace[name]
        saved.add(name)
        (base / f"{name}.bundle.zip").write_bytes(rr.to_bundle(result))
        selection_name, start, end = {
            "result": ("selection", "2024-01-01", "2024-01-07"),
            "all_result": ("alternatives", "2000-01-01", "2000-01-07"),
            "chosen_result": ("chosen", "2000-01-01", "2000-01-07"),
        }[name]
        recorded = rr.fetch(namespace[selection_name], start=start, end=end, cache="bypass", receipts=True)
        pt.assert_frame_equal(result.data, recorded.data)
        assert result.issues == recorded.issues
        assert result.source_series == recorded.source_series
        (base / f"{name}-with-receipts.bundle.zip").write_bytes(rr.to_bundle(recorded))
        for number, receipt in enumerate(recorded.receipts.entries):
            (base / f"{name}-receipt-{number}.json").write_bytes(receipt.content)
            (base / f"{name}-receipt-{number}-origin.json").write_text(
                json.dumps(
                    {
                        "url": receipt.origin.url,
                        "request_parameters": dict(receipt.origin.request_parameters),
                        "status_code": receipt.origin.status_code,
                        "retrieved_at": receipt.origin.retrieved_at.isoformat(),
                        "content_type": receipt.origin.content_type,
                        "sha256": hashlib.sha256(receipt.content).hexdigest(),
                    },
                    indent=2,
                )
            )
    (base / "execution.json").write_text(
        json.dumps(
            {
                "executed_utc": datetime.now(UTC).isoformat(),
                "page_sha256": hashlib.sha256(page.encode()).hexdigest(),
                "snippets": outputs,
            },
            indent=2,
        )
    )

frame = rr.series(rr.find(provider="usgs_nwis"))
groups = frame.group_by("station_id", "quantity", "frequency", "statistic").agg(
    pl.col("variant").n_unique().alias("series_count")
)
summary = (
    groups.group_by("quantity", "frequency", "statistic")
    .agg(
        pl.len().alias("stations"),
        (pl.col("series_count") > 1).sum().alias("stations_with_alternatives"),
    )
    .sort("quantity", "frequency", "statistic")
)
counts = {
    "concrete_series": frame["series_id"].n_unique(),
    "selectable_stations": frame["station_id"].n_unique(),
    "stations_with_alternatives": groups.filter(pl.col("series_count") > 1)["station_id"].n_unique(),
    "groups": summary.to_dicts(),
}
(base / "counts.json").write_text(json.dumps(counts, indent=2))
print(json.dumps(counts, indent=2))
