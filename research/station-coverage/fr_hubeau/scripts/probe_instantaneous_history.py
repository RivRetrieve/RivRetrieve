"""Re-probe instantaneous pairs that read zero on the 30-day route, against HydroPortail.

`observations_tr` serves a rolling 30 days, so a zero there means "nothing in the last month", never
"this station does not publish this measurement". Every zero is therefore re-probed against
HydroPortail - the route actually used in production - over a window far outside the real-time one,
before any negative is recorded.

Scope: pairs whose station is `en_service = True` in the committed referential. All 2,314 closed
stations read zero on the real-time route with no exceptions, which is the expected behaviour of a
real-time route and is reported as such rather than re-probed one by one.

HydroPortail answers an empty window in about 800 bytes, but each request takes several seconds, so
an exhaustive probe of every in-service zero is not proportionate against a public portal. This
script therefore probes a bounded sample (SAMPLE_LIMIT), reuses one HTTP connection, and records what
it establishes. Pairs it does not reach stay `uninvestigated` in the inventory - never reclassified
as source absence.

Rows are appended as obtained and re-running resumes; rows that failed transport are retried.

Usage: uv run python research/station-coverage/fr_hubeau/scripts/probe_instantaneous_history.py
Output: inventory/instantaneous_history.csv
"""

from __future__ import annotations

import csv
import pathlib
import time
from datetime import UTC, datetime

import pandas as pd
import requests  # noqa: TID251 - research capture tool, not provider runtime code

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = pathlib.Path(__file__).resolve().parents[3].parent
NATIVE = ROOT / "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet"
COUNTS = HERE / "inventory" / "instantaneous_counts.csv"
OUT = HERE / "inventory" / "instantaneous_history.csv"

HYDROPORTAIL = "https://hydro.eaufrance.fr"
USER_AGENT = "RivRetrieve-research/0.1 (station coverage survey; +https://github.com/RivRetrieve/RivRetrieve)"
GRANDEUR = {"stage_instantaneous": "H", "discharge_instantaneous": "Q"}
# Two windows well outside the 30-day real-time horizon, one recent-historical and one older.
WINDOWS = (("01/06/2026", "08/06/2026"), ("01/06/2023", "08/06/2023"))
FIELDS = (
    "code_station",
    "code_site",
    "product_id",
    "native_field",
    "route",
    "http_status",
    "points_window_1",
    "points_window_2",
    "windows",
    "request_error",
    "probed_at",
)
DELAY_SECONDS = 0.4
TIMEOUT_SECONDS = 45
RETRIES = 2
SAMPLE_LIMIT = 400

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})


def probe(station: str, grandeur: str, start: str, stop: str) -> tuple[object, object, str]:
    """Return (status, point count, error) for one window, over a reused connection."""
    params = {
        "hydro_series[startAt]": start,
        "hydro_series[endAt]": stop,
        "hydro_series[variableType]": "simple_and_interpolated_and_hourly_variable",
        "hydro_series[simpleAndInterpolatedAndHourlyVariable]": grandeur,
        "hydro_series[statusData]": "raw",
    }
    url = f"{HYDROPORTAIL}/stationhydro/ajax/{station}/series"
    last = ""
    for attempt in range(RETRIES):
        try:
            response = _SESSION.get(url, params=params, timeout=TIMEOUT_SECONDS)
            if response.status_code != 200:
                return response.status_code, "", ""
            series = response.json().get("series") or {}
            data = series.get("data") if isinstance(series, dict) else None
            return response.status_code, len(data or []), ""
        except (requests.RequestException, ValueError) as error:
            last = f"{type(error).__name__}: {error}"
            if attempt < RETRIES - 1:
                time.sleep(3.0)
                continue
    return "", "", last


def main() -> None:
    counts = pd.read_csv(COUNTS, dtype=str)
    counts["n"] = pd.to_numeric(counts["count"], errors="coerce")
    native = pd.read_parquet(NATIVE)
    service = native[native.source_endpoint == "hydrometrie/referentiel/stations"][["code_station", "en_service"]]
    service["code_station"] = service.code_station.astype(str)
    merged = counts.merge(service, on="code_station", how="left")
    targets = merged[(merged.n == 0) & (merged.en_service)]

    settled: set[tuple[str, str]] = set()
    if OUT.exists():
        prior = pd.read_csv(OUT, dtype=str)
        settled = set(zip(prior.code_station, prior.product_id, strict=False))
    remaining = [row for row in targets.itertuples() if (row.code_station, row.product_id) not in settled]
    remaining = remaining[:SAMPLE_LIMIT]
    print(
        f"{len(targets)} in-service zero pairs; {len(settled)} settled; probing {len(remaining)} "
        f"(sample limit {SAMPLE_LIMIT}); the rest stay uninvestigated",
        flush=True,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    new_file = not OUT.exists()
    started = time.time()
    with OUT.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        for index, row in enumerate(remaining, start=1):
            grandeur = GRANDEUR[row.product_id]
            status, first, error = probe(str(row.code_station), grandeur, *WINDOWS[0])
            second: object = ""
            if not error and first == 0:
                _, second, error = probe(str(row.code_station), grandeur, *WINDOWS[1])
            writer.writerow(
                {
                    "code_station": row.code_station,
                    "code_site": row.code_site,
                    "product_id": row.product_id,
                    "native_field": grandeur,
                    "route": "hydroportail",
                    "http_status": status,
                    "points_window_1": first,
                    "points_window_2": second,
                    "windows": f"{WINDOWS[0][0]}-{WINDOWS[0][1]} then {WINDOWS[1][0]}-{WINDOWS[1][1]}",
                    "request_error": error,
                    "probed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                }
            )
            if index % 25 == 0:
                handle.flush()
                rate = index / (time.time() - started)
                print(
                    f"  {index}/{len(remaining)}  {rate:.1f}/s  ~{(len(remaining) - index) / rate / 60:.0f} min",
                    flush=True,
                )
            time.sleep(DELAY_SECONDS)
    print(f"wrote {len(remaining)} rows -> {OUT.name}", flush=True)


if __name__ == "__main__":
    main()
