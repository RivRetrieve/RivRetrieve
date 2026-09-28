# Brazil provider documentation verification

Checked on 2026-09-22 for PR [#276](https://github.com/RivRetrieve/RivRetrieve/pull/276).
This is maintainer evidence, separate from the provider introduction.

## Revision and execution boundary

- Implementation and packaged catalogue: `19b4514` (the inspected `origin/main`).
- Documentation branch: `docs/provider-brazil`; merge `ad28fea` preserves the two
  original author commits and reconciles main without replacing other provider links.
- No production code or catalogue changes were made.
- Commands ran through `uv` from the repository root. Its implementation matches
  the merged worktree implementation. The working directory is intentional: normal
  public credential resolution uses its owner-provisioned `.env` or process variables.
  No credential file was read by the agent, copied, or included in these records.
- No receipt or authentication response was recorded. Public examples use
  `cache="bypass"`, so observation results are live rather than replayed or cached.

## Live examples

[`examples.py`](examples.py) contains the exact Python snippets from
[`br_ana.md`](../../providers/br_ana.md), in reading order. From the provisioned
repository root, the command was:

```bash
uv run python .worktrees/visions/brazil-provider-documentation-review/docs/verification/brazil-provider/examples.py
```

Captured stdout: [`live-output.txt`](live-output.txt).
Captured stderr: [`live-warnings.txt`](live-warnings.txt).
Both observation calls requested station `15400000`, daily mean discharge,
2020-01-10 through 2020-01-12, inclusive.

- The explicit `consistido` request returned three rows in m³/s, all with unknown
  time zone. Values were 31687.982, 31789.021 and 31553.52.
- The unrestricted daily selection requested both consistency identities. It
  returned the same three `consistido` rows and retained unresolved `bruto` identity.
  This is not evidence of a confirmed empty `bruto` record or history-wide absence.
  `source.unresolved_inventory` is a warning, also emitted through Python's default
  warning mechanism. Source status and unknown citation are informational issues.
- Telemetry selection was checked offline. Its frequency and statistic are null;
  no live telemetry observations are claimed by this verification.
- The example does not prove nationwide availability, continuous history, a
  preferred consistency level, or that the observations cannot change.

The displayed issue lists are distinct severity/code pairs, not issue counts.
Daily source status issues describe the full monthly response, rather than only
rows remaining after clipping to the requested three days.

There are no shell setup snippets in the provider page. Credential setup is prose
and links to the common usage instructions; no placeholder credentials were executed.

## Catalogue and implementation checks

[`catalogue.py`](catalogue.py) ran through the public `find` and `series` APIs.
[`catalogue-output.txt`](catalogue-output.txt) records 17,914 distinct stations and
107,484 candidates, exactly six per station. Each daily consistency/quantity
combination has 17,914 candidates; each adopted telemetry field also has 17,914.
This counts selectable candidates, not verified observations.

Code checks at the implementation revision:

- `src/rivretrieve/_internal/providers/br_ana/config.py` and `series.py` establish
  daily mean facts, consistency identities 1/2, telemetry measurement timestamps,
  unknown telemetry frequency/statistic, source units, and unknown time zone.
- `parse.py` keeps consistency identities separate, retains null daily slots,
  reports unobserved consistency as unresolved, preserves status strings in
  informational issues, and does not infer a quality ranking.
- Shared selection and retrieval preserve explicit variant scope. Recorded public
  tests exercise sibling isolation and unresolved availability. A successful
  `consistido` result alone does not prove all absent-sibling behavior live.
- `src/rivretrieve/_internal/discovery.py` resolves environment before the
  working-directory `.env`, including blank environment values, and reports
  credential presence separately from authentication.

## Recorded regression and documentation checks

These tests replay recordings or use controlled protocol inputs. They do not
establish current ANA service access. No new test was authored for this docs-only change.

```bash
uv run --with rdflib pytest -q .worktrees/visions/brazil-provider-documentation-review/tests/test_br_ana_public_daily.py .worktrees/visions/brazil-provider-documentation-review/tests/test_documentation.py .worktrees/visions/brazil-provider-documentation-review/tests/test_supporting_documentation.py .worktrees/visions/brazil-provider-documentation-review/tests/test_reference_contracts.py
uv run pytest -q .worktrees/visions/brazil-provider-documentation-review/tests/test_public_credentials.py
uv run python .worktrees/visions/brazil-provider-documentation-review/scripts/generate_reference.py --check
```

- Recorded public ANA + documentation/reference suite: **53 passed**, one existing
  rdflib deprecation warning; [`tests-output.txt`](tests-output.txt).
- Credential tests: **43 passed**; [`credentials-tests-output.txt`](credentials-tests-output.txt).
- Reference generation: current; [`reference-output.txt`](reference-output.txt).

## Authoritative sources

[`sources.md`](sources.md) records the independent source research, exact quotations,
URLs, dates and limits. Fresh content checks covered ANA's monitoring/manuals
index, open-data statement, current access-page text, and service OpenAPI. The
access page is a JavaScript application: its routed public page-description string
was checked rather than treating an HTTP 200 application shell as the instructions.
The source does not provide the original draft's “if you are Brazilian” qualification
for CPF/CNPJ. That unsupported qualification was removed.

Daily source meanings come from retained Hidro 1.4 dictionary evidence, rather than
a fresh installer download. Telemetry definitions likewise rely on the retained
manual excerpt. Neither is presented as a fresh PDF check. No formatted citation
was found in the bounded sources checked; this is not a claim about all ANA pages.
The open-data quotation is an institutional statement, not an inferred dataset-specific
licence. The source researcher made no authenticated observation request.

## Delivery limits

The documentation is subject to fresh independent review and user feedback.
This record does not grant approval or merge authority. No code defect was
established during these checks. There is no live-access blocker for the displayed
examples. The bounded source and observation checks above do not establish facts
outside their stated scope.

## Script formatting

On 2026-09-28, ancillary scripts received whitespace and import cleanup only.
The original executed bytes remain in Git at
`0b443049d50819978030e29e46011ca2101cb337`. The exact provider-example script
was left unchanged to preserve the recorded execution input. These maintenance
changes do not constitute a new execution of the historical verification.
