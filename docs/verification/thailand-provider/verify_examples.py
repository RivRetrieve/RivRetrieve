"""Execute the Thailand page through the public API against the live ThaiWater source."""

import io
import re
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

import rivretrieve as rr
from rivretrieve._internal.issues import FatalContractError

page = Path("docs/providers/th_thaiwater.md").read_text()
blocks = re.findall(r"```python\n(.*?)```\n\nOutput:\n\n```text\n(.*?)```", page, re.S)
assert len(blocks) == page.count("```python") == 2
print("Started:", datetime.now(UTC).isoformat(timespec="seconds"))
namespace = {}
for index, (code, expected) in enumerate(blocks, 1):
    output = io.StringIO()
    with redirect_stdout(output):
        exec(compile(code, f"th_thaiwater.md:block-{index}", "exec"), namespace)
    print(f"BLOCK {index}")
    print(output.getvalue(), end="")
    assert output.getvalue() == expected, index
print("Public snippets match all displayed output.")
for name in ("result", "discharge_result"):
    for call in namespace[name].provenance.calls_made:
        print(name, call["status_code"], call["retrieved_at"].isoformat(), call["request_parameters"])
try:
    rr.to_utc(namespace["result"])
except FatalContractError as error:
    print("to_utc refused:", error)
else:
    raise AssertionError("to_utc converted unknown-zone rows")
