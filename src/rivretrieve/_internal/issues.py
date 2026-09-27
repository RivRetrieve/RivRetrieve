import warnings
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from rivretrieve._internal.primitives import IssueSeverity, OnIssue, ProviderId


class Issue(BaseModel):
    """A problem or note recorded during selection or retrieval, kept with the results.

    Issues are kept on selections and results whatever ``on_issue`` policy is
    chosen. They let independent series return data while a failure elsewhere
    stays visible with its identity and reason.

    Attributes
    ----------
    severity : {"info", "warning", "error"}
        Finding severity. Only warning and error activate the caller issue policy.
    code : str
        Machine-readable classification, usually written as
        ``<area>.<finding>``. Some provider codes have no dot, such as
        ``source_no_data``. Examples include ``source.request_failed`` (error, a
        failed source request), ``source.http_not_found`` (warning, HTTP 404),
        ``bulk.store_missing`` (warning, no compiled store),
        ``selection.no_match`` and ``selection.unresolved_inventory`` (warning,
        an explicit restriction matched no known series), ``request.future_end``
        (info) and ``provenance.license_not_established`` (info). This list is
        not exhaustive.
    message : str
        Human-readable finding.
    details : dict[str, object] or None
        Structured context, such as station, product and source failure reason.
        Source request failures record ``station_id``, ``product_id``,
        ``request_url``, ``attempts``, ``status_code``, ``failure_reason`` and,
        when known, ``failure_category``. ``status_code`` is None when no HTTP
        status was received, for example after a timeout. A failed request for
        one series and interval also records ``series_id``, ``variant``,
        ``window`` (the source interval) and ``outcome_id``.
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
    """Raised when ``on_issue="raise"`` and warning or error issues exist.

    ``issues`` holds those warning and error issues. The result they belong to
    is not returned.
    """

    def __init__(self, issues: Sequence[Issue], message: str | None = None) -> None:
        self.issues = tuple(issues)
        if message is None:
            message = "Recoverable issue policy requested an exception"
        super().__init__(message)


class FatalContractError(RivRetrieveError):
    """Raised when a request or internal contract cannot be satisfied.

    These errors are raised whatever ``on_issue`` policy is chosen. Its
    subclasses name specific causes, such as invalid requests or missing
    credentials.
    """

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
    """Raised before retrieval when a required credential is not set.

    ``missing_by_provider`` maps each provider identifier to the missing
    variable names. No source request is made.
    """

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
    """Raised by ``fetch`` for a catalogue-only provider, such as ``za_dws``.

    The provider ships a station catalogue but no observations.
    """


class ObservationDataSchemaError(FatalContractError):
    """Raised when observation rows break the frame schema or contradict their facts.

    The facts are the source-series definitions that the rows reference.
    """


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
