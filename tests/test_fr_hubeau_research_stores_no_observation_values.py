"""The fr_hubeau research evidence stores no publisher observation value.

This project does not redistribute source observations. The research folder keeps request receipts,
digests and derived readings for responses that carry measurements, and whole bodies only for
responses that carry none. This test fails the suite if a measurement value becomes readable from
any committed file in that folder.
"""

from __future__ import annotations

import importlib.util
import pathlib

FOLDER = pathlib.Path(__file__).resolve().parents[1] / "research" / "station-coverage" / "fr_hubeau"


def _scanner():
    spec = importlib.util.spec_from_file_location(
        "fr_hubeau_observation_scan", FOLDER / "scripts" / "observation_scan.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fr_hubeau_research_folder_stores_no_observation_value() -> None:
    assert _scanner().find_stored_observations(FOLDER) == []
