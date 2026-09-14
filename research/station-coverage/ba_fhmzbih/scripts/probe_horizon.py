"""Probe every reported period suffix and format variant, preserving each response.

The earlier survey cited a single '_5Y' 404 on one station as grounds for stating that ten
suffixes and three format variants do not exist, and that history beyond one year cannot be
retrieved. One 404 for one guessed filename on one station does not establish that.

This probes the full matrix on several stations and products and preserves every response, so
each reported attempt names the exact station, product and request it concerns. Responses here
are 404/403 bodies of a few hundred bytes carrying no observations.

What this does NOT do: search for undocumented archive routes. Establishing that no
longer-history access method exists anywhere is out of scope; the finding is only that none was
established by these attempts.

Usage: uv run python research/station-coverage/ba_fhmzbih/scripts/probe_horizon.py
Writes: evidence/horizon/<station>_<code>_<variant>.evidence.json
        inventory/horizon_probe.csv
"""

from __future__ import annotations

import base64
import csv
import hashlib
import json
import pathlib
import sys
import time
import urllib.error  # noqa: TID251 - research capture tool, not provider runtime code
import urllib.request  # noqa: TID251 - research capture tool, not provider runtime code

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from workbook_evidence import read_workbook, utc_now  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parents[1]
BASE = "https://vodostaji.voda.ba/data/internet/stations"
USER_AGENT = "RivRetrieve-research/0.1 (station coverage survey; +https://github.com/RivRetrieve/RivRetrieve)"

# (site_no, station_no, source code, stem) - stems differ per product, as the population sweep shows.
TARGETS = [
    ("4", "4024", "Q", "Q"),
    ("1", "1010", "Q", "Q"),
    ("4", "4110", "H", "H"),
    ("1", "1020", "WT", "Tvode"),
]
PERIODS = ["1D", "1W", "1M", "3M", "6M", "1Y", "2Y", "5Y", "10Y", "ALL", "COMPLETE", "HIST"]
FORMATS = [".csv", ".json", ".zip"]


def fetch(url: str) -> tuple[int | str, str, bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read(), ""
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read(), ""
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return "", "", b"", f"{type(error).__name__}: {error}"


def main() -> None:
    rows = []
    directory = HERE / "evidence" / "horizon"
    directory.mkdir(parents=True, exist_ok=True)
    for site_no, station_no, code, stem in TARGETS:
        variants = [f"{stem}_{period}.xlsx" for period in PERIODS]
        variants += [f"{stem}_1Y{suffix}" for suffix in FORMATS]
        variants.append("")  # directory listing
        for variant in variants:
            url = f"{BASE}/{site_no}/{station_no}/{code}/{variant}"
            retrieved_at = utc_now()
            status_code, content_type, raw, transport_error = fetch(url)
            reading = read_workbook(raw) if status_code == 200 and variant.endswith(".xlsx") else None
            label = variant or "directory_listing"
            document: dict = {
                "format_version": 2,
                "evidence_kind": "response_recording",
                "station_no": station_no,
                "product_code": code,
                "attempted_variant": label,
                "request": {"method": "GET", "url": url, "parameters": None, "body": None},
                "response": {
                    "status_code": status_code,
                    "content_type": content_type,
                    "retrieved_at": retrieved_at,
                    "byte_size": len(raw),
                    "response_sha256": hashlib.sha256(raw).hexdigest(),
                },
            }
            if status_code == 200 and reading is not None and reading.populated_measurements > 0:
                # A working period route. Keep the reading and the observed window, not the
                # observation history: this response carries a year or a month of measurements.
                document["retention"] = (
                    "full response bytes not retained: this route served observations. "
                    "The digest is over the exact response; the reading below is derived."
                )
                document["reading"] = {
                    "declared_rows": reading.declared_rows,
                    "data_rows": reading.data_rows,
                    "populated_measurements": reading.populated_measurements,
                    "observed_window_start": reading.observed_window_start,
                    "observed_window_end": reading.observed_window_end,
                }
            else:
                # Refusals and empty responses carry no observations, so keep them whole.
                document["retention"] = "full response bytes retained; this response carries no observation values"
                document["response"]["content_base64"] = base64.b64encode(raw).decode()
            if transport_error:
                document["note"] = f"transport error, not a publisher response: {transport_error}"

            name = f"{station_no}_{code}_{label.replace('.', '_') or 'listing'}.evidence.json"
            (directory / name).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
            rows.append(
                {
                    "station_no": station_no,
                    "site_no": site_no,
                    "product_code": code,
                    "attempted_variant": label,
                    "url": url,
                    "http_status": status_code,
                    "byte_size": len(raw),
                    "served_measurements": bool(reading and reading.populated_measurements > 0),
                    "observed_window_start": reading.observed_window_start if reading else "",
                    "observed_window_end": reading.observed_window_end if reading else "",
                    "retrieved_at": retrieved_at,
                    "evidence_ref": f"evidence/horizon/{name}",
                    "transport_error": transport_error,
                }
            )
            print(f"  {station_no:<6}{code:<4}{label:<16}{status_code}  {len(raw)}b")
            time.sleep(0.25)

    path = HERE / "inventory" / "horizon_probe.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nwrote {len(rows)} attempts -> {path.name}")
    working = [r for r in rows if r["served_measurements"]]
    print(f"routes that served measurements: {sorted({r['attempted_variant'] for r in working})}")


if __name__ == "__main__":
    main()
