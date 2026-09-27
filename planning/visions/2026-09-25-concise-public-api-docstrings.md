# Concise public API docstrings

Program: https://github.com/RivRetrieve/RivRetrieve/issues/378
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/380

## Outcome

Provide complete, accurate documentation content for the automatically generated
public API reference. Readers should be able to use supported interfaces and
interpret their results without reading implementation code. AI agents parsing
the reference are a primary audience. Human readers should also find it clear,
following the audience and language guidance in `docs/AGENTS.md`.

Completeness means explaining the contracts that matter, not adding prose to
every symbol. Use judgement: when a name and signature fully explain an
interface, no docstring or prose summary is required. Such interfaces must still
appear in the generated reference with their names and signatures. A missing
docstring alone is not a documentation defect.

## Public surface and content

Review every supported public function and user-facing returned interface,
including relevant types, methods, attributes, enum states, and exceptions.
Start with `src/rivretrieve/__init__.py`, then follow actual returned contracts.
The current generator and reference tests provide useful evidence, but do not
establish the complete public surface by themselves.

Public reachability determines scope, not the implementation directory or a
leading underscore. For example, `rivretrieve.fetch` is re-exported from
`_internal.discovery`; its docstring belongs on the implementation while its
reference entry uses the supported public name. Returned objects can expose
useful interfaces even when their types are implemented under `_internal`.
Describe how users receive and use them without inventing new top-level exports
or presenting private helpers as supported APIs.

Use NumPy-style docstrings where explanation is useful. Allow one-line summaries
when sufficient. Include only applicable sections. Do not repeat obvious names,
annotations, or defaults solely to populate sections or satisfy coverage checks.
When a parameter or return needs explanation, use the conventional NumPy section
structure, including the names and types needed by that structure.

Explain information the signature does not adequately convey, where applicable:

- accepted values, constraints, and the consequences of meaningful defaults;
- units, time zones, temporal support, and other conditions needed to interpret data;
- return contents, frame or dataset structure, and user-facing fields or states;
- side effects, resource use that affects callers, and prerequisites;
- relevant exceptions and supported partial-result behavior.

Preserve source facts, vocabulary, uncertainty, and unknowns. Keep null values,
absent rows, and failed requests distinct. Preserve failure identity and reason
alongside supported partial results. Document current behavior rather than
changing behavior to fit preferred documentation.

Add concise examples when they explain non-obvious use or remove ambiguity.
Give them enough input context and accurate expected behavior. Do not require
an example on every interface or duplicate handwritten User Guides in docstrings.
All docstring prose must strictly follow `docs/AGENTS.md`, including its preference
for clarity over compression. Concision must not remove necessary qualifications.

## Contributor rule

Add the following rule to root `AGENTS.md` as the durable maintenance requirement:

```markdown
## Public API docstrings

Use NumPy-style docstrings where public interfaces need explanation.
Apply this rule to public functions and user-facing returned types, methods,
and attributes, including those implemented under `_internal`.

Use judgement. If the name and signature fully explain an interface, no
docstring or prose summary is required. Do not add text or sections solely
for coverage or repeat information already clear from the signature.

Document what readers need to use and interpret the interface correctly:
non-obvious constraints, units, return contents, side effects, and failure
behavior. Include only applicable sections. A one-line summary is enough
when no further explanation is needed. Add examples when they clarify use.

All docstring prose must follow `docs/AGENTS.md`. Keep documentation accurate
when changing an interface.
```

Align the existing docstring guidance in `docs/development-conventions.md` with
this rule so contributors do not receive a conflicting blanket requirement.
The Effort's request for comprehensive docstrings is subject to this confirmed
judgement-based policy, rather than a requirement for prose on every interface.

## Repository evidence and workflow boundary

At discovery, `src/rivretrieve/__init__.py` re-exports the public functions from
internal modules. `scripts/generate_reference.py` lists additional returned
contracts and exceptions. `tests/test_reference_contracts.py` checks selected
returned fields and enum states. These are starting points for a comprehensive
behavioral review, not a substitute for it.

