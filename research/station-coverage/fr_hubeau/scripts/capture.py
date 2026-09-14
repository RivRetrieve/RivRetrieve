"""Capture one official response as a recording, never storing an observation value.

    capture : (RecordingId, Url, Parameters) -> Recording   (network)

Follows the repository recording convention used by tests/test_data/*.recording.json - exact request
URL and query parameters, HTTP status, media type, UTC retrieval instant, byte size and SHA-256 of the
full bytes - with one restriction: this project does not redistribute source observations. The bytes
(base64) are kept only when the body carries no observation value (a count-only page, an empty series,
an error, a documentation page). Otherwise the recording keeps the receipt and derived readings
(`readings.derive`) and the bytes are never written.

Usage:
    uv run python .../capture.py <recording_id> <url> [key=value ...]

Read-only against public, unauthenticated endpoints. No credentials, cookies or tokens are sent or
stored.
"""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import sys
from datetime import UTC, datetime

import requests  # noqa: TID251 - research capture tool, not provider runtime code

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from observation_scan import body_carries_observations  # noqa: E402
from readings import derive, page_text  # noqa: E402

RECORDINGS = pathlib.Path(__file__).resolve().parents[1] / "recordings"
USER_AGENT = "RivRetrieve-research/0.1 (station coverage survey; +https://github.com/RivRetrieve/RivRetrieve)"


def capture(
    recording_id: str, url: str, params: dict[str, str] | None = None, quotes: tuple[str, ...] = ()
) -> tuple[pathlib.Path, bytes]:
    """Write the recording and return it with the response bytes, which the caller must not store.

    Each quote must be a slice of the page's visible text (`readings.page_text`); a quote that is not
    found stops the capture rather than being recorded as though the page said it.
    """
    retrieved_at = datetime.now(UTC)
    response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=180)
    raw = response.content
    text = page_text(raw) if quotes else ""
    missing = [quote for quote in quotes if quote not in text]
    if missing:
        raise SystemExit(f"{recording_id}: quoted passage not found in the response: {missing}")
    carries = body_carries_observations(raw)
    stored: dict[str, object] = {
        "status_code": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
        "retrieved_at": retrieved_at.isoformat().replace("+00:00", "Z"),
        "response_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "body_retained": not carries,
    }
    if not carries:
        stored["content_base64"] = base64.b64encode(raw).decode("ascii")
    if quotes:
        stored["reading"] = {"parse": "page_text", "quotes": list(quotes)}
    elif not response.headers.get("Content-Type", "").startswith("text/html"):
        stored["reading"] = derive(raw)
    document = {
        "format_version": 1,
        "request": {"method": "GET", "url": url, "parameters": params, "body": None, "sent_url": response.url},
        "response": stored,
    }
    RECORDINGS.mkdir(parents=True, exist_ok=True)
    path = RECORDINGS / f"{recording_id}.recording.json"
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    kept = "kept whole" if not carries else "receipt + readings only"
    print(f"{response.status_code} {len(raw):>9,}B  sha256:{stored['sha256'][:12]}  {kept}  -> {path.name}")
    return path, raw


if __name__ == "__main__":
    recording_id, url = sys.argv[1], sys.argv[2]
    parsed = dict(item.split("=", 1) for item in sys.argv[3:]) or None
    capture(recording_id, url, parsed)
