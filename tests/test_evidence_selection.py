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


def test_real_selected_nodes_keep_provider_and_helper_input_closure(pytester, monkeypatch):
    """Collect real consumers once; never resolve or open their retained inputs."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    monkeypatch.delenv("RIVRETRIEVE_TEST_EVIDENCE_ROOT", raising=False)
    monkeypatch.delenv("THAIWATER_REVIEW_EVIDENCE_ROOT", raising=False)
    modules = (
        "test_station_metadata_areas",
        "test_cz_fr_lt_acquisition_provenance",
        "test_catalogue_origin_certification",
        "test_catalogue_evidence",
        "test_live_numeric_values",
        "test_provider_series_parse",
        "test_za_dws_acquisition_provenance",
        "test_za_dws_generate_catalogue",
    )
    plan = pytester.path / "selected.json"
    result = pytester.runpytest_subprocess(
        *(str(root / "tests" / f"{module}.py") for module in modules),
        "--collect-only",
        "-q",
        "--evidence-plan",
        str(plan),
    )
    assert result.ret == 0
    selected = {item["nodeid"].split("::", 1)[1]: item for item in json.loads(plan.read_text())["tests"]}

    def check(name, purposes, requirements, full=()):
        item = selected[name]
        assert item["purposes"] == sorted(purposes)
        assert item["requirements"] == sorted(requirements)
        assert item["full_verification"] == sorted(full)

    native = "src/rivretrieve/_internal/providers/{}/catalogue/native.parquet"
    for provider in ("cz_chmi", "fr_hubeau", "lt_lhmt"):
        check(f"test_projection_preserves_every_native_scalar[{provider}]", ["derived"], [native.format(provider)])
        cli_recordings = {
            "cz_chmi": ["tests/test_data/cz_chmi_terms_licence.html", "tests/test_data/cz_meta2.json"],
            "fr_hubeau": [
                "maintenance/catalogue/fr_hubeau/inventory/hydrometry-stations-2026-09-21.json.xz",
                "maintenance/catalogue/fr_hubeau/inventory/temperature-stations-2026-09-21.json.xz",
                "tests/test_data/fr_hubeau_hydrometrie.html",
                "tests/test_data/fr_hubeau_temperature_openapi.json",
                "tests/test_data/fr_hubeau_terms_licence.html",
            ],
            "lt_lhmt": ["tests/test_data/lt_lhmt_terms_licence.html"],
        }
        check(
            f"test_native_cli_invokes_shared_recording_verifier[{provider}]",
            ["derived"],
            [native.format(provider), *cli_recordings[provider]],
            ["fr_hubeau"] if provider == "fr_hubeau" else [],
        )
        terms = f"tests/test_data/{provider}_terms_licence.html"
        check(
            f"test_production_provenance_rejects_changed_recording[{provider}-{provider}_terms_licence.html]",
            ["governing"],
            [terms],
            ["fr_hubeau"] if provider == "fr_hubeau" else [],
        )
    for provider, extra in (
        ("cz_chmi", ["tests/test_data/cz_chmi_terms_licence.html", "tests/test_data/cz_meta2.json"]),
        ("fr_hubeau", []),
        ("lt_lhmt", ["tests/test_data/lt_lhmt_terms_licence.html"]),
    ):
        check(
            f"test_native_cli_rejects_raw_byte_substitution[{provider}]",
            ["governing"],
            [native.format(provider), *extra],
            ["fr_hubeau"] if provider == "fr_hubeau" else [],
        )
    check(
        "test_committed_declaration_case_passes_real_build_and_origin_gate[lt_lhmt-stations]",
        ["derived"],
        [native.format("lt_lhmt")],
    )
    check(
        "test_native_composition_root_rebuilds_committed_artifacts_without_network[za_dws]",
        ["governing"],
        [native.format("za_dws"), *(f"tests/test_data/za_dws_terms_licence-{n}.html" for n in (1, 4, 5))],
    )
    for provider in ("cz_chmi", "jp_mlit", "lt_lhmt", "no_nve", "th_thaiwater"):
        check(f"test_all_ordered_source_assertions_match_pinned_original_revision[{provider}]", [], [])
    check(
        "test_actual_live_parser_isolates_unrepresentable_numeric_cells[lt_lhmt-zero]",
        ["recorded"],
        ["tests/test_data/lt_lhmt_anyksciu-vms_2023-06.recording.json"],
    )
    lithuanian = "tests/test_data/lt_lhmt_anyksciu-vms_2023-06.recording.json"
    check(
        "test_czech_internal_request_coordinates_are_not_rewritten_to_match_tags",
        ["recorded"],
        ["tests/test_data/cz_chmi_0-203-1-000400_DQ_2023.recording.json", lithuanian],
    )
    assert lithuanian in selected["test_other_recorded_provider_parsers_retain_series_context"]["requirements"]
    for name in (
        "test_south_africa_cli_rejects_native_byte_substitution",
        "test_canonical_cli_writes_versioned_native_built_artifacts",
        "test_native_build_is_network_free_and_byte_deterministic",
    ):
        check(
            name,
            ["governing"]
            if name == "test_south_africa_cli_rejects_native_byte_substitution"
            else ["governing", "recorded"],
            [native.format("za_dws"), *(f"tests/test_data/za_dws_terms_licence-{n}.html" for n in (1, 4, 5))],
        )
