import hashlib
import json
import traceback
from pathlib import Path

import rivretrieve as rr

out = Path(__file__).parent / "live-products"
out.mkdir(exist_ok=True)
cases = [
    ("fr_hubeau", "1011000101", "discharge", "daily", "mean", "2025-01-03", "2025-01-03"),
    ("fr_hubeau", "1011000101", "discharge", "daily", "max", "2025-01-03", "2025-01-03"),
    ("fr_hubeau", "1011000101", "stage", "daily", "max", "2025-01-03", "2025-01-03"),
    ("fr_hubeau", "01001336", "temperature", None, None, "2008-07-09", "2008-07-10"),
    ("fr_hydroportail", "1232000101", "discharge", None, "instantaneous", "2026-06-01", "2026-06-02"),
    ("fr_hydroportail", "Y251002001", "stage", None, "instantaneous", "2020-01-01", "2020-01-02"),
]
results = []
for provider, station, quantity, frequency, statistic, start, end in cases:
    name = "-".join([provider, station, quantity, statistic or "reported"])
    entry = {
        "provider": provider,
        "station": station,
        "quantity": quantity,
        "frequency": frequency,
        "statistic": statistic,
        "start": start,
        "end": end,
    }
    try:
        selection = rr.find(
            provider=provider, station=station, quantity=quantity, frequency=frequency, statistic=statistic
        )
        result = rr.fetch(selection, start=start, end=end, receipts=True, cache="bypass", on_issue="ignore")
        entry.update(
            rows=result.data.height,
            issues=[issue.model_dump(mode="json") for issue in result.issues],
            units=result.data["unit"].unique().to_list(),
            source_units=result.data["source_unit"].unique().to_list(),
            time_zones=result.data["time_zone"].unique().to_list(),
            first=None if result.data.is_empty() else str(result.data["time"].min()),
            last=None if result.data.is_empty() else str(result.data["time"].max()),
            definitions=[item.model_dump(mode="json") for item in result.source_series],
            calls=list(result.provenance.calls_made),
            receipts=[],
        )
        for index, receipt in enumerate(result.receipts.entries):
            path = out / f"{name}-{index}.body"
            path.write_bytes(receipt.content)
            entry["receipts"].append(
                {
                    "path": path.name,
                    "bytes": len(receipt.content),
                    "sha256": hashlib.sha256(receipt.content).hexdigest(),
                }
            )
    except Exception:
        entry["error"] = traceback.format_exc()
    results.append(entry)
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str) + "\n")
    print(name, entry.get("rows"), entry.get("issues", entry.get("error")), flush=True)
