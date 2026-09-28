"""Re-fetch the official pages identified by the independent source review."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from urllib.request import urlopen  # noqa: TID251 - independent publisher research, not provider transport

root = Path(__file__).parent
out = root / "source-checks" / "authoritative"
out.mkdir(parents=True, exist_ok=True)
for record in json.loads((root / "source-requests.json").read_text()):
    with urlopen(record["url"], timeout=45) as response:
        body = response.read()
        print(
            json.dumps(
                {
                    "name": record["name"],
                    "url": record["url"],
                    "final_url": response.url,
                    "accessed_utc": datetime.now(UTC).isoformat(),
                    "status": response.status,
                    "sha256": sha256(body).hexdigest(),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    (out / (record["name"] + ".html")).write_bytes(body)
