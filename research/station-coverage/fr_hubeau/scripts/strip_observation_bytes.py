# Historical research utility; not project policy or a certification/publication gate.
# Full governing evidence is retained privately; do not run stripping on that corpus.
"""Remove publisher observation values from the committed recordings, keeping receipts and readings.

    strip : Recording -> Recording   (idempotent; a recording already stripped is left unchanged)

This project does not redistribute source observations. A recording whose body carries no
observation value (a count-only page, an empty result, an error, station metadata) keeps its bytes
whole. A recording whose body carries observations keeps its exact request, HTTP status, media type,
UTC acquisition instant, byte size and SHA-256 of the full bytes, plus derived readings
(`readings.derive`), and loses the bytes. The stored digest is checked against the bytes before they
are removed. Original acquisition instants are kept as recorded; nothing is re-dated.

Usage: uv run python research/station-coverage/fr_hubeau/scripts/strip_observation_bytes.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from observation_scan import body_carries_observations  # noqa: E402
from readings import derive  # noqa: E402

RECORDINGS = pathlib.Path(__file__).resolve().parents[1] / "recordings"


def main() -> None:
    for path in sorted(RECORDINGS.glob("*.recording.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        response = document["response"]
        if "body_retained" in response:
            print(f"  already processed  {path.name}")
            continue
        raw = base64.b64decode(response["content_base64"])
        if hashlib.sha256(raw).hexdigest() != response["sha256"]:
            raise SystemExit(f"{path.name}: stored SHA-256 does not match stored bytes; refusing to strip")
        carries = body_carries_observations(raw)
        stored: dict[str, object] = {
            "status_code": response["status_code"],
            "content_type": response["content_type"],
            "retrieved_at": response["retrieved_at"],
            "response_bytes": len(raw),
            "sha256": response["sha256"],
            "body_retained": not carries,
        }
        if not carries:
            stored["content_base64"] = response["content_base64"]
        stored["reading"] = derive(raw)
        document["response"] = stored
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"  {'KEPT WHOLE' if not carries else 'stripped  '}  {path.name}  ({len(raw):,} B)")


if __name__ == "__main__":
    main()
