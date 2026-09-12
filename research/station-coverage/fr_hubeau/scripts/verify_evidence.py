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
  redistribution no observation value is readable from any file in the folder

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
from observation_scan import body_carries_observations, find_stored_observations  # noqa: E402
from readings import page_text  # noqa: E402

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
    kept_values = [
        n
        for n, d in documents.items()
        if d["response"]["body_retained"]
        and body_carries_observations(base64.b64decode(d["response"]["content_base64"]))
    ]
    check(not kept_values, "no kept recording body carries an observation value", kept_values)
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
            continue
        if "count" in r and r["http_status"] in ("200", "206"):
            codes = " ".join(sorted({str(row.get("code_station")) for row in document.get("data") or []}))
            if str(document.get("count")) != r["count"] or codes != r["returned_codes"]:
                drift.append(i)
        elif "points" in r and r["http_status"] == "200":
            series = document.get("series") or {}
            if str(len(series.get("data") or [])) != r["points"] or str(series.get("code") or "") != r["series_code"]:
                drift.append(i)
    check(not drift, f"{name}: every receipt reading re-derives from its kept body", drift[:5])
    return rows


def expected_row(
    station: str,
    product: str,
    hub: list[dict[str, str]],
    windows: dict[str, list[dict[str, str]]],
    sampled: bool,
) -> tuple[str, str, list[str]]:
    """Independent re-classification: (status, observations, cited request ids)."""
    good = [r for r in hub if answered_count(r)]
    if not good:
        return "access_failed", "", [f"hubeau:{r['request_id']}" for r in hub]
    count = int(good[-1]["count"])
    refs = [f"hubeau:{good[-1]['request_id']}"]
    if product not in ("stage_instantaneous", "discharge_instantaneous"):
        return ("available" if count else "empty_no_data_published"), str(count), refs
    if count:
        return "available", str(count), refs
    if not sampled:
        return "recent_window_empty_history_unchecked", "0", refs
    answers = {}
    for w in ("1", "2"):
        ok = [r for r in windows.get(w, []) if answered_series(r)]
        answers[w] = ok[-1] if ok else None
        refs += [f"hydroportail:{r['request_id']}" for r in ([ok[-1]] if ok else windows.get(w, []))]
    for w in ("1", "2"):
        if answers[w] is not None and int(answers[w]["points"]) > 0:  # type: ignore[index]
            return "available", answers[w]["points"], refs  # type: ignore[index]
    if answers["1"] is not None and answers["2"] is not None:
        return "empty_in_both_history_windows", "0", refs
    return "history_check_failed", "", refs


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
    print("\ninventory")
    with (folder / "inventory" / "station_product_evidence.csv").open(newline="", encoding="utf-8") as handle:
        inventory = list(csv.DictReader(handle))
    with (folder / "inventory" / "history_sample.csv").open(newline="", encoding="utf-8") as handle:
        sample = {(r["code_station"], r["product_id"]) for r in csv.DictReader(handle)}
    native = native.assign(code_station=native.code_station.astype(str))
    hydro = set(native.loc[native.source_endpoint == "hydrometrie/referentiel/stations", "code_station"])
    temperature = set(native.loc[native.source_endpoint == "temperature/station", "code_station"])
    check(
        len(inventory) == len(hydro) * 5 + len(temperature),
        f"{len(inventory):,} rows = {len(hydro)} x 5 + {len(temperature)}",
    )
    check(
        {r["code_station"] for r in inventory} == hydro | temperature,
        f"all {len(hydro | temperature):,} baseline stations accounted for",
    )
    pairs = collections.Counter((r["code_station"], r["product_id"]) for r in inventory)
    check(max(pairs.values()) == 1, "no station x product pair appears twice")
    check(
        {r["status"] for r in inventory} <= VOCABULARY,
        "statuses within the vocabulary",
        {r["status"] for r in inventory} - VOCABULARY,
    )
    check("producer" not in inventory[0], "no column asserts a 'producer'")

    hub: dict[tuple[str, str], list[dict[str, str]]] = collections.defaultdict(list)
    for r in hub_rows:
        hub[(r["code_station"], r["product_id"])].append(r)
    hist: dict[tuple[str, str], dict[str, list[dict[str, str]]]] = collections.defaultdict(
        lambda: collections.defaultdict(list)
    )
    for r in hist_rows:
        hist[(r["code_station"], r["product_id"])][r["window"]].append(r)
    by_ref = {f"hubeau:{r['request_id']}": r for r in hub_rows} | {
        f"hydroportail:{r['request_id']}": r for r in hist_rows
    }

    differing, dangling, failure_misread, windows_short, entity = [], [], [], [], []
    for row in inventory:
        key = (row["code_station"], row["product_id"])
        status, observations, refs = expected_row(*key, hub.get(key, []), hist.get(key, {}), key in sample)
        if (row["status"], row["observations"], row["evidence_refs"].split()) != (status, observations, refs):
            differing.append(
                f"{key}: inventory {row['status']}/{row['observations']}, receipts give {status}/{observations}"
            )
        cited = [by_ref.get(ref) for ref in row["evidence_refs"].split()]
        if None in cited or not cited:
            dangling.append(key)
            continue
        cited_rows: list[dict[str, str]] = [c for c in cited if c is not None]
        counts = [c for c in cited_rows if "count" in c]
        series = [c for c in cited_rows if "window" in c]
        if row["status"] != "access_failed" and not (len(counts) == 1 and answered_count(counts[0])):
            failure_misread.append(f"{key}: {row['status']} rests on an unanswered count request")
        if (
            row["status"] in ("empty_in_both_history_windows", "history_check_failed")
            or "HydroPortail" in row["evidence_basis"]
        ):
            per_window = collections.defaultdict(list)
            for c in series:
                per_window[c["window"]].append(c)
            if row["status"] == "empty_in_both_history_windows" and not all(
                len(per_window[w]) == 1 and answered_series(per_window[w][0]) and per_window[w][0]["points"] == "0"
                for w in ("1", "2")
            ):
                failure_misread.append(f"{key}: two-window emptiness without two answered empty windows")
            if row["status"] == "history_check_failed" and all(
                any(answered_series(c) for c in per_window[w]) for w in ("1", "2")
            ):
                failure_misread.append(f"{key}: marked failed though both windows answered")
        instantaneous = row["product_id"] in ("stage_instantaneous", "discharge_instantaneous")
        if key in sample and instantaneous and counts and answered_count(counts[0]) and counts[0]["count"] == "0":
            first = [c for c in hist.get(key, {}).get("1", []) if answered_series(c)]
            if not hist.get(key, {}).get("1") or (
                (not first or first[-1]["points"] == "0") and not hist.get(key, {}).get("2")
            ):
                windows_short.append(key)
        entity += [f"{key}: {p}" for p in entity_problems(row, cited_rows, hydro, temperature)]
    check(not dangling, "every row cites receipts that exist in the bundles", dangling[:5])
    check(not differing, "every row re-classifies identically from the receipts it cites", differing[:5])
    check(not failure_misread, "no failed request settles a count or an empty window", failure_misread[:5])
    check(
        not windows_short,
        "every sampled zero pair attempted window 1, and window 2 unless window 1 had points",
        windows_short[:5],
    )
    check(not entity, "every cited request addresses the row's station, route, measurement and filters", entity[:5])

    print("\nscope")
    q_rows = [r for r in inventory if r["product_id"] == "discharge_instantaneous"]
    check(
        all(r["tested_entity_kind"] == "station" and r["tested_entity_code"] == r["code_station"] and r["site_series_relation"] == "station_series_tested_site_series_not_established" for r in q_rows),
        f"all {len(q_rows):,} instantaneous-discharge rows are station-level and leave the site series unestablished",
    )  # fmt: skip
    check(not any(r["tested_entity_kind"] != "station" for r in inventory), "no row claims a site-level result")
    org = [
        r
        for r in inventory
        if r["organisation_scope_note"] not in ORGANISATION_NOTES.get(r["station_organisation_field"], set())
    ]
    check(not org, "organisation fields keep the source's name and a declared scope code", org[:3])
    summary = json.loads((folder / "inventory" / "inventory_summary.json").read_text(encoding="utf-8"))
    tally = collections.defaultdict(collections.Counter)
    for r in inventory:
        tally[r["product_id"]][r["status"]] += 1
    check(
        {p: dict(c) for p, c in tally.items()} == summary["by_product_status"],
        "inventory_summary.json reproduces from the inventory",
    )


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
    print("\nredistribution")
    stored = find_stored_observations(args.folder)
    check(not stored, "no observation value is readable from any file in the folder", stored[:5])
    print(f"\n{check.count - len(check.failures)}/{check.count} checks passed")
    if check.failures:
        print("FAILURES:", *check.failures, sep="\n  - ")
        sys.exit(1)


if __name__ == "__main__":
    main()
