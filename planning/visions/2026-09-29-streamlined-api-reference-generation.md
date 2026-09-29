# Streamlined API reference generation

Program: https://github.com/RivRetrieve/RivRetrieve/issues/378
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/379

## Outcome and confirmed scope

Build the API reference directly from the NumPy-style docstrings completed in
Effort #380, using mkdocstrings rather than a custom docstring renderer. Remove
the duplicate generation run while keeping publication to the sibling repository
straightforward. Contributors maintain the source docstrings; the documentation
build renders them automatically.

This is the focused workflow follow-up to discussion #372. During discovery the
user narrowed the broader wording in #379: the publication workflow remains, and
the change is how the API surface gets documented. This vision supersedes the
ticket's broader proposals for PR validation, new Ruff docstring enforcement,
and a full documentation-pipeline redesign. Do not treat those proposals as
additional acceptance requirements.

Keep the existing publication triggers and relevant-change filtering for this
work. Removing the release trigger was discussed earlier in #372 and the ticket,
but is outside this narrowed renderer change. No new PR workflow, general CI
rollout, or recurring full test run is requested.

## Rendering and generation

Retain MkDocs and Material. Use mkdocstrings' Python handler configured for NumPy
docstrings to render the public API. Remove the custom docstring parsing and
formatting path rather than retaining a competing renderer alongside it.

Preserve the useful API surface and content established by #380: public
functions, user-facing returned interfaces, meaningful attributes and methods,
and relevant exception explanations. Supported interfaces implemented under
`_internal` still belong in the reference; private implementation helpers do not
become supported API merely because the handler can discover them. Preserve
names, signatures, useful sections, and examples. Interfaces whose names and
signatures are sufficient must remain discoverable without adding filler
summaries or requiring a docstring on every symbol.

Custom generation may remain for factual schema, capability, or product tables
that do not come from docstrings. Each required generation operation has one
owner and runs once per build. Do not replace the removed renderer with another
home-grown NumPy parser, Markdown exporter, or AI-specific documentation system.
The reference's audience and content were settled in #380; this effort does not
reopen them or require a second complete reference format for agents.

Choose the simplest ownership for reference source and generated files that
fits MkDocs. Adapt obsolete freshness checks to that ownership. If generated
files remain committed, check drift before any build step can overwrite it.
Avoid manual regeneration chores for API docstring changes. Keep relevant
contributor instructions accurate and concise.

## Existing workflow and evidence

- `.github/workflows/deploy-docs.yml` runs
  `scripts/generate_reference.py` directly. Its subsequent strict MkDocs build
  invokes `docs/hooks.py`, which runs the same generator again. The step named
  "Verify reference freshness" currently writes the reference rather than
  checking it. This double execution is the concrete duplication to remove.
- `scripts/generate_reference.py` combines custom docstring rendering with
  factual tables. `mkdocs.yml` already configures mkdocstrings, but the reference
  does not yet use its directives or an explicit NumPy parsing configuration.
- The hook also prepares the README-derived home page and station-map asset.
  Preserve those unrelated functions without turning this into a map or hook
  redesign.
- The existing workflow builds on selected pushes to `main`, releases, and
  manual dispatch. Its publication step is guarded to `main` and pushes `site/`
  to the paired repository's `main` using the existing deploy key. Preserve
  that transport, guard, and manual operation. Change the generation steps
  only as needed to integrate the new rendering path and remove duplicate work.
- The paired repository is
  https://github.com/RivRetrieve/rivretrieve.github.io. Its local checkout is
  `/Users/nicolaslazaro/Desktop/work/rivretrieve.github.io`. It contains generated
  output, not another MkDocs source project. Both repositories are private;
  GitHub reported `has_pages=false` during discovery. Successful publication
  means updated files in that repository, not a verified public website.

## Proportionate verification

Verify the renderer transition during implementation and independent review.
Build with `mkdocs build --strict` through the project environment and inspect
representative rendered reference pages, including functions, returned types,
exceptions, signatures without explanatory prose, NumPy sections, and examples.
Check that useful content and relevant reference links survive the transition.
A successful process exit alone does not establish that the content rendered.

Reuse and adapt existing focused coverage. In particular,
`tests/test_documentation.py` includes generated-reference freshness checks and
`tests/test_reference_contracts.py` protects fields and enum states. Preserve
their meaningful contracts while removing assumptions tied solely to the old
Markdown renderer. Existing offline example tests remain useful evidence; this
work does not require wiring them into every publication run or adding a
separate recurring documentation test suite.

Add a regression test only where a concrete behavior or failure warrants it.
Avoid exhaustive HTML snapshots, exact-prose assertions, duplicate checks, and
new testing frameworks. Follow the repository's test-contribution rule and
measure the runtime impact of costly new coverage. No live provider access or
provider credentials should be needed to verify reference generation.

Confirm that the normal workflow can build and publish the new output to the
same private endpoint. Report publication evidence against the source revision
and paired output revision when exercising it; do not equate a local build or
the configured site URL with successful publication. Do not add a second build
or recurring verification framework just to obtain this implementation evidence.

## Boundaries and success

Success means mkdocstrings renders the existing NumPy documentation faithfully,
the custom docstring renderer and duplicate invocation are gone, and the
existing private publication path still delivers the generated site. Ordinary
publication remains a lean build-and-push operation.

Do not change runtime API behavior, repeat #380's comprehensive content audit,
rewrite provider guides, redesign navigation or visuals, enable public hosting,
add previews, or alter package/release CI. No new blanket missing-docstring
requirement or Ruff docstring rollout belongs here. Preserve unrelated files
and work in both repositories.
