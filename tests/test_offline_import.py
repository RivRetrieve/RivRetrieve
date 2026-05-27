from __future__ import annotations

import subprocess
import sys


def test_import_rivretrieve_does_not_import_providers_or_generators() -> None:
    script = """
import sys
import rivretrieve

assert "rivretrieve._internal.catalogues.artifact" in sys.modules, (
    "sentinel module not imported; subprocess didn't actually exercise the package"
)
assert "rivretrieve.providers" not in sys.modules
assert "tests._stubs" not in sys.modules
assert "tests._stubs.stub_provider" not in sys.modules
for module_name in sys.modules:
    assert not module_name.startswith(("rivretrieve.providers.",))
    assert module_name.rsplit(".", 1)[-1] != "generate_catalogue"
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
