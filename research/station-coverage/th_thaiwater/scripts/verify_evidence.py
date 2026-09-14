"""Verify historical research metadata and the current governing ledger offline.

    verify : committed research metadata → PASS/FAIL per consistency check

This command checks exact retained historical bodies where available. Historical
observation-bearing responses whose bytes were discarded remain uncertified here.
The separately required verify_governing_evidence.py command checks every current
private governing body at acceptance and integration. Public ledger agreement is
not a claim that public CI verifies those private bodies.
"""

from __future__ import annotations

import base64
import collections
import csv
import hashlib
import importlib.util
import json
import pathlib
import sys
import urllib.parse  # noqa: TID251 - research verification tool, not provider runtime code
import zipfile
from datetime import date

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = pathlib.Path(__file__).resolve().parents[3].parent
NATIVE = ROOT / "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet"
VOCABULARY = {"available", "empty_in_tested_window", "access_failed", "uninvestigated"}
SHORT, WIDE = ("2026-08-31", "2026-09-06"), ("2026-06-08", "2026-09-06")
FIELD = {"stage_reported": "value", "discharge_reported": "discharge"}
GRID_ROWS_PER_DATE = {24, 144}  # hourly and 10-minute grids, the two cadences the route answers with
COPIED = ("window_start", "window_end", "grid_rows", "http_status", "content_type", "retrieved_at",
          "response_bytes", "response_sha256")  # fmt: skip

failures: list[str] = []
checks = 0


def check(condition: bool, label: str) -> None:
    global checks
    checks += 1
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        failures.append(label)


