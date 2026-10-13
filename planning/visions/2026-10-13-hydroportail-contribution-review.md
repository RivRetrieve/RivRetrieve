# Review and finish the HydroPortail window-cap contribution

Freddy (GitHub `kratzert`) asked whether his HydroPortail change makes sense
before he opens a PR. Independently verify the contribution, repair concrete
faults, and open one PR containing his work and any justified repairs for his
review. Give the maintainer a concise verdict to send to Freddy on Slack.

## Contribution and scope

Review [the contribution branch](https://github.com/RivRetrieve/RivRetrieve/compare/main...fix/hydroportail-window-cap)
against [issue #443](https://github.com/RivRetrieve/RivRetrieve/issues/443).
At discovery, the branch tip was
`90a259f78ca25093991325d4ab60b76ee0f521f9`, one commit above merge base
`af074a126ab3892d19bc15bdd31e8971dbde6b51`. It changed HydroPortail's window
declaration and fetch loop, the shared window planner, and two test files.
Refresh branch, issue, PR, and target evidence when starting; these references
identify the reviewed starting point, not proof of current state.

The issue reports HTTP 400 above a 1,735-day request span, including padded
request dates. The branch chooses 1,000-day chunks, adds day/month/year rendering
to capped-span planning, and assigns chunk bounds to payloads and failures.
The reported limit and the suitability of that chunk size need independent
validation. They are not established facts merely because an issue or code
comment states them.

[Issue #417](https://github.com/RivRetrieve/RivRetrieve/issues/417) concerns
short-request timeouts and HTTP 503s. Do not claim this contribution resolves it.
This work concerns `fr_hydroportail`, not the separate `fr_hubeau` provider.

## Settled direction

Keep the chosen approach: split long HydroPortail requests into bounded chunks
using the existing window planner, then fetch those chunks. Review and repair
within that approach. Do not reopen the design decision, replace the architecture
based on preference, or expand into unrelated cleanup.

Correctness details, including bounds, failure handling, integration, tests, and
an evidence-backed chunk-size adjustment, remain open to repair. If evidence
shows the accepted approach fundamentally cannot meet the objective, report the
conflict to the maintainer rather than silently redesigning it. A materially
broader problem or redesign also requires returning to the maintainer.

## Evidence and review

Independently research the request contract and the evidence behind the reported
limit. Establish what is known about day counting, inclusive endpoints, padding,
and applicability to the affected products. Use source documentation, retained
material, and proportionate live observations where useful. State uncertainty;
do not require rediscovering an exact maximum when evidence already establishes
that the chosen requests are safe and the review's claims remain narrower.

Inspect the complete contribution and relevant surrounding contracts. Verify
that long requests are actually split and return correctly combined observations,
with no chunk-induced loss or duplication at boundaries. Check source-series
selection, preservation of source facts, chunk-specific failure reporting,
independent successful results, and affected cache coverage behavior. Review
shared-planner regressions and whether the change fits existing responsibilities
without unnecessary complexity.

Follow `docs/maintenance/testing.md`, `docs/maintenance/evidence.md`, repository
instructions, and the test-first development skill. Treat tests as design
evidence: identify the behavior promised, establish independent expected results,
and ask whether a plausible broken implementation could still pass. Reuse
existing sufficient coverage. Add focused tests for concrete gaps or repairs,
and observe the intended failure before implementing a repair when useful.
Do not add a test inventory, duplicate suites, or implementation-shaped assertions
merely to increase coverage counts.

The branch's test that manually supplies two rendered chunks demonstrates fetch
iteration; by itself it does not prove a long public request is planned and
assembled correctly. Investigate existing coverage before deciding what is
missing. Run affected source-independent tests and broader checks appropriate
to changed boundaries, using isolated cache and store roots.

Keep synthetic checks, retained-response replay, and live-service observations
separate in the conclusions. A passing synthetic test does not validate a
publisher limit, and a failed live request does not alone prove a library defect.
Follow the repository's genuine-input requirements when applicable. Report
unavailable mandatory evidence as blocked, never as a pass. Keep controlled
material and credentials out of public reports, logs, and committed artifacts.

## Delivery and authority

Use a separate integration branch targeting `main`. Preserve Freddy's commits
and authorship and leave `fix/hydroportail-window-cap` untouched. This authorizes
incorporating his existing commits into the integration branch; do not rewrite
his contribution merely to recreate it as agent-authored work.

Implement justified repairs and open one PR containing the contribution and any
repairs, crediting Freddy. Do not invent changes if his work already meets the
objective. Reuse a suitable existing PR if one appears before execution rather
than creating competing PRs; preserve his ownership and the same review boundary.
Explain the original contribution, any repairs, their evidence, and remaining
verification limits clearly. If mandatory verification remains blocked, keep
that limitation visible and do not describe the PR as ready to merge.

Assign the complete diff to a fresh independent agent that did not implement the
repairs. Give it this vision, repository rules, and validation evidence. Its review
must respect the settled direction while checking real behavior, regressions,
scope, safety, test quality, and unnecessary complexity. Address concrete
findings and repeat review after material repairs. Request Freddy (`kratzert`)
as the GitHub reviewer.

Do not merge the implementation PR, close the related issues, or send the Slack
message. This explicit no-merge boundary overrides the implementation workflow's
usual merge and post-merge completion steps. Completion here means the review
and justified repairs are delivered in the open PR, independent review is
finished, required verification is satisfied, and Freddy's review is requested.
If verification cannot be completed, report the precise blocker and preserve
inspectable progress instead of claiming completion.

Provide a detailed evidence-backed review report, with exact reviewed revisions,
checks, results, findings and their disposition, and any limitations. Include a
short Slack-ready message in the maintainer's voice: “I had my clankers look at
the work you did. Here is their verdict: …” Summarize the verdict, explain any
repairs without making Freddy rederive them, and link the PR for his review.
