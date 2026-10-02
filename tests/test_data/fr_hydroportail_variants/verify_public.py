"""Independent live check; run with uv run python from the implementation checkout."""

import argparse
import hashlib
import json
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path

import rivretrieve as rr

parser = argparse.ArgumentParser()
parser.add_argument("--offline", action="store_true")
parser.add_argument("--out-dir", type=Path, required=True)
parser.add_argument("--evidence-dir", type=Path, required=True)
args = parser.parse_args()
if args.offline:
    import rivretrieve._internal.discovery as discovery
    from rivretrieve._internal.recordings import ReplayTransport

    replay = ReplayTransport(args.evidence_dir.glob("Y251002001_*_padded_*.recording.json"))
    discovery.HttpClient = lambda: replay
OUT = args.out_dir.resolve()
if any((parent / ".git").exists() for parent in (OUT, *OUT.parents)):
    parser.error("Output must be outside source checkouts")
if OUT.is_relative_to(args.evidence_dir.resolve()):
    parser.error("Output must be separate from retained evidence")
OUT.mkdir(parents=True, exist_ok=False)
VARIANTS = {"raw", "validated", "pre_validated_and_validated", "most_valid"}
summary = []
selections = {
    quantity: rr.find(provider="fr_hydroportail", station="Y251002001", quantity=quantity, statistic="instantaneous")
    for quantity in ("discharge", "stage")
}
assert sum(rr.series(s).height for s in selections.values()) == 8
for quantity, selection in selections.items():
    assert set(rr.series(selection)["variant"]) == VARIANTS
    metric = "Q" if quantity == "discharge" else "H"
    for variant in ["all", *sorted(VARIANTS)]:
        chosen = selection if variant == "all" else rr.pick(selection, variant=variant)
        result = rr.fetch(chosen, start="2020-01-01", end="2020-01-02", cache="bypass", receipts=True)
        name = f"{quantity}_{variant}"
        expected = VARIANTS if variant == "all" else {variant}
        provenance = result.provenance.model_dump(mode="json")
        (OUT / f"{name}.provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
        assert all(
            issue.severity == "info"
            and issue.code in {"provenance.license_not_established", "provenance.citation_not_established"}
            for issue in result.issues
        ), result.issues
        assert set(rr.series(result)["variant"]) == expected
        calls = provenance["calls_made"]
        assert len(calls) == len(expected)
        assert {c["request_parameters"]["hydro_series[statusData]"] for c in calls} == expected
        assert all(
            c["request_parameters"]["hydro_series[simpleAndInterpolatedAndHourlyVariable]"] == metric for c in calls
        )
        assert all(
            c["request_parameters"]["hydro_series[startAt]"] == "30/12/2019"
            and c["request_parameters"]["hydro_series[endAt]"] == "04/01/2020"
            for c in calls
        )
        assert len(result.receipts.entries) == len(expected)
        receipts = []
        for i, entry in enumerate(result.receipts.entries):
            doc = json.loads(entry.content)
            series = doc["series"]
            assert series["statuses"] in expected and series["metric"] == metric and series["code"] == "Y251002001"
            filename = f"{name}.{i}.receipt.body"
            (OUT / filename).write_bytes(entry.content)
            receipts.append(
                {
                    "file": filename,
                    "sha256": hashlib.sha256(entry.content).hexdigest(),
                    "origin": {
                        field.name: (dict(value) if field.name == "request_parameters" else str(value))
                        for field in fields(entry.origin)
                        for value in [getattr(entry.origin, field.name)]
                    },
                    "authorship": entry.authorship.value,
                    "rows": len(series["data"]),
                }
            )
        (OUT / f"{name}.receipts.json").write_text(json.dumps(receipts, default=str, indent=2) + "\n")
        result.data.write_parquet(OUT / f"{name}.data.parquet")
        inspected = rr.series(result)
        inspected.write_parquet(OUT / f"{name}.series.parquet")
        expected_rows = 726 if variant == "all" else (576 if variant == "raw" else 50)
        assert result.data.height == expected_rows, (name, result.data.height)
        item = {
            "quantity": quantity,
            "selection": variant,
            "rows": result.data.height,
            "calls": len(calls),
            "requested_selectors": sorted(expected),
            "issues": len(result.issues),
            "verified_at": datetime.now(UTC).isoformat(),
        }
        summary.append(item)
        (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(item), flush=True)
print(
    "PASS: 10 public fetches, 16 actual source calls; all/explicit Q/H source selectors and receipt envelopes verified.",
    flush=True,
)
