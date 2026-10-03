import warnings
from typing import Any, cast

import pytest
from pydantic import ValidationError

from rivretrieve._internal.issues import (
    FatalContractError,
    Issue,
    IssuePolicyError,
    apply_on_issue,
)
from rivretrieve._internal.primitives import IssueSeverity, OnIssue, ProviderId


@pytest.fixture
def info_issue() -> Issue:
    return Issue(severity="info", code="note", message="Informational note")


@pytest.fixture
def warning_issue() -> Issue:
    return Issue(severity="warning", code="partial_live_response", message="Partial live response")


@pytest.fixture
def error_issue() -> Issue:
    return Issue(severity="error", code="live_unsupported", message="Live retrieval is unsupported")


@pytest.mark.parametrize("severity", ["info", "warning", "error"])
def test_issue_severity_accepts_all_values(severity: IssueSeverity) -> None:
    issue = Issue(severity=severity, code="example", message="Example issue")

    assert issue.severity == severity


def test_issue_severity_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        Issue(severity=cast(Any, "fatal"), code="fatal", message="Fatal issue")


def test_issue_construction_roundtrip() -> None:
    provider_id = ProviderId("ch_foen")
    details: dict[str, object] = {"station_id": "1234", "count": 2}

    issue = Issue(
        severity="warning",
        code="partial_live_response",
        message="Partial live response",
        details=details,
        provider_id=provider_id,
    )

    assert issue.severity == "warning"
    assert issue.code == "partial_live_response"
    assert issue.message == "Partial live response"
    assert issue.details == details
    assert issue.provider_id == provider_id


@pytest.mark.parametrize("on_issue", ["ignore", "warn", "raise"])
def test_on_issue_empty_list_noops_for_all_policies(on_issue: OnIssue) -> None:
    with warnings.catch_warnings(record=True) as captured_warnings:
        apply_on_issue([], on_issue)

    assert len(captured_warnings) == 0


def test_on_issue_ignore_ignores_all_severities(info_issue: Issue, warning_issue: Issue, error_issue: Issue) -> None:
    with warnings.catch_warnings(record=True) as captured_warnings:
        apply_on_issue([info_issue, warning_issue, error_issue], "ignore")

    assert len(captured_warnings) == 0


def test_on_issue_warn_ignores_info(info_issue: Issue) -> None:
    with warnings.catch_warnings(record=True) as captured_warnings:
        apply_on_issue([info_issue], "warn")

    assert len(captured_warnings) == 0


def test_on_issue_warn_emits_for_warning_and_error(warning_issue: Issue, error_issue: Issue) -> None:
    with pytest.warns(RuntimeWarning) as captured_warnings:
        apply_on_issue([warning_issue, error_issue], "warn")

    assert [str(warning.message) for warning in captured_warnings] == [
        "Partial live response",
        "Live retrieval is unsupported",
    ]


def test_on_issue_raise_ignores_info(info_issue: Issue) -> None:
    apply_on_issue([info_issue], "raise")


@pytest.mark.parametrize("severity", ["warning", "error"])
def test_on_issue_raise_raises_for_warning_and_error(severity: IssueSeverity) -> None:
    issue = Issue(severity=severity, code=f"{severity}_code", message=f"{severity} message")

    with pytest.raises(IssuePolicyError):
        apply_on_issue([issue], "raise")


def test_issue_policy_error_carries_issues(warning_issue: Issue, error_issue: Issue) -> None:
    with pytest.raises(IssuePolicyError) as error:
        apply_on_issue([warning_issue, error_issue], "raise")

    assert error.value.issues == (warning_issue, error_issue)


def test_fatal_contract_error_is_separate_from_issue_policy() -> None:
    assert FatalContractError().issues == ()
    assert not issubclass(FatalContractError, IssuePolicyError)
    assert not issubclass(IssuePolicyError, FatalContractError)
