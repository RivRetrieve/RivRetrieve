"""Acquire the Hub'Eau count responses behind every daily, temperature and 30-day availability result.

    acquire : BaselineStations -> (Receipt table, staged observation-free bodies)   (network)

Replacement capture. The original sweeps (2026-09-08/09) kept only a derived count per pair and
discarded every response, so no result could be traced to the response that produced it. This script
repeats the same requests and keeps, for every attempt, a receipt: exact request URL, HTTP status,
media type, UTC acquisition instant, byte size, SHA-256 of the full bytes, and the readings derived
from them. New acquisition instants are recorded as such; nothing is backdated.

Every request asks for `size=1` and `fields=code_station`, so the single row returned carries only
the station code. The body therefore holds the publisher's `count` and no observation value, and is
kept whole in the staging bundle, which `pack_evidence.py` compresses into `evidence/`. A body that
nevertheless carries a measurement field is receipted and not kept.

Routes, entities and filters, exactly as declared in the provider config:
  obs_elab (v2)                code_entite=<hydrometry station>  grandeur_hydro_elab=QmnJ|QIXnJ|HIXnJ
  temperature/chronique (v1)   code_station=<temperature station>
  observations_tr (v2)         code_entite=<hydrometry station>  grandeur_hydro=H|Q  (rolling 30 days)
No date filter is applied, so obs_elab and chronique counts cover the station's whole record.

Resumable. A pair is settled only by an attempt answered HTTP 200/206 with a parseable count. Every
other attempt - an HTTP error, a transport failure, an unparseable body - stays in the receipt table
as evidence, and the pair is attempted again, under a new request id, on this run or the next.

Usage: uv run python research/station-coverage/fr_hubeau/scripts/acquire_hubeau_counts.py <staging.zip>
Output: evidence/hubeau_count_receipts.csv; bodies appended to <staging.zip>
"""

from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import sys
import tarfile
import time
import zipfile
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import requests  # noqa: TID251 - research capture tool, not provider runtime code

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from observation_scan import body_carries_observations  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = pathlib.Path(__file__).resolve().parents[3].parent
NATIVE = ROOT / "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet"
RECEIPTS = HERE / "evidence" / "hubeau_count_receipts.csv"
BUNDLE = HERE / "evidence" / "hubeau_counts.tar.xz"

OBS_ELAB = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab"
CHRONIQUE = "https://hubeau.eaufrance.fr/api/v1/temperature/chronique"
OBSERVATIONS_TR = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/observations_tr"
USER_AGENT = "RivRetrieve-research/0.1 (station coverage survey; +https://github.com/RivRetrieve/RivRetrieve)"

DAILY = (("discharge_daily_mean", "QmnJ"), ("discharge_daily_max", "QIXnJ"), ("stage_daily_max", "HIXnJ"))
INSTANT = (("stage_instantaneous", "H"), ("discharge_instantaneous", "Q"))
FIELDS = [
    "request_id",
    "code_station",
    "product_id",
    "route",
    "entity_kind",
    "entity_code",
    "native_field",
    "request_url",
    "retrieved_at",
    "http_status",
    "content_type",
    "response_bytes",
    "response_sha256",
    "count",
    "returned_codes",
    "body_retained",
    "request_error",
]
DELAY_SECONDS = 0.1
TIMEOUT_SECONDS = 30
ATTEMPTS_PER_RUN = 3


def tasks(native: pd.DataFrame) -> list[dict[str, Any]]:
    hydro = native[native.source_endpoint == "hydrometrie/referentiel/stations"]
    temperature = native[native.source_endpoint == "temperature/station"]
    out: list[dict[str, Any]] = []
    for station in hydro.code_station.astype(str):
        for product_id, grandeur in DAILY:
            out.append(
                {
                    "code_station": station,
                    "product_id": product_id,
                    "route": "obs_elab",
                    "entity_kind": "station",
                    "entity_code": station,
                    "native_field": grandeur,
                    "url": OBS_ELAB,
                    "params": {
                        "code_entite": station,
                        "grandeur_hydro_elab": grandeur,
                        "size": "1",
                        "fields": "code_station",
                    },
                }
            )
        for product_id, grandeur in INSTANT:
            out.append(
                {
                    "code_station": station,
                    "product_id": product_id,
                    "route": "observations_tr",
                    "entity_kind": "station",
                    "entity_code": station,
                    "native_field": grandeur,
                    "url": OBSERVATIONS_TR,
                    "params": {
                        "code_entite": station,
                        "grandeur_hydro": grandeur,
                        "size": "1",
                        "fields": "code_station",
                    },
                }
            )
    for station in temperature.code_station.astype(str):
        out.append(
            {
                "code_station": station,
                "product_id": "water_temperature_reported",
                "route": "temperature/chronique",
                "entity_kind": "station",
                "entity_code": station,
                "native_field": "resultat",
                "url": CHRONIQUE,
                "params": {"code_station": station, "size": "1", "fields": "code_station"},
            }
        )
    return out


