"""Verify four ANA daily variants via public API against independent source expectations."""

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import polars as pl

import rivretrieve as rr
from rivretrieve._internal.discovery import _resolve_credentials


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expectations", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    expected = json.loads(args.expectations.read_text())["probes"]
    rr.providers()
    secrets = tuple(_resolve_credentials(("br_ana",), require_all=True)["br_ana"].values())
    groups = defaultdict(list)
    for product, probe in expected.items():
        groups[tuple(probe["window"])].append(product)
    audits = []
    passed = True
    for (start, end), products in groups.items():
        selection = rr.pick(rr.find(provider="br_ana", station="15400000"), product=products)
        result = rr.fetch(selection, start=start, end=end, receipts=True, on_issue="ignore")
        checks = {}
        for product in products:
            data = result.data.filter(pl.col("product_id") == product).sort("time")
            probe = expected[product]
            labels = [value.isoformat() for value in data["time"].to_list()]
            values = data["value"].to_list()
            source_values = [float(row["canonical_value"]) for row in probe["readings"]]
            ok = (
                data.height == probe["count"]
                and labels == [row["label"] for row in probe["readings"]]
                and len(values) == len(source_values)
                and all(
                    value is not None and math.isclose(value, source, rel_tol=1e-12, abs_tol=1e-12)
                    for value, source in zip(values, source_values, strict=True)
                )
                and data["time_zone"].to_list() == ["unknown"] * data.height
            )
            checks[product] = ok
            passed = passed and ok
        passed = passed and not any(issue.severity == "error" for issue in result.issues)
        audits.append(
            {
                "window": [start, end],
                "products": products,
                "checks": checks,
                "selection": rr.as_frame(selection).to_dicts(),
                "rows": result.data.to_dicts(),
                "issues": [{"severity": i.severity, "code": i.code, "message": i.message} for i in result.issues],
                "source_call_count": len(result.provenance.calls_made),
                "receipts": [
                    {"byte_count": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest()}
                    for r in result.receipts.entries
                ],
            }
        )
    encoded = json.dumps({"passed": passed, "audits": audits}, default=str, indent=2)
    if any(secret in encoded for secret in secrets):
        raise RuntimeError("unsafe audit output refused")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded + "\n")
    print(
        json.dumps(
            {
                "passed": passed,
                "checks": {key: value for audit in audits for key, value in audit["checks"].items()},
                "row_count": sum(len(audit["rows"]) for audit in audits),
            }
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    try:
        code = main()
    except Exception as error:
        print(json.dumps({"verification_failed_type": type(error).__name__}))
        code = 1
    raise SystemExit(code)
