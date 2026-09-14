"""Capture official ThaiWater responses as durable recordings.

Follows the repository recording convention used by tests/test_data/*.recording.json: exact
request URL and query parameters, HTTP status, media type, UTC retrieval instant, raw response
bytes (base64) and SHA-256.

Usage:
    uv run python .../capture.py <recording_id> <url> [key=value ...]

Read-only against public, unauthenticated endpoints. No credentials, cookies or tokens are sent
or stored.
"""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import sys
import urllib.error  # noqa: TID251 - research capture tool, not provider runtime code
import urllib.parse  # noqa: TID251 - research capture tool, not provider runtime code
import urllib.request  # noqa: TID251 - research capture tool, not provider runtime code
from datetime import UTC, datetime

RECORDINGS = pathlib.Path(__file__).resolve().parents[1] / "recordings"
USER_AGENT = "RivRetrieve-research/0.1 (station coverage survey; +https://github.com/RivRetrieve/RivRetrieve)"


def capture(recording_id: str, url: str, params: dict[str, str] | None = None) -> pathlib.Path:
    full = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    request = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
    retrieved_at = datetime.now(UTC)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            content, status = response.read(), response.status
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as error:  # record the refusal itself, never discard it
        content, status = error.read(), error.code
        content_type = error.headers.get("Content-Type", "") if error.headers else ""

    document = {
        "format_version": 1,
        "request": {"method": "GET", "url": url, "parameters": params, "body": None},
        "response": {
            "status_code": status,
            "content_type": content_type,
            "retrieved_at": retrieved_at.isoformat().replace("+00:00", "Z"),
            "content_base64": base64.b64encode(content).decode("ascii"),
            "sha256": hashlib.sha256(content).hexdigest(),
        },
    }
    RECORDINGS.mkdir(parents=True, exist_ok=True)
    path = RECORDINGS / f"{recording_id}.recording.json"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"{status} {len(content):>9,}B  sha256:{document['response']['sha256'][:12]}  -> {path.name}")
    return path


if __name__ == "__main__":
    recording_id, url = sys.argv[1], sys.argv[2]
    parsed = dict(item.split("=", 1) for item in sys.argv[3:]) or None
    capture(recording_id, url, parsed)
