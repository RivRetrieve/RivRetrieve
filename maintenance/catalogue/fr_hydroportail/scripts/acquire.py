import hashlib
import json
import sys
from pathlib import Path

from rivretrieve._internal.transport import HttpClient, HttpMethod, TransportRequest

out = Path(__file__).resolve().parents[1] / "evidence"
client = HttpClient()


def get(name, url, params=None):
    r = client.send(TransportRequest(HttpMethod.GET, url, params=params))
    (out / (name + ".body")).write_bytes(r.content)
    (out / (name + ".receipt.json")).write_text(
        json.dumps(
            {
                "url": url,
                "params": params,
                "status": r.status_code,
                "retrieved_at": r.retrieved_at.isoformat(),
                "content_type": r.content_type,
                "bytes": len(r.content),
                "sha256": hashlib.sha256(r.content).hexdigest(),
            },
            indent=2,
        )
    )
    print(name, r.status_code, len(r.content), flush=True)
    return r.content


if __name__ == "__main__":
    get(sys.argv[1], sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else None)
