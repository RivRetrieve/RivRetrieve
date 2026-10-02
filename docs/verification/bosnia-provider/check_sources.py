"""Re-fetch the official pages identified by the independent source review."""

import argparse
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from urllib.request import urlopen  # noqa: TID251 - independent publisher research, not provider transport

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source-requests", type=Path, required=True, help="External retained request manifest")
parser.add_argument("--out", type=Path, required=True, help="Output directory outside the checkout")
args = parser.parse_args()
out = args.out
out.mkdir(parents=True, exist_ok=True)
for record in json.loads(args.source_requests.read_text()):
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
