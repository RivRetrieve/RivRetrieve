"""Run every Python snippet on the Poland provider page, in order, in one session.

The first snippet downloads and compiles IMGW-PIB's complete daily archive. Set
RIVRETRIEVE_CACHE_DIR to an empty directory to repeat the fresh preparation.
Each printed result is compared with the page's following ``text`` block.
"""

import argparse
import contextlib
import io
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

PAGE = Path(__file__).resolve().parents[2] / "providers/pl_imgw.md"
BLOCK = re.compile(r"```(python|text)\n(.*?)```", re.DOTALL)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse-store", action="store_true", help="Skip download and check the existing live store.")
    args = parser.parse_args()
    blocks = BLOCK.findall(PAGE.read_text())
    scope: dict[str, object] = {}
    failures = 0
    for index, (kind, body) in enumerate(blocks):
        if kind != "python":
            continue
        if args.reuse_store and "rr.download(" in body:
            exec("import rivretrieve as rr", scope)
            print("--- download skipped: reusing existing store; this is not new acquisition evidence")
            continue
        expected = blocks[index + 1][1] if index + 1 < len(blocks) and blocks[index + 1][0] == "text" else None
        started = time.monotonic()
        print(f"--- snippet at block {index}, started {datetime.now(UTC).isoformat(timespec='seconds')}")
        print(body, end="")
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            exec(compile(body, str(PAGE), "exec"), scope)
        output = captured.getvalue()
        print(f"--- output after {time.monotonic() - started:.0f} s")
        print(output, end="")
        if expected is not None:
            matched = output == expected
            failures += not matched
            print(f"--- matches page output: {matched}")
            if not matched:
                print(f"--- page output:\n{expected}", end="")
    print(f"--- finished {datetime.now(UTC).isoformat(timespec='seconds')}, mismatches: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
