"""Save a web page as evidence, with its address, the instant, and a digest.

Research apparatus for the source-terms survey. Not library code and not shipped:
it lives outside ``src/`` and is excluded from lint, typecheck and both distributions.

Usage:

    python research/source-terms/record.py <provider_id> <slot> <url>

where ``slot`` is ``licence`` or ``citation`` (or any short label, for a page that
supports one of the two). Writes two files under
``research/source-terms/<provider_id>/pages/``:

    <slot>-<n>.html   the exact bytes the server returned
    <slot>-<n>.json   the address, the retrieval instant in UTC, and the SHA-256

Re-running never overwrites: each capture gets the next free number, so a page that
changed under you leaves both versions on disk.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
USER_AGENT = "RivRetrieve-source-terms-survey/1.0 (+https://github.com/RivRetrieve/RivRetrieve)"


def record(provider_id: str, slot: str, url: str) -> Path:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response:  # noqa: S310
        body = response.read()
        final_url = response.geturl()
        content_type = response.headers.get("Content-Type", "")
    retrieved_at = datetime.now(UTC).replace(microsecond=0).isoformat()

    suffix = ".html"
    for kind, ext in (("pdf", ".pdf"), ("json", ".body.json"), ("csv", ".csv"), ("xml", ".xml"), ("html", ".html")):
        if kind in content_type.lower():
            suffix = ext
            break
    else:
        if "text" in content_type.lower():
            suffix = ".txt"

    pages = ROOT / provider_id / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    n = 1
    while (pages / f"{slot}-{n}.json").exists():
        n += 1
    stem = pages / f"{slot}-{n}"

    (pages / f"{stem.name}{suffix}").write_bytes(body)
    stem.with_suffix(".json").write_text(
        json.dumps(
            {
                "requested_url": url,
                "final_url": final_url,
                "retrieved_at": retrieved_at,
                "content_type": content_type,
                "file": f"{stem.name}{suffix}",
                "sha256": hashlib.sha256(body).hexdigest(),
                "bytes": len(body),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return stem


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    _, provider_id, slot, url = sys.argv
    try:
        stem = record(provider_id, slot, url)
    except Exception as exc:
        print(f"FAILED to record {url}: {exc}")
        print("If the page needs a browser, a login or a captcha, say so in the form's Notes")
        print("and save the page by hand with your browser's Save As into the pages/ folder.")
        return 1
    saved = json.loads(stem.with_suffix(".json").read_text(encoding="utf-8"))["file"]
    print(f"saved {(stem.parent / saved).relative_to(ROOT.parent.parent)}")
    print(f"      {stem.with_suffix('.json').relative_to(ROOT.parent.parent)}")
    print(f"put this in the form's 'Recording' field: {stem.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
