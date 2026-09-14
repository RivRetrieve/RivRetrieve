"""Verify the fr_hubeau evidence offline: integrity, reproduction, failures, entities and scope.

    verify : (ResearchFolder, Baseline) -> [Failure]   (no network)

Groups, each able to fail on the defect it names:
  recordings    every recording carries its receipt; kept bytes hash-match; quoted passages are
                slices of the kept bytes; the station/site comparison cites recordings that exist
  bundles       every receipt with a kept body has exactly that body (SHA-256 and size); every
                reading in a receipt is re-derived from its body; every Hub'Eau count body is kept
  inventory     complete and unique; every row re-classified here, independently, from the receipts
                it cites, and must match; a failed attempt can never settle a count or an empty window,
                and an emptiness claim over two windows needs both windows answered HTTP 200
  entities      every cited request addresses the row's own station, in the right population, with
                the product's own measurement filter and no date filter where a whole record is claimed
  scope         instantaneous discharge rows are station-level and say the site series is not
                established; organisation fields keep the source's terms and scope codes
  publication   public checks do not certify the retained private corpus or infer publication rights

Usage: uv run python research/station-coverage/fr_hubeau/scripts/verify_evidence.py [--folder DIR] [--native PARQUET]
"""

from __future__ import annotations

import argparse
import base64
import collections
import csv
import hashlib
import json
import pathlib
import sys
import urllib.parse  # noqa: TID251 - offline URL parsing, not provider runtime code

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from evidence_bundle import bodies, receipts  # noqa: E402
from readings import page_text  # noqa: E402
from verify_governing_evidence import check_source, verify_public  # noqa: E402

VOCABULARY = {
    "available",
    "empty_no_data_published",
    "empty_in_both_history_windows",
    "history_check_failed",
    "recent_window_empty_history_unchecked",
    "access_failed",
}
ROUTE = {
    "discharge_daily_mean": ("hubeau.eaufrance.fr", "/api/v2/hydrometrie/obs_elab", "code_entite", "grandeur_hydro_elab", "QmnJ"),
    "discharge_daily_max": ("hubeau.eaufrance.fr", "/api/v2/hydrometrie/obs_elab", "code_entite", "grandeur_hydro_elab", "QIXnJ"),
    "stage_daily_max": ("hubeau.eaufrance.fr", "/api/v2/hydrometrie/obs_elab", "code_entite", "grandeur_hydro_elab", "HIXnJ"),
    "stage_instantaneous": ("hubeau.eaufrance.fr", "/api/v2/hydrometrie/observations_tr", "code_entite", "grandeur_hydro", "H"),
    "discharge_instantaneous": ("hubeau.eaufrance.fr", "/api/v2/hydrometrie/observations_tr", "code_entite", "grandeur_hydro", "Q"),
    "water_temperature_reported": ("hubeau.eaufrance.fr", "/api/v1/temperature/chronique", "code_station", None, None),
}  # fmt: skip
WINDOWS = {"1": ("01/06/2026", "08/06/2026"), "2": ("01/06/2023", "08/06/2023")}
ORGANISATION_NOTES = {
    "NomIntervenant": {"nomintervenant_role_unstated", "nomintervenant_blank", "station_absent_from_sandre_layer"},
    "ProducteurDuJeu": {
        "producteurdujeu_station_dataset_producer",
        "producteurdujeu_blank",
        "station_absent_from_sandre_layer",
    },
}


class Checks:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.count = 0

    def __call__(self, condition: bool, label: str, detail: object = "") -> None:
        self.count += 1
        print(f"  {'PASS' if condition else 'FAIL'}  {label}{'' if condition or not detail else f'  -> {detail}'}")
        if not condition:
            self.failures.append(label)


def answered_count(r: dict[str, str]) -> bool:
    return r["http_status"] in ("200", "206") and r["count"] != "" and not r["request_error"]


def answered_series(r: dict[str, str]) -> bool:
    return r["http_status"] == "200" and r["points"] != "" and not r["request_error"]


