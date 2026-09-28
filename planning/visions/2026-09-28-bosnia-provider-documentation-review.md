# Bosnia provider documentation review

## Outcome

Update the existing [provider documentation PR #296](https://github.com/RivRetrieve/RivRetrieve/pull/296),
`docs/provider-bosnia` targeting `main`, with a correct, readable provider page and
an accurate PR description. Preserve Thiago’s useful work and authorship where
possible. Do not replace the delivery with a new provider documentation PR.

The original page predates the API and behavior changes incorporated through
[PR #300](https://github.com/RivRetrieve/RivRetrieve/pull/300). This work migrates
the documentation itself. Readers need only the current behavior, not a migration
guide, compatibility advice, or an explanation of retired API calls. Use the
current implementation at execution time, including changes after #300.

This is a standalone vision. Its publication does not implement the documentation
review or authorize approval or merge of PR #296.

## Reader experience

Follow `AGENTS.md` and the mandatory writing guidance in `docs/AGENTS.md`. Write
for an educated hydrology reader with basic Python knowledge. Use the merged
pages in `docs/providers/` as strong templates, particularly the recently merged
Czechia and Lithuania pages. Keep repeated table labels and terminology consistent
with those references, while retaining source-specific facts and qualifications.
Do not expand this task into a rewrite of other provider pages.

Explain the relevant national context of Bosnia and Herzegovina, who measures
and publishes the data, and what RivRetrieve exposes. Establish the relationship
between provider identifier `ba_fhmzbih` and AVP Sava, the publisher named by the
original page. Do not imply nationwide coverage, agency responsibility, or
station ownership beyond the evidence. Explain the actual geographical and
institutional scope using authoritative sources.

Introduce one practical retrieval example with enough context to interpret its
inputs, output, units, time, and reported issues. Additional snippets are useful
only where the provider requires them. Link general selection and result-handling
instruction to `docs/usage.md`; do not turn the page into a mechanical API
reference. Describe source conditions that affect use, including coverage,
availability, data status, and terms. Keep detailed verification methods and
internal implementation evidence in a supporting verification record.

## Starting evidence, not accepted claims

Discovery inspected the original PR, current provider configuration and fetch
code, merged provider pages, and bug reports #305 and #324. It did not execute
the Bosnia examples or establish fresh live source facts.

The original PR changes `docs/providers/ba_fhmzbih.md` and `docs/README.md`.
Its example uses `product="discharge_reported"`, then selects station `2310`.
Replace outdated public calls with the current API and verify the chosen station
and period rather than carrying them forward automatically.

The current provider code is under
`src/rivretrieve/_internal/providers/ba_fhmzbih/`, with the packaged catalogue in
its `catalogue/` directory. At discovery, configuration mapped discharge, stage,
and temperature to AVP Sava workbooks `Q_1Y.xlsx`, `H_1Y.xlsx`, and
`Tvode_1Y.xlsx`. It retained unknown temporal support and time zone. These facts
are implementation context, not a reason to teach internal product identifiers
on the provider page.

Recheck every original claim. In particular:

- The counts of 60 stations, discharge and stage at all 60, and temperature at 12
  must be checked against the current packaged catalogue. Distinguish catalogue
  membership from actual data availability for a requested period.
- The rolling one-year history claim must be supported and qualified. A short
  retrieval does not establish full historical coverage or continuity.
- Observed approximately hourly spacing does not establish a published hourly
  statistic, instantaneous values, or temporal support.
- Verify source and returned units, timestamp interpretation, and source status.
  Preserve unknowns rather than filling them in from geographical assumptions.
- Verify the Impressum quotation and its unofficial translation. Establish what
  the inspected authoritative sources actually say about reuse and citation.
  Do not turn failure to identify terms into an unbounded claim that none exist.

## Verification and delivery evidence

Check every factual claim against current code, the packaged catalogue, or
authoritative sources, as appropriate. Retain enough traceable evidence to show
which source supports each substantive claim. Record source access dates and
limits. Existing prose, historical PR descriptions, and recorded tests are not
fresh live verification.

Execute every final Python snippet exactly as documented through the current
public API, using the repository’s `uv` environment. Respect any documented
shared-session prerequisites. Use live retrieval where applicable and bypass
local observation caches when establishing fresh source behavior. Check displayed
outputs, returned units and time information, row counts, issues, and every
behavior promised by the surrounding prose. Re-execute affected examples after
changes, including after a reported bug repair.

Choose a useful example within verified source availability. Explain rolling
availability honestly; do not promise that a fixed historical period remains
retrievable indefinitely. Preserve the distinction between published nulls,
absent observations, and failed requests. Do not treat successful retrieval or
an empty issue tuple as evidence of measurement quality.

Keep a supporting verification record following the merged provider examples.
Identify the tested revision, commands, exact output, live-check dates, source
references, and remaining limitations. Clearly distinguish fresh live checks,
recorded-source tests, and any authored controls. An outage or unavailable source
evidence blocks the affected verification; do not substitute a recorded test and
call the claim live-verified.

Update PR #296’s description to match the final changes and actual evidence.
Remove stale claims and disclose limitations and any repaired defects relevant
to verification. Preserve the documentation-index integration. Limit changes to
documentation and supporting verification material; no production code changes,
provider expansion, catalogue regeneration, or unrelated cleanup belong here.

## Mandatory defect stop

If the implementation agent finds a code defect, stop implementation and review.
Open a GitHub issue labelled `bug`, assign it to `CooperBigFoot`, and include
reproduction steps, tested revision and commands, expected versus actual
behavior, and supporting evidence. Distinguish a demonstrated code defect from
an upstream outage, missing source data, or a mistaken verification assumption.
[Issue #305](https://github.com/RivRetrieve/RivRetrieve/issues/305) and
[issue #324](https://github.com/RivRetrieve/RivRetrieve/issues/324) are examples
of the expected evidence and explicit pause.

Do not fix production code. Do not conceal the defect by changing examples,
weakening claims, bypassing the failing path, or presenting partial verification
as complete. Preserve inspectable partial work and report the blocker. The user
will repair the defect. Wait until the user explicitly reports it repaired, then
reverify the affected path and final examples before continuing. A commit or
closed issue alone does not replace that user report.

## Acceptance and human review gate

The documentation is ready for human review when:

- PR #296 contains a current-API page consistent with the merged provider docs,
  preserving useful original work and explaining the provider’s actual context.
- Every factual claim has appropriate evidence, and every final snippet has
  executed as advertised, with accurate displayed output and qualifications.
- The verification record distinguishes live checks from recorded tests and
  retains the evidence and limits of the checks.
- The PR description accurately reflects the delivered changes and verification.
- No production fix or documentation workaround has bypassed the defect gate.

Present the updated PR and verification results to the user. Independent agent
review may support this handoff but cannot replace human review. The user will
review PR #296 and provide feedback before the implementation agent concludes.
Wait for that feedback and address it. Never approve or merge PR #296 on the
user’s behalf. These restrictions remain binding even if a generic implementation
workflow would normally merge a completed PR.
