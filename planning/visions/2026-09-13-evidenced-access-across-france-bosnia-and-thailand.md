# Evidenced access across France, Bosnia and Thailand

Program: https://github.com/RivRetrieve/RivRetrieve/issues/6
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/225

Status: Implementation vision. Remote publication, Effort linkage and verification on `main` remain pending.

## Outcome

Replace the sample-only observation selections for France, Bosnia and Thailand with
source-evidenced access across their original captured station inventories. Every
applicable station/measurement pair must have a truthful acquisition and availability
account. A user can select an evidenced pair even when its availability is unknown;
fetching it can return measurements, an empty result, or an explicit source issue.
None of these states may silently become a claim that the source cannot supply the
measurement.

This is the remaining coverage outcome required before Program #6 publishes v0.1.0.
It is not a promise of every gauge in those countries, every product at every station,
continuous records, or successful retrieval for every requested window.

Nicolas owns acceptance, remaining verification, implementation and delivery. Thiago's
ordinary research issues #222, #223 and #224 remain outside PCE. His revised PRs are
inputs, not an oracle or permission to merge their entire contents unreviewed. Nicolas
explicitly took over the remaining verification: do not restart a correction-request
cycle with Thiago.

## Observable destination

The baseline IDs are those in the committed native tables, not a new live inventory.
The completed verification accounts for these populations:

| Provider | Baseline stations | Applicable pairs | Positive availability evidence | Unknown availability |
| --- | ---: | ---: | ---: | ---: |
| `fr_hubeau` | 7,323 | 33,139 | 20,966 | 12,173 |
| `ba_fhmzbih` | 60 | 180 | 132 | 48 |
| `th_thaiwater` | 825 | 1,650 | 1,096 | 554 |
| Total | 8,208 | 34,969 | 22,194 | 12,775 |

An applicable pair is supported by its source identity, product definition and actual
request/response evidence. This is not an inferred station × product cross-product:
France has 6,454 hydrometry stations with five applicable hydrometric products and
869 temperature stations with temperature only. Each Bosnia pair has a matching
workbook acquisition. Each Thai station has a matched graph response carrying both
source fields, together with the evidenced field meanings.

At discovery close, the public observation selections remain France 3 stations / 6
series, Bosnia 2 / 3, and Thailand 1 / 2. Verification has not changed those catalogues
or implemented the broader retrieval paths. The destination above is the expected
post-integration selection, subject to passing the normal identity, origin and
acquisition checks. Report any actual conflicting evidence rather than forcing a
count to match this table.

### Unknown is a selectable state, not an exclusion

Existing `selection.py` excludes `availability == "unavailable"` only. Its tests
explicitly include unknown availability. Preserve that contract; a positive-only
selection would introduce a new exclusion policy.

The 12,775 unknown pairs retain their precise dated evidence and limitations. They
must not be described as unsupported, universally absent, or lacking an acquisition
record once their governing acquisitions are bound. Conversely, an identity mismatch,
an inapplicable product or genuinely unestablished acquisition must not be waved
through by labelling it unknown. Preserve the distinction between unknown availability
and a withheld fact.

Positive availability means the recorded basis supports availability: publisher
observation counts for the relevant French queries, numerical witnesses for historical
France cases, or non-null measurements in the Bosnia/Thailand captures. It is not a
promise that every row or every requested period contains a numerical measurement.

## Settled source behaviour

### France: the selected station's own discharge

A station selection returns that station's own instantaneous discharge series, not
its shared site's series. HydroPortail documents that one station at a time supplies
a site's discharge and that the supplying station can change. A site series is a
different object; it must not appear as independent measurements from every linked
station. Site-level access and activation-calendar research are outside this outcome.

The station route is now directly verified with a complete response from
`/stationhydro/ajax/1232000101/series`: the returned station code, metric Q, UTC zone,
series unit and numerical values agree with the requested entity. This supplies the
missing representative station-Q evidence; it does not certify every station by
sampling. Preserve the published station and site mappings, never derive them by
truncating identifiers.

The current France adapter still selects a site for Q, has a one-station identity map,
and hard-codes a Q response entity. Its declaration, request construction and response
validation must all become consistent with station-own Q. Do not merely expand a
catalogue in front of sample-only wiring. The response's actual series unit is distinct
from a display preference such as top-level `unitQ`; retain the evidenced physical
conversion rather than inferring units from a UI setting.