def read_csv(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def inclusive_dates(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1


def graph_reading(raw: bytes) -> dict[str, str]:
    document = json.loads(raw)
    graph = document["data"]["graph_data"] or []
    return {
        "result": document.get("result", ""),
        "grid_rows": str(len(graph)),
        "nonnull_value": str(sum(1 for r in graph if r.get("value") is not None)),
        "nonnull_discharge": str(sum(1 for r in graph if r.get("discharge") is not None)),
        "nonnull_value_out": str(sum(1 for r in graph if r.get("value_out") is not None)),
        "grid_first": graph[0]["datetime"] if graph else "",
        "grid_last": graph[-1]["datetime"] if graph else "",
    }


def expected_status(receipt: dict[str, str], field: str) -> str:
    if receipt["request_error"] or receipt["http_status"] != "200" or receipt["result"] != "OK":
        return "access_failed"
    return "available" if int(receipt[f"nonnull_{field}"]) > 0 else "empty_in_tested_window"


def carries_observations(receipt: dict[str, str]) -> bool:
    return any(int(receipt[f"nonnull_{f}"] or 0) > 0 for f in ("value", "discharge", "value_out"))


def main() -> None:
    print("1. recordings: integrity and required fields")
    recordings = {path: json.loads(path.read_text()) for path in sorted((HERE / "recordings").glob("*.recording.json"))}
    required = ("status_code", "content_type", "retrieved_at", "response_bytes", "sha256", "body_retained")
    check(
        not [
            p.name
            for p, d in recordings.items()
            if any(f not in d["response"] for f in required) or "url" not in d["request"]
        ],
        f"all {len(recordings)} recordings carry url, status, media type, instant, byte size, sha256, retention flag",
    )
    bad = []
    for path, document in recordings.items():
        response = document["response"]
        if response.get("body_retained") is True:
            raw = base64.b64decode(response.get("content_base64", ""))
            if hashlib.sha256(raw).hexdigest() != response.get("sha256") or len(raw) != response.get("response_bytes"):
                bad.append(path.name)
        elif "content_base64" in response or "reading" not in response:
            bad.append(path.name)  # a stripped recording must carry no body and must carry its reading
    kept = sum(d["response"].get("body_retained") is True for d in recordings.values())
    check(
        not bad,
        f"{kept} retained bodies hash- and size-match; {len(recordings) - kept} stripped carry a reading {bad or ''}",
    )
    secret = [
        p.name
        for p, d in recordings.items()
        if any(t in json.dumps(d["request"]).lower() for t in ("token", "password", "apikey", "api_key"))
    ]
    check(not secret, f"no recording request carries a credential-like parameter {secret or ''}")

    print("\n3. receipts: one per request, internally consistent")
    receipts = read_csv(HERE / "evidence" / "graph_receipts.csv")
    by_id = {r["request_id"]: r for r in receipts}
    check(len(by_id) == len(receipts), f"{len(receipts)} receipts, request ids unique")
    url_mismatch = []
    for r in receipts:
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r["request_url"]).query))
        if (query.get("station_id"), query.get("start_date"), query.get("end_date")) != (
            r["station_id"],
            r["window_start"],
            r["window_end"],
        ):
            url_mismatch.append(r["request_id"])
    check(not url_mismatch, f"every receipt's request URL names its own station and window {url_mismatch[:5] or ''}")
    graphs = [r for r in receipts if not r["request_error"]]
    over = [
        r["request_id"]
        for r in graphs
        if max(int(r[f"nonnull_{f}"]) for f in ("value", "discharge", "value_out")) > int(r["grid_rows"])
    ]
    check(not over, f"no receipt reports more non-null values than its own grid rows {over[:5] or ''}")
    off_grid = []
    for r in graphs:
        n = inclusive_dates(r["window_start"], r["window_end"])
        rows = int(r["grid_rows"])
        if (
            rows % n
            or rows // n not in GRID_ROWS_PER_DATE
            or r["grid_first"][:10] != r["window_start"]
            or r["grid_last"][:10] != r["window_end"]
        ):
            off_grid.append(f"{r['request_id']}:{rows}/{n}")
    check(
        not off_grid,
        f"every response grid spans exactly its requested dates at 24 or 144 rows per date {off_grid[:5] or ''}",
    )

    print("\n4. retained bodies reproduce their receipts")
    with zipfile.ZipFile(HERE / "evidence" / "graph_bodies_without_observations.zip") as bundle:
        members = set(bundle.namelist())
        retained = [r for r in receipts if r["body_retained"] == "True"]
        mismatch = []
        for r in retained:
            member = f"{r['request_id']}.body"
            if member not in members:
                mismatch.append(f"{member} missing")
                continue
            raw = bundle.read(member)
            if hashlib.sha256(raw).hexdigest() != r["response_sha256"] or str(len(raw)) != r["response_bytes"]:
                mismatch.append(f"{member} digest")
                continue
            if not r["request_error"] and any(graph_reading(raw)[k] != r[k] for k in graph_reading(raw)):
                mismatch.append(f"{member} readings")
        check(
            not mismatch,
            f"{len(retained)} retained bodies match digest, size and every derived reading {mismatch[:5] or ''}",
        )
        check(
            members == {f"{r['request_id']}.body" for r in retained},
            "bundle holds exactly the retained bodies, nothing else",
        )
    unretained_empty = [
        r["request_id"]
        for r in receipts
        if r["body_retained"] != "True" and r["response_sha256"] and not carries_observations(r)
    ]
    check(
        not unretained_empty, f"every response carrying no observation is retained whole {unretained_empty[:5] or ''}"
    )

    print("\n5. inventory completeness")
    inventory = read_csv(HERE / "inventory" / "station_product_evidence.csv")
    baseline = set(pd.read_parquet(NATIVE)["station.id"].astype(str))
    check(len(inventory) == len(baseline) * 2, f"inventory has {len(inventory)} rows = {len(baseline)} stations x 2")
    check({r["station_id"] for r in inventory} == baseline, f"all {len(baseline)} baseline stations accounted for")
    pairs = collections.Counter((r["station_id"], r["product_id"]) for r in inventory)
    check(max(pairs.values()) == 1, "no station x product pair appears twice")
    check(
        {r["status"] for r in inventory} <= VOCABULARY,
        f"statuses within vocabulary: {sorted({r['status'] for r in inventory})}",
    )
    check(not any(r["status"] == "unsupported" for r in inventory), "no row claims a measurement is 'unsupported'")

    print("\n6. every row is linked to its own response and copies it exactly")
    unlinked = [f"{r['station_id']}/{r['product_id']}" for r in inventory if r["request_id"] not in by_id]
    check(not unlinked, f"every row cites a receipt that exists {unlinked[:5] or ''}")
    linked = [r for r in inventory if r["request_id"] in by_id]
    foreign = [
        f"{r['station_id']}->{by_id[r['request_id']]['station_id']}"
        for r in linked
        if by_id[r["request_id"]]["station_id"] != r["station_id"]
    ]
    check(
        not foreign,
        f"every row cites a response for its own station, never another station's example {foreign[:5] or ''}",
    )
    mixed = []
    for r in linked:
        receipt = by_id[r["request_id"]]
        differing = [k for k in COPIED if r[k] != receipt[k]]
        if r["nonnull_observations"] != receipt[f"nonnull_{FIELD[r['product_id']]}"]:
            differing.append("nonnull_observations")
        if r["response_body_retained"] != receipt["body_retained"]:
            differing.append("response_body_retained")
        if r["evidence_ref"] != f"evidence/graph_receipts.csv#{r['request_id']}":
            differing.append("evidence_ref")
        if differing:
            mixed.append(f"{r['station_id']}/{r['product_id']}:{','.join(differing)}")
    check(not mixed, f"no row carries a detail from a different request than the one it cites {mixed[:5] or ''}")
    over = [
        f"{r['station_id']}/{r['product_id']}"
        for r in inventory
        if r["nonnull_observations"] and r["grid_rows"] and int(r["nonnull_observations"]) > int(r["grid_rows"])
    ]
    check(not over, f"no row reports more non-null observations than its grid rows {over[:5] or ''}")
    wrong_dates = [
        r["station_id"]
        for r in inventory
        if str(inclusive_dates(r["window_start"], r["window_end"])) != r["window_dates"]
    ]
    check(
        not wrong_dates, f"every row's window_dates is the inclusive date count of its window {wrong_dates[:5] or ''}"
    )

    print("\n7. statuses reproduce from the cited response; the wider window governs")
    wrong = [
        f"{r['station_id']}/{r['product_id']}"
        for r in linked
        if r["status"] != expected_status(by_id[r["request_id"]], FIELD[r["product_id"]])
    ]
    check(not wrong, f"every status reproduces from its cited receipt {wrong[:5] or ''}")
    by_station = collections.defaultdict(list)
    for r in linked:
        by_station[r["station_id"]].append(r)
    split = [
        s
        for s, rows in by_station.items()
        if len({r["request_id"] for r in rows}) > 1 and not any(r["status"] == "access_failed" for r in rows)
    ]
    check(not split, f"both products of a station cite the one response that serves them {split[:5] or ''}")
    short_ok = {
        r["station_id"]: r for r in receipts if (r["window_start"], r["window_end"]) == SHORT and not r["request_error"]
    }
    needs_wide = {s for s, r in short_ok.items() if int(r["nonnull_value"]) == 0 or int(r["nonnull_discharge"]) == 0}
    not_wide = [
        s
        for s in needs_wide
        if any((r["window_start"], r["window_end"]) != WIDE and r["status"] != "available" for r in by_station[s])
    ]
    check(
        not not_wide,
        f"all {len(needs_wide)} stations with an empty product on 7 dates rest their empty rows on the 91-date response {not_wide[:5] or ''}",
    )
    empty = [r for r in inventory if r["status"] == "empty_in_tested_window"]
    check(
        all((r["window_start"], r["window_end"]) == WIDE for r in empty),
        f"all {len(empty)} empty rows rest on 2026-06-08..2026-09-06 (91 dates)",
    )
    ok200 = {r["status"] for r in inventory if r["http_status"] == "200"}
    check(len(ok200) > 1, "HTTP 200 alone does not imply available (200 rows carry both available and empty statuses)")
    check(
        all("graph route published" in r["evidence_basis"] for r in inventory if r["status"] == "available"),
        "every available row cites the graph route, never catalogue metadata",
    )

    print("\n8. population churn")
    live = {r["station_id"] for r in read_csv(HERE / "recordings" / "waterlevel_load_live.stations.csv")}
    churn = read_csv(HERE / "inventory" / "population_churn.csv")
    added = {r["station_id"] for r in churn if r["change"] == "added_since_baseline"}
    absent = {r["station_id"] for r in churn if r["change"] == "absent_from_latest_snapshot"}
    check(
        added == live - baseline and absent == baseline - live,
        "churn lists exactly the ids that differ between baseline and live snapshot",
    )
    check(
        len(baseline) - len(absent) + len(added) == len(live),
        f"churn reconciles: {len(baseline)} - {len(absent)} + {len(added)} = {len(live)}",
    )

    print("\n9. snapshot presence recorded per row")
    live_rows = {r["station_id"]: r for r in read_csv(HERE / "recordings" / "waterlevel_load_live.stations.csv")}
    wrong_state = [
        r["station_id"]
        for r in inventory
        if r["snapshot_discharge_state"]
        != (live_rows[r["station_id"]]["discharge_state"] if r["station_id"] in live_rows else "absent")
    ]
    check(
        not wrong_state,
        f"every row's snapshot state matches the snapshot readings, absent kept distinct from null {wrong_state[:5] or ''}",
    )

    print("\n10. metadata-versus-graph comparison reproduces from the final inventory")
    comparison = read_csv(HERE / "inventory" / "metadata_vs_graph.csv")
    summary = json.loads((HERE / "inventory" / "metadata_vs_graph_summary.json").read_text())
    discharge = {r["station_id"]: r["status"] for r in inventory if r["product_id"] == "discharge_reported"}
    recomputed = {}
    for s in baseline:
        state = live_rows[s]["discharge_state"] if s in live_rows else "absent"
        graph = "available" if discharge[s] == "available" else "empty"
        recomputed[s] = (state, graph)
    stale = [
        r["station_id"]
        for r in comparison
        if (r["snapshot_discharge_state"], "available" if r["graph_discharge_status"] == "available" else "empty")
        != recomputed[r["station_id"]]
    ]
    check(
        len(comparison) == len(baseline) and not stale,
        f"per-station comparison matches inventory and snapshot for all {len(baseline)} stations {stale[:5] or ''}",
    )
    tally = collections.Counter(recomputed.values())
    present = sum(v for (state, _), v in tally.items() if state != "absent")
    disagree = (
        tally[("null", "available")]
        + tally[("value", "empty")]
        + tally[("blank", "available")]
        + tally[("blank", "empty")]
    )
    check(
        summary["present_in_snapshot"] == present
        and summary["present_disagree"] == disagree
        and summary["absent_with_graph_discharge"] == tally[("absent", "available")],
        f"summary counts reproduce: {present} present, {disagree} disagree among them, {tally[('absent', 'available')]} absent with graph discharge",
    )

    print("\n11. window-limit readings reproduce from the recorded probe")
    probe = read_csv(HERE / "inventory" / "window_limit_probe.csv")
    readings = read_csv(HERE / "inventory" / "window_limit_readings.csv")
    drift = []
    for p, r in zip(probe, readings, strict=True):
        honoured = "yes" if p["returned_first"][:10] == p["requested_start"] else "no"
        if (
            r["requested_inclusive_dates"] != str(inclusive_dates(p["requested_start"], p["requested_end"]))
            or r["returned_inclusive_dates"] != str(inclusive_dates(p["returned_first"][:10], p["returned_last"][:10]))
            or r["start_honoured"] != honoured
            or r["rows"] != p["rows"]
        ):
            drift.append(p["requested_start"])
    check(not drift, f"all {len(readings)} readings match their recorded requested and returned dates {drift or ''}")

    print("\n12. governing acquisition ledger (public metadata checks, not private-body verification)")
    spec = importlib.util.spec_from_file_location(
        "governing_graph_evidence", HERE / "scripts/verify_governing_evidence.py"
    )
    assert spec is not None and spec.loader is not None
    governing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(governing)
    ledger = governing.read_ledger(HERE / "inventory/governing_station_product_evidence.csv")
    governing.verify_ledger(ledger, governing.station_agencies(NATIVE))
    governing_summary = json.loads((HERE / "inventory/governing_summary.json").read_text())
    check(
        governing_summary["baseline_stations"] == len({r["station_id"] for r in ledger})
        and governing_summary["applicable_pairs"] == len(ledger)
        and governing_summary["positive_availability"] == sum(r["availability"] == "available" for r in ledger)
        and governing_summary["unknown_availability"] == sum(r["availability"] == "unknown" for r in ledger),
        "governing coverage summary agrees with its public ledger",
    )
    certified_counts = {(r["station_id"], r["product_id"]): (r["status"], r["nonnull_observations"]) for r in ledger}
    drift = [
        f"{r['station_id']}/{r['product_id']}"
        for r in inventory
        if certified_counts[(r["station_id"], r["product_id"])] != (r["status"], r["nonnull_observations"])
    ]
    check(
        not drift, f"historical derived counts match the independently body-verified governing ledger {drift[:5] or ''}"
    )
    print(
        "Private body certification is a separate mandatory acceptance command: verify_governing_evidence.py --evidence-root ..."
    )

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("FAILURES:", *failures, sep="\n  - ")
        sys.exit(1)
    print(
        "public metadata consistency and retained historical-body checks complete; private governing-body certification remains separate"
    )


if __name__ == "__main__":
    main()
