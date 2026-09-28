"""Execute each Python fence on one provider page, in its documented order.

Run from the repository root. Supply credentials through the environment.
The output directory retains exact executed code, stdout/stderr and metadata.
"""

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("page", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--revision", required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
text = args.page.read_text()
fences = list(re.finditer(r"^```([^\n]*)\n(.*?)^```", text, re.M | re.S))
namespace = {"__name__": "__main__"}
secrets = [os.environ.get(k, "") for k in ("ANA_IDENTIFICADOR", "ANA_SENHA", "NVE_API_KEY", "USGS_API_KEY")]
report = {
    "page": str(args.page),
    "revision": args.revision,
    "command": ["uv", "run", "python", *sys.argv],
    "python": sys.version,
    "page_sha256": hashlib.sha256(text.encode()).hexdigest(),
    "started_utc": datetime.now(UTC).isoformat(),
    "snippets": [],
    "displayed_output_fences": sum(m[1] == "text" for m in fences),
}
for index, match in enumerate(fences, 1):
    if match[1] != "python":
        continue
    code = match[2]
    (args.output / f"fence-{index}.py.txt").write_text(code)
    output = io.StringIO()
    started = time.monotonic()
    status = "executed"
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        try:
            exec(compile(code, f"{args.page}:fence-{index}", "exec"), namespace)
        except Exception:
            traceback.print_exc()
            status = "failed"
    safe_output = output.getvalue()
    for secret in secrets:
        if secret:
            safe_output = safe_output.replace(secret, "[REDACTED]")
    (args.output / f"fence-{index}.txt").write_text(safe_output)
    report["snippets"].append({"fence": index, "status": status, "seconds": time.monotonic() - started})
    (args.output / "execution.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"{args.page.name} fence {index}: {status}", flush=True)
    if status == "failed":
        break
report["finished_utc"] = datetime.now(UTC).isoformat()
(args.output / "execution.json").write_text(json.dumps(report, indent=2) + "\n")
raise SystemExit(any(item["status"] == "failed" for item in report["snippets"]))
