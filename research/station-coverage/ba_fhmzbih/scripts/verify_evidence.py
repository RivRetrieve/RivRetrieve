"""Verify evidence integrity and inventory completeness. Runs offline - no network access.

The previous version of this script passed every check while the inventory was classifying
blank-only workbooks as available, because it validated the declared row count against itself.
The checks below are written to fail on that defect rather than restate it.

Checks:
  1.  Recordings and evidence files hash-match their stored bytes.
  2.  Every evidence file declares the fields issue #223 requires.
  3.  No request URL carries a credential-like parameter.
  4.  The inventory covers every station x product exactly once, with no omitted rows.
  5.  Every committed baseline station appears, and in_baseline reproduces the baseline exactly.
  6.  Statuses are drawn from the declared vocabulary; none claims 'unsupported'.
  7.  Rows with timestamps but no populated measurement cell are NOT called available.
  8.  Availability is never asserted from the declared row count or from HTTP status.
  9.  Each row's evidence file corresponds to that row: station, product, URL, instant, digest.
  10. Bytes are retained in full for every category carrying no observations.
  11. Excerpt digests are never presented as digests of the publisher response.
  12. Every reported horizon attempt cites its own preserved response and names its target.
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
VOCABULARY = {
    "measurements_present",
    "timestamped_without_measurements",
    "no_data_rows",
    "access_failed",
    "uninvestigated",
}
NO_OBSERVATION_STATUSES = {"timestamped_without_measurements", "no_data_rows", "access_failed"}

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


def load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text())


def main() -> None:
    print("1-3. evidence integrity, required fields, no credentials")
    recordings = sorted((HERE / "recordings").glob("*.recording.json"))
    evidence = sorted((HERE / "evidence").rglob("*.evidence.json"))
    documents = {path: load(path) for path in recordings + evidence}

    bad_hash = []
    for path, document in documents.items():
        response = document["response"]
        encoded = response.get("content_base64")
        if encoded is None:
            continue
        stored = response.get("sha256") or response.get("response_sha256")
        if hashlib.sha256(base64.b64decode(encoded)).hexdigest() != stored:
            bad_hash.append(path.name)
    retained = sum(1 for d in documents.values() if d["response"].get("content_base64") is not None)
    check(not bad_hash, f"all {retained} byte-retaining files hash-match their stored bytes {bad_hash or ''}")

    def has_size(response: dict) -> bool:
        # Size is explicit in the sweep evidence and implicit in the byte-retaining recordings.
        return "byte_size" in response or response.get("content_base64") is not None

    missing = [
        path.name
        for path, document in documents.items()
        if "url" not in document["request"]
        or any(field not in document["response"] for field in ("status_code", "content_type", "retrieved_at"))
        or not has_size(document["response"])
        or not (document["response"].get("sha256") or document["response"].get("response_sha256"))
    ]
    check(
        not missing,
        f"all {len(documents)} files carry url, status, media type, instant, size, digest {missing[:5] or ''}",
    )

    secrets = [
        path.name
        for path, document in documents.items()
        if any(t in document["request"]["url"].lower() for t in ("token", "password", "senha", "apikey", "api_key"))
    ]
    check(not secrets, f"no request URL carries a credential-like parameter {secrets or ''}")

    print("\n4-6. inventory completeness and vocabulary")
    inventory = pd.read_csv(HERE / "inventory" / "station_product_evidence.csv", dtype=str)
    stations = inventory.station_no.nunique()
    check(len(inventory) == stations * 3, f"inventory has {len(inventory)} rows = {stations} stations x 3 products")
    check(not inventory.duplicated(["station_no", "product_id"]).any(), "no station x product pair appears twice")

    baseline = set(pd.read_parquet(NATIVE).metadata_station_no.astype(str))
    check(baseline <= set(inventory.station_no), f"all {len(baseline)} committed baseline stations are accounted for")
    check(
        set(inventory[inventory.in_baseline == "True"].station_no) == baseline,
        "in_baseline flag reproduces the committed baseline exactly",
    )
    check(
        set(inventory.status) <= VOCABULARY,
        f"statuses drawn from the declared vocabulary: {sorted(set(inventory.status))}",
    )
    check(not inventory.status.eq("unsupported").any(), "no row claims a measurement is 'unsupported'")

    print("\n7-8. availability rests on measurement cells, not row counts or HTTP status")
    rows = pd.to_numeric(inventory.data_rows, errors="coerce")
    populated = pd.to_numeric(inventory.populated_measurements, errors="coerce")
    declared = pd.to_numeric(inventory.declared_rows, errors="coerce")

    blank_but_available = inventory[(rows > 0) & (populated == 0) & (inventory.status == "measurements_present")]
    check(
        blank_but_available.empty,
        f"no timestamped-but-blank workbook is classified as having measurements "
        f"{blank_but_available.station_no.tolist()[:5] or ''}",
    )
    present = inventory[inventory.status == "measurements_present"]
    check(
        bool((populated[present.index] > 0).all()),
        f"all {len(present)} rows with measurements cite a populated cell count > 0",
    )
    blank = inventory[inventory.status == "timestamped_without_measurements"]
    check(
        bool((rows[blank.index] > 0).all() and (populated[blank.index] == 0).all()),
        f"all {len(blank)} blank-only rows cite timestamped rows and zero populated cells",
    )
    empty = inventory[inventory.status == "no_data_rows"]
    check(bool((rows[empty.index] == 0).all()), f"all {len(empty)} no-data rows cite zero data rows")
    failed = inventory[inventory.status == "access_failed"]
    check(
        bool(failed.http_status.ne("200").all()),
        f"all {len(failed)} access failures cite a non-200 response",
    )
    # The defect this survey corrects: a positive declared row count that is not availability.
    overstated = inventory[(declared > 0) & (inventory.status != "measurements_present")]
    check(
        not overstated.empty,
        f"declared '#Rows' is demonstrably not availability: {len(overstated)} pairs declare rows > 0 "
        f"without a populated measurement cell",
    )
    ok200 = inventory[inventory.http_status == "200"]
    check(len(set(ok200.status)) > 1, f"HTTP 200 alone does not imply availability: {sorted(set(ok200.status))}")

    print("\n9-11. per-row evidence correspondence and retention")
    absent = [ref for ref in inventory.evidence_ref.dropna().unique() if not (HERE / ref).exists()]
    check(not absent, f"every cited evidence file exists on disk {absent[:5] or ''}")

    mismatched = []
    for row in inventory.itertuples():
        path = HERE / row.evidence_ref
        if not path.exists():
            continue
        document = documents.get(path) or load(path)
        if (
            document.get("station_no") != row.station_no
            or document.get("product_id") != row.product_id
            or document["request"]["url"] != row.url
            or document["response"]["retrieved_at"] != row.retrieved_at
            or document["response"]["response_sha256"] != row.response_sha256
        ):
            mismatched.append(f"{row.station_no}/{row.product_id}")
    check(
        not mismatched,
        f"every row's evidence matches that row's station, product, URL, instant and digest {mismatched[:5] or ''}",
    )
    shared = inventory.evidence_ref.value_counts()
    check(
        bool((shared == 1).all()),
        f"no evidence file is reused across rows as a stand-in {shared[shared > 1].index.tolist()[:3] or ''}",
    )

    unretained = []
    for row in inventory[inventory.status.isin(NO_OBSERVATION_STATUSES)].itertuples():
        path = HERE / row.evidence_ref
        if path.exists() and (documents.get(path) or load(path))["response"].get("content_base64") is None:
            unretained.append(f"{row.station_no}/{row.product_id}")
    check(
        not unretained,
        f"full bytes retained for every response carrying no observations {unretained[:5] or ''}",
    )

    conflated = []
    for path, document in documents.items():
        excerpt = document.get("excerpt")
        if excerpt and excerpt.get("excerpt_sha256") == document["response"].get("response_sha256"):
            conflated.append(path.name)
    check(not conflated, f"no excerpt digest is presented as a digest of the publisher response {conflated or ''}")

    proof = []
    for row in present.itertuples():
        path = HERE / row.evidence_ref
        if not path.exists():
            continue
        document = documents.get(path) or load(path)
        witness = [r for r in document.get("excerpt", {}).get("witness", []) if r.get("has_value")]
        if not witness:
            proof.append(f"{row.station_no}/{row.product_id}")
    check(
        not proof,
        f"every measurements-present row preserves a witness row {proof[:5] or ''}",
    )

    leaked = []
    for path, document in documents.items():
        excerpt = document.get("excerpt", {})
        if any("value" in row for row in excerpt.get("head", []) + excerpt.get("witness", [])):
            leaked.append(path.name)
        response = document["response"]
        if response.get("content_base64") and (document.get("reading") or {}).get("populated_measurements"):
            leaked.append(path.name)
    check(not leaked, f"no file retains publisher measurement values {leaked[:5] or ''}")

    print("\n12. historical-access attempts")
    horizon_path = HERE / "inventory" / "horizon_probe.csv"
    if horizon_path.exists():
        horizon = pd.read_csv(horizon_path, dtype=str)
        missing_ref = [r.attempted_variant for r in horizon.itertuples() if not (HERE / r.evidence_ref).exists()]
        check(not missing_ref, f"all {len(horizon)} horizon attempts cite a preserved response {missing_ref[:5] or ''}")
        check(
            bool(horizon.station_no.notna().all() and horizon.product_code.notna().all()),
            f"every horizon attempt names its station and product ({horizon.station_no.nunique()} stations probed)",
        )
    else:
        check(False, "horizon probe inventory is present")

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("FAILURES:", *failures, sep="\n  - ")
        sys.exit(1)
    print("evidence integrity and inventory completeness verified")


if __name__ == "__main__":
    main()
