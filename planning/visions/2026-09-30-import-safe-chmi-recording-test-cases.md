# Import-safe CHMI recording test cases

Repair the test-discovery error reported in [bug #451](https://github.com/RivRetrieve/RivRetrieve/issues/451). The CHMI observation test module must load without archive access, while retaining its genuine-recording cases and assertions.

This is a standalone, narrow repair vision. It addresses a blocker of [#429](https://github.com/RivRetrieve/RivRetrieve/issues/429); it does not replace that Effort's vision or authorize resuming its broader implementation.

## Why discovery fails

Python evaluates pytest parameter decorators when it loads a test module. Pytest supplies fixture values later, when setting up a selected test. The preserved draft constructs two parameter values with `recording_root` before that fixture is available. Module loading fails before any test body runs.

The draft's `--logic-only` option cannot prevent this error. Its collection hook excludes evidence-backed tests only after pytest has loaded their modules.

## Source evidence and location

The investigation on 2026-09-30 confirmed the error in the uncommitted draft at:

- Worktree: `.worktrees/visions/effort-429-test-inputs`
- Branch: `effort-429-test-inputs`
- Base commit: `afdf85eee1188f9e0073be102630cc48af0b6a4e`
- File: `tests/test_cz_chmi_observations.py`

That base commit does not contain the uncommitted changes. Locate and inspect the preserved draft before editing. If it is unavailable or has changed materially, report the gap rather than assuming the defective code exists on `main` or reconstructing the entire #429 refactor.

At investigation time:

- Lines 67–68 used `recording_root / _DQ` and `recording_root / _HQ` in the parameter list for `test_parse_official_annual_recordings`.
- `_DQ` and `_HQ` were plain recording filenames.
- The test body already used `ReplayTransport([recording_root / recording])`.
- The module's `recording_root(evidence_inputs)` fixture returned `evidence_inputs["cz_chmi_code_inputs"] / "tests/test_data"`.
- The test carried `pytest.mark.recorded(inputs=('cz_chmi_code_inputs',))`.
- `tests/conftest.py:51` defined the post-import `pytest_collection_modifyitems` filtering hook. Its `evidence_inputs` fixture at line 96 required an explicit reviewed archive handoff.

A fresh source-only check from the draft worktree, equivalent to the following command, reported exactly two F821 undefined-name errors at lines 67–68:

```console
uv run ruff check --no-cache --select F821 tests/test_cz_chmi_observations.py
```

The #429 issue also records an earlier logic-only collection attempt that failed with this module-scope `NameError`; no test bodies executed. That is historical failure evidence, not a passing check. This investigation did not execute private recordings.

## Repair boundaries

Keep the parameter cases source-independent: carry recording filenames and existing expected values. Join each filename to the fixture-provided root during test execution, where the draft already performs that operation. Align the parameter annotation with the filename value.

Preserve both daily and hourly cases, their product selections, expected counts and time boundaries, the archive binding, and all provider-specific assertions. Preserve explicit failure when requested evidence inputs are unavailable. Do not acquire or resolve private evidence at module import, restore hard-coded source-tree data paths, silently skip requested verification, or substitute synthetic provider recordings.

Limit changes to this defect and focused regression protection. Do not change provider behavior, governing claims, archive storage, or the unfinished shared input contract. Preserve all unrelated uncommitted #429 work. Do not publish that broad draft as part of this repair. The implementing agent must account for the fact that the defect exists only in preserved draft state when choosing a safe delivery method; a no-op change to clean `main` does not establish repair.

## Evidence of success

1. The focused undefined-name check passes for the repaired module.
2. Collection without an archive handoff discovers both annual-recording cases without requesting fixture values or reading private recordings.
3. Logic-only collection can exclude the module's evidence-backed tests without an import error. Treat a deliberately empty selection separately from a collection failure; do not describe zero executed tests as passing source verification.
4. Existing recording assertions and evidence requirements remain intact. Use focused regression coverage or existing collection checks rather than adding a broad testing framework.

Report the exact commands, results, and limits. Collection and lint establish import safety, not genuine-recording correctness. Any genuine-input execution must follow the repository's reviewed, restricted archive workflow. Missing mandatory evidence is blocked, never acceptance. Broader #429 verification remains that Effort's responsibility.

## Coordination and non-goals

At authoring time, #450 was closed after documentation PR #453 merged. That closure explicitly did not authorize #429 to resume. Recheck current issue and draft state during implementation; repair of #451 alone is not permission to continue #429. The Program's owner-controlled stop-and-report rule remains in force.

This vision authorizes neither a provider-data investigation nor completion of the all-provider refactor. No recordings should be changed, copied into public artifacts, or exposed through diagnostics. Publication of this vision is documentation only and must not close #451 or #429.