The current generator's `_contract` rejects missing docstrings. That behavior
conflicts with the confirmed signature-only allowance. Rendering, automated
docstring checks, and documentation delivery belong to sibling Effort #379:
https://github.com/RivRetrieve/RivRetrieve/issues/379.
Its workflow must retain signature-only public entries and avoid blanket
missing-docstring enforcement. Coordinate this requirement through the existing
Effort records rather than adding filler prose or silently expanding this work
into a renderer redesign. Neither Effort requires the other to land first;
report any integration limitation accurately until the workflow supports it.

This Effort owns public documentation content, the root contributor rule, and
alignment of the existing docstring convention. It does not own private-helper
rewrites, runtime or API redesign, new exports, provider-guide rewrites, public
launch, documentation deployment, or general release engineering. Both
repositories remain private. The initial broad request to cover all code was
clarified to mean the supported public API surface only.

## Concurrent repair work (2026-09-27)

The user reports that repairs and tests are in progress for
[Poland publication-aware downloads (#371)](https://github.com/RivRetrieve/RivRetrieve/issues/371)
and [interrupted-response retries (#375)](https://github.com/RivRetrieve/RivRetrieve/issues/375).
The user reports that one agent owns final verification and closure of both
issues together. Coordinate with that owner rather than closing either issue
from this documentation Effort. Verification is still in progress before these
issues are closed; do not treat an active test run as a successful result.

At this checkpoint, the Poland repair is in open
[PR #374](https://github.com/RivRetrieve/RivRetrieve/pull/374), on branch
`fix/poland-publication-aware-history`, with its existing worktree at
`.worktrees/visions/poland-publication-aware-history/`. Its PR records passing
focused checks but an earlier incomplete live full-history verification caused
by the interrupted-response failure tracked in #375.

The retry repair has since merged through
[PR #377](https://github.com/RivRetrieve/RivRetrieve/pull/377) at
`02643d7bea3d5de55e076cb30ced8798935815b7`. That PR records independent approval
and complete deterministic test coverage across two batches, with 4,423 passed
and three skipped. It did not attempt a live national download. Issue #375 is
still open, and successful Poland full-history verification must not be inferred
from the retry PR's merge. Its validation evidence is retained at
`.worktrees/evidence/http-retry-correctness/`.

The related provider documentation remains
in [PR #291](https://github.com/RivRetrieve/RivRetrieve/pull/291), with worktree
`.worktrees/visions/poland-provider-documentation-review/`.

Recheck the issues, linked PRs, test results, and worktree ownership when starting
implementation; these are dated coordination facts, not permanent blockers.
Work on this documentation Effort in a separate branch and worktree. Preserve
other agents' repair branches, worktrees, test runs, and evidence. Do not repair
those defects as part of this Effort or document unmerged behavior as current.
Most public API documentation can proceed independently. Before merging, compare
against the latest `main` and reconcile affected download, retry/failure, and
returned-store contracts with any repairs that have landed. If repairs remain
pending, describe the current behavior accurately and record the remaining
integration check rather than claiming the repairs have passed.

## Evidence of success

- Review covers the complete supported public surface and actual returned
  interfaces, with review evidence on the implementation PRs or Effort.
- Each interface has either sufficient name/signature information or concise,
  accurate NumPy-style explanation of its meaningful contract. Review explicitly
  considers whether omitted prose leaves a real ambiguity.
- Public documentation explains non-obvious return semantics and failures,
  preserving hydrological meaning and source uncertainty.
- Examples are accurate and useful. Validation can use local fixtures and must
  not depend on live providers or user credentials.
- Prose follows `docs/AGENTS.md`; root `AGENTS.md` and the development convention
  express the same judgement-based maintenance rule.
- Runtime behavior remains unchanged. Relevant repository checks pass, and any
  signature-only rendering limitation owned by #379 is recorded rather than
  concealed or counted as verified generated-output success.

Use the repository's `uv` commands for validation. Automated checks supplement
human or agent review of completeness and accuracy; a nonempty-docstring count
cannot establish success. This vision authorizes no implementation by itself.
