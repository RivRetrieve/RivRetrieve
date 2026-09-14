"""Compose the station x product evidence inventory for fr_hubeau from the preserved receipts.

    compose : (Baseline, HubEauReceipts, HistoryReceipts, HistorySample, StationLayers) -> Inventory   (pure)

Every row is derived from receipts in `evidence/*.tar.xz` and names them in `evidence_refs`, so each
conclusion traces to the exact request and response that produced it. A receipt settles a request
only if the publisher answered it: HTTP 200/206 with a parseable count (Hub'Eau) or HTTP 200 with a
parseable series (HydroPortail). A failed attempt never contributes a count or a point total.

Status vocabulary (non-interchangeable, per issue #222):
  available                              at least one observation reported: a count above zero (whole
                                         record, or observations_tr's rolling 30 days), or HydroPortail
                                         series points in a tested window
  empty_no_data_published                whole-record count of zero (daily and temperature products)
  empty_in_both_history_windows          30-day count of zero, and both HydroPortail windows answered
                                         HTTP 200 with no point; emptiness in those two windows only
  history_check_failed                   30-day count of zero, at least one HydroPortail window never
                                         answered, and none returned points; no claim about the source
  recent_window_empty_history_unchecked  30-day count of zero; never checked against history
  access_failed                          no attempt at the Hub'Eau count was answered; no claim

There is no `unsupported` status: no recorded evidence states that a station cannot supply a product.

Instantaneous scope: the tested entity is the STATION for H and for Q. Production requests the SITE
series for discharge_instantaneous; a station result is not transferred to it (`site_series_relation`).

Organisation columns carry the Sandre layer's own field name and a scope code; neither field is
established as the producer of the series retrieved. See HANDOFF.md section 6.

Usage: uv run python research/station-coverage/fr_hubeau/scripts/build_inventory.py
Output: inventory/station_product_evidence.csv, inventory/inventory_summary.json
"""

from __future__ import annotations

import base64
import collections
import csv
import json
import lzma
import pathlib
import statistics
import sys
from datetime import datetime
from urllib.parse import parse_qsl, urlsplit  # noqa: TID251 -- offline URL parsing only

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from evidence_bundle import receipts  # noqa: E402

DAILY = ("discharge_daily_mean", "discharge_daily_max", "stage_daily_max")
TEMPERATURE = "water_temperature_reported"
INSTANT = ("stage_instantaneous", "discharge_instantaneous")
HYDRO_PRODUCTS = (*DAILY, *INSTANT)
WHOLE_RECORD = "whole record (no date filter)"
HISTORY_WINDOWS = "HydroPortail station series 01/06/2026-08/06/2026 and 01/06/2023-08/06/2023"
Q_RELATION = "station_series_tested_site_series_not_established"
COLUMNS = [
    "code_station",
    "code_site",
    "en_service",
    "product_id",
    "status",
    "observations",
    "evidence_basis",
    "window_tested",
    "tested_entity_kind",
    "tested_entity_code",
    "site_series_relation",
    "station_organisation_field",
    "station_organisation_name",
    "organisation_scope_note",
    "evidence_refs",
    "legacy_evidence_refs",
]
LAYERS = (
    # (recording, code field, organisation field, note when named, note when blank)
    ("sandre_wfs_stationhydro_all", "CdStationHydro", "NomIntervenant", "nomintervenant_role_unstated", "nomintervenant_blank"),
    (
        "sandre_wfs_stationmesure_producers",
        "CdStationMesureEauxSurface",
        "ProducteurDuJeu",
        "producteurdujeu_station_dataset_producer",
        "producteurdujeu_blank",
    ),
)  # fmt: skip


def hubeau_settled(receipt: dict[str, str]) -> bool:
    return receipt["http_status"] in ("200", "206") and receipt["count"] != "" and not receipt["request_error"]


def history_settled(receipt: dict[str, str]) -> bool:
    return receipt["http_status"] == "200" and receipt["points"] != "" and not receipt["request_error"]


