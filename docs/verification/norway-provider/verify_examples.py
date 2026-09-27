"""Execute the Norway page through the public API. Requires NVE_API_KEY."""

import io
import re
from contextlib import redirect_stdout
from pathlib import Path

import rivretrieve as rr

page = Path("docs/providers/no_nve.md").read_text()
blocks = re.findall(r"```python\n(.*?)```\n\nOutput:\n\n```text\n(.*?)```", page, re.S)
assert len(blocks) == page.count("```python") == 2
print("no_nve access:", next(row[2] for row in rr.providers().rows() if row[0] == "no_nve"))
namespace = {}
for index, (code, expected) in enumerate(blocks, 1):
    output = io.StringIO()
    with redirect_stdout(output):
        exec(compile(code, f"no_nve.md:block-{index}", "exec"), namespace)
    print(f"BLOCK {index}")
    print(output.getvalue(), end="")
    assert output.getvalue() == expected, index
print("Public snippets match all displayed output.")
print("Source calls:", namespace["result"].provenance.calls_made)
