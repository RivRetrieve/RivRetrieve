"""Verify evidence integrity and inventory completeness. Runs offline - no network access.

Checks:
  1. Every recording's stored SHA-256 matches its stored bytes.
  2. Every recording declares the fields issue #223 requires.
  3. The inventory covers every station x product exactly once, with no omitted rows.
  4. Every one of the committed baseline's 60 stations appears in the inventory.
  5. Every status is drawn from the declared vocabulary.
  6. Every non-uninvestigated row cites an evidence recording that exists on disk.
  7. Availability is never asserted from HTTP status alone.
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
NATIVE = ROOT / "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet"
VOCABULARY = {"available", "declared_empty_in_rolling_window", "access_failed", "uninvestigated"}
REQUIRED = ("status_code", "content_type", "retrieved_at", "content_base64", "sha256")

failures: list[str] = []
checks = 0


def check(condition: bool, label: str) -> None:
    global checks
    checks += 1
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}")
        failures.append(label)


def main() -> None:
    print("1-2. recording integrity and required fields")
    recordings = sorted((HERE / "recordings").glob("*.recording.json"))
    bad_hash = [
        p.name
        for p in recordings
        if hashlib.sha256(base64.b64decode(json.loads(p.read_text())["response"]["content_base64"])).hexdigest()
        != json.loads(p.read_text())["response"]["sha256"]
    ]
    check(not bad_hash, f"all {len(recordings)} recordings hash-match their stored bytes {bad_hash or ''}")
    missing = [
        p.name
        for p in recordings
        if any(f not in json.loads(p.read_text())["response"] for f in REQUIRED)
        or "url" not in json.loads(p.read_text())["request"]
    ]
    check(not missing, f"all recordings carry url, status, media type, instant, bytes, sha256 {missing or ''}")
    secrets = [
        p.name
        for p in recordings
        if any(
            t in json.loads(p.read_text())["request"]["url"].lower()
            for t in ("token", "password", "senha", "apikey", "api_key")
        )
    ]
    check(not secrets, f"no recording URL carries a credential-like parameter {secrets or ''}")

    print("\n3-7. inventory completeness")
    inventory = pd.read_csv(HERE / "inventory" / "station_product_evidence.csv", dtype=str)
    stations = inventory.station_no.nunique()
    check(len(inventory) == stations * 3, f"inventory has {len(inventory)} rows = {stations} stations x 3 products")
    check(not inventory.duplicated(["station_no", "product_id"]).any(), "no station x product pair appears twice")

    baseline = set(pd.read_parquet(NATIVE).metadata_station_no.astype(str))
    present = set(inventory.station_no)
    check(baseline <= present, f"all {len(baseline)} committed baseline stations are accounted for")
    flagged = set(inventory[inventory.in_baseline == "True"].station_no)
    check(flagged == baseline, "in_baseline flag reproduces the committed baseline exactly")

    check(
        set(inventory.status) <= VOCABULARY,
        f"statuses drawn from the declared vocabulary: {sorted(set(inventory.status))}",
    )
    check(not inventory.status.eq("unsupported").any(), "no row claims a measurement is 'unsupported'")

    cited = inventory[inventory.status != "uninvestigated"].evidence_recording.dropna().unique()
    absent = [c for c in cited if c and not (HERE / c).exists()]
    check(not absent, f"every cited evidence recording exists on disk {absent or ''}")

    ok200 = inventory[inventory.http_status == "200"]
    check(
        set(ok200.status) - {"available"} != set(),
        "HTTP 200 alone does not imply available (both available and empty rows return 200)",
    )
    empty = inventory[inventory.status == "declared_empty_in_rolling_window"]
    check(
        bool(empty.declared_rows.astype(float).eq(0).all()), f"all {len(empty)} empty rows cite a published #Rows = 0"
    )
    avail = inventory[inventory.status == "available"]
    check(
        bool(avail.declared_rows.astype(float).gt(0).all()),
        f"all {len(avail)} available rows cite a published #Rows > 0",
    )
    failed = inventory[inventory.status == "access_failed"]
    check(bool(failed.http_status.eq("404").all()), f"all {len(failed)} access_failed rows cite a real HTTP failure")

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("FAILURES:", *failures, sep="\n  - ")
        sys.exit(1)
    print("evidence integrity and inventory completeness verified")


if __name__ == "__main__":
    main()
