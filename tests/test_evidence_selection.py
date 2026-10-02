"""Protect source-free selection and the archive coordinator's exact test handoff."""

import json
from types import SimpleNamespace

import pytest

from tests._evidence_selection import selected_test

pytest_plugins = ("pytester",)


def _item(*marks, fixtures=()):
    return SimpleNamespace(
        nodeid="test_control.py::test_control",
        fixturenames=fixtures,
        iter_markers=lambda name: (mark.mark for mark in marks if mark.name == name),
    )


def test_multiple_purposes_keep_scopes_and_prerequisites():
    result = selected_test(
        _item(
            pytest.mark.recorded("tests/recordings/provider"),
            pytest.mark.governing("maintenance/catalogue/provider/body.json", full_verification=("th_thaiwater",)),
            fixtures=("retained_evidence_root",),
        )
    )
    assert result == {
        "nodeid": "test_control.py::test_control",
        "purposes": ["governing", "recorded"],
        "requirements": ["maintenance/catalogue/provider/body.json", "tests/recordings/provider"],
        "full_verification": ["th_thaiwater"],
    }


@pytest.mark.parametrize("scope", ["../secret", "/absolute/path", "a//b", "a/./b", "a/../b", "a/", "a\\b", "single", 1])
def test_requirements_reject_noncanonical_paths(scope):
    with pytest.raises(pytest.UsageError):
        selected_test(_item(pytest.mark.recorded(scope)))


@pytest.mark.parametrize(
    "mark",
    [
        pytest.mark.recorded(),
        pytest.mark.recorded("tests/recordings/provider", inputs=("legacy",)),
        pytest.mark.governing("tests/recordings/provider", full_verification="th_thaiwater"),
        pytest.mark.governing("tests/recordings/provider", full_verification=("unknown",)),
    ],
)
def test_invalid_purpose_metadata_fails(mark):
    with pytest.raises(pytest.UsageError):
        selected_test(_item(mark))


def test_live_observation_is_not_source_independent():
    assert selected_test(_item(pytest.mark.live()))["purposes"] == ["live"]


def test_governing_fixture_requires_full_positive_prerequisite():
    with pytest.raises(pytest.UsageError, match="complete positive"):
        selected_test(
            _item(pytest.mark.governing("tests/recordings/provider"), fixtures=("thaiwater_review_evidence_root",))
        )


def _suite(pytester):
    pytester.makeconftest(
        "\n".join(
            [
                'pytest_plugins = ("tests._evidence_selection",)',
                "import pytest",
                "@pytest.fixture",
                "def retained_evidence_root():",
                '    raise AssertionError("collection must not resolve evidence")',
                "@pytest.fixture",
                "def indirect(retained_evidence_root):",
                "    return retained_evidence_root",
            ]
        )
    )
    pytester.makepyfile(
        test_control="""
        import pytest
        def test_logic():
            pass
        @pytest.mark.recorded("tests/recordings/provider")
        def test_recorded(indirect):
            pass
        """
    )


def test_logic_selection_and_plan_need_no_source_inputs(pytester):
    _suite(pytester)
    pytester.runpytest("--logic-only", "-q").assert_outcomes(passed=1, deselected=1)
    plan = pytester.path / "plan.json"
    result = pytester.runpytest("--collect-only", "--evidence-plan", str(plan), "-q")
    assert result.ret == 0
    selected = json.loads(plan.read_text())
    assert selected["schema_version"] == 1
    assert len(selected["tests"]) == 2
    assert selected["tests"][0]["requirements"] == []
    assert selected["tests"][1]["requirements"] == ["tests/recordings/provider"]


def test_indirect_unclassified_input_fails_before_logic_deselection(pytester):
    _suite(pytester)
    pytester.makepyfile(test_unclassified="def test_missing(indirect): pass")
    result = pytester.runpytest("--collect-only", "--logic-only", "-q")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*Retained-input test has no purpose*"])


def test_execution_must_match_nonempty_plan(pytester):
    _suite(pytester)
    plan = pytester.path / "plan.json"
    assert pytester.runpytest("--collect-only", "--logic-only", "--evidence-plan", str(plan), "-q").ret == 0
    pytester.runpytest("test_control.py::test_logic", "--evidence-plan-check", str(plan), "-q").assert_outcomes(
        passed=1
    )
    original = json.loads(plan.read_text())
    changed = json.loads(plan.read_text())
    changed["tests"][0]["purposes"] = ["recorded"]
    for invalid in (changed, dict(original, schema_version=True), dict(original, unknown=[])):
        plan.write_text(json.dumps(invalid))
        result = pytester.runpytest("test_control.py::test_logic", "--evidence-plan-check", str(plan), "-q")
        assert result.ret == pytest.ExitCode.USAGE_ERROR
        result.stderr.fnmatch_lines(["*does not match*"])
    missing = pytester.path / "empty.json"
    result = pytester.runpytest("--collect-only", "-k", "absent_test", "--evidence-plan", str(missing), "-q")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert not missing.exists()


@pytest.mark.parametrize(
    "flags",
    [("--evidence-plan",), ("--evidence-plan-check", "--collect-only"), ("--evidence-plan-check", "--logic-only")],
)
def test_plan_flags_require_correct_phase(pytester, flags):
    _suite(pytester)
    assert (
        pytester.runpytest(flags[0], str(pytester.path / "plan.json"), *flags[1:], "-q").ret
        == pytest.ExitCode.USAGE_ERROR
    )
