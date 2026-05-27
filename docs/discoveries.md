# Discoveries

Cross-milestone notes that future planners, reviewers, and executors should know but that are not part of architecture.md or the milestone tracker.

## D1 — Per-commit version bump touches `src/rivretrieve/__init__.py`

**Found during:** M1 step 01-foundations executor handoff.

**The fact:** `AGENTS.md` §3 requires `uv run bump-my-version bump patch` before every commit. The `[[tool.bumpversion.files]]` configuration in `pyproject.toml` updates two files in lockstep:

- `pyproject.toml` `version = "..."`
- `src/rivretrieve/__init__.py` `__version__ = "..."`

This means **every step commit in this project mutates `src/rivretrieve/__init__.py`**, even when the step's plan explicitly forbids editing that file for API-surface reasons.

**Why it matters:** Step plans that include a "no `__init__.py` edits" scope guard (M1 step 01 had one; future M1 steps may want one) must distinguish between:

- API-shape edits (forbidden until the step that owns the public surface — M1 step 03)
- Version-literal bumps (mandatory per commit, do not count as scope drift)

**How to apply going forward:**

1. **Step planners:** When writing a "no `__init__.py` edits" guard, phrase it as "no API-shape edits to `__init__.py` (no symbol additions, no re-exports, no import changes)." Do not phrase it as a blanket file-modification ban. Explicitly mention that the per-commit version bump is exempt.

2. **Step reviewers:** Do not flag the version-literal mutation as scope drift on a step that disclaims API-shape edits. Do flag it as drift on a step that performs ANY other mutation to `__init__.py`.

3. **Step executors:** Run `uv run bump-my-version bump patch` after all other staged changes pass `ruff format`, `ruff check --fix`, `ty check`, and `pytest`, and before committing. Tag with `v$(uv run bump-my-version show current_version)` after commit.

4. **The negative-control test that the public surface is unchanged** (M1 step 01 T17, and the offline-import test M1 step 03 will own) must assert *symbol absence* (`providers`, `provider`, `provider_info`, internal type leakage), not file-content equality. The current T17 already does this correctly.

**Architecture status:** Not an architecture.md contradiction. This is project commit policy interacting with step scope guards. Resolved at orchestrator level for M1 step 01; recorded here so subsequent step planners encode the exemption explicitly rather than re-deriving it.

**Forward implication:** Each M1 step lands its own patch bump. This branch already had a `v0.1.3` tag on commit `6488f6e` while configured files still said `0.1.2`, so M1 step 01 resolved to the next unoccupied patch tag, `v0.1.4`. Future step planners should inspect existing tags before assuming the next version from file literals alone. The M1 closing version is therefore not a planner decision — it falls out of the step count and pre-existing tag inventory. Note for the M5 conformance milestone: any version-tag inventory should expect step-granular tags, not just milestone-granular tags.
