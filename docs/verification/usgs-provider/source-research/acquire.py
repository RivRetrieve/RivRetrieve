"""Acquire authoritative source documents; no credentials or access bypasses."""

import argparse
import concurrent.futures
import datetime
import gzip
import hashlib
import json
import urllib.error  # noqa: TID251 - standalone source-document evidence acquisition
import urllib.request  # noqa: TID251 - standalone source-document evidence acquisition
from pathlib import Path


def acquire(item, output: Path):
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
            (output / path).write_bytes(gzip.compress(body, mtime=0))
            record["response_file"] = path
    except Exception as error:
        record["error"] = repr(error)
    print(json.dumps(record), flush=True)
    return record


def acquire_documents(requests: Path, output: Path):
    urls = json.loads(requests.read_text())
    output.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda item: acquire(item, output), urls.items()))
    (output / "manifest.json").write_text(
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


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    acquire_documents(args.requests, args.output)


if __name__ == "__main__":
    main()
