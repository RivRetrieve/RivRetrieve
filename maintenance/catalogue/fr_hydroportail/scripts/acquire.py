import argparse
import hashlib
import json
from pathlib import Path

from rivretrieve._internal.transport import HttpClient, HttpMethod, TransportRequest


def get(client, out, name, url, params=None):
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
    return r.content


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Acquire one response into an explicit external directory.")
    parser.add_argument("name")
    parser.add_argument("url")
    parser.add_argument("params", nargs="?", type=json.loads)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out = args.out.resolve()
    if any((parent / ".git").exists() for parent in (args.out, *args.out.parents)):
        parser.error("Output must be outside source checkouts")
    if not args.name or Path(args.name).name != args.name or args.name in {".", ".."}:
        parser.error("name must be a single filename stem")
    args.out.mkdir(parents=True, exist_ok=True)
    get(HttpClient(), args.out, args.name, args.url, args.params)
