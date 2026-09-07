"""Verify evidence integrity and inventory completeness. Runs offline - no network access.

Checks:
  1. Every recording's stored SHA-256 matches its stored bytes.
  2. Every recording declares the fields issue #224 requires.
  3. No recording URL carries a credential-like parameter.
  4. The inventory covers every baseline station exactly once per product, with no omitted rows.
  5. Every status is drawn from the declared vocabulary and none claims "unsupported".
  6. Availability is never asserted from HTTP status alone.
  7. Availability is never taken from catalogue metadata (the snapshot disagrees for 19 stations).
  8. Every station empty on the 7-day window carries a 90-day basis.
"""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import sys

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = pathlib.Path(__file__).resolve().parents[3].parent
NATIVE = ROOT / "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet"
VOCABULARY = {"available", "empty_in_tested_window", "access_failed", "uninvestigated"}
REQUIRED = ("status_code", "content_type", "retrieved_at", "content_base64", "sha256")

failures: list[str] = []
checks = 0


def check(condition: bool, label: str) -> None:
    global checks
    checks += 1
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        failures.append(label)


def main() -> None:
    print("1-3. recording integrity")
    recordings = sorted((HERE / "recordings").glob("*.recording.json"))
    documents = {path: json.loads(path.read_text()) for path in recordings}
    bad = [
        path.name
        for path, doc in documents.items()
        if hashlib.sha256(base64.b64decode(doc["response"]["content_base64"])).hexdigest() != doc["response"]["sha256"]
    ]
    check(not bad, f"all {len(recordings)} recordings hash-match their stored bytes {bad or ''}")
    missing = [
        path.name
        for path, doc in documents.items()
        if any(field not in doc["response"] for field in REQUIRED) or "url" not in doc["request"]
    ]
    check(not missing, f"all recordings carry url, status, media type, instant, bytes, sha256 {missing or ''}")
    secret = [
        path.name
        for path, doc in documents.items()
        if any(token in json.dumps(doc["request"]).lower() for token in ("token", "password", "apikey", "api_key"))
    ]
    check(not secret, f"no recording request carries a credential-like parameter {secret or ''}")

    print("\n4-8. inventory completeness")
    inventory = pd.read_csv(HERE / "inventory" / "station_product_evidence.csv", dtype=str)
    baseline = set(pd.read_parquet(NATIVE)["station.id"].astype(str))
    check(len(inventory) == len(baseline) * 2, f"inventory has {len(inventory)} rows = {len(baseline)} stations x 2")
    check(set(inventory.station_id) == baseline, f"all {len(baseline)} baseline stations accounted for")
    check(not inventory.duplicated(["station_id", "product_id"]).any(), "no station x product pair appears twice")
    check(set(inventory.status) <= VOCABULARY, f"statuses within vocabulary: {sorted(set(inventory.status))}")
    check(not inventory.status.eq("unsupported").any(), "no row claims a measurement is 'unsupported'")

    ok200 = inventory[inventory.http_status == "200"]
    check(
        len(set(ok200.status)) > 1,
        "HTTP 200 alone does not imply available (200 rows carry both available and empty statuses)",
    )
    available = inventory[inventory.status == "available"]
    counts = pd.to_numeric(available.nonnull_observations, errors="coerce")
    check(bool(counts.gt(0).all()), f"all {len(available)} available rows cite at least one non-null observation")
    empty = inventory[inventory.status == "empty_in_tested_window"]
    empty_counts = pd.to_numeric(empty.nonnull_observations, errors="coerce")
    check(bool(empty_counts.eq(0).all()), f"all {len(empty)} empty rows cite zero non-null observations")
    check(
        bool((empty.window_start == "2026-06-08").all()),
        f"all {len(empty)} empty rows rest on the 90-day window, not the 7-day one",
    )
    check(
        bool(available.evidence_basis.str.contains("graph route published").all()),
        "every available row cites the graph route, never catalogue metadata",
    )

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("FAILURES:", *failures, sep="\n  - ")
        sys.exit(1)
    print("evidence integrity and inventory completeness verified")


if __name__ == "__main__":
    main()
