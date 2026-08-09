import warnings
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from rivretrieve._internal.primitives import IssueSeverity, OnIssue, ProviderId


class Issue(BaseModel):
    model_config = ConfigDict(frozen=True)

    severity: IssueSeverity
    code: str
    message: str
    details: dict[str, object] | None = None
    provider_id: ProviderId | None = None


class RivRetrieveError(Exception):
    """Base exception for RivRetrieve harness errors."""


class IssuePolicyError(RivRetrieveError):
    def __init__(self, issues: Sequence[Issue], message: str | None = None) -> None:
        self.issues = tuple(issues)
        if message is None:
            message = "Recoverable issue policy requested an exception"
        super().__init__(message)


class FatalContractError(RivRetrieveError):
    def __init__(self, message: str | None = None, *, issues: Sequence[Issue] = ()) -> None:
        self.issues = tuple(issues)
        if message is None:
            message = "Fatal RivRetrieve contract failure"
        super().__init__(message)


class MissingOptionalDependencyError(FatalContractError):
    pass


class InvalidObservationRequestError(FatalContractError):
    pass


class ObservationsUnavailableError(FatalContractError):
    pass


class ObservationDataSchemaError(FatalContractError):
    pass


def apply_on_issue(issues: Sequence[Issue], on_issue: OnIssue) -> None:
    actionable_issues = tuple(issue for issue in issues if issue.severity in {"warning", "error"})

    if not actionable_issues or on_issue == "ignore":
        return

    if on_issue == "warn":
        for issue in actionable_issues:
            warnings.warn(issue.message, RuntimeWarning, stacklevel=2)
        return

    if on_issue == "raise":
        raise IssuePolicyError(actionable_issues)
