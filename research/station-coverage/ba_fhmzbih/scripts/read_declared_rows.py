"""Read the source-declared '#Rows' header from every station x product workbook.

'#Rows' is the publisher's own statement of how many observations the rolling
workbook contains. It is authoritative in a way that Content-Length is not, so it is
used as the availability basis for the evidence inventory.

Small workbooks (header-only candidates) are fetched in full because they are ~3.6 KB.
Large workbooks are NOT downloaded in full merely to confirm they are non-empty; for
those the recorded boundary cases plus Content-Length establish the class. Pass --all
to fetch every workbook (~15 MB) if a reviewer wants the declared count everywhere.

Usage: uv run python research/.../scripts/read_declared_rows.py [--all]
"""

from __future__ import annotations

import io
import pathlib
import sys
import time
import urllib.error  # noqa: TID251 - research capture tool, not provider runtime code
import urllib.request  # noqa: TID251 - research capture tool, not provider runtime code
import warnings
from datetime import UTC, datetime

import pandas as pd

warnings.filterwarnings("ignore")
HERE = pathlib.Path(__file__).resolve().parents[1]
PROBE = HERE / "inventory" / "workbook_probe.csv"
OUT = HERE / "inventory" / "declared_rows.csv"
USER_AGENT = "RivRetrieve-research/0.1 (station coverage survey; +https://github.com/RivRetrieve/RivRetrieve)"
SMALL_MAX_BYTES = 10_000


def declared_rows(url: str) -> tuple[object, object, str]:
    """Return (declared_rows, unit_symbol, error) read from the workbook header block."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as error:
        return "", "", f"{type(error).__name__}: {error}"
    try:
        frame = pd.read_excel(io.BytesIO(raw), header=None)
    except Exception as error:  # noqa: BLE001 - record any decode failure verbatim
        return "", "", f"decode_error: {type(error).__name__}: {error}"
    labels = frame[0].astype(str)
    rows = frame.loc[labels == "#Rows", 1]
    unit = frame.loc[labels == "#Unit Symbol", 1]
    return (
        rows.iloc[0] if len(rows) else "",
        unit.iloc[0] if len(unit) else "",
        "",
    )


def main() -> None:
    fetch_all = "--all" in sys.argv
    probe = pd.read_csv(PROBE, dtype=str)
    probe["content_length"] = pd.to_numeric(probe.content_length, errors="coerce")
    targets = probe if fetch_all else probe[probe.content_length <= SMALL_MAX_BYTES]
    print(f"reading #Rows for {len(targets)} of {len(probe)} workbooks{' (--all)' if fetch_all else ' (small only)'}")
    records = []
    for count, row in enumerate(targets.itertuples(), start=1):
        value, unit, error = declared_rows(str(row.url))
        records.append(
            {
                "station_no": row.station_no,
                "product_id": row.product_id,
                "url": row.url,
                "content_length": row.content_length,
                "declared_rows": value,
                "declared_unit": unit,
                "read_error": error,
                "read_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            }
        )
        if count % 10 == 0:
            print(f"  {count}/{len(targets)}", flush=True)
        time.sleep(0.25)
    pd.DataFrame(records).to_csv(OUT, index=False)
    print(f"wrote {len(records)} rows -> {OUT.name}")


if __name__ == "__main__":
    main()
