"""Establish per-station availability for the two instantaneous products (H and Q).

The sub-daily products are served in production from HydroPortail. HydroPortail returns the whole
series for a requested window, so probing 6,454 stations there would download observation data purely
to establish support, which issue #222 rules out.

Hub'Eau `observations_tr` publishes the same two measurements and answers with a `count` for ~200
bytes. It is used here as the availability instrument only - not as a proposal to change the
production route, which `ROUTE_DECISIONS.md` argues against.

The instrument has a limit that must be stated with every result it produces: `observations_tr`
serves a rolling 30-day window and refuses anything older with HTTP 400 `ValidateDateMin`. A count of
zero therefore means "no observation in the last 30 days", never "this station does not publish this
measurement". Stations reading zero are re-probed against HydroPortail over a wide window by
`probe_instantaneous_history.py` before any negative claim is recorded.

Rows are appended as they are obtained and re-running resumes: pairs already carrying a count are
skipped, while rows recorded with a transport error are retried.

Usage: uv run python research/station-coverage/fr_hubeau/scripts/sweep_instantaneous.py
Output: inventory/instantaneous_counts.csv
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
OUT = HERE / "inventory" / "instantaneous_counts.csv"

OBSERVATIONS_TR = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/observations_tr"
USER_AGENT = "RivRetrieve-research/0.1 (station coverage survey; +https://github.com/RivRetrieve/RivRetrieve)"

# (product_id, grandeur_hydro) exactly as declared in the provider config.
PRODUCTS = (("stage_instantaneous", "H"), ("discharge_instantaneous", "Q"))
FIELDS = (
    "code_station",
    "code_site",
    "product_id",
    "native_field",
    "route",
    "http_status",
    "count",
    "window",
    "request_error",
    "probed_at",
)
WINDOW_NOTE = "rolling 30 days (observations_tr publisher limit)"
DELAY_SECONDS = 0.1
TIMEOUT_SECONDS = 30
RETRIES = 3


def query(params: dict[str, str]) -> dict[str, object]:
    target = f"{OBSERVATIONS_TR}?{urllib.parse.urlencode(params)}"
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


def _settled_pairs() -> set[tuple[str, str]]:
    if not OUT.exists():
        return set()
    existing = pd.read_csv(OUT, dtype=str)
    settled = existing[existing["count"].notna() & (existing["count"].astype(str).str.strip() != "")]
    return set(zip(settled.code_station, settled.product_id, strict=False))


def main() -> None:
    native = pd.read_parquet(NATIVE)
    hydro = native[native.source_endpoint == "hydrometrie/referentiel/stations"]

    tasks = [
        (str(row.code_station), str(row.code_site), product_id, grandeur)
        for row in hydro.itertuples()
        for product_id, grandeur in PRODUCTS
    ]
    settled = _settled_pairs()
    remaining = [task for task in tasks if (task[0], task[2]) not in settled]
    print(f"{len(tasks)} pairs; {len(settled)} settled; {len(remaining)} to do", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    new_file = not OUT.exists()
    started = time.time()
    with OUT.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        for index, (station, site, product_id, grandeur) in enumerate(remaining, start=1):
            result = query({"code_entite": station, "grandeur_hydro": grandeur, "size": "1"})
            writer.writerow(
                {
                    "code_station": station,
                    "code_site": site,
                    "product_id": product_id,
                    "native_field": grandeur,
                    "route": "observations_tr",
                    **result,
                    "window": WINDOW_NOTE,
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
