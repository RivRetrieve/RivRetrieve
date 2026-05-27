# 01-foundations — adversarial critique (round 2)

## Verdict

**DISPATCH AS-IS.**

Both round-1 Majors are cleanly resolved and every Minor and
Nit is either addressed in the revision or explicitly
deferred with a named owner. One residual Nit (n1 below)
worth fixing in passing if the executor notices it, but it
does not block dispatch.

## Round-1 findings — resolution status

| # | Finding | Status in revised plan |
|---|---|---|
| M1 | `Issue.is_fatal` as fatal mechanism | **Resolved.** §3: "Do not add `Issue.is_fatal`." §4: "Fatal contract failures do not pass through `apply_on_issue`." §Q4 defends the change against architecture.md:587-593/607. T13 asserts the separation explicitly. |
| M2 | Version floors below Python-3.13 wheel floor | **Resolved.** §6 step 1: bare dependency names only. §Q10: defer to `uv lock`. §9 adds a stop for "uv lock resolves dependency versions that cannot install/import under Python 3.13." |
| m1 | Missing `ignore × info` cell | **Resolved.** T07 covers info/warning/error all under `"ignore"`. Matrix is now exhaustive (T06–T11). |
| m2 | Mixed fatal+recoverable untested | **Resolved by removal.** Fatal no longer flows through `apply_on_issue`, so the precedence rule from old §4 is gone. T13 covers the separation. |
| m3 | Empty list no-op untested | **Resolved.** T06 covers all three policies. |
| m4 | T17 target file unspecified | **Resolved.** §6 step 9 names `tests/test_package.py`; T17 specifies the negative-control assertion list. |
| m5 | `Issue.details` secret rule | **Resolved by explicit deferral.** §3 says no sanitization; §8 documents it as a later hardening task. |
| m6 | Speculative `arbitrary_types_allowed=True` | **Resolved.** §3: "Do not set `arbitrary_types_allowed=True` in this step." §Q8 reinforces. |
| m7 | Exception `.issues` not asserted | **Resolved.** T12 asserts `IssuePolicyError.issues` equals the trigger issues. |
| m8 | Q7 snake_case owner ambiguous | **Resolved.** §3 and §Q7 both name Step 03 as owner; §3 clarifies Step 02's narrower artifact-consistency role. |
| m9 | `endpoints` cross-field validator missing | **Resolved by explicit deferral.** §3 and §8 defer cross-field validation to Step 02/03. |
| m10 | `rivretrieve_version` auto-populate | **Resolved by explicit deferral.** §3 and §8 hand it to Step 03. |
| n1 | Per-model `ConfigDict` unspecified | **Resolved.** §3 now lists Issue/CatalogProvenance/CatalogResult each with `frozen=True`. |
| n2 | Test numbering | **Resolved.** T01–T17 used consistently. |
| n3 | `uv lock` failure path | **Resolved.** §6 step 2 cross-references §9; §9 adds the explicit stop. |
| n4 | `Sequence` in / `tuple` out | **Resolved.** §Q5 acknowledges the shape distinction. |

## Residual findings

### n1 (new). T13 wording is vague about what it actually asserts.

T13: "constructing or raising `FatalContractError` does not
require an `Issue` and is not produced by `apply_on_issue`."

The first clause is straightforwardly testable
(`FatalContractError()` constructs without args; `raise
FatalContractError(...)` works). The second clause —
"is not produced by `apply_on_issue`" — is a property
about the function, not an observation the test can make
directly. A clean way to write it: feed
`apply_on_issue` an arbitrary mix of severities under each
policy, assert that the only exception type it ever raises
is `IssuePolicyError`, never `FatalContractError`. That
turns the architectural claim into a concrete assertion.

Fold-in if executor notices, otherwise harmless.

## Lens-by-lens summary (delta vs round 1)

- **L4 Test coverage** — ✅ now. Matrix is exhaustive
  (T06–T11), `.issues` attribute is asserted (T12),
  fatal-is-separate is asserted (T13).
- **L11 Speculative abstraction** — ✅. `is_fatal` and
  `arbitrary_types_allowed` both gone.
- **L14 Python 3.13 compatibility** — ✅ by deferral. No
  planner-guessed floors; `uv lock` is the resolver; §9
  stops on install failure. This is the right call given
  the user's explicit instruction.
- **L15 Fatal vs recoverable** — ✅. Two-channel design:
  recoverable Issue → `apply_on_issue`; fatal → direct
  `FatalContractError` raise. Silent-downgrade vector
  eliminated.
- All other lenses retain their round-1 ✅.

## Adversarial probes attempted (round 2)

- **Re-checked architecture.md:607 against revised §Q4.**
  Architecture lists "unknown provider IDs, invalid
  catalogue source values, corrupt packaged catalogue
  artifacts, and provider implementation schema violations"
  as fatal contract failures. Revised plan handles all
  four via direct exception in Step 02/03 (deferred
  cleanly in §8); no silent-downgrade vector remains.
- **Walked the OnIssue × IssueSeverity matrix against
  T06–T11.** ignore×{info,warning,error}=T07,
  warn×info=T08, warn×{warning,error}=T09,
  raise×info=T10, raise×{warning,error}=T11,
  empty×{all}=T06. Complete.
- **Searched §6 for ordering hazards.** issues.py +
  test_internal_issues.py land together (steps 5–6);
  results.py + test_internal_results.py land together
  (steps 7–8). No throwaway test-only models. `uv run
  pytest` stays green at each boundary.
- **Searched §6 for any `__init__.py` mutation.** None.
  T17 is added in `tests/test_package.py` only.
- **Searched for any new Protocol, ABC, base class, or
  registry stub.** None. Scope remains primitives +
  policy helper + envelopes.
- **Checked §9 for the new fatal-mechanism stop.**
  Present: "Fatal contract failures cannot be expressed
  cleanly as direct exceptions in Step 02/03 without
  adding fatality back to `Issue`." Good — catches a
  future regression toward the round-1 design.
- **Checked §Q10 + §9 for the new dep-floor stop.**
  Present: "uv lock resolves dependency versions that
  cannot install/import under Python 3.13." Combined
  with `requires-python = ">=3.13"`, this catches the
  round-1 install-failure risk at the right boundary
  (executor-time, not planner-time).
- **Tried to find a remaining "for later" abstraction.**
  Couldn't. The single residual is T13's wording (above),
  which is presentation, not abstraction.

Ship it.
