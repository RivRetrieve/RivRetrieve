import warnings
from typing import Any, cast

import pytest
from pydantic import ValidationError

from rivretrieve._internal.issues import (
    FatalContractError,
    Issue,
    IssuePolicyError,
    LiveCatalogueRoutingNotImplementedError,
    LiveCatalogueUnsupportedIssue,
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


def test_live_catalogue_unsupported_issue_constructs_provider_issue() -> None:
    provider_id = ProviderId("ch_foen")

    issue = LiveCatalogueUnsupportedIssue(
        provider_id=provider_id,
        method="read_products",
        capability="live_products",
    )

    assert isinstance(issue, Issue)
    assert issue.severity == "warning"
    assert issue.code == "live_catalogue_unsupported"
    assert issue.provider_id == provider_id
    assert issue.message == "Provider ch_foen does not support live catalogue method read_products"
    assert issue.details == {
        "method": "read_products",
        "capability": "live_products",
        "source": "live",
    }


def test_live_catalogue_unsupported_issue_constructs_global_issue() -> None:
    issue = LiveCatalogueUnsupportedIssue(
        provider_id=None,
        method="read_stations",
        capability="live_stations",
    )

    assert issue.severity == "warning"
    assert issue.code == "live_catalogue_unsupported"
    assert issue.provider_id is None
    assert issue.message == "Provider <global> does not support live catalogue method read_stations"
    assert issue.details == {
        "method": "read_stations",
        "capability": "live_stations",
        "source": "live",
    }


def test_live_catalogue_routing_not_implemented_error_is_fatal_contract_error() -> None:
    assert issubclass(LiveCatalogueRoutingNotImplementedError, FatalContractError)


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


@pytest.mark.parametrize(
    ("issues", "on_issue", "raises_policy_error"),
    [
        ([], "ignore", False),
        ([], "warn", False),
        ([], "raise", False),
        ([Issue(severity="info", code="info", message="info")], "ignore", False),
        ([Issue(severity="info", code="info", message="info")], "warn", False),
        ([Issue(severity="info", code="info", message="info")], "raise", False),
        ([Issue(severity="warning", code="warning", message="warning")], "ignore", False),
        ([Issue(severity="warning", code="warning", message="warning")], "warn", False),
        ([Issue(severity="warning", code="warning", message="warning")], "raise", True),
        ([Issue(severity="error", code="error", message="error")], "ignore", False),
        ([Issue(severity="error", code="error", message="error")], "warn", False),
        ([Issue(severity="error", code="error", message="error")], "raise", True),
        (
            [
                Issue(severity="info", code="info", message="info"),
                Issue(severity="warning", code="warning", message="warning"),
                Issue(severity="error", code="error", message="error"),
            ],
            "ignore",
            False,
        ),
        (
            [
                Issue(severity="info", code="info", message="info"),
                Issue(severity="warning", code="warning", message="warning"),
                Issue(severity="error", code="error", message="error"),
            ],
            "warn",
            False,
        ),
        (
            [
                Issue(severity="info", code="info", message="info"),
                Issue(severity="warning", code="warning", message="warning"),
                Issue(severity="error", code="error", message="error"),
            ],
            "raise",
            True,
        ),
    ],
)
def test_fatal_contract_error_is_separate_from_on_issue(
    issues: list[Issue], on_issue: OnIssue, raises_policy_error: bool
) -> None:
    fatal_error = FatalContractError()
    assert fatal_error.issues == ()

    if raises_policy_error:
        with pytest.raises(IssuePolicyError) as error:
            apply_on_issue(issues, on_issue)
        assert not isinstance(error.value, FatalContractError)
        return

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            apply_on_issue(issues, on_issue)
        except Exception as error:  # pragma: no cover
            pytest.fail(f"apply_on_issue raised {type(error).__name__}: {error}")
