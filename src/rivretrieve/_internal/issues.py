import warnings
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from rivretrieve._internal.primitives import IssueSeverity, OnIssue, ProviderId


class Issue(BaseModel):
    """A retained finding distinct from a fatal contract exception.

    Attributes
    ----------
    severity : {"info", "warning", "error"}
        Finding severity. Only warning and error activate the caller issue policy.
    code : str
        Machine-readable classification.
    message : str
        Human-readable finding.
    details : dict[str, object] or None
        Structured context, such as station, product and source failure reason.
    provider_id : ProviderId or None
        Provider responsible for the affected series when known.
    """

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


class MissingCredentialError(FatalContractError):
    def __init__(self, missing_by_provider: dict[str, tuple[str, ...]]) -> None:
        self.missing_by_provider = {provider_id: tuple(names) for provider_id, names in missing_by_provider.items()}
        requirements = "; ".join(
            f"provider {provider_id} requires {', '.join(names)}"
            for provider_id, names in self.missing_by_provider.items()
        )
        super().__init__(
            "Missing credentials before observation fetch: "
            f"{requirements}. Set each value in the process environment or ./.env; "
            "see .env.example. No source request was made."
        )


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
