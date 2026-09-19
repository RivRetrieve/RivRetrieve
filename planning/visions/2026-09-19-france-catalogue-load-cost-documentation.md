# France catalogue load-cost documentation

Related issue: https://github.com/RivRetrieve/RivRetrieve/issues/273

## Outcome

Make the France provider note describe today's catalogue representation without
presenting historical large metadata files and process measurements as current
software behavior. This is a narrow software-documentation correction, not a
provider research or performance project.

## Required correction

Update the **Catalogue load cost** section of `docs/provider_ports/fr_hubeau.md`.
Explain the current compact representation: a Croissant descriptor, a provenance
header, and five typed Parquet evidence relations. At inspected `main` commit
`54b32fe`, `croissant.json` is 42,905 bytes and `provenance.json` is 9,824 bytes.
The header alone is not the complete provenance footprint. Verify any sizes used
in the final text against the implementation checkout and identify their scope.

The previous descriptor/provenance sizes of 102,402,010 and 55,085,081 bytes,
9,468,867-byte compressed wheel, and process memory/timing observations belong to
the superseded representation. They were historical observations, not fabricated
measurements. Do not present them as current costs. Keep historical measurement
detail in `docs/provider_ports/evidenced_coverage.md` and link to that account
rather than repeat the numerical history in the France note. Migration probes in
that account are also historical, environment-specific observations, not current
benchmarks or performance guarantees.

Preserve the relevant current behavior: provider registration loads and validates
the complete manifest before registration. France catalogue validation is not
limited to France selections. The inspected implementation is
`register_manifest` in `src/rivretrieve/_internal/providers/registration.py`.
Do not imply that this behavior disappeared with the representation migration,
or infer measured runtime or memory improvements from smaller file sizes.

Remove the obsolete release-verification-risk framing tied to #9. Write a short,
reader-oriented explanation of current behavior, with ordinary links for history
and representation details. Do not recount the internal investigation.

## Boundaries

Only the France note's catalogue-cost explanation needs correction. Leave unrelated
France documentation, source claims, coverage accounting, and historical evidence
unchanged. No software, API, loader, serialization, catalogue artifact, or data
changes are authorized. Do not add benchmarks, new timing/RSS claims, performance
budgets, or hosted CI. The existing coverage account and `docs/catalogue-evidence.md`
provide context; this work does not require rewriting them.

## Acceptance

A reader can distinguish the current descriptor/header/relations from the former
expanded representation and can follow the historical-account link. No old size,
wheel, memory, timing, or release-risk claim remains framed as current. The text
neither equates the small header with all provenance nor claims that cross-provider
loading has ended. Every current factual statement is checked against the code
and packaged artifacts on the implementation base. Review the documentation diff
and validate its links; no new performance measurement is required.

This vision is standalone. Issue #273 is the related documentation report, not a
Program Effort. Publishing this vision does not implement the correction or close
the issue.