def verify_recordings(folder: pathlib.Path, check: Checks) -> None:
    print("recordings")
    documents = {
        p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted((folder / "recordings").glob("*.json"))
    }
    required = ("status_code", "content_type", "retrieved_at", "response_bytes", "sha256", "body_retained")
    missing = [
        n for n, d in documents.items() if "url" not in d["request"] or any(k not in d["response"] for k in required)
    ]
    check(not missing, f"all {len(documents)} recordings carry url, status, media type, instant, size, sha256", missing)
    flag = [n for n, d in documents.items() if d["response"]["body_retained"] != ("content_base64" in d["response"])]
    check(not flag, "a recording keeps bytes exactly when it says it does", flag)
    bad = []
    for name, d in documents.items():
        if "content_base64" in d["response"]:
            raw = base64.b64decode(d["response"]["content_base64"])
            if (
                hashlib.sha256(raw).hexdigest() != d["response"]["sha256"]
                or len(raw) != d["response"]["response_bytes"]
            ):
                bad.append(name)
    check(not bad, "every kept recording body matches its SHA-256 and size", bad)
    unquoted, unverifiable = [], []
    for name, d in documents.items():
        quotes = (d["response"].get("reading") or {}).get("quotes") or []
        if quotes and "content_base64" not in d["response"]:
            unverifiable.append(name)
        elif quotes:
            text = page_text(base64.b64decode(d["response"]["content_base64"]))
            unquoted += [f"{name}: {q[:40]}" for q in quotes if q not in text]
    check(not unquoted, "every quoted passage is a slice of the recorded page", unquoted)
    print(f"        (quotes on {len(unverifiable)} receipted page(s) cannot be re-checked offline: {unverifiable})")
    comparison = json.loads((folder / "evidence" / "station_site_comparison.json").read_text(encoding="utf-8"))
    wrong = []
    for site in comparison["shared_sites"]:
        for entry in (site["site_series"], *site["stations"]):
            d = documents.get(entry["recording"])
            if (
                d is None
                or d["response"]["sha256"] != entry["sha256"]
                or d["response"]["reading"]["points"] != entry["points"]
            ):
                wrong.append(entry["recording"])
    check(not wrong, "the station/site comparison cites recordings that exist, by digest and point count", wrong)


def verify_bundle(folder: pathlib.Path, name: str, check: Checks) -> list[dict[str, str]]:
    bundle = folder / "evidence" / name
    rows, kept = receipts(bundle), bodies(bundle)
    ids = [r["request_id"] for r in rows]
    check(len(ids) == len(set(ids)), f"{name}: {len(rows):,} receipts, request ids unique")
    expected = {r["request_id"] for r in rows if r["body_retained"] == "True"}
    check(set(kept) == expected, f"{name}: bodies present exactly for receipts marked retained ({len(kept):,})",
          sorted(set(kept) ^ expected)[:5])  # fmt: skip
    by_id = {r["request_id"]: r for r in rows}
    mismatched = [
        i
        for i, raw in kept.items()
        if hashlib.sha256(raw).hexdigest() != by_id[i]["response_sha256"] or str(len(raw)) != by_id[i]["response_bytes"]
    ]
    check(not mismatched, f"{name}: every body matches its receipt's SHA-256 and size", mismatched[:5])
    drift = []
    for i, raw in kept.items():
        r = by_id[i]
        try:
            document = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            if r["http_status"] in ("200", "206"):
                drift.append(i)
            continue
        if "count" in r and r["http_status"] in ("200", "206"):
            codes = " ".join(sorted({str(row.get("code_station")) for row in document.get("data") or []}))
            if str(document.get("count")) != r["count"] or codes != r["returned_codes"]:
                drift.append(i)
        elif "points" in r and r["http_status"] == "200":
            try:
                check_source(r["code_station"], r["product_id"], r["request_url"], 200, raw)
            except (ValueError, KeyError, TypeError):
                drift.append(i)
                continue
            series = document.get("series") or {}
            if (
                str(len(series.get("data") or [])) != r["points"]
                or str(series.get("code") or "") != r["series_code"]
                or str(series.get("metric") or "") != r["series_metric"]
            ):
                drift.append(i)
    check(not drift, f"{name}: every receipt reading re-derives from its kept body", drift[:5])
    return rows


def entity_problems(
    row: dict[str, str], cited: list[dict[str, str]], hydro: set[str], temperature: set[str]
) -> list[str]:
    station, product = row["code_station"], row["product_id"]
    problems = []
    population = temperature if product == "water_temperature_reported" else hydro
    if station not in population:
        problems.append("station outside the product's population")
    for r in cited:
        url = urllib.parse.urlsplit(r["request_url"])
        query = dict(urllib.parse.parse_qsl(url.query))
        if "window" in r:
            if url.netloc != "hydro.eaufrance.fr" or url.path != f"/stationhydro/ajax/{station}/series":
                problems.append(f"{r['request_id']}: history request does not address station {station}")
            if query.get("hydro_series[simpleAndInterpolatedAndHourlyVariable]") != ROUTE[product][4]:
                problems.append(f"{r['request_id']}: history request asks for the wrong variable")
            if (query.get("hydro_series[startAt]"), query.get("hydro_series[endAt]")) != WINDOWS[r["window"]]:
                problems.append(f"{r['request_id']}: history request window differs from window {r['window']}")
            if answered_series(r) and (r["series_code"] != station or r["series_metric"] != ROUTE[product][4]):
                problems.append(f"{r['request_id']}: series returned for another entity or variable")
            continue
        host, path, code_param, filter_param, filter_value = ROUTE[product]
        if url.netloc != host or url.path != path:
            problems.append(f"{r['request_id']}: route {url.path} is not the product's route")
        if query.get(code_param) != station or r["entity_code"] != station:
            problems.append(f"{r['request_id']}: request addresses {query.get(code_param)}, not {station}")
        if filter_param and query.get(filter_param) != filter_value:
            problems.append(f"{r['request_id']}: measurement filter {query.get(filter_param)} is not {filter_value}")
        if any(key.startswith("date") for key in query):
            problems.append(f"{r['request_id']}: a date filter was applied")
        if query.get("size") != "1" or query.get("fields") != "code_station":
            problems.append(f"{r['request_id']}: not the size=1, fields=code_station count request")
        if answered_count(r) and r["returned_codes"] != (station if int(r["count"]) > 0 else ""):
            problems.append(f"{r['request_id']}: returned station {r['returned_codes']!r} for a count of {r['count']}")
    return problems


