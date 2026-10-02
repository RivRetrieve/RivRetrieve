"""Select test purposes without loading retained inputs or contacting the archive."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

import pytest

PURPOSES = {
    "recorded": "regression against genuine retained recordings",
    "derived": "offline rebuild from derived inputs, not original-source certification",
    "governing": "catalogue or governing source verification",
    "live": "observation of a live publisher service",
}
FULL_VERIFICATION = frozenset({"ba_fhmzbih", "fr_hubeau", "th_thaiwater"})
EVIDENCE_FIXTURES = frozenset({"retained_evidence_root", "thaiwater_review_evidence_root"})


def pytest_addoption(parser):
    group = parser.getgroup("evidence")
    group.addoption("--logic-only", action="store_true", help="Run source-independent checks only.")
    group.addoption("--evidence-plan", help="Internal source-free selected-test plan output (collect only).")
    group.addoption("--evidence-plan-check", help="Internal selected-test plan to check before execution.")


def pytest_configure(config):
    for name, description in PURPOSES.items():
        config.addinivalue_line("markers", f"{name}(*requirements, full_verification=()): {description}")
    output = config.getoption("evidence_plan")
    expected = config.getoption("evidence_plan_check")
    if output and not config.getoption("collectonly"):
        raise pytest.UsageError("--evidence-plan requires --collect-only.")
    if expected and (config.getoption("collectonly") or config.getoption("logic_only") or output):
        raise pytest.UsageError("--evidence-plan-check requires execution without --logic-only or --evidence-plan.")


def _requirement(value):
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[A-Za-z0-9_./-]+", value)
        or str(PurePosixPath(value)) != value
        or PurePosixPath(value).is_absolute()
        or any(part in {".", ".."} for part in value.split("/"))
        or "/" not in value
    ):
        raise pytest.UsageError("A test evidence requirement is not a canonical repository-relative scope.")
    return value


def selected_test(item):
    purposes, requirements, full = set(), set(), set()
    for purpose in PURPOSES:
        for mark in item.iter_markers(purpose):
            purposes.add(purpose)
            if set(mark.kwargs) - {"full_verification"}:
                raise pytest.UsageError("A test purpose has unsupported metadata.")
            if not mark.args and purpose != "live":
                raise pytest.UsageError("A retained-input test purpose requires a consumer scope.")
            requirements.update(_requirement(value) for value in mark.args)
            providers = mark.kwargs.get("full_verification", ())
            if not isinstance(providers, tuple) or any(
                not isinstance(provider, str) or provider not in FULL_VERIFICATION for provider in providers
            ):
                raise pytest.UsageError("A full-verification prerequisite is invalid.")
            full.update(providers)
    if EVIDENCE_FIXTURES.intersection(item.fixturenames) and not requirements:
        raise pytest.UsageError(f"Retained-input test has no purpose and consumer scopes: {item.nodeid}")
    if "thaiwater_review_evidence_root" in item.fixturenames and "th_thaiwater" not in full:
        raise pytest.UsageError("ThaiWater controlled inputs require complete positive verification.")
    return {
        "nodeid": item.nodeid,
        "purposes": sorted(purposes),
        "requirements": sorted(requirements),
        "full_verification": sorted(full),
    }


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    # Validate fixture closure before deselection, so a missing mark cannot enter
    # the source-independent route. Pytest supplies indirect fixture dependencies.
    selected = [(item, selected_test(item)) for item in items]
    if config.getoption("logic_only"):
        deselected = [item for item, metadata in selected if metadata["purposes"]]
        items[:] = [item for item, metadata in selected if not metadata["purposes"]]
        config.hook.pytest_deselected(items=deselected)


def pytest_collection_finish(session):
    output = session.config.getoption("evidence_plan")
    expected = session.config.getoption("evidence_plan_check")
    if not output and not expected:
        return
    if session.testsfailed or not session.items:
        raise pytest.UsageError("An evidence plan requires successful, nonempty collection.")
    plan = {"schema_version": 1, "tests": [selected_test(item) for item in session.items]}
    if expected:
        try:
            previous = json.loads(Path(expected).read_text())
        except (OSError, ValueError):
            raise pytest.UsageError("The selected-test plan cannot be read.") from None
        if json.dumps(previous, sort_keys=True) != json.dumps(plan, sort_keys=True):
            raise pytest.UsageError("Execution does not match the collected selected-test plan.")
    if output:
        # Exclusive creation prevents accidental replacement of a reviewed plan.
        with Path(output).open("x") as stream:
            json.dump(plan, stream, indent=2)
            stream.write("\n")
