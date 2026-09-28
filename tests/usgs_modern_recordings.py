"""Exact-coordinate replay of USGS publisher captures, without invented execution headers.

The evidence recorder used its own User-Agent. This helper asserts complete URL
and query coordinates and hashes, but does not claim engine execution metadata.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from rivretrieve._internal.transport import HttpMethod, TransportResponse

DATA = Path(__file__).parent / "test_data" / "usgs_modern"
MANIFEST = {
    item["name"]: item
    for path in sorted(DATA.glob("*-manifest.jsonl"))
    for item in (json.loads(line) for line in path.read_text().splitlines())
}


def body(name):
    entry = MANIFEST[name]
    content = (DATA / entry["file"]).read_bytes()
    assert len(content) == entry["bytes"]
    assert hashlib.sha256(content).hexdigest() == entry["sha256"]
    return content


def coordinates(url, params=None):
    parsed = urlsplit(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.extend((key, str(value)) for key, value in (params or {}).items() if value is not None)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")), tuple(sorted(query))


class ModernReplay:
    def __init__(self, *names):
        self.entries = {coordinates(MANIFEST[name]["original_url"]): name for name in names}
        self.calls = []

    def send(self, request):
        assert request.method is HttpMethod.GET
        self.calls.append(request)
        key = coordinates(request.url, request.params)
        assert key in self.entries, f"No exact modern recording for {key}"
        name = self.entries[key]
        entry = MANIFEST[name]
        return TransportResponse(
            content=body(name),
            status_code=entry["status"],
            retrieved_at=datetime.fromisoformat(entry["acquired_utc"]),
            content_type=entry["headers"].get("Content-Type"),
            url=request.url,
            request_parameters=request.params or {},
        )
