# USGS audit evidence description

Related bug: https://github.com/RivRetrieve/RivRetrieve/issues/450

## Outcome

Correct the opening description of `tests/test_usgs_coverage_audit.py` so readers can distinguish source-independent authored controls from tests that use retained publisher responses and derived audit outputs. This is a standalone documentation repair for #450, not the test-access refactor in #429.

The current description says all fixtures are synthetic. That misrepresents the inputs required by several tests. Effort #429 must distinguish tests that run without source evidence from tests that require archived inputs. Program #427's stop-and-report rule therefore paused that work when this documentation error was discovered. No incorrect USGS data, retrieval behavior, audit result or receipt check has been established by this finding.

## Established source evidence

Source inspection at `afdf85eee1188f9e0073be102630cc48af0b6a4e` establishes the contradiction without private archive access or live requests:

- The module's first line states: “Authored audit controls; fixtures below are synthetic, not publisher recordings.”
- Pagination, acquisition-failure, cache-validation and access-failure controls construct synthetic inputs and use temporary files or patched functions.
- `test_frozen_non_usgs_identity_matches_publisher_evidence` reads a frozen baseline, retained publisher probes and a derived coverage comparison.
- `test_frozen_full_denominator_and_receipt_hashes` reads an audit summary and acquisition receipts, and checks the hashes of retained response bytes.
- `test_unknown_statistic_with_observations_is_not_missing` reads the derived `unresolved.json` audit output. Although #450 names only the preceding two tests, this third test also depends on retained audit material.

In `scripts/audit_usgs_coverage.py`, `capture()` retains response bytes and acquisition receipts; `read_probe()` reads retained responses and checks their hashes. The audit writes `comparison.jsonl.gz` and `unresolved.json` as derived outputs. Do not describe these derived outputs as publisher originals.

Git history shows that commit `2a1d817` introduced both the blanket description and the evidence-dependent tests. At the inspected main revision, the file is unchanged from that introduction. The error was present from the start; it was not introduced by #429's draft refactor.

## Scope and constraints

Change the module documentation to describe its mixed inputs accurately and plainly. Follow the repository's documentation language guidance. A short description is sufficient; no test-by-test catalogue or historical narrative is needed in the module docstring.

Preserve test behavior, assertions, source claims, acquisition records and the distinction between publisher originals and derived artifacts. Do not change provider logic, repair audit results, move recordings, alter test selection or implement archive-access wiring. Those changes are outside this repair. Do not access or expose restricted material merely to verify this wording change.

Leave #429's archive-access refactor and #451's CHMI draft import error to their own work. #451 is recorded in an uncommitted implementation draft, not in the inspected main revision. Repairing #450 alone does not clear all recorded blockers or authorize #429 to resume. Resumption remains subject to the recorded blocker requirements and explicit owner permission.

## Acceptance and verification

- The opening description no longer labels all module inputs as synthetic.
- It clearly distinguishes authored synthetic controls from tests using retained publisher responses and derived audit outputs.
- Its description accounts for all tests in the module, including the unknown-statistic test, without conflating derived artifacts with original responses.
- The implementation diff changes documentation only. Tests, assertions and source claims remain unchanged.
- Review the final description against every test and the relevant audit read/write functions. Report source inspection as the basis for this documentation correction. Do not present it as a successful run of genuine-input tests or verification of USGS audit results.

No test execution or genuine-input acceptance was performed during discovery. There is no unresolved cause investigation required for this documentation bug. Implementation should confirm the current target still contains the same mismatch before applying the focused correction.