def failures(attempts: list[dict[str, str]]) -> str:
    tally = collections.Counter(attempt["request_error"] or f"HTTP {attempt['http_status']}" for attempt in attempts)
    return ", ".join(f"{reason} x{count}" for reason, count in sorted(tally.items()))


def organisations(recordings: pathlib.Path) -> dict[str, tuple[str, str, str]]:
    """Station code -> (source field, organisation name, scope code), from the two Sandre layers."""
    out: dict[str, tuple[str, str, str]] = {}
    for name, code_field, field, named, blank in LAYERS:
        document = json.loads((recordings / f"{name}.recording.json").read_text(encoding="utf-8"))
        payload = json.loads(base64.b64decode(document["response"]["content_base64"]))
        for feature in payload["features"]:
            properties = feature["properties"]
            value = str(properties.get(field) or "").strip()
            out[str(properties[code_field])] = (field, value, named if value else blank)
    return out


def classify(
    station: str,
    product: str,
    attempts: list[dict[str, str]],
    windows: dict[str, list[dict[str, str]]],
    sampled: bool,
) -> dict[str, object]:
    if not attempts:
        raise SystemExit(f"{station} {product}: no Hub'Eau receipt; run acquire_hubeau_counts.py")
    settled = [attempt for attempt in attempts if hubeau_settled(attempt)]
    whole = product not in INSTANT
    if not settled:
        return {
            "status": "access_failed",
            "observations": "",
            "evidence_basis": f"no attempt answered: {failures(attempts)}",
            "window_tested": WHOLE_RECORD if whole else "observations_tr rolling 30 days",
            "evidence_refs": [f"hubeau:{attempt['request_id']}" for attempt in attempts],
        }
    receipt = settled[-1]
    count = int(receipt["count"])
    refs = [f"hubeau:{receipt['request_id']}"]
    if whole:
        status = "available" if count > 0 else "empty_no_data_published"
        return {
            "status": status,
            "observations": count,
            "evidence_basis": f"count {count} over whole record",
            "window_tested": WHOLE_RECORD,
            "evidence_refs": refs,
        }
    recent = f"observations_tr rolling 30 days before {receipt['retrieved_at'][:10]}"
    if count > 0:
        return {
            "status": "available",
            "observations": count,
            "evidence_basis": f"observations_tr count {count} in rolling 30 days",
            "window_tested": recent,
            "evidence_refs": refs,
        }
    if not sampled:
        return {
            "status": "recent_window_empty_history_unchecked",
            "observations": 0,
            "evidence_basis": "observations_tr count 0 in rolling 30 days; no history check",
            "window_tested": recent,
            "evidence_refs": refs,
        }

    outcome: dict[str, tuple[dict[str, str] | None, list[dict[str, str]]]] = {}
    for window in ("1", "2"):
        tries = windows.get(window, [])
        answered = [attempt for attempt in tries if history_settled(attempt)]
        outcome[window] = (answered[-1] if answered else None, tries)
    first, first_tries = outcome["1"]
    if not first_tries:
        raise SystemExit(f"{station} {product}: sampled pair never attempted in window 1")
    if (first is None or int(first["points"]) == 0) and not outcome["2"][1]:
        raise SystemExit(f"{station} {product}: window 2 required but never attempted")
    for answered, tries in outcome.values():
        cited = [answered] if answered is not None else tries
        refs += [f"hydroportail:{attempt['request_id']}" for attempt in cited]
    window_tested = f"{recent}; {HISTORY_WINDOWS}"
    positive = [
        (window, answered) for window, (answered, _) in outcome.items() if answered and int(answered["points"]) > 0
    ]
    if positive:
        window, answered = positive[0]
        points = int(answered["points"])
        return {
            "status": "available",
            "observations": points,
            "evidence_basis": f"30-day count 0; HydroPortail station series {points} points in window {window}",
            "window_tested": window_tested,
            "evidence_refs": refs,
        }
    if outcome["1"][0] is not None and outcome["2"][0] is not None:
        return {
            "status": "empty_in_both_history_windows",
            "observations": 0,
            "evidence_basis": "30-day count 0; HydroPortail windows 1 and 2 answered HTTP 200 with 0 points",
            "window_tested": window_tested,
            "evidence_refs": refs,
        }
    described = "; ".join(
        f"window {window} " + ("HTTP 200, 0 points" if answered else f"never answered ({failures(tries)})")
        for window, (answered, tries) in outcome.items()
    )
    return {
        "status": "history_check_failed",
        "observations": "",
        "evidence_basis": f"30-day count 0; HydroPortail {described}",
        "window_tested": window_tested,
        "evidence_refs": refs,
    }


