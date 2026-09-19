# Rewrite project agent instructions

## Outcome

Rewrite the root `AGENTS.md` as concise, concrete guidance for working on RivRetrieve. This is a full cleanup, not just removal of one stale link. The file must work for a fresh coding agent without this conversation, a particular agent runtime, or retired discovery-workflow artifacts.

RivRetrieve provides faithful, traceable access to river-gauge data through a consistent shape. It harmonises objective identity and physics while leaving source judgement uninterpreted. Preserve that purpose and point to maintained architecture documentation rather than rebuilding a glossary or decision archive inside the instructions.

The user explicitly rejected mandatory mathematics everywhere. A module should have a clear responsibility; mathematical signatures in every module docstring are not required. Remove the instruction to stop implementation when such a signature cannot be written. Mathematical notation remains acceptable when it genuinely clarifies a specific computation.

## Settled guidance

Preserve useful project constraints, but rewrite their presentation to fit this library:

- Use `uv` exclusively for project dependencies and execution. Retain actionable dependency, environment, test, formatting, lint, and type-check commands, including `uv run pytest`, `uv run ruff format`, `uv run ruff check --fix`, and `uv run ty check src`.
- Retain the warning that `tests/typecheck/nominal_window_misuse.py` is an intentional negative fixture exercised by engine-contract tests. The normal type-check target is `src`; do not suppress the negative fixture.
- Give modules clear responsibilities and pass narrow dependencies. Do not mandate mathematical notation or unrelated training/evaluation examples.
- Resolve configuration, environment, paths, and resource wiring at explicit composition boundaries. Recognize public library API boundaries as well as CLI entry points; do not imply that only a CLI or `main()` can compose the application. Lower-level operations receive the dependencies they need.
- Parse external inputs into appropriate domain types at their actual boundaries, including provider responses arriving after initial API composition. Preserve typed invariants and unit clarity without wrapping every value or bulk array. Keep named domain states distinct from incidental boolean flags.
- Preserve source facts and unknowns without inventing interpretations or required-input defaults.
- Distinguish fatal internal contract errors from source failures explicitly retained as issues at established isolation boundaries. Do not permit silent log-and-continue behavior, but do not replace the supported partial-result model with a blanket crash rule.
- Prefer library-specific assertions for complex data objects over manual element-by-element structural checks.

Remove references to retired `CONTEXT.md`, ADRs, and discovery-workflow artifacts from the instruction file. Keep links only to maintained, relevant documentation. Remove obsolete synchronized-doctrine markers and their digest, abstract slogans that add no actionable guidance, unrelated examples, and redundant wording. The rewrite need not follow the old section structure or synchronize with another repository's instructions.

Do not duplicate Prime Agent's tools, delegation procedures, or workflow machinery. Keep instructions project-specific and runtime-independent. Do not turn general engineering practice or mechanically enforced lint rules into a long checklist.

## Repository evidence and historical boundary

At discovery, fetched `main` was `906fed6`. `AGENTS.md` still referenced `CONTEXT.md`, used a synchronized doctrine block, required mathematical module descriptions, and described composition only through CLI commands or `main()`. `CLAUDE.md` simply pointed to `AGENTS.md`.

`docs/architecture.md` describes public composition in `_internal/discovery.py`, source-specific fetch and parse stages, and the distinction between retained source-call issues and fatal contract errors. Use current code and maintained documentation to make the wording accurate, not to authorize architectural changes.

Although the user described deleting the old context artifacts, `CONTEXT.md` was still tracked on the fetched target at discovery. The settled requirement is to remove its authority and reference from `AGENTS.md`, not to delete that file as part of this task. Recheck the target when implementing; do not infer repository-wide deletion authority from the user's description.

The historical `planning/visions/2026-09-02-streamline-agents-md.md` required a shared pyplate baseline, synchronized doctrine, and ADR-based relocation. This new outcome supersedes those prescriptions for the current `AGENTS.md` rewrite. Leave that historical vision unchanged. Do not revive its relocation campaign, ADR destinations, or synchronization requirement.

## Scope and exclusions

The implementation changes only root `AGENTS.md`. No production code, tests, provider documentation, catalogue artifacts, parent-directory instructions, `CLAUDE.md`, or other repository files need changing. Do not delete other files, recreate retired artifacts, add instruction-enforcement tests, introduce hosted CI, or refactor software to satisfy revised prose.

This is standalone work, with no Program or Effort provenance. Publishing this vision does not implement the rewrite.

## Evidence of completion

- The diff changes only `AGENTS.md` and reads as a coherent rewrite rather than a stale-reference patch.
- The file retains the project purpose, native tool commands, negative-fixture warning, narrow dependencies, domain invariants, source fidelity, explicit failure handling, and complex-data assertion guidance.
- There is no mandatory mathematical-docstring rule, unrelated training example, synchronized-doctrine marker, retired-document reference, or runtime-specific workflow machinery.
- Its composition, parsing, and failure guidance matches the current library architecture and partial-result behavior.
- Every retained local documentation link names a maintained file on the target branch.
- Independent review checks the complete rewrite against this vision. A prose-only change does not require new executable tests or behavior changes; validate the diff and references directly.
