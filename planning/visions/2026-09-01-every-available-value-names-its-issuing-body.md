# Every available value names its issuing body

Program: https://github.com/RivRetrieve/RivRetrieve/issues/6
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/51

## Outcome

RivRetrieve makes a value available only when it can state from its own records how it obtained that value: what was obtained, from where, and when. Provenance identifies every issuing body responsible for each fact or coherent group of facts, so a user can trace and credit a value without assuming that every field under one provider came from that provider.

This is an acquisition-provenance rule, not a legal judgement. For public sources, RivRetrieve records a source's exact words about use, terms, and citation. For private evidence, it checks the exact words locally and publishes only a redacted verification binding and digest together with the evidence limitation. It does not classify licences, decide whether rights are sufficient, or silently publish such a decision through what it includes or removes.

## Why this is needed

The current catalogue origin gate proves that a canonical value matches a declared native column or documented statement. It does not identify who issued the native material or how RivRetrieve acquired it. Poland exposed the gap: one row combines IMGW material with station metadata issued by the Global Runoff Data Centre (GRDC). The current singular provider-level `license` and `citation` fields cannot say which body governs which facts and can direct a user to credit the wrong body.

The rule is hard and has no transition period. If acquisition provenance for a value is not established, the next release does not make that value available. The catalogue must distinguish “withheld because unsourced” from “the publisher supplied no value.” The evidence remains available for later restoration; the value is not erased from repository history.

## Completed inputs that must not be repeated

