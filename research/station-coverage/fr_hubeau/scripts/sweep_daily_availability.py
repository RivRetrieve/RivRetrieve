"""Establish per-station availability for the Hub'Eau daily and temperature products.

Method: one request per station and product with `size=1` and no date filter, reading the response's
`count`. `count` is the publisher's own total for that station and product over its whole record, so
availability rests on a published total rather than on whether data happens to fall inside a tested
window. Responses are ~200 bytes; no observation history is downloaded.

This deliberately avoids the window-bias trap recorded as discoveries D11: a station that reports
rarely cannot be mistaken for a station with no data, because no window is applied at all.

Rows are appended to the output as they are obtained, so an interrupted run keeps its work and can be
resumed by re-running: station/product pairs already present in the file are skipped.

Usage: uv run python research/station-coverage/fr_hubeau/scripts/sweep_daily_availability.py
Output: inventory/hubeau_counts.csv (one row per station x product, none omitted)
"""

from __future__ import annotations

import csv
import json
import pathlib
import time
import urllib.error  # noqa: TID251 - research capture tool, not provider runtime code
import urllib.parse  # noqa: TID251 - research capture tool, not provider runtime code
import urllib.request  # noqa: TID251 - research capture tool, not provider runtime code
from datetime import UTC, datetime

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = pathlib.Path(__file__).resolve().parents[3].parent
NATIVE = ROOT / "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet"
OUT = HERE / "inventory" / "hubeau_counts.csv"

OBS_ELAB = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab"
TEMPERATURE = "https://hubeau.eaufrance.fr/api/v1/temperature/chronique"
USER_AGENT = "RivRetrieve-research/0.1 (station coverage survey; +https://github.com/RivRetrieve/RivRetrieve)"

# (product_id, grandeur_hydro_elab) exactly as declared in the provider config.
DAILY_PRODUCTS = (
    ("discharge_daily_mean", "QmnJ"),
    ("discharge_daily_max", "QIXnJ"),
    ("stage_daily_max", "HIXnJ"),
)
FIELDS = (
    "code_station",
    "code_site",
    "product_id",
    "native_field",
    "route",
    "http_status",
    "count",
    "request_error",
    "probed_at",
)
DELAY_SECONDS = 0.1
TIMEOUT_SECONDS = 30
RETRIES = 3


def query(url: str, params: dict[str, str]) -> dict[str, object]:
    """Return the published count, retrying transient failures rather than recording them as absence."""
    target = f"{url}?{urllib.parse.urlencode(params)}"
    last = ""
    for attempt in range(RETRIES):
        request = urllib.request.Request(target, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                document = json.loads(response.read())
                return {"http_status": response.status, "count": document.get("count"), "request_error": ""}
        except urllib.error.HTTPError as error:
            last = f"HTTP {error.code}"
            if error.code in (500, 502, 503, 504) and attempt < RETRIES - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            return {"http_status": error.code, "count": "", "request_error": ""}
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            last = f"{type(error).__name__}: {error}"
            if attempt < RETRIES - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
    return {"http_status": "", "count": "", "request_error": last}


def _done_pairs() -> set[tuple[str, str]]:
    """Pairs that already carry a published count.

    Only rows with a count are treated as done. A row recorded with a transport error - for example
    because the machine slept mid-request - is retried on the next run rather than being mistaken for
    an established absence.
    """
    if not OUT.exists():
        return set()
    existing = pd.read_csv(OUT, dtype=str)
    settled = existing[existing["count"].notna() & (existing["count"].astype(str).str.strip() != "")]
    return set(zip(settled.code_station, settled.product_id, strict=False))


def main() -> None:
    native = pd.read_parquet(NATIVE)
    hydro = native[native.source_endpoint == "hydrometrie/referentiel/stations"]
    temperature = native[native.source_endpoint == "temperature/station"]

    tasks: list[tuple[str, str, str, str, str, dict[str, str]]] = []
    for row in hydro.itertuples():
        station, site = str(row.code_station), str(row.code_site)
        for product_id, grandeur in DAILY_PRODUCTS:
            tasks.append(
                (
                    station,
                    site,
                    product_id,
                    grandeur,
                    "obs_elab",
                    {"code_entite": station, "grandeur_hydro_elab": grandeur, "size": "1", "fields": "code_station"},
                )
            )
    for row in temperature.itertuples():
        station = str(row.code_station)
        tasks.append(
            (
                station,
                "",
                "water_temperature_reported",
                "resultat",
                "temperature/chronique",
                {"code_station": station, "size": "1", "fields": "code_station"},
            )
        )

    done = _done_pairs()
    remaining = [task for task in tasks if (task[0], task[2]) not in done]
    print(f"{len(tasks)} station x product pairs; {len(done)} already recorded; {len(remaining)} to do", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    new_file = not OUT.exists()
    started = time.time()
    with OUT.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        for index, (station, site, product_id, native_field, route, params) in enumerate(remaining, start=1):
            url = OBS_ELAB if route == "obs_elab" else TEMPERATURE
            result = query(url, params)
            writer.writerow(
                {
                    "code_station": station,
                    "code_site": site,
                    "product_id": product_id,
                    "native_field": native_field,
                    "route": route,
                    **result,
                    "probed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                }
            )
            if index % 100 == 0:
                handle.flush()
                rate = index / (time.time() - started)
                left = (len(remaining) - index) / rate / 60 if rate else 0
                print(f"  {index}/{len(remaining)}  {rate:.1f} req/s  ~{left:.0f} min left", flush=True)
            time.sleep(DELAY_SECONDS)
    print(f"wrote {len(remaining)} rows -> {OUT.name}", flush=True)


if __name__ == "__main__":
    main()
