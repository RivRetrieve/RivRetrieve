"""Execute final French page snippets live and retain exact source exchanges.

Run from the repository root with an explicit new evidence directory.
This does not edit the pages or substitute expected output.
"""

import argparse
import hashlib
import io
import json
import re
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.recordings import RecordingTransport, write_recording
from rivretrieve._internal.transport import HttpClient

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    report = {"checked_at": datetime.now(UTC).isoformat(), "pages": []}
    for provider in ("fr_hubeau", "fr_hydroportail"):
        path = ROOT / f"docs/providers/{provider}.md"
        page = path.read_text()
        blocks = re.findall(r"```python\n(.*?)```\n\nOutput:\n\n```text\n(.*?)```", page, re.DOTALL)
        assert len(blocks) == page.count("```python")
        recorder = RecordingTransport(HttpClient())
        discovery.HttpClient = lambda recorder=recorder: recorder
        namespace = {}
        entry = {
            "page": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "blocks": [],
        }
        for index, (code, expected) in enumerate(blocks, 1):
            output = io.StringIO()
            with redirect_stdout(output):
                exec(compile(code, f"{path.name}:block-{index}", "exec"), namespace)
            entry["blocks"].append(
                {"index": index, "stdout": output.getvalue(), "matches": output.getvalue() == expected}
            )
        result = namespace["result"]
        entry["issues"] = [
            {"severity": issue.severity, "code": issue.code, "message": issue.message} for issue in result.issues
        ]
        entry["rows"] = result.data.height
        entry["series"] = (
            namespace["rr"].series(result).select("station_id", "variant", "quantity", "source_unit", "unit").to_dicts()
        )
        entry["recordings"] = []
        for index, recording in enumerate(recorder.recordings):
            name = f"{provider}-{index}.recording.json"
            write_recording(recording, args.out / name)
            entry["recordings"].append(name)
        report["pages"].append(entry)
        (args.out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(entry, indent=2), flush=True)
    assert all(block["matches"] for page in report["pages"] for block in page["blocks"]), "Displayed output differs"
    assert all(not any(issue["severity"] != "info" for issue in page["issues"]) for page in report["pages"])


if __name__ == "__main__":
    main()
