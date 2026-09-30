# ANA telemetry test description

Related bug: https://github.com/RivRetrieve/RivRetrieve/issues/447

## Outcome

Describe the current responsibility of `tests/test_br_ana_telemetry.py` without
implying that ANA telemetry is not registered for public retrieval. This is a
small documentation repair, not a provider-data or runtime repair.

Issue #447 blocks the separate archive-test Effort
https://github.com/RivRetrieve/RivRetrieve/issues/429 under Program #427's
stop-and-report rule. This standalone bug vision does not implement that Effort.
After the repair lands, #429 still requires the owner's explicit instruction to
resume. Publishing this vision does not repair the bug or authorize that resume.

## Evidence and cause

Source and Git history were inspected at `main` commit
`815c8f8733f0c6f420ae9b282993c38a95d5eca1`.

- Commit `2dc1776503fb4debe43479d52e86962ab1e7ffa7` introduced the internal
  telemetry tests with the opening description “Adopted ANA telemetry stages
  over exact recordings, not yet public registration.”
- Commit `c3ec5f34972ce8076daeac4a19037c6299867f39` activated public ANA telemetry
  and added public API tests without updating that description. Git blame shows
  the opening docstring still comes from the earlier commit.
- `src/rivretrieve/_internal/providers/br_ana/config.py` declares
  `discharge_instantaneous` and `stage_instantaneous`.
- `src/rivretrieve/_internal/providers/br_ana/declaration.py` connects the
  provider to retrieval stages and credential exchange.
- `tests/test_br_ana_public_telemetry.py` defines public `rr.find` and `rr.fetch`
  coverage, including required credentials and authenticated recorded-response
  retrieval. These are test definitions, not a new passing-test claim.

The cause is a development-status note retained after public activation. The
internal test module still tests internal processing through the shared engine:
time boundaries, native values, nulls, caching, exact request matching, and
failure handling. Its responsibility is distinct from public API coverage.

This investigation used code and history only. No evidence-backed tests or live
ANA requests were run. The findings establish the documentation contradiction;
they do not establish current live-service health or a provider-data defect.

## Repair boundaries

Replace the outdated opening description with current-purpose wording. Suitable
wording is “Tests for internal ANA adopted telemetry stages using exact
recordings.” Exact phrasing is not an acceptance contract.

Preserve the existing statements about independently authored boundary
expectations, their recording documentation references, and the absence of a
conventional-daily claim. That last qualification describes this test module,
not the provider's entire product range. Keep source terminology and the strength
of existing claims unchanged.

Do not change runtime code, test behavior, product declarations, recordings, or
source claims. Do not expand this repair into an ANA documentation audit, archive
migration, new data acquisition, or a change to the Program's stop-and-report
rule. Preserve #429's separate incomplete work.

## Acceptance and verification

- The module description accurately identifies internal ANA adopted telemetry
  tests and no longer says public registration is pending.
- The remaining evidence qualifications are preserved.
- Source review against the product declarations, provider registration, and
  public API test definitions confirms the description is consistent.
- Review of the implementation diff confirms a documentation-only correction
  with no behavioral or source-evidence changes.

No new exact-wording regression test is needed. Source review and a
documentation-only diff are sufficient for this repair; access to source
recordings, credentials, or a live service is not required. Do not represent
these checks as genuine-input or live-service acceptance. The implementing
agent must report the repair separately from any later authorization to resume
#429.
