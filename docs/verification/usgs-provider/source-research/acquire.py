"""Acquire authoritative source documents; no credentials or access bypasses."""

import concurrent.futures
import datetime
import gzip
import hashlib
import json
import sys
import urllib.error  # noqa: TID251 - standalone source-document evidence acquisition
import urllib.request  # noqa: TID251 - standalone source-document evidence acquisition
from pathlib import Path

BASE = Path(__file__).parent
suffix = sys.argv[1] if len(sys.argv) > 1 else ""
urls = json.loads((BASE / ("requests" + suffix + ".json")).read_text())


def acquire(item):
    name, url = item
    record = {"name": name, "requested_url": url, "acquired_at_utc": datetime.datetime.now(datetime.UTC).isoformat()}
    try:
        request = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
        try:
            response = urllib.request.urlopen(request, timeout=45)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read()
            record.update(
                status=response.status,
                final_url=response.url,
                headers=dict(response.headers),
                bytes=len(body),
                sha256=hashlib.sha256(body).hexdigest(),
            )
            path = name + ".response.gz"
            (BASE / path).write_bytes(gzip.compress(body, mtime=0))
            record["response_file"] = path
    except Exception as error:
        record["error"] = repr(error)
    print(json.dumps(record), flush=True)
    return record


with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(acquire, urls.items()))
(BASE / ("manifest" + suffix + ".json")).write_text(
    json.dumps(
        {
            "method": "Fresh HTTP GET; unmodified HTTP entity bytes saved; Accept-Encoding identity; no credentials; HTTP headers saved in manifest",
            "storage": "Deterministic gzip (mtime=0); bytes and sha256 describe the decompressed, unmodified HTTP entity bytes, not the gzip container.",
            "records": results,
        },
        indent=2,
    )
    + "\n"
)
