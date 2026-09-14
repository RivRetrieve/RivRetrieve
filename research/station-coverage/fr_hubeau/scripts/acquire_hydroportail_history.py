"""Re-probe the bounded HydroPortail history sample, keeping a receipt for every window and attempt.

    acquire : HistorySample -> (Receipt table, staged observation-free bodies)   (network)

Replacement capture of the original bounded probe (2026-09-08). That probe kept one row per pair,
recorded only the first window's HTTP status, discarded the second window's status, and treated a
pair it had written - failed or not - as done. Its 96 HTTP 500/404 rows were then read as empty
windows. This script re-probes exactly the same 682 pairs (`inventory/history_sample.csv`), with the
same two windows, and records each window as its own request:

  window 1   01/06/2026 - 08/06/2026
  window 2   01/06/2023 - 08/06/2023   (probed unless window 1 answered with points)

Scope: the entity is the STATION: `/stationhydro/ajax/{code_station}/series`, for H and for Q. A
station's Q series is not the site's Q series that production requests (`/sitehydro/ajax/{code_site}`);
see FINDINGS.md section 5. These results are station-level findings only.

Retention. A body with no series point and no computed statistic carries no observation value and is
kept whole in the staging bundle. Any other body keeps its receipt - exact request URL, HTTP status,
media type, UTC acquisition instant, byte size, SHA-256 of the full bytes - and derived readings
(point count, first and last timestamp, returned series code and metric), and is never written.

Resumable. A (pair, window) is settled only by an HTTP 200 whose body parses as a series. Every other
attempt stays in the receipt table as evidence and is attempted again, under a new request id.

Usage: uv run python research/station-coverage/fr_hubeau/scripts/acquire_hydroportail_history.py <staging.zip>
Output: evidence/hydroportail_history_receipts.csv; bodies appended to <staging.zip>
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

import requests  # noqa: TID251 - research capture tool, not provider runtime code

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from observation_scan import body_carries_observations  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parents[1]
SAMPLE = HERE / "inventory" / "history_sample.csv"
RECEIPTS = HERE / "evidence" / "hydroportail_history_receipts.csv"
BUNDLE = HERE / "evidence" / "hydroportail_history.tar.xz"
HYDROPORTAIL = "https://hydro.eaufrance.fr"
USER_AGENT = "RivRetrieve-research/0.1 (station coverage survey; +https://github.com/RivRetrieve/RivRetrieve)"
GRANDEUR = {"stage_instantaneous": "H", "discharge_instantaneous": "Q"}
WINDOWS = {"1": ("01/06/2026", "08/06/2026"), "2": ("01/06/2023", "08/06/2023")}
FIELDS = [
    "request_id",
    "code_station",
    "product_id",
    "entity_kind",
    "entity_code",
    "native_field",
    "window",
    "window_start",
    "window_end",
    "request_url",
    "retrieved_at",
    "http_status",
    "content_type",
    "response_bytes",
    "response_sha256",
    "series_code",
    "series_metric",
    "points",
    "first_t",
    "last_t",
    "statistics_state",
    "body_retained",
    "request_error",
]
DELAY_SECONDS = 0.4
TIMEOUT_SECONDS = 60
ATTEMPTS_PER_RUN = 2


def read(raw: bytes) -> dict[str, str]:
    """Derived readings of one series body: identity, point count, endpoints. No value survives."""
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"request_error": "body is not JSON"}
    series = document.get("series") if isinstance(document, dict) else None
    if not isinstance(series, dict):
        return {"request_error": "body carries no series object"}
    data = series.get("data") or []
    statistics = document.get("statistics")
    return {
        "series_code": str(series.get("code") or ""),
        "series_metric": str(series.get("metric") or ""),
        "points": str(len(data)),
        "first_t": str(data[0].get("t", "")) if data else "",
        "last_t": str(data[-1].get("t", "")) if data else "",
        "statistics_state": "absent" if statistics is None else ("empty" if not statistics else "populated"),
    }


def attempt(
    session: requests.Session, pair: dict[str, str], window: str, request_id: str, bundle: zipfile.ZipFile
) -> dict[str, str]:
    start, stop = WINDOWS[window]
    grandeur = GRANDEUR[pair["product_id"]]
    params = {
        "hydro_series[startAt]": start,
        "hydro_series[endAt]": stop,
        "hydro_series[variableType]": "simple_and_interpolated_and_hourly_variable",
        "hydro_series[simpleAndInterpolatedAndHourlyVariable]": grandeur,
        "hydro_series[statusData]": "raw",
    }
    url = f"{HYDROPORTAIL}/stationhydro/ajax/{pair['code_station']}/series"
    prepared = session.prepare_request(requests.Request("GET", url, params=params))
    receipt = dict.fromkeys(FIELDS, "")
    receipt.update(
        request_id=request_id,
        code_station=pair["code_station"],
        product_id=pair["product_id"],
        entity_kind="station",
        entity_code=pair["code_station"],
        native_field=grandeur,
        window=window,
        window_start=start,
        window_end=stop,
        request_url=str(prepared.url),
    )
    retrieved_at = datetime.now(UTC)
    receipt["retrieved_at"] = retrieved_at.isoformat().replace("+00:00", "Z")
    try:
        response = session.send(prepared, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as error:
        receipt.update(request_error=f"{type(error).__name__}: {error}", body_retained="False")
        return receipt
    raw = response.content
    receipt.update(
        http_status=str(response.status_code),
        content_type=response.headers.get("Content-Type", ""),
        response_bytes=str(len(raw)),
        response_sha256=hashlib.sha256(raw).hexdigest(),
    )
    if response.status_code == 200:
        receipt.update(read(raw))
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
    return receipt["http_status"] == "200" and receipt["points"] != "" and not receipt["request_error"]


def main(staging: pathlib.Path) -> None:
    with SAMPLE.open(newline="", encoding="utf-8") as handle:
        sample = list(csv.DictReader(handle))
    attempts: dict[tuple[str, str, str], int] = {}
    outcome: dict[tuple[str, str, str], dict[str, str]] = {}
    RECEIPTS.parent.mkdir(parents=True, exist_ok=True)
    if not RECEIPTS.exists() and BUNDLE.exists():  # resume from the packed evidence
        with tarfile.open(BUNDLE, "r:xz") as packed:
            member = packed.extractfile("receipts.csv")
            if member is None:
                raise SystemExit(f"{BUNDLE.name} has no receipts.csv")
            RECEIPTS.write_bytes(member.read())
    if RECEIPTS.exists():
        with RECEIPTS.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row["code_station"], row["product_id"], row["window"])
                attempts[key] = attempts.get(key, 0) + 1
                if settled(row):
                    outcome[key] = row
    print(f"{len(sample)} pairs in the fixed sample; {len(outcome)} windows already settled", flush=True)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    new_file = not RECEIPTS.exists()
    started = time.time()
    with RECEIPTS.open("a", newline="", encoding="utf-8") as handle, zipfile.ZipFile(staging, "a") as bundle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()

        def acquire(pair: dict[str, str], window: str) -> dict[str, str] | None:
            key = (pair["code_station"], pair["product_id"], window)
            if key in outcome:
                return outcome[key]
            for tries in range(ATTEMPTS_PER_RUN):
                attempts[key] = attempts.get(key, 0) + 1
                request_id = f"{key[0]}_{GRANDEUR[key[1]]}_w{window}_a{attempts[key]}"
                receipt = attempt(session, pair, window, request_id, bundle)
                writer.writerow(receipt)
                handle.flush()
                time.sleep(DELAY_SECONDS)
                if settled(receipt):
                    outcome[key] = receipt
                    return receipt
                time.sleep(3.0 * (tries + 1))
            return None

        for index, pair in enumerate(sample, start=1):
            first = acquire(pair, "1")
            if first is None or int(first["points"]) == 0:
                acquire(pair, "2")
            if index % 25 == 0:
                rate = index / (time.time() - started)
                print(f"  {index}/{len(sample)}  ~{(len(sample) - index) / rate / 60:.0f} min", flush=True)
    print(f"receipts -> {RECEIPTS.name}; staged bodies -> {staging}", flush=True)


if __name__ == "__main__":
    main(pathlib.Path(sys.argv[1]))