The completed source survey is preserved at research commit [`3aae548b724cd8ce2887bc3ff9e52130428e970d`](https://github.com/RivRetrieve/RivRetrieve/tree/3aae548b724cd8ce2887bc3ff9e52130428e970d/research/source-terms). Its [`HANDOFF.md`](https://github.com/RivRetrieve/RivRetrieve/blob/3aae548b724cd8ce2887bc3ff9e52130428e970d/research/source-terms/HANDOFF.md), [`STATUS.md`](https://github.com/RivRetrieve/RivRetrieve/blob/3aae548b724cd8ce2887bc3ff9e52130428e970d/research/source-terms/STATUS.md), brief, recorder, checker, thirteen findings and recordings, and the Japan and Poland trails are implementation inputs. Provider research PRs #175–#187 are all merged into that research branch, and its checker reports 13/13.

The survey established source terms for ten of the original thirteen providers and recorded that no statement was found on the examined Bosnia, Thailand, and South Africa surfaces as of the recording dates. Encoding detection and PDF quotation checking were repaired during that work. Japan's current native table is already traced to MLIT's per-station register; the inherited historical file was a GSIM extract and is not used.

ADRs 0026 and 0027 on the research branch express the provenance gate and the decision that native tables do not ship. They are proposed records to reconcile with current repository authority, not instructions to copy stale consequences unchanged.

## Established GRDC evidence

The existing redacted provenance record establishes that GRDC/BfG sent Polish station metadata for inclusion. The only available private message evidence is a forwarded outer file of 228,628 bytes with SHA-256 `6ffc840e3a371cc7731fdd587e3d3a3918e47aa73c0e7e1c1251e54494054742`. It contains no embedded `message/rfc822` original. Its decoded `text/plain` and `text/html` parts each mechanically contain the required redacted excerpt exactly once. Its attached `Metadata_GRDC_30.10.2025.xlsx` is 116,301 bytes with SHA-256 `dfab6ea7de80fb1570f4a8dded8743ed7c7dcb4eb67fe75e2c0e02e9b964b7bf`, exactly matching the workbook used in the research trail.

The source record must identify the issuing body as the Global Runoff Data Centre, operated by the Bundesanstalt für Gewässerkunde. The message states no citation instruction, so citation remains absent rather than being invented.

Original `.eml` byte identity remains unestablished and must never be claimed. By operator authority, the forwarded evidence is sufficient to verify the redacted excerpt and the attachment. The public repository must retain only the redacted record and must never expose the excerpt, personal names, message headers, addresses, subject, receipt timestamp, or correspondence.

## Poland reconciliation constraint

Do not carry forward the research handoff's statement that Poland's `2025-10-10T18:46:34Z` value is “provably false” or automatically replace it with the workbook receipt time.

Current authoritative `AGENTS.md` records the committed table as a recovered historical import byte-identical to an upstream materialization at commit `f67f6d8507a55144bf235feb3f27f65648b90f83`, treats that commit time as a defensible provenance lower bound, and says the later GRDC workbook corroborates recovery but is not established as the exact historical delivery that produced the recovered file. The implementation must reconcile the meanings of acquisition time, recovered-material lower bound, and later corroborating receipt without making one timestamp assert a fact it does not establish.

This constraint does not reopen GRDC's issuing-body identity or the workbook's verified content relationship.

## Current product baseline

- `native.parquet` is already excluded from wheels. Preserve this as a regression invariant; do not claim a new wheel-size reduction.
- Observation provenance currently carries one nullable provider-level `license` and one nullable provider-level `citation`.
- Missing licence and citation already remain absent and produce informational provenance issues.
- The origin gate currently supports `Field`, `NotPublished`, and `Documented`. It lacks an unsourced form, acquisition-record enforcement, and issuing-body identity.
- Eleven providers have committed native tables and origin declarations with detailed acquisition attestations.
- `br_ana` and `no_nve` are deliberately outside that certification. Effort #90 owns the credentialed acquisition process needed for them to earn the same guarantees. This Effort must not implement #90, but its hard gate cannot treat uncertified values as proven merely because they already exist in a packaged catalogue.
- Observation results use the settled five-column data frame. Provenance must not be duplicated into every observation row.

## User-visible behavior

Normal discovery and retrieval remain recognizable:

```python
selection = rr.find(
    provider="pl_imgw",
    station="149180010",
    product="discharge_daily_mean",
)
result = rr.fetch(selection, start="2024-01-01", end="2024-01-31")
```

The exact type and attribute names are reversible design choices, but the public data must allow the user to observe all of the following:

- separate source records for IMGW and GRDC;
- the facts or coherent fact groups to which each source record applies;
- each body's acquisition record and established citation, if any; public-source records expose the exact source statement, while private-evidence records expose a redacted verification binding and digest together with the evidence limitation, with the exact words checked locally but not published;
- GRDC attached to the applicable Polish coordinates and station metadata, never IMGW by inheritance;
- IMGW attached to facts it issued;
- a named withheld fact and reason when acquisition provenance is missing;
- the repository location, revision, and digest of the native table used to build the installed catalogue.

A source record should be stored once and associated with the facts it covers. The vision does not require large provenance objects in every cell or additional provenance columns in every observation row. It also does not prescribe a new top-level public function.

## Evidence of success

The delivered system must make these outcomes externally observable:

1. **Correct mixed-source credit.** Inspecting a Polish selection or result identifies GRDC as issuer for the applicable station metadata and IMGW for IMGW-issued facts. No singular provider-level citation can misattribute the GRDC fields.
2. **Hard unsourced gate.** A deliberately unsubstantiated value is unavailable in the built catalogue, while structured provenance names the withheld fact and states that no acquisition record was established. There is no grace-period mode.
3. **Absence is not conflated.** A source-published null, a source statement that it publishes no value, and a value withheld as unsourced remain distinguishable.
4. **Native-table identity travels.** An installed catalogue exposes the source table's repository path, pinned revision, and digest. The identity resolves to the exact committed table.
5. **Substitution is refused.** Changing one byte of the identified table causes verification to fail with the expected and observed digests, rather than building from it.
6. **The wheel remains clean.** No `native.parquet` occurs in a built wheel.
7. **Source words are verified.** A finding whose quotation is absent from its recorded bytes is rejected by name, including non-UTF-8 HTML and PDF sources. For the private GRDC evidence, local verification binds the forwarded outer-file digest, confirms the required redacted excerpt once in each decoded text part, and binds the attached workbook digest; the public record exposes only the redacted verification binding, digest, and evidence limitation, without claiming original `.eml` byte identity or publishing the exact words or private correspondence.
8. **Unestablished terms do not block retrieval.** Where no licence or citation statement was found, the field remains absent and the existing informational issue behavior remains truthful. Missing terms do not by themselves make a traced value unsourced.
9. **The result data shape remains stable.** Observation data retains the settled five columns; the richer provenance is carried outside the numerical frame.

## Boundaries

This Effort does not:

- interpret, classify, or summarize a licence;
- remove a provider because RivRetrieve considers its terms restrictive;
- repeat the completed thirteen-provider survey;
- wait for Bosnia, Thailand, or South Africa to reply;
- publish private correspondence or personal contact details;
- infer a citation that GRDC did not state;
- replace Poland's provenance lower-bound timestamp without resolving the recovered-import semantics;
- implement the credentialed native-table acquisition outcome owned by #90;
- redesign the five-column observation data frame; or
- begin provider porting, release, or documentation work owned by other Program Efforts.

Later replies from Bosnia, Thailand, and South Africa belong in a separate Program Effort. That follow-up is not a blocker for this vision and must be charted through the Program workflow rather than created as an implementation task here.

## Delivery caution

The research branch contains valuable completed evidence alongside statements superseded by later authoritative repository records. Implementation must preserve the recordings and trails, reconcile conflicts explicitly, and avoid merging the branch wholesale as if every conclusion remained current. The final repository decisions and tests must agree with `AGENTS.md` and the verified evidence described above.
