"""Verify evidence integrity and inventory completeness. Runs offline - no network access."""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import sys

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = pathlib.Path(__file__).resolve().parents[3].parent
NATIVE = ROOT / "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet"
VOCABULARY = {
    "available",
    "empty_no_data_published",
    "empty_in_tested_window",
    "uninvestigated",
    "access_failed",
}
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
    print("recording integrity")
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

    print("\ninventory completeness")
    inventory = pd.read_csv(HERE / "inventory" / "station_product_evidence.csv", dtype=str)
    native = pd.read_parquet(NATIVE)
    baseline = set(native.code_station.astype(str))
    hydro = int((native.source_endpoint == "hydrometrie/referentiel/stations").sum())
    temperature = int((native.source_endpoint == "temperature/station").sum())
    expected = hydro * 5 + temperature

    check(len(inventory) == expected, f"inventory has {len(inventory)} rows = {hydro}x5 + {temperature}")
    check(set(inventory.code_station) == baseline, f"all {len(baseline)} baseline stations accounted for")
    check(not inventory.duplicated(["code_station", "product_id"]).any(), "no station x product pair appears twice")
    check(set(inventory.status) <= VOCABULARY, f"statuses within vocabulary: {sorted(set(inventory.status))}")
    check(not inventory.status.eq("unsupported").any(), "no row claims a measurement is 'unsupported'")

    available = inventory[inventory.status == "available"]
    counts = pd.to_numeric(available.observations, errors="coerce")
    check(bool(counts.gt(0).all()), f"all {len(available)} available rows cite at least one observation")

    whole = inventory[inventory.status == "empty_no_data_published"]
    check(
        bool(whole.window.eq("whole record (no date filter)").all()),
        f"all {len(whole)} 'none published' rows rest on a whole-record total, not a window",
    )
    check(
        set(whole.product_id)
        <= {"discharge_daily_mean", "discharge_daily_max", "stage_daily_max", "water_temperature_reported"},
        "only products with a whole-record total may be recorded as 'none published'",
    )
    windowed = inventory[inventory.status == "empty_in_tested_window"]
    check(
        set(windowed.product_id) <= {"discharge_instantaneous", "stage_instantaneous"},
        "only instantaneous products carry window-bounded negatives",
    )
    unresolved = inventory[inventory.status == "uninvestigated"]
    check(
        set(unresolved.product_id) <= {"discharge_instantaneous", "stage_instantaneous"},
        f"the {len(unresolved)} uninvestigated rows are confined to the instantaneous products",
    )
    check(
        bool(unresolved.evidence_basis.str.contains("not recorded as absence").all()) if len(unresolved) else True,
        "every uninvestigated row states that it is not a claim about the source",
    )

    producers = inventory[inventory.producer.notna() & (inventory.producer.astype(str).str.strip() != "")]
    check(
        producers.code_station.nunique() > 6000,
        f"producer established for {producers.code_station.nunique()} of {len(baseline)} stations",
    )

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("FAILURES:", *failures, sep="\n  - ")
        sys.exit(1)
    print("evidence integrity and inventory completeness verified")


if __name__ == "__main__":
    main()