def verify_inventory(folder: pathlib.Path, native: pd.DataFrame, hub_rows, hist_rows, check: Checks) -> None:
    """Check public accounting and original query identities, not private source bodies."""
    import lzma

    with (folder / "inventory/station_product_evidence.csv").open(newline="", encoding="utf-8") as handle:
        inventory = list(csv.DictReader(handle))
    governed = json.loads(lzma.decompress((folder / "inventory/governing_evidence.json.xz").read_bytes()))
    by_pair = {(r["code_station"], r["product_id"]): r for r in governed["pairs"]}
    # This public check verifies ledger/baseline consistency only. Full certification
    # requires verify_governing_evidence.py --evidence-root with complete private bytes.
    verify_public(native, governed)
    native = native.assign(code_station=native.code_station.astype(str))
    hydro = set(native.loc[native.source_endpoint == "hydrometrie/referentiel/stations", "code_station"])
    temperature = set(native.loc[native.source_endpoint == "temperature/station", "code_station"])
    check(len(inventory) == len(by_pair), "final inventory has the complete governed pair count")
    keys = [(r["code_station"], r["product_id"]) for r in inventory]
    check(len(set(keys)) == len(keys) and set(keys) == set(by_pair), "final inventory keys match the baseline ledger")
    original_receipts = {f"hubeau:{r['request_id']}": r for r in hub_rows} | {
        f"hydroportail:{r['request_id']}": r for r in hist_rows
    }
    differing, identity = [], []
    for row in inventory:
        key = (row["code_station"], row["product_id"])
        expected = by_pair[key]
        refs = ["governing:" + a["reference"] for a in expected["acquisitions"]]
        if (row["status"], row["observations"], row["evidence_refs"].split()) != (
            expected["status"],
            str(expected["published_count_or_new_witness_points"]),
            refs,
        ):
            differing.append(key)
        cited = [original_receipts[ref] for ref in row["legacy_evidence_refs"].split()]
        identity.extend((key, problem) for problem in entity_problems(row, cited, hydro, temperature))
    check(not differing, "final inventory agrees with the reviewed derived governing ledger", differing[:5])
    check(not identity, "original cited queries retain correct station/product filters", identity[:5])
    check(all(r["tested_entity_kind"] == "station" for r in inventory), "all final findings are station scoped")
    org = [
        r
        for r in inventory
        if r["organisation_scope_note"] not in ORGANISATION_NOTES.get(r["station_organisation_field"], set())
    ]
    check(not org, "organisation names retain their source role limitations", org[:3])
    summary = json.loads((folder / "inventory/inventory_summary.json").read_text(encoding="utf-8"))
    tally = collections.defaultdict(collections.Counter)
    for row in inventory:
        tally[row["product_id"]][row["status"]] += 1
    check({p: dict(c) for p, c in tally.items()} == summary["by_product_status"], "final summary matches the inventory")


def main() -> None:
    parser = argparse.ArgumentParser()
    here = pathlib.Path(__file__).resolve().parents[1]
    parser.add_argument("--folder", type=pathlib.Path, default=here)
    parser.add_argument(
        "--native",
        type=pathlib.Path,
        default=here.parents[2] / "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet",
    )
    args = parser.parse_args()
    check = Checks()
    verify_recordings(args.folder, check)
    print("\nbundles")
    hub_rows = verify_bundle(args.folder, "hubeau_counts.tar.xz", check)
    hist_rows = verify_bundle(args.folder, "hydroportail_history.tar.xz", check)
    unkept = [r["request_id"] for r in hub_rows if r["response_sha256"] and r["body_retained"] != "True"]
    check(not unkept, "every answered Hub'Eau count body is kept whole, so every count re-derives offline", unkept[:5])
    verify_inventory(args.folder, pd.read_parquet(args.native), hub_rows, hist_rows, check)
    print(f"\n{check.count - len(check.failures)}/{check.count} checks passed")
    if check.failures:
        print("FAILURES:", *check.failures, sep="\n  - ")
        sys.exit(1)


if __name__ == "__main__":
    main()