Retain HydroPortail historical access for instantaneous products, with the station
identity correction. No additional recent-route switch or redundancy feature is
required. The claimed freshness advantage over Hub'Eau was withdrawn: preserved
comparison responses have the same latest instant. Hub'Eau daily/temperature routes
and source-published products remain in scope without local aggregation.

France's final research partition is:

- 20,966 positive availability conclusions;
- 4,948 publisher whole-record count zeros;
- 524 pairs empty in both specified historical windows;
- 97 historical-check failures;
- 6,604 recent-empty pairs whose history was not checked.

The last four groups map to unknown availability with their separate reasons. A
whole-record zero describes the source response at acquisition, not a permanent ban
on future measurements. Two empty windows do not prove whole-history absence.
The failed/unchecked states are accounted research limitations, not permission to
claim that a historical search was completed.

`J783301020` instantaneous Q returned HTTP 500 for 1–8 June 2026 and an empty 2023
window in the bounded pass. Its older two-window-empty claim was replaced by a failed
check. Do not retry it or the 6,604 unchecked pairs merely to make the ledger look
complete. Normal future user retrieval still handles source outcomes through the
existing engine issue contract.

### Bosnia: exact workbook identities and rolling access

All 60 baseline stations have captured numerical Q and H evidence; 12 also have
numerical WT evidence. The remaining 48 WT workbooks are valid, station/parameter/unit
matched downloads with zero data rows. They remain unknown availability and selectable
under the existing contract, not unsupported measurements.

Read actual measurement cells, not just the workbook's `#Rows`. Timestamped blank
cells are genuine source records but not numerical values. The completed independent
verification checked raw workbook XML and the pinned production parser, including
mixed numeric/blank workbooks and the nonnumeric station ID `2101-B`. Preserve source
identifiers as strings and use the recorded metadata's `site_no` for the workbook
route; never guess a group from the station number.

The established retrieval uses rolling workbooks. Keep the configured yearly access
and known monthly example distinct from a historical archive. State the window each
capture actually contains. The research has not established a longer-history method;
failed guessed filenames do not prove that no such method exists. Do not claim the
publisher accepts no other date parameters or offers exactly two possible periods.
An old requested window can legitimately produce no rows from a rolling download.

Keep the stable public key `ba_fhmzbih`. Correct institutional display descriptions
and provenance to the evidenced AVP Sava publisher, without an implicit provider-ID
migration. Expansion to the additional 39 surveyed surface-water objects, the EPP
layers or other objects in the 230-object document is not part of this baseline outcome.

### Thailand: split the actual source window

All 825 baseline stations have governing graph responses. The recorded positive
counts are 813 stage and 283 discharge; 12 stage and 542 discharge results were empty
in their tested windows. Both fields' meanings come from the official source evidence,
not from assuming metadata's differently named water-level fields are interchangeable.

Use the existing engine-owned `capped-span` mechanism with a conservative size of
365 inclusive calendar dates per SOURCE request. This size was directly verified for
a normal window and a leap-containing window. The latter returned a complete null grid,
which proves the requested span was honoured, not that historical measurements exist.
Do not claim this is the source's exact maximum or a universal leap-year rule.

The engine adds two days to each side of the requested interval BEFORE planning source
windows. A 365-date user request can therefore require multiple source requests.
Split the padded window; do not add a separate public 361-date restriction, duplicate
padding, or write date-splitting arithmetic in the provider. Each chunk needs its own
bounds; backwards traversal is not required.

Direct captures demonstrate that padding plus final clipping explains the prior
two-day difference between the direct probe and public result. D11's revised claim
of an unstable source floor overlooked that path and must not survive as an accepted
finding. A silent cap can also cause accumulated-cache coverage to claim an interval
that was not actually requested in full: verify the corrected public fetch and
reuse/refresh paths, not just standalone planner arithmetic.

The final governing windows are seven or 91 inclusive dates, not an assumed 90-day
rule. A null-only response does not establish unsupported products. Keep the original
825 identities, including the 25 absent from a later snapshot. Do not add the 605
newly observed IDs or replace the baseline with the 1,405-row snapshot. The original
snapshot has been recovered and checked; no fresh station discovery is required.

## Attribution and fidelity

The approved requirement is traceable official publication: what was acquired, where,
when, and the issuing/publishing body responsible for the supplied material. This
preserves the accepted #51 acquisition contract; it does not require reconstructing
all historical sensor operators or original measurers before expansion.