def compose(
    native: pd.DataFrame,
    hubeau: list[dict[str, str]],
    history: list[dict[str, str]],
    sample: list[dict[str, str]],
    orgs: dict[str, tuple[str, str, str]],
) -> list[dict[str, object]]:
    by_pair: dict[tuple[str, str], list[dict[str, str]]] = collections.defaultdict(list)
    for receipt in hubeau:
        by_pair[(receipt["code_station"], receipt["product_id"])].append(receipt)
    by_window: dict[tuple[str, str], dict[str, list[dict[str, str]]]] = collections.defaultdict(
        lambda: collections.defaultdict(list)
    )
    for receipt in history:
        by_window[(receipt["code_station"], receipt["product_id"])][receipt["window"]].append(receipt)
    sampled = {(row["code_station"], row["product_id"]) for row in sample}

    records: list[dict[str, object]] = []
    for population, field, products in (
        ("hydrometrie/referentiel/stations", "NomIntervenant", HYDRO_PRODUCTS),
        ("temperature/station", "ProducteurDuJeu", (TEMPERATURE,)),
    ):
        for row in native[native.source_endpoint == population].itertuples():
            station = str(row.code_station)
            hydrometry = population.startswith("hydrometrie")
            organisation = orgs.get(station, (field, "", "station_absent_from_sandre_layer"))
            for product in products:
                pair = (station, product)
                records.append(
                    {
                        "code_station": station,
                        "code_site": str(row.code_site) if hydrometry else "",
                        "en_service": str(row.en_service) if hydrometry else "",
                        "product_id": product,
                        **classify(station, product, by_pair.get(pair, []), by_window.get(pair, {}), pair in sampled),
                        "tested_entity_kind": "station",
                        "tested_entity_code": station,
                        "site_series_relation": Q_RELATION
                        if product == "discharge_instantaneous"
                        else "not_applicable",
                        "station_organisation_field": organisation[0],
                        "station_organisation_name": organisation[1],
                        "organisation_scope_note": organisation[2],
                    }
                )
    for record in records:
        refs = record["evidence_refs"]
        assert isinstance(refs, list)
        record["evidence_refs"] = " ".join(str(ref) for ref in refs)
    return sorted(records, key=lambda record: (str(record["code_station"]), str(record["product_id"])))


def summarise(
    records: list[dict[str, object]], hubeau: list[dict[str, str]], history: list[dict[str, str]], sample_size: int
) -> dict[str, object]:
    frame = pd.DataFrame(records)
    by_product = {
        product: {status: int(n) for status, n in group.status.value_counts().sort_index().items()}
        for product, group in frame.groupby("product_id")
    }
    instant = frame[frame.product_id.isin(INSTANT)]
    by_service = {
        product: {
            service: {status: int(n) for status, n in grp.status.value_counts().sort_index().items()}
            for service, grp in group.groupby("en_service")
        }
        for product, group in instant.groupby("product_id")
    }
    unchecked = instant[instant.status == "recent_window_empty_history_unchecked"]
    instants = sorted(datetime.fromisoformat(r["retrieved_at"].replace("Z", "+00:00")) for r in history)
    gaps = [(b - a).total_seconds() for a, b in zip(instants, instants[1:], strict=False)]
    pacing = statistics.median(gap for gap in gaps if gap < 600) if gaps else 0.0
    never_checked = len(unchecked)
    failed = int((instant.status == "history_check_failed").sum())
    requests_upper = 2 * (never_checked + failed)
    names = frame.drop_duplicates("code_station")
    return {
        "rows": len(frame),
        "stations": int(frame.code_station.nunique()),
        "by_product_status": by_product,
        "instantaneous_by_en_service_status": by_service,
        "history_sample_pairs": sample_size,
        "remaining_historical_uncertainty": {
            "recent_window_empty_history_unchecked_in_service": int((unchecked.en_service == "True").sum()),
            "recent_window_empty_history_unchecked_out_of_service": int((unchecked.en_service == "False").sum()),
            "history_check_failed": failed,
            "empty_in_both_history_windows": int((instant.status == "empty_in_both_history_windows").sum()),
            "historical_hypothetical_two_window_request_count": requests_upper,
            "survey_scope": "no_further_survey",
            "hydroportail_median_seconds_between_requests": round(pacing, 2),
            "historical_hypothetical_two_window_hours": round(requests_upper * pacing / 3600, 1),
        },
        "hubeau_attempts": len(hubeau),
        "hubeau_attempts_unanswered": sum(not hubeau_settled(r) for r in hubeau),
        "history_attempts": len(history),
        "history_attempts_unanswered": sum(not history_settled(r) for r in history),
        "stations_with_organisation_name": {
            field: int(((names.station_organisation_field == field) & (names.station_organisation_name != "")).sum())
            for field in ("NomIntervenant", "ProducteurDuJeu")
        },
    }