def read(raw: bytes) -> tuple[str, str, str]:
    """(count, returned station codes, parse error) derived from one body."""
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "", "", "body is not JSON"
    if not isinstance(document, dict) or not isinstance(document.get("count"), int):
        return "", "", "body carries no integer count"
    codes = sorted({str(row.get("code_station")) for row in document.get("data") or [] if isinstance(row, dict)})
    return str(document["count"]), " ".join(codes), ""


def attempt(
    session: requests.Session, task: dict[str, Any], request_id: str, bundle: zipfile.ZipFile
) -> dict[str, str]:
    prepared = session.prepare_request(requests.Request("GET", task["url"], params=task["params"]))
    receipt = dict.fromkeys(FIELDS, "")
    receipt.update(
        {
            key: task[key]
            for key in ("code_station", "product_id", "route", "entity_kind", "entity_code", "native_field")
        }
    )
    receipt.update(request_id=request_id, request_url=str(prepared.url))
    retrieved_at = datetime.now(UTC)
    receipt["retrieved_at"] = retrieved_at.isoformat().replace("+00:00", "Z")
    try:
        response = session.send(prepared, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as error:
        receipt["request_error"] = f"{type(error).__name__}: {error}"
        receipt["body_retained"] = "False"
        return receipt
    raw = response.content
    receipt.update(
        http_status=str(response.status_code),
        content_type=response.headers.get("Content-Type", ""),
        response_bytes=str(len(raw)),
        response_sha256=hashlib.sha256(raw).hexdigest(),
    )
    if response.status_code in (200, 206):
        count, codes, problem = read(raw)
        receipt.update(count=count, returned_codes=codes, request_error=problem)
    else:
        receipt["request_error"] = f"HTTP {response.status_code}"
    keep = not body_carries_observations(raw)
    receipt["body_retained"] = str(keep)
    if keep:
        info = zipfile.ZipInfo(f"{request_id}.body", date_time=retrieved_at.timetuple()[:6])
        info.compress_type = zipfile.ZIP_DEFLATED
        bundle.writestr(info, raw)
    return receipt


def settled(receipt: dict[str, str]) -> bool:
    return receipt["http_status"] in ("200", "206") and receipt["count"] != "" and not receipt["request_error"]


def main(staging: pathlib.Path) -> None:
    work = tasks(pd.read_parquet(NATIVE))
    RECEIPTS.parent.mkdir(parents=True, exist_ok=True)
    if not RECEIPTS.exists() and BUNDLE.exists():  # resume from the packed evidence
        with tarfile.open(BUNDLE, "r:xz") as packed:
            member = packed.extractfile("receipts.csv")
            if member is None:
                raise SystemExit(f"{BUNDLE.name} has no receipts.csv")
            RECEIPTS.write_bytes(member.read())
    attempts: dict[tuple[str, str], int] = {}
    done: set[tuple[str, str]] = set()
    if RECEIPTS.exists():
        with RECEIPTS.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row["code_station"], row["product_id"])
                attempts[key] = attempts.get(key, 0) + 1
                if settled(row):
                    done.add(key)
    remaining = [task for task in work if (task["code_station"], task["product_id"]) not in done]
    print(f"{len(work)} pairs; {len(done)} settled; {len(remaining)} to acquire", flush=True)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    new_file = not RECEIPTS.exists()
    started = time.time()
    with RECEIPTS.open("a", newline="", encoding="utf-8") as handle, zipfile.ZipFile(staging, "a") as bundle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        for index, task in enumerate(remaining, start=1):
            key = (task["code_station"], task["product_id"])
            for tries in range(ATTEMPTS_PER_RUN):
                attempts[key] = attempts.get(key, 0) + 1
                receipt = attempt(session, task, f"{key[0]}_{key[1]}_a{attempts[key]}", bundle)
                writer.writerow(receipt)
                time.sleep(DELAY_SECONDS)
                if settled(receipt):
                    break
                time.sleep(1.5 * (tries + 1))
            if index % 200 == 0:
                handle.flush()
                rate = index / (time.time() - started)
                print(
                    f"  {index}/{len(remaining)}  {rate:.1f}/s  ~{(len(remaining) - index) / rate / 60:.0f} min",
                    flush=True,
                )
    print(f"receipts -> {RECEIPTS.name}; staged bodies -> {staging}", flush=True)


if __name__ == "__main__":
    main(pathlib.Path(sys.argv[1]))