Keep publisher, platform operator, station-reference organisation, collector and
original measurement producer roles distinct. France's official publishing and PHyC
statements, recorded role definitions and source terms now support that distinction.
`NomIntervenant` alone gives an organisation name without a measurement-production
role; `ProducteurDuJeu` identifies a station-referential dataset producer. Neither may
silently become authorship of every historical measurement or shared-site series.
Correct the old three-station attribution assertions where they exceed their evidence,
without inventing replacement original producers.

For Bosnia, AVP Sava is the evidenced issuer of the directly acquired station/workbook
material. For Thailand, preserve the existing verified per-station supplying-agency
bindings and distinguish them from HII's platform role. Where additional upstream
responsibility is not established, disclose that limit explicitly.

Retain source terms and citation words verbatim. A publisher label does not declare
an unresolved dataset-author citation question satisfied. Do not classify licences,
infer redistribution permission, or use an assumed legal verdict to silently remove
needed evidence. Source units and wall-clock timestamps retain the existing engine
contracts. Do not invent zones, temporal support, datums or published record bounds,
and do not aggregate products the source does not publish.

## Evidence already acquired: reuse it, do not restart the survey

The canonical discovery decisions and verification checkpoint are on the Effort:

- [Ownership and France station-own discharge](https://github.com/RivRetrieve/RivRetrieve/issues/225#issuecomment-5655022916).
- [Attribution scope and bounded Thailand capture approval](https://github.com/RivRetrieve/RivRetrieve/issues/225#issuecomment-5655060163).
- [Completed three-country verification and accounting](https://github.com/RivRetrieve/RivRetrieve/issues/225#issuecomment-5655285384).

Research inputs reviewed before agent-owned verification:

| PR | Reviewed commit | Role |
| --- | --- | --- |
| #228 | `5d9596cfe4f05fcc3eaac98525be97eb976335dc` | Bosnia research and source metadata |
| #229 | `c3e4f8003d4acb347ce9db58721ccc4e2933a877` | Thailand research and recorded-window inventory |
| #230 | `9ffab6e3b37ea0dd94a6e3fef8d72a944ee7c739` | D11 guidance, requiring padding correction |
| #231 | `46b2fde90b3aed5ab6993e625e6118815f9fa22b` | France research and compact count/history bundles |

These PRs remain unmerged. Complete private source responses and source-grounded
verification supersede their receipt-only availability claims and the disclosed
remaining errors. The new research-only scanners forbidding all measurement values
are not an approved project-wide policy and must not be adopted as one. Existing
recorded-source test conventions remain in force.

### Controlled local handoff

On the discovery machine, the evidence root is:

`/Users/nicolaslazaro/.local/share/rivretrieve/review-evidence/effort-225/`

Use its manifests and exact acquisition references, not disposable `/tmp` copies or
memory of this conversation. This is a local controlled corpus, not a public download
URL or an artifact already available in a fresh clone. If it is unavailable to the
implementing environment, stop and arrange an authorised reviewable handoff. Do not
substitute hashes without bodies, repeat the full survey automatically, or pretend
that a later response recovers discarded earlier bytes. Some working scripts retain
original scratch paths: inspect their arguments and adapt a working copy to the
retained inputs before offline replay. Never accidentally rerun an acquisition script.

- **`ba_fhmzbih/`:** read `COMPLETION.md`, `completion-summary.json`,
  `baseline-source-selection.json`, `baseline-180-verified.json`/`.csv`,
  `verify-baseline-180.py`, its validation log and `FILE_HASHES.json`. All 180 pairs
  have complete source responses: six valid historical positive captures, 126 positive
  captures from September 13, and 48 empty WT captures from September 9. The historical
  positives retain September 2/7 dates. The final 120-request pass succeeded without
  retries in 146 seconds; independent XML and production-parser counts agree.
- **`fr_hubeau/`:** official publisher/role documents and the station-Q witness are
  retained at the root. `reused-pr231-head46b2fde/` holds the pinned inventory and
  compressed source bundles. `availability-verification-20260913/` contains the final
  `governing-evidence-ledger.json`, `independent_verify.py`,
  `independent-verification.json`, `retired-historical-totals.json`, `manifest.json`
  and the offline selectability projection. Exact Hub'Eau bodies support all primary
  count conclusions; the bounded pass preserved every response, including the new
  HTTP 500. Fifty-nine unsupported old precise historical totals are retired in favour
  of exact positive witnesses. Do not reproduce those old totals from summaries.
- **`th_thaiwater/`:** the initial captures prove safe source-window handling and
  recover the old complete snapshot. `baseline-capture-2026-09-13/` holds
  `verified_final_inventory.csv`, `verified_summary.json`, `differences.json`,
  `CONTRACT_SYNTHESIS.json`, `MANIFEST.json`, offline verification scripts and
  `complete_raw_evidence.zip`. The final 813-request pass took 34.2 minutes with no
  failures/retries; 12 complete September 11 responses were reused. All 1,650 final
  count/status results match the revised research. The 25,582,314-byte full bundle has
  SHA-256 `46320ee0fa6b908c6009f223f59d6daa94f836bdfe3bbf82fee6d4354779c73f`.

All three final corpora were independently checked and their manifest hashes checked
again by the root agent. Their dates are intentionally mixed and explicit. They are
not a simultaneous live snapshot, do not establish continuous history, and do not
certify obsolete adaptive-survey anecdotes or unsupported exact old totals.

Keep this verification corpus private and out of wheels and other distributed
artifacts. Retaining review evidence is distinct from publishing a data archive.
Reconcile research publication, portable offline verification and any required
recorded-test inputs through the repository's reviewed process; do not upload the
private corpus automatically or weaken genuine-recording requirements for convenience.

## Completion evidence

Delivery must demonstrate the following externally observable results:

- Reproducible, offline catalogue/provenance builds expose the evidenced baseline
  station/product selections, with available/unknown counts and no unexplained missing
  baseline IDs. Every admitted fact has its proper source/acquisition binding; every
  genuine exclusion has a precise reviewed reason. Preserve native-table packaging
  safeguards and existing origin conversions/checks.
- The ordinary public discovery and retrieval functions work beyond the old samples.
  Station identity is correct end to end, particularly France station Q and Bosnia's
  metadata groups. Returned physical units, timestamps, receipts, issues and source
  roles remain faithful to the established contracts.
- Tests exercise the actual changed paths using recorded source interactions. For
  bug fixes, first demonstrate the failing real path, then make that same test pass.
  New boundary expectations must satisfy the repository's independent-authorship rule;
  the research scripts' observed parser outputs are not an independent expectation
  merely because they were recorded. Test Thailand's padded multi-chunk and cache
  paths, and keep valid empty/source-failure outcomes distinct from contract defects.
- Research conclusions and verification agree. Bosnia's old verifier accepted a
  deliberately false positive summary despite unchanged blank source bytes; checks
  must read the source, not merely compare two derived assertions. France's new failed
  check and retired totals remain visible. D11 describes actual padded requests rather
  than an imagined same-end-date comparison. Do not preserve an unsupported statement
  because the research tests happen to pass.
- Publish a readable before/after coverage account and machine-readable accounting,
  distinguishing selectable pairs, positive evidence, unknown reasons, acquisition
  dates and actual retrieval limitations. Feed accurate results to #18/#91 and release
  verification under #9 without taking over their separate documentation-site scope.
- Reconcile and publish accepted research through normal review; satisfy #225's
  research-acceptance and merged-input requirements before claiming complete delivery.
  Neither an open research PR nor this local draft counts as accepted, merged delivery.

## Explicit exclusions and handoff state

No additional providers, Brazil/South Africa retrieval, live station-discovery API,
provider-key migration, population expansion, exhaustive historical probing, local
aggregation, inferred source facts or relaxed recording/origin checks. No new original-
producer enquiry is a prerequisite under the approved official-publication scope.
Normal future user requests are not restricted to the research windows; preserve
existing requested-window behaviour and report actual source limits honestly.

This document records the completed discussion and verification, not implementation.
The working tree had no production changes at authoring, the research PRs were open,
and the Effort's `Vision:` line was still `pending`. This is the sole new local vision
for #225; do not create a competing vision for the same outcome.

The repository ignores new `planning/*` files. This vision is explicitly tracked as
an exception; do not change the ignore policy or stage unrelated planning material.

Before substantive work, `implement-vision` must publish and verify this vision
through the appropriate Effort-linked workflow, including its matching Program/Effort
provenance, durable commit-pinned linkage and exact target-branch copy. Do not describe
it as durable or implementation-ready until those publication checks succeed. This
invocation does not start implementation or merge any PR.
