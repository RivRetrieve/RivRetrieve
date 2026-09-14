"""Capture official ba_fhmzbih source responses as durable recordings.

Follows the repository recording convention used by tests/test_data/*.recording.json:
exact request, HTTP status, media type, UTC retrieval instant, raw bytes (base64), SHA-256.

Usage:  uv run python research/station-coverage/ba_fhmzbih/scripts/capture.py <url> <recording_id>

Read-only against public, unauthenticated endpoints. No credentials, cookies or tokens
are sent or stored. Re-running overwrites the named recording with a fresh capture.
"""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import sys
import urllib.error  # noqa: TID251 - research capture tool, not provider runtime code
import urllib.request  # noqa: TID251 - research capture tool, not provider runtime code
from datetime import UTC, datetime

RECORDINGS = pathlib.Path(__file__).resolve().parents[1] / "recordings"
USER_AGENT = "RivRetrieve-research/0.1 (station coverage survey; +https://github.com/RivRetrieve/RivRetrieve)"


def capture(url: str, recording_id: str) -> pathlib.Path:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    retrieved_at = datetime.now(UTC)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            content = response.read()
            status_code = response.status
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as error:  # record the refusal itself, do not discard it
        content = error.read()
        status_code = error.code
        content_type = error.headers.get("Content-Type", "") if error.headers else ""

    document = {
        "format_version": 1,
        "request": {"method": "GET", "url": url, "parameters": None, "body": None},
        "response": {
            "status_code": status_code,
            "content_type": content_type,
            "retrieved_at": retrieved_at.isoformat().replace("+00:00", "Z"),
            "content_base64": base64.b64encode(content).decode("ascii"),
            "sha256": hashlib.sha256(content).hexdigest(),
        },
    }
    RECORDINGS.mkdir(parents=True, exist_ok=True)
    path = RECORDINGS / f"{recording_id}.recording.json"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"{status_code} {len(content):>8}B  sha256:{document['response']['sha256'][:12]}  -> {path.name}")
    return path


if __name__ == "__main__":
    capture(sys.argv[1], sys.argv[2])