def apply_governing_evidence(records: list[dict[str, object]], governing: dict) -> list[dict[str, object]]:
    """Project the reviewed final ledger without recertifying private source bytes."""
    indexed = {(row["code_station"], row["product_id"]): row for row in governing["pairs"]}
    keys = {(row["code_station"], row["product_id"]) for row in records}
    if keys != set(indexed) or len(records) != len(indexed):
        raise ValueError("governing evidence must match the exact baseline pairs")
    for row in records:
        evidence = indexed[(row["code_station"], row["product_id"])]
        row["legacy_evidence_refs"] = row["evidence_refs"]
        row["status"] = evidence["status"]
        row["observations"] = evidence["published_count_or_new_witness_points"]
        row["evidence_refs"] = " ".join("governing:" + a["reference"] for a in evidence["acquisitions"])
        row["evidence_basis"] = (
            evidence["basis"] + "; " + evidence["availability"] + "; dated source outcome, not whole-history absence"
        )
        windows = []
        for acquisition in evidence["acquisitions"]:
            query = dict(parse_qsl(urlsplit(acquisition["requested_from"][0]).query))
            if acquisition["role"] == "historical_check":
                window = query["hydro_series[startAt]"] + ".." + query["hydro_series[endAt]"]
            else:
                window = (
                    "rolling recent window"
                    if row["product_id"] in INSTANT
                    else "whole-record query without date filters"
                )
            windows.append(window + " acquired " + acquisition["retrieved_at_start"])
        row["window_tested"] = " | ".join(windows)
    return records


def main() -> None:
    here = pathlib.Path(__file__).resolve().parents[1]
    native = pd.read_parquet(here.parents[2] / "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet")
    hubeau = receipts(here / "evidence" / "hubeau_counts.tar.xz")
    history = receipts(here / "evidence" / "hydroportail_history.tar.xz")
    with (here / "inventory" / "history_sample.csv").open(newline="", encoding="utf-8") as handle:
        sample = list(csv.DictReader(handle))
    governing = json.loads(lzma.decompress((here / "inventory/governing_evidence.json.xz").read_bytes()))
    records = apply_governing_evidence(
        compose(native, hubeau, history, sample, organisations(here / "recordings")), governing
    )

    expected = int((native.source_endpoint == "hydrometrie/referentiel/stations").sum()) * 5 + int(
        (native.source_endpoint == "temperature/station").sum()
    )
    if len(records) != expected:
        raise SystemExit(f"expected {expected} rows, composed {len(records)}")
    with (here / "inventory" / "station_product_evidence.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    summary = summarise(records, hubeau, history, len(sample))
    (here / "inventory" / "inventory_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(records)} rows")
    print(json.dumps(summary["by_product_status"], indent=1))
    print(json.dumps(summary["remaining_historical_uncertainty"], indent=1))


if __name__ == "__main__":
    main()
